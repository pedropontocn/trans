"""O formato executivo do relatório de riscos e do dossiê (vão ao governador eleito): o resumo da primeira página, as
travas por código no texto da IA, o agrupamento por tema e o desenho no Word."""
import io
import re
from datetime import date

from test_analise import CFG, RELATORIO


def _risco(rid, titulo, categoria, data=None, vencido=False, horizonte="Antes da posse", nota=6, prioridade="Alta", **extra):
    base = {"id": rid, "titulo": titulo, "categoria": categoria, "o_que_e": f"Contrato de {titulo.lower()}",
            "valor": "R$ 3,68 mi, valor do contrato", "situacao_atual": "Prorrogação em andamento",
            "consequencia": "O serviço pode ficar sem contrato", "motivo_sensibilidade": "Pode gerar reação da imprensa",
            "impacto": "Alto", "sensibilidade": "Média", "fatos": [], "firmeza": "informado pelo órgão", "nota": nota,
            "prioridade": prioridade, "prazo_de_fato": bool(data), "data_evento": data, "agir_ate": data,
            "horizonte": horizonte, "vencido": vencido, "revisao": {"objecoes": []}}
    return dict(base, **extra)


RESULTADO = {"riscos": [
    _risco("R1", "Firewall da rede", "Continuidade de serviço", date(2026, 11, 18)),
    _risco("R2", "Limpeza do IML", "Continuidade de serviço", date(2026, 10, 31), vencido=True, prioridade="Máxima"),
    _risco("R3", "Nova sede", "Obras e projetos", None, horizonte="Primeiras 72 horas", valor="R$ 99,35 mi, avaliação"),
    _risco("R4", "Sentença do ICCE", "Jurídico e controle", date(2026, 11, 9), vencido=True)],
    "pedir": [{"o_que": "Aditivo da limpeza", "para_que": "Diz se há cobertura.", "onde": "SEI", "serve_a": "R2",
               "apontado_por": ["Análise"]},
              {"o_que": "Situação de 1 processo do TCE-RJ", "para_que": "Diz se há determinação.", "onde": "TCE-RJ",
               "serve_a": "", "apontado_por": ["Cruzamento com o TCE-RJ"]}]}


# --- AGRUPAMENTO E QUADRO -----------------------------------------------------------------------------------------

def test_relatorio_agrupa_por_tema_com_o_mais_urgente_primeiro(funcoes):
    grupos = funcoes.riscos_por_tema(RESULTADO, date(2026, 11, 10))
    assert [(k, t) for k, t, _ in grupos] == [(1, "Continuidade de serviço"), (2, "Jurídico e controle"), (3, "Obras e projetos")]
    assert [x["num"] + " " + x["r"]["titulo"] for x in grupos[0][2]] == ["1.1 Limpeza do IML", "1.2 Firewall da rede"]
    md = funcoes.relatorio_riscos(RESULTADO, None, "_nota_", data_corte="10/11/2026")
    primeira, corpo = md.split("<<<QUEBRA>>>")
    assert primeira.startswith("## Resumo executivo\n4 pontos de atenção em 3 temas. Prazo vencido: Limpeza do IML; "
                               "Sentença do ICCE. Antes da posse: Firewall da rede.")       # sem IA: por código
    assert "| § 1. Continuidade de serviço |\n| 1.1 | **Limpeza do IML**<br>O serviço pode ficar sem contrato. | " \
           "R$ 3,68 mi | 31/10/2026<br>Prazo vencido | Máxima<br>impacto alto |" in primeira
    assert "| 3.1 | **Nova sede**" in primeira and "| R$ 99,35 mi | Sem data<br>Primeiras 72 h |" in primeira
    assert [l for l in corpo.split("\n") if l.startswith("## ")][:3] == [
        "## 1. Continuidade de serviço", "## 2. Jurídico e controle", "## 3. Obras e projetos"]
    assert ("- **O que é:** Contrato de limpeza do iml. Valor: R$ 3,68 mi, valor do contrato.\n"
            "- **Status:** Prorrogação em andamento.\n- **Consequência:** O serviço pode ficar sem contrato.") in corpo
    # as informações que faltam vão para o grupo do tema do ponto, com o número do ponto; o TCE tem grupo próprio
    falta = corpo.split("## Informações que faltam")[1]
    assert "| § 1. Continuidade de serviço |\n| Aditivo da limpeza | Diz se há cobertura. | 1.1 |" in falta
    assert "| § Controle externo (TCE-RJ) |\n| Situação de 1 processo do TCE-RJ | Diz se há determinação. | – |" in falta
    assert md.rstrip().endswith("_nota_")


