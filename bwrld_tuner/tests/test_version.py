"""
tests/test_version.py — Testes para core/version.py

A versão já esteve cravada em três lugares (cabeçalho de main_ponteiro.py e o
rodapé de cada idioma em i18n.py). Estes testes seguram a centralização.
"""
import re

from core import i18n
from core.version import APP_NAME, ENGINE_LABEL, VERSION, WINDOW_TITLE


def test_versao_e_sete():
    assert VERSION.startswith("7")


def test_formato_da_versao():
    assert re.fullmatch(r"\d+\.\d+", VERSION), f"formato inesperado: {VERSION}"


def test_rotulos_derivam_da_versao():
    """Se alguém subir VERSION, os rótulos acompanham sozinhos."""
    assert VERSION in ENGINE_LABEL
    assert VERSION in WINDOW_TITLE
    assert APP_NAME in WINDOW_TITLE


def test_i18n_nao_guarda_versao():
    """Versão em tabela de tradução é como a v6.2 ficou defasada em dois lugares."""
    for lang in i18n.LANGUAGES:
        for chave in ("FOOTER_LEFT", "ENGINE"):
            assert not i18n.has(chave, lang), f"{chave} voltou para o i18n de {lang}"


def test_nenhuma_traducao_menciona_versao():
    for lang in i18n.LANGUAGES:
        for chave in i18n._STRINGS[lang]:
            texto = i18n.t(chave, lang)
            assert not re.search(r"[Vv]\d+\.\d+", texto), (
                f"{lang}/{chave} tem versão cravada: {texto!r}"
            )
