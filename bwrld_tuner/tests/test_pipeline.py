"""
tests/test_pipeline.py — Testes para core/pipeline.py

Cobre a sequência gate -> suavização -> engine que antes vivia solta dentro do
callback do sounddevice e não tinha teste nenhum.

O parâmetro `now` é sempre passado explicitamente: os testes controlam o tempo,
nunca dependem de time.time().
"""
import pytest

from core.gate import GateState
from core.pipeline import TunerPipeline

GOOD_RMS = 0.05
GOOD_CLARITY = 0.7


def feed(pipe, freq, n=7, t0=0.0, step=0.09):
    """Alimenta n quadros bons e devolve o último resultado."""
    result = None
    for i in range(n):
        result = pipe.process(freq, GOOD_RMS, GOOD_CLARITY, now=t0 + i * step)
    return result


# ── caminho feliz ─────────────────────────────────────────────────────────────

def test_guitar_e2_returns_active_result():
    pipe = TunerPipeline(mode="GUITAR")
    result = feed(pipe, 82.41)
    assert result.active is True
    assert result.note == "E2"
    assert result.raw_cents == pytest.approx(0.0, abs=0.5)


def test_string_name_comes_filled():
    pipe = TunerPipeline(mode="GUITAR")
    result = feed(pipe, 82.41)
    assert result.string_name == "STRING_6"  # chave de i18n, não texto


def test_bass_e1_survives_pipeline():
    pipe = TunerPipeline(mode="BASS")
    result = feed(pipe, 41.20)
    assert result.note == "E1"
    assert result.active is True


def test_drop_d_keeps_large_deviation():
    """Corda ainda em E2 no DROP D não pode ser descartada como outlier."""
    pipe = TunerPipeline(mode="DROP D")
    result = feed(pipe, 82.41)
    assert result.active is True
    assert result.note == "D2"
    assert result.status == "DROP_A_LOT"


# ── suavização ────────────────────────────────────────────────────────────────

def test_single_outlier_frame_is_smoothed_away():
    """Um quadro perdido no meio de leituras boas não pode mover a nota."""
    pipe = TunerPipeline(mode="GUITAR")
    for i, f in enumerate([110.0, 110.0, 110.0, 155.0, 110.0, 110.0, 110.0]):
        result = pipe.process(f, GOOD_RMS, GOOD_CLARITY, now=i * 0.09)
    assert result.note == "A2"
    assert result.freq == pytest.approx(110.0)


def test_mode_change_clears_history():
    pipe = TunerPipeline(mode="GUITAR")
    feed(pipe, 329.63)          # enche o histórico com E4
    pipe.set_mode("BASS")
    result = pipe.process(41.20, GOOD_RMS, GOOD_CLARITY, now=1.0)
    # Sem o clear, a mediana ainda estaria presa perto de 329 Hz
    assert result.freq == pytest.approx(41.20)
    assert result.note == "E1"


# ── gate: HOLD e STANDBY ──────────────────────────────────────────────────────

def test_silence_right_after_signal_holds():
    pipe = TunerPipeline(mode="GUITAR", hold_time=0.75)
    feed(pipe, 82.41, n=3, t0=0.0)
    assert pipe.process(None, 0.0, 0.0, now=0.5) is None
    assert pipe.gate_state is GateState.HOLD


def test_silence_past_hold_time_goes_standby():
    pipe = TunerPipeline(mode="GUITAR", hold_time=0.75)
    feed(pipe, 82.41, n=3, t0=0.0)
    result = pipe.process(None, 0.0, 0.0, now=5.0)
    assert result is not None
    assert result.active is False
    assert result.status == "STANDBY"
    assert pipe.gate_state is GateState.STANDBY


def test_standby_clears_history():
    pipe = TunerPipeline(mode="GUITAR", hold_time=0.75)
    feed(pipe, 329.63, n=7, t0=0.0)     # histórico cheio de E4
    pipe.process(None, 0.0, 0.0, now=5.0)  # cai em STANDBY
    result = pipe.process(82.41, GOOD_RMS, GOOD_CLARITY, now=5.1)
    assert result.freq == pytest.approx(82.41)  # começou limpo, sem arrastar E4


def test_loud_noise_without_pitch_does_not_hold_forever():
    """Ruído alto sem pitch (palhetada abafada) deve cair em STANDBY."""
    pipe = TunerPipeline(mode="GUITAR", hold_time=0.75)
    feed(pipe, 82.41, n=3, t0=0.0)
    result = pipe.process(None, rms=0.9, clarity=0.05, now=5.0)
    assert result is not None
    assert result.active is False


