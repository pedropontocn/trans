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
    """Um resumo de ~100 páginas (300 mil caracteres) entra inteiro; só o que passa de 800 mil é cortado, com aviso."""
    pagina = "## Contratos\n" + ("Contrato 012/2025, obra da Ponte do Rio, valor de R$ 1.000.000,00. " * 40) + "\n"
    resumo = pagina * 100 + "## Última seção\nRelação final de contratos."
    texto, avisos = funcoes.limpar_relatorio(resumo)
    assert len(resumo) > 250_000 and "Relação final de contratos." in texto
    assert not any("cortado" in a for a in avisos)
    grande, avisos = funcoes.limpar_relatorio(resumo * 3)
    assert len(grande) == funcoes.LIMITE_RELATORIO and any("passou do limite" in a for a in avisos)


def test_fontes_no_anexo_com_links_e_selos(funcoes):
    d = dossie_exemplo(funcoes)
    md = funcoes.markdown_dossie(d)
    assert md.startswith("# Dossiê – ") and "## Visão geral" in md and "## O órgão" in md
    assert "✔ conferido na fonte" in md and "⚠" in md
    confronto = {"divergencias": [{"item": d["itens"][-1]["id"], "situacao": "contradiz", "o_orgao_declara": "100 obras",
                                   "trecho_relatorio": "100 obras", "as_fontes_mostram": "80 obras"}]}
    anexo = funcoes.markdown_fontes(d, None, citados={"O1", "E1"}, cobertura_md="## Cobertura\n| tabela |")
    assert anexo.startswith("## 6. Cobertura do checklist obrigatório\n| tabela |\n## Anexo – Fontes") and "\n# " not in anexo
    assert " — O1" in anexo and "O2" not in anexo
    confronto_md = funcoes.markdown_confronto(d, confronto)
    assert confronto_md.startswith("## 5. O que a secretaria informou") and "**As fontes mostram:** 80 obras" in confronto_md
    # uma linha por página, com os ids dos fatos que ela sustenta
    todos = funcoes.markdown_fontes(d, None)
    assert todos.count("\n- ") < len(funcoes.itens_incluidos(d))
    assert "Visão geral" not in anexo and "Sobre este dossiê" not in anexo               # sem explicação de método


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
    # as três primeiras colunas são para filtrar: janela de decisão (contada da posse), secretaria (sigla) e mês
    assert [ws.cell(1, j).value for j in (1, 2, 3)] == ["Janela de decisão", "Secretaria", "Mês"]
    assert ws["D2"].value.date() == date(2026, 11, 11) and ws["G3"].value == "SECID" and ws["B3"].value == "SECID"
    assert ws["A2"].value == "Antes da posse" and ws["A3"].value == "Primeiros 100 dias" and ws["C2"].value == "2026-11"
    assert ws["A2"].fill.fgColor.rgb.endswith("C00000")                    # antes da posse em vermelho
    assert ws["P2"].hyperlink.target == "https://alerj.exemplo/emendas" and ws.auto_filter.ref == ws.dimensions
    assert ws["D3"].number_format == "mm/yyyy" and set(wb.sheetnames) == {"Prioridades", "Calendário", "Como ler", "Descartados"}
    assert wb["Prioridades"].auto_filter.ref and wb["Prioridades"]["A1"].value == "Janela de decisão"


def test_diagnostico_so_com_afirmacoes_conferidas(funcoes, llm):
    rel, _ = funcoes.limpar_relatorio(RELATORIO)
    d = dossie_exemplo(funcoes)
    diag = funcoes.extrair_diagnostico("anthropic/claude-sonnet-5-5", d, rel, "Secretaria de Exemplo")
    assert [s["titulo"] for s in diag["secoes"]] == funcoes.SECOES_DIAGNOSTICO   # sempre os mesmos blocos
    com_itens = {s["titulo"]: s for s in diag["secoes"] if s["itens"]}
    assert list(com_itens) == ["Como se organiza", "Orçamento e execução"] and diag["descartados"] == 2
    # organograma: só as unidades com origem conferida; panorama vem junto
    assert [u["unidade"] for u in diag["organograma"]] == ["Gabinete do Secretário", "Subsecretaria de Obras",
                                                            "Superintendência de Projetos", "EMOP"]
    assert diag["organograma"][3]["vinculada"] and diag["panorama"][0].startswith("A Secretaria de Exemplo")
    assert [(i["nome"], i["rotulo"]) for i in diag["indicadores"]] == [("LOA 2026", "confirmado em fonte oficial"),
                                                                        ("Empenhado", "informado pelo órgão")]
    rotulos = [i["rotulo"] for i in com_itens["Orçamento e execução"]["itens"]]
    assert rotulos[1] == "informado pelo órgão" and rotulos[0].startswith(("confirmado", "fonte pública"))
    ids = [i["id"] for s in diag["secoes"] for i in s["itens"]]
    assert ids == [f"F{k}" for k in range(1, len(ids) + 1)]                     # numerados para os riscos citarem
    md = funcoes.markdown_capitulos(diag)
    titulos = [l for l in md.splitlines() if l.startswith("## ")]
    from test_analise import TITULOS_DO_ROTEIRO
    assert titulos == TITULOS_DO_ROTEIRO                 # sem a leitura da análise, os itens 3 e g não aparecem
    assert "_Não se sabe:_ Organograma atualizado" in md and "40 subsecretarias" not in md
    assert "A secretaria tem pendências de controle." in md and "└── Subsecretaria de Obras" in md


