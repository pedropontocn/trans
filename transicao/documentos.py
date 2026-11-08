"""Documentos: Word (a partir de Markdown, com tabelas, quadros e links) e Excel do calendário."""
import io
import re
from datetime import date

import docx
from docx.enum.text import WD_TAB_ALIGNMENT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

from .modelo import _norm
from .pesquisa import BLOCOS, BLOCOS_ESTADO, BLOCOS_ORGAO, TIPOS_FONTE, TIPOS_OFICIAIS, itens_incluidos, resumo_dossie


AZUL = RGBColor(0x1B, 0x2A, 0x41)


ACENTO = RGBColor(0x3E, 0x6A, 0x9E)


CINZA = RGBColor(0x68, 0x72, 0x80)


TEXTO = RGBColor(0x26, 0x2C, 0x36)


NIVEIS = {3: ("F6DBD6", RGBColor(0xB0, 0x40, 0x34)), 2: ("F8ECCD", RGBColor(0xB0, 0x80, 0x16)), 1: ("DAECE1", RGBColor(0x3E, 0x80, 0x5C))}


def _nivel(txt):
    n = _norm(txt)
    if re.match(r"^(alt|high|critic)", n):
        return 3
    if re.match(r"^(med|moder)", n):
        return 2
    if re.match(r"^(baix|low)", n):
        return 1
    return None


def _sombrear(celula, cor):
    tcPr = celula._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), cor)
    tcPr.append(shd)


def _bordas_celula(celula, **lados):
    tcPr = celula._tc.get_or_add_tcPr()
    bordas = OxmlElement("w:tcBorders")
    for lado, (estilo, tamanho, cor) in lados.items():
        b = OxmlElement(f"w:{lado}")
        b.set(qn("w:val"), estilo)
        b.set(qn("w:sz"), str(tamanho))
        b.set(qn("w:color"), cor)
        bordas.append(b)
    tcPr.append(bordas)


def _linha_inferior(par, cor="D5DBE3", tamanho=4):
    pPr = par._p.get_or_add_pPr()
    pbdr = OxmlElement("w:pBdr")
    b = OxmlElement("w:bottom")
    b.set(qn("w:val"), "single")
    b.set(qn("w:sz"), str(tamanho))
    b.set(qn("w:space"), "4")
    b.set(qn("w:color"), cor)
    pbdr.append(b)
    pPr.append(pbdr)


def _campo(par, instrucao, tamanho, cor):
    """Insere um campo do Word (PAGE, NUMPAGES) que o próprio Word atualiza."""
    def _run_com(elemento):
        run = par.add_run()
        run.font.size, run.font.color.rgb = tamanho, cor
        run._r.append(elemento)
        return run

    inicio = OxmlElement("w:fldChar")
    inicio.set(qn("w:fldCharType"), "begin")
    _run_com(inicio)
    instr = OxmlElement("w:instrText")
    instr.set(qn("xml:space"), "preserve")
    instr.text = f" {instrucao} "
    _run_com(instr)
    separador = OxmlElement("w:fldChar")
    separador.set(qn("w:fldCharType"), "separate")
    _run_com(separador)
    provisorio = par.add_run("1")
    provisorio.font.size, provisorio.font.color.rgb = tamanho, cor
    fim = OxmlElement("w:fldChar")
    fim.set(qn("w:fldCharType"), "end")
    _run_com(fim)


LINK = RGBColor(0x2E, 0x5F, 0xA8)


def _link(par, texto, url, tamanho, cor=LINK):
    """Hiperlink de verdade no Word (clicável), azul e sublinhado."""
    rid = par.part.relate_to(url, "http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink",
                             is_external=True)
    hiper = OxmlElement("w:hyperlink")
    hiper.set(qn("r:id"), rid)
    run = OxmlElement("w:r")
    props = OxmlElement("w:rPr")
    for nome, valor in (("w:color", str(cor)), ("w:u", "single"), ("w:sz", str(int(tamanho.pt * 2)))):
        e = OxmlElement(nome)
        e.set(qn("w:val"), valor)
        props.append(e)
    run.append(props)
    t = OxmlElement("w:t")
    t.text = texto
    t.set(qn("xml:space"), "preserve")
    run.append(t)
    hiper.append(run)
    par._p.append(hiper)


def _texto_inline(par, texto, tamanho=Pt(10.5), cor=TEXTO, negrito=False):
    texto = re.sub(r"`([^`]+)`", r"\1", texto)
    partes = re.split(r"(\[[^\]]+\]\(https?://[^)\s]+\))", texto)
    if len(partes) > 1:                         # tem link: cada pedaço vai na ordem, o link como hiperlink
        for pedaco in partes:
            m = re.fullmatch(r"\[([^\]]+)\]\((https?://[^)\s]+)\)", pedaco)
            if m:
                _link(par, m.group(1), m.group(2), tamanho)
            elif pedaco:
                _texto_inline(par, pedaco, tamanho, cor, negrito)
        return
    texto = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", texto)
    for pedaco in re.split(r"(\*\*[^*]+\*\*)", texto):
        if not pedaco:
            continue
        forte = pedaco.startswith("**") and pedaco.endswith("**")
        conteudo = pedaco[2:-2] if forte else re.sub(r"(?<![\w*])[*_]([^*_]+)[*_](?![\w*])", r"\1", pedaco)
        run = par.add_run(conteudo)
        run.bold = forte or negrito
        run.font.size, run.font.color.rgb = tamanho, cor


def _ler_markdown(md):
    """Divide o Markdown em blocos: título, parágrafo, lista e tabela."""
    blocos, paragrafo = [], []

    def fechar_paragrafo():
        if paragrafo:
            blocos.append(("p", " ".join(paragrafo)))
            paragrafo.clear()

    for linha in md.splitlines():
        s = linha.strip()
        if not s:
            fechar_paragrafo()
            continue
        if m := re.match(r"^(#{1,4})\s+(.*)", s):
            fechar_paragrafo()
            blocos.append(("h", len(m.group(1)), m.group(2).strip().strip("*")))
        elif s.startswith("|"):
            fechar_paragrafo()
            if re.match(r"^\|?\s*:?-{2,}", s):
                continue
            celulas = [c.strip() for c in s.strip("|").split("|")]
            if blocos and blocos[-1][0] == "table":
                blocos[-1][1].append(celulas)
            else:
                blocos.append(("table", [celulas]))
        elif m := re.match(r"^([-*•])\s+(.*)", s):
            fechar_paragrafo()
            if blocos and blocos[-1][0] == "ul":
                blocos[-1][1].append(m.group(2))
            else:
                blocos.append(("ul", [m.group(2)]))
        elif m := re.match(r"^(\d+)[.)]\s+(.*)", s):
            fechar_paragrafo()
            if blocos and blocos[-1][0] == "ol":
                blocos[-1][1].append(m.group(2))
            else:
                blocos.append(("ol", [m.group(2)]))
        else:
            paragrafo.append(s)
    fechar_paragrafo()
    return blocos


def _desenhar_blocos(alvo, blocos):
    """Desenha os blocos no documento ou dentro de uma célula de tabela."""
    for bloco in blocos:
        tipo = bloco[0]
        if tipo == "h":
            nivel, texto = bloco[1], bloco[2]
            par = alvo.add_paragraph()
            par.paragraph_format.space_before = Pt(14 if nivel <= 2 else 8)
            par.paragraph_format.space_after = Pt(5)
            par.paragraph_format.keep_with_next = True
            _texto_inline(par, texto, Pt(13 if nivel <= 2 else 11), AZUL, negrito=True)
            if nivel <= 2:
                _linha_inferior(par)
        elif tipo == "p":
            par = alvo.add_paragraph()
            par.paragraph_format.space_after = Pt(6)
            par.paragraph_format.line_spacing = 1.2
            _texto_inline(par, bloco[1])
        elif tipo in ("ul", "ol"):
            for i, item in enumerate(bloco[1], 1):
                par = alvo.add_paragraph()
                par.paragraph_format.left_indent = Cm(0.7)
                par.paragraph_format.first_line_indent = Cm(-0.5)
                par.paragraph_format.space_after = Pt(3)
                marcador = par.add_run(f"{i}.  " if tipo == "ol" else "•  ")
                marcador.bold = True
                marcador.font.size, marcador.font.color.rgb = Pt(10.5), ACENTO
                _texto_inline(par, item)
        elif tipo == "table":
            _desenhar_tabela(alvo, bloco[1])
            alvo.add_paragraph()


