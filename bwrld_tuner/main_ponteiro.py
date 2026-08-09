from kivy.app import App
from kivy.uix.widget import Widget
from kivy.graphics import Color, Line, Rectangle, Triangle, Ellipse, RoundedRectangle
from kivy.core.window import Window
from kivy.core.text import Label as CoreLabel
from kivy.clock import Clock

import sounddevice as sd
from threading import Lock

from tuner_pro import detectar_frequencia

from core.pipeline import TunerPipeline
from core.tunings import get_display_tuning, get_min_freq

# ==========================================
# BWRLD TUNER V6.2 - EXPERT SYSTEM EDITION
# ==========================================
# Toda a lógica musical (notas, cents, status, suavização, gate) vive em core/
# e é coberta por testes. Este arquivo é apenas áudio + desenho.
FS = 44100
BLOCKSIZE = 4096
CHANNELS = 1
DEVICE_ID = None  # None uses the default system input

MAX_FREQ = 500
RMS_TRIGGER = 0.006
CLARITY_TRIGGER = 0.18
HISTORY_SIZE = 7
HOLD_TIME = 0.75  # Segundos segurando a última leitura antes de ir para STANDBY

# Set window size and dark theme background color
Window.clearcolor = (0.035, 0.039, 0.047, 1.0)  # Deep Charcoal #090a0f
Window.minimum_width = 820
Window.minimum_height = 560

# ── Paleta ────────────────────────────────
NEON_GREEN = (0.00, 1.00, 0.40, 1.0)  # #00FF66 — afinado
NEON_AMBER = (1.00, 0.65, 0.00, 1.0)  # #FFA600 — levemente fora
NEON_RED   = (1.00, 0.20, 0.25, 1.0)  # #FF333F — muito fora
STEEL      = (0.35, 0.38, 0.46, 1.0)  # inativo
INK        = (0.09, 0.10, 0.13, 1.0)  # fundo de trilho
BORDER     = (0.15, 0.17, 0.22, 1.0)  # bordas de painel
LABEL      = (0.45, 0.48, 0.58, 1.0)  # texto secundário

IN_TUNE_CENTS = 5.0   # Faixa considerada afinada (detente verde da fita)
METER_RANGE   = 50.0  # Cents nas extremidades da fita

# Altura do bloco central (nota + fita + números) com escala 1.0. A escala da
# janela sai daqui, não de um número solto: se os blocos mudarem de tamanho,
# a conta de caber continua certa. Ver layout() e draw_center_content().
CENTER_NOTE_H = 150.0 + 44.0
CENTER_METER_H = 190.0
CENTER_NUM_H = 190.0
CENTER_GAP = 66.0
CENTER_CONTENT_H = CENTER_NOTE_H + CENTER_GAP + CENTER_METER_H + CENTER_GAP + CENTER_NUM_H


def lerp(a, b, t):
    return a + (b - a) * t

def mix_color(c1, c2, t):
    t = max(0.0, min(1.0, t))
    return tuple(lerp(c1[i], c2[i], t) for i in range(4))

def with_alpha(color, alpha):
    """Mesma cor com outra opacidade."""
    return (color[0], color[1], color[2], alpha)

def color_for_cents(cents, active=True):
    if not active:
        return STEEL

    a = abs(cents)
    if a <= 4:
        return NEON_GREEN
    if a <= 15:
        return mix_color(NEON_GREEN, NEON_AMBER, (a - 4) / 11)
    if a <= 30:
        return mix_color(NEON_AMBER, NEON_RED, (a - 15) / 15)
    return NEON_RED

def zone_color(cents):
    """Cor fixa da zona da escala (não interpolada) para marcações e rótulos."""
    a = abs(cents)
    if a <= IN_TUNE_CENTS:
        return NEON_GREEN
    if a <= 25:
        return NEON_AMBER
    return NEON_RED

