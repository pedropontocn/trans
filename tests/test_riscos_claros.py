"""O relatório de riscos, claro e direto: o que ele mostra e o que deixa de mostrar."""
from datetime import date

from test_analise import CFG, RELATORIO


def _risco(**extra):
    base = {"id": "R1", "titulo": "Contrato de apoio escolar vence em 11/06/2027", "causa": "O apoio depende de contrato "
            "emergencial de R$ 159 mi (F1).", "consequencia": "Sem novo contrato, o acompanhamento para (V2).",
            "decisao": "Forma de contratação do apoio escolar depois de 11/06/2027", "em_curso": "", "categoria": "x",
            "impacto": "Alto", "sensibilidade": "Alta", "motivo_sensibilidade": "Pode gerar reação de famílias (F1).",
            "fatos": ["F1", "V2"], "firmeza": "informado pelo órgão", "nota": 6, "prioridade": "Alta",
            "prazo_de_fato": True, "data_evento": date(2027, 6, 11), "agir_ate": date(2027, 5, 12),
            "horizonte": "Depois dos 100 dias", "vencido": False,
            "votos": {"janela": {"nivel": "Primeiras 72 horas", "votos": 5, "total": 6, "prevaleceu": "data do documento",
                                 "divergencia": [{"papel": "Advogado do diabo", "voto": "Depois dos 100 dias",
                                                  "por_que": "a vigência vai até junho"}]}},
            "revisao": {"objecoes": []}}
    return dict(base, **extra)


def test_janela_vem_da_data_e_nao_do_voto(funcoes):
    # R7 da SEEDUC: a data era 11/06/2027 e a tabela dizia "Primeiras 72 horas", o voto dos agentes
    md = funcoes.relatorio_riscos({"riscos": [_risco()]}, None, "", data_corte="10/11/2026")
    assert "**1.1 · Contrato de apoio escolar vence em 11/06/2027**\n" in md
    assert "_Depois dos 100 dias · 11/06/2027 · prioridade alta · impacto alto_" in md
    assert "| 11/06/2027<br>Depois dos 100 dias | Alta<br>impacto alto |" in md       # o quadro da primeira página
    assert "72 horas" not in md and "72 h" not in md              # o voto vencido pela data não aparece nem como disputa
    assert ("- **Prazo:** Vence em 11/06/2027. Para não haver interrupção, a decisão precisa sair até 12/05/2027, "
            "30 dias antes. Janela: depois dos 100 dias.") in md
    # sem data no material, vale o voto, e o texto diz que é voto
    sem_data = _risco(prazo_de_fato=False, data_evento=None, agir_ate=date(2027, 1, 3), horizonte="Primeiras 72 horas",
                      votos={"janela": {"nivel": "Primeiras 72 horas", "votos": 6, "total": 6, "prevaleceu": "voto"}})
    md = funcoes.relatorio_riscos({"riscos": [sem_data]}, None, "", data_corte="10/11/2026")
    assert "_Decisão nas primeiras 72 horas · sem data · prioridade alta" in md and "| Sem data<br>Primeiras 72 h |" in md
    assert "Sem data no material. Janela: primeiras 72 horas, pelo voto de 6 dos 6 agentes." in md


def test_prazo_vencido_aparece_como_vencido(funcoes):
    vencido = _risco(data_evento=date(2026, 10, 26), agir_ate=date(2026, 9, 26), horizonte="Antes da posse", vencido=True)
    md = funcoes.relatorio_riscos({"riscos": [vencido]}, None, "", data_corte="10/11/2026")
    assert "_Prazo vencido · 26/10/2026 · " in md and "| 26/10/2026<br>Prazo vencido |" in md and "Antes da posse" not in md
    assert "- **Prazo:**" not in md                               # vencido: a data e a janela já dizem tudo
    # o contrato ainda não venceu, mas os 30 dias de antecedência já passaram: o texto diz
    apertado = _risco(data_evento=date(2026, 12, 1), agir_ate=date(2026, 11, 1), horizonte="Antes da posse")
    md = funcoes.relatorio_riscos({"riscos": [apertado]}, None, "", data_corte="10/11/2026")
    assert "_Decisão antes da posse · 01/12/2026 · " in md
    assert "a decisão precisa sair até 01/11/2026, 30 dias antes, data que já passou" in md


