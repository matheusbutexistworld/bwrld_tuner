"""
core/i18n.py — Traduções da interface.

Sem kivy, sem sounddevice, sem numpy: só dicionários e uma função de busca.

O resto do core devolve **chaves** ("SLIGHTLY_HIGH", "STRING_6"), nunca texto
de tela. Quem desenha chama t(chave, idioma). Isso mantém a lógica musical
independente de idioma e deixa o core portável para C++/JUCE, onde a tabela
vira um array estático.

Uso:
    from core.i18n import t
    t("PERFECT", "pt-BR")   -> "AFINADO"
    t("PERFECT", "en-US")   -> "PERFECT"
"""

DEFAULT_LANG = "pt-BR"
LANGUAGES: tuple[str, ...] = ("pt-BR", "en-US")

# Rótulo curto de cada idioma, para o botão de troca na interface.
LANGUAGE_LABEL: dict[str, str] = {"pt-BR": "PT", "en-US": "EN"}


_STRINGS: dict[str, dict[str, str]] = {
    "pt-BR": {
        # Estados do afinador
        "PERFECT":        "PERFEITO",
        "IN_TUNE":        "AFINADO",
        "SLIGHTLY_HIGH":  "POUCO ALTO",
        "SLIGHTLY_LOW":   "POUCO BAIXO",
        "HIGH":           "ALTO",
        "LOW":            "BAIXO",
        "VERY_HIGH":      "MUITO ALTO",
        "VERY_LOW":       "MUITO BAIXO",
        "DROP_A_LOT":     "AFROUXE MUITO",
        "TIGHTEN_A_LOT":  "APERTE MUITO",
        "STANDBY":        "EM ESPERA",

        # Cordas
        "STRING_1": "1ª CORDA",
        "STRING_2": "2ª CORDA",
        "STRING_3": "3ª CORDA",
        "STRING_4": "4ª CORDA",
        "STRING_5": "5ª CORDA",
        "STRING_6": "6ª CORDA",

        # Modos
        "CHROMATIC": "CROMÁTICO",
        "GUITAR":    "GUITARRA",
        "DROP D":    "DROP D",
        "BASS":      "BAIXO",
        "MANUAL":    "MANUAL",

        # Painéis
        "PANEL_TELEMETRY":     "SINAL",
        "PANEL_PRESETS_GUITAR": "CORDAS — GUITARRA",
        "PANEL_PRESETS_BASS":   "CORDAS — BAIXO",
        "LEVEL_RMS":  "NÍVEL",
        "CLARITY":    "CLAREZA",
        "REFERENCE":  "REFERÊNCIA",

        # Sinal
        "SIGNAL_OK":    "SINAL OK",
        "SIGNAL_LOW":   "SINAL FRACO",
        "SIGNAL_NOISY": "SINAL SUJO",

        # Leitura central
        "WAITING_SIGNAL": "AGUARDANDO SINAL",
        "TARGET":         "ALVO",
        "CENTS":          "CENTS",
        "NO_SOURCE":      "SEM FONTE",

        # Botões
        "PANELS":     "PAINÉIS",
        "AUTO_MODE":  "MODO AUTO",
        "RESET_LOCK": "SOLTAR CORDA",
        "LOCKED":     "TRAVADO",
        "MODE":       "MODO",

        # Cabeçalho e rodapé
        "APP_SUBTITLE": "AFINADOR CROMÁTICO",
        "FOOTER_LEFT":  "BWRLD AUDIO ENGINE V6.2",
    },
    "en-US": {
        "PERFECT":        "PERFECT",
        "IN_TUNE":        "IN TUNE",
        "SLIGHTLY_HIGH":  "SLIGHTLY HIGH",
        "SLIGHTLY_LOW":   "SLIGHTLY LOW",
        "HIGH":           "HIGH",
        "LOW":            "LOW",
        "VERY_HIGH":      "VERY HIGH",
        "VERY_LOW":       "VERY LOW",
        "DROP_A_LOT":     "LOOSEN A LOT",
        "TIGHTEN_A_LOT":  "TIGHTEN A LOT",
        "STANDBY":        "STANDBY",

        "STRING_1": "1ST STRING",
        "STRING_2": "2ND STRING",
        "STRING_3": "3RD STRING",
        "STRING_4": "4TH STRING",
        "STRING_5": "5TH STRING",
        "STRING_6": "6TH STRING",

        "CHROMATIC": "CHROMATIC",
        "GUITAR":    "GUITAR",
        "DROP D":    "DROP D",
        "BASS":      "BASS",
        "MANUAL":    "MANUAL",

        "PANEL_TELEMETRY":      "SIGNAL",
        "PANEL_PRESETS_GUITAR": "STRINGS — GUITAR",
        "PANEL_PRESETS_BASS":   "STRINGS — BASS",
        "LEVEL_RMS":  "LEVEL",
        "CLARITY":    "CLARITY",
        "REFERENCE":  "REFERENCE",

        "SIGNAL_OK":    "SIGNAL OK",
        "SIGNAL_LOW":   "WEAK SIGNAL",
        "SIGNAL_NOISY": "NOISY SIGNAL",

        "WAITING_SIGNAL": "WAITING FOR SIGNAL",
        "TARGET":         "TARGET",
        "CENTS":          "CENTS",
        "NO_SOURCE":      "NO SOURCE",

        "PANELS":     "PANELS",
        "AUTO_MODE":  "AUTO MODE",
        "RESET_LOCK": "RELEASE STRING",
        "LOCKED":     "LOCKED",
        "MODE":       "MODE",

        "APP_SUBTITLE": "CHROMATIC TUNER",
        "FOOTER_LEFT":  "BWRLD AUDIO ENGINE V6.2",
    },
}


def t(key: str, lang: str = DEFAULT_LANG) -> str:
    """Traduz uma chave. Chave desconhecida volta como ela mesma.

    Devolver a chave em vez de estourar é proposital: um rótulo faltando vira
    um texto feio na tela, não um crash no meio de uma sessão de afinação.
    """
    return _STRINGS.get(lang, _STRINGS[DEFAULT_LANG]).get(key, key)


def has(key: str, lang: str = DEFAULT_LANG) -> bool:
    """A chave está traduzida neste idioma?

    Existe porque `t(k) != k` não serve de prova: em en-US "PERFECT" traduz
    para "PERFECT", idêntico à chave.
    """
    return key in _STRINGS.get(lang, {})


def next_language(lang: str) -> str:
    """Próximo idioma do ciclo — usado pelo botão de troca."""
    if lang not in LANGUAGES:
        return DEFAULT_LANG
    return LANGUAGES[(LANGUAGES.index(lang) + 1) % len(LANGUAGES)]


def missing_keys(lang: str) -> set[str]:
    """Chaves que existem no idioma padrão mas faltam em `lang`.

    Usado pelos testes para garantir que os idiomas não saiam de sincronia.
    """
    if lang not in _STRINGS:
        raise KeyError(f"Idioma desconhecido: '{lang}'. Disponíveis: {LANGUAGES}")
    return set(_STRINGS[DEFAULT_LANG]) - set(_STRINGS[lang])