class BwrldTunerUI(Widget):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.note = "---"
        self.string_name = ""
        self.freq = 0.0
        self.target = 0.0
        self.cents = 0.0
        self.raw_cents = 0.0
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

    @property
    def effective_mode(self):
        """Modo de instrumento em vigor (MANUAL herda o modo base)."""
        return self.base_mode if self.tuner_mode == "MANUAL" else self.tuner_mode

    def set_result(self, result, rms, clarity):
        """Recebe um TunerResult pronto de core/ — a UI não calcula nada."""
        self.note = result.note
        self.string_name = result.string_name
        self.freq = result.freq
        self.target = result.target
        self.raw_cents = result.raw_cents
        self.cents = result.display_cents
        self.status = result.status
        self.rms = float(rms)
        self.clarity = float(clarity)
        self.active = True

    def set_idle(self, rms=0.0, clarity=0.0):
        self.note = "---"
        self.string_name = ""
        self.freq = 0.0
        self.target = 0.0
        self.cents = 0.0
        self.raw_cents = 0.0
        self.status = "STANDBY"
        self.rms = float(rms)
        self.clarity = float(clarity)
        self.active = False

    def get_active_strings(self):
        """Cordas do preset ativo. CHROMATIC exibe o preset de GUITAR."""
        return get_display_tuning(self.effective_mode)

    # ==========================================
    # GEOMETRIA — fonte única para desenho e toque
    # ==========================================
    # Estas funções são a única definição de onde as coisas ficam. draw_* e
    # on_touch_down leem daqui, então mudar o layout não desalinha os cliques.

    def layout(self, w, h):
        """Retângulos dos três painéis e a escala tipográfica da janela."""
        px_left = 24
        px_right = w - 234
        py_start = 42
        p_height = h - 110
        return {
            "px_left": px_left,
            "px_right": px_right,
            "py_start": py_start,
            "p_height": p_height,
            "cx_center": px_left + 226 + (px_right - px_left - 242) / 2,
            "w_center": px_right - px_left - 242,
            # Escala do conteúdo central: derivada da altura que o bloco
            # realmente ocupa, com 8% de folga. Em janela pequena tudo encolhe
            # junto em vez de vazar para o header e o rodapé; em janela grande
            # para de crescer em 1.0 para não esparramar.
            "s": max(0.45, min(1.0, (p_height * 0.92) / CENTER_CONTENT_H)),
        }

    def mode_button_rects(self, w, h):
        """[(nome_do_modo, x, y, largura, altura)] da barra de modos no header."""
        btn_w, btn_h, gap = 92, 22, 10
        modes = ["CHROMATIC", "GUITAR", "DROP D", "BASS"]
        total = len(modes) * btn_w + (len(modes) - 1) * gap
        x0 = w - 24 - total
        return [
            (m, x0 + i * (btn_w + gap), h - 45, btn_w, btn_h)
            for i, m in enumerate(modes)
        ]

    def preset_row_rects(self, px_right, py_start, p_height):
        """[(nota, rótulo, hz, x, y, largura, altura)] das linhas de preset.

        As linhas preenchem a altura do painel. O que estragava a versão antiga
        não era a linha alta e sim o texto de 14 px perdido dentro dela — quem
        desenha escala a tipografia por `row_h` (ver row_font_size).
        """
        strings = self.get_active_strings()
        n = len(strings)
        top = py_start + p_height - 46        # abaixo do título do painel
        bottom = py_start + 58                # acima do botão AUTO MODE
        row_h = (top - bottom) / n

        return [
            (nota, rotulo, hz, px_right + 10, top - (i + 1) * row_h, 190, row_h)
            for i, (nota, rotulo, hz) in enumerate(strings)
        ]

    @staticmethod
    def row_font_size(row_h):
        """(tamanho_da_nota, tamanho_do_rótulo) proporcionais à altura da linha."""
        nota = int(max(14.0, min(row_h * 0.24, 30.0)))
        return nota, int(max(9.0, nota * 0.62))

    def reset_button_rect(self, px_right, py_start):
        """(x, y, largura, altura) do botão AUTO MODE / RESET LOCK."""
        return (px_right + 15, py_start + 15, 180, 30)

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

        # Barra de modos (geometria vinda de mode_button_rects)
        botoes = self.mode_button_rects(w, h)
        self._text("MODE:", botoes[0][1] - 55, h - 38, 11, LABEL, bold=True, align="left", cache=True)

        for mode_name, bx, by, bw, bh in botoes:
            is_sel = (self.tuner_mode == mode_name or (self.tuner_mode == "MANUAL" and self.base_mode == mode_name))

            if is_sel:
                capsule_bg = with_alpha(NEON_GREEN, 0.12)
                capsule_brd = with_alpha(NEON_GREEN, 0.5)
                text_col = NEON_GREEN
            else:
                capsule_bg = (0.06, 0.07, 0.09, 0.3)
                capsule_brd = (0.15, 0.17, 0.22, 0.6)
                text_col = (0.42, 0.46, 0.54, 1.0)

            self._rounded_rect(bx, by, bw, bh, capsule_bg, bh / 2)
            with self.canvas:
                Color(*capsule_brd)
                Line(rounded_rectangle=[bx, by, bw, bh, bh / 2], width=1)
            self._text(mode_name, bx + bw / 2, by + 5, 9, text_col, bold=True, align="center", cache=True)

        self._line([24, h - 50, w - 24, h - 50], BORDER, 1.2)

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

        # Barras preenchendo a altura do painel. O que estragava antes era a
        # proporção (762x16 = 47:1), não a altura: com 46 px de largura e
        # marcações de escala elas leem como VU meter de verdade.
        bar_w = 46
        rot_y = top_y - 62                    # rótulos abaixo do título
        bar_top = top_y - 78
        bar_y = py_start + 104                # espaço para números + badge
        bar_h = max(40.0, bar_top - bar_y)

        x_rms = px_left + 26
        x_clr = px_left + 120

        for x, rotulo, valor, cor_cheia in (
            (x_rms, "LEVEL (RMS)", min(self.rms / 0.035, 1.0), (1.00, 0.62, 0.00, 1.0)),
            (x_clr, "CLARITY", min(max(self.clarity, 0.0), 1.0), NEON_GREEN),
        ):
            self._text(rotulo, x, rot_y, 10, LABEL, bold=True, align="left", cache=True)
            self._rounded_rect(x, bar_y, bar_w, bar_h, INK, 8)
            cor = cor_cheia if self.active else (0.22, 0.25, 0.32, 1.0)
            self._rounded_rect(x, bar_y, bar_w, max(bar_h * valor, 4), cor, 8)
            # Marcações de escala a cada 25%
            for frac in (0.25, 0.5, 0.75):
                ty = bar_y + bar_h * frac
                self._line([x + bar_w - 9, ty, x + bar_w - 2, ty], with_alpha(BORDER, 0.9), 1.0)
            with self.canvas:
                Color(*BORDER)
                Line(rounded_rectangle=[x, bar_y, bar_w, bar_h, 8], width=1.0)

        # Números logo abaixo das barras
        num_y = bar_y - 28
        self._text(f"{self.rms:.4f}", x_rms + bar_w / 2, num_y, 13, (0.84, 0.86, 0.92, 1.0), bold=True, align="center", cache=False)
        self._text("RMS", x_rms + bar_w / 2, num_y - 15, 9, LABEL, bold=True, align="center", cache=True)

        self._text(f"{self.clarity:.2f}", x_clr + bar_w / 2, num_y, 13, (0.84, 0.86, 0.92, 1.0), bold=True, align="center", cache=False)
        self._text("CLARITY", x_clr + bar_w / 2, num_y - 15, 9, LABEL, bold=True, align="center", cache=True)

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

    def _meter_x(self, cx, half, cents):
        """Posição horizontal de um valor em cents dentro da fita."""
        c = max(-METER_RANGE, min(METER_RANGE, cents))
        return cx + (c / METER_RANGE) * half

    def draw_strip_meter(self, cx, cy, strip_w, s, main_color):
        """Fita linear de cents com detente central.

        cy é a linha de centro do trilho. A leitura acontece pela posição do
        cursor e pelo comprimento da barra que cresce a partir do zero — os dois
        legíveis de relance, sem precisar ler número.
        """
        half = strip_w / 2.0
        track_h = 96 * s
        ty = cy - track_h / 2.0
        afinado = self.active and abs(self.raw_cents) <= IN_TUNE_CENTS

        # 1. Trilho
        self._rounded_rect(cx - half, ty, strip_w, track_h, INK, track_h / 2)
        with self.canvas:
            Color(*BORDER)
            Line(rounded_rectangle=[cx - half, ty, strip_w, track_h, track_h / 2], width=1.2)

        # 2. Zona afinada (±5 cents) — acende forte quando você chega nela
        zx0 = self._meter_x(cx, half, -IN_TUNE_CENTS)
        zx1 = self._meter_x(cx, half, IN_TUNE_CENTS)
        self._rounded_rect(zx0, ty + 3, zx1 - zx0, track_h - 6,
                           with_alpha(NEON_GREEN, 0.22 if afinado else 0.07), 5)

        # 3. Barra de desvio, crescendo do centro para o lado do erro
        if self.active:
            cur = self._meter_x(cx, half, self.needle_cents)
            x0 = min(cx, cur)
            bw = max(abs(cur - cx), 3.0)
            # brilho por trás, depois a barra sólida
            self._rounded_rect(x0, ty + 2, bw, track_h - 4, with_alpha(main_color, 0.20), 5)
            self._rounded_rect(x0, ty + 7, bw, track_h - 14, main_color, 4)

        # 4. Marcações acima do trilho
        tick_base = ty + track_h + 7 * s
        for c in range(-50, 51, 5):
            x = self._meter_x(cx, half, c)
            maior = (c % 25 == 0)
            medio = (c % 10 == 0)
            tl = (15 if maior else 9 if medio else 5) * s
            tw = 2.0 if maior else 1.2 if medio else 0.8
            self._line([x, tick_base, x, tick_base + tl],
                       with_alpha(zone_color(c), 0.9 if maior else 0.5), tw)

        # 5. Detente central: a referência mais importante da tela
        det_h = 26 * s
        self._line([cx, ty - det_h * 0.35, cx, ty], with_alpha(NEON_GREEN, 0.9), 2.2)
        with self.canvas:
            Color(*with_alpha(NEON_GREEN, 0.95))
            Triangle(points=[
                cx, tick_base + 4 * s,
                cx - 7 * s, tick_base + 15 * s,
                cx + 7 * s, tick_base + 15 * s,
            ])

        # 6. Cursor sobre a posição atual
        if self.active:
            cur = self._meter_x(cx, half, self.needle_cents)
            with self.canvas:
                Color(*main_color)
                Line(points=[cur, ty + 3, cur, ty + track_h - 3], width=2.4)
                Triangle(points=[
                    cur, ty - 3 * s,
                    cur - 8 * s, ty - 15 * s,
                    cur + 8 * s, ty - 15 * s,
                ])

        # 7. Rótulos da escala
        for c, lbl in [(-50, "-50"), (-25, "-25"), (0, "0"), (25, "+25"), (50, "+50")]:
            x = self._meter_x(cx, half, c)
            self._text(lbl, x, tick_base + 18 * s, int(11 * s) or 9,
                       with_alpha(zone_color(c), 0.95), bold=(c == 0), cache=True)

        return tick_base + 32 * s  # topo ocupado pela fita

    def draw_readout(self, cx, top_y, s, main_color):
        """Nota grande, corda, Hz e cents. Retorna a altura consumida."""
        y = top_y

        # 1. Nota
        tam_nota = int(150 * s)
        if self.active:
            self._text(self.note, cx, y - tam_nota, tam_nota, main_color, bold=True, cache=False)
        else:
            self._text("---", cx, y - tam_nota, tam_nota, (0.20, 0.23, 0.30, 1.0), bold=True, cache=True)
        y -= tam_nota + 10 * s

        # 2. Corda (ex: 6ª CORDA) — só existe nos presets, não no cromático
        if self.active and self.string_name:
            self._text(self.string_name, cx, y - 18 * s, int(15 * s) or 10, LABEL, bold=True, cache=True)
        y -= 34 * s

        return top_y - y

    def draw_numbers(self, cx, top_y, s, main_color):
        """Hz medido, alvo e desvio em cents, abaixo da fita."""
        y = top_y

        if self.active:
            sinal = "+" if self.raw_cents > 0 else ""
            self._text(f"{sinal}{self.raw_cents:.1f} CENTS", cx, y - 26 * s, int(24 * s) or 12,
                       main_color, bold=True, cache=False)
            y -= 44 * s
            self._text(f"{self.freq:.2f} Hz", cx, y - 24 * s, int(22 * s) or 12,
                       (0.92, 0.94, 0.98, 1.0), cache=False)
            y -= 34 * s
            self._text(f"TARGET {self.target:.2f} Hz", cx, y - 15 * s, int(13 * s) or 9,
                       (0.42, 0.46, 0.55, 1.0), bold=True, cache=False)
            y -= 30 * s
        else:
            self._text("WAITING SIGNAL", cx, y - 20 * s, int(16 * s) or 10, STEEL, bold=True, cache=True)
            y -= 108 * s

        # Cápsula de status
        badge_w, badge_h = 240 * s, 40 * s
        bx, by = cx - badge_w / 2, y - badge_h
        fundo = with_alpha(main_color, 0.10) if self.active else (0.09, 0.10, 0.12, 0.3)
        borda = with_alpha(main_color, 0.32) if self.active else (0.16, 0.18, 0.23, 0.4)
        self._rounded_rect(bx, by, badge_w, badge_h, fundo, badge_h / 2)
        with self.canvas:
            Color(*borda)
            Line(rounded_rectangle=[bx, by, badge_w, badge_h, badge_h / 2], width=1.0)
        self._text(self.status.upper(), cx, by + 12 * s, int(14 * s) or 10,
                   main_color, bold=True, cache=False)

    def draw_center_content(self, geo, main_color):
        """Empilha nota, fita e números centralizados no painel do meio.

        Alturas fixas escaladas por `s`, não frações da altura disponível: é o
        que impede o vão gigante que aparecia em tela grande.
        """
        cx = geo["cx_center"]
        s = geo["s"]
        strip_w = max(240.0, min(geo["w_center"] * 0.80, 1120.0))

        h_nota = CENTER_NOTE_H * s
        h_fita = CENTER_METER_H * s
        h_num = CENTER_NUM_H * s
        gap = CENTER_GAP * s
        total = CENTER_CONTENT_H * s

        topo = geo["py_start"] + geo["p_height"] / 2 + total / 2

        self.draw_readout(cx, topo, s, main_color)
        cy_fita = topo - h_nota - gap - h_fita / 2
        self.draw_strip_meter(cx, cy_fita, strip_w, s, main_color)
        self.draw_numbers(cx, cy_fita - h_fita / 2 - gap, s, main_color)

        # Suavização do cursor (frame a frame, ~60 fps)
        alvo = self.cents if self.active else 0.0
        self.needle_cents += (alvo - self.needle_cents) * 0.18

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
        titulo = "BASS PRESETS" if self.effective_mode == "BASS" else "GUITAR PRESETS"
        self._text(titulo, px_right + 16, top_y - 25, 11, LABEL, bold=True, align="left", cache=True)
        self._line([px_right + 16, top_y - 34, px_right + 194, top_y - 34], BORDER, 1)

        # Linhas de preset (geometria vinda de preset_row_rects)
        for note_key, note_label, target_hz, rx, ry_min, rw, row_h in self.preset_row_rects(px_right, py_start, p_height):
            ry = ry_min + row_h / 2  # linha de centro da linha

            # Seleção: nota travada manualmente, ou nota detectada no automático
            if self.selected_preset is not None:
                is_selected = (self.selected_preset == note_key)
            else:
                is_selected = self.active and (self.note == note_key)

            row_color = main_color if is_selected else (0.28, 0.31, 0.38, 1.0)

            # Cápsula acesa atrás da linha selecionada
            if is_selected:
                self._rounded_rect(rx, ry_min + 3, rw, row_h - 6, with_alpha(NEON_GREEN, 0.08), 8)
                with self.canvas:
                    Color(*with_alpha(NEON_GREEN, 0.25))
                    Line(rounded_rectangle=[rx, ry_min + 3, rw, row_h - 6, 8], width=1.0)

            # LED
            with self.canvas:
                if is_selected:
                    Color(*NEON_GREEN)
                    Ellipse(pos=(px_right + 20, ry - 5), size=(10, 10))
                    Color(*with_alpha(NEON_GREEN, 0.25))
                    Line(circle=(px_right + 25, ry, 9), width=1.5)
                else:
                    Color(0.16, 0.18, 0.23, 1.0)
                    Line(circle=(px_right + 25, ry, 5), width=1.5)

            f_nota, f_lbl = self.row_font_size(row_h)

            note_txt_col = (0.94, 0.96, 1.00, 1.0) if is_selected else LABEL
            self._text(note_key, px_right + 42, ry - f_nota * 0.42, f_nota, note_txt_col, bold=True, align="left", cache=True)

            lbl_txt_col = (0.65, 0.68, 0.76, 1.0) if is_selected else (0.32, 0.35, 0.42, 1.0)
            self._text(note_label, px_right + 42, ry - f_nota * 0.42 - f_lbl - 4, f_lbl, lbl_txt_col, bold=False, align="left", cache=True)

            self._text(f"{target_hz:.1f} Hz", px_right + 192, ry - f_lbl * 0.5, f_lbl + 2, row_color, bold=is_selected, align="right", cache=True)

        # Botão AUTO MODE / RESET LOCK
        btn_x, btn_y, btn_w, btn_h = self.reset_button_rect(px_right, py_start)

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
        self._text("BWRLD AUDIO ENGINE V6.2 // EXPERT TUNING MODES ACTIVE", 24, 15, 9, (0.32, 0.35, 0.42, 1.0), bold=True, align="left", cache=True)
        self._text("SR: 44.1 KHZ // BLOCK: 4096 // WIN32 DIRECTSOUND", w - 24, 15, 9, (0.32, 0.35, 0.42, 1.0), bold=True, align="right", cache=True)

    def draw(self, dt):
        self.canvas.clear()
        w, h = self.width, self.height
        if w <= 10 or h <= 10:
            return

        main_color = color_for_cents(self.cents, self.active)

        geo = self.layout(w, h)
        px_left = geo["px_left"]
        px_right = geo["px_right"]
        py_start = geo["py_start"]
        p_height = geo["p_height"]
        w_center = geo["w_center"]
        cx = geo["cx_center"]
        cy = py_start + p_height / 2

        # Modular execution blocks
        self.draw_background(w, h)
        self.draw_header(w, h)
        self.draw_left_panel(px_left, py_start, p_height)
        self.draw_center_panel(cx, cy, w_center, p_height, main_color)
        self.draw_center_content(geo, main_color)
        self.draw_right_panel(px_right, py_start, p_height, main_color)
        self.draw_footer(w, h)

    def on_touch_down(self, touch):
        """Touch handler mapping preset selection clicks, header mode swaps, and auto-reset button."""
        w, h = self.width, self.height
        if w <= 10 or h <= 10:
            return super().on_touch_down(touch)

        geo = self.layout(w, h)
        px_right = geo["px_right"]
        py_start = geo["py_start"]
        p_height = geo["p_height"]

        # 1. Barra de modos no header
        for mode_name, bx, by, bw, bh in self.mode_button_rects(w, h):
            if bx <= touch.x <= bx + bw and by <= touch.y <= by + bh:
                self.selected_preset = None
                self.tuner_mode = mode_name
                self.base_mode = mode_name
                self.needs_history_reset = True  # Flush stale history on mode switch
                print(f"[TUNER] Active mode set to {mode_name}")
                return True

        # 2. Painel direito
        if px_right <= touch.x <= px_right + 210 and py_start <= touch.y <= py_start + p_height:
            # Botão AUTO MODE / RESET LOCK
            rx, ry, rw, rh = self.reset_button_rect(px_right, py_start)
            if rx <= touch.x <= rx + rw and ry <= touch.y <= ry + rh:
                if self.selected_preset is not None:
                    self.selected_preset = None
                    self.tuner_mode = self.base_mode
                    self.needs_history_reset = True  # Flush history on manual unlock
                    print(f"[TUNER] Reset manual lock. Restored mode: {self.tuner_mode}")
                    return True

            # Linhas de preset
            for preset_note, _label, _hz, _rx, ry_min, _rw, row_h in self.preset_row_rects(px_right, py_start, p_height):
                if ry_min <= touch.y <= ry_min + row_h:
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

        # A thread de áudio só entrega números crus. Toda a decisão musical
        # acontece na thread do Kivy, dentro do pipeline — nada compartilhado.
        self.lock = Lock()
        self.pending = None
        self.last_rms = 0.0
        self.last_clarity = 0.0

        self.pipeline = TunerPipeline(
            mode=self.ui.tuner_mode,
            history_size=HISTORY_SIZE,
            hold_time=HOLD_TIME,
            rms_threshold=RMS_TRIGGER,
            clarity_threshold=CLARITY_TRIGGER,
        )

        self.start_audio()
        Clock.schedule_interval(self.apply_audio_data, 1 / 45)
        return self.ui

    def start_audio(self):
        def callback(indata, frames, time_info, status):
            audio = indata[:, 0].copy()

            # MIN_FREQ dinâmico para alcançar o BASS (E1 = 41.20 Hz).
            # Usa effective_mode: travar manualmente em E1 mantém o modo BASS.
            m_freq = get_min_freq(self.ui.effective_mode)

            freq, rms, clarity = detectar_frequencia(
                audio,
                fs=FS,
                min_freq=m_freq,
                max_freq=MAX_FREQ,
                rms_threshold=RMS_TRIGGER,
                clarity_threshold=CLARITY_TRIGGER,
            )

            with self.lock:
                self.pending = (freq, rms, clarity)

        self.stream = sd.InputStream(
            device=DEVICE_ID,
            channels=CHANNELS,
            samplerate=FS,
            blocksize=BLOCKSIZE,
            callback=callback,
        )
        self.stream.start()

    def sync_pipeline(self):
        """Alinha o pipeline com o modo/preset escolhido na UI."""
        if self.ui.tuner_mode == "MANUAL" and self.ui.selected_preset:
            self.pipeline.set_mode(self.ui.base_mode)
            self.pipeline.lock_note(self.ui.selected_preset)
        else:
            self.pipeline.set_mode(self.ui.tuner_mode)

    def apply_audio_data(self, dt):
        with self.lock:
            data = self.pending
            self.pending = None

        if self.ui.needs_history_reset:
            self.ui.needs_history_reset = False
            self.sync_pipeline()

        if data is None:
            # Sem bloco novo (áudio ~11 Hz, UI 45 Hz): só deixa o gate contar
            # o tempo para eventualmente cair em STANDBY.
            freq, rms, clarity = None, 0.0, self.last_clarity
        else:
            freq, rms, clarity = data
            self.last_rms = float(rms)
            self.last_clarity = float(clarity)

        result = self.pipeline.process(freq, rms, clarity)

        if result is None:
            return  # HOLD — mantém o último quadro na tela

        if result.active:
            self.ui.set_result(result, self.last_rms, self.last_clarity)
        else:
            self.ui.set_idle(self.last_rms, self.last_clarity)

    def on_stop(self):
        if hasattr(self, "stream"):
            self.stream.stop()
            self.stream.close()


if __name__ == "__main__":
    BwrldTunerApp().run()
