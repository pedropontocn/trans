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
    assert "| R1 | Contrato de apoio escolar vence em 11/06/2027 | 11/06/2027 | Depois dos 100 dias | Alta | órgão |" in md
    assert "72 horas" not in md                                   # o voto vencido pela data não aparece nem como disputa
    assert ("- **Prazo:** Vence em 11/06/2027. Para não haver interrupção, a decisão precisa sair até 12/05/2027, "
            "30 dias antes. Janela: depois dos 100 dias.") in md
    # sem data no material, vale o voto, e o texto diz que é voto
    sem_data = _risco(prazo_de_fato=False, data_evento=None, agir_ate=date(2027, 1, 3), horizonte="Primeiras 72 horas",
                      votos={"janela": {"nivel": "Primeiras 72 horas", "votos": 6, "total": 6, "prevaleceu": "voto"}})
    md = funcoes.relatorio_riscos({"riscos": [sem_data]}, None, "", data_corte="10/11/2026")
    assert "| sem data | Primeiras 72 horas |" in md
    assert "Sem data no material. Janela: primeiras 72 horas, pelo voto de 6 dos 6 agentes." in md


def test_prazo_vencido_aparece_como_vencido(funcoes):
    vencido = _risco(data_evento=date(2026, 10, 26), agir_ate=date(2026, 9, 26), horizonte="Antes da posse", vencido=True)
    md = funcoes.relatorio_riscos({"riscos": [vencido]}, None, "", data_corte="10/11/2026")
    assert "| 26/10/2026 | Prazo vencido |" in md and "Antes da posse" not in md
    assert "- **Prazo:** Vence em 26/10/2026, já vencido. Janela: prazo vencido." in md
    # o contrato ainda não venceu, mas os 30 dias de antecedência já passaram: o texto diz
    apertado = _risco(data_evento=date(2026, 12, 1), agir_ate=date(2026, 11, 1), horizonte="Antes da posse")
    md = funcoes.relatorio_riscos({"riscos": [apertado]}, None, "", data_corte="10/11/2026")
    assert "| 01/12/2026 | Antes da posse |" in md
    assert "a decisão precisa sair até 01/11/2026, 30 dias antes, data que já passou" in md


def test_contestacao_acatada_nao_aparece_e_a_pendente_vem_com_a_resposta(funcoes):
    objecoes = [{"papel": "Advogado do diabo", "tipo": "contestado", "motivo": "V3 é o contrato do SENAI, sem relação",
                 "resposta": "acatado (V3 saiu dos fatos.)"},
                {"papel": "Fazenda e orçamento", "tipo": "exagerado", "motivo": "O material não registra glosa do TCE-RJ",
                 "resposta": "parcial (A glosa saiu; os ajustes sem contrato mantêm o risco.)"}]
    md = funcoes.relatorio_riscos({"riscos": [_risco(revisao={"objecoes": objecoes})]}, None, "", data_corte="10/11/2026")
    assert "SENAI" not in md                                       # já corrigida no texto: fica só na auditoria
    assert ("- **Ponto contestado:** Fazenda: O material não registra glosa do TCE-RJ. Resposta da consolidação "
            "(parcial): A glosa saiu; os ajustes sem contrato mantêm o risco.") in md
    limpo = funcoes.relatorio_riscos({"riscos": [_risco()]}, None, "", data_corte="10/11/2026")
    assert "Ponto contestado" not in limpo and "Advogado do diabo contesta" not in limpo


def test_cada_risco_em_linhas_rotuladas_sem_codigos_e_com_fontes(funcoes):
    diag = {"secoes": [{"titulo": "Contratos", "itens": [
        {"id": "F1", "texto": "x", "rotulo": "informado pelo órgão", "url": "", "origem_item": ""},
        {"id": "F5", "texto": "y", "rotulo": "fonte pública conferida", "url": "https://g1.globo.com/a", "origem_item": "O20"}]}]}
    dossie = {"itens": [{"id": "O20", "afirmacao": "y", "fonte": "G1", "data_fonte": "06/02/2026", "incluir": True,
                         "url": "https://g1.globo.com/a", "tipo_fonte": "imprensa", "checagem": "conferido"}]}
    md = funcoes.relatorio_riscos({"riscos": [_risco(fatos=["F1", "V2", "F5"])]}, None, "", diag=diag, dossie=dossie,
                                  data_corte="10/11/2026")
    bloco = md.split("## Os riscos, um a um")[1]
    rotulos = [l.split(":**")[0] for l in bloco.strip().split("\n")[1:]]
    assert rotulos == ["- **Fato", "- **Consequência", "- **Ponto de decisão", "- **Prazo", "- **Peso",
                       "- **Repercussão possível", "- **Fontes"]
    assert "(F1)" not in md and "(V2)" not in md
    assert "- **Fontes:** material enviado pela secretaria; [G1, 06/02/2026](https://g1.globo.com/a)." in md
    assert "- **Peso:** prioridade alta; impacto alto; repercussão política alta." in md


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
    assert "| 2 | Decisão do TCE-RJ sobre a cautelar das obras escolares | Derrubaria o risco. | TCE-RJ | R1 | Advogado do diabo |" in md
    assert "| R2 | Análise, Área-fim |" in md and "| – | Consolidação |" in md
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
    assert "- **A confirmar:** O fato não fala em parada." in md


def test_rodada_inteira_gera_o_relatorio_novo(llm, tmp_path):
    from transicao import analise
    r = analise.analisar_orgao("seeduc", RELATORIO, CFG)
    md = r["riscos_md"]
    assert "## Situação" not in md and "Advogado do diabo contesta" not in md and "6/6" not in md
    pauta = md.split("## Informações que faltam: a pauta de investigação")[1]
    assert "Lista de contratos vigentes com datas de término" in pauta and "Fazenda" in pauta and "Análise" in pauta
    assert "Parecer da PGE sobre a retomada das licitações" not in pauta or "Advogado do diabo" in pauta
    reg = r["registro"]
    assert reg["conferencia_final"]["corrigidos"] == [] and len(reg["lacunas_brutas"]) >= 7     # análise + 6 agentes
    assert any(l["quem"] == "Advogado do diabo" for l in reg["lacunas_brutas"])
    # o título do documento: a sigla em maiúsculas e o nome por extenso
    import io
    import docx
    textos = [p.text for p in docx.Document(io.BytesIO(r["riscos_docx"])).paragraphs]
    assert "SEEDUC – Secretaria de Estado de Educação" in textos and "seeduc" not in textos
