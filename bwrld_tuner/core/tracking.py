"""
core/tracking.py — Continuidade temporal do pitch.

Sem kivy, sem sounddevice, sem numpy: só aritmética escalar, pensada para ser
portada para C++/JUCE sem tradução criativa.

O problema que este módulo resolve
----------------------------------
Detectores por autocorrelação erram principalmente em *oitava*: em vez da
fundamental, travam no 2º harmônico (2x) ou no sub-harmônico (0.5x). Comparar a
leitura contra a nota alvo não pega esse erro — uma oitava acima de E2 é E3,
que também é uma nota perfeitamente válida, a 0 cents de si mesma. O filtro
antigo (`abs(cents) > 85` contra o alvo) era, por isso, inalcançável.

A informação que denuncia o erro não está em *uma* leitura, e sim na relação
entre leituras **consecutivas**: instrumento nenhum salta 1200 cents em 93 ms
sozinho. Então comparamos cada quadro com o anterior, não com a nota alvo.

As quatro decisões
------------------
    ACCEPTED     variação normal em torno da referência -> usa a leitura
    OCTAVE_FIXED salto de ~1200 cents ainda não confirmado -> dobra de volta
    REJECTED     salto isolado sem forma de oitava -> descarta o quadro
    RETUNED      salto que se repetiu -> o músico mudou de nota mesmo

Por que oitava exige mais confirmação
-------------------------------------
Errar a oitava é o erro *mais comum* do detector; tocar exatamente uma oitava
acima é a mudança *menos comum* do músico. Então um salto de oitava precisa se
repetir por mais quadros que um salto qualquer antes de ser levado a sério.
Enquanto não se confirma, a leitura é dobrada para a oitava da referência — o
mostrador continua útil em vez de piscar.
"""
import math
from dataclasses import dataclass
from enum import Enum


class PitchEvent(Enum):
    ACCEPTED = "ACCEPTED"
    OCTAVE_FIXED = "OCTAVE_FIXED"
    REJECTED = "REJECTED"
    RETUNED = "RETUNED"


@dataclass
class PitchDecision:
    """Veredito sobre um quadro.

    Attributes:
        event:         O que aconteceu com a leitura.
        freq:          Frequência a usar; None quando o quadro foi descartado.
        reset_history: True quando a referência mudou de nota e a suavização
                       precisa ser esvaziada para não arrastar a nota anterior.
    """
    event: PitchEvent
    freq: float | None
    reset_history: bool


def _cents(freq: float, reference: float) -> float:
    """Distância em cents entre duas frequências positivas."""
    return 1200.0 * math.log2(freq / reference)


class PitchTracker:
    """Filtra erros de oitava e saltos espúrios olhando a sequência de leituras.

    Exemplo:
        tracker = PitchTracker()
        tracker.update(82.41)          # RETUNED  — primeira leitura
        tracker.update(82.50)          # ACCEPTED — variação normal
        tracker.update(164.82).freq    # 82.41    — erro de oitava, dobrado
    """

    def __init__(
        self,
        jump_cents: float = 150.0,
        octave_tolerance_cents: float = 60.0,
        confirm_tolerance_cents: float = 100.0,
        confirm_frames: int = 2,
        octave_confirm_frames: int = 5,
        max_octaves: int = 2,
    ):
        """
        Args:
            jump_cents:              Desvio máximo tratado como variação normal.
                                     150 = um tom e meio; cobre corda muito
                                     desafinada sem cobrir troca de corda.
            octave_tolerance_cents:  Tolerância para reconhecer um salto como
                                     múltiplo de oitava.
            confirm_tolerance_cents: Proximidade exigida entre quadros para eles
                                     contarem como a "mesma" nota candidata.
            confirm_frames:          Quadros para confirmar um salto comum.
            octave_confirm_frames:   Quadros para confirmar um salto de oitava.
            max_octaves:             Maior erro de oitava corrigível (2 = 4x/¼x).
        """
        if confirm_frames < 1 or octave_confirm_frames < 1:
            raise ValueError("confirm_frames deve ser >= 1.")
        if max_octaves < 1:
            raise ValueError("max_octaves deve ser >= 1.")

        self.jump_cents = jump_cents
        self.octave_tolerance_cents = octave_tolerance_cents
        self.confirm_tolerance_cents = confirm_tolerance_cents
        self.confirm_frames = confirm_frames
        self.octave_confirm_frames = octave_confirm_frames
        self.max_octaves = max_octaves

        self._reference: float | None = None
        self._candidate: float | None = None
        self._candidate_count: int = 0

    # ── estado ────────────────────────────
    @property
    def reference(self) -> float | None:
        """Última frequência aceita, ou None se o rastreador está zerado."""
        return self._reference

    def reset(self) -> None:
        """Esquece tudo. Chamar ao entrar em STANDBY ou ao trocar de modo."""
        self._reference = None
        self._candidate = None
        self._candidate_count = 0

    # ── processamento ─────────────────────
    def update(self, freq: float) -> PitchDecision:
        """Avalia uma frequência recém-detectada contra o histórico recente."""
        if freq is None or freq <= 0:
            return PitchDecision(PitchEvent.REJECTED, None, False)

        if self._reference is None:
            return self._adopt(freq)

        delta = _cents(freq, self._reference)

        # 1. Variação normal: a corda está apenas desafinada ou vibrando.
        if abs(delta) <= self.jump_cents:
            self._reference = freq
            self._candidate = None
            self._candidate_count = 0
            return PitchDecision(PitchEvent.ACCEPTED, freq, False)

        # 2. Salto. Tem forma de erro de oitava?
        octaves = round(delta / 1200.0)
        is_octave = (
            octaves != 0
            and abs(octaves) <= self.max_octaves
            and abs(delta - octaves * 1200.0) <= self.octave_tolerance_cents
        )

        # 3. O salto se repete? Só então é mudança real de nota.
        if self._candidate is not None and abs(_cents(freq, self._candidate)) <= self.confirm_tolerance_cents:
            self._candidate_count += 1
        else:
            self._candidate = freq
            self._candidate_count = 1

        needed = self.octave_confirm_frames if is_octave else self.confirm_frames
        if self._candidate_count >= needed:
            return self._adopt(freq)

        # 4. Ainda não confirmado.
        if is_octave:
            # Dobra para a oitava da referência: leitura aproveitável, sem piscar.
            return PitchDecision(PitchEvent.OCTAVE_FIXED, freq / (2.0 ** octaves), False)

        return PitchDecision(PitchEvent.REJECTED, None, False)

    # ── interno ───────────────────────────
    def _adopt(self, freq: float) -> PitchDecision:
        """Assume freq como nova referência e pede limpeza do histórico."""
        self._reference = freq
        self._candidate = None
        self._candidate_count = 0
        return PitchDecision(PitchEvent.RETUNED, freq, True)