def _desenhar_tabela(alvo, linhas):
    ncol = max(len(l) for l in linhas)
    tabela = alvo.add_table(rows=len(linhas), cols=ncol)
    tabela.style = "Table Grid"
    cabecalho = [_norm(c) for c in linhas[0]]
    colunas_nivel = {i for i, c in enumerate(cabecalho) if any(k in c for k in ("probab", "impact", "nivel", "intens"))}
    for r, linha in enumerate(linhas):
        for c in range(ncol):
            celula = tabela.cell(r, c)
            texto = linha[c] if c < len(linha) else ""
            celula.text = ""
            par = celula.paragraphs[0]
            if r == 0:
                _sombrear(celula, "1B2A41")
                _texto_inline(par, texto.strip("*"), Pt(9), RGBColor(0xFF, 0xFF, 0xFF), negrito=True)
                continue
            nivel = _nivel(texto) if c in colunas_nivel else None
            if nivel:
                fundo, cor = NIVEIS[nivel]
                _sombrear(celula, fundo)
                _texto_inline(par, texto, Pt(9), cor, negrito=True)
            else:
                _texto_inline(par, texto, Pt(9))
    # larguras proporcionais ao tamanho médio do texto de cada coluna (17 cm úteis)
    medias = []
    for c in range(ncol):
        textos = [len(l[c]) if c < len(l) else 0 for l in linhas]
        cabecalho_len = len(linhas[0][c]) if c < len(linhas[0]) else 0
        curta = all(len(l[c]) <= 4 for l in linhas[1:] if c < len(l))      # coluna de ids (C1, R2...): estreita
        medias.append(max(7 if curta else 12, cabecalho_len + 2, min(60, sum(textos) / len(textos))))
    total = sum(medias)
    larguras = [Cm(17 * m / total) for m in medias]
    tabela.autofit = False
    for c, coluna in enumerate(tabela.columns):
        coluna.width = larguras[c]
    for linha in tabela.rows:
        for c, celula in enumerate(linha.cells):
            celula.width = larguras[c]
        # não quebra uma linha entre duas páginas
        trPr = linha._tr.get_or_add_trPr()
        nao_quebrar = OxmlElement("w:cantSplit")
        nao_quebrar.set(qn("w:val"), "true")
        trPr.append(nao_quebrar)
    # repete o cabeçalho quando a tabela passa de página
    cab = OxmlElement("w:tblHeader")
    cab.set(qn("w:val"), "true")
    tabela.rows[0]._tr.get_or_add_trPr().append(cab)


def gerar_docx(memorando_md, meta):
    doc = docx.Document()
    secao = doc.sections[0]
    secao.page_width, secao.page_height = Cm(21), Cm(29.7)
    secao.left_margin = secao.right_margin = secao.top_margin = secao.bottom_margin = Cm(2)
    normal = doc.styles["Normal"]
    normal.font.name, normal.font.size = "Arial", Pt(10.5)
    normal.element.rPr.rFonts.set(qn("w:eastAsia"), "Arial")

    # Cabeçalho institucional (órgão e unidade são opcionais; a linha azul sai mesmo sem eles)
    p = None
    if meta.get("orgao"):
        p = doc.add_paragraph()
        p.paragraph_format.space_after = Pt(0)
        _texto_inline(p, meta["orgao"], Pt(9.5), AZUL, negrito=True)
    if meta.get("unidade"):
        p = doc.add_paragraph()
        _texto_inline(p, meta["unidade"], Pt(9.5), CINZA)
    if p is None:
        p = doc.add_paragraph()
        p.paragraph_format.space_after = Pt(0)
    _linha_inferior(p, "3E6A9E", 12)
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(10)
    p.paragraph_format.space_after = Pt(2)
    run = p.add_run((meta.get("tipo") or "Memorando executivo").upper())
    run.bold, run.font.size, run.font.color.rgb = True, Pt(8.5), ACENTO
    blocos = _ler_markdown(memorando_md)
    titulo_memo = ""
    if blocos and blocos[0][0] == "h" and blocos[0][1] == 1:
        titulo_memo = "" if "memorando" in _norm(blocos[0][2]) and len(blocos[0][2]) < 30 else blocos[0][2]
        blocos = blocos[1:]
    p = doc.add_paragraph()
    _texto_inline(p, meta.get("assunto") or titulo_memo or "Memorando executivo", Pt(17), AZUL, negrito=True)
    dados = [("PARA", meta.get("para")), ("DE", meta.get("unidade") or meta.get("orgao")), ("DATA", meta.get("data"))]
    for rotulo, valor in [d for d in dados if d[1]]:
        p = doc.add_paragraph()
        p.paragraph_format.space_after = Pt(1)
        p.paragraph_format.tab_stops.add_tab_stop(Cm(2.2))
        r = p.add_run(rotulo + "\t")
        r.bold, r.font.size, r.font.color.rgb = True, Pt(8), CINZA
        _texto_inline(p, valor, Pt(10))
    _linha_inferior(p)

    # Corpo: "O essencial" (ou "Em síntese") vai num quadro; os anexos começam em página nova
    i = 0
    while i < len(blocos):
        b = blocos[i]
        if b[0] == "h" and b[1] == 2 and _norm(b[2]).startswith(("anexo", "capitulo")) and i > 0:
            doc.add_page_break()
        if b[0] == "h" and b[1] <= 2 and ("sintese" in _norm(b[2]) or "essencial" in _norm(b[2])):
            j = i + 1
            while j < len(blocos) and not (blocos[j][0] == "h" and blocos[j][1] <= 2):
                j += 1
            doc.add_paragraph().paragraph_format.space_after = Pt(2)
            quadro = doc.add_table(rows=1, cols=1)
            celula = quadro.cell(0, 0)
            _sombrear(celula, "F2F5F9")
            _bordas_celula(celula, left=("single", 24, "3E6A9E"), top=("nil", 0, "auto"), right=("nil", 0, "auto"), bottom=("nil", 0, "auto"))
            par = celula.paragraphs[0]
            r = par.add_run(b[2].upper())
            r.bold, r.font.size, r.font.color.rgb = True, Pt(8.5), ACENTO
            _desenhar_blocos(celula, blocos[i + 1:j])
            i = j
            continue
        _desenhar_blocos(doc, [b])
        i += 1

    # Rodapé com numeração de páginas
    rodape = secao.footer.paragraphs[0]
    rodape.paragraph_format.tab_stops.add_tab_stop(Cm(17), WD_TAB_ALIGNMENT.RIGHT)
    origem = " · ".join(x for x in [meta.get("orgao"), meta.get("tipo") or "Memorando executivo", meta.get("data"),
                                    meta.get("rodape_extra")] if x)
    r = rodape.add_run(origem + "\tPágina ")
    r.font.size, r.font.color.rgb = Pt(8), CINZA
    _campo(rodape, "PAGE", Pt(8), CINZA)
    r = rodape.add_run(" de ")
    r.font.size, r.font.color.rgb = Pt(8), CINZA
    _campo(rodape, "NUMPAGES", Pt(8), CINZA)

    buffer = io.BytesIO()
    doc.save(buffer)
    return buffer.getvalue()


def _data_extenso(d):
    meses = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto",
             "setembro", "outubro", "novembro", "dezembro"]
    return f"{d.day} de {meses[d.month - 1]} de {d.year}"


SELO_CHECAGEM = {"conferido": "✔ conferido na fonte", "trecho_nao_encontrado": "⚠ trecho não encontrado na página",
                 "inacessivel": "⚠ página inacessível", "sem_trecho": "⚠ sem trecho para conferir",
                 "nao_conferido": "⚠ não conferido"}


def _titulo_bloco(bloco):
    if bloco in BLOCOS:
        return BLOCOS[bloco].split(":")[0]
    return "Outros"


