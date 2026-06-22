from kivy.app import App
from kivy.uix.widget import Widget
from kivy.graphics import Color, Line, Rectangle, Triangle, Ellipse, RoundedRectangle
from kivy.core.window import Window
from kivy.core.text import Label as CoreLabel
from kivy.clock import Clock

import sounddevice as sd
import numpy as np
from collections import deque
from threading import Lock
import time

from tuner_pro import detectar_frequencia, encontrar_nota, notas

# =========================
# BWRLD TUNER - VISUAL V2
# =========================
FS = 44100
BLOCKSIZE = 4096
CHANNELS = 1
DEVICE_ID = None  # None usa a entrada padrao. Ex: DEVICE_ID = 3 para Focusrite fixa

MIN_FREQ = 60
MAX_FREQ = 500
RMS_TRIGGER = 0.006
CLARITY_TRIGGER = 0.18
HISTORY_SIZE = 7

Window.clearcolor = (0.012, 0.012, 0.018, 1)
Window.minimum_width = 820
Window.minimum_height = 560

CORDA_MAP = {
    "E2": "6a CORDA",
    "A2": "5a CORDA",
    "D3": "4a CORDA",
    "G3": "3a CORDA",
    "B3": "2a CORDA",
    "E4": "1a CORDA",
}


def cents_between(freq, target):
    if freq <= 0 or target <= 0:
        return 0.0
    return 1200.0 * np.log2(freq / target)


def hz_at_cents(target, cents):
    return target * (2 ** (cents / 1200.0))


def lerp(a, b, t):
    return a + (b - a) * t


def mix_color(c1, c2, t):
    t = max(0.0, min(1.0, t))
    return tuple(lerp(c1[i], c2[i], t) for i in range(4))


def color_for_cents(cents, active=True):
    if not active:
        return (0.48, 0.50, 0.58, 1)

    a = abs(cents)
    green = (0.10, 1.00, 0.38, 1)
    yellow = (1.00, 0.78, 0.12, 1)
    orange = (1.00, 0.42, 0.10, 1)
    red = (1.00, 0.12, 0.16, 1)

    if a <= 4:
        return green
    if a <= 14:
        return mix_color(green, yellow, (a - 4) / 10)
    if a <= 28:
        return mix_color(yellow, orange, (a - 14) / 14)
    return mix_color(orange, red, min((a - 28) / 22, 1))


