"""Caderno executivo: leitura da seção 3, ligação com a LOA e o plano, seleção, travas e montagem."""
import io
import json

import pytest

from conftest import RELATORIO

PAGINAS = [
    "Sumário\n3.1 Programas e políticas públicas........................10\n4.1 Orçamento e execução financeira.......19",
    "GOVERNO DO ESTADO DO RIO DE JANEIRO Relatório de Transição de Gestão – SEX\n"
    "3. PROGRAMAS, PROJETOS ESTRATÉGICOS E CONCESSÕES\n3.1 Programas e políticas públicas\n"
    "3.1.1 Calendário Estadual de Eventos\n"
    "Situação EM ANDAMENTO Doze eventos realizados em 2026.\n"
    "Objetivo / Produto Promover o turismo com eventos regionais.\n"
    "Público-alvo e abrangência Turistas e trade turístico. Estado do Rio de Janeiro.\n"
    "Metas e resultados Meta de 20 eventos; 12 realizados até agosto/2026.\n"
    "Valor / Fonte de recursos Ação 2027 – Formalização: liquidada R$ 30,00 (jan–ago/2026).\n"
    "Próximas etapas e prazos Primeiro evento de 2027 em 15/01/2027.\n"
    "Processo SEI / TCE-RJ / outro SEI-050001/000001/2026. Acordo sem número SEI\n"
    "Informações posicionadas em 29/10/2026 Página 1 de 2",
    "GOVERNO DO ESTADO DO RIO DE JANEIRO Relatório de Transição de Gestão – SEX\n"
    "procedimento informado.\n"
    "Responsável COOCP\n"
    "3.1.2 Artesanato Fluminense\n"
    "Situação AÇÃO PENDENTE A feira anual depende de contrato.\n"
    "Objetivo / Produto Apoiar artesãos.\n"
    "Responsável Coordenação de Artesanato\n"
    "3.2 Projetos estratégicos, obras e investimentos\n"
    "Texto de abertura da subseção, que não é de nenhuma ficha.\n"
    "3.2.1 Reforma da sede\n"
    "Situação A ESPECIFICAR Necessidade de reparos.\n"
    "Objeto / Produto Conservação predial.\n"
    "Execução física e financeira Não iniciado; sem estimativa de custos.\n"
    "Responsável DIRAF\n"
    "4. GESTÃO ADMINISTRATIVA, CONTRATOS E CONVÊNIOS\n4.1 Orçamento e execução financeira\nSEX\n"
    "Item Valor (R$) Observação\nDotação inicial (LOA do exercício) 1.600,00\nLiquidado 1.200,00\n"
    "Fonte: SIAFE-Rio, posição em 28/10/2026.\n4.2 Contratos e licitações\n"
    "Informações posicionadas em 29/10/2026 Página 2 de 2",
]


def _acao(uo, nome, cod, desc, total, pag=10):
    return {"uo": uo, "uo_nome": nome, "codigo": cod, "funcao": cod[:2], "subfuncao": cod[3:6], "programa": cod[7:11],
            "acao": cod[12:], "descricao": desc, "total": total, "pagina": pag}


@pytest.fixture
def bases(tmp_path, monkeypatch):
    sec, cia = "Secretaria de Estado de Exemplo", "Companhia de Exemplo"
    acoes = [_acao("10010", sec, "23.122.0002.2660", "Pessoal e Encargos Sociais", 500),
             _acao("10010", sec, "23.695.0452.4489", "Fomento ao Exemplo", 1000),
             _acao("10010", sec, "23.691.0452.4888", "Fortalecimento da Atividade Artesanal", 100),
             _acao("10710", cia, "23.695.0452.2027", "Formalização da Atividade", 50),
             _acao("10710", cia, "23.122.0002.0467", "Despesas Obrigatórias", 30),
             _acao("20010", "Secretaria de Estado de Outra Coisa", "10.302.0508.4933", "Outra", 9999)]
    uos = {"10010": {"nome": sec, "total_declarado": 1600, "atribuicoes": "Promover o turismo no Estado. Outra frase."},
           "10710": {"nome": cia, "total_declarado": 80, "atribuicoes": ""},
           "20010": {"nome": "Secretaria de Estado de Outra Coisa", "total_declarado": 9999, "atribuicoes": ""}}
    (tmp_path / "loa_2026.json").write_text(json.dumps({"uos": uos, "acoes": acoes}), encoding="utf-8")
    ploa = [dict(a, total=a["total"] + 10) for a in acoes]
    (tmp_path / "ploa_2027.json").write_text(json.dumps({"uos": uos, "acoes": ploa}), encoding="utf-8")
    (tmp_path / "plano_governo_2027_2030.json").write_text(json.dumps({"trechos": [
        {"id": "P33.9", "pagina": 33, "eixo": "Eixo 3 – Rio Próspero", "tema": "DA SERRA AO MAR", "tipo": "compromisso",
         "texto": "Criação do Calendário Estadual de Turismo, Esportes e Grandes Eventos, integrando competições."},
        {"id": "P33.8", "pagina": 33, "eixo": "Eixo 3 – Rio Próspero", "tema": "DA SERRA AO MAR", "tipo": "texto",
         "texto": "Transformar as riquezas naturais do Rio em desenvolvimento."}]}), encoding="utf-8")
    monkeypatch.setenv("PASTA_BASES", str(tmp_path))
    return tmp_path