def markdown_dossie(dossie, confronto=None):
    """O dossiê do órgão como documento para leitura: fatos por tema, com a fonte clicável e o selo da conferência.
    Montado por código a partir dos itens (sem chamada a modelo)."""
    itens = itens_incluidos(dossie)
    res = resumo_dossie(dossie)
    orgao = (dossie or {}).get("orgao") or "órgão"
    linhas = [f"# Dossiê – {orgao}",
              "## Sobre este dossiê",
              f"Fatos sobre o órgão e o contexto do Estado reunidos com apoio de IA em fontes públicas, com data de corte em "
              f"{(dossie or {}).get('data_corte') or 'data não informada'}. São {res['itens']} itens, {res['conferidos']} "
              f"conferidos na fonte e {res['oficiais']} de fonte oficial. \"Conferido na fonte\" quer dizer que o sistema "
              "abriu o link e encontrou nele o trecho citado. Item sem esse selo deve ser checado antes de ser usado. "
              "O dossiê não inclui o que o órgão informou: isso aparece só na comparação, ao final.",
              "## Visão geral",
              "| Tema | Itens | Conferidos na fonte | De fonte oficial |", "|---|---|---|---|"]
    ordem = [("orgao", b) for b in BLOCOS_ORGAO] + [("orgao", "outro_orgao")] + \
            [("estado", b) for b in BLOCOS_ESTADO] + [("estado", "outro_estado")]
    for camada, bloco in ordem:
        grupo = [i for i in itens if i["camada"] == camada and i["bloco"] == bloco]
        if grupo:
            conf = sum(1 for i in grupo if i["checagem"] == "conferido" or i.get("conferido_pela_equipe"))
            ofi = sum(1 for i in grupo if i["tipo_fonte"] in TIPOS_OFICIAIS)
            linhas.append(f"| {'Estado · ' if camada == 'estado' else ''}{_titulo_bloco(bloco)} | {len(grupo)} | {conf} | {ofi} |")
    for camada, titulo in (("orgao", f"O órgão"), ("estado", "Contexto do Estado")):
        blocos_camada = [b for c, b in ordem if c == camada]
        if not any(i["camada"] == camada for i in itens):
            continue
        linhas.append(f"## {titulo}")
        for bloco in blocos_camada:
            grupo = [i for i in itens if i["camada"] == camada and i["bloco"] == bloco]
            if not grupo:
                continue
            linhas.append(f"### {_titulo_bloco(bloco)}")
            for i in grupo:
                selo = "✔ conferido pela equipe" if i.get("conferido_pela_equipe") else SELO_CHECAGEM.get(i["checagem"], "")
                fonte = (i["fonte"] or "fonte") + (f", {i['data_fonte']}" if i["data_fonte"] else "")
                fonte = f"[{fonte}]({i['url']})" if i["url"] else fonte
                linhas.append(f"- {i['afirmacao']} — {fonte} · {TIPOS_FONTE[i['tipo_fonte']].lower()} · {selo}")
    divs = (confronto or {}).get("divergencias") or []
    if divs:
        linhas.append("## O que o órgão informou e o que as fontes mostram")
        por_id = {i["id"]: i for i in itens}
        for d in divs:
            item = por_id.get(d["item"], {})
            fonte = f" ([fonte]({item['url']}))" if item.get("url") else ""
            if d["situacao"] == "contradiz":
                linhas.append(f"- **O órgão informa:** {d['o_orgao_declara'] or d['trecho_relatorio']} "
                              f"**As fontes mostram:** {d['as_fontes_mostram']}{fonte}")
            else:
                linhas.append(f"- **Não mencionado pelo órgão:** {d['as_fontes_mostram']}{fonte}")
    nao = [n for n in (dossie or {}).get("nao_encontrado") or [] if n.get("procurado")]
    if nao:
        linhas.append("## Procurado e não encontrado em fonte confiável")
        linhas.append("A pesquisa procurou estes pontos e não achou fonte pública confiável. Não quer dizer que não "
                      "existam: são lacunas a cobrir com o órgão ou com outras bases.")
        linhas += [f"- {_titulo_bloco(n.get('bloco')) if n.get('bloco') in BLOCOS else (n.get('bloco') or 'Outros')}: "
                   f"{n['procurado']}" for n in nao]
    return "\n".join(linhas)


def _sigla_orgao(nome):
    partes = [p.strip() for p in str(nome).rsplit(" - ", 1)]
    return partes[-1] if len(partes) == 2 and partes[-1].isupper() else nome


def calendario_xlsx(eventos, descartados=None, titulo="Calendário de vencimentos críticos", data_corte=""):
    """Planilha do calendário: uma linha por evento, ordenada por data, com filtro, criticidade colorida e as
    instruções de leitura numa aba própria. Serve para um órgão ou para o consolidado do lote."""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter
    from .riscos import horizonte
    wb = Workbook()
    ws = wb.active
    ws.title = "Calendário"
    colunas = [("Data", 12), ("Dias até a data", 9), ("Criticidade", 20), ("Órgão", 30), ("Tipo", 16), ("Evento", 45),
               ("Objeto", 35), ("Valor (R$)", 16), ("Valor como informado", 18), ("O que acontece se nada for feito", 45),
               ("Decisão necessária", 40), ("Origem da informação", 20), ("Fonte", 40), ("Trecho conferido", 60),
               ("Prioridade", 11), ("Nota (impacto × urgência)", 10), ("Impacto", 9), ("Categoria", 24),
               ("Serviço essencial", 10), ("Agir até", 12), ("Sem tempo para nova licitação", 12)]
    # as três primeiras colunas são para filtrar: secretaria (sigla), janela contada da posse e mês
    colunas = [("Secretaria", 12), ("Janela", 18), ("Mês", 10)] + colunas
    ws.append([c for c, _ in colunas])
    cores_prioridade = {"Máxima": "C00000", "Alta": "F4B183", "Média": "FFE699", "Baixa": "E2EFDA"}
    cores = {"Vencido": "C00000", "Crítico (até 30 dias)": "F4B183", "Atenção (31 a 90 dias)": "FFE699",
             "Acompanhar": "E2EFDA"}
    o = 3                                                   # deslocamento das colunas originais
    for e in sorted(eventos, key=lambda x: (x["data"], -(x["valor"] or 0))):
        ws.append([_sigla_orgao(e["orgao"]), horizonte(e.get("agir_ate") or e["data"]), f"{e['data']:%Y-%m}",
                   e["data"], e["dias"], e["criticidade"], e["orgao"], e["tipo"], e["evento"], e["objeto"], e["valor"],
                   e["valor_texto"], e["consequencia"], e["decisao"], e["origem"], e["fonte"], e["trecho"],
                   e.get("prioridade", ""), e.get("prioridade_nota"), e.get("impacto", ""), e.get("categoria", ""),
                   "sim" if e.get("essencial") else "não", e.get("agir_ate"),
                   "sim" if e.get("sem_tempo_licitar") else "não"])
        linha = ws.max_row
        ws.cell(linha, o + 20).number_format = "dd/mm/yyyy"
        if e.get("prioridade") in cores_prioridade:
            ws.cell(linha, o + 15).fill = PatternFill("solid", fgColor=cores_prioridade[e["prioridade"]])
            if e["prioridade"] == "Máxima":
                ws.cell(linha, o + 15).font = Font(color="FFFFFF", bold=True)
        ws.cell(linha, o + 1).number_format = "mm/yyyy" if e["so_mes"] else "dd/mm/yyyy"
        ws.cell(linha, o + 8).number_format = '#,##0.00'
        if e["criticidade"] in cores:
            ws.cell(linha, o + 3).fill = PatternFill("solid", fgColor=cores[e["criticidade"]])
            if e["criticidade"] == "Vencido":
                ws.cell(linha, o + 3).font = Font(color="FFFFFF", bold=True)
        if str(e["fonte"]).startswith("http"):
            ws.cell(linha, o + 13).hyperlink = e["fonte"]
            ws.cell(linha, o + 13).font = Font(color="2E5FA8", underline="single")
    for j, (_, largura) in enumerate(colunas, 1):
        ws.column_dimensions[get_column_letter(j)].width = largura
        ws.cell(1, j).font = Font(bold=True, color="FFFFFF")
        ws.cell(1, j).fill = PatternFill("solid", fgColor="1B2A41")
        ws.cell(1, j).alignment = Alignment(wrap_text=True, vertical="center")
    for linha in ws.iter_rows(min_row=2):
        for c in linha:
            c.alignment = Alignment(wrap_text=True, vertical="top")
    ws.freeze_panes = "D2"
    ws.auto_filter.ref = ws.dimensions
    prioridades = wb.create_sheet("Prioridades", 0)        # a primeira aba: o que tratar primeiro, em todos os órgãos
    cab = ["Secretaria", "Janela", "Prioridade", "Agir até", "Vence em", "Órgão", "Categoria", "Serviço essencial", "Evento",
           "Valor (R$)", "Sem tempo para nova licitação", "Fonte"]
    prioridades.append(cab)
    from .produtos import ordem_de_prioridade
    for e in sorted([e for e in eventos if e["dias"] >= -30], key=ordem_de_prioridade)[:500]:
        prioridades.append([_sigla_orgao(e["orgao"]), horizonte(e.get("agir_ate") or e["data"]), e.get("prioridade", ""),
                            e.get("agir_ate"), e["data"], e["orgao"], e.get("categoria", ""),
                            "sim" if e.get("essencial") else "não", e["evento"], e["valor"],
                            "sim" if e.get("sem_tempo_licitar") else "não", e["fonte"]])
        linha = prioridades.max_row
        for col in (4, 5):
            prioridades.cell(linha, col).number_format = "dd/mm/yyyy"
        prioridades.cell(linha, 10).number_format = '#,##0.00'
        if e.get("prioridade") in cores_prioridade:
            prioridades.cell(linha, 3).fill = PatternFill("solid", fgColor=cores_prioridade[e["prioridade"]])
    for j, largura in enumerate([12, 18, 11, 12, 12, 30, 24, 10, 50, 16, 12, 40], 1):
        prioridades.column_dimensions[get_column_letter(j)].width = largura
        prioridades.cell(1, j).font = Font(bold=True, color="FFFFFF")
        prioridades.cell(1, j).fill = PatternFill("solid", fgColor="1B2A41")
        prioridades.cell(1, j).alignment = Alignment(wrap_text=True, vertical="center")
    prioridades.freeze_panes = "A2"
    prioridades.auto_filter.ref = prioridades.dimensions
    leia = wb.create_sheet("Como ler")
    for texto in [titulo, f"Data de corte: {data_corte}" if data_corte else "",
                  "Cada linha é um evento com data escrita nos documentos: vencimento de contrato ou convênio, prazo "
                  "legal, orçamentário ou de órgão de controle, marco de obra.",
                  "Conferência: o trecho de onde a data foi tirada foi procurado por código no relatório do órgão ou "
                  "no item do dossiê, e a data foi procurada dentro do trecho. Eventos que não passaram ficam na aba "
                  "\"Descartados\".",
                  "Origem: \"Informado pelo órgão\" quer dizer que a data só consta do relatório do órgão; \"Fonte "
                  "pública\" quer dizer que veio de documento ou notícia com link.",
                  "Só entram as datas que a secretaria informou. Bases externas de contratos (SIGA, PNCP, portais) "
                  "não são usadas: trazem datas defasadas.",
                  "Criticidade (pela distância até a data de corte): Vencido; Crítico, até 30 dias; Atenção, de 31 a "
                  "90 dias; Acompanhar, mais de 90 dias.",
                  "Prioridade (régua igual para todos os órgãos, calculada por código): impacto × urgência. Impacto "
                  "Alto para serviço essencial (saúde, medicamentos, alimentação, custódia, vigilância, sistemas críticos "
                  "etc.) a partir de R$ 1 mi, decisão de controle ou outro contrato a partir de R$ 50 mi; Médio para "
                  "serviço essencial menor, outro contrato a partir de R$ 5 mi ou valor desconhecido; Baixo abaixo disso. Urgência pela data-limite para agir: já passou, até 30, até 90 ou mais de 90 dias. "
                  "Máxima: nota 9 ou mais; "
                  "Alta: 6 a 8; Média: 3 a 5; Baixa: 1 ou 2.",
                  "Agir até: para contratos, 30 dias antes do fim (tempo de assinar uma prorrogação). Sem tempo para "
                  "nova licitação: o contrato vence em menos de 120 dias.",
                  "Filtros: as setas no cabeçalho filtram qualquer coluna. As três primeiras servem para isso: "
                  "Secretaria (sigla), Janela (antes da posse, primeiras 72 horas, primeiros 100 dias ou depois, pela "
                  "data-limite para agir contada da posse em 01/01/2027) e Mês.",
                  "A aba Prioridades mostra os 500 eventos de maior prioridade.",
                  "Datas só com mês e ano aparecem como mm/aaaa.",
                  "Limite: só entram datas que estão escritas nos documentos. Se um relatório não traz a vigência dos "
                  "contratos, eles não aparecem aqui. Gerado com apoio de IA; confira antes de usar."]:
        leia.append([texto])
    leia.column_dimensions["A"].width = 120
    leia["A1"].font = Font(bold=True, size=13)
    for c in leia["A"]:
        c.alignment = Alignment(wrap_text=True, vertical="top")
    if descartados:
        desc = wb.create_sheet("Descartados")
        desc.append(["Órgão", "Data informada", "Evento", "Motivo do descarte"])
        for d in descartados:
            desc.append([d.get("orgao", ""), d.get("data"), d.get("evento"), d.get("motivo")])
        for j, largura in enumerate([30, 14, 60, 40], 1):
            desc.column_dimensions[get_column_letter(j)].width = largura
    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


