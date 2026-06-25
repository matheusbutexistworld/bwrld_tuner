"""
tests/test_tuner_engine.py — Testes para core/tuner_engine.py
"""
import pytest
from core.tuner_engine import TunerEngine, TunerResult


# ── modo GUITAR ────────────────────────────────────────────────────────────────

def test_guitar_mode_e2_detects_e2():
    engine = TunerEngine(mode="GUITAR")
    result = engine.process_frequency(82.41)
    assert result.active is True
    assert result.note == "E2"
    assert result.target == pytest.approx(82.41)

def test_guitar_mode_a2():
    engine = TunerEngine(mode="GUITAR")
    result = engine.process_frequency(110.0)
    assert result.note == "A2"


# ── modo DROP D ────────────────────────────────────────────────────────────────

def test_drop_d_with_e2_returns_d2():
    """Corda ainda em E2 (82.41 Hz) deve ser mapeada para D2 no DROP D."""
    engine = TunerEngine(mode="DROP D")
    result = engine.process_frequency(82.41)
    assert result.note == "D2"

def test_drop_d_with_e2_has_large_positive_cents():
    engine = TunerEngine(mode="DROP D")
    result = engine.process_frequency(82.41)
    assert result.raw_cents > 150

def test_drop_d_with_e2_status_is_drop_a_lot():
    engine = TunerEngine(mode="DROP D")
    result = engine.process_frequency(82.41)
    assert result.status == "DROP A LOT"

def test_drop_d_display_cents_clipped():
    engine = TunerEngine(mode="DROP D")
    result = engine.process_frequency(82.41)
    assert -50.0 <= result.display_cents <= 50.0


# ── modo BASS ─────────────────────────────────────────────────────────────────

def test_bass_e1():
    engine = TunerEngine(mode="BASS")
    result = engine.process_frequency(41.20)
    assert result.note == "E1"
    assert result.active is True

def test_bass_g2():
    engine = TunerEngine(mode="BASS")
    result = engine.process_frequency(98.0)
    assert result.note == "G2"


# ── modo CHROMATIC ────────────────────────────────────────────────────────────

def test_chromatic_a4():
    engine = TunerEngine(mode="CHROMATIC")
    result = engine.process_frequency(440.0)
    assert result.note == "A4"
    assert result.raw_cents == pytest.approx(0.0, abs=0.01)

def test_chromatic_e2():
    engine = TunerEngine(mode="CHROMATIC")
    result = engine.process_frequency(82.41)
    assert result.note == "E2"


# ── raw_cents vs display_cents ────────────────────────────────────────────────

def test_raw_cents_is_unclipped():
    engine = TunerEngine(mode="DROP D")
    result = engine.process_frequency(82.41)
    # raw deve ser maior que 50
    assert result.raw_cents > 50.0

def test_display_cents_max_50():
    engine = TunerEngine(mode="DROP D")
    result = engine.process_frequency(82.41)
    assert result.display_cents <= 50.0

def test_display_cents_min_minus50():
    # Tocar uma nota muito abaixo do alvo
    engine = TunerEngine(mode="GUITAR")
    result = engine.process_frequency(50.0)  # bem abaixo de E2=82.41
    assert result.display_cents >= -50.0


# ── modo MANUAL ───────────────────────────────────────────────────────────────

def test_manual_lock_a2():
    engine = TunerEngine(mode="GUITAR")
    engine.lock_note("A2")
    result = engine.process_frequency(110.0)
    assert result.note == "A2"
    assert result.raw_cents == pytest.approx(0.0, abs=0.5)

def test_manual_unlock_restores_guitar():
    engine = TunerEngine(mode="GUITAR")
    engine.lock_note("A2")
    engine.unlock()
    assert engine.locked_note is None
    assert engine.mode == "MANUAL"  # mode permanece MANUAL até set_mode ser chamado


# ── outlier rejection ─────────────────────────────────────────────────────────

def test_chromatic_rejects_large_cents():
    engine = TunerEngine(mode="CHROMATIC")
    result = engine.process_frequency(82.41)
    assert not engine.should_reject(result.raw_cents)  # E2 em CHROMATIC é válido

def test_drop_d_never_rejects():
    engine = TunerEngine(mode="DROP D")
    # mesmo com desvio gigante, DROP D não deve rejeitar
    result = engine.process_frequency(82.41)
    assert engine.should_reject(result.raw_cents) is False


# ── zero/inválido ──────────────────────────────────────────────────────────────

def test_zero_frequency_returns_inactive():
    engine = TunerEngine()
    result = engine.process_frequency(0.0)
    assert result.active is False

def test_invalid_mode_raises():
    with pytest.raises(ValueError):
        TunerEngine(mode="UKULELE")
