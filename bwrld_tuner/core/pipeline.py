"""
core/pipeline.py — Orquestração pura de um quadro de áudio.

Sem kivy, sem sounddevice. Recebe (freq, rms, clarity) já extraídos pelo
detector de pitch e devolve o que a UI deve desenhar.

Junta as quatro peças já testadas isoladamente:

    PitchTracker   -> corrige erro de oitava e descarta salto espúrio
    SignalGate     -> decide ACTIVE / HOLD / STANDBY (histerese)
    MedianSmoother -> estabiliza a frequência antes de virar nota
    TunerEngine    -> transforma frequência em nota/cents/status

A ordem importa: o rastreador vem antes da suavização, senão um único quadro
com erro de oitava contamina a mediana por meio segundo.

Contrato de process():

    TunerResult(active=True)  -> desenhar a leitura nova
    TunerResult(active=False) -> ir para STANDBY
    None                      -> HOLD: manter o último quadro na tela

Antes da V6.2 essa sequência vivia dentro do callback do sounddevice, o que
deixava o histórico de frequências sendo escrito por uma thread e limpo por
outra. Aqui ela é síncrona e sem estado compartilhado: quem chama garante que
só uma thread usa a instância.
"""
from core.gate import GateState, SignalGate
from core.smoothing import MedianSmoother
from core.tracking import PitchTracker
from core.tuner_engine import TunerEngine, TunerResult
from core.tunings import A4_STANDARD


class TunerPipeline:
    """Fluxo completo de um quadro: gate -> suavização -> engine.

    Exemplo:
        pipe = TunerPipeline(mode="GUITAR")
        result = pipe.process(freq=82.41, rms=0.02, clarity=0.6, now=0.0)
        # result.note -> "E2"
    """

    def __init__(
        self,
        mode: str = "CHROMATIC",
        history_size: int = 7,
        hold_time: float = 0.75,
        rms_threshold: float = 0.006,
        clarity_threshold: float = 0.18,
        a4: float = A4_STANDARD,
    ):
        self._engine = TunerEngine(mode, a4=a4)
        self._gate = SignalGate(
            rms_threshold=rms_threshold,
            clarity_threshold=clarity_threshold,
            hold_time=hold_time,
        )
        self._smoother = MedianSmoother(maxlen=history_size)
        self._tracker = PitchTracker()

    # ── estado ────────────────────────────
    @property
    def mode(self) -> str:
        return self._engine.mode

    @property
    def locked_note(self) -> str | None:
        return self._engine.locked_note

    @property
    def gate_state(self) -> GateState:
        return self._gate.state

    @property
    def tracker(self) -> PitchTracker:
        """Rastreador de continuidade — exposto para ajuste fino e inspeção."""
        return self._tracker

    # ── configuração ──────────────────────
    @property
    def a4(self) -> float:
        return self._engine.a4

    def set_reference_pitch(self, a4: float) -> None:
        """Troca a afinação de referência e descarta o histórico.

        Sem o clear, a mediana das leituras da referência antiga arrastaria
        a nota por meio segundo depois da troca.
        """
        self._engine.set_reference_pitch(a4)
        self._clear_history()

    def set_mode(self, mode: str) -> None:
        """Troca o modo e descarta o histórico (evita arrastar leitura antiga)."""
        self._engine.set_mode(mode)
        self._clear_history()

    def lock_note(self, note: str) -> None:
        """Trava o alvo em uma corda específica (modo MANUAL)."""
        self._engine.lock_note(note)
        self._clear_history()

    def unlock(self, fallback_mode: str) -> None:
        """Destrava e volta para o modo automático informado."""
        self._engine.unlock()
        self.set_mode(fallback_mode)

    def reset(self) -> None:
        """Zera histórico e gate (volta para STANDBY)."""
        self._clear_history()
        self._gate.reset()

    def _clear_history(self) -> None:
        """Esvazia suavização e rastreador — a próxima leitura começa do zero."""
        self._smoother.clear()
        self._tracker.reset()

    # ── processamento ─────────────────────
    def process(
        self,
        freq: float | None,
        rms: float,
        clarity: float,
        now: float | None = None,
    ) -> TunerResult | None:
        """Processa um quadro de áudio.

        Args:
            freq:    Frequência detectada, ou None se o detector não achou pitch.
            rms:     Nível RMS do bloco.
            clarity: Confiança do detector (0.0–1.0).
            now:     Timestamp (usa time.time() se None).

        Returns:
            TunerResult ativo, TunerResult inativo (STANDBY), ou None (HOLD).
        """
        tracked = None
        if freq is not None and freq > 0:
            decision = self._tracker.update(freq)
            if decision.reset_history:
                # Nota nova confirmada: a mediana da nota anterior só atrasaria.
                self._smoother.clear()
            tracked = decision.freq  # None quando o quadro foi descartado

        usable = tracked is not None

        # O gate mede "há pitch utilizável?", não apenas "há som?". Sem pitch,
        # alimentamos rms=0 para que ruído alto (palhetada abafada, manuseio do
        # instrumento) não segure a última nota na tela indefinidamente.
        state = self._gate.update(rms if usable else 0.0, clarity, now)

        if not usable:
            if state is GateState.STANDBY:
                self._clear_history()
                return TunerResult(status="STANDBY", active=False)
            return None  # HOLD — mantém o último quadro

        self._smoother.add(tracked)
        smooth_freq = self._smoother.value()
        return self._engine.process_frequency(smooth_freq)