# --- O DOCUMENTO ÚNICO DE CADA ÓRGÃO ------------------------------------------------------

def sobre_o_documento(data_corte, confianca):
    """Nota curta de proveniência que abre o documento. Escrita por código, para não depender do modelo."""
    return ("## Sobre este documento\n"
            f"Apoio à decisão gerado com IA a partir do dossiê de fontes públicas (data de corte: "
            f"{data_corte or 'não informada'}) e do que a secretaria informou. Não recomenda decisões. Confiança da "
            f"análise: {confianca['nivel']}. Gerado em processamento automático, sem revisão da equipe.")


def _origem(i):
    return f"[{i['rotulo']}]({i['url']})" if i.get("url") else i["rotulo"]


BASE_CURTA = {"confirmado em fonte oficial": "fonte oficial ✔",
              "fonte pública conferida": "fonte pública ✔", "fonte pública não conferida": "fonte não conferida",
              "informado pelo órgão": "órgão", "só na imprensa": "imprensa", "sem comprovação": "sem comprovação"}


def _base_curta(i):
    """A firmeza em poucas palavras, para caber em tabela (com o link, quando há)."""
    rotulo = BASE_CURTA.get(i["rotulo"], i["rotulo"])
    return f"[{rotulo}]({i['url']})" if i.get("url") else rotulo


def markdown_diagnostico(diag, ficha=None, resumo_dossie=None):
    """Capítulo 1: a ficha de números (código) e os seis blocos, com cada afirmação conferida na origem."""
    linhas = ["## Capítulo 1 – Diagnóstico",
              "Como a secretaria está hoje, nos mesmos blocos usados para todas as secretarias. Cada afirmação foi "
              "conferida por código na origem, indicada entre parênteses."]
    numeros = list(ficha or [])
    if resumo_dossie and resumo_dossie.get("itens"):
        numeros.append(("Fatos do dossiê (conferidos na fonte)",
                        f"{resumo_dossie['itens']} ({resumo_dossie['conferidos']})"))
    if numeros:
        linhas += ["### Ficha", "| Indicador | Valor |", "|---|---|"] + [f"| {a} | {b} |" for a, b in numeros]
    for sec in (diag or {}).get("secoes") or []:
        linhas.append(f"### {sec['titulo']}")
        if sec.get("leitura"):
            linhas.append(sec["leitura"])
        linhas += [f"- {i['texto']} _({_origem(i)})_" for i in sec["itens"]]
        if not sec["itens"] and not sec.get("nao_se_sabe"):
            linhas.append("_Sem informação conferida neste bloco._")
        if sec.get("nao_se_sabe"):
            linhas.append("_Não se sabe:_ " + "; ".join(sec["nao_se_sabe"]))
    if (diag or {}).get("descartados"):
        linhas.append(f"_{diag['descartados']} afirmação(ões) sem origem conferida foram retiradas._")
    return "\n".join(linhas)


def _agir(r):
    return f"agir até {r['agir_ate']:%d/%m/%Y}" if r.get("agir_ate") else "sem data"


