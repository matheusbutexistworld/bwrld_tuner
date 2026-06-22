from kivy.app import App
from kivy.uix.widget import Widget
from kivy.graphics import Color, Line, Rectangle, Triangle
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
# CONFIGURACOES PRINCIPAIS
# =========================
FS = 44100
BLOCKSIZE = 4096          # 4096 = mais rapido | 8192 = mais estavel
CHANNELS = 1
DEVICE_ID = None          # None usa a entrada padrao do Windows. Ex: DEVICE_ID = 3 para Focusrite

MIN_FREQ = 60             # guitarra: E2 ~82 Hz. Baixo 4 cordas precisaria ~35/40 Hz
MAX_FREQ = 500
RMS_TRIGGER = 0.006       # aumente se captar ruido; diminua se nao captar corda fraca
CLARITY_TRIGGER = 0.18    # qualidade minima do pico da autocorrelacao
HISTORY_SIZE = 7          # suavizacao anti-tremedeira

Window.clearcolor = (0.02, 0.02, 0.025, 1)


def cents_between(freq, target):
    """Calcula desvio musical real em cents."""
    if freq <= 0 or target <= 0:
        return 0.0
    return 1200.0 * np.log2(freq / target)


def hz_at_cents(target, cents):
    """Converte alvo + cents para Hz."""
    return target * (2 ** (cents / 1200.0))


class TunerGauge(Widget):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        self.note = "---"
        self.freq = 0.0
        self.target = 0.0
        self.cents = 0.0
        self.pointer_cents = 0.0
        self.status = "TOQUE UMA CORDA"
        self.rms = 0.0
        self.clarity = 0.0
        self.active = False

        Clock.schedule_interval(self.draw, 1 / 30)

    def set_data(self, note, freq, target, cents, status, rms, clarity, active=True):
        self.note = note
        self.freq = freq
        self.target = target
        self.cents = float(np.clip(cents, -50, 50))
        self.status = status
        self.rms = rms
        self.clarity = clarity
        self.active = active

    def set_idle(self, rms=0.0, clarity=0.0):
        self.note = "---"
        self.freq = 0.0
        self.target = 0.0
        self.cents = 0.0
        self.status = "TOQUE UMA CORDA"
        self.rms = rms
        self.clarity = clarity
        self.active = False

    def _draw_text(self, text, x, y, size=20, color=(1, 1, 1, 1), bold=False, align="center"):
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

    def draw(self, dt):
        self.canvas.clear()

        w, h = self.width, self.height
        cx = w / 2
        gauge_y = h * 0.45
        gauge_len = min(w * 0.78, 760)
        left = cx - gauge_len / 2
        right = cx + gauge_len / 2

        # Movimento suavizado do ponteiro
        self.pointer_cents += (self.cents - self.pointer_cents) * 0.18
        pointer_x = cx + (np.clip(self.pointer_cents, -50, 50) / 50.0) * (gauge_len / 2)

        # Cor principal conforme afinacao
        abs_c = abs(self.cents)
        if not self.active:
            main_color = (0.65, 0.65, 0.70, 1)
        elif abs_c <= 4:
            main_color = (0.15, 1.0, 0.35, 1)      # verde
        elif abs_c <= 15:
            main_color = (1.0, 0.75, 0.15, 1)      # amarelo
        else:
            main_color = (1.0, 0.18, 0.18, 1)      # vermelho

        with self.canvas:
            # Fundo
            Color(0.02, 0.02, 0.025, 1)
            Rectangle(pos=(0, 0), size=(w, h))

            # Linha base do medidor
            Color(0.22, 0.22, 0.26, 1)
            Line(points=[left, gauge_y, right, gauge_y], width=2)

            # Ticks do medidor: -50 a +50 cents
            for c in range(-50, 51, 10):
                x = cx + (c / 50.0) * (gauge_len / 2)
                is_major = c in (-50, -25, 0, 25, 50)
                tick_h = 45 if is_major else 25
                width = 2 if is_major else 1

                if c == 0:
                    Color(0.15, 1.0, 0.35, 1)
                else:
                    Color(0.42, 0.42, 0.48, 1)

                Line(points=[x, gauge_y - tick_h / 2, x, gauge_y + tick_h / 2], width=width)

            # Ponteiro
            Color(*main_color)
            Line(points=[pointer_x, gauge_y - 80, pointer_x, gauge_y + 92], width=4)
            Triangle(points=[pointer_x - 14, gauge_y + 105, pointer_x + 14, gauge_y + 105, pointer_x, gauge_y + 130])

        # Textos principais
        self._draw_text("BWRLD TUNER", cx, h - 70, 20, (0.70, 0.70, 0.76, 1), bold=True)

        note_color = main_color if self.active else (0.75, 0.75, 0.80, 1)
        self._draw_text(self.note, cx, h * 0.68, 76, note_color, bold=True)

        if self.active:
            self._draw_text(f"{self.freq:.2f} Hz", cx, h * 0.68 - 48, 28, (0.95, 0.95, 1, 1))
            self._draw_text(f"{self.cents:+.1f} cents", cx, h * 0.68 - 84, 24, main_color, bold=True)
            self._draw_text(self.status, cx, h * 0.68 - 120, 24, main_color, bold=True)
        else:
            self._draw_text("Aguardando sinal limpo...", cx, h * 0.68 - 55, 25, (0.75, 0.75, 0.80, 1))

        # Numeros dos cantos do medidor
        self._draw_text("-50c", left, gauge_y - 62, 16, (0.65, 0.65, 0.70, 1), align="center")
        self._draw_text("0", cx, gauge_y - 62, 16, (0.15, 1.0, 0.35, 1), align="center")
        self._draw_text("+50c", right, gauge_y - 62, 16, (0.65, 0.65, 0.70, 1), align="center")

        if self.active and self.target > 0:
            left_hz = hz_at_cents(self.target, -50)
            right_hz = hz_at_cents(self.target, 50)
            self._draw_text(f"{left_hz:.2f} Hz", 28, 28, 18, (0.72, 0.72, 0.78, 1), align="left")
            self._draw_text(f"alvo {self.target:.2f} Hz", cx, 28, 18, (0.15, 1.0, 0.35, 1), align="center")
            self._draw_text(f"{right_hz:.2f} Hz", w - 28, 28, 18, (0.72, 0.72, 0.78, 1), align="right")
        else:
            self._draw_text("baixo", 28, 28, 18, (0.55, 0.55, 0.60, 1), align="left")
            self._draw_text("centro = afinado", cx, 28, 18, (0.55, 0.55, 0.60, 1), align="center")
            self._draw_text("alto", w - 28, 28, 18, (0.55, 0.55, 0.60, 1), align="right")

        # Status tecnico discreto
        self._draw_text(f"RMS {self.rms:.4f}  CL {self.clarity:.2f}", 20, h - 35, 14, (0.45, 0.45, 0.50, 1), align="left")


class TunerApp(App):
    def build(self):
        self.title = "BWRLD Tuner"
        self.ui = TunerGauge()

        self.lock = Lock()
        self.pending = None
        self.last_signal_time = 0
        self.freq_history = deque(maxlen=HISTORY_SIZE)
        self.cents_history = deque(maxlen=HISTORY_SIZE)

        self.start_audio()
        Clock.schedule_interval(self.apply_audio_data, 1 / 30)
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

            # Rejeita leituras absurdas para evitar pulo de harmonico/ruido
            if abs(cents) > 80:
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
            if time.time() - last_signal > 0.7:
                self.ui.set_idle()
            return

        if not data.get("active"):
            if time.time() - last_signal > 0.7:
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
    TunerApp().run()
