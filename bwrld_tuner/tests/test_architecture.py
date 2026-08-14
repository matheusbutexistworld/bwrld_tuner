"""
tests/test_architecture.py — A regra que sustenta o projeto.

`core/` não pode importar `kivy` nem `sounddevice`. É o que permite rodar a
suíte headless e sem PortAudio, e é o que vai permitir portar `core/` para
C++/JUCE sem arrastar a interface junto.

Sem este teste a regra é só uma promessa no README: um `import kivy` a mais em
core/ passaria despercebido até o dia do port.
"""
import ast
import pathlib

import pytest

CORE = pathlib.Path(__file__).resolve().parent.parent / "core"
PROIBIDOS = {"kivy", "sounddevice"}

MODULOS = sorted(p for p in CORE.glob("*.py") if p.name != "__init__.py")


def imports_de(caminho: pathlib.Path) -> set[str]:
    """Nomes de módulo de topo importados por um arquivo."""
    arvore = ast.parse(caminho.read_text(encoding="utf-8"), filename=str(caminho))
    nomes = set()
    for no in ast.walk(arvore):
        if isinstance(no, ast.Import):
            nomes.update(a.name.split(".")[0] for a in no.names)
        elif isinstance(no, ast.ImportFrom):
            if no.level == 0 and no.module:
                nomes.add(no.module.split(".")[0])
    return nomes


def test_existem_modulos_para_checar():
    """Guarda contra o teste virar vazio se a pasta mudar de lugar."""
    assert len(MODULOS) >= 8, f"achei só {len(MODULOS)} módulos em {CORE}"


@pytest.mark.parametrize("modulo", MODULOS, ids=lambda p: p.name)
def test_core_nao_importa_ui_nem_audio(modulo):
    vazou = imports_de(modulo) & PROIBIDOS
    assert not vazou, f"core/{modulo.name} importa {sorted(vazou)}"


@pytest.mark.parametrize("modulo", MODULOS, ids=lambda p: p.name)
def test_core_nao_importa_a_camada_de_app(modulo):
    """core/ é a base: não pode depender de quem depende dele."""
    proibidos_locais = {"main_ponteiro", "tuner_pro", "app"}
    vazou = imports_de(modulo) & proibidos_locais
    assert not vazou, f"core/{modulo.name} importa {sorted(vazou)}"


def test_modulos_novos_do_core_evitam_numpy():
    """Código novo em core/ usa `math`, pensando no port para C++.

    Os módulos antigos ainda usam numpy para operações escalares e estão
    listados como exceção conhecida — a lista não deve crescer.
    """
    herdados = {"notes.py", "smoothing.py", "pitch_detection.py"}
    for modulo in MODULOS:
        if modulo.name in herdados:
            continue
        assert "numpy" not in imports_de(modulo), (
            f"core/{modulo.name} usa numpy; prefira math ou adicione à lista de herdados"
        )
