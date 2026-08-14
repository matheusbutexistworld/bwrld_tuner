"""
tests/test_tracking.py — Testes para core/tracking.py

Cobre o filtro que substitui o antigo `should_reject`, que era inalcançável:
comparar contra a nota alvo nunca pega erro de oitava, porque uma oitava acima
de E2 é E3 — outra nota perfeitamente válida.
"""
import pytest

from core.tracking import PitchEvent, PitchTracker

E2 = 82.41
E3 = 164.82   # E2 uma oitava acima — o erro clássico da autocorrelação
E1 = 41.205   # E2 uma oitava abaixo — o sub-harmônico
A2 = 110.00


def feed(tracker, freqs):
    """Passa uma sequência e devolve a lista de decisões."""
    return [tracker.update(f) for f in freqs]


# ── primeira leitura ──────────────────────────────────────────────────────────

def test_first_reading_is_adopted():
    t = PitchTracker()
    d = t.update(E2)
    assert d.event is PitchEvent.RETUNED
    assert d.freq == pytest.approx(E2)
    assert d.reset_history is True
    assert t.reference == pytest.approx(E2)


def test_invalid_frequency_is_rejected():
    t = PitchTracker()
    for bad in (0.0, -10.0):
        d = t.update(bad)
        assert d.event is PitchEvent.REJECTED
        assert d.freq is None


# ── variação normal ───────────────────────────────────────────────────────────

def test_small_variation_is_accepted():
    t = PitchTracker()
    t.update(E2)
    d = t.update(82.9)
    assert d.event is PitchEvent.ACCEPTED
    assert d.freq == pytest.approx(82.9)
    assert d.reset_history is False


def test_very_flat_string_is_still_normal_variation():
    """Corda um tom abaixo do alvo não pode ser confundida com troca de nota."""
    t = PitchTracker()
    t.update(E2)
    d = t.update(73.42)  # ~-200 cents... acima do limiar de 150
    assert d.event is not PitchEvent.ACCEPTED
    # mas com o limiar afrouxado, é variação normal
    t2 = PitchTracker(jump_cents=250.0)
    t2.update(E2)
    assert t2.update(73.42).event is PitchEvent.ACCEPTED


# ── erro de oitava: o caso central ────────────────────────────────────────────

def test_octave_up_glitch_is_folded_back():
    t = PitchTracker()
    t.update(E2)
    d = t.update(E3)
    assert d.event is PitchEvent.OCTAVE_FIXED
    assert d.freq == pytest.approx(E2, rel=1e-3)
    assert d.reset_history is False


def test_octave_down_glitch_is_folded_back():
    t = PitchTracker()
    t.update(E2)
    d = t.update(E1)
    assert d.event is PitchEvent.OCTAVE_FIXED
    assert d.freq == pytest.approx(E2, rel=1e-3)


def test_two_octave_glitch_is_folded_back():
    t = PitchTracker()
    t.update(E2)
    d = t.update(E2 * 4)
    assert d.event is PitchEvent.OCTAVE_FIXED
    assert d.freq == pytest.approx(E2, rel=1e-3)


def test_octave_glitch_does_not_move_the_reference():
    """O ponto do filtro: um blip de oitava não pode virar a nova referência."""
    t = PitchTracker()
    t.update(E2)
    t.update(E3)
    assert t.reference == pytest.approx(E2)


def test_isolated_octave_glitches_never_confirm():
    """Blips alternados com leituras boas nunca acumulam confirmação."""
    t = PitchTracker()
    t.update(E2)
    for _ in range(10):
        assert t.update(E3).event is PitchEvent.OCTAVE_FIXED
        assert t.update(E2).event is PitchEvent.ACCEPTED
    assert t.reference == pytest.approx(E2)


def test_sustained_octave_change_is_eventually_adopted():
    """Se o músico realmente foi para a oitava, o afinador acompanha."""
    t = PitchTracker(octave_confirm_frames=5)
    t.update(E2)
    events = [t.update(E3).event for _ in range(5)]
    assert events[-1] is PitchEvent.RETUNED
    assert t.reference == pytest.approx(E3)


def test_octave_needs_more_confirmation_than_ordinary_jump():
    """Erro de oitava é o erro mais comum do detector: exige mais evidência."""
    t = PitchTracker(confirm_frames=2, octave_confirm_frames=5)

    t.update(E2)
    ordinario = [t.update(A2).event for _ in range(2)]
    assert ordinario[-1] is PitchEvent.RETUNED

    t.reset()
    t.update(E2)
    oitava = [t.update(E3).event for _ in range(2)]
    assert oitava[-1] is not PitchEvent.RETUNED


# ── salto comum: troca de corda ───────────────────────────────────────────────

def test_isolated_jump_is_rejected():
    t = PitchTracker()
    t.update(E2)
    d = t.update(A2)
    assert d.event is PitchEvent.REJECTED
    assert d.freq is None


def test_repeated_jump_is_adopted_as_new_note():
    t = PitchTracker(confirm_frames=2)
    t.update(E2)
    assert t.update(A2).event is PitchEvent.REJECTED
    d = t.update(A2)
    assert d.event is PitchEvent.RETUNED
    assert d.reset_history is True
    assert t.reference == pytest.approx(A2)


def test_string_change_costs_only_confirm_frames():
    """Trocar de corda não pode demorar: 2 quadros ~= 190 ms a 11 Hz."""
    t = PitchTracker(confirm_frames=2)
    t.update(E2)
    quadros = 0
    while True:
        quadros += 1
        if t.update(A2).event is PitchEvent.RETUNED:
            break
        assert quadros < 10, "troca de corda travou"
    assert quadros == 2


def test_scattered_garbage_never_confirms():
    """Quadros de lixo espalhados não se corroboram entre si."""
    t = PitchTracker(confirm_frames=2)
    t.update(E2)
    for lixo in (137.0, 301.0, 190.0, 411.0, 255.0):
        assert t.update(lixo).event is PitchEvent.REJECTED
    assert t.reference == pytest.approx(E2)


def test_candidate_resets_when_jump_target_changes():
    t = PitchTracker(confirm_frames=2)
    t.update(E2)
    t.update(A2)      # candidato = A2, contagem 1
    t.update(300.0)   # candidato muda, contagem volta a 1
    assert t.update(300.0).event is PitchEvent.RETUNED


# ── reset ─────────────────────────────────────────────────────────────────────

def test_reset_forgets_reference():
    t = PitchTracker()
    t.update(E2)
    t.reset()
    assert t.reference is None
    d = t.update(A2)
    assert d.event is PitchEvent.RETUNED  # sem referência, adota direto


def test_reset_clears_pending_candidate():
    t = PitchTracker(confirm_frames=2)
    t.update(E2)
    t.update(A2)     # candidato pendente
    t.reset()
    t.update(E2)     # nova referência
    assert t.update(A2).event is PitchEvent.REJECTED  # candidato recomeçou


# ── configuração inválida ─────────────────────────────────────────────────────

def test_invalid_confirm_frames_raises():
    with pytest.raises(ValueError):
        PitchTracker(confirm_frames=0)


def test_invalid_max_octaves_raises():
    with pytest.raises(ValueError):
        PitchTracker(max_octaves=0)