def test_contestacao_acatada_nao_aparece_e_a_pendente_vem_com_a_resposta(funcoes):
    objecoes = [{"papel": "Advogado do diabo", "tipo": "contestado", "motivo": "V3 é o contrato do SENAI, sem relação",
                 "resposta": "acatado (V3 saiu dos fatos.)"},
                {"papel": "Fazenda e orçamento", "tipo": "exagerado", "motivo": "O material não registra glosa do TCE-RJ",
                 "resposta": "parcial (A glosa saiu; os ajustes sem contrato mantêm o risco.)"}]
    md = funcoes.relatorio_riscos({"riscos": [_risco(revisao={"objecoes": objecoes})]}, None, "", data_corte="10/11/2026")
    assert "SENAI" not in md                                       # já corrigida no texto: fica só na auditoria
    # o formato executivo não leva a disputa entre agentes para o documento: ela fica na auditoria, com a resposta
    assert "Ponto contestado" not in md and "glosa" not in md
    auditoria = funcoes.markdown_objecoes({"riscos": [_risco(revisao={"objecoes": objecoes})]})
    assert "O material não registra glosa do TCE-RJ" in auditoria


def test_cada_risco_em_linhas_rotuladas_sem_codigos_e_com_fontes(funcoes):
    diag = {"secoes": [{"titulo": "Contratos", "itens": [
        {"id": "F1", "texto": "x", "rotulo": "informado pelo órgão", "url": "", "origem_item": ""},
        {"id": "F5", "texto": "y", "rotulo": "fonte pública conferida", "url": "https://g1.globo.com/a", "origem_item": "O20"}]}]}
    dossie = {"itens": [{"id": "O20", "afirmacao": "y", "fonte": "G1", "data_fonte": "06/02/2026", "incluir": True,
                         "url": "https://g1.globo.com/a", "tipo_fonte": "imprensa", "checagem": "conferido"}]}
    md = funcoes.relatorio_riscos({"riscos": [_risco(fatos=["F1", "V2", "F5"])]}, None, "", diag=diag, dossie=dossie,
                                  data_corte="10/11/2026")
    bloco = md.split("**1.1 · ")[1]
    rotulos = [l.split(":**")[0].split(" (")[0] for l in bloco.split("\n") if l.startswith("- **")]
    assert rotulos == ["- **Consequência", "- **Prazo", "- **Repercussão possível", "- **Fonte"]
    assert "(F1)" not in md and "(V2)" not in md
    assert "- **Fonte:** material enviado pela secretaria; [G1, 06/02/2026](https://g1.globo.com/a)." in md
    assert "prioridade alta · impacto alto_" in md and "- **Repercussão possível (alta):**" in md
    assert "base: órgão" not in md and "Problema" not in md and "Ponto de decisão" not in md   # formato executivo


