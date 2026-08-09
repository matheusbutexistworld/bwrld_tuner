from kivy.app import App
from kivy.uix.widget import Widget
from kivy.graphics import Color, Line, Rectangle, Triangle, Ellipse, RoundedRectangle
from kivy.core.window import Window
from kivy.core.text import Label as CoreLabel
from kivy.clock import Clock

import os
from threading import Lock

import sounddevice as sd

from tuner_pro import detectar_frequencia

from core.i18n import DEFAULT_LANG, LANGUAGE_LABEL, next_language, t
from core.pipeline import TunerPipeline
from core.tunings import A4_STANDARD, REFERENCE_PITCHES, get_display_tuning, get_min_freq

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
Window.clearcolor = (0.078, 0.071, 0.055, 1.0)  # #14120E carvão quente
Window.minimum_width = 820
Window.minimum_height = 560

# ── Paleta analógica ──────────────────────
# Carvão quente + creme, com os indicadores em tons de gear vintage. Nada de
# neon saturado: o verde/âmbar/tijolo abaixo são os mesmos da serigrafia de
# pedal e de mostrador de VU meter. O código de cor (verde = afinado) sobrevive.
GREEN      = (0.498, 0.651, 0.314, 1.0)  # #7FA650 verde-musgo — afinado
AMBER      = (0.784, 0.525, 0.165, 1.0)  # #C8862A âmbar queimado — fora
BRICK      = (0.651, 0.239, 0.180, 1.0)  # #A63D2E tijolo — muito fora
CREAM      = (0.910, 0.875, 0.784, 1.0)  # #E8DFC8 texto principal
STEEL      = (0.380, 0.353, 0.302, 1.0)  # #615A4D inativo
INK        = (0.055, 0.047, 0.035, 1.0)  # #0E0C09 fundo de trilho
PANEL      = (0.110, 0.098, 0.075, 1.0)  # #1C1913 fundo de painel
BORDER     = (0.227, 0.204, 0.165, 1.0)  # #3A342A bordas
LABEL      = (0.549, 0.510, 0.443, 1.0)  # #8C8271 texto secundário

# ── Tipografia ────────────────────────────
# Bahnschrift é a DIN condensada do Windows: cara de painel de instrumento.
# Consolas dá o ar de mostrador digital nos números. Ambas caem para as fontes
# que vêm dentro do Kivy quando não existem — o app não pode quebrar em outra
# máquina só por causa de fonte.
_WIN_FONTS = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "Fonts")


def _primeira_fonte(*candidatas, padrao="Roboto"):
    """Devolve o caminho da primeira fonte que existir, ou o nome de fallback."""
    for nome in candidatas:
        caminho = os.path.join(_WIN_FONTS, nome)
        if os.path.exists(caminho):
            return caminho
    return padrao


FONT_UI = _primeira_fonte("bahnschrift.ttf", "segoeui.ttf", padrao="Roboto")
FONT_NUM = _primeira_fonte("consola.ttf", padrao="RobotoMono-Regular")

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


def _fs(base, s, minimo=9):
    """Tamanho de fonte escalado, com piso legível de verdade.

    O idioma `int(base * s) or minimo` não servia: `or` só dispara quando o
    valor é zero, então em janela pequena int(11 * 0.586) = 6 passava batido e
    os rótulos da escala saíam em 6 px.
    """
    return max(int(minimo), int(round(base * s)))


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
        return GREEN
    if a <= 15:
        return mix_color(GREEN, AMBER, (a - 4) / 11)
    if a <= 30:
        return mix_color(AMBER, BRICK, (a - 15) / 15)
    return BRICK

