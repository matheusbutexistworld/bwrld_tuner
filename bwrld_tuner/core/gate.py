"""
core/gate.py — Gate de sinal com histerese para evitar flicker.

Sem kivy, sem sounddevice. Apenas lógica de estado baseada em RMS/clarity/tempo.

Comportamento:
    - Sinal bom (RMS + clarity ok) -> estado ACTIVE
    - Sinal baixo por < hold_time  -> estado HOLD (mantém última leitura)
    - Sinal baixo por >= hold_time -> estado STANDBY
    - Clarity baixa                -> estado NOISY
"""
import time
from enum import Enum


class GateState(Enum):
    ACTIVE  = "ACTIVE"
    HOLD    = "HOLD"
    STANDBY = "STANDBY"
    NOISY   = "NOISY"


class SignalGate:
    """Gate inteligente com histerese.

    Exemplo de uso:
        gate = SignalGate()
        state = gate.update(rms=0.01, clarity=0.5, now=time.time())
        # -> GateState.ACTIVE
    """

    def __init__(
        self,
        rms_threshold: float = 0.006,
        clarity_threshold: float = 0.18,
        hold_time: float = 0.8,
    ):
        self.rms_threshold = rms_threshold
        self.clarity_threshold = clarity_threshold
        self.hold_time = hold_time
        self._last_good_signal: float = 0.0
        self._state: GateState = GateState.STANDBY

    def update(self, rms: float, clarity: float, now: float | None = None) -> GateState:
        """Atualiza o estado do gate com as leituras atuais.

        Args:
            rms:     Nível RMS do bloco de áudio.
            clarity: Clareza/confiança do pitch detector (0.0–1.0).
            now:     Timestamp atual (usa time.time() se None).

        Returns:
            GateState: Estado atual do gate.
        """
        if now is None:
            now = time.time()

        signal_ok = rms >= self.rms_threshold

        if not signal_ok:
            elapsed = now - self._last_good_signal
            if elapsed < self.hold_time:
                self._state = GateState.HOLD
            else:
                self._state = GateState.STANDBY
            return self._state

        # Sinal presente — verificar clarity
        if clarity < self.clarity_threshold:
            self._last_good_signal = now
            self._state = GateState.NOISY
            return self._state

        # Sinal bom
        self._last_good_signal = now
        self._state = GateState.ACTIVE
        return self._state

    @property
    def state(self) -> GateState:
        return self._state

    def reset(self) -> None:
        """Reseta o gate para STANDBY."""
        self._last_good_signal = 0.0
        self._state = GateState.STANDBY