def markdown_riscos(resultado, limite_detalhe=5, cobre_siga=False):
    """Capítulo 5: riscos por prioridade (os primeiros em detalhe), decisões em aberto com as opções e o que pedir à
    secretaria. O que cada agente teme e valoriza fica no Anexo B."""
    riscos, decisoes = resultado.get("riscos") or [], resultado.get("decisoes") or []
    linhas = ["## Riscos por prioridade",
              "Ordem por prioridade (impacto × urgência), com a mesma régua em todas as secretarias. \"Base\" diz quão "
              "firme é a informação que sustenta o risco; \"Revisão\" diz quantos dos seis agentes independentes não fizeram "
              "objeção e o que o advogado do diabo contestou."]
    for r in riscos[:limite_detalhe]:
        linhas.append(f"### {r['id']}. {r['titulo']} – {_agir(r)} · {r['prioridade'].lower()}")
        linhas.append(f"- {r['causa']} → {r['consequencia']}")
        detalhes = [f"**Em jogo:** {r['em_jogo']}" if r.get("em_jogo") else "",
                    f"**Em curso:** {r['em_curso']}" if r.get("em_curso") else "",
                    f"**Base:** {r['firmeza']}" + (f" ({', '.join(r['fatos'])})" if r.get("fatos") else "")]
        linhas.append("- " + " · ".join(d for d in detalhes if d))
        if r.get("revisao"):
            linhas.append("- " + _linha_revisao(r["revisao"]))
        linhas.append(f"- **Decisão:** {r['decisao']}" + (f" — {r['quem_decide']}" if r.get("quem_decide") else ""))
    if len(riscos) > limite_detalhe:
        linhas += ["### Outros riscos a acompanhar", "| Risco | Categoria | Prioridade | Prazo | Base |", "|---|---|---|---|---|"]
        linhas += [f"| {r['id']}. {r['titulo']} | {r['categoria']} | {r['prioridade']} | {_agir(r)} | {r['firmeza']} |"
                   for r in riscos[limite_detalhe:]]
    if decisoes:
        linhas += ["## Decisões em aberto", "As opções têm o mesmo peso. O que cada olhar de gestão teme e valoriza em "
                   "cada opção está no Anexo."]
        for q in decisoes:
            linhas.append(f"**{q['id']}. {q['pergunta']}**" + (f" _(ligada a {', '.join(q['riscos'])})_" if q["riscos"] else ""))
            linhas += [f"- **{o['nome']}:** {o.get('o_que_e', '')}" for o in q["opcoes"]]
            if q.get("o_que_falta_saber"):
                linhas.append(f"- _Falta saber:_ {q['o_que_falta_saber']}")
    if resultado.get("pedir"):
        linhas.append("## Pedir à secretaria")
        linhas += [f"{k}. {p['o_que']}" + (f" _(serve a {p['serve_a']})_" if p.get("serve_a") else "")
                   for k, p in enumerate(resultado["pedir"], 1)]
    return "\n".join(linhas)


def _linha_revisao(rev):
    """Quem apontou e quem contestou o risco, em uma linha: a contagem, a contestação do advogado do diabo (a mais
    forte) e a resposta da consolidação. As objeções completas de cada agente vão no arquivo de anexos."""
    from .riscos import PAPEL_CONTRA
    objecoes = rev.get("objecoes") or []
    exageros = {o["papel"] for o in objecoes if o["tipo"] == "exagerado"}
    partes = [f"**Revisão:** {rev['sem_objecao']} de {rev['agentes']} agentes sem objeção"
              + (f" ({len(exageros)} {'vê' if len(exageros) == 1 else 'veem'} exagero)" if exageros else "")
              + (f"; {rev['origem']}" if rev.get("origem") and rev["origem"] != "análise" else "")]
    contra = [o for o in objecoes if o["papel"] == PAPEL_CONTRA]
    for o in contra[:1]:
        partes.append(f"{PAPEL_CONTRA} contesta: {_curto(o['motivo'], 160)}"
                      + (f" ({', '.join(o['fatos'][:3])})" if o.get("fatos") else "")
                      + (f" → consolidação: {_curto(o['resposta'], 120)}" if o.get("resposta") else ""))
    return "; ".join(partes) + "."


def markdown_objecoes(resultado):
    """Para o arquivo de anexos: todas as objeções de cada agente a cada risco, com a resposta da consolidação."""
    linhas = ["## Revisão dos agentes, risco a risco",
              "O que cada agente apontou como exagerado ou contestou, e o que a consolidação fez com isso."]
    algum = False
    for r in resultado.get("riscos") or []:
        rev = r.get("revisao") or {}
        if not rev.get("objecoes") and rev.get("origem", "análise") == "análise":
            continue
        algum = True
        linhas.append(f"**{r['id']}. {r['titulo']}** — {rev.get('sem_objecao', '?')} de {rev.get('agentes', '?')} sem objeção"
                      + (f"; {rev['origem']}" if rev.get("origem") and rev["origem"] != "análise" else ""))
        for o in rev.get("objecoes") or []:
            verbo = "contesta" if o["tipo"] == "contestado" else "vê exagero"
            linhas.append(f"- {o['papel']} {verbo}: {o['motivo']}" + (f" ({', '.join(o['fatos'])})" if o.get("fatos") else "")
                          + (f" → consolidação: {o['resposta']}" if o.get("resposta") else ""))
    return "\n".join(linhas) if algum else ""


def markdown_visoes(resultado):
    """Anexo B: o que cada olhar de gestão teme e valoriza em cada decisão, em tabela."""
    decisoes = [q for q in resultado.get("decisoes") or [] if q.get("visoes")]
    if not decisoes:
        return ""
    linhas = ["## Anexo – O que cada olhar de gestão teme e valoriza",
              "Seis agentes independentes, cada um com um olhar (Fazenda; controle e jurídico; área-fim; operação; nova "
              "gestão; advogado do diabo), leram a análise sem ver uns aos outros. Nenhum escolhe uma opção."]
    for q in decisoes:
        linhas += [f"**{q['id']}. {q['pergunta']}**", "| Olhar | Teme | Valoriza |", "|---|---|---|"]
        linhas += [f"| {v['papel']} | {v.get('teme') or '–'} | {v.get('valoriza') or '–'} |" for v in q["visoes"]]
    return "\n".join(linhas)


FRASE_CONFIANCA = {"alta": "Pode servir de base; confira os pontos marcados como \"órgão\".",
                   "média": "Confirme os pontos marcados como \"órgão\" ou \"sem comprovação\" antes de usar.",
                   "baixa": "Use para saber o que perguntar à secretaria, não para afirmar."}


def antes_de_ler(confianca, data_corte, cortes=None):
    """O quadro de abertura do dossiê e do relatório de riscos: o que é o documento, a confiança (com o motivo em
    português e o que fazer com ela), material cortado, como ler a base de cada informação e as ressalvas."""
    bases = "do dossiê de fontes públicas e dos dados da SEPLAG"
    linhas = ["## Antes de ler",
              f"- **O que é:** apoio à decisão gerado com IA a partir do que a secretaria enviou, {bases}, com data de "
              f"corte {data_corte or 'não informada'}. Expõe riscos e opções; não recomenda decisões."]
    if confianca:
        nivel = confianca["nivel"]
        por_que = "; ".join(confianca.get("por_que") or [])
        texto = f"- **Confiança desta análise: {nivel.upper()}**" + (f", porque {por_que}." if por_que else ".")
        if confianca.get("lacuna_checklist"):
            texto += " Silêncio do documento sobre esses temas não quer dizer que não haja risco."
        linhas.append(f"{texto} {FRASE_CONFIANCA[nivel]}")
    for c in cortes or []:
        linhas.append(f"- **Material cortado:** {c}. O que estava no trecho cortado não entrou na análise.")
    linhas.append("- **Base de cada informação:** \"fonte oficial ✔\" é dado conferido; \"órgão\" é o "
                  "que a secretaria declarou; \"sem comprovação\" precisa ser confirmado.")
    linhas.append("- **Contratos e calendário:** só o que a secretaria informou. Bases externas (SIGA, PNCP, portais) "
                  "não são usadas, por trazerem datas defasadas; contrato que a secretaria não citou não aparece aqui.")
    linhas.append("- **Sem revisão da equipe:** confira antes de usar.")
    return "\n".join(linhas)


def cortes_de_leitura(manifesto=None, avisos=None):
    """O que foi cortado do material da secretaria, em frases curtas: arquivos de uma pasta (pelo manifesto) e o
    relatório que passou do limite (pelos avisos da limpeza)."""
    cortes = []
    for c in (manifesto or {}).get("cortados") or []:
        cortes.append(f"{c['arquivo']} ({c['usados'] // 1000} de {c['caracteres'] // 1000} mil caracteres lidos)")
    for a in avisos or []:
        if "foi cortado" in a:
            cortes.append(re.sub(r"^⚠️\s*", "", a).rstrip(". ").replace(" e não entra na análise", ""))
    return cortes


def resumo_do_dossie(resultado, cobertura=None, indicadores=None):
    """A abertura do dossiê: a situação da secretaria em poucas frases, os números-chave e as lacunas do checklist."""
    from .checklist import linha_essencial
    linhas = ["## Em resumo"] + [f"- {x}" for x in resultado.get("situacao") or []]
    if indicadores:
        linhas += ["**Números-chave**", "| Indicador | Valor | Base |", "|---|---|---|"]
        linhas += [f"| {i['nome']} | {i['valor']} | {_base_curta(i)} |" for i in indicadores]
    lacunas = linha_essencial(cobertura) if cobertura else ""
    if lacunas:
        linhas.append(lacunas.replace("Ver a tabela de cobertura no Capítulo 1.", "Tabela no capítulo 6."))
    return "\n".join(linhas)