def _manifesto():
    from transicao import secao3
    return {"secao3": [{"arquivo": "Relatorio_SEX.pdf", "fichas": secao3.fichas_das_paginas(PAGINAS, "Relatorio_SEX.pdf"),
                        "orcamento_41": secao3.quadro_41(PAGINAS, "Relatorio_SEX.pdf")}]}


def test_leitura_da_secao3_por_codigo(llm):
    from transicao import secao3
    fichas = secao3.fichas_das_paginas(PAGINAS, "Relatorio_SEX.pdf")
    assert [f["secao"] for f in fichas] == ["3.1.1", "3.1.2", "3.2.1"]       # o sumário e a abertura da 3.2 ficam fora
    f1 = fichas[0]
    assert f1["pagina"] == 2 and f1["titulo"] == "Calendário Estadual de Eventos"
    assert f1["campos"]["situacao"] == "EM ANDAMENTO Doze eventos realizados em 2026."
    # a ficha atravessa a quebra de página: o cabeçalho e o rodapé saem; a 2ª linha do rótulo do SEI também
    assert f1["campos"]["processo"] == "SEI-050001/000001/2026. Acordo sem número SEI informado."
    assert f1["campos"]["responsavel"] == "COOCP"
    assert fichas[2]["campos"]["objetivo"] == "Conservação predial." and fichas[2]["grupo"] == "3.2"
    q = secao3.quadro_41(PAGINAS, "Relatorio_SEX.pdf")
    assert q == [{"orgao": "SEX", "itens": {"dotacao_inicial": "1.600,00", "liquidado": "1.200,00"},
                  "data_base": "28/10/2026", "pagina": 3, "arquivo": "Relatorio_SEX.pdf"}]


def test_unidades_e_acoes_da_secretaria(llm, bases):
    from transicao import caderno
    loa, ploa = caderno.orcamento()
    uos, principal = caderno.unidades_da_secretaria("Secretaria de Exemplo - SEX", loa,
                                                    "Secretaria de Estado de Exemplo")
    assert uos == ["10010", "10710"] and principal == "10010"            # a vinculada vem junto, pelo órgão
    acoes = caderno.acoes_da_secretaria(uos, loa, ploa)
    a = acoes["10010:23.695.0452.4489"]
    assert a["loa_2026"] == 1000 and a["ploa_2027"] == 1010 and a["finalistica"]
    assert not acoes["10010:23.122.0002.2660"]["finalistica"]            # 0002: gestão administrativa
    assert caderno.unidades_da_secretaria("Secretaria de Nada", loa) == ([], None)


