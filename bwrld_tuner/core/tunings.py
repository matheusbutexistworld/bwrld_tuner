"""
core/tunings.py — Presets de afinação centralizados.

Sem kivy, sem sounddevice. Apenas dados de cordas por modo.

Formato de cada entrada: (nota, label_display, freq_hz)
"""

TUNINGS: dict[str, list[tuple[str, str, float]]] = {
    "GUITAR": [
        ("E4", "1ª CORDA", 329.63),
        ("B3", "2ª CORDA", 246.94),
        ("G3", "3ª CORDA", 196.00),
        ("D3", "4ª CORDA", 146.83),
        ("A2", "5ª CORDA", 110.00),
        ("E2", "6ª CORDA",  82.41),
    ],
    "DROP D": [
        ("E4", "1ª CORDA", 329.63),
        ("B3", "2ª CORDA", 246.94),
        ("G3", "3ª CORDA", 196.00),
        ("D3", "4ª CORDA", 146.83),
        ("A2", "5ª CORDA", 110.00),
        ("D2", "6ª CORDA",  73.42),
    ],
    "BASS": [
        ("G2", "1ª CORDA",  98.00),
        ("D2", "2ª CORDA",  73.42),
        ("A1", "3ª CORDA",  55.00),
        ("E1", "4ª CORDA",  41.20),
    ],
}


def get_tuning(mode: str) -> list[tuple[str, str, float]]:
    """Retorna a lista de cordas para um modo de afinação.

    Args:
        mode: Nome do modo (ex: 'GUITAR', 'DROP D', 'BASS').

    Returns:
        Lista de (nota, label, freq_hz).

    Raises:
        KeyError: Se o modo não existir em TUNINGS.
    """
    if mode not in TUNINGS:
        raise KeyError(f"Modo de afinação desconhecido: '{mode}'. Disponíveis: {list(TUNINGS.keys())}")
    return TUNINGS[mode]


def get_notes_dict(mode: str) -> dict[str, float]:
    """Retorna um dicionário {nota: freq_hz} para um modo.

    Útil para usar com find_closest_note() de core/notes.py.
    """
    return {note: freq for note, _label, freq in get_tuning(mode)}


def get_min_freq(mode: str) -> float:
    """Retorna a frequência mínima esperada para um modo.

    Usado para ajustar o detector de pitch (ex: BASS precisa de 30 Hz).
    """
    if mode == "BASS":
        return 30.0
    return 55.0