def test_resumo_da_ia_entra_no_quadro_e_nos_temas(funcoes):
    resumo = {"abertura": "Quatro pontos; dois já vencidos.", "temas": {"Continuidade de serviço": "Contratos de apoio."},
              "em_jogo": {"R2": "Venceu sem aditivo comprovado."}}
    md = funcoes.relatorio_riscos(RESULTADO, None, "", data_corte="10/11/2026", resumo=resumo)
    assert md.startswith("## Resumo executivo\nQuatro pontos; dois já vencidos.\n")
    assert "**Limpeza do IML**<br>Venceu sem aditivo comprovado. |" in md
    assert "**Firewall da rede**<br>O serviço pode ficar sem contrato. |" in md                 # sem frase: a consequência
    assert "## 1. Continuidade de serviço\n_Contratos de apoio._\n" in md


# --- TRAVAS NO TEXTO DA IA ----------------------------------------------------------------------------------------

def test_resumo_dos_riscos_trava_numero_recomendacao_e_codigo(llm, funcoes):
    from transicao import executivo
    lista = funcoes.riscos_para_o_resumo(RESULTADO, "10/11/2026")
    assert [r["id"] for r in lista] == ["R2", "R1", "R4", "R3"] and lista[0]["janela"] == "Prazo vencido"
    llm.resumo_riscos = {"abertura": "4 pontos de atenção em 3 temas; a nova sede envolve R$ 99,35 mi.", "fatos": ["R3"],
                         "temas": [{"tema": "Continuidade de serviço", "texto": "2 contratos que vencem perto da posse."},
                                   {"tema": "Obras e projetos", "texto": "Deve-se decidir a sede."},          # recomendação
                                   {"tema": "Tema que não existe", "texto": "x"}],
                         "em_jogo": [{"risco": "R1", "texto": "Prorrogação em andamento; pode faltar contrato."},
                                     {"risco": "R2", "texto": "Venceu e custa R$ 7 mi."},                    # número novo
                                     {"risco": "R4", "texto": "Ver F3 para detalhes."}]}               # código no texto
    uso = []
    r = executivo.resumir_riscos("m", "SEPOL", lista, uso)
    assert r["abertura"] == "4 pontos de atenção em 3 temas; a nova sede envolve R$ 99,35 mi." and not r["por_codigo"]
    assert r["temas"] == {"Continuidade de serviço": "2 contratos que vencem perto da posse."}
    assert r["em_jogo"] == {"R1": "Prorrogação em andamento; pode faltar contrato."}
    motivos = {x["item"]: x["motivo"] for x in r["recusados"]}
    assert motivos["tema Obras e projetos"].startswith("recomendação") and motivos["em jogo R2"].endswith(": 7")
    assert motivos["em jogo R4"] == "traz código de fato no texto"
    assert uso and uso[0]["etapa"] == "relatório de riscos: resumo executivo"
    assert "texto_conferido" not in str(llm.pedido_resumo_riscos)                    # o modelo não recebe o campo interno
    # abertura com número fora dos riscos citados: sai a abertura por código, e o motivo fica registrado
    llm.resumo_riscos = {"abertura": "A nova sede custa R$ 120 mi.", "fatos": ["R3"], "temas": [], "em_jogo": []}
    r = executivo.resumir_riscos("m", "SEPOL", lista, [])
    assert r["por_codigo"] and r["abertura"].startswith("4 pontos de atenção em 3 temas. Prazo vencido:")
    assert r["recusados"][0] == {"item": "abertura", "texto": "A nova sede custa R$ 120 mi.",
                                 "motivo": "número que não está nos fatos citados: 120"}
    # sem resposta legível: tudo por código, sem erro
    llm.resumo_riscos = "não é um objeto"
    assert executivo.resumir_riscos("m", "SEPOL", lista, [])["por_codigo"]
    assert executivo.resumir_riscos("m", "SEPOL", [], [])["abertura"] == ""