def test_regua_de_risco_igual_para_todos(funcoes):
    from datetime import date, timedelta
    corte = date(2026, 11, 6)
    def ev(dias, valor, objeto, termos=None, tipo="Contrato"):
        return {"data": corte + timedelta(days=dias), "dias": dias, "valor": valor, "evento": "Fim do contrato",
                "objeto": objeto, "tipo": tipo, "valor_texto": "", "origem": "Informado pelo órgão",
                "termos": termos if termos is not None else ""}
    eventos = funcoes.avaliar_riscos([
        ev(40, 300e6, "PAVIMENTAÇÃO DE VIAS"),                                     # obra grande
        ev(40, 2e6, "FORNECIMENTO DE ALIMENTAÇÃO PARA PRESOS"),                    # essencial pequeno
        ev(40, 2e6, "ALIMENTAÇÃO HOSPITALAR"),                                     # essencial
        ev(200, 1e6, "MATERIAL DE ESCRITÓRIO"),
    ], "06/11/2026")
    obra, presos, hospital, escritorio = eventos
    assert presos["essencial"] and presos["impacto"] == "Alto" and presos["categoria"].startswith("Continuidade")
    assert obra["categoria"] == "Obra" and obra["impacto"] == "Alto"
    assert presos["agir_ate"] == corte + timedelta(days=10) and presos["sem_tempo_licitar"]
    assert presos["prioridade"] == "Máxima" and hospital["prioridade_nota"] == presos["prioridade_nota"]
    assert escritorio["prioridade"] == "Baixa" and not escritorio["sem_tempo_licitar"]
    md = funcoes.markdown_vencimentos(eventos)
    assert md.index("ALIMENTAÇÃO PARA PRESOS") < md.index("ALIMENTAÇÃO HOSPITALAR") and "serviço essencial" in md
    assert "SIGA" not in md and "PNCP" not in md
    import io
    import openpyxl
    wb = openpyxl.load_workbook(io.BytesIO(funcoes.calendario_xlsx([dict(e, orgao="SEX", criticidade="x", so_mes=False,
                                consequencia="", decisao="", fonte="", trecho="") for e in eventos])))
    assert wb.sheetnames[0] == "Prioridades" and wb["Prioridades"]["C2"].value == "Máxima" and wb["Prioridades"]["B2"].value == "SEX"



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
    criticos = [{"contrato": "Contrato 1/2026", "objeto": "Limpeza", "contratado": "A", "valor": "R$ 1,0 mi",
                 "vigencia": "01/12/2026", "motivos": ["vence em breve", "emergencial"], "observacao": "prioridade máxima",
                 "rotulo": "dado do SIGA/PNCP", "url": ""},
                {"contrato": "Contrato 1/2026", "objeto": "repetido", "contratado": "A", "valor": "", "vigencia": "",
                 "motivos": ["valor alto"], "observacao": "", "rotulo": "informado pelo órgão", "url": ""}]
    cobertura = [{"id": "C1", "tema": "Contratos a vencer", "estado": "não procurado"}] + \
                [{"id": f"C{k}", "tema": "x", "estado": "encontrado"} for k in range(2, 11)]
    nota = funcoes.nota_final("abc", {"auxiliar": "m1", "debate": "m2"}, {"nivel": "média", "motivos": ["x"]}, "04/11/2026")
    # produto 2: o dossiê
    texto = funcoes.dossie_secretaria(resultado, diag, [("Contratos que vencem em até 180 dias", "3")], [], d, None,
                                      "## Cobertura – o que foi procurado\n| tabela |", nota,
                                      cobertura=cobertura, contratos_criticos=criticos)
    ordem = [texto.index(t) for t in ["## Panorama", "**Ficha rápida**", "| LOA 2026 | R$ 412 mi |",
                                      "**Lacunas: 1 de 10", "## 1. Estrutura organizacional vigente", "## 2. Funcionamento atual",
                                      "## b) Cargos e força de trabalho", "## c) Contratos relevantes e riscos de vencimento",
                                      "- **Contrato 1/2026 – A** · ", "## e) Programas e serviços essenciais", "## Fontes",
                                      "_Apoio à decisão gerado com IA (registro abc"]]
    assert ordem == sorted(ordem)
    assert "| tabela |" not in texto and "Cobertura do checklist" not in texto   # a cobertura vai para a auditoria
    assert texto.count("**Contrato 1/2026 – A**") == 1                                  # o repetido da planilha não entra duas vezes
    assert "_Não se sabe:_ Organograma atualizado" in texto
    for fora in ("Riscos por prioridade", "### R1.", "Sobre este documento", "Como este documento foi feito", "teme aditivo"):
        assert fora not in texto, fora                                            # riscos e método ficam em outros produtos
    # produto 3: o relatório de riscos, em ordem de prazo e sem anexo
    riscos = funcoes.relatorio_riscos(resultado, cobertura, nota, confianca={"nivel": "média", "por_que": ["x"]},
                                      data_corte="04/11/2026")
    ordem = [riscos.index(t) for t in ["- **O que é:**", "- **Confiança: MÉDIA**", "- **Como ler:**",
                                       "pontos de decisão, por janela:", "## ", "**R", "- **Problema:**",
                                       "- **Consequência:**", "- **Ponto de decisão:**", "- **Prazo:**",
                                       "## Informações que faltam: a pauta de investigação",
                                       "| # | O que falta | Para que serve | Onde procurar | Risco | Quem apontou |",
                                       "_Apoio à decisão gerado com IA (registro abc"]]
    assert ordem == sorted(ordem)
    assert "## Situação" not in riscos and "## Antes de ler" not in riscos                 # direto ao ponto
    assert "Decisões em aberto" not in riscos and "Pedir à secretaria" not in riscos and "Quem decide" not in riscos
    titulos = re.findall(r"^\*\*(R\d+) · ", riscos, re.M)
    assert len(titulos) == len(resultado["riscos"][:10]) and len(set(titulos)) == len(titulos)   # todos, uma vez só
    assert "Anexo" not in riscos and "aditivo irregular" not in riscos and "1. Contratos" not in riscos
    assert not re.search(r"\((?:[FVO]\d+(?:, )?)+\)", riscos)                              # sem códigos soltos no texto
    # agrupado por janela, na ordem das janelas
    janelas = re.findall(r"^## (.+)$", riscos.split("## Informações que faltam")[0], re.M)
    assert janelas and janelas == [j for j in funcoes.JANELAS_DO_RELATORIO if j in janelas]
    # produto 5: a auditoria legível
    auditoria = funcoes.auditoria_secretaria(resultado, d, None, "## Anexo 3 – Como este documento foi feito\nx")
    assert "## Todas as fontes do dossiê" in auditoria and auditoria.rstrip().endswith("x")
    doc = docx.Document(io.BytesIO(funcoes.gerar_docx(texto, {"orgao": "Equipe", "assunto": "Secretaria de Exemplo"})))
    quebras = sum('w:br w:type="page"' in p._p.xml for p in doc.paragraphs)
    assert quebras == 0                                                           # as fontes seguem na mesma página


