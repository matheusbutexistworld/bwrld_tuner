"""
core/smoothing.py — Suavização de frequência e cents por mediana.

Sem kivy, sem sounddevice. Apenas lógica de buffer com deque.
"""
from collections import deque
import numpy as np


class MedianSmoother:
    """Suaviza valores usando a mediana de uma janela deslizante.

    Exemplo de uso:
        smoother = MedianSmoother(maxlen=7)
        smoother.add(100.0)
        smoother.add(101.0)
        smoother.add(99.0)
        print(smoother.value())  # 100.0
    """

    def __init__(self, maxlen: int = 7):
        if maxlen < 1:
            raise ValueError("maxlen deve ser >= 1.")
        self._buf: deque[float] = deque(maxlen=maxlen)
        self._maxlen = maxlen

    def add(self, value: float) -> None:
        """Adiciona um novo valor ao buffer."""
        self._buf.append(float(value))

    def value(self) -> float | None:
        """Retorna a mediana atual do buffer. None se o buffer estiver vazio."""
        if not self._buf:
            return None
        return float(np.median(list(self._buf)))

    def clear(self) -> None:
        """Limpa o histórico (ex: após troca de modo ou preset)."""
        self._buf.clear()

    def __len__(self) -> int:
        return len(self._buf)

    @property
    def maxlen(self) -> int:
        return self._maxlen
