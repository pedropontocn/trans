"""Testes das funções do app, sem a interface."""
import re

from conftest import RELATORIO, dossie_exemplo


def test_limpeza_tira_orientacoes_e_dados_pessoais(funcoes):
    texto, avisos = funcoes.limpar_relatorio(RELATORIO)
    assert "ORIENTAÇÕES DE PREENCHIMENTO" not in texto
    assert "Como preencher" not in texto
    assert "fulano@exemplo.gov.br" not in texto
    assert "PONTOS FOCAIS" not in texto
    assert "Quatro concorrências" in texto
    assert any("seção 9" in a for a in avisos)


def test_extrair_json_ignora_lixo_e_respeita_marcadores(funcoes):
    assert funcoes.extrair_json('texto {"a": 1} depois {quebrado') == {"a": 1}
    assert funcoes.extrair_json('[INÍCIO DO JSON]{"b": 2}[FIM DO JSON] {"c": 3}') == {"b": 2}
    assert funcoes.extrair_json("sem json nenhum") is None


def test_numeros_do_memorando(funcoes):
    memo = ("Licitações somam R$ 120,5 mi (80%), LOA de R$ 412 mi, diferença de R$ 13,3 mi (cálculo). "
            "Valor inventado: R$ 999,9 mi. Data 23/10/2026 e data inventada 12/12/2026.")
    achados = {n["valor"]: n["situacao"] for n in funcoes.verificar_numeros(memo, RELATORIO)}
    assert achados["R$ 120,5 mi"] == "conferido"
    assert achados["R$ 412 mi"] == "conferido"
    assert achados["80%"] == "conferido"
    assert achados["R$ 13,3 mi"] == "cálculo declarado"
    assert achados["R$ 999,9 mi"] == "não encontrado"
    assert achados["23/10/2026"] == "conferido"
    assert achados["12/12/2026"] == "não encontrado"


def test_numero_br(funcoes):
    assert funcoes._numero_br("236.441.332,55") == (236441332.55, 2)
    assert funcoes._numero_br("236,4") == (236.4, 1)
    assert funcoes._numero_br("1.302") == (1302.0, 0)


def test_custo_considera_cache(funcoes):
    sem_cache = [{"modelo": "anthropic/claude-opus-5-5", "entrada": 1_000_000, "entrada_sem_cache": 1_000_000,
                  "cache_leitura": 0, "cache_escrita": 0, "saida": 0}]
    com_cache = [{"modelo": "anthropic/claude-opus-5-5", "entrada": 1_000_000, "entrada_sem_cache": 0,
                  "cache_leitura": 1_000_000, "cache_escrita": 0, "saida": 0}]
    assert round(funcoes.custo_estimado(sem_cache)[0], 2) == 4.00
    assert round(funcoes.custo_estimado(com_cache)[0], 2) == 0.20
    # busca na web da Anthropic: US$ 10 por mil buscas
    assert round(funcoes.custo_estimado([dict(com_cache[0], buscas=20)])[0], 2) == 0.40


def test_word_gerado_abre_e_tem_matriz(funcoes):
    import io

    import docx
    from conftest import MEMORANDO
    dados = funcoes.gerar_docx(MEMORANDO, {"orgao": "Secretaria de Exemplo", "unidade": "Gabinete", "para": "Secretária",
                                          "assunto": "Teste", "data": "4 de novembro de 2026"})
    documento = docx.Document(io.BytesIO(dados))
    tabelas = [t for t in documento.tables if t.rows and "Probabilidade" in [c.text for c in t.rows[0].cells]]
    assert len(tabelas) == 1 and len(tabelas[0].rows) == 3      # cabeçalho + 2 riscos numa tabela só
    assert "**" not in "\n".join(p.text for p in documento.paragraphs)


def test_custo_da_escrita_de_cache_de_uma_hora(funcoes):
    base = {"modelo": "anthropic/claude-opus-5-5", "entrada": 1_000_000, "entrada_sem_cache": 0, "cache_leitura": 0,
            "cache_escrita": 1_000_000, "saida": 0}
    assert round(funcoes.custo_estimado([base])[0], 2) == 5.00                         # 5 minutos: 1,25x
    assert round(funcoes.custo_estimado([dict(base, cache_escrita_1h=1_000_000)])[0], 2) == 8.00   # 1 hora: 2x