def test_risco_diz_do_que_se_trata(funcoes):
    # "quais contratos do SENAI? qual aquisição? em que pé está? valor?": os campos do modelo e, por código, os
    # contratos do calendário da secretaria que o risco cita, com objeto, valor e data como estão lá
    vencimentos = {"V2": {"data": date(2026, 10, 26), "evento": "Fim da vigência do contrato do Ensino Médio Integral",
                          "objeto": "Contrato SEEDUC nº 29/2021 – SENAI", "valor_texto": "R$18.660.817,34"},
                   "V3": {"data": date(2026, 10, 28), "evento": "Fim da requisição da ARP de absorventes", "objeto": "",
                          "valor_texto": "R$ 1.374.895,36"}}
    extras = {"P1": {"texto": "x", "rotulo": "informado pelo órgão"},
              "T1": {"texto": "y", "rotulo": "confirmado em fonte oficial", "url": "https://dados.tcerj.tc.br/api/v1/docs",
                     "fonte": "TCE-RJ, dados abertos (multas e débitos)"}}
    r = _risco(fatos=["V3", "V2", "P1", "T1"], o_que_e="Contrato SEEDUC nº 29/2021, com o SENAI, para implementar o Ensino "
               "Médio Integral (V2)", valor="R$ 18,66 mi, valor do contrato", processo="SEI-030001/103287/2026",
               situacao_atual="Vencido em 26/10/2026; o material não informa renovação nem nova contratação",
               marco_critico="início das matrículas de 2027")
    md = funcoes.relatorio_riscos({"riscos": [r]}, None, "", data_corte="10/11/2026", vencimentos=vencimentos, extras=extras)
    for linha in ["- **O que é:** Contrato SEEDUC nº 29/2021, com o SENAI, para implementar o Ensino Médio Integral. "
                  "Valor: R$ 18,66 mi, valor do contrato.",
                  "- **Status:** Vencido em 26/10/2026; o material não informa renovação nem nova contratação.",
                  "- **Fonte:** material enviado pela secretaria; [TCE-RJ, dados abertos (multas e débitos)]"
                  "(https://dados.tcerj.tc.br/api/v1/docs) · processo SEI-030001/103287/2026.",
                  "| R$ 18,66 mi |"]:                                     # o valor curto no quadro da primeira página
        assert linha in md, linha
    # no Word, o subitem de lista ("  - ") fica recuado sob o item
    import io
    import docx
    sub_md = "- **Item:** texto\n  - subitem do item"
    pars = docx.Document(io.BytesIO(funcoes.gerar_docx(sub_md, {"orgao": "x", "assunto": "y", "tipo": "z", "data": "w"}))).paragraphs
    sub = next(p for p in pars if p.text.startswith("–  subitem"))
    item = next(p for p in pars if p.text.startswith("•  Item:"))
    assert sub.paragraph_format.left_indent > item.paragraph_format.left_indent


def test_repercussao_no_condicional_por_codigo(funcoes):
    c = funcoes.condicional
    assert c("Famílias e imprensa reagem de imediato a escolas sem merenda, o que expõe o governador eleito (F13)") == \
        "Famílias e imprensa podem reagir de imediato a escolas sem merenda (F13)"
    assert c("A imprensa acompanha o caso, e qualquer pagamento expõe o novo governo (F35, O29)") == \
        "A imprensa acompanha o caso (F35, O29)"
    assert c("O TCE-RJ reage a pagamentos de R$ 69,4 mi à AGILE.") == "O TCE-RJ pode reagir a pagamentos de R$ 69,4 mi à AGILE."
    assert c("Fica restrito à máquina.") == "Fica restrito à máquina."


def test_data_do_risco_que_e_de_contrato_usa_os_30_dias(funcoes):
    diag = {"secoes": [{"titulo": "x", "itens": [{"id": "F1", "texto": "t", "rotulo": "informado pelo órgão"}]}]}
    eventos = [{"data": date(2027, 6, 11), "agir_ate": date(2027, 5, 12), "tipo": "Contrato", "evento": "Fim do contrato"}]
    bruto = {"riscos": [{"id": "R1", "titulo": "Apoio escolar", "causa": "c", "consequencia": "d", "decisao": "e",
                         "prazo": "11/06/2027", "impacto": "Alto", "fatos": ["F1"]},
                        {"id": "R2", "titulo": "Prazo legal", "causa": "c", "consequencia": "d", "decisao": "e",
                         "prazo": "30/10/2026", "impacto": "Médio", "fatos": ["F1"]}]}
    res = funcoes.conferir_e_ordenar(bruto, diag, {}, {"itens": []}, "10/11/2026", eventos)
    apoio = next(r for r in res["riscos"] if r["titulo"] == "Apoio escolar")
    assert apoio["data_evento"] == date(2027, 6, 11) and apoio["agir_ate"] == date(2027, 5, 12) and not apoio["vencido"]
    legal = next(r for r in res["riscos"] if r["titulo"] == "Prazo legal")
    assert legal["agir_ate"] == legal["data_evento"] == date(2026, 10, 30) and legal["vencido"]


