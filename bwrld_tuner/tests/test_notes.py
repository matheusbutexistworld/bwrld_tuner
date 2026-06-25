"""
tests/test_notes.py — Testes para core/notes.py
"""
import pytest
from core.notes import cents_between, clip_cents, find_chromatic_note, find_closest_note


# ── cents_between ──────────────────────────────────────────────────────────────

def test_cents_between_unison():
    assert cents_between(82.41, 82.41) == pytest.approx(0.0, abs=0.01)

def test_cents_between_octave_up():
    # Uma oitava acima = +1200 cents exatos
    assert cents_between(440.0, 220.0) == pytest.approx(1200.0, abs=0.01)

def test_cents_between_octave_down():
    assert cents_between(220.0, 440.0) == pytest.approx(-1200.0, abs=0.01)

def test_cents_between_e2_vs_d2():
    # E2 = 82.41 Hz, D2 = 73.42 Hz — diferença grande positiva (~198 cents)
    result = cents_between(82.41, 73.42)
    assert result > 150
    assert result < 250

def test_cents_between_zero_freq_returns_zero():
    assert cents_between(0.0, 82.41) == 0.0
    assert cents_between(82.41, 0.0) == 0.0


# ── clip_cents ─────────────────────────────────────────────────────────────────

def test_clip_cents_upper():
    assert clip_cents(200.0) == 50.0

def test_clip_cents_lower():
    assert clip_cents(-200.0) == -50.0

def test_clip_cents_inside():
    assert clip_cents(25.0) == 25.0
    assert clip_cents(-10.0) == -10.0

def test_clip_cents_exactly_at_boundary():
    assert clip_cents(50.0) == 50.0
    assert clip_cents(-50.0) == -50.0


# ── find_closest_note ──────────────────────────────────────────────────────────

def test_find_closest_note_exact():
    notes = {"A2": 110.0, "E2": 82.41, "D2": 73.42}
    note, freq = find_closest_note(82.41, notes)
    assert note == "E2"
    assert freq == pytest.approx(82.41)

def test_find_closest_note_between_two():
    # Frequência entre E2 e A2 — deve escolher a mais próxima
    notes = {"E2": 82.41, "A2": 110.0}
    note, _ = find_closest_note(90.0, notes)
    # 90 está mais perto de 82.41 que de 110
    assert note == "E2"

def test_find_closest_note_empty_raises():
    with pytest.raises(ValueError):
        find_closest_note(82.41, {})


# ── find_chromatic_note ────────────────────────────────────────────────────────

def test_find_chromatic_note_a4():
    note, freq = find_chromatic_note(440.0)
    assert note == "A4"
    assert freq == pytest.approx(440.0, abs=0.01)

def test_find_chromatic_note_e2():
    note, freq = find_chromatic_note(82.41)
    assert note == "E2"
    assert freq == pytest.approx(82.41, abs=0.5)

def test_find_chromatic_note_zero():
    note, freq = find_chromatic_note(0.0)
    assert note == "---"
    assert freq == 0.0