def test_mensagens_sem_cache_para_outros_modelos(funcoes):
    msgs = funcoes.mensagens_com_cache("gemini/gemini-3.8-flash", "INSTRUÇÕES", "<dossie>\nx\n</dossie>", "pergunta")
    assert msgs[0] == {"role": "system", "content": "INSTRUÇÕES"}
    assert msgs[1]["content"].startswith("<dossie>") and msgs[1]["content"].endswith("pergunta")


def test_material_de_referencia_marca_o_relatorio_como_autodeclaracao(funcoes):
    dossie = dossie_exemplo(funcoes)
    m = funcoes.material_referencia(dossie, "texto do órgão")
    assert m.startswith("<dossie>") and "<relatorio>\nAUTODECLARAÇÃO DO ÓRGÃO" in m and m.endswith("</relatorio>")
    assert "<relatorio>" not in funcoes.material_referencia(dossie, "")
    texto = funcoes.texto_dossie(dossie)
    assert "[E1] (situacao_fiscal)" in texto and "nível máximo 1" in texto
    assert "PROCURADO E NÃO ENCONTRADO" in texto and "terceirizados" in texto


def test_nivel_maximo_por_tipo_de_fonte(funcoes):
    item = lambda tipo, chec="conferido", equipe=False: {"tipo_fonte": tipo, "checagem": chec, "conferido_pela_equipe": equipe}
    assert funcoes.nivel_maximo(item("documento_oficial")) == 1
    assert funcoes.nivel_maximo(item("documento_oficial", "inacessivel")) == 3
    assert funcoes.nivel_maximo(item("documento_oficial", "inacessivel", True)) == 1     # a equipe conferiu
    assert funcoes.nivel_maximo(item("estudo")) == 2
    assert funcoes.nivel_maximo(item("imprensa")) == 3
    assert funcoes.nivel_maximo(item("declaracao_politica")) == 3                        # promessa nunca é fato
    assert funcoes.nivel_maximo(item("hipotese")) == 4


def test_links_conferidos_por_codigo(funcoes, llm):
    d = dossie_exemplo(funcoes)
    chec = {i["id"]: i["checagem"] for i in d["itens"]}
    assert chec["O3"] == "conferido"                       # o script da página é ignorado e o trecho é achado
    assert chec["O2"] == "trecho_nao_encontrado"           # a página abre, mas não tem o trecho
    assert chec["O5"] == "inacessivel"
    assert chec["O6"] == "sem_trecho"
    # cada página é aberta uma vez só, mesmo citada por dois itens
    assert llm.paginas_abertas.count("https://transparencia.exemplo.gov.br/licitacoes") == 1
    r = funcoes.resumo_dossie(d)
    assert (r["itens"], r["estado"], r["orgao"], r["nao_encontrado"]) == (9, 3, 6, 2)
    assert r["conferidos"] == 6


def test_enderecos_internos_nao_sao_abertos(funcoes, llm):
    for url in ("http://localhost/x", "http://127.0.0.1/x", "http://169.254.169.254/latest", "http://10.0.0.5/a",
                "http://servidor.internal/a"):
        llm.paginas[url] = "<p>segredo</p>"
        assert funcoes.baixar_pagina(url) is None
    assert not any(u.startswith("http://") for u in getattr(llm, "paginas_abertas", []))     # nem chegou a abrir
    assert "Quatro concorrências" in funcoes.baixar_pagina("https://transparencia.exemplo.gov.br/licitacoes")


def test_nome_que_aponta_para_rede_interna_nao_e_aberto(funcoes, llm):
    llm.dns["metadados.exemplo.com"] = {"169.254.169.254"}
    llm.paginas["https://metadados.exemplo.com/x"] = "<p>segredo</p>"
    assert funcoes.baixar_pagina("https://metadados.exemplo.com/x") is None
    assert funcoes.baixar_pagina("file:///etc/passwd") is None
    assert not funcoes._endereco_publico("ftp://transparencia.exemplo.gov.br/a")