class BwrldTunerUI(Widget):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.note = "---"
        self.string_name = ""
        self.freq = 0.0
        self.target = 0.0
        self.cents = 0.0
        self.pointer_cents = 0.0
        self.status = "TOQUE UMA CORDA"
        self.rms = 0.0
        self.clarity = 0.0
        self.active = False
        self.last_active_time = 0

        Clock.schedule_interval(self.draw, 1 / 60)

    def set_data(self, note, freq, target, cents, status, rms, clarity, active=True):
        self.note = note
        self.string_name = CORDA_MAP.get(note, "")
        self.freq = float(freq)
        self.target = float(target)
        self.cents = float(np.clip(cents, -50, 50))
        self.status = status
        self.rms = float(rms)
        self.clarity = float(clarity)
        self.active = active
        if active:
            self.last_active_time = time.time()

    def set_idle(self, rms=0.0, clarity=0.0):
        self.note = "---"
        self.string_name = ""
        self.freq = 0.0
        self.target = 0.0
        self.cents = 0.0
        self.status = "TOQUE UMA CORDA"
        self.rms = float(rms)
        self.clarity = float(clarity)
        self.active = False

    def _text(self, text, x, y, size=20, color=(1, 1, 1, 1), bold=False, align="center"):
        label = CoreLabel(text=text, font_size=size, bold=bold)
        label.refresh()
        texture = label.texture
        tw, th = texture.size

        if align == "center":
            px = x - tw / 2
        elif align == "right":
            px = x - tw
        else:
            px = x

        with self.canvas:
            Color(*color)
            Rectangle(texture=texture, pos=(px, y), size=texture.size)

    def _rounded_rect(self, x, y, w, h, color, radius=14):
        with self.canvas:
            Color(*color)
            RoundedRectangle(pos=(x, y), size=(w, h), radius=[radius])

    def _line(self, points, color, width=1):
        with self.canvas:
            Color(*color)
            Line(points=points, width=width)

    def _draw_background(self, w, h):
        with self.canvas:
            Color(0.012, 0.012, 0.018, 1)
            Rectangle(pos=(0, 0), size=(w, h))

            # leve vinheta central
            Color(0.025, 0.025, 0.040, 0.70)
            Ellipse(pos=(w * 0.18, h * 0.10), size=(w * 0.64, h * 0.88))

    def _draw_header(self, w, h):
        self._text("BWRLD TUNER", w / 2, h - 72, 22, (0.82, 0.82, 0.90, 1), bold=True)
        self._text("GUITARRA STANDARD  E A D G B E", w / 2, h - 101, 13, (0.42, 0.44, 0.52, 1), bold=True)
        self._text(f"RMS {self.rms:.4f}   CL {self.clarity:.2f}", 24, h - 36, 14, (0.44, 0.46, 0.54, 1), align="left")

    def _draw_main_note(self, w, h, main_color):
        cx = w / 2
        note_y = h * 0.655

        # glow simples atras da nota
        if self.active:
            with self.canvas:
                Color(main_color[0], main_color[1], main_color[2], 0.10)
                Ellipse(pos=(cx - 112, note_y - 20), size=(224, 118))

        self._text(self.note, cx, note_y, 82, main_color if self.active else (0.62, 0.64, 0.72, 1), bold=True)

        if self.active:
            self._text(self.string_name, cx, note_y - 30, 15, (0.64, 0.66, 0.76, 1), bold=True)
            self._text(f"{self.freq:.2f} Hz", cx, note_y - 70, 30, (0.96, 0.96, 1.00, 1), bold=False)
            self._text(f"{self.cents:+.1f} cents", cx, note_y - 106, 23, main_color, bold=True)

            # status pill
            pill_w = min(max(len(self.status) * 11.5, 210), 360)
            pill_h = 38
            self._rounded_rect(cx - pill_w / 2, note_y - 158, pill_w, pill_h, (main_color[0], main_color[1], main_color[2], 0.13), radius=18)
            self._text(self.status, cx, note_y - 149, 18, main_color, bold=True)
        else:
            self._text("Aguardando sinal limpo...", cx, note_y - 58, 25, (0.72, 0.73, 0.80, 1))
            self._text("toque uma corda por vez", cx, note_y - 92, 15, (0.45, 0.47, 0.55, 1), bold=True)

    def _draw_gauge(self, w, h, main_color):
        cx = w / 2
        gauge_y = h * 0.335
        gauge_len = min(w * 0.80, 820)
        left = cx - gauge_len / 2
        right = cx + gauge_len / 2

        # zonas de cor discretas atras da linha
        with self.canvas:
            Color(1.0, 0.12, 0.16, 0.10)
            Rectangle(pos=(left, gauge_y - 8), size=(gauge_len * 0.22, 16))
            Rectangle(pos=(right - gauge_len * 0.22, gauge_y - 8), size=(gauge_len * 0.22, 16))
            Color(1.0, 0.78, 0.12, 0.10)
            Rectangle(pos=(left + gauge_len * 0.22, gauge_y - 8), size=(gauge_len * 0.18, 16))
            Rectangle(pos=(right - gauge_len * 0.40, gauge_y - 8), size=(gauge_len * 0.18, 16))
            Color(0.10, 1.0, 0.38, 0.14)
            Rectangle(pos=(cx - gauge_len * 0.10, gauge_y - 9), size=(gauge_len * 0.20, 18))

        # linha base
        self._line([left, gauge_y, right, gauge_y], (0.28, 0.29, 0.36, 1), 2)

        # ticks
        for c in range(-50, 51, 5):
            x = cx + (c / 50.0) * (gauge_len / 2)
            major = c % 25 == 0
            medium = c % 10 == 0

            if c == 0:
                tick_color = (0.10, 1.0, 0.38, 1)
                tick_h = 60
                width = 3
            elif major:
                tick_color = (0.56, 0.57, 0.66, 1)
                tick_h = 45
                width = 2
            elif medium:
                tick_color = (0.38, 0.39, 0.47, 1)
                tick_h = 30
                width = 1.35
            else:
                tick_color = (0.25, 0.26, 0.32, 1)
                tick_h = 18
                width = 1

            self._line([x, gauge_y - tick_h / 2, x, gauge_y + tick_h / 2], tick_color, width)

        # labels da escala
        self._text("-50c", left, gauge_y - 58, 16, (0.62, 0.63, 0.72, 1))
        self._text("-25", cx - gauge_len * 0.25, gauge_y - 47, 12, (0.42, 0.43, 0.52, 1))
        self._text("0", cx, gauge_y - 66, 17, (0.10, 1.0, 0.38, 1), bold=True)
        self._text("+25", cx + gauge_len * 0.25, gauge_y - 47, 12, (0.42, 0.43, 0.52, 1))
        self._text("+50c", right, gauge_y - 58, 16, (0.62, 0.63, 0.72, 1))

        # ponteiro suavizado
        target_pointer = self.cents if self.active else 0.0
        self.pointer_cents += (target_pointer - self.pointer_cents) * 0.16
        pointer_x = cx + (np.clip(self.pointer_cents, -50, 50) / 50.0) * (gauge_len / 2)

        # glow do ponteiro
        with self.canvas:
            Color(main_color[0], main_color[1], main_color[2], 0.18)
            Line(points=[pointer_x, gauge_y - 95, pointer_x, gauge_y + 95], width=10)
            Color(main_color[0], main_color[1], main_color[2], 0.95)
            Line(points=[pointer_x, gauge_y - 90, pointer_x, gauge_y + 92], width=4)
            Triangle(points=[pointer_x - 14, gauge_y + 108, pointer_x + 14, gauge_y + 108, pointer_x, gauge_y + 132])
            Ellipse(pos=(pointer_x - 7, gauge_y - 7), size=(14, 14))

    def _draw_bottom_hz(self, w, h, main_color):
        if self.active and self.target > 0:
            left_hz = hz_at_cents(self.target, -50)
            right_hz = hz_at_cents(self.target, 50)
            self._text(f"{left_hz:.2f} Hz", 34, 30, 18, (0.70, 0.71, 0.80, 1), align="left")
            self._text(f"alvo {self.target:.2f} Hz", w / 2, 30, 18, (0.10, 1.0, 0.38, 1), bold=True)
            self._text(f"{right_hz:.2f} Hz", w - 34, 30, 18, (0.70, 0.71, 0.80, 1), align="right")
        else:
            self._text("baixo", 34, 30, 18, (0.48, 0.49, 0.56, 1), align="left")
            self._text("centro = afinado", w / 2, 30, 18, (0.48, 0.49, 0.56, 1), bold=True)
            self._text("alto", w - 34, 30, 18, (0.48, 0.49, 0.56, 1), align="right")

    def draw(self, dt):
        self.canvas.clear()
        w, h = self.width, self.height
        if w <= 10 or h <= 10:
            return

        main_color = color_for_cents(self.cents, self.active)
        self._draw_background(w, h)
        self._draw_header(w, h)
        self._draw_main_note(w, h, main_color)
        self._draw_gauge(w, h, main_color)
        self._draw_bottom_hz(w, h, main_color)