def test_resumo_do_dossie_trava_destaques(llm):
    from transicao import executivo
    fatos = [{"id": "B1", "origem": "Caderno de RH", "texto": "Caderno de RH: 9.763 vínculos ativos; folha de R$ 156,47 mi."},
             {"id": "F3", "origem": "item c", "texto": "O contrato de combustível de R$ 29.104.442,28 vai até 24/04/2027."},
             {"id": "F7", "origem": "item f", "texto": "A construção do complexo de perícia está paralisada por falta de terreno."}]
    llm.resumo_dossie = {"abertura": "A SEPOL tem 9.763 vínculos ativos e folha de R$ 156,47 mi.", "fatos": ["B1"],
                         "destaques": [{"rotulo": "Combustível", "texto": "Contrato de R$ 29,10 mi até 24/04/2027.", "fatos": ["F3"]},
                                       {"rotulo": "Obras", "texto": "Complexo de perícia parado por falta de terreno.", "fatos": ["F7"]},
                                       {"rotulo": "obras", "texto": "Outra frase.", "fatos": ["F7"]},           # repetido
                                       {"rotulo": "Pessoal", "texto": "São 12 mil servidores.", "fatos": ["B1"]},  # número novo
                                       {"rotulo": "Governança", "texto": "Cabe à secretaria rever o status.", "fatos": ["F7"]},
                                       {"rotulo": "Sem fato", "texto": "Algo.", "fatos": ["X1"]}]}
    r = executivo.resumir_dossie("m", "SEPOL", fatos, [], "abertura por código")
    assert r["abertura"] == "A SEPOL tem 9.763 vínculos ativos e folha de R$ 156,47 mi." and not r["por_codigo"]
    assert [d["rotulo"] for d in r["destaques"]] == ["Combustível", "Obras"]
    motivos = [x["motivo"] for x in r["recusados"]]
    assert motivos[0] == "assunto repetido" and motivos[1].endswith(": 12") and motivos[2].startswith("recomendação")
    assert motivos[3] == "não cita fato que exista"
    llm.resumo_dossie = {"abertura": "", "destaques": []}
    r = executivo.resumir_dossie("m", "SEPOL", fatos, [], "abertura por código")
    assert r["abertura"] == "abertura por código" and r["por_codigo"]


# --- O DOSSIÊ: CARTÕES E VALORES CURTOS ---------------------------------------------------------------------------

def test_cartoes_e_valores_curtos(funcoes):
    assert funcoes._compacto(3237754901.47) == "R$ 3,24 bi" and funcoes._compacto(156470000) == "R$ 156,47 mi"
    assert funcoes._compacto(45400275, 1) == "R$ 45,4 mi" and funcoes._compacto(950000) == "R$ 950 mil"
    assert funcoes._reais_compactos("R$ 3.237.754.901,47") == "R$ 3,24 bi"
    assert funcoes._reais_compactos("R$ 3,24 bi") == "R$ 3,24 bi" and funcoes._reais_compactos("190") == "190"
    assert funcoes._competencia_curta("setembro de 2026") == "set/2026"
    folha = {"vinculos": "9.763", "folha_mes": "R$ 156,47 mi", "competencia": "setembro de 2026"}
    lei = {"total_loa": 3139954311, "total_ploa": 3389386020, "unidades": [], "principal": ""}
    ind = lambda nome, valor: {"nome": nome, "valor": valor, "rotulo": "informado pelo órgão"}
    diag = {"indicadores": [ind("Dotação inicial na LOA 2026", "R$ 3.138.774.347"),     # a lei já está nos cartões
                            ind("Viaturas próprias", "3.926"), ind("Imóveis no patrimônio", "190"),
                            ind("Vínculos", "9.763"),                                    # número que já apareceu
                            ind("Dotação atualizada 2026", "R$ 3.237.754.901,47"),
                            ind("Texto longo", "um valor que não cabe num cartão de número")]}
    cartoes = funcoes.cartoes_do_dossie(diag, folha, lei)
    assert cartoes == [("9.763", "vínculos ativos (set/2026)"), ("R$ 156,47 mi", "folha de pessoal do mês"),
                       ("R$ 3,14 bi", "LOA 2026 (dotação inicial)"), ("R$ 3,39 bi", "PLOA 2027 (+7,9%)"),
                       ("3.926", "Viaturas próprias"), ("190", "Imóveis no patrimônio"),
                       ("R$ 3,24 bi", "Dotação atualizada 2026")]


# --- TCE-RJ ---------------------------------------------------------------------------------------------------------

