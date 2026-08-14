"""
core/version.py — Versão do BWRLD Tuner, em um lugar só.

Sem kivy, sem sounddevice, sem numpy.

A versão estava cravada em três lugares (o cabeçalho de main_ponteiro.py e o
rodapé de cada idioma em i18n.py), então subir de versão dependia de lembrar
de todos. Agora sai daqui, e o rodapé monta o texto em tempo de desenho.
"""

VERSION = "7.0"
APP_NAME = "BWRLD TUNER"

# Nome que aparece no rodapé e na barra de título.
ENGINE_LABEL = f"BWRLD AUDIO ENGINE V{VERSION}"
WINDOW_TITLE = f"{APP_NAME} V{VERSION}"