def resumo_dos_riscos(resultado, cobertura=None, limite_riscos=5):
    """A abertura do relatório de riscos: os riscos mais urgentes, as decisões em aberto e as lacunas."""
    from .checklist import linha_essencial
    linhas = ["## Resumo executivo"]
    riscos = resultado.get("riscos") or []
    if riscos:
        linhas.append("**Riscos mais urgentes**")
        linhas += [f"{k}. **{r['titulo']}** – {_agir(r)} · prioridade {r['prioridade'].lower()} · {r['firmeza']}"
                   for k, r in enumerate(riscos[:limite_riscos], 1)]
    if resultado.get("decisoes"):
        linhas.append("**Decisões em aberto**")
        linhas += [f"- {q['pergunta']}" for q in resultado["decisoes"]]
    lacunas = linha_essencial(cobertura) if cobertura else ""
    if lacunas:
        linhas.append(lacunas.replace("Ver a tabela de cobertura no Capítulo 1.", "Tabela no dossiê da secretaria."))
    linhas.append("_A base de cada risco (contratos, pessoal, passivos, orçamento, fontes e o que a secretaria informou) "
                  "está no dossiê da secretaria, que acompanha este relatório._")
    return "\n".join(linhas)


def em_uma_pagina(resultado, cobertura=None, indicadores=None, limite_riscos=5):
    """Resumo em uma página com tudo (situação, números, riscos, decisões, lacunas): usado na revisão de neutralidade."""
    return "\n".join([resumo_do_dossie(resultado, cobertura, indicadores),
                       resumo_dos_riscos(resultado, cobertura, limite_riscos).split("\n", 1)[1]])


def _chave_contrato(c):
    """O número do contrato (2023000622, 036/2025) ou, sem número, o contratado: para juntar a mesma linha citada mais
    de uma vez."""
    texto = str(c.get("contrato") or "")
    m = re.search(r"\d{7,}|\d{1,4}/\d{4}", texto)
    return m.group(0).lstrip("0") if m else _norm(c.get("contratado") or texto)[:30]


def _juntar_contratos(contratos, limite=15):
    """Uma linha por contrato, juntando o que veio em mais de uma citação (motivos, valor, vigência, observação). Ordem por criticidade (quantos motivos, valor), com no máximo `limite` linhas."""
    from .verificacao import _valores_fonte
    juntos = {}
    for c in contratos or []:
        k = _chave_contrato(c)
        if k not in juntos:
            juntos[k] = dict(c, motivos=list(c.get("motivos") or []))
            continue
        j = juntos[k]
        j["motivos"] = list(dict.fromkeys(j["motivos"] + list(c.get("motivos") or [])))
        for campo in ("objeto", "contratado", "observacao", "vigencia", "valor"):
            if not j.get(campo) and c.get(campo):
                j[campo] = c[campo]

    def reais(c):
        v = _valores_fonte(c.get("valor") or "")
        return max(v) if v else 0
    return sorted(juntos.values(), key=lambda c: (-len(c["motivos"]), -reais(c)))[:limite]


def _curto(texto, n):
    texto = re.sub(r"\s+", " ", str(texto or "")).strip(" .;")
    return texto if len(texto) <= n else texto[:n - 1].rstrip() + "…"


def _nome(texto, n):
    texto = _curto(texto, n)
    return texto.title() if texto.isupper() else texto


def markdown_contratos_criticos(contratos, limite=15):
    """A tabela dos contratos que a nova gestão precisa conhecer: os que a secretaria informou, apontados
    no material e conferidos (origem e valor), juntos por número de contrato, no máximo `limite` linhas."""
    linhas_c = _juntar_contratos(contratos, limite)
    if not linhas_c:
        return ""
    linhas = ["| Contrato | Objeto | Contratado | Valor | Vigência | Por que é crítico | Base |",
              "|---|---|---|---|---|---|---|"]
    for c in linhas_c:
        motivo = ", ".join(c["motivos"]) + (f". {_curto(c['observacao'], 90)}" if c.get("observacao") else "")
        linhas.append(f"| {_curto(c['contrato'], 28)} | {_nome(c.get('objeto'), 60) or '–'} | "
                      f"{_nome(c.get('contratado'), 36) or '–'} | {c.get('valor') or '–'} | {c.get('vigencia') or '–'} | "
                      f"{motivo} | {_base_curta(c)} |")
    nota = (f"{len(contratos)} contrato(s) apontados; os {len(linhas_c)} mais críticos acima. Todos no calendário "
            "consolidado (Excel). " if len(contratos or []) > len(linhas_c) else "")
    if nota:
        linhas.append(f"_{nota.strip()}_")
    return "\n".join(linhas)


def _secao_diagnostico(sec):
    linhas = []
    if sec.get("leitura"):
        linhas.append(sec["leitura"])
    linhas += [f"- {i['texto']} _({_origem(i)})_" for i in sec["itens"]]
    if not sec["itens"] and not sec.get("nao_se_sabe"):
        linhas.append("_Sem informação conferida._")
    if sec.get("nao_se_sabe"):
        linhas.append("_Não se sabe:_ " + "; ".join(sec["nao_se_sabe"]))
    return linhas


CAPITULOS = [("1. Contratos", ["Contratos"]), ("2. Pessoal", ["Pessoal"]),
             ("3. Passivos jurídicos e de controle", ["Passivos jurídicos e de controle"]),
             ("4. Orçamento, obras e estrutura", ["Orçamento e execução", "Obras e entregas", "Estrutura e dirigentes"])]


def _quadro_folha(q):
    """A folha do órgão, por código, do Caderno de RH: o que não é efetivo é o que pode sair na troca de governo."""
    return "\n".join([
        f"**Folha de pessoal** ([Caderno de RH, SEPLAG, {q['competencia']}]({q['url']}))",
        "| Vínculos ativos | Efetivos | Não efetivos (comissão, temporários, requisitados) | Folha do mês | Remuneração média |",
        "|---|---|---|---|---|",
        f"| {q['vinculos']} | {q['efetivos']} | {q['nao_efetivos']} ({q['pct_nao_efetivos']}) | {q['folha_mes']} | {q['remuneracao_media']} |"]
        + ([f"_{q['pct_nao_efetivos']} dos vínculos não são de servidor efetivo: é a parte da equipe que pode sair na troca "
            "de governo._"] if q["pct"] >= 50 else []))


def markdown_capitulos(diag, contratos_criticos=None, ficha=None, folha=None):
    """Os capítulos de dados, na ordem do que mais pesa: contratos (com a tabela dos críticos), pessoal, passivos,
    e por fim orçamento, obras e estrutura. Cada afirmação traz a origem conferida."""
    por_titulo = {_norm(s["titulo"]): s for s in (diag or {}).get("secoes") or []}
    linhas = []
    for titulo, blocos in CAPITULOS:
        linhas.append(f"## {titulo}")
        if titulo.startswith("1.") and contratos_criticos:
            linhas += ["**Contratos críticos**", markdown_contratos_criticos(contratos_criticos)]
        if titulo.startswith("2.") and folha:
            linhas.append(_quadro_folha(folha))
        if titulo.startswith("1.") and ficha:
            linhas += ["| Carteira que vence | Contratos (valor) |", "|---|---|"]
            linhas += [f"| {a} | {b} |" for a, b in ficha]
        for bloco in blocos:
            sec = por_titulo.get(_norm(bloco))
            if not sec:
                continue
            if len(blocos) > 1:
                linhas.append(f"### {sec['titulo']}")
            linhas += _secao_diagnostico(sec)
    return "\n".join(linhas)