def test_redirecionamento_para_rede_interna_e_recusado(funcoes):
    import urllib.error
    import urllib.request
    import pytest
    manipulador = next(h for h in funcoes._abridor().handlers if isinstance(h, urllib.request.HTTPRedirectHandler))
    pedido = urllib.request.Request("https://transparencia.exemplo.gov.br/a")
    with pytest.raises(urllib.error.URLError):
        manipulador.redirect_request(pedido, None, 302, "Found", {}, "http://169.254.169.254/latest")
    seguinte = manipulador.redirect_request(pedido, None, 302, "Found", {}, "https://transparencia.exemplo.gov.br/b")
    assert seguinte.full_url == "https://transparencia.exemplo.gov.br/b"


def test_nomes_parecidos_nao_se_sobrescrevem(funcoes):
    assert funcoes._pastas_unicas(["Secretaria de Saúde", "Secretaria de Saude", "SES"]) == [
        "secretaria_de_saude", "secretaria_de_saude_2", "ses"]


def test_html_vira_texto(funcoes):
    assert funcoes._html_para_texto("<p>a &amp; b</p><script>x()</script><style>p{}</style>").split() == ["a", "&", "b"]




def test_pesquisa_usa_busca_na_web_em_grupos(funcoes, llm):
    d = funcoes.montar_dossie("anthropic/claude-sonnet-5-5", "Secretaria de Exemplo", "04/11/2026", "licitações")
    pesquisas = [c for c in llm.chamadas if "Monte a camada" in str(c["mensagens"])]
    assert len(pesquisas) == 5 and all(c["kw"]["web_search_options"] == {"search_context_size": "medium"} for c in pesquisas)
    assert all("Foco indicado pela equipe" in str(c["mensagens"]) for c in pesquisas)
    assert sorted(i["id"] for i in d["itens"]) == ["E1", "E2", "E3", "O1", "O2", "O3", "O4", "O5", "O6"]
    assert sum(u["buscas"] for u in d["uso"]) == 20
    assert all(not x["erro"] and not x["continuacao"] for x in d["diagnostico"])
    assert len(d["nao_encontrado"]) == 2
    # mesma pesquisa de novo: reaproveitada, sem nova busca
    de_novo = funcoes.montar_dossie("anthropic/claude-sonnet-5-5", "Secretaria de Exemplo", "04/11/2026", "licitações")
    assert de_novo["reaproveitado"] and len([c for c in llm.chamadas if "Monte a camada" in str(c["mensagens"])]) == 5


def test_resposta_sem_json_pede_que_o_modelo_termine(funcoes, llm):
    llm.grupos_sem_json = {"situacao_fiscal", "contratos_convenios"}
    d = funcoes.montar_dossie("anthropic/claude-sonnet-5-5", "Secretaria de Exemplo", "04/11/2026")
    assert len(d["itens"]) == 9                                   # a continuação recuperou os itens
    continuacoes = [c for c in llm.chamadas if str(c["mensagens"][-1]["content"]).startswith("Você parou antes")]
    assert len(continuacoes) == 2
    assert continuacoes[0]["mensagens"][1] == {"role": "assistant", "content": "Fiz as buscas e encontrei documentos relevantes."}
    assert sum(x["continuacao"] for x in d["diagnostico"]) == 2 and not any(x["erro"] for x in d["diagnostico"])


def test_erro_em_parte_da_pesquisa_nao_derruba_o_resto(funcoes, llm):
    llm.grupos_com_erro = {"situacao_fiscal"}
    d = funcoes.montar_dossie("anthropic/claude-sonnet-5-5", "Secretaria de Exemplo", "04/11/2026")
    assert len(d["itens"]) == 8
    erro = next(x for x in d["diagnostico"] if x["erro"])
    assert erro["blocos"][0] == "situacao_fiscal" and "RuntimeError: busca indisponível" in erro["erro"]


