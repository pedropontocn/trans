"""Documentos: Word (a partir de Markdown, com tabelas, quadros e links) e Excel do calendário."""
import io
import re

import docx
from docx.enum.text import WD_TAB_ALIGNMENT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

from .debate import ler_personas
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
        medias.append(max(12, cabecalho_len + 2, min(60, sum(textos) / len(textos))))
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
        if b[0] == "h" and b[1] == 2 and _norm(b[2]).startswith(("anexo", "diagnostico")) and i > 0:
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


ROTULO_EVIDENCIA = {1: "confirmado em fonte oficial", 2: "cálculo, norma ou estudo", 3: "só na imprensa ou fonte não conferida",
                    4: "só informado pelo órgão", 5: "sem comprovação"}


def _rotulo_nivel(nivel):
    try:
        n = int(nivel)
    except (TypeError, ValueError):
        return "não informado"
    return f"{ROTULO_EVIDENCIA.get(n, 'não informado')} (nível {n})"


def anexo_debate(tm, personas_txt=""):
    """Anexo técnico do memorando, montado por código a partir do Tension Map: todo o detalhe do debate (posições,
    quem defende, evidência, tipo de divergência, mecanismo, o que mudaria) sem gastar tokens nem depender do modelo."""
    nomes = {p["id"]: p["nome"] for p in ler_personas(personas_txt)} if personas_txt else {}
    nome = lambda pid: nomes.get(pid, pid)
    linhas = ["## Anexo 2 – O debate em detalhe",
              "Os dilemas abaixo saíram de um debate entre papéis institucionais simulados (não são opiniões de pessoas "
              "ou órgãos reais). O memorando traz os três principais; aqui estão todos, com o detalhe técnico."]
    estab = tm.get("estabilidade") or {}
    for t in tm.get("trade_offs") or []:
        if not isinstance(t, dict):
            continue
        linhas.append(f"### {t.get('titulo', '')}")
        if t.get("descricao"):
            linhas.append(str(t["descricao"]))
        for rotulo, chave in (("Opção A", "polo_a"), ("Opção B", "polo_b")):
            polo = t.get(chave) or {}
            quem = ", ".join(nome(x) for x in (polo.get("defendido_por") or []))
            linhas.append(f"- **{rotulo}:** {polo.get('posicao', '')}" + (f" Defendida por: {quem}." if quem else "")
                          + (f" Argumento: {polo.get('argumento')}" if polo.get("argumento") else "")
                          + f" Informação: {_rotulo_nivel(polo.get('evidencia'))}.")
        detalhes = [("Quem ganha", t.get("quem_ganha")), ("Quem perde", t.get("quem_perde")),
                    ("Por que as duas opções não cabem juntas", t.get("mecanismo_causal")),
                    ("Natureza do desacordo", ", ".join(t.get("tipos_divergencia") or [])),
                    ("O que mudaria a balança", t.get("o_que_mudaria")),
                    ("Estabilidade", "não medida" if t.get("estabilidade") == "não medida" else
                     f"apareceu em {t['estabilidade']} rodadas independentes" if t.get("estabilidade") else "")]
        linhas += [f"- **{r}:** {v}" for r, v in detalhes if v]
    if tm.get("convergencias"):
        linhas.append("### Pontos em que todos concordaram")
        linhas += [f"- {c.get('tema', '')}" for c in tm["convergencias"] if isinstance(c, dict)]
    fracos = tm.get("sinais_fracos") or []
    if fracos:
        linhas.append("### Dilemas que apareceram em poucas rodadas (sinais fracos)")
        linhas += [f"- {f.get('titulo', '')} ({f.get('estabilidade', '')})" for f in fracos if isinstance(f, dict)]
    if tm.get("questoes_juridicas"):
        linhas.append("### Dúvidas jurídicas com resposta na norma")
        linhas += [f"- {q.get('questao', '')} ({q.get('norma', '')})" for q in tm["questoes_juridicas"] if isinstance(q, dict)]
    if estab.get("rodadas"):
        linhas.append(f"_Debate repetido em {estab['rodadas']} rodadas independentes; {estab.get('estaveis', 0)} "
                      "dilema(s) apareceram na maioria delas._")
    return "\n".join(linhas)