def markdown_metodo(registro_id, modelos, resumo_dossie, confianca, numeros, neutralidade, revisoes, resultado):
    """Anexo 3: como o documento foi feito e o que foi conferido por código."""
    nao_enc = [n for n in numeros if n["situacao"] == "não encontrado"]
    calc = [n for n in numeros if n["situacao"] == "cálculo declarado"]
    linhas = ["## Anexo 3 – Como este documento foi feito",
              f"Registro {registro_id}. Modelos: {modelos.get('auxiliar')} (diagnóstico, calendário e confronto), "
              f"{modelos.get('debate')} (riscos, agentes e consolidação).",
              "1. O diagnóstico parte do dossiê de fontes públicas; o relatório da secretaria entra "
              "como informação dela. Cada afirmação foi conferida por código: item do dossiê existente ou trecho literal "
              "encontrado no relatório.",
              "2. Uma análise identificou riscos e decisões a partir do diagnóstico e dos vencimentos prioritários.",
              "3. Cinco agentes independentes, cada um com um olhar (" + ", ".join(p[1] for p in _papeis()) + "), "
              "revisaram a análise sem ver uns aos outros: riscos que faltaram, riscos exagerados e o que temem e "
              "valorizam em cada opção.",
              "4. Uma consolidação juntou as revisões. O código conferiu os fatos citados por cada risco, deu a firmeza "
              "da informação e calculou a prioridade com a mesma régua dos vencimentos.",
              f"- **Confiança calculada:** {confianca['nivel']}. " + "; ".join(confianca["motivos"]) + "."]
    if resumo_dossie:
        linhas.append(f"- **Dossiê:** {resumo_dossie['itens']} fatos; {resumo_dossie['conferidos']} conferidos na fonte; "
                      f"{resumo_dossie['nao_encontrado']} assunto(s) procurado(s) sem fonte.")
    opinaram = [r["papel"] for r in revisoes or [] if not r.get("erro")]
    falharam = [r["papel"] for r in revisoes or [] if r.get("erro")]
    usados = sorted({r.get("modelo") for r in revisoes or [] if r.get("modelo")})
    substitutos = [f"{r['papel']} (previsto {r['modelo_previsto']}: {r.get('erro_do_previsto', '')[:60]})"
                   for r in revisoes or [] if r.get("substituto")]
    linhas.append(f"- **Agentes que revisaram:** {len(opinaram)} de {len(revisoes or [])}"
                  + (f" (sem resposta: {', '.join(falharam)})" if falharam else "")
                  + (f". Modelos dos agentes: {', '.join(usados)}" + (" (provedores diferentes: os pontos cegos de um "
                     "modelo não se repetem nos cinco)" if len({m.split('/')[0] for m in usados}) > 1 else "")
                     if usados else "")
                  + (f". Rodaram no modelo principal porque o previsto falhou: {'; '.join(substitutos)}" if substitutos else "")
                  + ".")
    invalidos = sorted({f for r in resultado.get("riscos") or [] for f in r.get("fatos_invalidos") or []})
    if invalidos:
        linhas.append(f"- **Referências citadas que não existem no material (ignoradas):** {', '.join(invalidos)}.")
    linhas.append(f"- **Números do documento conferidos no material:** {len(numeros) - len(nao_enc) - len(calc)} de "
                  f"{len(numeros)}" + (f"; cálculos declarados: {', '.join(n['valor'] for n in calc)}" if calc else "")
                  + (f"; não encontrados, a conferir: {', '.join(n['valor'] for n in nao_enc)}" if nao_enc else "") + ".")
    if neutralidade and not neutralidade.get("erro"):
        linhas.append(f"- **Revisão de neutralidade ({neutralidade['modelo']}):** "
                      f"{neutralidade['avaliacao_geral'].replace('_', ' ')}"
                      + (". Trechos que soam como recomendação: " + "; ".join(f"\"{r['trecho']}\""
                         for r in neutralidade["recomendacoes_implicitas"]) if neutralidade["recomendacoes_implicitas"]
                         else "") + ".")
    return "\n".join(linhas)


def _papeis():
    from .riscos import PAPEIS
    return PAPEIS


def dossie_secretaria(resultado, diag, ficha, eventos, dossie, confronto, cobertura_md, nota_md, cobertura=None,
                      contratos_criticos=None, antes_md=""):
    """Produto 2, o dossiê da secretaria atualizado com o que ela informou: resumo e números-chave; 1. Contratos (com
    a tabela dos críticos); 2. Pessoal; 3. Passivos; 4. Orçamento, obras e estrutura; 5. o confronto entre o que a
    secretaria informou e o que as fontes mostram; 6. a cobertura do checklist; anexos com fontes citadas e prazos que
    não são contratos. Só dados, cada um com a origem conferida."""
    outros = [e for e in eventos or [] if not e.get("origem", "").startswith("Contratos")]
    venc = markdown_vencimentos(outros, limite=10)
    venc = ("## Anexo – Prazos de controle, convênios e outros vencimentos\n" + venc.split("\n", 1)[1]) if venc else ""
    partes = [antes_md, resumo_do_dossie(resultado, cobertura, (diag or {}).get("indicadores")),
              markdown_capitulos(diag, contratos_criticos, ficha, (dossie or {}).get("folha")),
              markdown_confronto(dossie, confronto),
              markdown_fontes(dossie, None, ids_citados(diag, resultado, contratos_criticos), cobertura_md),
              venc, nota_md]
    return "\n\n".join(p for p in partes if p)


def _contestacao_curta(r):
    """A contestação do advogado do diabo, se houver, em até 140 caracteres."""
    from .riscos import PAPEL_CONTRA
    rev = r.get("revisao") or {}
    contra = next((o for o in rev.get("objecoes") or [] if o["papel"] == PAPEL_CONTRA), None)
    return _curto(contra["motivo"], 140) if contra else ""


def _voto(r, eixo, valor):
    """O resultado de um eixo com a contagem de votos ("Alto 5/6"); sem votação, só o valor."""
    v = (r.get("votos") or {}).get(eixo)
    if not v:
        return valor or "–"
    return f"{v['nivel']} {v['votos']}/{v['total']}" + (" ⚠" if v.get("divergencia") else "")


def _divergencias(r):
    """As divergências entre agentes, em uma frase por eixo: quem votou diferente e por quê."""
    partes = []
    nomes = {"impacto": "impacto", "janela": "janela", "sensibilidade": "sensibilidade"}
    for eixo, rotulo in nomes.items():
        v = (r.get("votos") or {}).get(eixo) or {}
        for d in (v.get("divergencia") or [])[:1]:
            papel = d["papel"].split(":")[0].split(" (")[0]
            partes.append(f"{papel} vê {rotulo} {d['voto'].lower()}" + (f" ({_curto(d['por_que'], 110)})" if d.get("por_que") else ""))
    return "; ".join(partes)


def relatorio_riscos(resultado, cobertura, nota_md, limite_riscos=8, limite_pedir=5, antes_md=""):
    """Produto 3, o relatório de riscos, em até 3 páginas: situação; tabela de todos os riscos (prazo, janela,
    prioridade, sensibilidade política, base, revisão); cada risco em três linhas; decisões em aberto com as opções numa
    linha; o que pedir à secretaria. Sem anexo: as visões e objeções completas ficam no registro de auditoria."""
    from .checklist import linha_essencial
    riscos = sorted((resultado.get("riscos") or [])[:limite_riscos], key=lambda r: (r.get("agir_ate") or date.max, -r["nota"]))
    md = ([antes_md] if antes_md else []) + ["## Situação"] + [f"- {_curto(x, 260)}" for x in (resultado.get("situacao") or [])[:4]]
    lacunas = linha_essencial(cobertura) if cobertura else ""
    if lacunas and "sem informação" in lacunas:
        md.append(lacunas.replace(" Ver a tabela de cobertura no Capítulo 1.", " Ver o dossiê da secretaria."))
    if riscos:
        votado = any(r.get("votos") for r in riscos)
        md += ["## Decisões urgentes, em ordem de prazo",
               ("_Impacto, janela e repercussão política foram votados, item a item, pelos seis agentes independentes "
                "(a contagem diz quantos votaram no resultado; ⚠ marca divergência). Data que está no documento prevalece "
                "sobre o voto de janela. Prioridade: impacto × urgência, por código._" if votado else ""),
               "| # | Decisão (risco) | Agir até | Janela | Impacto | Repercussão política | Prioridade | Base |",
               "|---|---|---|---|---|---|---|---|"]
        for r in riscos:
            agir = f"{r['agir_ate']:%d/%m/%Y}" if r.get("agir_ate") else "–"
            md.append(f"| {r['id']} | {_curto(r.get('decisao') or r['titulo'], 90)} _({_curto(r['titulo'], 50)})_ | {agir} | "
                      f"{_voto(r, 'janela', r.get('horizonte'))} | {_voto(r, 'impacto', r.get('impacto'))} | "
                      f"{_voto(r, 'sensibilidade', r.get('sensibilidade'))} | {r['prioridade']} | "
                      f"{BASE_CURTA.get(r['firmeza'], r['firmeza'])} |")
        for r in riscos:
            md.append(f"**{r['id']}. {_curto(r.get('decisao') or r['titulo'], 180)}**"
                      + (f" — {_curto(r['quem_decide'], 60)}" if r.get("quem_decide") else ""))
            linha = f"Risco: {r['titulo']}. {_curto(r['causa'], 180)} → {_curto(r['consequencia'], 180)}"
            if r.get("motivo_sensibilidade"):
                linha += f". Repercussão: {_curto(r['motivo_sensibilidade'], 130)}"
            div = _divergencias(r)
            if div:
                linha += f". Divergência: {div}"
            contra = _contestacao_curta(r)
            if contra:
                linha += f". Advogado do diabo contesta: {contra}"
            md.append(f"- {linha}.")
    decisoes = resultado.get("decisoes") or []
    if decisoes:
        md += ["## Decisões em aberto", "_As opções têm o mesmo peso._"]
        for q in decisoes:
            opcoes = "; ".join(f"**{o['nome']}**" + (f" ({_curto(o.get('o_que_e'), 110)})" if o.get("o_que_e") else "")
                               for o in q["opcoes"])
            md.append(f"- **{q['id']}. {_curto(q['pergunta'], 160)}** {opcoes}."
                      + (f" _Falta saber: {_curto(q['o_que_falta_saber'], 140)}_" if q.get("o_que_falta_saber") else ""))
    pedir = (resultado.get("pedir") or [])[:limite_pedir]
    if pedir:
        md.append("## Pedir à secretaria")
        md += [f"{k}. {_curto(p['o_que'], 170)}" + (f" _({p['serve_a']})_" if p.get("serve_a") else "")
               for k, p in enumerate(pedir, 1)]
    md.append(nota_md)
    return "\n".join(m for m in md if m)


