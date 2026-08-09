"""
core/tunings.py — Presets de afinação centralizados.

Sem kivy, sem sounddevice. Apenas dados de cordas por modo.

Formato de cada entrada: (nota, chave_do_rótulo, freq_hz)

O segundo campo é uma *chave* de tradução (ver core/i18n.py), não texto de
tela: "STRING_6" vira "6ª CORDA" em pt-BR e "6TH STRING" em en-US.

As frequências da tabela valem para A4 = 440 Hz. get_tuning() escala tudo
quando a referência é outra.
"""

# Afinações de referência oferecidas na interface.
#   440 — padrão moderno (ISO 16)
#   432 — "verdi tuning", meio tom abaixo de nada, ~-31.8 cents de 440
#   415 — diapasão barroco, praticamente meio tom abaixo de 440
REFERENCE_PITCHES: tuple[float, ...] = (440.0, 432.0, 415.0)

A4_STANDARD = 440.0

TUNINGS: dict[str, list[tuple[str, str, float]]] = {
    "GUITAR": [
        ("E4", "STRING_1", 329.63),
        ("B3", "STRING_2", 246.94),
        ("G3", "STRING_3", 196.00),
        ("D3", "STRING_4", 146.83),
        ("A2", "STRING_5", 110.00),
        ("E2", "STRING_6",  82.41),
    ],
    "DROP D": [
        ("E4", "STRING_1", 329.63),
        ("B3", "STRING_2", 246.94),
        ("G3", "STRING_3", 196.00),
        ("D3", "STRING_4", 146.83),
        ("A2", "STRING_5", 110.00),
        ("D2", "STRING_6",  73.42),
    ],
    "BASS": [
        ("G2", "STRING_1",  98.00),
        ("D2", "STRING_2",  73.42),
        ("A1", "STRING_3",  55.00),
        ("E1", "STRING_4",  41.20),
    ],
}


def get_tuning(mode: str, a4: float = A4_STANDARD) -> list[tuple[str, str, float]]:
    """Retorna a lista de cordas para um modo, na afinação de referência dada.

    Args:
        mode: Nome do modo (ex: 'GUITAR', 'DROP D', 'BASS').
        a4:   Afinação de referência em Hz. Todos os alvos são multiplicados
              por a4/440 — a razão entre as cordas não muda, o instrumento
              inteiro desce ou sobe junto.

    Returns:
        Lista de (nota, chave_do_rótulo, freq_hz).

    Raises:
        KeyError:   Se o modo não existir em TUNINGS.
        ValueError: Se a4 não for positivo.
    """
    if mode not in TUNINGS:
        raise KeyError(f"Modo de afinação desconhecido: '{mode}'. Disponíveis: {list(TUNINGS.keys())}")
    if a4 <= 0:
        raise ValueError(f"Afinação de referência inválida: {a4}")

    base = TUNINGS[mode]
    if a4 == A4_STANDARD:
        return base

    razao = a4 / A4_STANDARD
    return [(nota, chave, freq * razao) for nota, chave, freq in base]


def get_notes_dict(mode: str, a4: float = A4_STANDARD) -> dict[str, float]:
    """Retorna um dicionário {nota: freq_hz} para um modo.

    Útil para usar com find_closest_note() de core/notes.py.
    """
    return {note: freq for note, _chave, freq in get_tuning(mode, a4)}


def get_display_tuning(mode: str, a4: float = A4_STANDARD) -> list[tuple[str, str, float]]:
    """Retorna as cordas a exibir no painel de presets para qualquer modo.

    Diferente de get_tuning(), aceita modos sem tabela própria: CHROMATIC (e
    qualquer modo desconhecido) cai no preset de GUITAR, que é o que a UI já
    mostrava na V6.
    """
    alvo = mode if mode in TUNINGS else "GUITAR"
    return get_tuning(alvo, a4)


def get_min_freq(mode: str) -> float:
    """Retorna a frequência mínima esperada para um modo.

    Usado para ajustar o detector de pitch (ex: BASS precisa de 30 Hz).
    """
    if mode == "BASS":
        return 30.0
    return 55.0
