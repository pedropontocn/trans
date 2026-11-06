"""Configuração: modelos, preços e limites."""
VERSAO = "5.0"
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
