"""
tests/test_tunings.py — Testes para core/tunings.py
"""
import pytest
from core.tunings import TUNINGS, get_tuning, get_notes_dict, get_min_freq


# ── estrutura dos presets ──────────────────────────────────────────────────────

def test_guitar_has_6_strings():
    strings = get_tuning("GUITAR")
    assert len(strings) == 6

def test_drop_d_has_6_strings():
    strings = get_tuning("DROP D")
    assert len(strings) == 6

def test_bass_has_4_strings():
    strings = get_tuning("BASS")
    assert len(strings) == 4


# ── frequências específicas ────────────────────────────────────────────────────

def test_guitar_6th_string_is_e2():
    strings = get_tuning("GUITAR")
    last_note, _label, last_freq = strings[-1]
    assert last_note == "E2"
    assert last_freq == pytest.approx(82.41)

def test_drop_d_6th_string_is_d2():
    strings = get_tuning("DROP D")
    last_note, _label, last_freq = strings[-1]
    assert last_note == "D2"
    assert last_freq == pytest.approx(73.42)

def test_bass_lowest_string_is_e1():
    strings = get_tuning("BASS")
    last_note, _label, last_freq = strings[-1]
    assert last_note == "E1"
    assert last_freq == pytest.approx(41.20)

def test_bass_highest_string_is_g2():
    strings = get_tuning("BASS")
    first_note, _label, first_freq = strings[0]
    assert first_note == "G2"
    assert first_freq == pytest.approx(98.00)


# ── get_notes_dict ─────────────────────────────────────────────────────────────

def test_get_notes_dict_guitar_contains_e2():
    d = get_notes_dict("GUITAR")
    assert "E2" in d
    assert d["E2"] == pytest.approx(82.41)

def test_get_notes_dict_drop_d_contains_d2_not_e2():
    d = get_notes_dict("DROP D")
    assert "D2" in d
    assert "E2" not in d


# ── erros ─────────────────────────────────────────────────────────────────────

def test_get_tuning_unknown_mode_raises():
    with pytest.raises(KeyError):
        get_tuning("UKULELE")


# ── get_min_freq ──────────────────────────────────────────────────────────────

def test_min_freq_bass_is_30():
    assert get_min_freq("BASS") == 30.0

def test_min_freq_guitar_is_55():
    assert get_min_freq("GUITAR") == 55.0

def test_min_freq_chromatic_is_55():
    assert get_min_freq("CHROMATIC") == 55.0