def markdown_verificacao(ev, numeros, registro_id, modelo, confianca=None, tm=None, neutralidade=None,
                         dossie=None, confronto=None, titulo="## Anexo 3 – Como este documento foi feito"):
    """Seção que vai no fim do Word, para o leitor saber o que foi conferido."""
    nao_enc = [n for n in numeros if n["situacao"] == "não encontrado"]
    calc = [n for n in numeros if n["situacao"] == "cálculo declarado"]
    linhas = [titulo,
              f"Documento elaborado com apoio de IA ({modelo}); registro {registro_id}. "
              "Os itens abaixo foram conferidos por código contra o dossiê de fontes e o relatório do órgão."]
    if dossie:
        linhas.append(f"- **Dossiê:** {dossie['itens']} itens ({dossie['estado']} sobre o Estado, {dossie['orgao']} sobre o "
                      f"órgão); {dossie['conferidos']} conferidos na fonte, {dossie['oficiais']} de fonte oficial; "
                      f"{dossie['nao_encontrado']} assunto(s) procurado(s) sem fonte confiável.")
    if confianca:
        linhas.append(f"- **Confiança calculada: {confianca['nivel']}.** " + "; ".join(confianca["motivos"]) + ".")
    if confronto and confronto.get("divergencias"):
        linhas.append(f"- **Autodeclaração × dossiê:** {len(confronto['divergencias'])} divergência(s) conferida(s) "
                      f"({sum(d['situacao'] == 'contradiz' for d in confronto['divergencias'])} contradição(ões), "
                      f"{sum(d['situacao'] == 'nao_mencionado' for d in confronto['divergencias'])} assunto(s) não mencionado(s)).")
    estab = (tm or {}).get("estabilidade")
    if estab:
        linhas.append(f"- **Estabilidade:** {estab['rodadas']} rodadas independentes; {estab['estaveis']} trade-off(s) "
                      f"apareceram em pelo menos {estab['minimo_para_estavel']} delas."
                      + (f" Estavam previstas {estab['previstas']}, mas as rodadas 1 e 2 chegaram aos mesmos trade-offs "
                         "e as demais não foram necessárias." if estab.get("previstas", 0) > estab["rodadas"] else ""))
        fracos = (tm or {}).get("sinais_fracos") or []
        if fracos:
            linhas.append("- **Sinais fracos (fora do memorando):** "
                          + "; ".join(f"{f.get('titulo', '')} ({f.get('estabilidade', '')})" for f in fracos[:8]) + ".")
    linhas.append(f"- **Fontes conferidas:** {len(ev['conferidas'])} item(ns) do dossiê, {len(ev['calculos'])} cálculo(s) "
                  f"e {len(ev.get('autodeclaracoes', []))} trecho(s) da autodeclaração do órgão.")
    if ev.get("limitadas"):
        linhas.append("- **Nível de evidência limitado pela fonte:** " + "; ".join(r["onde"] for r in ev["limitadas"][:10]) + ".")
    if ev["rebaixadas"]:
        linhas.append("- **Rebaixadas para nível 5 (fonte não encontrada):** "
                      + "; ".join(r["onde"] for r in ev["rebaixadas"][:10]) + ".")
    if ev["normas"]:
        refs = sorted({r["referencia"] for r in ev["normas"] if r["referencia"]})
        linhas.append("- **Citações legais a confirmar com a assessoria jurídica:** " + "; ".join(refs[:10]) + ".")
    if neutralidade and not neutralidade.get("erro"):
        partes = [f"avaliação geral: {neutralidade['avaliacao_geral'].replace('_', ' ')}"]
        if neutralidade["desequilibrados"]:
            partes.append("polos desequilibrados em " + ", ".join(
                f"{t.get('id')} ({'pende para A' if t['equilibrio'] == 'pende_para_a' else 'pende para B'})"
                for t in neutralidade["desequilibrados"]))
        if neutralidade["recomendacoes_implicitas"]:
            partes.append(f"{len(neutralidade['recomendacoes_implicitas'])} trecho(s) com recomendação implícita")
        linhas.append(f"- **Revisão de neutralidade ({neutralidade['modelo']}):** " + "; ".join(partes) + ".")
    conferidos = sum(1 for n in numeros if n["situacao"] == "conferido")
    linhas.append(f"- **Números do memorando conferidos no dossiê ou no relatório:** {conferidos} de {len(numeros)}.")
    if calc:
        linhas.append("- **Cálculos declarados (não constam das fontes como tal):** " + "; ".join(n["valor"] for n in calc[:10]) + ".")
    if nao_enc:
        linhas.append("- **Números não encontrados no dossiê nem no relatório, a conferir:** " + "; ".join(n["valor"] for n in nao_enc[:10]) + ".")
    return "\n".join(linhas)


