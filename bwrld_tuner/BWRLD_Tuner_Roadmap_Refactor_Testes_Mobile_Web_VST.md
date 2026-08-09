# BWRLD Tuner — Roadmap de Evolução Sem Quebrar o Projeto

## Objetivo deste documento

Este documento organiza as próximas etapas do **BWRLD Tuner** para evoluirmos com calma, segurança e sem quebrar o app que já está funcionando.

A ideia principal é:

1. **Congelar uma versão estável.**
2. **Criar testes automatizados.**
3. **Refatorar a arquitetura aos poucos.**
4. **Preparar o projeto para mobile, web e futuramente VST.**

---

# Estado atual do projeto

O BWRLD Tuner já possui:

- captura de áudio em tempo real;
- suporte à interface de áudio/Focusrite via entrada padrão do sistema;
- detecção de frequência;
- modos como `CHROMATIC`, `GUITAR`, `DROP D`, `BASS` e `MANUAL`;
- interface Kivy com dashboard visual;
- velocímetro/ponteiro;
- presets de guitarra/baixo;
- correções de estabilidade V6;
- separação entre `raw_cents` e `cents` visual;
- comportamento mais estável no modo `DROP D`.

Agora o foco muda de “adicionar feature” para **organizar, testar e preparar para crescimento**.

---

# Regra de ouro daqui pra frente

Antes de mexer forte no app:

```text
Não refatorar tudo de uma vez.
Não misturar UI, áudio e lógica musical.
Não apagar a versão funcional.
Sempre criar testes antes de mudanças grandes.
```

---

# Etapa 0 — Congelar a versão atual estável

## Objetivo

Preservar a versão atual funcionando antes de começar a refatoração.

## Ações

1. Criar uma cópia do arquivo atual:

```bash
copy main_ponteiro.py main_ponteiro_stable_v6.py
```

Ou no PowerShell:

```powershell
Copy-Item main_ponteiro.py main_ponteiro_stable_v6.py
```

2. Criar uma branch no Git:

```bash
git checkout -b v6-stable
```

3. Fazer commit:

```bash
git add .
git commit -m "chore: freeze stable V6 tuner version"
```

## Resultado esperado

Ter uma versão segura para voltar caso algo quebre.

---

# Etapa 1 — Criar estrutura de pastas profissional

## Objetivo

Separar o projeto em camadas para facilitar testes, manutenção e futuras versões mobile/web/VST.

## Estrutura sugerida

```text
bwrld_tuner/
├── app/
│   ├── main.py
│   ├── ui_kivy.py
│   └── audio_input.py
│
├── core/
│   ├── notes.py
│   ├── tunings.py
│   ├── tuner_engine.py
│   ├── pitch_detection.py
│   ├── smoothing.py
│   └── gate.py
│
├── tests/
│   ├── test_notes.py
│   ├── test_tunings.py
│   ├── test_tuner_engine.py
│   ├── test_smoothing.py
│   └── test_gate.py
│
├── main_ponteiro.py
├── main_ponteiro_stable_v6.py
├── tuner_pro.py
├── requirements.txt
├── requirements-dev.txt
└── pytest.ini
```

## Regra importante

A pasta `core/` não deve importar:

```python
kivy
sounddevice
```

O `core/` deve conter apenas lógica pura, para ser testável e reutilizável.

---

# Etapa 2 — Instalar e configurar pytest

## Objetivo

Criar testes automatizados para garantir que a lógica musical não quebre.

## Criar `requirements-dev.txt`

```text
pytest
pytest-cov
```

## Instalar dependências de desenvolvimento

```bash
python -m pip install -r requirements-dev.txt
```

## Criar `pytest.ini`

```ini
[pytest]
testpaths = tests
python_files = test_*.py
python_functions = test_*
addopts = -v
```

## Rodar testes

```bash
python -m pytest
```

---

# Etapa 3 — Criar `core/notes.py`

## Objetivo

Mover funções matemáticas/musicais para um módulo puro.

## Funções que devem ir para `core/notes.py`

