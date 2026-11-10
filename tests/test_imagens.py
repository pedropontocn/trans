"""Leitura do que está em imagem: PDF digitalizado ou com imagem grande, slides, prints no Word e no Excel, imagens
soltas e dentro de .zip. Os arquivos são montados de verdade (PyMuPDF, python-pptx, python-docx, openpyxl, Pillow);
só o modelo é falso."""
import io
import json
import random
import zipfile

import pytest


def _png(largura=900, altura=650, semente=1, formato="PNG"):
    """Imagem com cara de documento (linhas de "texto" e uma tabela); cada semente dá uma imagem diferente."""
    from PIL import Image, ImageDraw
    rnd = random.Random(semente)
    img = Image.new("RGB", (largura, altura), (255, 255, 255))
    d = ImageDraw.Draw(img)
    for y in range(20, altura - 20, 22):
        d.rectangle((20, y, 20 + rnd.randrange(largura // 3, largura - 40), y + 9), fill=(30, 30, 30))
    d.rectangle((largura // 2, altura // 2, largura - 30, altura - 30), outline=(0, 0, 0), width=3)
    saida = io.BytesIO()
    img.save(saida, formato)
    return saida.getvalue()


def _pdf():
    """p1: só texto; p2: digitalizada (imagem na página inteira); p3: texto e logo pequeno; p4: texto e uma tabela
    colada como imagem (um terço da página)."""
    import pymupdf
    doc = pymupdf.open()
    texto = "Relatório da secretaria com texto digitado suficiente para não ser página digitalizada. " * 3
    p = doc.new_page()
    p.insert_text((50, 80), texto[:90])
    p.insert_text((50, 100), texto[90:180])
    p = doc.new_page()
    p.insert_image(p.rect, stream=_png(semente=2))
    p = doc.new_page()
    p.insert_text((50, 80), texto[:90])
    p.insert_text((50, 100), texto[90:180])
    p.insert_image(pymupdf.Rect(500, 20, 560, 60), stream=_png(300, 300, semente=3))
    p = doc.new_page()
    p.insert_text((50, 80), texto[:90])
    p.insert_text((50, 100), texto[90:180])
    p.insert_image(pymupdf.Rect(50, 300, 545, 650), stream=_png(semente=4))
    return doc.tobytes()


def _pptx():
    """slide 1: figura grande; slide 2: só o logo pequeno; slide 3: a mesma figura do slide 1."""
    from pptx import Presentation
    from pptx.util import Inches
    apres = Presentation()
    grande, logo = _png(semente=5), _png(300, 300, semente=6)
    for imagem, largura in ((grande, Inches(8)), (logo, Inches(0.6)), (grande, Inches(8))):
        slide = apres.slides.add_slide(apres.slide_layouts[6])
        slide.shapes.add_picture(io.BytesIO(imagem), Inches(1), Inches(1), width=largura)
    saida = io.BytesIO()
    apres.save(saida)
    return saida.getvalue()


def _docx():
    import docx
    from docx.shared import Inches
    d = docx.Document()
    d.add_paragraph("Ofício com a tabela de obras colada como print.")
    d.add_picture(io.BytesIO(_png(120, 120, semente=7)), width=Inches(0.5))      # ícone
    d.add_picture(io.BytesIO(_png(semente=8)), width=Inches(6))                   # print da tabela
    saida = io.BytesIO()
    d.save(saida)
    return saida.getvalue()


def _xlsx():
    import openpyxl
    from openpyxl.drawing.image import Image as XLImage
    wb = openpyxl.Workbook()
    wb.active["A1"] = "Planilha com gráfico colado"
    wb.active.add_image(XLImage(io.BytesIO(_png(semente=9))), "B3")
    saida = io.BytesIO()
    wb.save(saida)
    return saida.getvalue()


def test_acha_as_imagens_que_importam_em_cada_formato(llm):
    from transicao import imagens
    pdf = imagens.imagens_do_arquivo("r.pdf", _pdf())
    assert [r for r, _ in pdf] == ["página 2", "página 4, imagem"]          # sem a p1 (texto) e o logo da p3
    assert [r for r, _ in imagens.imagens_do_arquivo("a.pptx", _pptx())] == ["slide 1", "slide 3"]  # logo fora
    assert [r for r, _ in imagens.imagens_do_arquivo("o.docx", _docx())] == ["imagem 2"]             # ícone fora
    assert [r for r, _ in imagens.imagens_do_arquivo("p.xlsx", _xlsx())] == ["imagem 1"]
    assert [r for r, _ in imagens.imagens_do_arquivo("foto.jpg", _png(formato="JPEG"))] == ["imagem"]
    assert imagens.imagens_do_arquivo("x.emf", b"nao e imagem") == []
    from PIL import Image
    for _, jpeg in pdf:
        assert max(Image.open(io.BytesIO(jpeg)).size) <= imagens.LADO_MAXIMO


def test_transcricao_entra_no_texto_do_orgao_e_no_manifesto(llm):
    from transicao import entrada, imagens
    envio = [("SEEDUC.pptx", _pptx()), ("SEEDUC.png", _png(semente=10)), ("SEEDUC.pdf", _pdf())]
    orgaos = entrada.orgaos_do_envio(envio)
    assert [o["nome"] for o in orgaos] == ["SEEDUC"]
    with imagens.leitura("anthropic/claude-opus-5-5") as lidas:
        texto, manifesto = orgaos[0]["ler"]()
    # pptx: 2 slides (a figura repetida no slide 3 é a mesma: 1 transcrição); png: 1; pdf: 2
    assert lidas["transcritas"] == 4 and len(llm.imagens_vistas) == 4
    assert all(u.startswith("data:image/jpeg;base64,") for u in llm.imagens_vistas)
    assert texto.count("(transcrição de imagem)") == 4 and "|Ponte do Rio|R$ 1.234.567,89|" in texto
    assert "### Slide 1 (transcrição de imagem)" in texto and "### Página 2 (transcrição de imagem)" in texto
    assert {l["arquivo"] for l in manifesto["lidos"]} == {a for a, _ in envio}       # a imagem solta também
    assert set(manifesto["com_imagem_transcrita"]) == {a for a, _ in envio}
    assert len(lidas["uso"]) == 4 and lidas["uso"][0]["etapa"] == "leitura: transcrição de imagem"
    # a mesma imagem de novo: vem da resposta guardada, sem nova chamada
    with imagens.leitura("anthropic/claude-opus-5-5"):
        orgaos[0]["ler"]()
    assert len(llm.imagens_vistas) == 4


def test_pdf_digitalizado_e_imagem_dentro_do_zip_de_pastas(llm):
    import pymupdf
    from transicao import entrada, imagens
    doc = pymupdf.open()
    p = doc.new_page()
    p.insert_image(p.rect, stream=_png(semente=11))
    llm.texto_relatorio = ""                          # o conversor de texto não acha nada no PDF digitalizado
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("SEEDUC/digitalizado.pdf", doc.tobytes())
        z.writestr("SEEDUC/fotos/quadro.jpeg", _png(semente=12, formato="JPEG"))
    orgaos = entrada.orgaos_do_envio([("envio.zip", buf.getvalue())], cada_pasta=True)
    with imagens.leitura("anthropic/claude-opus-5-5"):
        texto, manifesto = orgaos[0]["ler"]()
    assert texto.count("(transcrição de imagem)") == 2 and not manifesto["pulados"] and not manifesto["erros"]
    # desligada: o que só existe em imagem fica de fora, com o motivo
    with imagens.leitura("anthropic/claude-opus-5-5", ligado=False):
        texto, manifesto = orgaos[0]["ler"]()
    assert not texto.strip() and {p["motivo"] for p in manifesto["pulados"]} == {
        "sem texto digitado; está em imagem e a leitura de imagens está desligada"}


def test_teto_por_secretaria(llm):
    from transicao import entrada, imagens
    envio = [("SEEDUC" + "_" * k + ".png", _png(semente=20 + k)) for k in range(5)]
    with imagens.leitura("anthropic/claude-opus-5-5", teto=3) as lidas:
        texto, _ = entrada.orgaos_do_envio(envio)[0]["ler"]()
    assert lidas["transcritas"] == 3 and lidas["acima_do_teto"] == 2 and texto.count("(transcrição de imagem)") == 3


def test_rodada_transcreve_e_conta_o_custo(llm, tmp_path):
    from transicao import analise, entrada
    from test_analise import CFG
    orgaos = entrada.orgaos_do_envio([("SEEDUC.docx", _docx())])
    linhas = analise.rodar_orgaos(orgaos, CFG, tmp_path, log=lambda *_: None)
    assert linhas[0]["situacao"] == "concluído", linhas[0]
    lidos = json.loads(next((tmp_path / "auditoria").glob("*_arquivos_lidos.json")).read_text(encoding="utf-8"))
    assert lidos["imagens"]["transcritas"] == 1 and lidos["imagens"]["modelo"] == CFG["modelo_auxiliar"]
    usos = [c for c in llm.chamadas if "Você transcreve imagens" in str(c["mensagens"][0]["content"])]
    assert len(usos) == 1
    registro = (tmp_path / "auditoria" / "seeduc.json").read_text(encoding="utf-8")
    assert "leitura: transcrição de imagem" in registro                 # entra no uso (e no custo) da secretaria
    # sem a opção, nada é transcrito
    llm.imagens_vistas.clear()
    analise.rodar_orgaos(orgaos, dict(CFG, ler_imagens=False), tmp_path / "sem", log=lambda *_: None)
    assert not llm.imagens_vistas


def test_fundo_com_texto_digitado_e_imagem_lisa_ficam_de_fora(llm):
    # a capa com foto de fundo e o texto digitado por cima já é lida pelo conversor; a caixa branca não tem nada
    import pymupdf
    from PIL import Image
    from transicao import imagens
    branca = io.BytesIO()
    Image.new("RGB", (800, 600), (255, 255, 255)).save(branca, "PNG")
    doc = pymupdf.open()
    p = doc.new_page()
    p.insert_image(p.rect, stream=_png(semente=30))
    for k in range(6):
        p.insert_text((60, 300 + 20 * k), "Texto digitado por cima da foto de fundo, já lido pelo conversor.")
    p = doc.new_page()
    p.insert_text((50, 80), "Página com texto e uma caixa branca, que não é conteúdo, desenhada como imagem.")
    p.insert_text((50, 100), "Segunda linha de texto digitado, para a página não parecer digitalizada.")
    p.insert_image(pymupdf.Rect(50, 300, 545, 650), stream=branca.getvalue())
    assert imagens.imagens_do_arquivo("capa.pdf", doc.tobytes()) == []