def calendario_xlsx(eventos, descartados=None, titulo="Calendário de vencimentos críticos", data_corte=""):
    """Planilha do calendário: uma linha por evento, ordenada por data, com filtro, criticidade colorida e as
    instruções de leitura numa aba própria. Serve para um órgão ou para o consolidado do lote."""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter
    wb = Workbook()
    ws = wb.active
    ws.title = "Calendário"
    colunas = [("Data", 12), ("Dias até a data", 9), ("Criticidade", 20), ("Órgão", 30), ("Tipo", 16), ("Evento", 45),
               ("Objeto", 35), ("Valor (R$)", 16), ("Valor como informado", 18), ("O que acontece se nada for feito", 45),
               ("Decisão necessária", 40), ("Origem da informação", 20), ("Fonte", 40), ("Trecho conferido", 60),
               ("Prioridade", 11), ("Nota (impacto × urgência)", 10), ("Impacto", 9), ("Categoria", 24),
               ("Serviço essencial", 10), ("Agir até", 12), ("Sem tempo para nova licitação", 12),
               ("Situação no PNCP", 40)]
    ws.append([c for c, _ in colunas])
    cores_prioridade = {"Máxima": "C00000", "Alta": "F4B183", "Média": "FFE699", "Baixa": "E2EFDA"}
    cores = {"Vencido": "C00000", "Crítico (até 30 dias)": "F4B183", "Atenção (31 a 90 dias)": "FFE699",
             "Acompanhar": "E2EFDA"}
    for e in sorted(eventos, key=lambda x: (x["data"], -(x["valor"] or 0))):
        ws.append([e["data"], e["dias"], e["criticidade"], e["orgao"], e["tipo"], e["evento"], e["objeto"], e["valor"],
                   e["valor_texto"], e["consequencia"], e["decisao"], e["origem"], e["fonte"], e["trecho"],
                   e.get("prioridade", ""), e.get("prioridade_nota"), e.get("impacto", ""), e.get("categoria", ""),
                   "sim" if e.get("essencial") else "não", e.get("agir_ate"),
                   "sim" if e.get("sem_tempo_licitar") else "não", e.get("situacao_pncp", "")])
        linha = ws.max_row
        ws.cell(linha, 20).number_format = "dd/mm/yyyy"
        if e.get("prioridade") in cores_prioridade:
            ws.cell(linha, 15).fill = PatternFill("solid", fgColor=cores_prioridade[e["prioridade"]])
            if e["prioridade"] == "Máxima":
                ws.cell(linha, 15).font = Font(color="FFFFFF", bold=True)
        ws.cell(linha, 1).number_format = "mm/yyyy" if e["so_mes"] else "dd/mm/yyyy"
        ws.cell(linha, 8).number_format = '#,##0.00'
        if e["criticidade"] in cores:
            ws.cell(linha, 3).fill = PatternFill("solid", fgColor=cores[e["criticidade"]])
            if e["criticidade"] == "Vencido":
                ws.cell(linha, 3).font = Font(color="FFFFFF", bold=True)
        if str(e["fonte"]).startswith("http"):
            ws.cell(linha, 13).hyperlink = e["fonte"]
            ws.cell(linha, 13).font = Font(color="2E5FA8", underline="single")
    for j, (_, largura) in enumerate(colunas, 1):
        ws.column_dimensions[get_column_letter(j)].width = largura
        ws.cell(1, j).font = Font(bold=True, color="FFFFFF")
        ws.cell(1, j).fill = PatternFill("solid", fgColor="1B2A41")
        ws.cell(1, j).alignment = Alignment(wrap_text=True, vertical="center")
    for linha in ws.iter_rows(min_row=2):
        for c in linha:
            c.alignment = Alignment(wrap_text=True, vertical="top")
    ws.freeze_panes = "B2"
    ws.auto_filter.ref = ws.dimensions
    prioridades = wb.create_sheet("Prioridades", 0)        # a primeira aba: o que tratar primeiro, em todos os órgãos
    cab = ["Prioridade", "Agir até", "Vence em", "Órgão", "Categoria", "Serviço essencial", "Evento", "Valor (R$)",
           "Sem tempo para nova licitação", "Situação no PNCP", "Fonte"]
    prioridades.append(cab)
    from .produtos import ordem_de_prioridade
    for e in sorted([e for e in eventos if e["dias"] >= -30], key=ordem_de_prioridade)[:200]:
        prioridades.append([e.get("prioridade", ""), e.get("agir_ate"), e["data"], e["orgao"], e.get("categoria", ""),
                            "sim" if e.get("essencial") else "não", e["evento"], e["valor"],
                            "sim" if e.get("sem_tempo_licitar") else "não", e.get("situacao_pncp", ""), e["fonte"]])
        linha = prioridades.max_row
        for col in (2, 3):
            prioridades.cell(linha, col).number_format = "dd/mm/yyyy"
        prioridades.cell(linha, 8).number_format = '#,##0.00'
        if e.get("prioridade") in cores_prioridade:
            prioridades.cell(linha, 1).fill = PatternFill("solid", fgColor=cores_prioridade[e["prioridade"]])
    for j, largura in enumerate([11, 12, 12, 30, 24, 10, 50, 16, 12, 40, 40], 1):
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
                  "Criticidade (pela distância até a data de corte): Vencido; Crítico, até 30 dias; Atenção, de 31 a "
                  "90 dias; Acompanhar, mais de 90 dias.",
                  "Prioridade (régua igual para todos os órgãos, calculada por código): impacto × urgência. Impacto "
                  "Alto para serviço essencial (saúde, medicamentos, alimentação, custódia, vigilância, sistemas críticos "
                  "etc.) a partir de R$ 1 mi, decisão de controle ou outro contrato a partir de R$ 50 mi; Médio para "
                  "serviço essencial menor, outro contrato a partir de R$ 5 mi ou valor desconhecido; Baixo abaixo disso. Urgência pela data-limite para agir: já passou, até 30, até 90 ou mais de 90 dias. "
                  "Aditivo publicado no PNCP nos últimos 120 dias reduz a urgência em um nível. Máxima: nota 9 ou mais; "
                  "Alta: 6 a 8; Média: 3 a 5; Baixa: 1 ou 2.",
                  "Agir até: para contratos, 30 dias antes do fim (tempo de assinar uma prorrogação). Sem tempo para "
                  "nova licitação: o contrato vence em menos de 120 dias.",
                  "A aba Prioridades mostra os 200 eventos de maior prioridade de todos os órgãos. Limite: "
                  "contratos de gestão com OS, convênios e concessões não estão na base de contratos (SIGA).",
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