def test_riscos_conferidos_e_ordenados_por_codigo(funcoes, llm):
    from datetime import date, timedelta
    rel, _ = funcoes.limpar_relatorio(RELATORIO)
    d = dossie_exemplo(funcoes)
    diag = funcoes.extrair_diagnostico("m", d, rel, "Secretaria de Exemplo")
    ev = {"data": date(2026, 11, 20), "dias": 16, "valor": 2e6, "evento": "Fim do contrato 1", "objeto": "ALIMENTAÇÃO DE PRESOS",
          "tipo": "Contrato", "origem": "Informado pelo órgão", "termos": "", "valor_texto": "R$ 2 mi"}
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
    assert r["riscos"][0]["firmeza"] == "informado pelo órgão" and r["riscos"][0]["prioridade"] == "Máxima"
    sem_base = next(x for x in r["riscos"] if x["titulo"] == "Sem base")
    assert sem_base["firmeza"] == "sem comprovação" and sem_base["nota"] <= 5 and sem_base["categoria"] == "Continuidade de serviço"
    assert sem_base["agir_ate"] == date(2026, 12, 31) and sem_base["horizonte"] == "Antes da posse"   # "antes da posse"
    assert not sem_base["prazo_de_fato"] and r["riscos"][0]["prazo_de_fato"]          # vencimento é fato; janela é opinião
    assert r["decisoes"] == []                                                     # sem opções: o relatório não sugere caminho
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
          "tipo": "Contrato", "origem": "Informado pelo órgão", "termos": "", "valor_texto": "R$ 9 mi"}
    funcoes.avaliar_riscos([ev], "04/11/2026")
    texto = funcoes.material("SEX", diag, funcoes.vencimentos_numerados([ev]), "DIVERGÊNCIAS: x", "04/11/2026")
    assert "[F1]" in texto and "[V1] vence 20/12/2026" in texto and "agir até 20/11/2026" in texto
    assert "DIVERGÊNCIAS: x" in texto and "SIGA" not in texto


# --- CHECKLIST OBRIGATÓRIO -----------------------------------------------------------------------

def test_checklist_da_o_estado_de_cada_ponto(funcoes, llm):
    rel, _ = funcoes.limpar_relatorio(RELATORIO)
    d = dossie_exemplo(funcoes)
    llm.checklist = {"respostas": [
        {"id": "C3", "resposta": "LOA de R$ 412 mi; empenhado R$ 398,75 mi.", "itens": ["O1"],
         "trechos": ["Empenhado até 23/10/2026: R$ 398.750.000,00"]},
        {"id": "C5", "resposta": "O TCE-RJ apontou atraso em convênios.", "itens": ["O4"]},
        {"id": "C6", "resposta": "Inventada, sem referência.", "itens": ["O999"], "trechos": ["frase que não existe"]},
        {"id": "C7", "resposta": "Não há convênios federais.", "trechos": ["Empenhado até 23/10/2026: R$ 398.750.000,00"],
         "nega": True}]}
    brutas = funcoes.responder("m", d, rel, "Secretaria de Exemplo")["respostas"]
    assert set(brutas) == {"C3", "C5", "C6", "C7"}
    cob = {c["id"]: c for c in funcoes.conferir(brutas, d, rel, [])}
    assert [c["id"] for c in funcoes.conferir(brutas, d, rel, [])] == [p[0] for p in funcoes.PERGUNTAS]
    assert cob["C3"]["estado"] == "encontrado" and cob["C3"]["fatos"] == ["O1"] and cob["C3"]["trechos"]
    assert cob["C3"]["firmeza"] == "confirmado em fonte oficial"      # a melhor entre as referências, como nos riscos
    assert cob["C5"]["estado"] == "encontrado" and cob["C5"]["firmeza"] == "confirmado em fonte oficial"
    assert cob["C7"]["estado"] == "procurado e não encontrado"            # o órgão informou que não há
    # referência inventada vale como nada; o bloco ter itens na pesquisa não prova que o ponto foi procurado
    assert cob["C6"]["estado"] == "não procurado" and not cob["C6"]["fatos"]
    # pessoal: a pesquisa registrou o que procurou e não achou (palavra-chave "terceirizados", no bloco certo)
    assert cob["C9"]["estado"] == "procurado e não encontrado" and "terceirizados" in cob["C9"]["resposta"]
    assert cob["C8"]["estado"] == "não procurado"
    # o registro pelo id vale em qualquer bloco; palavra solta fora do bloco não vale
    d_id = dict(d, nao_encontrado=[{"bloco": "outro_orgao", "procurado": "C8: obras paradas na secretaria"},
                                   {"bloco": "mandato_estrutura", "procurado": "aditivos de obras"}])
    cob_id = {c["id"]: c for c in funcoes.conferir({}, d_id, rel, [])}
    assert cob_id["C8"]["estado"] == "procurado e não encontrado" and "C8: obras" in cob_id["C8"]["resposta"]
    assert cob_id["C9"]["estado"] == "não procurado"
    d2 = dict(d, origem="arquivo", nao_encontrado=[])
    cob2 = {c["id"]: c for c in funcoes.conferir(brutas, d2, rel, [])}
    assert cob2["C6"]["estado"] == "não procurado" and cob2["C9"]["estado"] == "não procurado"
    assert cob2["C5"]["estado"] == "encontrado"
    r = funcoes.resumo(funcoes.conferir(brutas, d2, rel, []))
    assert r["não procurado"] >= 5 and "C6" in r["nao_procurados"]
    md = funcoes.markdown(funcoes.conferir(brutas, d2, rel, []))
    assert "SEM INFORMAÇÃO" in md and "procurar em: PGE e TJRJ" in md and "O4" in md
    assert "ficaram sem informação" in funcoes.linha_essencial(funcoes.conferir(brutas, d2, rel, []))


def test_confianca_cai_com_ponto_nao_procurado(funcoes):
    dossie_bom = {"itens": 10, "conferidos": 9, "nao_encontrado": 0}
    riscos = [{"firmeza": "confirmado em fonte oficial"}] * 3
    todos = [{"id": f"C{k}", "estado": "encontrado"} for k in range(1, 11)]
    assert funcoes.confianca(dossie_bom, riscos, todos)["nivel"] == "alta"
    um = todos[:9] + [{"id": "C10", "estado": "não procurado"}]
    c = funcoes.confianca(dossie_bom, riscos, um)
    assert c["nivel"] == "média" and "sem informação: C10" in c["motivos"][0]
    assert c["por_que"] == ["dos 10 temas básicos que toda secretaria precisa ter verificados, 1 ficaram sem informação (c10)"]
    assert c["lacuna_checklist"]
    alta = funcoes.confianca(dossie_bom, riscos, todos)
    assert alta["por_que"] == [] and not alta["lacuna_checklist"]
    muitos = todos[:4] + [{"id": f"C{k}", "estado": "não procurado"} for k in range(5, 11)]
    assert funcoes.confianca(dossie_bom, riscos, muitos)["nivel"] == "baixa"


