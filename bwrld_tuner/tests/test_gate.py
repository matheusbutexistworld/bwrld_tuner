"""
tests/test_gate.py — Testes para core/gate.py
"""
import pytest
from core.gate import SignalGate, GateState


RMS_OK = 0.01
RMS_LOW = 0.001
CLARITY_OK = 0.5
CLARITY_LOW = 0.05
T0 = 1000.0   # timestamp base fixo para testes determinísticos


def test_good_signal_returns_active():
    gate = SignalGate()
    state = gate.update(rms=RMS_OK, clarity=CLARITY_OK, now=T0)
    assert state == GateState.ACTIVE

def test_low_rms_within_hold_time_returns_hold():
    gate = SignalGate(hold_time=0.8)
    # Primeiro, sinal bom para registrar last_good_signal
    gate.update(rms=RMS_OK, clarity=CLARITY_OK, now=T0)
    # Depois, sinal fraco mas dentro do hold_time
    state = gate.update(rms=RMS_LOW, clarity=CLARITY_OK, now=T0 + 0.3)
    assert state == GateState.HOLD

def test_low_rms_after_hold_time_returns_standby():
    gate = SignalGate(hold_time=0.8)
    gate.update(rms=RMS_OK, clarity=CLARITY_OK, now=T0)
    state = gate.update(rms=RMS_LOW, clarity=CLARITY_OK, now=T0 + 1.5)
    assert state == GateState.STANDBY

def test_low_clarity_returns_noisy():
    gate = SignalGate()
    state = gate.update(rms=RMS_OK, clarity=CLARITY_LOW, now=T0)
    assert state == GateState.NOISY

def test_initial_state_is_standby():
    gate = SignalGate()
    assert gate.state == GateState.STANDBY

def test_reset_returns_to_standby():
    gate = SignalGate()
    gate.update(rms=RMS_OK, clarity=CLARITY_OK, now=T0)
    assert gate.state == GateState.ACTIVE
    gate.reset()
    assert gate.state == GateState.STANDBY

def test_good_signal_after_silence_recovers():
    gate = SignalGate(hold_time=0.8)
    gate.update(rms=RMS_OK, clarity=CLARITY_OK, now=T0)
    gate.update(rms=RMS_LOW, clarity=CLARITY_OK, now=T0 + 2.0)   # standby
    state = gate.update(rms=RMS_OK, clarity=CLARITY_OK, now=T0 + 3.0)  # recupera
    assert state == GateState.ACTIVE

def test_noisy_signal_updates_last_good():
    """Sinal NOISY ainda conta como sinal presente (não zera hold)."""
    gate = SignalGate(hold_time=0.8)
    gate.update(rms=RMS_OK, clarity=CLARITY_LOW, now=T0)   # NOISY
    # 0.5s depois, sinal apaga — ainda está dentro do hold_time
    state = gate.update(rms=RMS_LOW, clarity=CLARITY_OK, now=T0 + 0.5)
    assert state == GateState.HOLD

def test_custom_thresholds():
    gate = SignalGate(rms_threshold=0.02, clarity_threshold=0.3)
    # RMS suficiente mas clarity abaixo do threshold custom
    state = gate.update(rms=0.05, clarity=0.25, now=T0)
    assert state == GateState.NOISY
