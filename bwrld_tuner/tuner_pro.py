import numpy as np

# Afinacao padrao guitarra: E A D G B E
notas = {
    "E2": 82.41,
    "A2": 110.00,
    "D3": 146.83,
    "G3": 196.00,
    "B3": 246.94,
    "E4": 329.63,
}


def encontrar_nota(freq):
    """Retorna a nota padrao de guitarra mais proxima e sua frequencia alvo."""
    nota = min(notas, key=lambda n: abs(freq - notas[n]))
    return nota, notas[nota]


def _parabolic_interpolation(y, x):
    """Refina o pico usando interpolacao parabolica."""
    if x <= 0 or x >= len(y) - 1:
        return float(x)

    alpha = y[x - 1]
    beta = y[x]
    gamma = y[x + 1]
    denom = alpha - 2 * beta + gamma

    if abs(denom) < 1e-12:
        return float(x)

    return float(x + 0.5 * (alpha - gamma) / denom)


def detectar_frequencia(
    audio,
    fs=44100,
    min_freq=60,
    max_freq=500,
    rms_threshold=0.006,
    clarity_threshold=0.18,
):
    """
    Detecta a frequencia fundamental usando autocorrelacao via FFT.

    Retorna:
        (freq, rms, clarity)
        freq = None quando o sinal esta fraco/ruidoso.
    """
    audio = np.asarray(audio, dtype=np.float32)

    if audio.size < 256:
        return None, 0.0, 0.0

    # Remove DC offset
    audio = audio - np.mean(audio)

    rms = float(np.sqrt(np.mean(audio ** 2)))
    if rms < rms_threshold:
        return None, rms, 0.0

    # Janela para reduzir vazamento espectral
    audio = audio * np.hanning(len(audio))

    # Autocorrelacao via FFT: rapido e mais estavel que FFT pura para afinador
    n = len(audio)
    fft_size = 1 << (2 * n - 1).bit_length()
    spectrum = np.fft.rfft(audio, fft_size)
    corr = np.fft.irfft(spectrum * np.conj(spectrum))[:n]

    if corr[0] <= 1e-12:
        return None, rms, 0.0

    corr = corr / corr[0]

    min_lag = int(fs / max_freq)
    max_lag = int(fs / min_freq)
    max_lag = min(max_lag, len(corr) - 2)

    if min_lag >= max_lag:
        return None, rms, 0.0

    region = corr[min_lag:max_lag]

    # Evita pegar pico fraco/ruidoso
    peak_relative = int(np.argmax(region))
    peak_index = min_lag + peak_relative
    clarity = float(corr[peak_index])

    if clarity < clarity_threshold:
        return None, rms, clarity

    refined_peak = _parabolic_interpolation(corr, peak_index)

    if refined_peak <= 0:
        return None, rms, clarity

    freq = float(fs / refined_peak)

    if not (min_freq <= freq <= max_freq):
        return None, rms, clarity

    return freq, rms, clarity