```python
cents_between(freq, target)
clip_cents(cents, min_value=-50, max_value=50)
note_frequency_from_midi(midi_num)
frequency_to_midi(freq)
find_closest_note(freq, notes_dict)
```

## Testes que devem ser criados

Arquivo:

```text
tests/test_notes.py
```

Casos:

```python
cents_between(82.41, 82.41) == 0
clip_cents(200) == 50
clip_cents(-200) == -50
E2 contra D2 deve dar valor alto positivo
frequência inválida deve ser tratada com segurança
```

## Resultado esperado

A matemática principal passa a ser testada isoladamente.

---

# Etapa 4 — Criar `core/tunings.py`

## Objetivo

Centralizar todos os modos de afinação.

## Estrutura desejada

```python
TUNINGS = {
    "GUITAR": [
        ("E4", "1ª CORDA", 329.63),
        ("B3", "2ª CORDA", 246.94),
        ("G3", "3ª CORDA", 196.00),
        ("D3", "4ª CORDA", 146.83),
        ("A2", "5ª CORDA", 110.00),
        ("E2", "6ª CORDA", 82.41),
    ],
    "DROP D": [
        ("E4", "1ª CORDA", 329.63),
        ("B3", "2ª CORDA", 246.94),
        ("G3", "3ª CORDA", 196.00),
        ("D3", "4ª CORDA", 146.83),
        ("A2", "5ª CORDA", 110.00),
        ("D2", "6ª CORDA", 73.42),
    ],
    "BASS": [
        ("G2", "1ª CORDA", 98.00),
        ("D2", "2ª CORDA", 73.42),
        ("A1", "3ª CORDA", 55.00),
        ("E1", "4ª CORDA", 41.20),
    ],
}
```

## Testes

Arquivo:

```text
tests/test_tunings.py
```

Casos:

```python
GUITAR deve ter 6 cordas
DROP D deve ter D2 na 6ª corda
BASS deve ter 4 cordas
E1 do baixo deve estar em 41.20 Hz
```

---

# Etapa 5 — Criar `core/tuner_engine.py`

## Objetivo

Criar uma engine central que recebe frequência e devolve um resultado pronto para a UI.

## Modelo sugerido

```python
from dataclasses import dataclass

@dataclass
class TunerResult:
    note: str
    string_name: str
    freq: float
    target: float
    raw_cents: float
    display_cents: float
    status: str
    active: bool
```

## Classe sugerida

```python
class TunerEngine:
    def __init__(self, mode="CHROMATIC"):
        self.mode = mode
        self.locked_note = None

    def set_mode(self, mode):
        ...

    def lock_note(self, note):
        ...

    def unlock(self):
        ...

    def process_frequency(self, freq):
        ...
```

## Resultado esperado

A UI deixa de calcular nota/status diretamente. Ela só recebe um `TunerResult`.

---

# Etapa 6 — Testar a engine

## Arquivo

```text
tests/test_tuner_engine.py
```

## Casos importantes

```python
modo GUITAR com 82.41 Hz deve retornar E2
modo DROP D com 82.41 Hz deve retornar D2 e DROP A LOT
modo BASS com 41.20 Hz deve retornar E1
modo MANUAL travado em A2 deve comparar tudo contra A2
raw_cents deve guardar valor real
display_cents deve ficar limitado entre -50 e +50
```

## Resultado esperado

A lógica principal do app fica protegida por testes.

---

# Etapa 7 — Criar `core/smoothing.py`

## Objetivo

Isolar a suavização de frequência/cents.

## Função/classe sugerida

```python
class MedianSmoother:
    def __init__(self, maxlen=7):
        ...

    def add(self, value):
        ...

    def value(self):
        ...

    def clear(self):
        ...
```

## Testes

Arquivo:

```text
tests/test_smoothing.py
```

Casos:

```python
mediana de [1, 2, 100] deve ser 2
clear deve apagar histórico
limite maxlen deve funcionar
```

---

# Etapa 8 — Criar `core/gate.py`

## Objetivo

Criar gate inteligente com histerese para evitar flicker quando o som da corda morre.

## Comportamento desejado

```text
RMS baixo por pouco tempo -> mantém última leitura
RMS baixo por muito tempo -> standby
Clarity ruim -> sinal instável
Sinal bom -> ativo
```

