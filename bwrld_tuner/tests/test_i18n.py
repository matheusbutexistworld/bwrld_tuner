"""
tests/test_i18n.py — Testes para core/i18n.py
"""
import pytest

from core.i18n import (
    DEFAULT_LANG,
    LANGUAGES,
    LANGUAGE_LABEL,
    has,
    missing_keys,
    next_language,
    t,
)
from core.tuner_engine import TunerEngine
from core.tunings import TUNINGS


# ── básico ────────────────────────────────────────────────────────────────────

def test_traduz_status_para_portugues():
    assert t("IN_TUNE", "pt-BR") == "AFINADO"

def test_traduz_status_para_ingles():
    assert t("IN_TUNE", "en-US") == "IN TUNE"

def test_idioma_padrao_e_portugues():
    assert DEFAULT_LANG == "pt-BR"
    assert t("PERFECT") == "PERFEITO"

def test_chave_desconhecida_volta_como_ela_mesma():
    """Rótulo faltando vira texto feio na tela, não crash no meio da afinação."""
    assert t("CHAVE_QUE_NAO_EXISTE", "pt-BR") == "CHAVE_QUE_NAO_EXISTE"

def test_idioma_desconhecido_cai_no_padrao():
    assert t("PERFECT", "xx-XX") == "PERFEITO"


# ── sincronia entre idiomas ───────────────────────────────────────────────────

def test_nenhum_idioma_tem_chave_faltando():
    for lang in LANGUAGES:
        assert missing_keys(lang) == set(), f"{lang} está sem chaves"

def test_idioma_invalido_em_missing_keys_estoura():
    with pytest.raises(KeyError):
        missing_keys("xx-XX")

def test_todo_idioma_tem_rotulo_curto():
    for lang in LANGUAGES:
        assert lang in LANGUAGE_LABEL


# ── cobertura do que o core produz ────────────────────────────────────────────

def test_todo_status_do_engine_tem_traducao():
    """Varre a faixa de cents e exige tradução para cada status que aparecer."""
    engine = TunerEngine(mode="CHROMATIC")
    vistos = {engine.process_frequency(f).status
              for f in [440.0 * (2 ** (c / 1200.0)) for c in range(-600, 601, 7)]}
    vistos.add("STANDBY")
    assert len(vistos) >= 6, "a varredura devia cobrir vários status"
    for lang in LANGUAGES:
        for chave in vistos:
            assert has(chave, lang), f"status {chave} sem tradução em {lang}"

def test_toda_chave_de_corda_tem_traducao():
    chaves = {chave for cordas in TUNINGS.values() for _n, chave, _f in cordas}
    for lang in LANGUAGES:
        for chave in chaves:
            assert has(chave, lang), f"corda {chave} sem tradução em {lang}"

def test_todo_modo_tem_traducao():
    for lang in LANGUAGES:
        for modo in TunerEngine.VALID_MODES:
            assert has(modo, lang), f"modo {modo} sem tradução em {lang}"

def test_has_distingue_traduzido_de_ausente():
    """t(k) != k não serve de prova: em en-US PERFECT traduz para PERFECT."""
    assert t("PERFECT", "en-US") == "PERFECT"   # igual à chave...
    assert has("PERFECT", "en-US")              # ...mas está traduzido
    assert not has("CHAVE_INEXISTENTE", "en-US")


# ── ciclo de idiomas ──────────────────────────────────────────────────────────

def test_next_language_alterna():
    assert next_language("pt-BR") == "en-US"
    assert next_language("en-US") == "pt-BR"

def test_next_language_de_idioma_invalido_volta_ao_padrao():
    assert next_language("xx-XX") == DEFAULT_LANG

def test_ciclo_completo_volta_ao_inicio():
    lang = DEFAULT_LANG
    for _ in range(len(LANGUAGES)):
        lang = next_language(lang)
    assert lang == DEFAULT_LANG