def test_tce_no_formato_executivo(monkeypatch, tmp_path):
    from test_tce import DEBITOS, MULTAS
    from transicao import tce
    monkeypatch.delenv("TCE_DESLIGADO", raising=False)
    monkeypatch.setenv("PASTA_REGISTROS", str(tmp_path / "registros"))
    tce._MEMORIA.clear(); tce._FALHAS.clear()
    monkeypatch.setattr(tce, "_baixar_json", lambda caminho, params: MULTAS if params["tipo"] == "multa" else DEBITOS)
    md = tce.markdown_executivo(tce.cruzar("SEEDUC", "Processo 100144-5/2022.", "10/11/2026"))
    assert md.startswith("## Controle externo (TCE-RJ)\nDados abertos do TCE-RJ, consultados em ")
    assert ": de 2024 para cá, 3 condenações em multa e 2 condenações em débito, em 3 processos; 2 não aparecem no " \
           "material enviado pela secretaria." in md
    assert "| Processo | Última sessão | Multas | Débitos | No material |" in md and "R$ " not in md.replace("(R$ ou", "")
    sem = tce.markdown_executivo(tce.cruzar("SETUR", "", "10/11/2026"))
    assert "nenhuma multa ou débito" in sem or "nenhuma condenação" in sem
    assert tce.markdown_executivo(None) == ""
    tce._MEMORIA.clear(); tce._FALHAS.clear()


# --- O WORD ----------------------------------------------------------------------------------------------------------

def test_word_desenha_grupo_quebra_na_celula_prioridade_e_cartoes(funcoes):
    import docx
    md = "\n".join(["## Resumo executivo", "```cartoes", "9.763 | vínculos ativos", "R$ 3,24 bi | dotação 2026", "```",
                    "| Nº | Ponto | Prioridade |", "|---|---|---|", "| § 1. Continuidade de serviço |",
                    "| 1.1 | **Limpeza do IML**<br>Venceu sem aditivo. | Máxima<br>impacto alto |",
                    "| 1.2 | **Firewall**<br>Em prorrogação. | Média<br>impacto médio |", "<<<QUEBRA>>>", "## 1. Tema"])
    doc = docx.Document(io.BytesIO(funcoes.gerar_docx(md, {"orgao": "Equipe", "assunto": "SEPOL"})))
    cartoes, quadro = doc.tables
    assert [p.text for p in cartoes.cell(0, 0).paragraphs] == ["9.763", "vínculos ativos"]
    assert cartoes.cell(0, 2).text == "" and 'w:fill="EEF2F7"' not in cartoes.cell(0, 2)._tc.xml   # sobra em branco
    grupo = quadro.rows[1]._tr.xml
    assert 'w:gridSpan w:val="3"' in grupo and 'w:fill="E8EDF4"' in grupo and "1. Continuidade de serviço" in grupo
    celula = quadro.cell(2, 1)
    assert "<w:br/>" in celula._tc.xml and celula.text.replace("\n", " | ") == "Limpeza do IML | Venceu sem aditivo."
    assert 'w:fill="F6DBD6"' in quadro.cell(2, 2)._tc.xml and 'w:fill="DAECE1"' in quadro.cell(3, 2)._tc.xml
    assert sum('w:br w:type="page"' in p._p.xml for p in doc.paragraphs) == 1


# --- A RODADA ---------------------------------------------------------------------------------------------------------

def test_rodada_registra_o_resumo_executivo(llm):
    from transicao import analise
    r = analise.analisar_orgao("Secretaria de Exemplo", RELATORIO, CFG)
    reg = r["registro"]["resumo_executivo"]
    assert not reg["riscos"]["por_codigo"] and not reg["dossie"]["por_codigo"]
    assert r["riscos_md"].split("\n")[1] == reg["riscos"]["abertura"]
    assert reg["dossie"]["abertura"] in r["dossie_md"] and reg["dossie"]["destaques"]
    etapas = [u["etapa"] for u in r["registro"]["uso_tokens"]]
    assert "relatório de riscos: resumo executivo" in etapas and "dossiê: resumo executivo" in etapas
    # o pedido do dossiê leva as bases oficiais e os fatos dos capítulos que ficam no documento
    ids = [f["id"] for f in llm.pedido_resumo_dossie["fatos"]]
    assert all(re.fullmatch(r"[BIFVR]\d+", i) for i in ids)
    # a IA recomendando: o código troca pela abertura montada por código e registra o motivo
    llm.resumo_riscos = {"abertura": "Recomenda-se renovar os contratos.", "fatos": ["R1"], "temas": [], "em_jogo": []}
    r = analise.analisar_orgao("Secretaria de Exemplo", RELATORIO, CFG)
    reg = r["registro"]["resumo_executivo"]["riscos"]
    assert reg["por_codigo"] and reg["recusados"][0]["motivo"].startswith("recomendação")
    assert "Recomenda-se" not in r["riscos_md"] and r["riscos_md"].split("\n")[1].startswith("2 pontos de atenção em")