## Classe sugerida

```python
class SignalGate:
    def __init__(self, rms_threshold=0.006, clarity_threshold=0.18, hold_time=0.8):
        ...

    def update(self, rms, clarity, now):
        ...
```

## Testes

Arquivo:

```text
tests/test_gate.py
```

Casos:

```python
sinal bom deve ativar gate
sinal baixo por pouco tempo deve manter hold
sinal baixo após hold_time deve ir para standby
clarity baixa deve retornar NOISY
```

---

# Etapa 9 — Refatorar `main_ponteiro.py` com segurança

## Objetivo

Começar a substituir partes internas pelo novo `core/`, sem mudar visual ainda.

## Ordem segura

1. Importar funções de `core/notes.py`.
2. Importar presets de `core/tunings.py`.
3. Usar `TunerEngine` apenas no callback.
4. Manter UI Kivy igual.
5. Rodar testes.
6. Testar manualmente com guitarra.

## Regra

Após cada alteração:

```bash
python -m pytest
python main_ponteiro.py
```

---

# Etapa 10 — Preparar layout mobile

## Objetivo

Pensar em como a UI se adapta a celular.

## Problemas no mobile

- tela menor;
- toque em botões precisa ser maior;
- modo retrato/paisagem;
- permissões de microfone;
- input de áudio diferente do Windows;
- latência.

## Layout mobile sugerido

```text
Topo:
BWRLD TUNER + modo atual

Centro:
Nota grande
Hz
Cents
Status

Meio/Baixo:
Velocímetro simplificado

Rodapé:
Botões de modo: Guitar / Drop D / Bass / Manual
```

## Estratégia

Criar um modo de layout:

```python
if width < 700:
    draw_mobile_layout()
else:
    draw_desktop_layout()
```

---

# Etapa 11 — Preparar versão web/site

## Objetivo

Planejar uma versão web do BWRLD Tuner.

## Caminho provável

```text
Python atual
↓
Core testado em Python
↓
Portar core para TypeScript
↓
Frontend com React/Svelte/Vue
↓
Áudio pelo navegador usando Web Audio API
↓
Canvas/SVG para velocímetro
```

## O que pode ser reaproveitado

- fórmulas de cents;
- presets;
- status;
- smoothing;
- lógica de modos;
- design visual.

## O que precisa ser refeito

- captura de áudio;
- UI;
- detector de pitch;
- permissões do navegador.

---

# Etapa 12 — Pesquisa e protótipo VST

## Objetivo

Planejar o caminho para transformar o BWRLD Tuner em plugin VST.

## Realidade técnica

VST normalmente é desenvolvido em:

```text
C++
JUCE
VST3 SDK
```

Python/Kivy não é o caminho ideal para VST final.

## Caminho recomendado

```text
BWRLD Tuner Python
↓
Core testado e documentado
↓
Portar core musical para C++
↓
Criar app standalone em JUCE
↓
Criar plugin VST3 em JUCE
↓
Testar em DAW
```

## Primeira versão VST possível

```text
BWRLD Tuner VST3
- plugin analisador de pitch
- entrada mono/stereo
- visual com nota/cents
- modos Guitar, Drop D, Bass
- sem processar/modificar áudio inicialmente
```

## Por que isso seria forte para portfólio

Porque junta:

- DSP;
- C++;
- áudio em tempo real;
- UI;
- plugin para DAW;
- arquitetura multiplataforma.

---

# Ordem recomendada de execução

> **Status:** Sprints 1 a 4 concluídos. `main_ponteiro.py` já roda sobre `core/`,
> com 86 testes cobrindo notas, tunings, engine, smoothing, gate e pipeline.
> Próximo alvo: Sprint 5 (layout mobile).

## Sprint 1 — Testes base

- criar `core/notes.py`;
- criar `core/tunings.py`;
- criar `tests/test_notes.py`;
- criar `tests/test_tunings.py`;
- configurar `pytest`.

## Sprint 2 — Engine

- criar `core/tuner_engine.py`;
- criar `TunerResult`;
- testar modos Guitar, Drop D, Bass e Manual.