def test_pesquisa_toda_com_erro_mostra_o_motivo(funcoes, llm):
    import pytest
    llm.falhar_pesquisa = True
    with pytest.raises(RuntimeError, match="todas as buscas falharam: RuntimeError: busca indisponível"):
        funcoes.montar_dossie("gemini/gemini-3.8-flash", "Secretaria de Exemplo", "04/11/2026")


def test_pesquisa_sem_json_nenhum_devolve_dossie_vazio_com_diagnostico(funcoes, llm):
    from conftest import GRUPOS
    llm.grupos_sem_json = {g[0] for g in GRUPOS}
    llm.continuacao_sem_json = True
    d = funcoes.montar_dossie("anthropic/claude-sonnet-5-5", "Secretaria de Exemplo", "04/11/2026")
    assert d["itens"] == [] and all(x["erro"] == funcoes.SEM_JSON for x in d["diagnostico"])
    assert all("Fiz as buscas" in x["resposta"] and x["continuacao"] for x in d["diagnostico"])


def test_confronto_descarta_o_que_nao_confere(funcoes, llm):
    texto_rel, _ = funcoes.limpar_relatorio(RELATORIO)
    c = funcoes.confrontar("anthropic/claude-sonnet-5-5", dossie_exemplo(funcoes), texto_rel)
    assert [(d["item"], d["situacao"]) for d in c["divergencias"]] == [("O4", "nao_mencionado"), ("O3", "contradiz")]
    assert c["descartadas"] == 3      # item inexistente, trecho que não está no relatório e item que o relatório menciona
    assert "<relatorio>" in llm.mensagem_confronto and "<dossie>" in llm.mensagem_confronto
    assert "sem atribuir intenção" in funcoes.texto_confronto(c)
    assert funcoes.confrontar("m", dossie_exemplo(funcoes), "")["divergencias"] == []


def test_dossie_com_estado_compartilhado(funcoes, llm):
    estado = funcoes.pesquisar_estado("anthropic/claude-sonnet-5-5", "04/11/2026")
    assert [i["id"] for i in estado["itens"]] == ["E1", "E2", "E3"]
    antes = len([c for c in llm.chamadas if "Monte a camada" in str(c["mensagens"])])
    assert antes == 2
    d = funcoes.montar_dossie("anthropic/claude-sonnet-5-5", "Secretaria de Exemplo", "04/11/2026", estado=estado)
    pesquisas = [str(c["mensagens"]) for c in llm.chamadas if "Monte a camada" in str(c["mensagens"])][antes:]
    assert len(pesquisas) == 3 and not any('camada\\n"Estado"' in p for p in pesquisas)   # só o órgão
    assert sorted(i["id"] for i in d["itens"]) == ["E1", "E2", "E3", "O1", "O2", "O3", "O4", "O5", "O6"]
    assert d["estado_compartilhado"] and sum(x.get("compartilhado", False) for x in d["diagnostico"]) == 2
    # o Estado não é conferido de novo nem cobrado de novo no dossiê do órgão
    assert llm.paginas_abertas.count("https://www.exemplo.rj.gov.br/loa-2027") == 1
    assert sum(u["buscas"] for u in d["uso"]) == 12


def test_memorando_sem_orgao_nem_unidade_no_cabecalho(funcoes):
    """Com os campos "Órgão" e "De (unidade)" vazios, o Word sai sem eles, sem erro."""
    from conftest import MEMORANDO
    import io
    import docx
    dados = funcoes.gerar_docx(MEMORANDO, {"orgao": "", "unidade": "", "para": "", "assunto": "Teste", "data": "5 de novembro de 2026"})
    assert "MEMORANDO EXECUTIVO" in "\n".join(p.text for p in docx.Document(io.BytesIO(dados)).paragraphs)


def test_resumo_de_100_paginas_entra_inteiro(funcoes):
    """Um resumo de ~100 páginas (300 mil caracteres) entra inteiro; só o que passa de 400 mil é cortado, com aviso."""
    pagina = "## Contratos\n" + ("Contrato 012/2025, obra da Ponte do Rio, valor de R$ 1.000.000,00. " * 40) + "\n"
    resumo = pagina * 100 + "## Última seção\nRelação final de contratos."
    texto, avisos = funcoes.limpar_relatorio(resumo)
    assert len(resumo) > 250_000 and "Relação final de contratos." in texto
    assert not any("cortado" in a for a in avisos)
    grande, avisos = funcoes.limpar_relatorio(resumo * 2)
    assert len(grande) == funcoes.LIMITE_RELATORIO and any("passou do limite" in a for a in avisos)


