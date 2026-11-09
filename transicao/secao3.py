"""Leitura, por código, do Relatório de Transição de Gestão (modelo v2 da Casa Civil) em PDF: as fichas da seção 3
(3.1 Programas e políticas públicas, 3.2 Projetos estratégicos, obras e investimentos, 3.3 Concessões, PPPs e
estudos) e o quadro 4.1 (Orçamento e execução financeira), por órgão. Fonte do caderno executivo.

As fichas têm rótulos fixos ("Situação", "Objetivo / Produto"...): o código separa cada campo e guarda o endereço
(arquivo, seção e página). Cabeçalho e rodapé de página são descartados; uma ficha que atravessa a quebra de página
continua inteira. Nada aqui chama modelo.
"""
import io
import re

ROTULOS = {
    "Situação": "situacao",
    "Objetivo / Produto": "objetivo", "Objeto / Produto": "objetivo", "Objeto / Problema / Produto": "objetivo",
    "Público-alvo e abrangência": "publico",
    "Metas e resultados": "metas",
    "Valor / Fonte de recursos": "valor",
    "Localização e escopo": "localizacao",
    "Execução física e financeira": "execucao",
    "Contratos e instrumentos": "instrumentos",
    "Próximas etapas e prazos": "proximas",
    "Ponto crítico / Riscos": "pontos_criticos",
    "Processo SEI / TCE-RJ / outro": "processo",
    "Responsável": "responsavel",
}
NOMES_DOS_CAMPOS = {v: k for k, v in reversed(list(ROTULOS.items()))}
RE_ROTULO = re.compile(r"^(" + "|".join(re.escape(r) for r in sorted(ROTULOS, key=len, reverse=True)) + r")(?=\s|$)")
RE_FICHA = re.compile(r"^(3\.[123]\.\d{1,2})\s+(\S.*)$")
RE_INICIO = re.compile(r"^3\.1\s+Programas", re.I)
RE_FIM = re.compile(r"^4(\.|\.1)\s+\S")
RE_SUBSECAO = re.compile(r"^3\.[123]\s+\S")
RE_CABECALHO = re.compile(r"^GOVERNO DO ESTADO", re.I)
RE_RODAPE = re.compile(r"(Informações posicionadas em|Página \d+ de \d+\s*$|\.{5,}\s*\d+\s*$)", re.I)  # e o sumário
GRUPOS = {"3.1": "Programas e políticas públicas", "3.2": "Projetos estratégicos, obras e investimentos",
          "3.3": "Concessões, PPPs e estudos de estruturação"}

# quadro 4.1: as linhas que interessam e o rótulo curto de cada uma
ITENS_41 = [("Dotação inicial", "dotacao_inicial"), ("Dotação atualizada", "dotacao_atualizada"),
            ("Empenhado", "empenhado"), ("Liquidado", "liquidado"), ("Pago", "pago")]
RE_VALOR_41 = re.compile(r"(\d{1,3}(?:\.\d{3})*,\d{2}|Não informado|Não quantificado)")
RE_POSICAO = re.compile(r"posição em (\d{2}/\d{2}/\d{4})", re.I)


def _paginas(dados):
    import pdfplumber
    with pdfplumber.open(io.BytesIO(dados)) as pdf:
        return [pg.extract_text() or "" for pg in pdf.pages]


def _linhas(paginas):
    for n, texto in enumerate(paginas, 1):
        for linha in texto.splitlines():
            linha = linha.strip()
            if linha and not RE_CABECALHO.match(linha) and not RE_RODAPE.search(linha):
                yield n, linha


def fichas_das_paginas(paginas, arquivo):
    """As fichas da seção 3, em ordem. Cada uma: {"secao", "grupo", "titulo", "arquivo", "pagina", "campos"}."""
    fichas, atual, campo, dentro = [], None, None, False
    for pagina, linha in _linhas(paginas):
        if RE_INICIO.match(linha):
            dentro = True
            continue
        if dentro and RE_FIM.match(linha):
            break
        if not dentro:
            continue
        if m := RE_FICHA.match(linha):
            atual = {"secao": m.group(1), "grupo": m.group(1)[:3], "titulo": m.group(2).strip(), "arquivo": arquivo,
                     "pagina": pagina, "campos": {}}
            fichas.append(atual)
            campo = None
            continue
        if RE_SUBSECAO.match(linha):
            atual, campo = None, None        # o texto de abertura da subseção não é de nenhuma ficha
            continue
        if atual is None:
            continue
        if campo == "processo" and re.match(r"^procedimento\b", linha):
            linha = linha[len("procedimento"):].strip()   # a segunda linha do rótulo "…/ outro procedimento"
            if not linha:
                continue
        if m := RE_ROTULO.match(linha):
            campo = ROTULOS[m.group(1)]
            valor = linha[m.end():].strip()
            atual["campos"][campo] = (atual["campos"].get(campo, "") + " " + valor).strip()
            continue
        if campo:
            atual["campos"][campo] = (atual["campos"][campo] + " " + linha).strip()
        else:
            atual["titulo"] += " " + linha
    for f in fichas:
        f["campos"] = {k: re.sub(r"\s+", " ", v).strip() for k, v in f["campos"].items()}
    return fichas


def quadro_41(paginas, arquivo):
    """O quadro 4.1 (Orçamento e execução financeira), por órgão: dotação, empenhado, liquidado e pago, com a
    data-base ("posição em"). Devolve [{"orgao", "itens": {chave: valor como está}, "data_base", "pagina"}]."""
    blocos, atual, dentro = [], None, False
    for pagina, linha in _linhas(paginas):
        if re.match(r"^4\.1\s+Or[çc]amento", linha, re.I):
            dentro = True
            continue
        if dentro and re.match(r"^4\.2\s+\S", linha):
            break
        if not dentro:
            continue
        if re.fullmatch(r"[A-ZÁÉÍÓÚÂÊÔÃÕÇ/ ]{3,40}(\s*\(UG \d+\))?", linha):
            atual = {"orgao": linha, "itens": {}, "data_base": "", "pagina": pagina, "arquivo": arquivo}
            blocos.append(atual)
            continue
        if atual is None:
            continue
        for rotulo, chave in ITENS_41:
            if linha.startswith(rotulo) and chave not in atual["itens"]:
                if m := RE_VALOR_41.search(linha[len(rotulo):]):
                    atual["itens"][chave] = m.group(1)
        if m := RE_POSICAO.search(linha):
            atual["data_base"] = atual["data_base"] or m.group(1)
    return [b for b in blocos if b["itens"]]


def ler_relatorio_pdf(nome, dados):
    """Fichas da seção 3 e quadro 4.1 de um PDF no modelo do Relatório de Transição. Vazio se o PDF não for desse
    modelo. Nunca levanta erro: a leitura do resto do app não depende disto."""
    try:
        paginas = _paginas(dados)
    except Exception:
        return {"fichas": [], "orcamento_41": []}
    if not any(RE_INICIO.match(l) for _, l in _linhas(paginas)):
        return {"fichas": [], "orcamento_41": []}
    return {"fichas": fichas_das_paginas(paginas, nome), "orcamento_41": quadro_41(paginas, nome)}