def test_pesquisa_recebe_os_pontos_obrigatorios_do_checklist(funcoes, llm):
    funcoes.montar_dossie("m", "Secretaria de Exemplo", "04/11/2026")
    pedidos = [c["mensagens"][0]["content"] for c in llm.chamadas if "Monte a camada" in c["mensagens"][0]["content"]]
    do_orgao = [p for p in pedidos if 'camada\n"órgão"' in p]
    do_estado = [p for p in pedidos if 'camada\n"Estado"' in p]
    assert do_orgao and all("PONTOS OBRIGATÓRIOS" in p for p in do_orgao)
    assert not any("PONTOS OBRIGATÓRIOS" in p for p in do_estado)
    grupo_controle = next(p for p in do_orgao if "- controle_judicializacao:" in p)
    assert "C5:" in grupo_controle and "C6:" in grupo_controle and "C3:" not in grupo_controle


def test_esquema_de_modelos_por_familia(funcoes):
    opus, sonnet = "anthropic/claude-opus-5-5", "anthropic/claude-sonnet-5-5"
    gpt, gem, dsk = "openai/gpt-6-astra", "gemini/gemini-4-argon", "deepseek/deepseek-reasoner"
    # ordem dos papéis: fiscal, controle, servico, operacao, governo, contra
    # sem chave de fora: todos os agentes no principal e a neutralidade no auxiliar (ao menos outro modelo)
    e = funcoes.esquema_de_modelos(opus, sonnet, [], [])
    assert e["agentes"] == [opus] * 6 and e["neutralidade"] == sonnet and not e["independente"]
    # auxiliar igual ao principal (tudo no Opus): a neutralidade vai para outro modelo da casa, nunca para o autor
    e = funcoes.esquema_de_modelos(opus, opus, [], [])
    assert e["neutralidade"] == sonnet
    # uma família de fora: 3 a 3, com o advogado do diabo e o controle fora
    e = funcoes.esquema_de_modelos(opus, sonnet, [], ["gemini"])
    assert e["agentes"] == [opus, gem, gem, opus, opus, gem] and e["neutralidade"] == gem and e["independente"]
    # duas (sem OpenAI): a primeira na ordem de preferência leva os papéis adversariais; Anthropic fica com um
    e = funcoes.esquema_de_modelos(opus, sonnet, [], ["deepseek", "gemini"])
    assert e["agentes"] == [opus, gem, dsk, gem, dsk, gem] and e["neutralidade"] == gem
    # três: nenhuma família com mais de dois agentes
    e = funcoes.esquema_de_modelos(opus, sonnet, [], ["openai", "gemini", "deepseek"])
    assert e["agentes"] == [opus, gpt, gem, dsk, gem, gpt] and e["neutralidade"] == gpt
    assert max(e["agentes"].count(m) for m in set(e["agentes"])) == 2
    # lista informada à mão vale sobre o esquema
    e = funcoes.esquema_de_modelos(opus, sonnet, ["a", " b "], ["openai"])
    assert e["agentes"] == ["a", "b", "a", "b", "a", "b"]
    assert funcoes.familias_disponiveis({"OPENAI_API_KEY": "x", "GEMINI_API_KEY": " ", "DEEPSEEK_API_KEY": "y"}) == ["openai", "deepseek"]
    # o modelo da família pode ser trocado pelos Secrets (ex.: Flash na cota gratuita do Google)
    assert funcoes.modelo_da_familia("gemini", {"GEMINI_MODELO": " gemini/gemini-3.8-flash "}) == "gemini/gemini-3.8-flash"
    assert funcoes.modelo_da_familia("gemini", {}) == gem


def test_agentes_podem_usar_modelos_diferentes(funcoes, llm):
    modelos = ["anthropic/claude-opus-5-5", "gemini/gemini-4-argon"] * 3
    revisoes = funcoes.revisar_por_agentes("a", "MATERIAL", {"riscos": []}, [], modelos)
    assert [r["modelo"] for r in revisoes] == modelos and all(not r.get("erro") for r in revisoes)
    assert [r["papel"] for r in revisoes][-1] == "Advogado do diabo" and revisoes[-1]["contestados"]
    chamadas = [c for c in llm.chamadas if "Você revisa a análise de riscos" in str(c["mensagens"])
                or "ADVOGADO DO DIABO" in str(c["mensagens"])]
    # na Anthropic, o material vem primeiro e em cache, e as instruções de cada agente depois
    anthropic = [c for c in chamadas if c["modelo"].startswith("anthropic/")]
    assert all(c["mensagens"][1]["content"][0].get("cache_control") for c in anthropic)
    assert all("<instrucoes>" in c["mensagens"][1]["content"][1]["text"] for c in anthropic)
    assert sorted(c["modelo"] for c in chamadas) == sorted(modelos)
    md = funcoes.markdown_metodo("x", {}, None, {"nivel": "alta", "motivos": []}, [], None, revisoes, {"riscos": []})
    assert "gemini/gemini-4-argon" in md and "provedores diferentes" in md


