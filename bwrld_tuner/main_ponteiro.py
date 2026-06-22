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
import math

from tuner_pro import detectar_frequencia, encontrar_nota

# ==========================================
# BWRLD TUNER V5 - EXPERT SYSTEM EDITION
# ==========================================
FS = 44100
BLOCKSIZE = 4096
CHANNELS = 1
DEVICE_ID = None  # None uses the default system input

MAX_FREQ = 500
RMS_TRIGGER = 0.006
CLARITY_TRIGGER = 0.18
HISTORY_SIZE = 7

# Set window size and dark theme background color
Window.clearcolor = (0.035, 0.039, 0.047, 1.0)  # Deep Charcoal #090a0f
Window.minimum_width = 820
Window.minimum_height = 560

CORDA_MAP = {
    "E1": "4ª CORDA",
    "A1": "3ª CORDA",
    "D2": "2ª CORDA",
    "G2": "1ª CORDA",
    "E2": "6ª CORDA",
    "A2": "5ª CORDA",
    "D3": "4ª CORDA",
    "G3": "3ª CORDA",
    "B3": "2ª CORDA",
    "E4": "1ª CORDA",
}

# Dynamic string arrays for instrument/tuning presets
GUITAR_STRINGS = [
    ("E4", "1ª CORDA", 329.63),
    ("B3", "2ª CORDA", 246.94),
    ("G3", "3ª CORDA", 196.00),
    ("D3", "4ª CORDA", 146.83),
    ("A2", "5ª CORDA", 110.00),
    ("E2", "6ª CORDA", 82.41),
]

# Custom Frequency Matchers to avoid editing tuner_pro.py
A4 = 440.0
NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]