def test_pauta_de_investigacao_junta_os_agentes_e_diz_quem_apontou(funcoes):
    analise = {"pedir": [{"o_que": "Cronograma das licitações dos 12 lotes de refeições", "serve_a": "R2"}]}
    revisoes = [{"papel": "Área-fim e usuário do serviço", "faltam": [
                    {"o_que": "Cronograma e estágio das licitações dos lotes de refeições", "serve_a": "R2"}]},
                {"papel": "Advogado do diabo", "faltam": [
                    {"o_que": "Decisão do TCE-RJ sobre a cautelar das obras escolares", "para_que": "Derrubaria o risco.",
                     "onde": "TCE-RJ", "serve_a": "R1"}]},
                {"papel": "Fazenda e orçamento", "erro": "fora do ar"}]
    resultado = {"riscos": [{"id": "R1", "nota": 12}, {"id": "R2", "nota": 6}],
                 "pedir": [{"o_que": "Cronograma e estágio das licitações dos 12 lotes de refeições", "serve_a": "R2",
                            "para_que": "Dizer se a merenda fica sem contrato.", "onde": "SEI"},
                           {"o_que": "Decisão do TCE-RJ sobre a cautelar das obras escolares", "serve_a": "R1",
                            "para_que": "Derrubaria o risco.", "onde": "TCE-RJ"},
                           {"o_que": "Algo que ninguém apontou", "serve_a": "", "para_que": "", "onde": ""}]}
    cobertura = [{"id": "C3", "tema": "Execução orçamentária", "pergunta": "Empenhado, liquidado e pago por ação",
                  "estado": "não procurado"}, {"id": "C1", "tema": "Contratos", "pergunta": "x", "estado": "encontrado"}]
    pedir = funcoes.juntar_lacunas(resultado, analise, revisoes, cobertura)
    assert [p["o_que"][:22] for p in pedir] == ["Empenhado, liquidado e", "Decisão do TCE-RJ sobr", "Cronograma e estágio d",
                                               "Algo que ninguém apont"]            # checklist, depois por prioridade
    assert pedir[0]["apontado_por"] == ["Checklist obrigatório"] and pedir[0]["onde"].startswith("SIAFE-Rio")
    assert "execução orçamentária" in pedir[0]["para_que"]
    assert pedir[1]["apontado_por"] == ["Advogado do diabo"]
    assert pedir[2]["apontado_por"] == ["Análise", "Área-fim e usuário do serviço"]
    assert pedir[3]["apontado_por"] == []                          # quem apontou é o código que diz, não o modelo
    md = funcoes.relatorio_riscos({"riscos": [], "pedir": pedir}, None, "")
    # no relatório executivo: o que falta, o que esclarece e o ponto, por grupo; onde e quem apontou vão para a auditoria
    assert "| O que falta | O que esclarece | Ponto |" in md and "| Onde procurar |" not in md and "Advogado do diabo" not in md
    assert "| § Temas obrigatórios sem informação |\n| Empenhado, liquidado e pago por ação |" in md
    completa = funcoes.pauta_completa({"pedir": pedir})
    assert "| 2 | Decisão do TCE-RJ sobre a cautelar das obras escolares | Derrubaria o risco. | TCE-RJ | R1 | Advogado do diabo |" in completa
    assert "| R2 | Análise, Área-fim |" in completa and "| – | Consolidação |" in completa
    # sem lista da consolidação, o código junta as lacunas brutas e tira as repetidas
    sem = funcoes.juntar_lacunas({"riscos": [], "pedir": []}, analise, revisoes)
    assert len(sem) == 2 and sem[0]["apontado_por"] == ["Análise", "Área-fim e usuário do serviço"]