def test_fontes_no_anexo_com_links_e_selos(funcoes):
    d = dossie_exemplo(funcoes)
    md = funcoes.markdown_dossie(d)
    assert md.startswith("# Dossiê – ") and "## Visão geral" in md and "## O órgão" in md
    assert "✔ conferido na fonte" in md and "⚠" in md
    confronto = {"divergencias": [{"item": d["itens"][-1]["id"], "situacao": "contradiz", "o_orgao_declara": "100 obras",
                                   "trecho_relatorio": "100 obras", "as_fontes_mostram": "80 obras"}]}
    anexo = funcoes.markdown_fontes(d, confronto)
    assert anexo.startswith("## Anexo 1 – Fontes consultadas") and "\n# " not in anexo   # títulos descem um nível
    assert "**As fontes mostram:** 80 obras" in anexo and "### Visão geral" in anexo


def test_calendario_so_com_datas_conferidas(funcoes, llm):
    from datetime import date
    rel, _ = funcoes.limpar_relatorio(RELATORIO)
    cal = funcoes.extrair_calendario("anthropic/claude-sonnet-5-5", dossie_exemplo(funcoes), rel, "Secretaria de Exemplo",
                                     "04/11/2026")
    assert [(e["data"], e["origem"], e["criticidade"]) for e in cal["eventos"]] == [
        (date(2026, 10, 23), "Informado pelo órgão", "Vencido")]
    assert cal["eventos"][0]["valor"] == 398750000.0
    motivos = {d["evento"]: d["motivo"] for d in cal["descartados"]}
    assert motivos == {"Data trocada": "a data não está no trecho citado",
                       "Trecho inventado": "trecho não encontrado no relatório"}


def test_formas_de_data_e_valores(funcoes):
    from datetime import date
    assert funcoes._ler_data("31/12/2026") == (date(2026, 12, 31), False)
    assert funcoes._ler_data("03/2027") == (date(2027, 3, 1), True)
    assert funcoes._ler_data("31/02/2026") is None
    assert funcoes._norm("31 de dezembro de 2026") in funcoes._formas_da_data(date(2026, 12, 31), False)
    assert funcoes._valor_em_reais("R$ 998,1 mi") == 998100000.0 and funcoes._valor_em_reais("R$ 1,2 bi") == 1.2e9
    assert funcoes.criticidade(10).startswith("Crítico") and funcoes.criticidade(60).startswith("Atenção")


def test_calendario_em_excel(funcoes):
    import io
    from datetime import date
    from openpyxl import load_workbook
    eventos = [{"data": date(2027, 3, 1), "so_mes": True, "dias": 117, "criticidade": "Acompanhar", "orgao": "SECID",
                "tipo": "Contrato", "evento": "Fim da locação de máquinas", "objeto": "Contrato 12/2025", "valor": 5e6,
                "valor_texto": "R$ 5 mi", "consequencia": "Fica sem máquinas", "decisao": "Prorrogar ou não",
                "origem": "Informado pelo órgão", "fonte": "relatório do órgão", "trecho": "vence em 03/2027"},
               {"data": date(2026, 11, 11), "so_mes": False, "dias": 6, "criticidade": "Crítico (até 30 dias)",
                "orgao": "Estado", "tipo": "Prazo legal", "evento": "Fim das emendas", "objeto": "LOA 2027", "valor": None,
                "valor_texto": "", "consequencia": "", "decisao": "", "origem": "Fonte pública (dossiê)",
                "fonte": "https://alerj.exemplo/emendas", "trecho": "até 11/11/2026"}]
    wb = load_workbook(io.BytesIO(funcoes.calendario_xlsx(eventos, [{"orgao": "SECID", "data": "x", "evento": "y",
                                                                     "motivo": "z"}])))
    ws = wb["Calendário"]
    assert ws["A2"].value.date() == date(2026, 11, 11) and ws["D3"].value == "SECID"     # ordenado por data
    assert ws["M2"].hyperlink.target == "https://alerj.exemplo/emendas" and ws.auto_filter.ref
    assert ws["A3"].number_format == "mm/yyyy" and set(wb.sheetnames) == {"Prioridades", "Calendário", "Como ler", "Descartados"}


