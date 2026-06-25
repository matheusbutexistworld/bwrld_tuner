"""
core/tuner_engine.py — Engine central do BWRLD Tuner.

Sem kivy, sem sounddevice. Recebe uma frequência detectada e devolve
um TunerResult completo para a UI renderizar.

Concentra:
    - seleção de modo (CHROMATIC, GUITAR, DROP D, BASS, MANUAL)
    - encontrar nota/alvo mais próximo
    - calcular raw_cents e display_cents
    - gerar texto de status
"""
from dataclasses import dataclass, field

from core.notes import (
    cents_between,
    clip_cents,
    find_chromatic_note,
    find_closest_note,
)
from core.tunings import get_notes_dict


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


# Mapeamento de nota → nome de corda (fallback genérico)
_CORDA_MAP: dict[str, str] = {
    "E1": "4ª CORDA", "A1": "3ª CORDA",
    "D2": "2ª CORDA", "G2": "1ª CORDA",
    "E2": "6ª CORDA", "A2": "5ª CORDA",
    "D3": "4ª CORDA", "G3": "3ª CORDA",
    "B3": "2ª CORDA", "E4": "1ª CORDA",
}


def _status_from_cents(raw_cents: float) -> str:
    """Calcula o texto de status a partir do desvio real em cents."""
    a = abs(raw_cents)
    if a <= 3:
        return "PERFECT"
    if a <= 5:
        return "IN TUNE"
    if a <= 12:
        return "SLIGHTLY HIGH" if raw_cents > 0 else "SLIGHTLY LOW"
    if a <= 25:
        return "HIGH" if raw_cents > 0 else "LOW"
    if a <= 80:
        return "VERY HIGH" if raw_cents > 0 else "VERY LOW"
    return "DROP A LOT" if raw_cents > 0 else "TIGHTEN A LOT"


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

    def __init__(self, mode: str = "CHROMATIC"):
        self._mode: str = "CHROMATIC"
        self._locked_note: str | None = None
        self.set_mode(mode)

    # ── configuração ──────────────────────
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
            for tuning_notes in [get_notes_dict("GUITAR"), get_notes_dict("DROP D"), get_notes_dict("BASS")]:
                if self._locked_note in tuning_notes:
                    return self._locked_note, tuning_notes[self._locked_note]
            # Fallback: nota não encontrada
            return self._locked_note, freq

        if mode in {"GUITAR", "DROP D", "BASS"}:
            notes = get_notes_dict(mode)
            return find_closest_note(freq, notes)

        # CHROMATIC
        return find_chromatic_note(freq)

    # ── filtro de outliers (apenas CHROMATIC) ──
    def should_reject(self, raw_cents: float) -> bool:
        """Retorna True se a leitura deve ser descartada como outlier.

        Apenas no modo CHROMATIC: desvios > 85 cents indicam detecção errada.
        Em outros modos, a corda pode estar muito longe do alvo (ex: DROP D).
        """
        return self._mode == "CHROMATIC" and abs(raw_cents) > 85
