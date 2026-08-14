"""
core/pitch_detection.py — Interface de detecção de pitch.

Sem kivy, sem sounddevice. Apenas tipagem e contrato da função de detecção.

A implementação real fica em tuner_pro.py (existente).
Este módulo define o protocolo para futura substituição/teste.
"""
from typing import Protocol
import numpy as np


class PitchDetector(Protocol):
    """Protocolo para detectores de pitch intercambiáveis."""

    def detect(
        self,
        audio: np.ndarray,
        fs: int,
        min_freq: float = 55.0,
        max_freq: float = 500.0,
    ) -> tuple[float | None, float, float]:
        """Analisa um bloco de áudio e retorna (freq, rms, clarity).

        Args:
            audio:    Array de amostras mono (float).
            fs:       Taxa de amostragem (Hz).
            min_freq: Frequência mínima a detectar.
            max_freq: Frequência máxima a detectar.

        Returns:
            (freq, rms, clarity)
            - freq: Frequência fundamental detectada, ou None se sinal fraco.
            - rms:  Nível de amplitude (0.0+).
            - clarity: Confiança/autocorrelação do pitch (0.0–1.0).
        """
        ...