def test_proveniencia_de_cada_risco_por_codigo(funcoes):
    analise = {"riscos": [{"id": "R1"}, {"id": "R2"}]}
    revisoes = [{"papel": "Fazenda e orçamento", "exagerados": [{"risco": "R2", "motivo": "valor pequeno"}]},
                {"papel": "Área-fim e usuário do serviço", "exagerados": []},
                {"papel": "Operação e servidores", "erro": "fora do ar"},
                {"papel": "Advogado do diabo", "contestados": [{"risco": "R2", "motivo": "já resolvido", "fatos": ["F4"]}],
                 "sustentados": ["R1"]}]
    finais = [{"id": "R1", "id_anterior": "R2"}, {"id": "R2", "id_anterior": "R1"},
              {"id": "R3", "id_anterior": "novo: Área-fim e usuário do serviço"}, {"id": "R4", "id_anterior": "R9"}]
    funcoes.proveniencia(finais, revisoes, analise)
    r = {f["id"]: f["revisao"] for f in finais}
    assert r["R1"]["agentes"] == 3 and r["R1"]["sem_objecao"] == 1 and r["R1"]["contestado"]
    assert [(o["papel"], o["tipo"]) for o in r["R1"]["objecoes"]] == [("Fazenda e orçamento", "exagerado"),
                                                                       ("Advogado do diabo", "contestado")]
    assert r["R2"] == {"origem": "análise", "objecoes": [], "agentes": 3, "sem_objecao": 3, "contestado": False}
    assert r["R3"]["origem"] == "apontado por Área-fim e usuário do serviço" and r["R3"]["sem_objecao"] == 3
    assert r["R4"]["origem"] == "análise" and r["R4"]["objecoes"] == []          # id_anterior desconhecido: só a contagem
    linha = funcoes._linha_revisao(r["R1"])
    assert linha == ("**Revisão:** 1 de 3 agentes sem objeção (1 vê exagero); Advogado do diabo contesta: já resolvido (F4) "
                     "→ consolidação: sem resposta registrada.")
    completo = funcoes.markdown_objecoes({"riscos": [{"id": "R1", "titulo": "T", "revisao": r["R1"]}]})
    assert "- Fazenda e orçamento vê exagero: valor pequeno → consolidação: sem resposta registrada" in completo
    # com a resposta da consolidação, ela aparece; sem id_anterior, o casamento é pelo título
    consolidado = {"respostas_as_revisoes": [{"agente": "Advogado do diabo", "risco": "R2", "decisao": "não acatado",
                                               "motivo": "o aditivo não foi publicado"}]}
    analise2 = {"riscos": [{"id": "R1", "titulo": "Licitações adiadas travam obras"}, {"id": "R2", "titulo": "Frota vence em dezembro"}]}
    finais2 = [{"id": "R1", "titulo": "Frota vence em dezembro sem aditivo"}, {"id": "R2", "titulo": "Convênios da Caixa pendentes"}]
    revisoes2 = revisoes + [{"papel": "Nova gestão: prioridades e articulação",
                             "faltando": [{"titulo": "Convênios da Caixa com pendências"}]}]
    funcoes.proveniencia(finais2, revisoes2, analise2, consolidado)
    assert finais2[0]["revisao"]["objecoes"][-1]["resposta"] == "não acatado (o aditivo não foi publicado)"
    assert finais2[1]["revisao"]["origem"] == "apontado por Nova gestão: prioridades e articulação"


def test_agente_de_outra_familia_que_falha_roda_no_principal(funcoes, llm):
    llm.modelos_que_falham = {"gemini/gemini-3.8-flash"}
    modelos = ["anthropic/claude-opus-5-5", "gemini/gemini-3.8-flash"] * 3
    revisoes = funcoes.revisar_por_agentes("anthropic/claude-opus-5-5", "MATERIAL", {"riscos": []}, [], modelos)
    assert all(not r.get("erro") for r in revisoes)                      # nenhum olhar se perde
    trocados = [r for r in revisoes if r.get("substituto")]
    assert len(trocados) == 3 and all(r["modelo"] == "anthropic/claude-opus-5-5" for r in trocados)
    assert all(r["modelo_previsto"] == "gemini/gemini-3.8-flash" and "fora do ar" in r["erro_do_previsto"] for r in trocados)
    nota = funcoes.nota_final("x", {"auxiliar": "a", "debate": "b"}, {"nivel": "média", "motivos": []}, "04/11/2026",
                              None, revisoes)
    assert "6 agentes de IA" in nota and "todos no mesmo modelo" in nota
    assert "3 rodaram no modelo principal porque o previsto falhou (Controle e jurídico" in nota
    # se o principal também falha, o agente fica sem resposta, como antes
    llm.modelos_que_falham = {"gemini/gemini-3.8-flash", "anthropic/claude-opus-5-5"}
    revisoes = funcoes.revisar_por_agentes("anthropic/claude-opus-5-5", "MATERIAL", {"riscos": []}, [], modelos)
    assert all(r.get("erro") for r in revisoes) and "substituto:" in revisoes[1]["erro"]


def test_dossies_embutidos_sao_lidos_e_o_enviado_vale_sobre_eles(funcoes, tmp_path, monkeypatch):
    import zipfile, io
    pacote = io.BytesIO()
    with zipfile.ZipFile(pacote, "w") as z:
        z.writestr("dossies/00_CONSOLIDACAO_ESTADUAL.md", "| Sigla | Secretaria |\n|---|---|\n| SETUR | Secretaria de Turismo |\n| SEFAZ | Secretaria de Fazenda |\n")
        z.writestr("dossies/SETUR.md", "# Dossiê reduzido SETUR (painel do SIGA): ignorado\n- fato")
        z.writestr("pesquisa/SETUR_pesquisa.md", "# Pesquisa SETUR\n- fato")
        z.writestr("pesquisa/SEFAZ_pesquisa.md", "# Pesquisa SEFAZ\n- fato")
        z.writestr("dossies_automaticos/dados_vencimentos/SETUR_vencimentos_180d.csv", "contratacao;fim\n1;01/12/2026\n")
        z.writestr("referencia/REVISAO.md", "ignorar")
    (tmp_path / "Transicao_RJ_dossies_06-11-2026.zip").write_bytes(pacote.getvalue())
    (tmp_path / "LEIA-ME.md").write_text("como atualizar", encoding="utf-8")
    dossies, data = funcoes.dossies_embutidos(tmp_path)
    assert data == "06/11/2026" and [d["orgao"] for d in dossies] == ["Secretaria de Fazenda - SEFAZ", "Secretaria de Turismo - SETUR"]
    assert all(d["embutido"] for d in dossies) and next(d for d in dossies if "SETUR" in d["orgao"])["partes"].keys() == {"pesquisa"}
    # pasta vazia ou inexistente: nada
    assert funcoes.dossies_embutidos(tmp_path / "nada") == ([], "")
    # a variável PASTA_DOSSIES aponta para outra pasta
    monkeypatch.setenv("PASTA_DOSSIES", str(tmp_path))
    assert len(funcoes.dossies_embutidos()[0]) == 2
    # o enviado vale sobre o embutido da mesma secretaria; as demais continuam
    enviado = funcoes.dossies_do_envio([("SETUR_pesquisa.md", b"# Dossie novo SETUR")])
    juntos = {d["orgao"]: d for d in funcoes.juntar_dossies(dossies, enviado)}
    assert set(juntos) == {"Secretaria de Fazenda - SEFAZ", "Secretaria de Turismo - SETUR"}   # casa pela sigla
    assert not juntos["Secretaria de Turismo - SETUR"].get("embutido") and juntos["Secretaria de Fazenda - SEFAZ"]["embutido"]
    assert b"novo" in juntos["Secretaria de Turismo - SETUR"]["partes"]["pesquisa"]


