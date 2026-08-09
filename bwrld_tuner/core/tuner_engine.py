"""
core/tuner_engine.py — Engine central do BWRLD Tuner.

Sem kivy, sem sounddevice. Recebe uma frequência detectada e devolve
um TunerResult completo para a UI renderizar.

Concentra:
    - seleção de modo (CHROMATIC, GUITAR, DROP D, BASS, MANUAL)
    - encontrar nota/alvo mais próximo
    - calcular raw_cents e display_cents
    - gerar texto de status

Não filtra leitura ruim: isso depende da *sequência* de quadros, não de um
quadro isolado, e vive em core/tracking.py.
"""
from dataclasses import dataclass, field

from core.notes import (
    cents_between,
    clip_cents,
    find_chromatic_note,
    find_closest_note,
)
from core.tunings import A4_STANDARD, get_notes_dict


# ─────────────────────────────────────────
# Resultado que a UI consome
# ─────────────────────────────────────────
@dataclass
class TunerResult:
    note: str          = "---"
    string_name: str   = ""
    freq: float        = 0.0
    target: float      = 0.0
    raw_cents: float   = 0.0
    display_cents: float = 0.0   # Clipado em [-50, +50] para o ponteiro
    status: str        = "STANDBY"
    active: bool       = False


# Mapeamento de nota → chave do rótulo de corda (fallback genérico).
# São chaves de tradução (core/i18n.py), não texto de tela.
_CORDA_MAP: dict[str, str] = {
    "E1": "STRING_4", "A1": "STRING_3",
    "D2": "STRING_2", "G2": "STRING_1",
    "E2": "STRING_6", "A2": "STRING_5",
    "D3": "STRING_4", "G3": "STRING_3",
    "B3": "STRING_2", "E4": "STRING_1",
}


def _status_from_cents(raw_cents: float) -> str:
    """Chave de status a partir do desvio real em cents.

    Retorna chave de tradução, não texto de tela: quem desenha resolve o
    idioma. Ver core/i18n.py.
    """
    a = abs(raw_cents)
    if a <= 3:
        return "PERFECT"
    if a <= 5:
        return "IN_TUNE"
    if a <= 12:
        return "SLIGHTLY_HIGH" if raw_cents > 0 else "SLIGHTLY_LOW"
    if a <= 25:
        return "HIGH" if raw_cents > 0 else "LOW"
    if a <= 80:
        return "VERY_HIGH" if raw_cents > 0 else "VERY_LOW"
    return "DROP_A_LOT" if raw_cents > 0 else "TIGHTEN_A_LOT"


# ─────────────────────────────────────────
# Engine
# ─────────────────────────────────────────
class TunerEngine:
    """Engine que transforma uma frequência detectada em um TunerResult.

    Exemplo:
        engine = TunerEngine(mode="DROP D")
        result = engine.process_frequency(82.41)
        # result.note         -> "D2"
        # result.raw_cents    -> ~+198.0
        # result.status       -> "DROP A LOT"
    """

    VALID_MODES = {"CHROMATIC", "GUITAR", "DROP D", "BASS", "MANUAL"}

    def __init__(self, mode: str = "CHROMATIC", a4: float = A4_STANDARD):
        self._mode: str = "CHROMATIC"
        self._locked_note: str | None = None
        self._a4: float = A4_STANDARD
        self.set_reference_pitch(a4)
        self.set_mode(mode)

    # ── configuração ──────────────────────
    def set_reference_pitch(self, a4: float) -> None:
        """Define a afinação de referência (440, 432, 415...).

        Move todos os alvos junto: a razão entre as cordas não muda, o
        instrumento inteiro desce ou sobe.
        """
        if a4 <= 0:
            raise ValueError(f"Afinação de referência inválida: {a4}")
        self._a4 = float(a4)

    @property
    def a4(self) -> float:
        return self._a4

    def set_mode(self, mode: str) -> None:
        if mode not in self.VALID_MODES:
            raise ValueError(f"Modo inválido: '{mode}'. Válidos: {self.VALID_MODES}")
        self._mode = mode
        if mode != "MANUAL":
            self._locked_note = None

    def lock_note(self, note: str) -> None:
        """Trava o alvo de comparação em uma nota específica (modo MANUAL)."""
        self._locked_note = note
        self._mode = "MANUAL"

    def unlock(self) -> None:
        """Desfaz o travamento manual."""
        self._locked_note = None

    @property
    def mode(self) -> str:
        return self._mode

    @property
    def locked_note(self) -> str | None:
        return self._locked_note

    # ── processamento ─────────────────────
    def process_frequency(self, freq: float) -> TunerResult:
        """Processa uma frequência e retorna um TunerResult.

        Args:
            freq: Frequência detectada em Hz (> 0).

        Returns:
            TunerResult com todos os campos preenchidos.
        """
        if freq <= 0:
            return TunerResult(active=False)

        note, target = self._find_note_and_target(freq)
        raw = cents_between(freq, target)
        display = clip_cents(raw)
        status = _status_from_cents(raw)
        string_name = _CORDA_MAP.get(note, "")

        return TunerResult(
            note=note,
            string_name=string_name,
            freq=freq,
            target=target,
            raw_cents=raw,
            display_cents=display,
            status=status,
            active=True,
        )

    # ── interno ───────────────────────────
    def _find_note_and_target(self, freq: float) -> tuple[str, float]:
        mode = self._mode

        if mode == "MANUAL" and self._locked_note:
            # Busca o alvo da nota travada em todos os tunings disponíveis
            for nome in ("GUITAR", "DROP D", "BASS"):
                tuning_notes = get_notes_dict(nome, self._a4)
                if self._locked_note in tuning_notes:
                    return self._locked_note, tuning_notes[self._locked_note]
            # Fallback: nota não encontrada
            return self._locked_note, freq

        if mode in {"GUITAR", "DROP D", "BASS"}:
            notes = get_notes_dict(mode, self._a4)
            return find_closest_note(freq, notes)

        # CHROMATIC
        return find_chromatic_note(freq, self._a4)
