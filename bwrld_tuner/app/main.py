"""
app/main.py — Ponto de entrada do BWRLD Tuner.

Responsável por inicializar o app Kivy e conectar a UI com o engine de áudio.
Não contém lógica musical — apenas cola os módulos juntos.
"""
from app.ui_kivy import BwrldTunerApp

if __name__ == "__main__":
    BwrldTunerApp().run()