def sobre_o_documento(resumo, data_corte, confianca):
    """Nota curta de proveniência que abre o documento. Escrita por código, para não depender do modelo."""
    return ("## Sobre este documento\n"
            "Apoio à decisão gerado com IA a partir de pesquisa em fontes públicas"
            f" (data de corte: {data_corte or 'não informada'}) e do que o órgão informou. Não recomenda decisões. "
            f"Confiança da análise: {confianca['nivel']}. Gerado em processamento automático, sem revisão da equipe. "
            "As urgências seguem a ordem de prazo e valor calculada a partir dos dados; diagnóstico, fontes e "
            "verificação vêm depois.")


def inserir_sobre_documento(memorando, quadro):
    """Põe o quadro logo depois do título do memorando (ou no começo, se não houver título)."""
    linhas = memorando.splitlines()
    if linhas and linhas[0].lstrip().startswith("# "):
        return "\n".join([linhas[0], "", quadro, ""] + linhas[1:]).strip()
    return (quadro + "\n\n" + memorando).strip()


def markdown_diagnostico(diag):
    """O diagnóstico do órgão: cada afirmação já conferida na origem, com o rótulo entre parênteses."""
    if not (diag or {}).get("secoes"):
        return ""
    linhas = ["## Diagnóstico do órgão",
              "Como o órgão está e se organiza hoje. Cada afirmação foi conferida por código na fonte citada; a origem "
              "vem entre parênteses."]
    for sec in diag["secoes"]:
        linhas.append(f"### {sec['titulo']}")
        for i in sec["itens"]:
            origem = f"[{i['rotulo']}]({i['url']})" if i.get("url") else i["rotulo"]
            linhas.append(f"- {i['texto']} _({origem})_")
    if diag.get("lacunas"):
        linhas.append("### O que não se sabe")
        linhas += [f"- {x}" for x in diag["lacunas"]]
    if diag.get("descartados"):
        linhas.append(f"_{diag['descartados']} afirmação(ões) sem origem conferida foram retiradas._")
    return "\n".join(linhas)


