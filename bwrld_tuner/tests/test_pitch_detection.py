"""
tests/test_pitch_detection.py — Testes para tuner_pro.detectar_frequencia

Era o único 0% de cobertura do projeto, e é o coração do afinador: qualquer
erro aqui vira corda desafinada, por mais correto que o resto esteja.

Os sinais são sintéticos e determinísticos (senoides somadas, ruído com semente
fixa), então o erro é medido em cents contra um alvo conhecido — não há
"aproximadamente certo" por inspeção visual.

Timbres usados:
    senoide   — o caso limpo, pior para autocorrelação (sem harmônicos)
    GUITARRA  — fundamental forte com 6 harmônicos decaindo
    BAIXO     — 4 harmônicos, período longo, poucos ciclos no bloco
"""
import numpy as np
import pytest

from tuner_pro import detectar_frequencia, encontrar_nota

FS = 44100
N = 4096                      # o mesmo BLOCKSIZE que o app usa

GUITARRA = (1.0, 0.5, 0.33, 0.25, 0.2, 0.16)
BAIXO = (1.0, 0.7, 0.4, 0.2)


def tom(freq, harmonicos=(1.0,), n=N, amp=0.2, ruido=0.0, semente=0, fase=0.0):
    """Sinal periódico sintético com os harmônicos dados."""
    t = np.arange(n) / FS
    x = np.zeros(n)
    for k, a in enumerate(harmonicos, start=1):
        if freq * k < FS / 2:
            x += a * np.sin(2 * np.pi * freq * k * t + fase)
    pico = np.max(np.abs(x)) or 1.0
    x = x / pico * amp
    if ruido:
        x = x + np.random.default_rng(semente).normal(0, ruido, n)
    return x.astype(np.float32)


def cents(freq, alvo):
    return 1200.0 * np.log2(freq / alvo)


def detecta(x, min_freq=55, max_freq=500):
    return detectar_frequencia(x, fs=FS, min_freq=min_freq, max_freq=max_freq)


# ── precisão em senoide pura ──────────────────────────────────────────────────

@pytest.mark.parametrize("alvo", [82.41, 110.0, 146.83, 196.0, 246.94, 329.63, 440.0])
def test_senoide_pura_dentro_de_um_cent(alvo):
    freq, _rms, _clar = detecta(tom(alvo))
    assert freq is not None, f"não detectou {alvo} Hz"
    assert abs(cents(freq, alvo)) < 1.0, f"{alvo} Hz saiu {cents(freq, alvo):+.2f} cents"


def test_sem_vies_sistematico_na_faixa_grave():
    """O erro não pode ser sempre para o mesmo lado.

    A versão anterior lia tudo sharp, e quanto mais grave pior (E2 saía +9,9
    cents, A1 saía +22,3). Erro sistemático é o pior tipo aqui: a mediana não
    remove, então o músico deixava a corda baixa na mesma medida.
    """
    erros = []
    for alvo in (82.41, 92.5, 103.8, 110.0, 123.47, 130.81, 146.83):
        freq, _, _ = detecta(tom(alvo))
        assert freq is not None
        erros.append(cents(freq, alvo))
    assert abs(np.mean(erros)) < 0.5, f"viés de {np.mean(erros):+.2f} cents"


# ── timbre de instrumento ─────────────────────────────────────────────────────

@pytest.mark.parametrize("alvo", [82.41, 110.0, 146.83, 196.0, 246.94, 329.63])
def test_guitarra_com_harmonicos(alvo):
    freq, _, _ = detecta(tom(alvo, GUITARRA))
    assert freq is not None
    assert abs(cents(freq, alvo)) < 1.0


@pytest.mark.parametrize("alvo", [41.20, 55.0, 73.42, 98.0])
def test_baixo_incluindo_o_e1(alvo):
    """E1 = 41,20 Hz cabe só 3,8 vezes no bloco. Antes não era detectado nunca:
    o argmax global agarrava o valor de borda em vez de um pico."""
    freq, _, _ = detecta(tom(alvo, BAIXO), min_freq=30)
    assert freq is not None, f"não detectou {alvo} Hz"
    assert abs(cents(freq, alvo)) < 2.0


def test_segundo_harmonico_dominante_nao_dobra_a_leitura():
    """Captador magnético costuma realçar o 2º harmônico."""
    alvo = 82.41
    freq, _, _ = detecta(tom(alvo, (0.6, 1.0, 0.4)))
    assert freq is not None
    assert abs(cents(freq, alvo)) < 5.0


def test_fundamental_ausente():
    """Só 2º e 3º harmônicos: o ouvido ainda escuta a fundamental, e o
    detector também precisa — é o gatilho clássico de erro de oitava."""
    alvo = 110.0
    freq, _, _ = detecta(tom(alvo, (0.0, 1.0, 0.6)))
    assert freq is not None
    assert abs(cents(freq, alvo)) < 5.0


# ── rejeição: o que não pode virar leitura ────────────────────────────────────

def test_silencio():
    freq, rms, clar = detecta(np.zeros(N, dtype=np.float32))
    assert freq is None
    assert rms == 0.0
    assert clar == 0.0