def test_diagnostico_so_com_afirmacoes_conferidas(funcoes, llm):
    rel, _ = funcoes.limpar_relatorio(RELATORIO)
    d = dossie_exemplo(funcoes)
    diag = funcoes.extrair_diagnostico("anthropic/claude-sonnet-5-5", d, rel, "Secretaria de Exemplo")
    assert [s["titulo"] for s in diag["secoes"]] == funcoes.SECOES_DIAGNOSTICO   # sempre os mesmos blocos
    com_itens = {s["titulo"]: s for s in diag["secoes"] if s["itens"]}
    assert list(com_itens) == ["Missão e estrutura", "Orçamento e execução"] and diag["descartados"] == 2
    rotulos = [i["rotulo"] for i in com_itens["Orçamento e execução"]["itens"]]
    assert rotulos[1] == "informado pelo órgão" and rotulos[0].startswith(("confirmado", "fonte pública"))
    ids = [i["id"] for s in diag["secoes"] for i in s["itens"]]
    assert ids == [f"F{k}" for k in range(1, len(ids) + 1)]                     # numerados para os riscos citarem
    md = funcoes.markdown_diagnostico(diag)
    assert md.startswith("## Capítulo 1 – Diagnóstico") and "### Orçamento e execução" in md
    assert "_Não se sabe:_ Organograma atualizado" in md and "40 subsecretarias" not in md
    assert "A secretaria tem pendências de controle." in md


def test_regua_de_risco_igual_para_todos(funcoes):
    from datetime import date, timedelta
    corte = date(2026, 11, 6)
    def ev(dias, valor, objeto, termos=None, tipo="Contrato"):
        return {"data": corte + timedelta(days=dias), "dias": dias, "valor": valor, "evento": "Fim do contrato",
                "objeto": objeto, "tipo": tipo, "valor_texto": "", "origem": "Contratos do Estado (SIGA/PNCP)",
                "termos": termos if termos is not None else ""}
    eventos = funcoes.avaliar_riscos([
        ev(40, 300e6, "PAVIMENTAÇÃO DE VIAS"),                                     # obra grande
        ev(40, 2e6, "FORNECIMENTO DE ALIMENTAÇÃO PARA PRESOS"),                    # essencial pequeno
        ev(40, 2e6, "ALIMENTAÇÃO HOSPITALAR", "Termo Aditivo Termo 1 (2026-10-20)"),  # essencial com aditivo
        ev(200, 1e6, "MATERIAL DE ESCRITÓRIO"),
    ], "06/11/2026")
    obra, presos, hospital, escritorio = eventos
    assert presos["essencial"] and presos["impacto"] == "Alto" and presos["categoria"].startswith("Continuidade")
    assert obra["categoria"] == "Obra" and obra["impacto"] == "Alto"
    assert presos["agir_ate"] == corte + timedelta(days=10) and presos["sem_tempo_licitar"]
    assert presos["prioridade"] == "Máxima" and hospital["prioridade_nota"] < presos["prioridade_nota"]
    assert "aditivo publicado em 20/10/2026" in hospital["situacao_pncp"]
    assert escritorio["prioridade"] == "Baixa" and not escritorio["sem_tempo_licitar"]
    md = funcoes.markdown_vencimentos(eventos)
    assert md.index("ALIMENTAÇÃO PARA PRESOS") < md.index("ALIMENTAÇÃO HOSPITALAR") and "serviço essencial" in md
    assert "contratos de gestão com OS" in md
    import io
    import openpyxl
    wb = openpyxl.load_workbook(io.BytesIO(funcoes.calendario_xlsx([dict(e, orgao="SEX", criticidade="x", so_mes=False,
                                consequencia="", decisao="", fonte="", trecho="") for e in eventos])))
    assert wb.sheetnames[0] == "Prioridades" and wb["Prioridades"]["A2"].value == "Máxima"