## Sprint 3 — Estabilidade

- criar `core/smoothing.py`;
- criar `core/gate.py`;
- testar gate com histerese.

## Sprint 4 — Integrar com Kivy

- manter visual atual;
- trocar lógica interna para usar `TunerEngine`;
- testar app real com guitarra.

## Sprint 5 — Layout mobile

- criar `draw_mobile_layout`;
- adaptar botões e medidor;
- testar janela pequena.

## Sprint 6 — Web research

- portar `notes/tunings` para TypeScript;
- criar protótipo visual web;
- estudar captura de áudio no navegador.

## Sprint 7 — VST research

- instalar JUCE;
- criar plugin vazio;
- portar lógica de cents/presets;
- depois pensar em pitch detection em C++.

---

# Checklist de segurança antes de cada sprint

Antes de começar:

```bash
git status
python -m pytest
python main_ponteiro.py
```

Depois de terminar:

```bash
python -m pytest
python -m py_compile main_ponteiro.py
git add .
git commit -m "descrição clara da mudança"
```

---

# Próxima ação imediata

Sprint 4 concluído. O que mudou:

```text
main_ponteiro.py: 852 -> 698 linhas, sem lógica musical duplicada
core/pipeline.py: nova camada gate -> smoothing -> engine (17 testes)
core/tunings.py: get_display_tuning() para o painel de presets
pytest.ini: pythonpath = . (agora "pytest" puro funciona, não só "python -m pytest")
```

Corrigido no caminho:

```text
Race condition: histórico de frequências era escrito pela thread de áudio
                e limpo pela thread do Kivy fora do lock. Agora todo o
                processamento acontece na thread do Kivy.
min_freq:       MANUAL sobre BASS usava 55 Hz e nunca detectava E1 (41.20 Hz).
                Agora usa effective_mode.
Código morto:   cents_history, status_txt="AFINADO", GUITAR_STRINGS,
                import não usado de encontrar_nota.
```

# Sprint 4.5 — Continuidade de pitch (concluído)

O filtro de outliers da V6 (`abs(cents) > 85` em CHROMATIC) era inalcançável e
foi removido. Substituído por `core/tracking.py`, que compara quadros
**consecutivos** em vez de comparar contra a nota alvo:

```text
ACCEPTED     variação < 150 cents        -> usa a leitura
OCTAVE_FIXED salto de ~1200 cents        -> dobra de volta para a oitava certa
REJECTED     salto isolado sem forma     -> descarta o quadro (vira HOLD)
RETUNED      salto repetido              -> o músico mudou de nota mesmo
```

Erro de oitava exige mais confirmação (5 quadros ≈ 460 ms) que salto comum
(2 quadros ≈ 190 ms): travar no 2º harmônico é o erro mais frequente do
detector, e tocar exatamente uma oitava acima é a mudança menos frequente do
músico.

Também corrigido: `find_closest_note()` media distância em **Hz linear**.
Distância musical é logarítmica — a fronteira entre duas cordas é a média
geométrica, não a aritmética. Medir em Hz enviesava para a corda mais grave.

Estado: 113 testes, 98% de cobertura em `core/`.

---

# Nota sobre o caminho VST

Decisão tomada: **desktop standalone offline primeiro**, VST depois, mobile por
último. Isso muda uma regra de `core/`:

```text
core/ deve evitar numpy em código novo.
```

Não por performance, mas porque `core/` é o que será portado para C++/JUCE.
`core/tracking.py` já segue isso (só `math`). Os módulos antigos ainda usam
numpy para operações escalares triviais (`np.log2`, `np.clip`, `np.median`) —
trocar por `math` e uma mediana manual é um refactor pequeno que deixa a
tradução para C++ quase mecânica.

Ainda fora de `core/`: a detecção de pitch em si continua em `tuner_pro.py`,
sem teste nenhum (`core/pitch_detection.py` é só o Protocol). É o maior buraco
de cobertura restante e o próximo alvo natural antes do VST.

---

A próxima coisa é a **lapidação da interface gráfica**, depois o Sprint 5.