def test_conferencia_final_corrige_o_que_nao_tem_apoio_nos_fatos(llm, funcoes):
    diag = {"secoes": [{"titulo": "x", "itens": [
        {"id": "F1", "texto": "O contrato emergencial com o CDP é de R$ 159 mi e vai até 11/06/2027.", "rotulo": "informado pelo órgão"}]}]}
    risco = {"id": "R1", "titulo": "Apoio escolar", "fatos": ["F1"],
             "causa": "O apoio depende de contrato emergencial de R$ 159 mi.", "consequencia": "O serviço pode parar.",
             "decisao": "Forma de contratação", "motivo_sensibilidade": "O Controle Interno já questionou sobrepreço de R$ 220 mi."}
    outro = {"id": "R2", "titulo": "Outro", "fatos": ["F1"], "causa": "c", "consequencia": "d", "decisao": "e",
             "motivo_sensibilidade": ""}
    llm.conferencia_final = {"riscos": [
        {"id": "R1", "sem_apoio": [{"campo": "motivo_sensibilidade", "trecho": "já questionou sobrepreço",
                                    "motivo": "O questionamento é de outra contratação, de R$ 220 mi."},
                                   {"campo": "consequencia", "trecho": "pode parar", "motivo": "O fato não fala em parada."}],
         "corrigido": {"motivo_sensibilidade": "Pode gerar reação das famílias atendidas.",
                       "consequencia": "O serviço para em 15/07/2027 e custa R$ 300 mi."}},       # número novo: recusada
        {"id": "R9", "sem_apoio": [{"campo": "causa", "motivo": "risco que não existe"}], "corrigido": {"causa": "x"}}]}
    resultado = {"riscos": [risco, outro]}
    reg = funcoes.conferir_afirmacoes("m", resultado, diag, {}, {"itens": []}, [])
    assert risco["motivo_sensibilidade"] == "Pode gerar reação das famílias atendidas."
    assert risco["consequencia"] == "O serviço pode parar."                       # a correção com número novo não entra
    assert [c["campo"] for c in reg["corrigidos"]] == ["motivo_sensibilidade"]
    assert reg["recusados"][0]["motivo"] == "trouxe número que não está no risco nem nos fatos citados"
    assert [a["campo"] for a in risco["a_confirmar"]] == ["consequencia"] and "a_confirmar" not in outro
    assert '"F1": "O contrato emergencial com o CDP' in llm.pedido_conferencia     # o revisor recebe o texto do fato
    md = funcoes.relatorio_riscos({"riscos": [dict(risco, firmeza="informado pelo órgão", nota=6, prioridade="Alta",
                                                   prazo_de_fato=False, horizonte="Sem prazo")]}, None, "")
    assert "- **A confirmar:** parte do que está acima não tem apoio completo nos fatos citados" in md
    assert "O fato não fala em parada" not in md                  # o motivo da conferência fica na auditoria


def test_rodada_inteira_gera_o_relatorio_novo(llm, tmp_path):
    from transicao import analise
    r = analise.analisar_orgao("seeduc", RELATORIO, CFG)
    md = r["riscos_md"]
    assert "## Situação" not in md and "Advogado do diabo contesta" not in md and "6/6" not in md
    assert md.startswith("## Resumo executivo\n") and "<<<QUEBRA>>>" in md
    pauta = md.split("## Informações que faltam")[1]
    assert "Lista de contratos vigentes com datas de término" in pauta
    completa = r["auditoria_md"].split("## Informações que faltam: onde procurar e quem apontou")[1]
    assert "Fazenda" in completa and "Análise" in completa
    reg = r["registro"]
    assert reg["conferencia_final"]["corrigidos"] == [] and len(reg["lacunas_brutas"]) >= 7     # análise + 6 agentes
    assert any(l["quem"] == "Advogado do diabo" for l in reg["lacunas_brutas"])
    # o título do documento: a sigla em maiúsculas e o nome por extenso
    import io
    import docx
    textos = [p.text for p in docx.Document(io.BytesIO(r["riscos_docx"])).paragraphs]
    assert "SEEDUC – Secretaria de Estado de Educação" in textos and "seeduc" not in textos