def test_caderno_seleciona_redige_confere_e_fecha_o_total(llm, bases):
    from transicao import caderno
    llm.fichas_ruins = {"3.2.1": {"programa": {"valor": "Reforma da sede", "fontes": ["3.2.1:titulo"]},
                                  "situacao": {"valor": "A reforma deve custar R$ 9.999,00", "fontes": ["3.2.1:situacao"]}}}
    riscos = [{"id": "R1", "titulo": "Feira de artesanato sem contrato"}, {"id": "R2", "titulo": "Outro"}]
    c = caderno.gerar("Secretaria de Exemplo - SEX", "SEX", _manifesto(), riscos, [],
                      {"modelo": "anthropic/claude-opus-5-5", "data_corte": "29/10/2026"},
                      nome_por_extenso="Secretaria de Estado de Exemplo")
    assert c["situacao"] == "gerado", c.get("motivo")
    aud = c["auditoria"]
    fichas = {f["secao"]: f for f in aud["fichas"]}
    # ação: o código citado na ficha vale direto; sem código, a proposta do modelo, conferida
    assert fichas["3.1.1"]["acoes"] == ["10710:23.695.0452.2027"] and fichas["3.1.1"]["acoes_por"].startswith("código")
    assert fichas["3.1.2"]["acoes"] == ["10010:23.695.0452.4489"] and fichas["3.1.2"]["acoes_por"].startswith("descrição")
    # seleção: riscos (3.1.2), plano (3.1.1, citação conferida) e orçamento (3.2.1, pela ação 4489)
    assert [fichas[s]["regra"] for s in ("3.1.1", "3.1.2", "3.2.1")] == ["plano de governo", "riscos e painel", "orçamento"]
    assert fichas["3.1.1"]["plano"]["trecho_id"] == "P33.9" and fichas["3.1.1"]["plano"]["eixo"].startswith("Eixo 3")
    assert fichas["3.1.2"]["plano"]["eixo"] == "Sem correspondência"         # a citação não estava no plano
    assert fichas["3.1.2"]["plano_recusado"]["motivo"] == "citação não está no plano"
    # a ficha ruim foi refeita uma vez e, falhando de novo, saiu do caderno com o motivo
    ruim = aud["redacoes"]["3.2.1"]
    assert ruim["dados"] is None and ruim["tentativas"] == 2 and llm.fichas_refeitas >= 1
    assert "número que não está na fonte" in ruim["motivo"] and "recomendação" in ruim["motivo"]
    assert c["fichas"] == 3 and c["fichas_geradas"] == 2
    # o total do quadro fecha com o finalístico da LOA (1.600 + 80 - 500 - 30)
    assert aud["verificacao_total"] == {"soma_do_quadro": 1150, "finalistico_da_loa": 1150, "confere": True}
    md = c["md"]
    assert "Ficha não gerada:" in md and "↳ 3.2.1 Reforma da sede (ficha não gerada)" in md
    assert "| **Total finalístico** | **1.150** |" in md and "Demais ações finalísticas (1) | 100 |" in md
    assert "Liquidado 2026 – SEX | R$ 1.200,00 | Relatório de Transição, 4.1, posição em 28/10/2026" in md
    assert "**Missão (principais atribuições, LOA 2026):** Promover o turismo no Estado." in md
    assert "(ação compartilhada com 1 outro(s) programa(s)" in md
    assert "marco de 15/01/2027 não está no calendário" in md                # aviso, não bloqueia
    assert md.count("<<<QUEBRA>>>") >= 4 and "…" not in md
    # CSV: ação e programas, total e "demais", com a regra de cada programa
    linhas = c["csv"].decode("utf-8-sig").splitlines()
    assert linhas[0].startswith("secretaria;linha;secao;programa")
    assert any(";3.1.1;" in l and "plano de governo" in l and ";sim" in l for l in linhas)
    assert any(l.startswith("SEX;Total finalístico") and ";1150;" in l for l in linhas)
    # o Word sai com cada ficha em página nova
    import docx
    from transicao import documentos
    doc = docx.Document(io.BytesIO(documentos.gerar_docx(md, {"tipo": "Caderno executivo"})))
    quebras = sum(1 for p in doc.paragraphs for r in p.runs for br in r._element.findall(
        "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}br")
        if br.get("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}type") == "page")
    assert quebras >= 4


def test_travas_da_ficha(llm):
    from transicao import caderno
    trechos = {"3.1.1:metas": "Metas e resultados: Meta de 20 eventos; 12 realizados.", "3.1.1:titulo": "Título"}
    ok = {"situacao": {"valor": "12 de 20 eventos realizados.", "fontes": ["3.1.1:metas"]}}
    assert caderno.conferir_ficha(ok, trechos) == []
    erros = caderno.conferir_ficha({"situacao": {"valor": "13 eventos.", "fontes": ["3.1.1:metas"]},
                                    "objetivo": {"valor": "Promover eventos", "fontes": ["X9"]},
                                    "publico_cobertura": {"valor": "É necessário ampliar (sem fim", "fontes": ["3.1.1:titulo"]}},
                                   trechos)
    assert any("13" in e for e in erros) and any("sem fonte válida" in e for e in erros)
    assert any("recomendação" in e for e in erros) and any("cortado" in e for e in erros)
    assert caderno.status("AÇÃO PENDENTE A Companhia") == "AÇÃO PENDENTE"
    assert caderno.status("A ESPECIFICAR A SETUR concede") == "A ESPECIFICAR"


def test_caderno_na_rodada(llm, bases, tmp_path):
    from transicao import analise
    from test_analise import CFG
    orgaos = [{"nome": "Secretaria de Exemplo - SEX", "ler": lambda: (RELATORIO, _manifesto())}]
    cfg = dict(CFG, caderno=True)
    linhas = analise.rodar_orgaos(orgaos, cfg, tmp_path / "saida", log=lambda *_: None)
    assert linhas[0]["situacao"] == "concluído" and linhas[0]["caderno"].endswith("fichas")
    saida = tmp_path / "saida"
    assert list((saida / "cadernos").glob("*_caderno.docx")) and list((saida / "cadernos").glob("*_quadro.csv"))
    aud = json.loads(next((saida / "auditoria").glob("*_caderno.json")).read_text(encoding="utf-8"))
    assert aud["situacao"] == "gerado" and aud["uso_tokens"]
    # sem relatório no modelo v2, o caderno não sai e a rodada segue
    orgaos = [{"nome": "Secretaria de Exemplo - SEX", "ler": lambda: (RELATORIO, {"lidos": []})}]
    linhas = analise.rodar_orgaos(orgaos, cfg, tmp_path / "outra", log=lambda *_: None)
    assert linhas[0]["situacao"] == "concluído" and linhas[0]["caderno"].startswith("não gerado: nenhum Relatório")