def encontrar_nota_cromatica(freq):
    """Finds the closest note in the standard 12-tone equal temperament scale."""
    if freq <= 0:
        return "---", 0.0
    midi_num = round(12 * np.log2(freq / 440.0) + 69)
    target_freq = 440.0 * (2.0 ** ((midi_num - 69) / 12.0))
    octave = (midi_num // 12) - 1
    note_name = NOTE_NAMES[midi_num % 12] + str(octave)
    return note_name, target_freq

def encontrar_nota_guitar(freq):
    guitar_notes = {
        "E2": 82.41, "A2": 110.00, "D3": 146.83,
        "G3": 196.00, "B3": 246.94, "E4": 329.63
    }
    nota = min(guitar_notes, key=lambda n: abs(freq - guitar_notes[n]))
    return nota, guitar_notes[nota]

def encontrar_nota_drop_d(freq):
    drop_notes = {
        "D2": 73.42, "A2": 110.00, "D3": 146.83,
        "G3": 196.00, "B3": 246.94, "E4": 329.63
    }
    nota = min(drop_notes, key=lambda n: abs(freq - drop_notes[n]))
    return nota, drop_notes[nota]

def encontrar_nota_bass(freq):
    bass_notes = {
        "E1": 41.20, "A1": 55.00, "D2": 73.42, "G2": 98.00
    }
    nota = min(bass_notes, key=lambda n: abs(freq - bass_notes[n]))
    return nota, bass_notes[nota]

def cents_between(freq, target):
    if freq <= 0 or target <= 0:
        return 0.0
    return 1200.0 * np.log2(freq / target)

def lerp(a, b, t):
    return a + (b - a) * t

def mix_color(c1, c2, t):
    t = max(0.0, min(1.0, t))
    return tuple(lerp(c1[i], c2[i], t) for i in range(4))

def color_for_cents(cents, active=True):
    if not active:
        return (0.35, 0.38, 0.46, 1.0)  # Dim steel blue for inactive

    a = abs(cents)
    # Futuristic Neon Color Palette
    green = (0.00, 1.00, 0.40, 1.0)  # Neon Green #00FF66 (tuned)
    amber = (1.00, 0.65, 0.00, 1.0)  # Neon Amber #FFA600 (slightly flat/sharp)
    red = (1.00, 0.20, 0.25, 1.0)    # Neon Red #FF333F (far out of tune)

    if a <= 4:
        return green
    if a <= 15:
        return mix_color(green, amber, (a - 4) / 11)
    if a <= 30:
        return mix_color(amber, red, (a - 15) / 15)
    return red

def angle_for_cents(cents):
    """Maps -50..+50 cents to a flat dashboard arc: 140°..40°."""
    cents = float(np.clip(cents, -50, 50))
    return 90.0 - (cents / 50.0) * 50.0

def polar(cx, cy, radius, angle_deg):
    rad = math.radians(angle_deg)
    return cx + math.cos(rad) * radius, cy + math.sin(rad) * radius

def arc_points(cx, cy, radius, start_deg, end_deg, steps=48):
    """Generates continuous coordinate points to render Kivy Line arcs."""
    pts = []
    for i in range(steps + 1):
        t = i / steps
        ang = start_deg + (end_deg - start_deg) * t
        x, y = polar(cx, cy, radius, ang)
        pts.extend([x, y])
    return pts

class BwrldTunerUI(Widget):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.note = "---"
        self.string_name = ""
        self.freq = 0.0
        self.target = 0.0
        self.cents = 0.0
        self.needle_cents = 0.0
        self.status = "STANDBY"
        self.rms = 0.0
        self.clarity = 0.0
        self.active = False

        # Tuning mode state
        self.tuner_mode = "CHROMATIC"  # Active: CHROMATIC, GUITAR, DROP D, BASS, MANUAL
        self.base_mode = "CHROMATIC"   # Fallback from manual lock: CHROMATIC, GUITAR, DROP D, BASS
        self.selected_preset = None

        # Flag: request history flush on mode/preset change (read by App.apply_audio_data)
        self.needs_history_reset = False

        # Text rendering texture cache
        self.text_cache = {}

        Clock.schedule_interval(self.draw, 1 / 60)

    def set_data(self, note, freq, target, cents, status, rms, clarity, active=True):
        self.note = note
        self.string_name = CORDA_MAP.get(note, "")
        self.freq = float(freq)
        self.target = float(target)
        # In non-CHROMATIC modes allow up to ±100 cents so the needle shows
        # the full deviation instead of clipping at ±50.
        clip_range = 50 if self.tuner_mode == "CHROMATIC" else 100
        self.cents = float(np.clip(cents, -clip_range, clip_range))
        self.status = status
        self.rms = float(rms)
        self.clarity = float(clarity)
        self.active = active

    def set_idle(self, rms=0.0, clarity=0.0):
        self.note = "---"
        self.string_name = ""
        self.freq = 0.0
        self.target = 0.0
        self.cents = 0.0
        self.status = "STANDBY"
        self.rms = float(rms)
        self.clarity = float(clarity)
        self.active = False

    def get_status_text(self):
        """Dynamic tuner state levels (V5 corrected — covers full ±100c range)."""
        if not self.active:
            return "STANDBY"

        a = abs(self.cents)
        if a <= 3:
            return "PERFECT"
        if a <= 5:
            return "IN TUNE"
        if a <= 12:
            return "SLIGHTLY HIGH" if self.cents > 0 else "SLIGHTLY LOW"
        if a <= 25:
            return "HIGH" if self.cents > 0 else "LOW"
        if a <= 80:
            return "VERY HIGH" if self.cents > 0 else "VERY LOW"
        # Beyond ±80 cents — string is far off, needs aggressive action
        return "DROP A LOT" if self.cents > 0 else "TIGHTEN A LOT"

    def get_active_strings(self):
        """Returns string lists mapped dynamically to active instrument/tuning presets."""
        mode = self.base_mode if self.tuner_mode == "MANUAL" else self.tuner_mode
        if mode == "BASS":
            return [
                ("G2", "1ª CORDA", 98.00),
                ("D2", "2ª CORDA", 73.42),
                ("A1", "3ª CORDA", 55.00),
                ("E1", "4ª CORDA", 41.20),
            ]
        elif mode == "DROP D":
            return [
                ("E4", "1ª CORDA", 329.63),
                ("B3", "2ª CORDA", 246.94),
                ("G3", "3ª CORDA", 196.00),
                ("D3", "4ª CORDA", 146.83),
                ("A2", "5ª CORDA", 110.00),
                ("D2", "6ª CORDA", 73.42),
            ]
        else:  # CHROMATIC or GUITAR
            return [
                ("E4", "1ª CORDA", 329.63),
                ("B3", "2ª CORDA", 246.94),
                ("G3", "3ª CORDA", 196.00),
                ("D3", "4ª CORDA", 146.83),
                ("A2", "5ª CORDA", 110.00),
                ("E2", "6ª CORDA", 82.41),
            ]

    def get_cached_text(self, text, size, bold):
        """Retrieves or creates cached textures for static text elements."""
        key = (text, size, bold)
        if key not in self.text_cache:
            lbl = CoreLabel(text=text, font_size=size, bold=bold)
            lbl.refresh()
            self.text_cache[key] = lbl.texture
        return self.text_cache[key]

    def _text(self, text, x, y, size=14, color=(1, 1, 1, 1), bold=False, align="center", cache=True):
        if cache:
            texture = self.get_cached_text(text, size, bold)
        else:
            lbl = CoreLabel(text=text, font_size=size, bold=bold)
            lbl.refresh()
            texture = lbl.texture

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

    def _rounded_rect(self, x, y, w, h, color, radius=12):
        with self.canvas:
            Color(*color)
            RoundedRectangle(pos=(x, y), size=(w, h), radius=[radius])

    def _line(self, points, color, width=1):
        with self.canvas:
            Color(*color)
            Line(points=points, width=width)

    # ==========================================
    # MODULAR DRAWING METHODS
    # ==========================================
    def draw_background(self, w, h):
        # Subtle dashboard tech grid in background
        grid_color = (0.10, 0.11, 0.15, 0.08)
        grid_step = 40
        for gx in range(0, int(w), grid_step):
            self._line([gx, 0, gx, h], grid_color, 1)
        for gy in range(0, int(h), grid_step):
            self._line([0, gy, w, gy], grid_color, 1)

    def draw_header(self, w, h):
        self._text("BWRLD AUTO-TUNER // TELEMETRY PRO", 24, h - 38, 12, (0.50, 0.54, 0.65, 1.0), bold=True, align="left", cache=True)
        
        # Display LOCKED indicator capsule if manual mode is active
        if self.tuner_mode == "MANUAL" and self.selected_preset:
            self._rounded_rect(265, h - 45, 95, 22, (1.00, 0.65, 0.00, 0.08), 10)
            with self.canvas:
                Color(1.00, 0.65, 0.00, 0.35)
                Line(rounded_rectangle=[265, h - 45, 95, 22, 10], width=1)
            self._text(f"LOCKED: {self.selected_preset}", 312, h - 39, 9, (1.00, 0.65, 0.00, 1.0), bold=True, align="center", cache=False)

        # Mode Selection Bar inside Header (with click zones)
        self._text("MODE:", w - 495, h - 38, 11, (0.45, 0.48, 0.58, 1.0), bold=True, align="left", cache=True)
        
        for idx, mode_name in enumerate(["CHROMATIC", "GUITAR", "DROP D", "BASS"]):
            bx = w - 440 + idx * 102
            by = h - 45
            is_sel = (self.tuner_mode == mode_name or (self.tuner_mode == "MANUAL" and self.base_mode == mode_name))
            
            if is_sel:
                capsule_bg = (0.00, 1.00, 0.40, 0.12)
                capsule_brd = (0.00, 1.00, 0.40, 0.5)
                text_col = (0.00, 1.00, 0.40, 1.0)
            else:
                capsule_bg = (0.06, 0.07, 0.09, 0.3)
                capsule_brd = (0.15, 0.17, 0.22, 0.6)
                text_col = (0.42, 0.46, 0.54, 1.0)

            self._rounded_rect(bx, by, 92, 22, capsule_bg, 11)
            with self.canvas:
                Color(*capsule_brd)
                Line(rounded_rectangle=[bx, by, 92, 22, 11], width=1)
            self._text(mode_name, bx + 46, by + 5, 9, text_col, bold=True, align="center", cache=True)

        self._line([24, h - 50, w - 24, h - 50], (0.15, 0.17, 0.22, 1.0), 1.2)

    def draw_left_panel(self, px_left, py_start, p_height):
        top_y = py_start + p_height
        
        # Panel frame
        panel_bg = (0.07, 0.08, 0.11, 0.65)
        panel_border = (0.15, 0.17, 0.22, 1.0)
        self._rounded_rect(px_left, py_start, 210, p_height, panel_bg, 12)
        with self.canvas:
            Color(*panel_border)
            Line(rounded_rectangle=[px_left, py_start, 210, p_height, 12], width=1.2)

        # Title
        self._text("SYSTEM TELEMETRY", px_left + 16, top_y - 25, 11, (0.45, 0.48, 0.58, 1.0), bold=True, align="left", cache=True)
        self._line([px_left + 16, top_y - 34, px_left + 194, top_y - 34], (0.15, 0.17, 0.22, 1.0), 1)

        bar_h = p_height - 150
        bar_y = py_start + 75

        # Bar 1: RMS Signal Level
        self._text("LEVEL (RMS)", px_left + 16, top_y - 65, 10, (0.45, 0.48, 0.58, 1.0), bold=True, align="left", cache=True)
        self._rounded_rect(px_left + 26, bar_y, 16, bar_h, (0.09, 0.10, 0.13, 1.0), 5)
        rms_val = min(self.rms / 0.035, 1.0)
        fill_h1 = max(bar_h * rms_val, 2)
        fill_col1 = (1.00, 0.62, 0.00, 1.0) if self.active else (0.22, 0.25, 0.32, 1.0)
        self._rounded_rect(px_left + 26, bar_y, 16, fill_h1, fill_col1, 5)

        # Bar 2: Clarity Level
        self._text("CLARITY", px_left + 116, top_y - 65, 10, (0.45, 0.48, 0.58, 1.0), bold=True, align="left", cache=True)
        self._rounded_rect(px_left + 126, bar_y, 16, bar_h, (0.09, 0.10, 0.13, 1.0), 5)
        clar_val = min(max(self.clarity, 0.0), 1.0)
        fill_h2 = max(bar_h * clar_val, 2)
        fill_col2 = (0.00, 1.00, 0.40, 1.0) if self.active else (0.22, 0.25, 0.32, 1.0)
        self._rounded_rect(px_left + 126, bar_y, 16, fill_h2, fill_col2, 5)

        # Stats below bars
        self._text(f"{self.rms:.4f}", px_left + 34, py_start + 48, 12, (0.84, 0.86, 0.92, 1.0), bold=True, align="center", cache=False)
        self._text("RMS", px_left + 34, py_start + 34, 9, (0.45, 0.48, 0.58, 1.0), bold=True, align="center", cache=True)

        self._text(f"{self.clarity:.2f}", px_left + 134, py_start + 48, 12, (0.84, 0.86, 0.92, 1.0), bold=True, align="center", cache=False)
        self._text("CLARITY", px_left + 134, py_start + 34, 9, (0.45, 0.48, 0.58, 1.0), bold=True, align="center", cache=True)

        # Signal status evaluations (LOW, NOISY, OK)
        if self.rms < RMS_TRIGGER:
            sig_status = "SIGNAL: LOW"
            sig_color = (1.00, 0.62, 0.00, 1.0)  # Amber
        elif self.clarity < CLARITY_TRIGGER:
            sig_status = "SIGNAL: NOISY"
            sig_color = (1.00, 0.20, 0.25, 1.0)  # Red
        else:
            sig_status = "SIGNAL: OK"
            sig_color = (0.00, 1.00, 0.40, 1.0)  # Green

        bx = px_left + 26
        by = py_start + 12
        badge_w = 158
        badge_h = 20
        self._rounded_rect(bx, by, badge_w, badge_h, (sig_color[0], sig_color[1], sig_color[2], 0.08), 10)
        with self.canvas:
            Color(*(sig_color[0], sig_color[1], sig_color[2], 0.3))
            Line(rounded_rectangle=[bx, by, badge_w, badge_h, 10], width=1.0)
        self._text(sig_status, px_left + 105, by + 4, 10, sig_color, bold=True, align="center", cache=False)

    def draw_center_panel(self, cx, cy, w_center, p_height, main_color):
        px_left = 24
        py_start = 42
        panel_bg = (0.07, 0.08, 0.11, 0.4)
        panel_border = (0.15, 0.17, 0.22, 1.0)
        self._rounded_rect(px_left + 226, py_start, w_center, p_height, panel_bg, 12)
        with self.canvas:
            Color(*panel_border)
            Line(rounded_rectangle=[px_left + 226, py_start, w_center, p_height, 12], width=1.2)

    def draw_speedometer(self, cx, cy, radius, main_color):
        # 1. Outer Tachometer Scale Frame (140° to 40°)
        scale_color = (0.12, 0.14, 0.19, 1.0)
        self._line(arc_points(cx, cy, radius, 140, 40, steps=64), scale_color, 4)

        # 2. Dynamic Tachometer Fill (0 cents at 90° fills out to current cents)
        if self.active:
            cents_ang = angle_for_cents(self.cents)
            self._line(arc_points(cx, cy, radius, 90.0, cents_ang, steps=32), main_color, 4.5)
            # Soft neon glow behind fill arc
            glow_col = (main_color[0], main_color[1], main_color[2], 0.18)
            self._line(arc_points(cx, cy, radius, 90.0, cents_ang, steps=32), glow_col, 10)

        # 3. Tachometer Scale Ticks (Colored dynamically: green center, yellow near, red extremes)
        for c in range(-50, 51, 5):
            ang = angle_for_cents(c)
            is_major = c % 25 == 0
            is_medium = c % 10 == 0

            tick_len = 14 if is_major else 9 if is_medium else 5
            tick_width = 2.0 if is_major else 1.2 if is_medium else 0.8
            
            # Map tick color zones (automotive sportscar theme)
            a_c = abs(c)
            if a_c <= 5:
                tick_color = (0.00, 1.00, 0.40, 1.0)  # Neon green (tuned zone)
            elif a_c <= 25:
                tick_color = (1.00, 0.65, 0.00, 1.0)  # Neon amber (warn zone)
            else:
                tick_color = (1.00, 0.20, 0.25, 1.0)  # Neon red (limit zone)

            if c == 0:
                tick_len = 18
                tick_width = 2.5

            x1, y1 = polar(cx, cy, radius - tick_len, ang)
            x2, y2 = polar(cx, cy, radius, ang)
            self._line([x1, y1, x2, y2], tick_color, tick_width)

        # 4. Scale Labels
        for c, lbl, f_size in [(-50, "-50c", 10), (-25, "-25", 9), (0, "0", 12), (25, "+25", 9), (50, "+50c", 10)]:
            ang = angle_for_cents(c)
            lx, ly = polar(cx, cy, radius - 28, ang)
            a_c = abs(c)
            if a_c <= 5:
                lbl_color = (0.00, 1.00, 0.40, 1.0)
            elif a_c <= 25:
                lbl_color = (1.00, 0.65, 0.00, 1.0)
            else:
                lbl_color = (1.00, 0.20, 0.25, 1.0)
            self._text(lbl, lx, ly - 5, f_size, lbl_color, bold=(c == 0), cache=True)

        # 5. Elegant Rim Needle (Triangular outer cursor, index needle tick)
        target_needle = self.cents if self.active else 0.0
        self.needle_cents += (target_needle - self.needle_cents) * 0.15
        needle_ang = angle_for_cents(self.needle_cents)

        tx, ty = polar(cx, cy, radius + 2, needle_ang)
        bx1, by1 = polar(cx, cy, radius + 8, needle_ang - 2.2)
        bx2, by2 = polar(cx, cy, radius + 8, needle_ang + 2.2)

        with self.canvas:
            Color(*main_color)
            # Sharp index tick crossing the scale arc line
            x_idx1, y_idx1 = polar(cx, cy, radius - 6, needle_ang)
            x_idx2, y_idx2 = polar(cx, cy, radius + 2, needle_ang)
            Line(points=[x_idx1, y_idx1, x_idx2, y_idx2], width=2.0)
            
            # Cursor triangle sitting exactly over the outer arc
            Triangle(points=[tx, ty, bx1, by1, bx2, by2])
            
            # Subtly darker border line backing
            Color(0.0, 0.0, 0.0, 0.35)
            Line(points=[bx1, by1, bx2, by2], width=1)

    def draw_note_info(self, cx, cy, main_color):
        # 1. Main Note Display
        if self.active:
            # Subtle radial backdrop glow behind active note
            with self.canvas:
                Color(main_color[0], main_color[1], main_color[2], 0.05)
                Ellipse(pos=(cx - 60, cy + 5), size=(120, 100))
            self._text(self.note, cx, cy + 15, 72, main_color, bold=True, cache=False)
        else:
            self._text("---", cx, cy + 15, 70, (0.20, 0.23, 0.30, 1.0), bold=True, cache=True)

        # 2. Frequencies Readout
        if self.active:
            self._text(f"{self.freq:.2f} Hz", cx, cy - 50, 18, (0.92, 0.94, 0.98, 1.0), bold=False, cache=False)
            self._text(f"TARGET: {self.target:.2f} Hz", cx, cy - 72, 11, (0.42, 0.46, 0.55, 1.0), bold=True, cache=False)
        else:
            self._text("WAITING SIGNAL", cx, cy - 50, 12, (0.35, 0.38, 0.46, 1.0), bold=True, cache=True)

        # 3. Cents Deviation
        if self.active:
            sign = "+" if self.cents > 0 else ""
            self._text(f"{sign}{self.cents:.1f} CENTS", cx, cy - 94, 13, main_color, bold=True, cache=False)
        else:
            self._text("NO SOURCE", cx, cy - 94, 11, (0.28, 0.31, 0.38, 1.0), bold=True, cache=True)

        # 4. Status Badge Capsule (Precise V5 levels, no emojis)
        badge_w = 170
        badge_h = 24
        bx = cx - badge_w / 2
        by = cy - 138

        capsule_bg = (main_color[0], main_color[1], main_color[2], 0.08) if self.active else (0.09, 0.10, 0.12, 0.3)
        capsule_border = (main_color[0], main_color[1], main_color[2], 0.28) if self.active else (0.16, 0.18, 0.23, 0.4)

        self._rounded_rect(bx, by, badge_w, badge_h, capsule_bg, 12)
        with self.canvas:
            Color(*capsule_border)
            Line(rounded_rectangle=[bx, by, badge_w, badge_h, 12], width=1.0)

        # Map dynamic status text
        status_lbl = self.get_status_text().upper()
        self._text(status_lbl, cx, by + 5, 10, main_color, bold=True, cache=False)

    def draw_right_panel(self, px_right, py_start, p_height, main_color):
        top_y = py_start + p_height
        
        # Panel frame
        panel_bg = (0.07, 0.08, 0.11, 0.65)
        panel_border = (0.15, 0.17, 0.22, 1.0)
        self._rounded_rect(px_right, py_start, 210, p_height, panel_bg, 12)
        with self.canvas:
            Color(*panel_border)
            Line(rounded_rectangle=[px_right, py_start, 210, p_height, 12], width=1.2)

        # Title
        self._text("GUITAR PRESETS", px_right + 16, top_y - 25, 11, (0.45, 0.48, 0.58, 1.0), bold=True, align="left", cache=True)
        self._line([px_right + 16, top_y - 34, px_right + 194, top_y - 34], (0.15, 0.17, 0.22, 1.0), 1)

        # Dynamic string rows based on instrument list
        strings = self.get_active_strings()
        n_strings = len(strings)
        row_h = (p_height - 105) / n_strings  # Leaves 65px at bottom for the manual reset button

        for idx, (note_key, note_label, target_hz) in enumerate(strings):
            ry = py_start + 65 + (n_strings - 1 - idx) * row_h + row_h / 2
            
            # Determine selection: locked manual note, or active auto pitch
            if self.selected_preset is not None:
                is_selected = (self.selected_preset == note_key)
            else:
                is_selected = self.active and (self.note == note_key)

            row_color = main_color if is_selected else (0.28, 0.31, 0.38, 1.0)

            # Discrete Green Glow capsule behind row if selected
            if is_selected:
                glow_bg = (0.00, 1.00, 0.40, 0.08)
                glow_border = (0.00, 1.00, 0.40, 0.25)
                self._rounded_rect(px_right + 10, ry - row_h / 2 + 3, 190, row_h - 6, glow_bg, 8)
                with self.canvas:
                    Color(*glow_border)
                    Line(rounded_rectangle=[px_right + 10, ry - row_h / 2 + 3, 190, row_h - 6, 8], width=1.0)

            # LED Indicator dot
            with self.canvas:
                if is_selected:
                    Color(0.00, 1.00, 0.40, 1.0)
                    Ellipse(pos=(px_right + 20, ry - 5), size=(10, 10))
                    Color(0.00, 1.00, 0.40, 0.25)
                    Line(circle=(px_right + 25, ry, 9), width=1.5)
                else:
                    Color(0.16, 0.18, 0.23, 1.0)
                    Line(circle=(px_right + 25, ry, 5), width=1.5)

            # Note Name
            note_txt_col = (0.94, 0.96, 1.00, 1.0) if is_selected else (0.45, 0.48, 0.58, 1.0)
            self._text(note_key, px_right + 42, ry - 6, 14, note_txt_col, bold=True, align="left", cache=True)

            # Label (e.g. 1ª CORDA)
            lbl_txt_col = (0.65, 0.68, 0.76, 1.0) if is_selected else (0.32, 0.35, 0.42, 1.0)
            self._text(note_label, px_right + 78, ry - 5, 10, lbl_txt_col, bold=False, align="left", cache=True)

            # Frequency Label
            self._text(f"{target_hz:.1f} Hz", px_right + 192, ry - 6, 12, row_color, bold=is_selected, align="right", cache=True)

        # Auto Mode / Manual Lock Indicator Button at the bottom of Right Panel
        btn_w = 180
        btn_h = 30
        btn_x = px_right + 15
        btn_y = py_start + 15

        if self.selected_preset is not None:
            btn_bg = (0.00, 1.00, 0.40, 0.08)
            btn_brd = (0.00, 1.00, 0.40, 0.6)
            btn_txt = "RESET LOCK"
            btn_color = (0.00, 1.00, 0.40, 1.0)
        else:
            btn_bg = (0.06, 0.07, 0.09, 0.2)
            btn_brd = (0.12, 0.14, 0.18, 0.5)
            btn_txt = "AUTO MODE"
            btn_color = (0.32, 0.35, 0.42, 1.0)

        self._rounded_rect(btn_x, btn_y, btn_w, btn_h, btn_bg, 8)
        with self.canvas:
            Color(*btn_brd)
            Line(rounded_rectangle=[btn_x, btn_y, btn_w, btn_h, 8], width=1)
        self._text(btn_txt, btn_x + btn_w / 2, btn_y + 8, 10, btn_color, bold=True, align="center", cache=True)

    def draw_footer(self, w, h):
        self._line([24, 34, w - 24, 34], (0.15, 0.17, 0.22, 1.0), 1.0)
        self._text("BWRLD AUDIO ENGINE V5 // EXPERT TUNING MODES ACTIVE", 24, 15, 9, (0.32, 0.35, 0.42, 1.0), bold=True, align="left", cache=True)
        self._text("SR: 44.1 KHZ // BLOCK: 4096 // WIN32 DIRECTSOUND", w - 24, 15, 9, (0.32, 0.35, 0.42, 1.0), bold=True, align="right", cache=True)

    def draw(self, dt):
        self.canvas.clear()
        w, h = self.width, self.height
        if w <= 10 or h <= 10:
            return

        main_color = color_for_cents(self.cents, self.active)

        # Dynamic Symmetrical Boundaries
        px_left = 24
        px_right = w - 234
        w_center = px_right - px_left - 242
        py_start = 42
        p_height = h - 110

        # Gauge dimensions
        cx = px_left + 226 + w_center / 2
        cy = py_start + p_height * 0.42
        radius = min(w_center * 0.48, p_height * 0.42)

        # Modular execution blocks
        self.draw_background(w, h)
        self.draw_header(w, h)
        self.draw_left_panel(px_left, py_start, p_height)
        self.draw_center_panel(cx, cy, w_center, p_height, main_color)
        self.draw_speedometer(cx, cy, radius, main_color)
        self.draw_note_info(cx, cy, main_color)
        self.draw_right_panel(px_right, py_start, p_height, main_color)
        self.draw_footer(w, h)

    def on_touch_down(self, touch):
        """Touch handler mapping preset selection clicks, header mode swaps, and auto-reset button."""
        w, h = self.width, self.height
        if w <= 10 or h <= 10:
            return super().on_touch_down(touch)

        px_right = w - 234
        py_start = 42
        p_height = h - 110

        # 1. Click Header Mode Bar
        if h - 45 <= touch.y <= h - 21:
            for idx, mode_name in enumerate(["CHROMATIC", "GUITAR", "DROP D", "BASS"]):
                bx_start = w - 440 + idx * 102
                bx_end = bx_start + 92
                if bx_start <= touch.x <= bx_end:
                    self.selected_preset = None
                    self.tuner_mode = mode_name
                    self.base_mode = mode_name
                    self.needs_history_reset = True  # Flush stale history on mode switch
                    print(f"[TUNER] Active mode set to {mode_name}")
                    return True

        # 2. Click Right Panel Bounds
        if px_right <= touch.x <= px_right + 210 and py_start <= touch.y <= py_start + p_height:
            # Check if auto reset button clicked
            if py_start + 15 <= touch.y <= py_start + 45:
                if px_right + 15 <= touch.x <= px_right + 195:
                    if self.selected_preset is not None:
                        self.selected_preset = None
                        self.tuner_mode = self.base_mode
                        self.needs_history_reset = True  # Flush history on manual unlock
                        print(f"[TUNER] Reset manual lock. Restored mode: {self.tuner_mode}")
                        return True

            # Check if dynamic preset rows clicked
            strings = self.get_active_strings()
            n_strings = len(strings)
            row_h = (p_height - 105) / n_strings

            for idx in range(n_strings):
                ry_min = py_start + 65 + (n_strings - 1 - idx) * row_h
                ry_max = ry_min + row_h
                if ry_min <= touch.y <= ry_max:
                    preset_note = strings[idx][0]
                    if self.selected_preset == preset_note:
                        self.selected_preset = None
                        self.tuner_mode = self.base_mode
                        self.needs_history_reset = True  # Flush on deselect
                        print(f"[TUNER] Preset {preset_note} deselected. Auto mode enabled.")
                    else:
                        self.selected_preset = preset_note
                        self.tuner_mode = "MANUAL"
                        self.needs_history_reset = True  # Flush on lock to new string
                        print(f"[TUNER] Locked manually to {preset_note}.")
                    return True

        return super().on_touch_down(touch)


class BwrldTunerApp(App):
    def build(self):
        self.title = "BWRLD Tuner Pro"
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

            # Dynamic MIN_FREQ selection to support BASS E1 (41.20 Hz) and A1 (55.00 Hz)
            active_mode = self.ui.tuner_mode if hasattr(self, 'ui') else "CHROMATIC"
            m_freq = 30 if active_mode == "BASS" else 55

            freq, rms, clarity = detectar_frequencia(
                audio,
                fs=FS,
                min_freq=m_freq,
                max_freq=MAX_FREQ,
                rms_threshold=RMS_TRIGGER,
                clarity_threshold=CLARITY_TRIGGER,
            )

            if freq is None:
                with self.lock:
                    self.pending = {"active": False, "rms": rms, "clarity": clarity}
                return

            # Apply Pitch Matching dynamically in callback thread based on active mode
            if active_mode == "MANUAL" and hasattr(self, 'ui') and self.ui.selected_preset:
                preset_note = self.ui.selected_preset
                strings = self.ui.get_active_strings()
                target = next((hz for key, label, hz in strings if key == preset_note), 82.41)
                note = preset_note
            elif active_mode == "BASS":
                note, target = encontrar_nota_bass(freq)
            elif active_mode == "DROP D":
                note, target = encontrar_nota_drop_d(freq)
            elif active_mode == "GUITAR":
                note, target = encontrar_nota_guitar(freq)
            else:  # CHROMATIC auto mode
                note, target = encontrar_nota_cromatica(freq)

            cents = cents_between(freq, target)

            # Correction 1: Only drop outliers in CHROMATIC mode.
            # In GUITAR, DROP D, BASS and MANUAL the string may be very far from
            # target at the start — rejecting those frames causes blinking.
            if active_mode == "CHROMATIC" and abs(cents) > 85:
                with self.lock:
                    self.pending = {"active": False, "rms": rms, "clarity": clarity}
                return

            self.freq_history.append(freq)
            self.cents_history.append(cents)

            smooth_freq = float(np.median(self.freq_history))
            smooth_cents = float(np.median(self.cents_history))

            # Recalculate target for the smoothed freq to match selected mode
            if active_mode == "MANUAL" and hasattr(self, 'ui') and self.ui.selected_preset:
                smooth_note = self.ui.selected_preset
                strings = self.ui.get_active_strings()
                smooth_target = next((hz for key, label, hz in strings if key == smooth_note), 82.41)
            elif active_mode == "BASS":
                smooth_note, smooth_target = encontrar_nota_bass(smooth_freq)
            elif active_mode == "DROP D":
                smooth_note, smooth_target = encontrar_nota_drop_d(smooth_freq)
            elif active_mode == "GUITAR":
                smooth_note, smooth_target = encontrar_nota_guitar(smooth_freq)
            else:
                smooth_note, smooth_target = encontrar_nota_cromatica(smooth_freq)

            smooth_cents = cents_between(smooth_freq, smooth_target)
            status_txt = "AFINADO"

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
        # Correction 3: flush stale history whenever the UI requests it
        # (set by mode switches and preset locks in on_touch_down).
        if self.ui.needs_history_reset:
            self.freq_history.clear()
            self.cents_history.clear()
            self.ui.needs_history_reset = False

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
