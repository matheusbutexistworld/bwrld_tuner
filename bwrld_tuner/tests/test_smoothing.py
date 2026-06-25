"""
tests/test_smoothing.py — Testes para core/smoothing.py
"""
import pytest
from core.smoothing import MedianSmoother


def test_median_basic():
    s = MedianSmoother(maxlen=7)
    for v in [1.0, 2.0, 100.0]:
        s.add(v)
    assert s.value() == pytest.approx(2.0)

def test_median_single_value():
    s = MedianSmoother(maxlen=7)
    s.add(42.0)
    assert s.value() == pytest.approx(42.0)

def test_empty_returns_none():
    s = MedianSmoother(maxlen=7)
    assert s.value() is None

def test_clear_empties_buffer():
    s = MedianSmoother(maxlen=7)
    s.add(1.0)
    s.add(2.0)
    s.clear()
    assert s.value() is None
    assert len(s) == 0

def test_maxlen_respected():
    s = MedianSmoother(maxlen=3)
    for v in [10.0, 20.0, 30.0, 40.0]:
        s.add(v)
    # Com maxlen=3, apenas os últimos 3 valores: [20, 30, 40]
    assert s.value() == pytest.approx(30.0)
    assert len(s) == 3

def test_maxlen_property():
    s = MedianSmoother(maxlen=5)
    assert s.maxlen == 5

def test_invalid_maxlen_raises():
    with pytest.raises(ValueError):
        MedianSmoother(maxlen=0)

def test_stable_signal():
    s = MedianSmoother(maxlen=7)
    for _ in range(7):
        s.add(100.0)
    assert s.value() == pytest.approx(100.0)

def test_outlier_resistance():
    """Mediana deve ignorar um pico isolado."""
    s = MedianSmoother(maxlen=7)
    for v in [100.0, 100.0, 100.0, 999.0, 100.0, 100.0, 100.0]:
        s.add(v)
    assert s.value() == pytest.approx(100.0)