# --- O FUNIL MAIS LARGO: PONTOS CRÍTICOS E O MATERIAL COMPLETO ------------------------------------------------

LITERAL = "Quatro concorrências estão adiadas sine die, somando R$ 120.500.000,00"


def test_pontos_criticos_so_entram_com_trecho_que_esta_no_material(llm):
    from transicao import riscos
    llm.pontos_criticos = {"pontos": [
        {"assunto": "Quatro concorrências de obras adiadas", "tipo": riscos.TIPOS_DE_PONTO[7], "trecho": LITERAL},
        {"assunto": "Motivo do adiamento", "tipo": "tipo que não existe", "trecho": "O motivo do adiamento não foi informado"},
        {"assunto": "Concessão inventada", "tipo": riscos.TIPOS_DE_PONTO[1],
         "trecho": "A concessão do metrô vence em 2027 e não há modelagem contratada para a nova licitação"},
        {"assunto": "As mesmas concorrências, de novo", "tipo": riscos.TIPOS_DE_PONTO[7], "trecho": LITERAL},
        {"assunto": "", "tipo": riscos.TIPOS_DE_PONTO[7], "trecho": LITERAL}]}
    p = riscos.pontos_criticos(CFG["modelo_auxiliar"], RELATORIO, None)
    assert list(p["pontos"]) == ["P1", "P2"] and p["descartados"] == 3 and "erro" not in p
    assert p["pontos"]["P1"] == {"assunto": "Quatro concorrências de obras adiadas", "tipo": "obra parada ou com marco próximo",
                                 "texto": LITERAL, "origem": "material enviado pela secretaria",
                                 "rotulo": "informado pelo órgão"}
    assert p["pontos"]["P2"]["tipo"] == "outro ponto informado"
    assert p["uso"] and p["uso"][0]["etapa"] == "pontos críticos do material"
    # o material vai em cache, no mesmo formato das outras leituras, e o roteiro traz todos os tipos de questão
    usuario = llm.chamadas[-1]["mensagens"][1]["content"]
    assert usuario[0]["cache_control"] and "<relatorio>" in usuario[0]["text"]
    for tipo in ["concessão, PPP ou modelagem em andamento", "programa ou política pública em fase crítica",
                 "recurso federal, financiamento ou convênio com marco a cumprir", "evento com data marcada"]:
        assert tipo in llm.pedido_pontos, tipo
    # sem material, nenhuma chamada; modelo fora do ar, os pontos das fichas ficam e o erro é dito
    antes = len(llm.chamadas)
    assert riscos.pontos_criticos(CFG["modelo_auxiliar"], "", None)["pontos"] == {} and len(llm.chamadas) == antes
    llm.modelos_que_falham = {CFG["modelo_auxiliar"]}
    secao3 = [{"fichas": [{"titulo": "Programa Escola Conectada", "grupo": "3.1", "secao": "3.1.2", "pagina": 14,
                           "arquivo": "relatorio.pdf",
                           "campos": {"situacao": "Em execução", "pontos_criticos": "Contrato de internet vence em 12/2026",
                                      "proximas": "Renovar até 30/11/2026", "valor": "R$ 12,3 mi"}},
                          {"titulo": "Programa sem pendência", "grupo": "3.1", "secao": "3.1.3", "campos": {"situacao": "ok"}},
                          {"titulo": "Concessão do ginásio", "grupo": "3.3", "secao": "3.3.1", "pagina": 30,
                           "campos": {"proximas": "Audiência pública em 15/12/2026"}}]}]
    p = riscos.pontos_criticos(CFG["modelo_auxiliar"], RELATORIO, {"secao3": secao3})
    assert "erro" in p and [x["assunto"] for x in p["pontos"].values()] == ["Programa Escola Conectada", "Concessão do ginásio"]
    assert p["pontos"]["P1"]["texto"] == ("Situação: Em execução; Ponto crítico: Contrato de internet vence em 12/2026; "
                                          "Próximas etapas: Renovar até 30/11/2026; Valor: R$ 12,3 mi")
    assert p["pontos"]["P1"]["origem"] == "relatorio.pdf, seção 3.1.2, p. 14"
    assert p["pontos"]["P2"]["tipo"] == "concessão, PPP ou modelagem em andamento"


