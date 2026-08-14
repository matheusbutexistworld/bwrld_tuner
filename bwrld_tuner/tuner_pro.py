"""
tuner_pro.py — Detecção de pitch por autocorrelação via FFT.

Só numpy. É a única parte do projeto que faz DSP de verdade.

Três decisões sustentam a precisão, e todas nasceram de medição (ver
tests/test_pitch_detection.py, que compara o erro em cents contra senoides e
timbres sintéticos ao longo de toda a faixa):

1. **Desenviesar pela janela.** A autocorrelação de um sinal janelado é a
   autocorrelação real multiplicada pela autocorrelação da própria janela, que
   decai com o lag. Esse decaimento puxa o pico para lags menores, ou seja,
   para frequências maiores: a leitura sai sharp, e o erro cresce quanto mais
   grave a nota. Sem a correção, um E2 afinado lia +9,9 cents e um A1 lia
   +22,3 — o músico deixava a corda quase um quarto de tom baixa.

2. **Pular o lobo central.** Para uma nota grave, o período é uma fração grande
   do bloco, e a autocorrelação ainda vale quase 1 no início da faixa de busca.
   Um `argmax` global agarrava esse valor de borda em vez de um pico de
   verdade. Era por isso que o E1 do baixo (41,20 Hz) simplesmente nunca era
   detectado. A busca agora começa depois da autocorrelação cruzar o zero.

3. **Entre picos equivalentes, o lag menor vence.** A autocorrelação tem picos
   no período e em todos os múltiplos dele; os múltiplos são erro de oitava
   para baixo. Pegar o primeiro pico que chega a 92% do máximo escolhe o
   período real. Sozinha, a correção (1) faria os múltiplos empatarem com o
   período e a oitava errada venceria em metade dos casos.
"""
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

# Fração do máximo que um pico precisa atingir para ser aceito no lugar do
# máximo global. 0.92 saiu de uma varredura: valores menores deixam ruído
# vencer, maiores voltam a produzir erro de oitava.
PEAK_TOLERANCE = 0.92

# Piso do divisor de desenviesamento. Em lags longos a autocorrelação da janela
# fica pequena e dividir por ela amplificaria ruído sem limite.
UNBIAS_FLOOR = 0.30

_JANELA_CACHE: dict[int, tuple[np.ndarray, np.ndarray]] = {}


def encontrar_nota(freq):
    """Retorna a nota padrao de guitarra mais proxima e sua frequencia alvo."""
    nota = min(notas, key=lambda n: abs(freq - notas[n]))
    return nota, notas[nota]


def _janela_e_norma(n):
    """Janela de Hann de tamanho n e a autocorrelação normalizada dela.

    Cacheado: o bloco tem sempre o mesmo tamanho em uso real, então isso é
    calculado uma vez por sessão e não por quadro.
    """
    if n not in _JANELA_CACHE:
        w = np.hanning(n)
        fft_size = 1 << (2 * n - 1).bit_length()
        espectro = np.fft.rfft(w, fft_size)
        corr_w = np.fft.irfft(espectro * np.conj(espectro))[:n]
        _JANELA_CACHE[n] = (w, corr_w / corr_w[0])
    return _JANELA_CACHE[n]


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


def _primeiro_pico(corr, inicio, fim, limiar):
    """Menor lag em [inicio, fim) que é máximo local e atinge `limiar`.

    Devolve None se nenhum pico qualificar — quem chama cai no máximo global.
    """
    for lag in range(inicio, fim - 1):
        if corr[lag] < limiar:
            continue
        if corr[lag] >= corr[lag - 1] and corr[lag] >= corr[lag + 1]:
            return lag
    return None


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

    Args:
        audio:             Bloco de amostras mono.
        fs:                Taxa de amostragem.
        min_freq/max_freq: Faixa de busca em Hz.
        rms_threshold:     Abaixo disso o sinal é considerado silêncio.
        clarity_threshold: Abaixo disso a leitura é considerada ruído.

    Retorna:
        (freq, rms, clarity)
        freq = None quando o sinal esta fraco/ruidoso ou fora da faixa.
    """
    audio = np.asarray(audio, dtype=np.float32)

    if audio.size < 256:
        return None, 0.0, 0.0

    # Remove DC offset
    audio = audio - np.mean(audio)

    rms = float(np.sqrt(np.mean(audio ** 2)))
    if rms < rms_threshold:
        return None, rms, 0.0

    n = len(audio)
    janela, norma_janela = _janela_e_norma(n)
    audio = audio * janela

    # Autocorrelacao via FFT: rapido e mais estavel que FFT pura para afinador
    fft_size = 1 << (2 * n - 1).bit_length()
    spectrum = np.fft.rfft(audio, fft_size)
    corr = np.fft.irfft(spectrum * np.conj(spectrum))[:n]

    if corr[0] <= 1e-12:
        return None, rms, 0.0

    # (1) desenviesa: tira o decaimento que a própria janela introduz
    corr = corr / corr[0] / np.maximum(norma_janela, UNBIAS_FLOOR)

    min_lag = max(2, int(fs / max_freq))
    max_lag = min(int(fs / min_freq), n // 2 - 2)
    if min_lag >= max_lag:
        return None, rms, 0.0

    # (2) pula o lobo central: procura pico só depois do primeiro cruzamento
    # por zero, senão o valor de borda vence em notas graves
    lag = 1
    while lag < max_lag and corr[lag] > 0.0:
        lag += 1
    inicio = max(min_lag, lag)
    if inicio >= max_lag - 1:
        return None, rms, 0.0

    regiao = corr[inicio:max_lag]
    valor_max = float(np.max(regiao))
    if valor_max < clarity_threshold:
        return None, rms, max(valor_max, 0.0)

    # (3) entre picos equivalentes, o lag menor é o período real
    peak_index = _primeiro_pico(corr, inicio, max_lag, valor_max * PEAK_TOLERANCE)
    if peak_index is None:
        peak_index = inicio + int(np.argmax(regiao))

    clarity = float(min(corr[peak_index], 1.0))

    refined_peak = _parabolic_interpolation(corr, peak_index)
    if refined_peak <= 0:
        return None, rms, clarity

    freq = float(fs / refined_peak)

    if not (min_freq <= freq <= max_freq):
        return None, rms, clarity

    return freq, rms, clarity
