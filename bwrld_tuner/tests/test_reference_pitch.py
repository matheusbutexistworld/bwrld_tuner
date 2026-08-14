"""
tests/test_reference_pitch.py — Afinação de referência (A4 = 440 / 432 / 415).

Trocar a referência move todos os alvos juntos: a razão entre as cordas não
muda, o instrumento inteiro desce ou sobe.
"""
import pytest

from core.notes import cents_between, find_chromatic_note, note_frequency_from_midi
from core.pipeline import TunerPipeline
from core.tuner_engine import TunerEngine
from core.tunings import (
    A4_STANDARD,
    REFERENCE_PITCHES,
    get_notes_dict,
    get_tuning,
)


# ── constantes ────────────────────────────────────────────────────────────────

def test_referencias_oferecidas():
    assert REFERENCE_PITCHES == (440.0, 432.0, 415.0)

def test_padrao_e_440():
    assert A4_STANDARD == 440.0


# ── escala dos presets ────────────────────────────────────────────────────────

def test_440_nao_altera_a_tabela():
    assert get_tuning("GUITAR", 440.0) == get_tuning("GUITAR")

def test_432_baixa_todas_as_cordas():
    padrao = get_notes_dict("GUITAR", 440.0)
    verdi = get_notes_dict("GUITAR", 432.0)
    for nota in padrao:
        assert verdi[nota] < padrao[nota]

def test_432_baixa_exatamente_a_mesma_razao_em_todas():
    padrao = get_notes_dict("GUITAR", 440.0)
    verdi = get_notes_dict("GUITAR", 432.0)
    esperado = 432.0 / 440.0
    for nota in padrao:
        assert verdi[nota] / padrao[nota] == pytest.approx(esperado)

def test_432_fica_a_cerca_de_menos_32_cents():
    padrao = get_notes_dict("GUITAR", 440.0)
    verdi = get_notes_dict("GUITAR", 432.0)
    desvio = cents_between(verdi["E2"], padrao["E2"])
    assert desvio == pytest.approx(-31.77, abs=0.1)

def test_415_fica_a_cerca_de_meio_tom_abaixo():
    padrao = get_notes_dict("GUITAR", 440.0)
    barroco = get_notes_dict("GUITAR", 415.0)
    desvio = cents_between(barroco["E2"], padrao["E2"])
    assert -105.0 < desvio < -95.0   # ~meio semitom

def test_intervalos_entre_cordas_nao_mudam():
    """A guitarra continua sendo uma guitarra: só o diapasão desce."""
    for a4 in REFERENCE_PITCHES:
        d = get_notes_dict("GUITAR", a4)
        # E2 -> A2 é sempre uma quarta justa (500 cents)
        assert cents_between(d["A2"], d["E2"]) == pytest.approx(500.0, abs=1.0)

def test_referencia_invalida_estoura():
    with pytest.raises(ValueError):
        get_tuning("GUITAR", 0.0)
    with pytest.raises(ValueError):
        get_tuning("GUITAR", -440.0)


# ── engine ────────────────────────────────────────────────────────────────────

def test_engine_em_432_afina_e2_mais_grave():
    engine = TunerEngine(mode="GUITAR", a4=432.0)
    alvo = get_notes_dict("GUITAR", 432.0)["E2"]
    r = engine.process_frequency(alvo)
    assert r.note == "E2"
    assert r.raw_cents == pytest.approx(0.0, abs=0.01)

def test_e2_padrao_soa_alto_em_432():
    """Tocar 82.41 Hz com o afinador em 432 tem que acusar corda alta."""
    engine = TunerEngine(mode="GUITAR", a4=432.0)
    r = engine.process_frequency(82.41)
    assert r.raw_cents > 30.0
    assert r.status in ("VERY_HIGH", "HIGH")

def test_cromatico_respeita_a_referencia():
    engine = TunerEngine(mode="CHROMATIC", a4=432.0)
    r = engine.process_frequency(432.0)
    assert r.note == "A4"
    assert r.raw_cents == pytest.approx(0.0, abs=0.01)

def test_nome_da_nota_nao_muda_com_a_referencia():
    """Em A4=432 a nota A4 continua se chamando A4 — só vale 432 Hz."""
    nome, alvo = find_chromatic_note(432.0, a4=432.0)
    assert nome == "A4"
    assert alvo == pytest.approx(432.0)

def test_manual_travado_respeita_a_referencia():
    engine = TunerEngine(mode="GUITAR", a4=415.0)
    engine.lock_note("A2")
    alvo = get_notes_dict("GUITAR", 415.0)["A2"]
    r = engine.process_frequency(alvo)
    assert r.note == "A2"
    assert r.raw_cents == pytest.approx(0.0, abs=0.01)

def test_engine_rejeita_referencia_invalida():
    with pytest.raises(ValueError):
        TunerEngine(mode="GUITAR", a4=0.0)

def test_note_frequency_from_midi_usa_a_referencia():
    # MIDI 69 é o A4 por definição
    assert note_frequency_from_midi(69, a4=432.0) == pytest.approx(432.0)
    assert note_frequency_from_midi(69) == pytest.approx(440.0)


# ── pipeline ──────────────────────────────────────────────────────────────────

def test_pipeline_aceita_referencia_na_criacao():
    pipe = TunerPipeline(mode="GUITAR", a4=432.0)
    assert pipe.a4 == 432.0

def test_trocar_referencia_limpa_o_historico():
    """Sem o clear, a mediana da referência antiga arrastaria a nota."""
    pipe = TunerPipeline(mode="GUITAR")
    for i in range(7):
        pipe.process(82.41, 0.05, 0.7, now=i * 0.09)
    pipe.set_reference_pitch(432.0)
    assert pipe.tracker.reference is None

def test_pipeline_em_432_reporta_afinado_no_alvo_certo():
    pipe = TunerPipeline(mode="GUITAR", a4=432.0)
    alvo = get_notes_dict("GUITAR", 432.0)["E2"]
    r = None
    for i in range(7):
        r = pipe.process(alvo, 0.05, 0.7, now=i * 0.09)
    assert r.note == "E2"
    assert r.status == "PERFECT"