# ── continuidade: erro de oitava e saltos ─────────────────────────────────────

def test_chromatic_stays_active_between_notes():
    """Frequência no meio de dois semitons continua sendo leitura válida."""
    pipe = TunerPipeline(mode="CHROMATIC")
    result = feed(pipe, 453.0)  # entre A4 (440) e A#4 (466)
    assert result.active is True


def test_octave_glitch_does_not_change_the_displayed_note():
    """O caso que o filtro antigo não pegava: detector pulando para o harmônico."""
    pipe = TunerPipeline(mode="GUITAR")
    feed(pipe, 82.41, n=7, t0=0.0)
    result = pipe.process(164.82, GOOD_RMS, GOOD_CLARITY, now=0.7)  # E3 = 2x E2
    assert result.note == "E2"
    assert result.active is True


def test_octave_glitch_does_not_poison_the_median():
    """Rastreador antes da suavização: o blip nem entra no histórico."""
    pipe = TunerPipeline(mode="GUITAR")
    feed(pipe, 82.41, n=7, t0=0.0)
    pipe.process(164.82, GOOD_RMS, GOOD_CLARITY, now=0.7)
    result = pipe.process(82.41, GOOD_RMS, GOOD_CLARITY, now=0.8)
    assert result.freq == pytest.approx(82.41, rel=1e-3)


def test_isolated_garbage_frame_becomes_hold():
    """Salto isolado sem forma de oitava vira HOLD, não leitura errada."""
    pipe = TunerPipeline(mode="GUITAR")
    feed(pipe, 82.41, n=7, t0=0.0)
    assert pipe.process(137.0, GOOD_RMS, GOOD_CLARITY, now=0.7) is None


def test_changing_string_is_picked_up_quickly():
    """Trocar de corda de verdade tem que aparecer rápido, não virar HOLD eterno."""
    pipe = TunerPipeline(mode="GUITAR")
    feed(pipe, 82.41, n=7, t0=0.0)
    quadros = 0
    result = None
    while result is None or not result.active or result.note != "A2":
        quadros += 1
        result = pipe.process(110.0, GOOD_RMS, GOOD_CLARITY, now=0.7 + quadros * 0.09)
        assert quadros < 8, "troca de corda demorou demais"
    assert result.note == "A2"
    assert result.freq == pytest.approx(110.0)  # histórico do E2 não arrastou


def test_standby_resets_the_tracker():
    """Depois do silêncio, a nota nova não é comparada com a referência velha."""
    pipe = TunerPipeline(mode="GUITAR", hold_time=0.75)
    feed(pipe, 82.41, n=7, t0=0.0)
    pipe.process(None, 0.0, 0.0, now=5.0)      # STANDBY
    assert pipe.tracker.reference is None
    result = pipe.process(329.63, GOOD_RMS, GOOD_CLARITY, now=5.1)
    assert result.active is True               # adota direto, sem confirmação
    assert result.note == "E4"


# ── modo MANUAL ───────────────────────────────────────────────────────────────

def test_manual_lock_compares_against_locked_note():
    pipe = TunerPipeline(mode="GUITAR")
    pipe.lock_note("A2")
    result = feed(pipe, 110.0)
    assert result.note == "A2"
    assert result.target == pytest.approx(110.0)


def test_manual_lock_holds_target_even_when_far_off():
    """Travado em E2, tocar D2 deve continuar medindo contra E2."""
    pipe = TunerPipeline(mode="GUITAR")
    pipe.lock_note("E2")
    result = feed(pipe, 73.42)
    assert result.note == "E2"
    assert result.raw_cents < -150


def test_unlock_restores_automatic_mode():
    pipe = TunerPipeline(mode="GUITAR")
    pipe.lock_note("E2")
    pipe.unlock("GUITAR")
    assert pipe.mode == "GUITAR"
    assert pipe.locked_note is None
    result = feed(pipe, 110.0, t0=2.0)
    assert result.note == "A2"


def test_lock_clears_history():
    pipe = TunerPipeline(mode="BASS")
    feed(pipe, 98.0)            # histórico cheio de G2
    pipe.lock_note("E1")
    result = pipe.process(41.20, GOOD_RMS, GOOD_CLARITY, now=1.0)
    assert result.freq == pytest.approx(41.20)


# ── reset ─────────────────────────────────────────────────────────────────────

def test_reset_returns_to_standby():
    pipe = TunerPipeline(mode="GUITAR")
    feed(pipe, 82.41)
    pipe.reset()
    assert pipe.gate_state is GateState.STANDBY