def test_quadro_sobre_o_documento(funcoes):
    q = funcoes.sobre_o_documento("04/11/2026", {"nivel": "média"})
    assert q.startswith("## Sobre este documento") and "Não recomenda decisões" in q and "média" in q
    assert "sem revisão da equipe" in q


def _resultado_exemplo():
    from datetime import date
    risco = lambda k, titulo, nota, prio: {
        "id": f"R{k}", "titulo": titulo, "causa": "c", "consequencia": "d", "em_jogo": "R$ 1 mi", "prazo": "",
        "em_curso": "aditivo publicado" if k == 1 else "", "decisao": "Renovar ou não?", "quem_decide": "SECID",
        "categoria": "Continuidade de serviço", "impacto": "Alto", "chance": "Alta", "fatos": ["F1"],
        "fatos_invalidos": [], "firmeza": "dado do SIGA/PNCP", "agir_ate": date(2026, 12, 1), "nota": nota,
        "prioridade": prio}
    return {"situacao": ["Linha 1.", "Linha 2."],
            "riscos": [risco(k, f"Risco {k}", 12 - k, "Máxima" if k < 3 else "Média") for k in range(1, 8)],
            "decisoes": [{"id": "Q1", "pergunta": "Renovar agora?", "opcoes": [{"nome": "Renovar", "o_que_e": "x"},
                          {"nome": "Esperar", "o_que_e": "y"}], "o_que_falta_saber": "saldo", "riscos": ["R1"],
                          "visoes": [{"papel": "Controle e jurídico (TCE-RJ, PGE, MPRJ)", "teme": "aditivo irregular",
                                      "valoriza": "legalidade"}]}],
            "pedir": [{"o_que": "Lista de contratos", "serve_a": "R1"}]}


def test_documento_curto_montado_por_codigo(funcoes, llm):
    import io
    import docx
    rel, _ = funcoes.limpar_relatorio(RELATORIO)
    d = dossie_exemplo(funcoes)
    diag = funcoes.extrair_diagnostico("m", d, rel, "Secretaria de Exemplo")
    resultado = _resultado_exemplo()
    texto = funcoes.documento_secretaria(resultado, diag, [("Contratos que vencem em até 180 dias", "3")], [], d, None,
                                         funcoes.resumo_dossie(d), "## Anexo 3 – Como este documento foi feito\nx",
                                         funcoes.sobre_o_documento("04/11/2026", {"nivel": "média"}))
    ordem = [texto.index(t) for t in ["## Sobre este documento", "## O essencial", "## Os riscos mais urgentes",
                                      "## Capítulo 1 – Diagnóstico", "### Ficha", "### Missão e estrutura",
                                      "## Capítulo 2", "### R1. Risco 1", "### Outros riscos a acompanhar",
                                      "### Decisões em aberto", "### Pedir à secretaria", "## Anexo 1", "## Anexo 3"]]
    assert ordem == sorted(ordem)
    assert len(re.findall(r"^### R\d", texto, re.M)) == 5 and "| R6. Risco 6 |" in texto            # 5 em detalhe, o resto na tabela
    assert "- **Em curso:** aditivo publicado" in texto and "_Não se sabe:_ Organograma atualizado" in texto
    assert "_Controle e jurídico (TCE-RJ, PGE, MPRJ):_ teme aditivo irregular; valoriza legalidade" in texto
    for bloco in funcoes.SECOES_DIAGNOSTICO:
        assert f"### {bloco}" in texto                                          # ficha padrão: todos os blocos
    doc = docx.Document(io.BytesIO(funcoes.gerar_docx(texto, {"orgao": "Equipe", "assunto": "Secretaria de Exemplo"})))
    quebras = sum('w:br w:type="page"' in p._p.xml for p in doc.paragraphs)
    assert quebras >= 4                                                           # capítulos e anexos em página nova