def test_pacote_embutido_no_repositorio_cobre_as_31_secretarias(funcoes):
    dossies, data = funcoes.dossies_embutidos()
    assert data == "06/11/2026" and len(dossies) >= 31
    secid = next(d for d in dossies if d["orgao"].endswith("- SECID"))
    assert set(secid["partes"]) == {"pesquisa"}                 # sem a planilha do SIGA nem o painel do SIGA/PNCP
    textos = funcoes._texto_dossie(secid)
    assert "SIGA" not in textos["pesquisa"][:2000] and "contratacao;" not in textos["pesquisa"]


def test_folha_do_caderno_de_rh_entra_como_dado_oficial(funcoes, tmp_path_factory):
    # bases embutidas do repositório (Cadernos de RH de março e de setembro de 2026): vale o mais recente
    secid = funcoes.itens("SECID")
    assert len(secid) == 2 and all(i["bloco"] == "pessoal" and i["tipo_fonte"] == "dado_oficial" for i in secid)
    assert "Em setembro de 2026, SECID tinha 113 vínculos ativos" in secid[0]["afirmacao"]
    assert "R$ 0,92 milhões" in secid[0]["afirmacao"] and secid[0]["fonte"].endswith("setembro de 2026")
    assert "nenhum dos 113 vínculos ativos é de servidor efetivo" in secid[1]["afirmacao"]
    sefaz = funcoes.itens("SEFAZ")[1]["afirmacao"]
    assert "1.002 são de servidores efetivos" in sefaz and "497 (33,2%)" in sefaz
    assert funcoes.quadro("SEAPA")["efetivos"] == "155"                      # SEAPA no dossiê, SEAPPA no Caderno
    # vale o nome mais atualizado: quem saiu na reforma de 2026 e tem sucessora usa a sucessora, e o texto diz
    seap = funcoes.itens("SEAP")
    assert seap[0]["tipo_fonte"] == "documento_oficial" and "PLOA" in seap[0]["fonte"]     # confirmada na PLOA 2027
    assert "SEAP passou a se chamar Secretaria de Estado de Polícia Penal" in seap[0]["afirmacao"]
    assert "a unidade 25010 é a Secretaria de Estado de Polícia Penal" in seap[0]["afirmacao"]
    secti = funcoes.itens("SECTI")
    assert secti[0]["tipo_fonte"] == "imprensa" and secti[0]["url"].startswith("https://www.correiodamanha")
    assert "Em setembro de 2026, SEPPENRJ tinha 5.857 vínculos ativos" in seap[1]["afirmacao"]
    assert seap[1]["tipo_fonte"] == "dado_oficial"
    md_seap = funcoes.markdown_capitulos({"secoes": []}, None, None, funcoes.quadro("SEAP"))
    assert "| 5.857 |" in md_seap and "os números são de toda a SEPPENRJ" in md_seap
    assert funcoes.quadro("SECTI")["sigla"] == funcoes.quadro("SEENEMAR")["sigla"] == "SEDES"
    assert "1 é de servidor efetivo/concursado" in funcoes.itens("SEIJES")[2]["afirmacao"]
    assert funcoes.quadro("SEM")["sigla"] == "SEMPI"
    # sem sucessora conhecida: fica com o último Caderno em que aparece, e o texto diz
    import csv
    pasta = tmp_path_factory.mktemp("bases")
    for comp, linhas in (("2026-03", [("SEX", "10")]), ("2026-09", [("SEY", "20")])):
        with open(pasta / f"folha_rh_{comp}.csv", "w", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow(["competencia", "url", "sigla", "administracao", "vinculos_ativos", "dispendio_mes_mi",
                        "remuneracao_media", "efetivos", "efetivos_na_tabela_8", "idade_media_efetivos",
                        "tempo_exercicio_medio_efetivos", "nao_efetivos", "pct_nao_efetivos"])
            for s, v in linhas:
                w.writerow([comp, "https://x", s, "direta", v, "1", "1000", "0", "não", "", "", v, "100.0"])
    sex = funcoes.itens("SEX", pasta)
    assert "Em março de 2026, SEX tinha 10 vínculos ativos" in sex[0]["afirmacao"]
    assert "não aparece no Caderno de RH de setembro de 2026, o mais recente" in sex[-1]["afirmacao"]
    md_sex = funcoes.markdown_capitulos({"secoes": []}, None, None, funcoes.quadro("SEX", pasta))
    assert "Caderno de RH, SEPLAG, março de 2026" in md_sex and "os números são os de março de 2026" in md_sex
    assert funcoes.itens("NAOEXISTE") == [] and funcoes.quadro("") is None
    q = funcoes.quadro("SECID")
    md = funcoes.markdown_capitulos({"secoes": []}, None, None, q)
    assert "| 113 | 0 | 113 (100,0%) | R$ 0,92 mi | R$ 8.113,29 |" in md and "pode sair na troca de governo" in md
    assert "o mais recente" not in md
    assert md.index("## b) Cargos e força de trabalho") < md.index("**Folha de pessoal**") < md.index("## c) Contratos")
    # no dossiê: id novo, conferido, firmeza de fonte oficial; o checklist C9 sai por código
    d = {"itens": [], "origem": "arquivo", "nao_encontrado": []}
    funcoes.acrescentar_itens(d, secid)
    assert [i["id"] for i in d["itens"]] == ["O1", "O2"] and d["itens"][0]["checagem"] == "conferido"
    c9 = next(c for c in funcoes.conferir({}, d, "", []) if c["id"] == "C9")
    assert c9["estado"] == "encontrado" and c9["fatos"] == ["O1", "O2"] and c9["firmeza"] == "confirmado em fonte oficial"


def test_painel_mostra_servicos_essenciais_que_podem_parar(funcoes):
    from datetime import date
    base = {"origem": "Informado pelo órgão", "tipo": "Contrato", "dias": 30, "valor_texto": "", "evento": "Fim do contrato"}
    eventos = [dict(base, orgao="Secretaria de Saúde - SES", essencial=True, data=date(2026, 12, 20),
                    agir_ate=date(2026, 11, 20), valor=2_000_000.0, prioridade="Máxima", contratacao="2026000001",
                    objeto="Aquisição de medicamentos", fornecedor="FARMA LTDA"),
               dict(base, orgao="Secretaria de Saúde - SES", essencial=True, data=date(2027, 3, 1),
                    agir_ate=date(2027, 1, 30), valor=1_000_000.0, prioridade="Alta", contratacao="2026000002",
                    objeto="Alimentação hospitalar", fornecedor="NUTRI"),
               dict(base, orgao="Secretaria de Saúde - SES", essencial=True, data=date(2027, 5, 1),     # depois dos 100 dias
                    agir_ate=date(2027, 4, 1), valor=9_000_000.0, prioridade="Alta", objeto="Oxigênio"),
               dict(base, orgao="Secretaria de Turismo - SETUR", essencial=False, data=date(2026, 12, 1),  # não essencial
                    agir_ate=date(2026, 11, 1), valor=5_000_000.0, prioridade="Alta", objeto="Eventos")]
    md = "\n".join(funcoes.markdown_apagao(eventos))
    assert md.startswith("## Serviços essenciais que podem parar até 10/04/2027")
    assert "2 contrato(s) de serviço essencial" in md and "SETUR" not in md and "Oxigênio" not in md
    assert "| SES | 1 (R$ 2,0 mi) | – | 1 (R$ 1,0 mi) | 2 (R$ 3,0 mi) |" in md
    assert "**Prioridade máxima (1)**" in md and "| 20/11/2026 | SES | 2026000001: Aquisição de medicamentos | FARMA LTDA |" in md
    assert funcoes.markdown_apagao([]) == []


def test_quadro_antes_de_ler_diz_o_que_e_a_confianca_e_os_cortes(funcoes):
    conf = funcoes.confianca({"itens": 10, "conferidos": 9}, [{"firmeza": "confirmado em fonte oficial"}] * 3,
                             [{"id": "C3", "tema": "Execução orçamentária", "estado": "não procurado"},
                              {"id": "C5", "tema": "TCE-RJ", "estado": "não procurado"}]
                             + [{"id": f"C{k}", "tema": "x", "estado": "encontrado"} for k in (1, 2)])
    assert conf["nivel"] == "média" and "execução orçamentária, tce-rj" in conf["por_que"][0]
    cortes = funcoes.cortes_de_leitura(
        {"cortados": [{"arquivo": "Controle_SECID.xlsx", "caracteres": 93411, "usados": 60000}]},
        ["⚠️ O relatório tem 500.000 caracteres e passou do limite de 400.000: o final (cerca de 20%) foi cortado e não "
         "entra na análise.", "3 endereço(s) de e-mail foram omitidos."])
    assert funcoes._tamanho(12337906) == "12,3 milhões" and funcoes._tamanho(331632) == "332 mil"
    assert cortes == ["Controle_SECID.xlsx (lidos 60 mil de 93 mil caracteres)",
                      "O relatório tem 500.000 caracteres e passou do limite de 400.000: o final (cerca de 20%) foi cortado"]
    md = funcoes.antes_de_ler(conf, "04/11/2026", cortes)
    assert md.startswith("## Antes de ler\n- **O que é:**") and "data de corte 04/11/2026" in md
    assert "**Confiança desta análise: MÉDIA**, porque dos 4 temas básicos" in md
    assert "Silêncio do documento sobre esses temas não quer dizer que não haja risco." in md
    assert "Confirme os pontos marcados" in md and md.count("**Material cortado:**") == 2
    assert "só o que a secretaria informou" in md and md.rstrip().endswith("confira antes de usar.")
    baixa = funcoes.confianca(None, [], None)
    assert "não houve dossiê" in funcoes.antes_de_ler(baixa, "", []) and "não para afirmar" in funcoes.antes_de_ler(baixa, "", [])


def test_encurtar_nao_corta_frase_no_meio(funcoes):
    from transicao import documentos
    texto = "Firewall termina em 18/11/2026 (V3, V14). Seguro vence em 06/12/2026 (F6). Telefonia em 31/12/2026."
    assert documentos._curto(texto, 60) == "Firewall termina em 18/11/2026 (V3, V14)"
    assert documentos._curto(texto, 90) == "Firewall termina em 18/11/2026 (V3, V14). Seguro vence em 06/12/2026 (F6)"
    longa = "Uma frase só, bem longa, com referências no fim que não podem sumir (F1, F2, F3, F4, F5)."
    assert documentos._curto(longa, 30) == longa.rstrip(".")                 # a primeira frase fica inteira
    assert "…" not in documentos._curto(texto, 20)


def test_revisao_do_texto_reescreve_no_tom_de_analise_com_travas(funcoes, llm):
    from transicao import revisao
    resultado = {"situacao": ["A secretaria deve renovar 3 contratos (F1)."],
                 "riscos": [{"id": "R1", "titulo": "Viaturas", "causa": "Sete contratos de R$ 55,2 mi terminam (V1).",
                             "consequencia": "Dívida (F2).", "decisao": "Aditivar ou encerrar? Cabe ao secretário.",
                             "motivo_sensibilidade": "", "em_curso": ""}],
                 "pedir": [{"o_que": "É preciso pedir a execução por ação.", "serve_a": "R1"}]}
    assert revisao.alertas(resultado["situacao"][0]) == ['recomendação: "deve"']
    llm.revisao_texto = {"textos": {
        "situacao.0": "A secretaria tem 3 contratos a renovar (F1).",                 # aceita: mesmos números e refs
        "R1.decisao": "Destino dos sete contratos de viaturas.",                        # aceita
        "R1.causa": "Sete contratos de R$ 60 mi terminam (V1).",                        # recusada: mudou o valor
        "pedido.9": "campo que não existe",                                             # ignorada
        "pedir.0": "Recomenda-se a execução por ação."}}                                # recusada: recomendação
    reg = revisao.revisar_texto("anthropic/claude-opus-5-5", resultado, [], pistas=[])
    assert resultado["situacao"][0] == "A secretaria tem 3 contratos a renovar (F1)."
    assert resultado["riscos"][0]["decisao"] == "Destino dos sete contratos de viaturas."
    assert resultado["riscos"][0]["causa"].startswith("Sete contratos de R$ 55,2 mi")
    motivos = {r["campo"]: r["motivo"] for r in reg["recusados"]}
    assert motivos == {"R1.causa": "mudou número, data ou referência", "pedir.0": "manteve palavra de recomendação"}
    assert set(reg["alertas_depois"]) == {"pedir.0"}                              # o que sobrou fica registrado
    # sem resposta legível do modelo, o texto fica como estava
    llm.revisao_texto = None
    antes = dict(resultado["riscos"][0])
    revisao.revisar_texto("anthropic/claude-opus-5-5", resultado, [], pistas=[])
    assert resultado["riscos"][0] == antes


def test_organograma_em_arvore(funcoes):
    from transicao import documentos
    u = lambda nome, pai="", **k: dict({"unidade": nome, "sigla": "", "subordinada_a": pai, "titular": "",
                                         "vinculada": False, "rotulo": "informado pelo órgão"}, **k)
    unidades = [u("Gabinete do Secretário", titular="Ana Lima (Secretária)"), u("Subsecretaria A", "Gabinete do Secretário"),
                u("Superintendência A1", "Subsecretaria A"), u("Subsecretaria B", "Gabinete do Secretário", titular="vago"),
                u("Fundação X", vinculada=True, sigla="FX")]
    md = documentos.organograma_em_arvore(unidades, "Secretaria de Exemplo")
    assert md.splitlines() == ["```", "Secretaria de Exemplo",
                               "├── Gabinete do Secretário — Ana Lima (Secretária)",
                               "│   ├── Subsecretaria A",
                               "│   │   └── Superintendência A1",
                               "│   └── Subsecretaria B — vago",
                               "└── Vinculadas",
                               "    └── Fundação X (FX)", "```"]
    # sem vinculadas e com um topo só, a árvore começa nele
    md = documentos.organograma_em_arvore(unidades[:3])
    assert md.splitlines()[1] == "Gabinete do Secretário — Ana Lima (Secretária)"
    # no Word, o bloco sai em fonte fixa, uma linha por parágrafo
    import io
    import docx
    doc = docx.Document(io.BytesIO(documentos.gerar_docx("## 2. Como se organiza\n" + md, {"assunto": "x"})))
    fixos = [p for p in doc.paragraphs if p.runs and p.runs[0].font.name == "Consolas"]
    assert [p.text for p in fixos][:2] == ["Gabinete do Secretário — Ana Lima (Secretária)", "└── Subsecretaria A"]


def test_dossie_so_com_o_que_a_secretaria_informou_e_fonte_oficial(funcoes):
    from transicao import documentos
    it = lambda t, r, o="": {"id": "F1", "texto": t, "rotulo": r, "url": "", "origem_item": o}
    diag = {"secoes": [{"titulo": "Programas e ações", "itens": [
                it("Programa A atende 92 municípios.", "informado pelo órgão"),
                it("Decreto fixa a meta de 10 mil casas.", "confirmado em fonte oficial", "O1"),
                it("Jornal diz que o programa atrasou.", "fonte pública conferida"),
                it("Blog diz outra coisa.", "fonte pública não conferida")], "leitura": "x", "nao_se_sabe": []},
                       {"titulo": "Pendências com controle e justiça", "itens": [
                it("A secretaria informa uma determinação do TCE-RJ.", "informado pelo órgão"),
                it("O TCE-RJ abriu inquérito sobre obras.", "fonte pública conferida", "O2"),
                it("Site diz que há outra apuração.", "fonte pública não conferida")], "leitura": "", "nao_se_sabe": ["Prazo da determinação"]}],
            "indicadores": [{"nome": "LOA", "valor": "R$ 1 bi", "rotulo": "confirmado em fonte oficial"},
                            {"nome": "Segundo a imprensa", "valor": "R$ 9 bi", "rotulo": "fonte pública conferida"}],
            "organograma": [{"unidade": "Gabinete", "sigla": "", "subordinada_a": "", "titular": "", "rotulo": "informado pelo órgão"},
                            {"unidade": "Unidade da notícia", "sigla": "", "subordinada_a": "Gabinete", "titular": "",
                             "rotulo": "fonte pública conferida"}]}
    dossie = {"itens": [{"id": "O1", "fonte": "Decreto 50.003", "data_fonte": "19/11/2025", "url": "https://rj.gov.br/d",
                         "tipo_fonte": "documento_oficial", "checagem": "conferido"},
                        {"id": "O2", "fonte": "G1", "data_fonte": "06/02/2026", "url": "https://g1.globo.com/a",
                         "tipo_fonte": "imprensa", "checagem": "conferido"}]}
    md = documentos.markdown_capitulos(diag, dossie=dossie)
    # o que a secretaria informou vem sem marca; a fonte oficial vem com a marca e a fonte por extenso
    assert "- Programa A atende 92 municípios.\n" in md and "(informado pelo órgão)" not in md
    assert "- Decreto fixa a meta de 10 mil casas. _(fonte oficial ✔: [Decreto 50.003, 19/11/2025](https://rj.gov.br/d))_" in md
    assert "Jornal" not in md and "Blog" not in md
    assert "_2 outros fatos deste tema vêm de imprensa ou de fonte não oficial e ficam no relatório de riscos e na auditoria._" in md
    # só no capítulo de pendências a notícia conferida entra, com a marca de imprensa; a não conferida fica de fora
    assert "- O TCE-RJ abriu inquérito sobre obras. _(imprensa ✔: [G1, 06/02/2026](https://g1.globo.com/a))_" in md
    assert "Site diz" not in md
    assert "_1 outro fato deste tema vem de fonte que não pôde ser conferida e fica no relatório de riscos e na auditoria._" in md
    assert "\n\n_Não se sabe:_ Prazo da determinação.\n\n_1 outro fato" in md          # em parágrafos separados, com ponto
    assert "(s)" not in md
    assert "Unidade da notícia" not in md and "Gabinete" in md
    ficha = documentos.ficha_rapida(diag)
    assert "| LOA | R$ 1 bi |" in ficha and "Segundo a imprensa" not in ficha and "| Estrutura | 1 unidade no organograma |" in ficha
    # o anexo de fontes só traz o que o corpo usa, sem códigos
    fontes = documentos.fontes_do_dossie(diag, dossie)
    assert "- [Decreto 50.003, 19/11/2025](https://rj.gov.br/d) · ✔ conferido na fonte" in fontes
    assert "- [G1, 06/02/2026](https://g1.globo.com/a) · ✔ conferido na fonte" in fontes
    assert "O1" not in fontes and "O2" not in fontes and "os ids" not in fontes
    assert len(diag["secoes"][0]["itens"]) == 4                     # o diagnóstico (que vai aos riscos) segue inteiro