def markdown_vencimentos(eventos, limite=12, dias_passados=30):
    """Os vencimentos de maior prioridade do órgão, em tabela curta. O calendário completo vai no Excel."""
    from .produtos import LIMITE_SIGA, ordem_de_prioridade
    candidatos = [e for e in eventos or [] if e["dias"] >= -dias_passados]
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
                                         if e.get("sem_tempo_licitar") else "", e.get("situacao_pncp", "")] if x)
        linhas.append(f"| {e.get('prioridade', '–')} | {agir} | {data} | {evento} | {e.get('valor_texto') or '–'} | "
                      f"{situacao} |")
    if len(eventos) > len(proximos):
        linhas.append(f"_Calendário completo, com {len(eventos)} data(s), no Excel consolidado._")
    if any(e.get("origem", "").startswith("Contratos") for e in eventos):
        linhas.append(f"_Limite: {LIMITE_SIGA}_")
    return "\n".join(linhas)


def markdown_fontes(dossie, confronto=None):
    """Anexo 1: o dossiê do órgão (fatos por tema, com link e selo), um nível abaixo no documento único."""
    md = markdown_dossie(dossie, confronto)
    corpo = [l for l in md.splitlines() if not l.startswith("# ")]
    corpo = [("#" + l) if l.startswith("## ") or l.startswith("### ") else l for l in corpo]
    return "## Anexo 1 – Fontes consultadas\n" + "\n".join(corpo)


def documento_orgao(memorando, diag, eventos, dossie, confronto, anexo_debate_md, verificacao_md):
    """O documento único de cada órgão, em Markdown: decisões (memorando), diagnóstico com os próximos vencimentos e,
    nos anexos, fontes, debate e verificação."""
    diag_md = markdown_diagnostico(diag)
    venc_md = markdown_vencimentos(eventos)
    if venc_md and not diag_md:
        diag_md = "## Diagnóstico do órgão"
    partes = [memorando, diag_md, venc_md, markdown_fontes(dossie, confronto), anexo_debate_md, verificacao_md]
    return "\n\n".join(p for p in partes if p)