def auditoria_secretaria(resultado, dossie, confronto, metodo_md):
    """Produto 5, a auditoria legível: as objeções de cada agente risco a risco com a resposta da consolidação, todas as
    fontes do dossiê com as conferências, e o método (modelos, confiança, números conferidos, neutralidade). O registro
    completo, em JSON, fica ao lado."""
    partes = [markdown_objecoes(resultado),
              "## Todas as fontes do dossiê\n" + markdown_fontes(dossie, confronto).split("\n", 1)[1],
              metodo_md]
    return "\n\n".join(p for p in partes if p)


def documento_secretaria(*args, **kwargs):
    """Compatibilidade: o antigo documento único é o dossiê."""
    return dossie_secretaria(*args, **kwargs)


def markdown_vencimentos(eventos, limite=12, dias_passados=30):
    """Os vencimentos de maior prioridade do órgão, em tabela curta. O calendário completo vai no Excel."""
    from .produtos import ordem_de_prioridade
    eventos = list(eventos or [])
    candidatos = [e for e in eventos if e["dias"] >= -dias_passados]
    proximos = sorted(candidatos, key=ordem_de_prioridade)[:limite]
    if not proximos:
        return ""
    linhas = ["### Vencimentos prioritários",
              "Ordem por prioridade (impacto × urgência). \"Agir até\" desconta "
              "o tempo de assinar uma prorrogação (30 dias); nova licitação costuma levar uns 120 dias.",
              "| Prioridade | Agir até | Vence em | Evento | Valor | Situação |", "|---|---|---|---|---|---|"]
    for e in proximos:
        data = e["data"].strftime("%m/%Y" if e.get("so_mes") else "%d/%m/%Y")
        agir = e["agir_ate"].strftime("%d/%m/%Y") if e.get("agir_ate") else data
        evento = (e["evento"] + (f" ({e['objeto'][:80]})" if e.get("objeto") else "")
                  + (" – serviço essencial" if e.get("essencial") else ""))
        situacao = "; ".join(x for x in [e.get("criticidade", ""), "sem tempo para nova licitação"
                                         if e.get("sem_tempo_licitar") else ""] if x)
        linhas.append(f"| {e.get('prioridade', '–')} | {agir} | {data} | {evento} | {e.get('valor_texto') or '–'} | "
                      f"{situacao} |")
    if len(eventos) > len(proximos):
        linhas.append(f"_Calendário completo, com {len(eventos)} data(s), no Excel consolidado._")
    return "\n".join(linhas)


def markdown_fontes(dossie, confronto=None, citados=None, cobertura_md=""):
    """Anexo A: a cobertura do checklist, as fontes citadas no documento (uma linha cada, com link e selo) e o que o
    órgão informou contra o que as fontes mostram. Sem explicação de método: isso fica no arquivo de auditoria."""
    itens = itens_incluidos(dossie)
    linhas = ["## Anexo – Fontes"] if not cobertura_md else ["## 6. Cobertura do checklist obrigatório",
                                                             cobertura_md.split("\n", 1)[1] if cobertura_md.startswith("## ") else cobertura_md,
                                                             "## Anexo – Fontes"]
    usados = [i for i in itens if (not citados or i["id"] in citados)
]
    if usados:
        # uma linha por página consultada, com os ids dos fatos que ela sustenta: quem quiser conferir abre o link
        linhas.append("**Fontes citadas no documento** (os ids são os dos fatos no corpo do documento)")
        por_fonte = {}
        for i in usados:
            por_fonte.setdefault(i["url"] or i["fonte"], {"itens": [], "i": i})["itens"].append(i["id"])
        for g in por_fonte.values():
            i = g["i"]
            selo = "✔ equipe" if i.get("conferido_pela_equipe") else SELO_CHECAGEM.get(i["checagem"], "")
            fonte = (i["fonte"] or "fonte") + (f", {i['data_fonte']}" if i["data_fonte"] else "")
            fonte = f"[{fonte}]({i['url']})" if i["url"] else fonte
            linhas.append(f"- {fonte} · {selo} — {', '.join(g['itens'])}")
    return "\n".join(linhas)


def markdown_confronto(dossie, confronto):
    """Capítulo 5 do dossiê: o que a secretaria informou contra o que as fontes públicas mostram, e o que as
    fontes trazem e a secretaria não mencionou."""
    divs = (confronto or {}).get("divergencias") or []
    if not divs:
        return ""
    por_id = {i["id"]: i for i in itens_incluidos(dossie)}
    linhas = ["## 5. O que a secretaria informou e o que as fontes mostram",
              "Confronto feito pelo modelo e conferido por código: cada trecho da secretaria é literal e cada fato das "
              "fontes tem o link. Divergência não é erro de ninguém até ser apurada; é o que perguntar primeiro."]
    for d in divs:
        item = por_id.get(d["item"], {})
        fonte = f" ([fonte]({item['url']}))" if item.get("url") else ""
        if d["situacao"] == "contradiz":
            linhas.append(f"- **A secretaria informa:** {d['o_orgao_declara'] or d['trecho_relatorio']} "
                          f"**As fontes mostram:** {d['as_fontes_mostram']}{fonte}")
        else:
            linhas.append(f"- **Não mencionado pela secretaria:** {d['as_fontes_mostram']}{fonte}")
    return "\n".join(linhas)


def ids_citados(diag, resultado, contratos_criticos=None):
    """Os ids do dossiê (O1, E2...) que o documento usa: nos itens do diagnóstico, nos riscos e nos contratos."""
    ids = {i.get("origem_item") for s in (diag or {}).get("secoes") or [] for i in s["itens"] if i.get("origem_item")}
    ids |= {f for r in resultado.get("riscos") or [] for f in r.get("fatos") or [] if f[:1] in "OE"}
    ids |= {i.get("origem_item") for i in (diag or {}).get("indicadores") or [] if i.get("origem_item")}
    return ids


def nota_final(registro_id, modelos, confianca, data_corte, neutralidade=None, revisoes=None):
    """Uma linha de proveniência no fim do documento. O método completo fica na auditoria."""
    agentes = sum(1 for r in revisoes or [] if not r.get("erro"))
    familias = {r["modelo"].split("/")[0] for r in revisoes or [] if not r.get("erro") and r.get("modelo")}
    substitutos = [r["papel"] for r in revisoes or [] if r.get("substituto")]
    partes = [f"Apoio à decisão gerado com IA (registro {registro_id}; {modelos.get('auxiliar')} e {modelos.get('debate')}) "
              f"a partir do dossiê de fontes públicas e do que a secretaria informou, com data de "
              f"corte {data_corte or 'não informada'}. Não recomenda decisões. Confiança da análise: {confianca['nivel']} "
              f"({'; '.join(confianca['motivos'])}).",
              (f"{agentes} agente(s) independente(s) revisaram a análise"
               + (f", em {len(familias)} famílias de modelos" if len(familias) > 1 else ", todos na mesma família de modelos")
               + (f"; {len(substitutos)} rodaram no modelo principal porque o previsto falhou ({', '.join(substitutos)})"
                  if substitutos else "") + ".") if revisoes else "",
              f"Revisão de neutralidade: {neutralidade['avaliacao_geral'].replace('_', ' ')}."
              if neutralidade and not neutralidade.get("erro") and neutralidade.get("avaliacao_geral") else "",
              "Método, conferências por código e revisões completas no arquivo de auditoria."]
    return "_" + " ".join(p for p in partes if p) + "_"