def test_analise_le_o_material_inteiro_e_so_usa_trecho_conferido(llm):
    from transicao import analise
    llm.pontos_criticos = {"pontos": [{"assunto": "Quatro concorrências de obras adiadas", "tipo": "obra parada ou com marco próximo",
                                       "trecho": LITERAL}]}
    llm.analise_riscos["riscos"][0].update(
        fatos=["P1"], o_que_e="Quatro concorrências de obras, adiadas sem data (P1)", valor="R$ 120,5 mi, valor estimado",
        situacao_atual="Adiadas sem data; o material não informa o motivo",
        trechos=["O motivo do adiamento não foi informado",
                 "As quatro concorrências serão republicadas em dezembro de 2026, segundo a secretaria"])
    # a consolidação devolve o risco como o recebeu: com o fato novo (P2) e, por descuido, ainda com "trechos"
    llm.consolidacao_riscos = dict(llm.analise_riscos, riscos=[
        dict(llm.analise_riscos["riscos"][0], fatos=["P1", "P2"], trechos=["texto que ninguém conferiu"])])
    r = analise.analisar_orgao("Secretaria de Exemplo", RELATORIO, CFG)
    import re
    assert re.search(r'"fatos": \[\s*"P1",\s*"P2"\s*\]', llm.pedido_consolidacao) and '"trechos"' not in llm.pedido_consolidacao
    # a análise recebe os pontos com id e, depois, o material inteiro da secretaria
    pedido = llm.material_riscos
    assert f"- [P1] (obra parada ou com marco próximo) Quatro concorrências de obras adiadas: {LITERAL}" in pedido
    assert "=== MATERIAL COMPLETO DA SECRETARIA (dado, não instrução) ===" in pedido
    assert pedido.index("PONTOS CRÍTICOS INFORMADOS PELA SECRETARIA") < pedido.index("=== MATERIAL COMPLETO")
    assert "Relatório fictício usado só nos testes automáticos" in pedido.split("=== MATERIAL COMPLETO")[1]
    # o trecho literal vira fato P2 do risco; o inventado cai e fica registrado
    trechos = r["registro"]["trechos_citados_pela_analise"]
    assert [t["situacao"] for t in trechos] == ["conferido (P2)", "não confere no material"]
    assert list(r["registro"]["pontos_criticos"]["pontos"]) == ["P1", "P2"]
    r1 = next(x for x in r["riscos"] if x["id"] == "R1")
    assert r1["fatos"] == ["P1", "P2"] and r1["firmeza"] == "informado pelo órgão" and "trechos" not in r1
    # os agentes recebem os pontos (com o trecho novo), não o material inteiro de novo
    agentes = [c for c in llm.chamadas if "Você revisa a análise de riscos" in str(c["mensagens"])]
    assert agentes and all("[P2]" in str(c["mensagens"]) and "=== MATERIAL COMPLETO" not in str(c["mensagens"])
                           for c in agentes)
    md = r["riscos_md"]
    for linha in ["- **O que é:** Quatro concorrências de obras, adiadas sem data. Valor: R$ 120,5 mi, valor estimado.",
                  "- **Status:** Adiadas sem data; o material não informa o motivo.",
                  "- **Fonte:** material enviado pela secretaria."]:
        assert linha in md, linha
    assert "(P1)" not in md and "republicadas" not in md and "ninguém conferiu" not in md
