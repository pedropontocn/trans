"""Configuração: modelos, preços e limites."""
VERSAO = "5.1"
MARCA_JSON_INI, MARCA_JSON_FIM = "[INÍCIO DO JSON]", "[FIM DO JSON]"

MODELOS = [
    "anthropic/claude-sonnet-5-5",
    "anthropic/claude-opus-5-5",
    "anthropic/claude-haiku-5-5",
    "anthropic/claude-sonnet-4-5-20250929",
]


LIMITE_CARACTERES = 150_000      # documentos brutos de uma pasta (Drive ou .zip), somados


# Relatório ou resumo do órgão: é o material já preparado e precisa ser lido inteiro. 400 mil caracteres são cerca de
# 130 páginas e 110 mil tokens, o que cabe com folga no contexto dos modelos junto com o dossiê.
LIMITE_RELATORIO = 400_000




# US$ por milhão de tokens (entrada, saída). Fonte: platform.claude.com/docs/en/about-claude/pricing (nov/2026).
# O Haiku 5.5 cobra mais caro acima de 100 mil tokens de entrada; a estimativa usa o preço base.
# (entrada, saída, multiplicador da leitura de cache). Escrita de cache custa 1,25x a entrada (5 minutos) ou 2x (1 hora).
PRECOS = {"opus-5-5": (4, 20, 0.05), "sonnet-5-5": (2, 10, 0.05), "haiku-5-5": (0.10, 0.50, 0.10), "sonnet-4-5": (3, 15, 0.10)}


ESCRITA_CACHE = 1.25


ESCRITA_CACHE_1H = 2.0


DESCONTO_LOTE_API = 0.5


# Busca na web da Anthropic: US$ 10 por mil buscas, além dos tokens. A do Gemini tem preço próprio (não cadastrado).
PRECO_BUSCA_ANTHROPIC = 0.01


MIN_ITENS_DOSSIE = 5


# --- ESQUEMA DE MODELOS -------------------------------------------------------------------------
# Princípio: quem produz não confere, e quem confere não é da mesma família de quem produziu. O código já confere o
# modelo; entre modelos, a independência vem de famílias diferentes nos revisores. Cada família de fora precisa da
# chave do provedor no .env ou nos Secrets; sem a chave, a etapa cai para o modelo principal (Anthropic).
# Famílias de fora, em ordem de preferência, com o modelo de ponta de cada uma (nomes no formato do LiteLLM; os da
# OpenAI e do Google são os "most capable" dos changelogs oficiais em nov/2026; os da DeepSeek são apelidos estáveis).
FAMILIAS = {
    "openai": {"chave": "OPENAI_API_KEY", "modelo": "openai/gpt-6-astra"},
    "gemini": {"chave": "GEMINI_API_KEY", "modelo": "gemini/gemini-4-argon"},
    "deepseek": {"chave": "DEEPSEEK_API_KEY", "modelo": "deepseek/deepseek-reasoner"},
}

# Quem fica com cada papel (chaves de PAPEIS em riscos.py), conforme quantas famílias de fora têm chave. Os papéis
# mais adversariais (advogado do diabo, controle jurídico) vão primeiro para fora; o autor da análise (Anthropic)
# nunca tem maioria quando há ao menos uma família de fora. O número é o índice da família de fora, na ordem em que
# estão disponíveis; papel ausente fica com o principal.
DISTRIBUICAO = {
    0: {},
    1: {"contra": 0, "controle": 0, "servico": 0},                                   # 3 fora, 3 Anthropic
    2: {"contra": 0, "controle": 0, "operacao": 0, "servico": 1, "governo": 1},      # 3 + 2, 1 Anthropic
    3: {"contra": 0, "controle": 0, "servico": 1, "governo": 1, "operacao": 2},      # 2 + 2 + 1, 1 Anthropic
}


def familias_disponiveis(ambiente=None):
    """As famílias de fora com chave configurada."""
    import os
    ambiente = os.environ if ambiente is None else ambiente
    return [f for f, dados in FAMILIAS.items() if (ambiente.get(dados["chave"]) or "").strip()]


PAPEIS_ORDEM = ["fiscal", "controle", "servico", "operacao", "governo", "contra"]   # a ordem de PAPEIS em riscos.py


def esquema_de_modelos(principal, auxiliar, lista=None, familias=None):
    """Os modelos de cada etapa de revisão. lista: modelos informados à mão, que se revezam entre os agentes (vale
    sobre o esquema). Sem lista, DISTRIBUICAO reparte os papéis entre o principal e as famílias de fora com chave.
    A neutralidade vai para a primeira família de fora disponível; sem nenhuma, para o auxiliar (ao menos um modelo
    diferente do que escreveu)."""
    familias = familias_disponiveis() if familias is None else familias
    familias = [f for f in FAMILIAS if f in familias]                   # na ordem de preferência
    lista = [m.strip() for m in (lista or []) if str(m or "").strip()]
    if lista:
        agentes = [lista[k % len(lista)] for k in range(len(PAPEIS_ORDEM))]
    else:
        reparto = DISTRIBUICAO[min(len(familias), max(DISTRIBUICAO))]
        agentes = [FAMILIAS[familias[reparto[p]]]["modelo"] if p in reparto else principal for p in PAPEIS_ORDEM]
    de_fora = [FAMILIAS[f]["modelo"] for f in familias]
    neutralidade = de_fora[0] if de_fora else (auxiliar if auxiliar != principal else principal)
    return {"agentes": agentes, "neutralidade": neutralidade, "familias": familias,
            "independente": len({m.split("/")[0] for m in agentes}) > 1}


# Sem o modo econômico, quantas secretarias rodam ao mesmo tempo. Cada uma já faz até 8 chamadas em paralelo
# (os cinco agentes, por exemplo); mais que isso tende a esbarrar no limite de uso por minuto da API.
PARALELOS_DIRETO = 3