def zone_color(cents):
    """Cor fixa da zona da escala (não interpolada) para marcações e rótulos."""
    a = abs(cents)
    if a <= IN_TUNE_CENTS:
        return GREEN
    if a <= 25:
        return AMBER
    return BRICK

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

        # Idioma da interface e afinação de referência (A4)
        self.lang = DEFAULT_LANG
        self.a4 = A4_STANDARD

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
        """Cordas do preset ativo, já na afinação de referência escolhida."""
        return get_display_tuning(self.effective_mode, self.a4)

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

    def lang_button_rect(self, w, h):
        """(x, y, largura, altura) do botão de idioma, à direita do título."""
        return (250, h - 45, 52, 22)

    def reference_button_rects(self, px_left, py_start, p_height):
        """[(a4, x, y, largura, altura)] dos botões 440 / 432 / 415.

        Ficam no topo do painel esquerdo, abaixo do título. O painel tem 210 px
        de largura útil, então três pílulas de 56 px com 6 px de folga cabem
        sem apertar mesmo na janela mínima.
        """
        top_y = py_start + p_height
        btn_w, btn_h, gap = 56, 22, 6
        y = top_y - 78
        return [
            (a4, px_left + 20 + i * (btn_w + gap), y, btn_w, btn_h)
            for i, a4 in enumerate(REFERENCE_PITCHES)
        ]

    @staticmethod
    def _render_text(text, size, bold, font):
        lbl = CoreLabel(text=text, font_size=size, bold=bold, font_name=font)
        lbl.refresh()
        return lbl.texture

    def get_cached_text(self, text, size, bold, font):
        """Texturas de texto estático. A fonte entra na chave: sem isso, o
        mesmo rótulo em duas fontes devolveria a textura errada."""
        key = (text, size, bold, font)
        if key not in self.text_cache:
            self.text_cache[key] = self._render_text(text, size, bold, font)
        return self.text_cache[key]

    def _text(self, text, x, y, size=14, color=(1, 1, 1, 1), bold=False, align="center",
              cache=True, font=None):
        font = font or FONT_UI
        if cache:
            texture = self.get_cached_text(text, size, bold, font)
        else:
            texture = self._render_text(text, size, bold, font)

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
        grid_color = with_alpha(BORDER, 0.10)
        grid_step = 40
        for gx in range(0, int(w), grid_step):
            self._line([gx, 0, gx, h], grid_color, 1)
        for gy in range(0, int(h), grid_step):
            self._line([0, gy, w, gy], grid_color, 1)

    def _pill(self, x, y, w, h, selecionada, texto, tam=9):
        """Cápsula clicável no estilo da serigrafia de pedal."""
        if selecionada:
            fundo, borda, cor = with_alpha(GREEN, 0.16), with_alpha(GREEN, 0.65), GREEN
        else:
            fundo, borda, cor = with_alpha(INK, 0.5), with_alpha(BORDER, 0.7), LABEL
        self._rounded_rect(x, y, w, h, fundo, h / 2)
        with self.canvas:
            Color(*borda)
            Line(rounded_rectangle=[x, y, w, h, h / 2], width=1)
        self._text(texto, x + w / 2, y + (h - tam) / 2 - 1, tam, cor, bold=True, align="center", cache=True)

    def draw_header(self, w, h):
        self._text("BWRLD", 24, h - 38, 13, CREAM, bold=True, align="left", cache=True)
        self._text(t("APP_SUBTITLE", self.lang), 88, h - 37, 10, LABEL, bold=True, align="left", cache=True)

        # Botão de idioma
        lx, ly, lw, lh = self.lang_button_rect(w, h)
        self._pill(lx, ly, lw, lh, False, LANGUAGE_LABEL.get(self.lang, "?"), tam=10)

        # Cápsula LOCKED quando há corda travada manualmente
        if self.tuner_mode == "MANUAL" and self.selected_preset:
            bx = lx + lw + 12
            self._rounded_rect(bx, h - 45, 105, 22, with_alpha(AMBER, 0.10), 11)
            with self.canvas:
                Color(*with_alpha(AMBER, 0.40))
                Line(rounded_rectangle=[bx, h - 45, 105, 22, 11], width=1)
            self._text(f"{t('LOCKED', self.lang)}: {self.selected_preset}", bx + 52, h - 39, 9,
                       AMBER, bold=True, align="center", cache=False)

        # Barra de modos (geometria vinda de mode_button_rects)
        botoes = self.mode_button_rects(w, h)
        self._text(t("MODE", self.lang), botoes[0][1] - 52, h - 38, 11, LABEL, bold=True, align="left", cache=True)

        for mode_name, bx, by, bw, bh in botoes:
            is_sel = (self.tuner_mode == mode_name or (self.tuner_mode == "MANUAL" and self.base_mode == mode_name))
            self._pill(bx, by, bw, bh, is_sel, t(mode_name, self.lang))

        self._line([24, h - 50, w - 24, h - 50], BORDER, 1.2)

    def draw_left_panel(self, px_left, py_start, p_height):
        top_y = py_start + p_height
        
        # Panel frame
        panel_bg = with_alpha(PANEL, 0.72)
        panel_border = BORDER
        self._rounded_rect(px_left, py_start, 210, p_height, panel_bg, 12)
        with self.canvas:
            Color(*panel_border)
            Line(rounded_rectangle=[px_left, py_start, 210, p_height, 12], width=1.2)

        # Title
        self._text(t("PANEL_TELEMETRY", self.lang), px_left + 16, top_y - 25, 11, LABEL, bold=True, align="left", cache=True)
        self._line([px_left + 16, top_y - 34, px_left + 194, top_y - 34], BORDER, 1)

        # Seletor de afinação de referência (440 / 432 / 415)
        self._text(f"{t('REFERENCE', self.lang)} A4", px_left + 20, top_y - 54, 10, LABEL, bold=True, align="left", cache=True)
        for a4, bx, by, bw, bh in self.reference_button_rects(px_left, py_start, p_height):
            self._pill(bx, by, bw, bh, a4 == self.a4, f"{a4:.0f}")

        # Barras preenchendo a altura do painel. O que estragava antes era a
        # proporção (762x16 = 47:1), não a altura: com 46 px de largura e
        # marcações de escala elas leem como VU meter de verdade.
        bar_w = 46
        rot_y = top_y - 106                   # rótulos abaixo do seletor de A4
        bar_top = top_y - 122
        bar_y = py_start + 104                # espaço para números + badge
        bar_h = max(40.0, bar_top - bar_y)

        x_rms = px_left + 26
        x_clr = px_left + 120

        for x, rotulo, valor, cor_cheia in (
            (x_rms, t("LEVEL_RMS", self.lang), min(self.rms / 0.035, 1.0), AMBER),
            (x_clr, t("CLARITY", self.lang), min(max(self.clarity, 0.0), 1.0), GREEN),
        ):
            self._text(rotulo, x, rot_y, 10, LABEL, bold=True, align="left", cache=True)
            self._rounded_rect(x, bar_y, bar_w, bar_h, INK, 8)
            cor = cor_cheia if self.active else with_alpha(STEEL, 0.6)
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
        self._text(f"{self.rms:.4f}", x_rms + bar_w / 2, num_y, 13, CREAM, align="center", cache=False, font=FONT_NUM)
        self._text("RMS", x_rms + bar_w / 2, num_y - 15, 9, LABEL, bold=True, align="center", cache=True)

        self._text(f"{self.clarity:.2f}", x_clr + bar_w / 2, num_y, 13, CREAM, align="center", cache=False, font=FONT_NUM)
        self._text(t("CLARITY", self.lang), x_clr + bar_w / 2, num_y - 15, 9, LABEL, bold=True, align="center", cache=True)

        # Avaliação do sinal (fraco / sujo / ok)
        if self.rms < RMS_TRIGGER:
            sig_status = t("SIGNAL_LOW", self.lang)
            sig_color = AMBER
        elif self.clarity < CLARITY_TRIGGER:
            sig_status = t("SIGNAL_NOISY", self.lang)
            sig_color = BRICK
        else:
            sig_status = t("SIGNAL_OK", self.lang)
            sig_color = GREEN

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
        panel_bg = with_alpha(PANEL, 0.45)
        panel_border = BORDER
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
                           with_alpha(GREEN, 0.22 if afinado else 0.07), 5)

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
        self._line([cx, ty - det_h * 0.35, cx, ty], with_alpha(GREEN, 0.9), 2.2)
        with self.canvas:
            Color(*with_alpha(GREEN, 0.95))
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
            # Folga constante acima da marcação mais longa (15 * s): em escala
            # pequena um espaçamento proporcional encostava o rótulo no tick.
            self._text(lbl, x, tick_base + 15 * s + 7, _fs(11, s, 9),
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
            self._text("---", cx, y - tam_nota, tam_nota, with_alpha(STEEL, 0.55), bold=True, cache=True)
        y -= tam_nota + 10 * s

        # 2. Corda (ex: 6ª CORDA) — só existe nos presets, não no cromático
        if self.active and self.string_name:
            self._text(t(self.string_name, self.lang), cx, y - 18 * s, _fs(15, s, 10), LABEL, bold=True, cache=True)
        y -= 34 * s

        return top_y - y

    def draw_numbers(self, cx, top_y, s, main_color):
        """Hz medido, alvo e desvio em cents, abaixo da fita."""
        y = top_y

        if self.active:
            sinal = "+" if self.raw_cents > 0 else ""
            self._text(f"{sinal}{self.raw_cents:.1f}", cx, y - 26 * s, _fs(26, s, 12),
                       main_color, cache=False, font=FONT_NUM)
            self._text(t("CENTS", self.lang), cx, y - 46 * s, _fs(12, s, 9),
                       LABEL, bold=True, cache=True)
            y -= 60 * s
            self._text(f"{self.freq:.2f} Hz", cx, y - 24 * s, _fs(22, s, 12),
                       CREAM, cache=False, font=FONT_NUM)
            y -= 34 * s
            self._text(f"{t('TARGET', self.lang)} {self.target:.2f} Hz", cx, y - 15 * s, _fs(13, s, 9),
                       LABEL, bold=True, cache=False)
            y -= 30 * s
        else:
            self._text(t("WAITING_SIGNAL", self.lang), cx, y - 20 * s, _fs(16, s, 10), STEEL, bold=True, cache=True)
            y -= 108 * s

        # Cápsula de status
        badge_w, badge_h = 240 * s, 40 * s
        bx, by = cx - badge_w / 2, y - badge_h
        fundo = with_alpha(main_color, 0.10) if self.active else with_alpha(INK, 0.4)
        borda = with_alpha(main_color, 0.32) if self.active else with_alpha(BORDER, 0.5)
        self._rounded_rect(bx, by, badge_w, badge_h, fundo, badge_h / 2)
        with self.canvas:
            Color(*borda)
            Line(rounded_rectangle=[bx, by, badge_w, badge_h, badge_h / 2], width=1.0)
        self._text(t(self.status, self.lang), cx, by + 12 * s, _fs(14, s, 10),
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
        panel_bg = with_alpha(PANEL, 0.72)
        panel_border = BORDER
        self._rounded_rect(px_right, py_start, 210, p_height, panel_bg, 12)
        with self.canvas:
            Color(*panel_border)
            Line(rounded_rectangle=[px_right, py_start, 210, p_height, 12], width=1.2)

        # Title
        chave = "PANEL_PRESETS_BASS" if self.effective_mode == "BASS" else "PANEL_PRESETS_GUITAR"
        titulo = t(chave, self.lang)
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

            row_color = main_color if is_selected else STEEL

            # Cápsula acesa atrás da linha selecionada
            if is_selected:
                self._rounded_rect(rx, ry_min + 3, rw, row_h - 6, with_alpha(GREEN, 0.08), 8)
                with self.canvas:
                    Color(*with_alpha(GREEN, 0.25))
                    Line(rounded_rectangle=[rx, ry_min + 3, rw, row_h - 6, 8], width=1.0)

            # LED
            with self.canvas:
                if is_selected:
                    Color(*GREEN)
                    Ellipse(pos=(px_right + 20, ry - 5), size=(10, 10))
                    Color(*with_alpha(GREEN, 0.25))
                    Line(circle=(px_right + 25, ry, 9), width=1.5)
                else:
                    Color(*BORDER)
                    Line(circle=(px_right + 25, ry, 5), width=1.5)

            f_nota, f_lbl = self.row_font_size(row_h)

            note_txt_col = CREAM if is_selected else LABEL
            self._text(note_key, px_right + 42, ry - f_nota * 0.42, f_nota, note_txt_col, bold=True, align="left", cache=True)

            lbl_txt_col = with_alpha(CREAM, 0.75) if is_selected else STEEL
            self._text(t(note_label, self.lang), px_right + 42, ry - f_nota * 0.42 - f_lbl - 4, f_lbl, lbl_txt_col, bold=False, align="left", cache=True)

            self._text(f"{target_hz:.1f} Hz", px_right + 192, ry - f_lbl * 0.5, f_lbl + 2, row_color, align="right", cache=True, font=FONT_NUM)

        # Botão AUTO MODE / RESET LOCK
        btn_x, btn_y, btn_w, btn_h = self.reset_button_rect(px_right, py_start)

        if self.selected_preset is not None:
            btn_bg = (0.00, 1.00, 0.40, 0.08)
            btn_brd = (0.00, 1.00, 0.40, 0.6)
            btn_txt = t("RESET_LOCK", self.lang)
            btn_color = GREEN
        else:
            btn_bg = with_alpha(INK, 0.35)
            btn_brd = with_alpha(BORDER, 0.55)
            btn_txt = t("AUTO_MODE", self.lang)
            btn_color = STEEL

        self._rounded_rect(btn_x, btn_y, btn_w, btn_h, btn_bg, 8)
        with self.canvas:
            Color(*btn_brd)
            Line(rounded_rectangle=[btn_x, btn_y, btn_w, btn_h, 8], width=1)
        self._text(btn_txt, btn_x + btn_w / 2, btn_y + 8, 10, btn_color, bold=True, align="center", cache=True)

    def draw_footer(self, w, h):
        self._line([24, 34, w - 24, 34], BORDER, 1.0)
        self._text(t("FOOTER_LEFT", self.lang), 24, 15, 9, STEEL, bold=True, align="left", cache=True)
        self._text(f"A4 {self.a4:.0f} HZ   /   {FS/1000:.1f} KHZ   /   {BLOCKSIZE}", w - 24, 15, 9, STEEL, bold=True, align="right", cache=True)

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

        # 1. Botão de idioma
        lx, ly, lw, lh = self.lang_button_rect(w, h)
        if lx <= touch.x <= lx + lw and ly <= touch.y <= ly + lh:
            self.lang = next_language(self.lang)
            print(f"[TUNER] Idioma: {self.lang}")
            return True

        # 2. Seletor de afinação de referência
        for a4, bx, by, bw, bh in self.reference_button_rects(geo["px_left"], py_start, p_height):
            if bx <= touch.x <= bx + bw and by <= touch.y <= by + bh:
                if a4 != self.a4:
                    self.a4 = a4
                    self.needs_history_reset = True  # alvos mudaram: descarta leitura antiga
                    print(f"[TUNER] Afinação de referência: A4 = {a4:.0f} Hz")
                return True

        # 3. Barra de modos no header
        for mode_name, bx, by, bw, bh in self.mode_button_rects(w, h):
            if bx <= touch.x <= bx + bw and by <= touch.y <= by + bh:
                self.selected_preset = None
                self.tuner_mode = mode_name
                self.base_mode = mode_name
                self.needs_history_reset = True  # Flush stale history on mode switch
                print(f"[TUNER] Active mode set to {mode_name}")
                return True

        # 4. Painel direito
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
            a4=self.ui.a4,
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
        """Alinha o pipeline com modo, preset e afinação de referência da UI."""
        if self.pipeline.a4 != self.ui.a4:
            self.pipeline.set_reference_pitch(self.ui.a4)

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