def test_ruido_branco_nao_vira_nota():
    ruido = np.random.default_rng(1).normal(0, 0.3, N).astype(np.float32)
    freq, rms, clar = detecta(ruido)
    assert freq is None
    assert rms > 0.006, "o ruído é alto: a rejeição tem que vir da clarity"
    assert clar < 0.18


def test_offset_dc_puro():
    freq, _, _ = detecta(np.full(N, 0.5, dtype=np.float32))
    assert freq is None


def test_sinal_fraco_demais():
    freq, rms, _ = detecta(tom(110.0, amp=0.001))
    assert freq is None
    assert rms < 0.006


def test_bloco_curto_demais():
    freq, rms, clar = detecta(tom(110.0, n=200))
    assert (freq, rms, clar) == (None, 0.0, 0.0)


def test_frequencia_abaixo_da_faixa():
    freq, _, _ = detecta(tom(20.0), min_freq=30)
    assert freq is None


# ── robustez ──────────────────────────────────────────────────────────────────

def test_offset_dc_nao_atrapalha():
    """O offset é removido antes de tudo."""
    alvo = 82.41
    limpo, _, _ = detecta(tom(alvo, GUITARRA))
    com_offset, _, _ = detecta(tom(alvo, GUITARRA) + 0.3)
    assert com_offset is not None
    assert abs(cents(com_offset, limpo)) < 0.5


@pytest.mark.parametrize("fase", [0.0, np.pi / 3, np.pi / 2, np.pi])
def test_fase_nao_muda_a_leitura(fase):
    """Autocorrelação é insensível a fase — a leitura não pode depender de
    onde o bloco caiu dentro do ciclo."""
    alvo = 110.0
    freq, _, _ = detecta(tom(alvo, GUITARRA, fase=fase))
    assert freq is not None
    assert abs(cents(freq, alvo)) < 1.0


@pytest.mark.parametrize("sigma", [0.005, 0.02])
def test_ruido_moderado(sigma):
    alvo = 110.0
    freq, _, _ = detecta(tom(alvo, GUITARRA, ruido=sigma))
    assert freq is not None
    assert abs(cents(freq, alvo)) < 15.0


def test_ruido_pesado_nao_produz_erro_de_oitava():
    """Sob ruído a precisão cai, e tudo bem: o MedianSmoother e o PitchTracker
    limpam quadro isolado. O que não pode é errar a oitava, porque aí a nota
    exibida muda."""
    alvo = 110.0
    for semente in range(6):
        freq, _, _ = detecta(tom(alvo, GUITARRA, ruido=0.1, semente=semente))
        if freq is None:
            continue
        assert abs(cents(freq, alvo)) < 300.0, f"erro de oitava com semente {semente}"


# ── varredura ─────────────────────────────────────────────────────────────────

def test_varredura_guitarra_sem_falha_nem_oitava():
    """Percorre a faixa da guitarra em passos irregulares, para não cair sempre
    em múltiplos convenientes da resolução."""
    falhas, oitavas, erros = 0, 0, []
    for alvo in np.arange(82.0, 400.0, 3.7):
        freq, _, _ = detecta(tom(float(alvo), GUITARRA))
        if freq is None:
            falhas += 1
            continue
        e = cents(freq, float(alvo))
        if abs(e) > 600:
            oitavas += 1
        erros.append(e)
    assert falhas == 0
    assert oitavas == 0
    assert max(abs(np.array(erros))) < 2.0


def test_varredura_baixo_sem_falha():
    falhas = 0
    for alvo in np.arange(41.0, 100.0, 1.9):
        freq, _, _ = detecta(tom(float(alvo), BAIXO), min_freq=30)
        if freq is None:
            falhas += 1
    assert falhas == 0


# ── contrato de retorno ───────────────────────────────────────────────────────

def test_clarity_entre_zero_e_um():
    for alvo in (82.41, 196.0, 329.63):
        _freq, _rms, clar = detecta(tom(alvo, GUITARRA))
        assert 0.0 <= clar <= 1.0


def test_rms_bate_com_o_sinal():
    x = tom(110.0, amp=0.2)
    _f, rms, _c = detecta(x)
    assert rms == pytest.approx(float(np.sqrt(np.mean((x - x.mean()) ** 2))), rel=1e-4)


def test_taxa_de_amostragem_diferente():
    """O detector não pode ter 44100 embutido em lugar nenhum."""
    fs = 48000
    alvo = 146.83
    t = np.arange(4096) / fs
    x = (0.2 * np.sin(2 * np.pi * alvo * t)).astype(np.float32)
    freq, _, _ = detectar_frequencia(x, fs=fs, min_freq=55, max_freq=500)
    assert freq is not None
    assert abs(cents(freq, alvo)) < 1.0


# ── encontrar_nota (helper legado) ────────────────────────────────────────────

def test_encontrar_nota_exata():
    assert encontrar_nota(82.41) == ("E2", 82.41)


def test_encontrar_nota_aproximada():
    nota, alvo = encontrar_nota(330.0)
    assert nota == "E4"
    assert alvo == pytest.approx(329.63)