def test_riscos_conferidos_e_ordenados_por_codigo(funcoes, llm):
    from datetime import date, timedelta
    rel, _ = funcoes.limpar_relatorio(RELATORIO)
    d = dossie_exemplo(funcoes)
    diag = funcoes.extrair_diagnostico("m", d, rel, "Secretaria de Exemplo")
    ev = {"data": date(2026, 11, 20), "dias": 16, "valor": 2e6, "evento": "Fim do contrato 1", "objeto": "ALIMENTAÇÃO DE PRESOS",
          "tipo": "Contrato", "origem": "Contratos do Estado (SIGA/PNCP)", "termos": "", "valor_texto": "R$ 2 mi"}
    funcoes.avaliar_riscos([ev], "04/11/2026")
    venc = funcoes.vencimentos_numerados([ev])
    bruto = {"situacao": ["s"], "riscos": [
        {"id": "R1", "titulo": "Obra", "categoria": "Obras e projetos", "impacto": "Médio", "chance": "Média",
         "prazo": "31/03/2027", "fatos": ["F1"], "causa": "a", "consequencia": "b", "decisao": "?"},
        {"id": "R2", "titulo": "Alimentação de presos", "categoria": "Continuidade de serviço", "impacto": "Alto",
         "fatos": ["V1"], "causa": "a", "consequencia": "b", "decisao": "?"},
        {"id": "R3", "titulo": "Sem base", "categoria": "Inventada", "impacto": "Alto", "prazo": "antes da posse",
         "fatos": ["X9"], "causa": "a", "consequencia": "b", "decisao": "?"}],
        "decisoes": [{"pergunta": "?", "opcoes": [{"nome": "A"}], "riscos": ["R2"]},
                     {"pergunta": "Renovar?", "opcoes": [{"nome": "A"}, {"nome": "B"}], "riscos": ["R2", "R9"]}],
        "pedir": [{"o_que": "contratos", "serve_a": "R2 e R3"}]}
    r = funcoes.conferir_e_ordenar(bruto, diag, venc, d, "04/11/2026")
    titulos = [x["titulo"] for x in r["riscos"]]
    assert titulos[0] == "Alimentação de presos" and r["riscos"][0]["id"] == "R1"     # renumerados pela prioridade
    assert r["riscos"][0]["firmeza"] == "dado do SIGA/PNCP" and r["riscos"][0]["prioridade"] == "Máxima"
    sem_base = next(x for x in r["riscos"] if x["titulo"] == "Sem base")
    assert sem_base["firmeza"] == "sem comprovação" and sem_base["nota"] <= 5 and sem_base["categoria"] == "Continuidade de serviço"
    assert sem_base["agir_ate"] == date(2027, 1, 1)
    assert len(r["decisoes"]) == 1 and r["decisoes"][0]["riscos"] == ["R1"]         # decisão com uma opção só sai
    assert r["pedir"][0]["serve_a"].startswith("R1 e R")
    c = funcoes.confianca(funcoes.resumo_dossie(d), r["riscos"])
    assert c["nivel"] in ("baixa", "média") and any("riscos apoiados" in m for m in c["motivos"])
    assert funcoes.confianca(None, [])["nivel"] == "baixa"
    _ = timedelta


def test_material_dos_riscos_tem_ids_e_limite_da_base(funcoes, llm):
    from datetime import date
    rel, _ = funcoes.limpar_relatorio(RELATORIO)
    d = dossie_exemplo(funcoes)
    diag = funcoes.extrair_diagnostico("m", d, rel, "Secretaria de Exemplo")
    ev = {"data": date(2026, 12, 20), "dias": 46, "valor": 9e6, "evento": "Fim do contrato 7", "objeto": "LIMPEZA",
          "tipo": "Contrato", "origem": "Contratos do Estado (SIGA/PNCP)", "termos": "", "valor_texto": "R$ 9 mi"}
    funcoes.avaliar_riscos([ev], "04/11/2026")
    texto = funcoes.material("SEX", diag, funcoes.vencimentos_numerados([ev]), "DIVERGÊNCIAS: x", "04/11/2026")
    assert "[F1]" in texto and "[V1] vence 20/12/2026" in texto and "agir até 20/11/2026" in texto
    assert "contratos de gestão com OS" in texto and "DIVERGÊNCIAS: x" in texto