class BwrldTunerApp(App):
    def build(self):
        self.title = "BWRLD Tuner"
        self.ui = BwrldTunerUI()

        self.lock = Lock()
        self.pending = None
        self.last_signal_time = 0
        self.freq_history = deque(maxlen=HISTORY_SIZE)
        self.cents_history = deque(maxlen=HISTORY_SIZE)

        self.start_audio()
        Clock.schedule_interval(self.apply_audio_data, 1 / 45)
        return self.ui

    def start_audio(self):
        def callback(indata, frames, time_info, status):
            audio = indata[:, 0].copy()

            freq, rms, clarity = detectar_frequencia(
                audio,
                fs=FS,
                min_freq=MIN_FREQ,
                max_freq=MAX_FREQ,
                rms_threshold=RMS_TRIGGER,
                clarity_threshold=CLARITY_TRIGGER,
            )

            if freq is None:
                with self.lock:
                    self.pending = {"active": False, "rms": rms, "clarity": clarity}
                return

            note, target = encontrar_nota(freq)
            cents = cents_between(freq, target)

            # filtro de seguranca contra harmonicos ou saltos absurdos
            if abs(cents) > 85:
                with self.lock:
                    self.pending = {"active": False, "rms": rms, "clarity": clarity}
                return

            self.freq_history.append(freq)
            self.cents_history.append(cents)

            smooth_freq = float(np.median(self.freq_history))
            smooth_cents = float(np.median(self.cents_history))
            smooth_note, smooth_target = encontrar_nota(smooth_freq)

            if abs(smooth_cents) <= 4:
                status_txt = "AFINADO"
            elif smooth_cents < 0:
                status_txt = "BAIXO - aperte a corda"
            else:
                status_txt = "ALTO - afrouxe a corda"

            with self.lock:
                self.pending = {
                    "active": True,
                    "note": smooth_note,
                    "freq": smooth_freq,
                    "target": smooth_target,
                    "cents": smooth_cents,
                    "status": status_txt,
                    "rms": rms,
                    "clarity": clarity,
                }
                self.last_signal_time = time.time()

        self.stream = sd.InputStream(
            device=DEVICE_ID,
            channels=CHANNELS,
            samplerate=FS,
            blocksize=BLOCKSIZE,
            callback=callback,
        )
        self.stream.start()

    def apply_audio_data(self, dt):
        with self.lock:
            data = self.pending
            self.pending = None
            last_signal = self.last_signal_time

        if data is None:
            if time.time() - last_signal > 0.75:
                self.ui.set_idle()
            return

        if not data.get("active"):
            if time.time() - last_signal > 0.75:
                self.freq_history.clear()
                self.cents_history.clear()
                self.ui.set_idle(data.get("rms", 0.0), data.get("clarity", 0.0))
            return

        self.ui.set_data(
            data["note"],
            data["freq"],
            data["target"],
            data["cents"],
            data["status"],
            data["rms"],
            data["clarity"],
            active=True,
        )

    def on_stop(self):
        if hasattr(self, "stream"):
            self.stream.stop()
            self.stream.close()


if __name__ == "__main__":
    BwrldTunerApp().run()
