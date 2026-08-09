"""
core/notes.py — Matemática musical pura.

Sem kivy, sem sounddevice. Apenas fórmulas e utilitários de notas/cents.
"""
import numpy as np

A4 = 440.0  # Afinação de referência padrão (concert pitch)
NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]


def frequency_to_midi(freq: float, a4: float = A4) -> int:
    """Converte frequência Hz para número MIDI mais próximo.

    Args:
        freq: Frequência em Hz (> 0).
        a4:   Afinação de referência (440 padrão, 432 e 415 também usadas).
    """
    if freq <= 0:
        raise ValueError(f"Frequência inválida: {freq}")
    return round(12 * np.log2(freq / a4) + 69)


def note_frequency_from_midi(midi_num: int, a4: float = A4) -> float:
    """Retorna a frequência exata de um número MIDI na referência dada."""
    return a4 * (2.0 ** ((midi_num - 69) / 12.0))


def midi_to_note_name(midi_num: int) -> str:
    """Retorna o nome da nota (ex: 'E2') a partir do número MIDI."""
    octave = (midi_num // 12) - 1
    name = NOTE_NAMES[midi_num % 12]
    return f"{name}{octave}"


def cents_between(freq: float, target: float) -> float:
    """Calcula a diferença em cents entre uma frequência e o alvo.

    Valor positivo = acima do alvo (sharp).
    Valor negativo = abaixo do alvo (flat).
    """
    if freq <= 0 or target <= 0:
        return 0.0
    return 1200.0 * np.log2(freq / target)


def clip_cents(cents: float, min_value: float = -50.0, max_value: float = 50.0) -> float:
    """Limita cents a um intervalo visual (para o ponteiro/velocímetro)."""
    return float(np.clip(cents, min_value, max_value))


def find_closest_note(freq: float, notes_dict: dict) -> tuple[str, float]:
    """Encontra a nota mais próxima em um dicionário {nome: freq_hz}.

    A proximidade é medida em cents, não em Hz. Distância musical é logarítmica:
    entre E2 (82.41) e A2 (110.00) o ponto médio auditivo é 95.2 Hz, mas o ponto
    médio em Hz é 96.2 Hz. Medir em Hz enviesa a escolha para a corda mais grave,
    justamente na faixa onde o músico chega desafinado.

    Returns:
        (note_name, target_freq)
    """
    if not notes_dict:
        raise ValueError("Dicionário de notas está vazio.")
    if freq <= 0:
        raise ValueError(f"Frequência inválida: {freq}")
    nota = min(notes_dict, key=lambda n: abs(cents_between(freq, notes_dict[n])))
    return nota, notes_dict[nota]


def find_chromatic_note(freq: float, a4: float = A4) -> tuple[str, float]:
    """Encontra a nota cromática mais próxima na escala temperada de 12 tons.

    Args:
        freq: Frequência detectada em Hz.
        a4:   Afinação de referência. Muda o alvo, não o nome da nota: em
              A4=432 a nota A4 continua se chamando A4, mas vale 432 Hz.

    Returns:
        (note_name, target_freq)
    """
    if freq <= 0:
        return "---", 0.0
    midi_num = frequency_to_midi(freq, a4)
    target_freq = note_frequency_from_midi(midi_num, a4)
    note_name = midi_to_note_name(midi_num)
    return note_name, target_freq
