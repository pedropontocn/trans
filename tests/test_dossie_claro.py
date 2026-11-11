"""O dossiê da secretaria ("como funciona hoje"): abertura própria, orçamento na lei por código (LOA 2026 e PLOA 2027),
contratos sem corte, conferências por código, imprensa só nas pendências, fontes só do que o corpo usa."""
import io
import re

from test_analise import CFG, RELATORIO

FOLHA = {"competencia": "setembro de 2026", "url": "https://www.rj.gov.br/gesperj/", "vinculos": "61.343",
         "efetivos": "55.961", "nao_efetivos": "5.382", "pct_nao_efetivos": "8,8%", "folha_mes": "R$ 320,92 mi",
         "remuneracao_media": "R$ 5.231,58", "pct": 8.8, "fora_do_mais_recente": "", "sigla": "SEEDUC", "sucessao": None}


def _item(texto, rotulo="informado pelo órgão", origem=""):
    return {"id": "F1", "texto": texto, "rotulo": rotulo, "url": "", "origem_item": origem}


def test_orcamento_na_lei_vem_das_bases_embutidas(funcoes):
    from transicao import caderno
    lei = caderno.orcamento_na_lei("seeduc")
    assert lei["principal"] == "18010" and lei["nome"] == "Secretaria de Estado de Educação"
    assert [(u["uo"], u["loa"], u["ploa"]) for u in lei["unidades"]] == [
        ("18010", 6702485057, 7654748512), ("18020", 479889772, 499330060), ("18030", 10000, 10000)]
    assert (lei["total_loa"], lei["total_ploa"]) == (7182384829, 8154088572)
    assert "criada pelo Decreto Lei nº 1, de 15 de março de 1975" in lei["atribuicoes"]
    # sigla fora da tabela conferida: nada (não adivinha a secretaria pelo nome)
    assert caderno.orcamento_na_lei("XYZ") is None and caderno.orcamento_na_lei("") is None
    assert caderno.orcamento_na_lei("Secretaria de Estado de Educação") is None
    # unidade que mudou de órgão entre as leis aparece só na lei em que está; o nome é o mais atual (PLOA)
    seiop = caderno.orcamento_na_lei("SEIOP")
    assert any(u["loa"] is None or u["ploa"] is None for u in seiop["unidades"])
    assert caderno.orcamento_na_lei("SEAP")["nome"] == "Secretaria de Estado de Administração Penitenciária"
    assert caderno.orcamento_na_lei("SEAP")["unidades"][0]["nome"] == "Secretaria de Estado de Polícia Penal"
    # como fatos do dossiê: documento oficial, conferido, um por unidade e por lei, mais as atribuições
    brutos = caderno.itens_da_lei(lei)
    assert len(brutos) == 7 and {b["tipo_fonte"] for b in brutos} == {"documento_oficial"}
    assert brutos[0]["afirmacao"] == ("Na LOA 2026, a dotação inicial de Secretaria de Estado de Educação (unidade "
                                      "orçamentária 18010) é de R$ 6.702.485.057.")
    assert brutos[1]["afirmacao"].startswith("No PLOA 2027, a proposta para Secretaria de Estado de Educação")
    assert brutos[-1]["bloco"] == "mandato_estrutura" and caderno.itens_da_lei(None) == []
    dossie = funcoes.acrescentar_itens({"itens": []}, brutos)
    assert all(i["checagem"] == "conferido" and i["id"].startswith("O") for i in dossie["itens"])


def test_ficha_rapida_com_folha_e_lei_sem_repetir(funcoes):
    from transicao import caderno, documentos
    lei = caderno.orcamento_na_lei("SEEDUC")
    diag = {"organograma": [{"unidade": "Gabinete", "sigla": "", "subordinada_a": "", "titular": "Fulana — Secretária",
                             "rotulo": "informado pelo órgão"}],
            "indicadores": [{"nome": "Dotação inicial 2026", "valor": "R$ 6.702.485.057,00", "rotulo": "informado pelo órgão"},
                            {"nome": "Dotação atualizada 2026", "valor": "R$ 7.216.267.495,45", "rotulo": "informado pelo órgão"},
                            {"nome": "Vínculos ativos (set/2026)", "valor": "61.343", "rotulo": "confirmado em fonte oficial"},
                            {"nome": "Folha mensal (set/2026)", "valor": "R$ 320,92 milhões", "rotulo": "confirmado em fonte oficial"},
                            {"nome": "Escolas da rede estadual", "valor": "1.244", "rotulo": "informado pelo órgão"}]}
    ficha = documentos.ficha_rapida(diag, FOLHA, "SEEDUC", lei)
    linhas = ficha.split("\n")[2:]
    assert linhas == [
        "| Titular | Fulana — Secretária | órgão |",
        "| Estrutura | 1 unidade no organograma | conferido no material |",
        "| Vínculos ativos e folha do mês | 61.343 vínculos; R$ 320,92 mi | fonte oficial ✔ (Caderno de RH, SEPLAG, setembro de 2026) |",
        "| Dotação inicial na LOA 2026 | R$ 6.702.485.057 (órgão, com as outras unidades: R$ 7.182.384.829) | fonte oficial ✔ (LOA 2026, Volume II) |",
        "| Proposta no PLOA 2027 | R$ 7.654.748.512 (órgão, com as outras unidades: R$ 8.154.088.572) | fonte oficial ✔ (PLOA 2027, Volume II) |",
        "| Dotação atualizada 2026 | R$ 7.216.267.495,45 | órgão |",
        "| Escolas da rede estadual | 1.244 | órgão |"]


def test_contratos_sem_corte_e_destaques_em_linha_propria(funcoes):
    from transicao import documentos
    c = lambda **k: dict({"rotulo": "informado pelo órgão", "url": "", "motivos": ["valor alto"], "observacao": ""}, **k)
    contratos = [
        c(contrato="Contrato Emergencial PED nº 09/2026", contratado="Centro de Desenvolvimento Pessoal - CDP",
          objeto="Profissionais de apoio escolar para estudantes da Educação Especial e com TEA", valor="R$158.997.240,00",
          vigencia="11/06/2027", motivos=["emergencial", "serviço essencial", "valor alto"],
          observacao="É um contrato emergencial com saldo informado de R$47.699.172,00; a licitação regular está em ajustes."),
        c(contrato="TAC 08/2026", contratado="AGILE CORP SERVIÇOS ESPECIALIZADOS LTDA", valor="R$ 14.196.481,17", vigencia="",
          objeto="Serviços de limpeza da rede estadual por Termo de Ajuste de Contas", motivos=["serviço essencial"])]
    md = documentos.markdown_contratos_criticos(contratos)
    assert "…" not in md
    assert ("| Contrato Emergencial PED nº 09/2026 | Centro de Desenvolvimento Pessoal - CDP | Profissionais de apoio escolar "
            "para estudantes da Educação Especial e com TEA | R$158.997.240,00 | 11/06/2027 |") in md
    assert "| TAC 08/2026 | AGILE CORP SERVIÇOS ESPECIALIZADOS LTDA | Serviços de limpeza da rede estadual por Termo de Ajuste de Contas | R$ 14.196.481,17 | – |" in md
    assert "| Contrato | Contratado | Objeto | Valor | Vigência |" in md and "Destaques |" not in md and "| Base |" not in md
    assert "_Todos informados pela secretaria. As datas de todos os contratos informados estão no calendário (Excel)._" in md
    assert ("- **Contrato Emergencial PED nº 09/2026 (Centro de Desenvolvimento Pessoal - CDP):** emergencial, serviço "
            "essencial, valor alto. É um contrato emergencial com saldo informado de R$47.699.172,00; a licitação regular "
            "está em ajustes.") in md
    assert "- **TAC 08/2026 (AGILE CORP SERVIÇOS ESPECIALIZADOS LTDA):** serviço essencial." in md   # a caixa é a do material
    # mais contratos do que cabem: a nota diz quantos, sem "(s)"
    muitos = [c(contrato=f"Contrato {k}/2026", contratado=f"Empresa {k}", objeto="x", valor=f"R$ {k}.000,00", vigencia="")
              for k in range(1, 15)]
    md = documentos.markdown_contratos_criticos(muitos)
    assert "Os 12 mais críticos dos 14 que a leitura do material destacou." in md and "(s)" not in md
    # no Word, a tabela não quebra palavra nem valor
    import docx
    doc = docx.Document(io.BytesIO(funcoes.gerar_docx("## 4. Principais contratos\n" + documentos.markdown_contratos_criticos(contratos),
                                                      {"orgao": "x", "assunto": "y", "tipo": "z", "data": "w"})))
    celulas = [c.text for t in doc.tables for l in t.rows for c in l.cells]
    assert "Contrato Emergencial PED nº 09/2026" in celulas and "R$158.997.240,00" in celulas


def test_soma_do_pessoal_contra_o_caderno_de_rh(funcoes):
    from transicao import documentos
    frase = ("A SUPGP registra 48.565 professores efetivos em exercício, 4.842 professores temporários, 5.065 servidores "
             "administrativos, 524 inspetores de alunos e 612 servidores na categoria Executivo.")
    nota = documentos.conferir_soma_do_pessoal([_item("A Inspeção Escolar tem 400 servidores em atuação direta."), _item(frase)], FOLHA)
    assert nota == ("_Conferência por código: as 5 categorias que a secretaria lista acima somam 59.608; o Caderno de RH "
                    "(setembro de 2026) registra 61.343 vínculos ativos, diferença de 1.735. A lista pode não cobrir toda a "
                    "equipe, e as bases e as datas podem não ser as mesmas._")
    sem = lambda texto, folha=FOLHA, rotulo="informado pelo órgão": documentos.conferir_soma_do_pessoal([_item(texto, rotulo)], folha)
    # não aponta: categorias que são parte uma da outra; soma que fecha; soma longe do total (não é a equipe toda);
    # menos de três contagens; frase que não é da secretaria; sem folha
    assert sem("São 48.565 professores, dos quais 4.842 temporários, 5.065 administrativos e 612 técnicos.") == ""
    assert sem("São 50.000 professores, 6.343 servidores administrativos e 5.000 temporários.") == ""
    assert sem("São 1.200 professores, 300 servidores administrativos e 40 inspetores.") == ""
    assert sem("São 48.565 professores e 9.000 servidores administrativos.") == ""
    assert sem(frase, rotulo="confirmado em fonte oficial") == "" and sem(frase, folha=None) == ""
    # ano não é contagem
    assert sem("Em 2026 servidores somam 48.565 professores, 4.842 temporários e 5.065 servidores administrativos.") != ""
    md = documentos.markdown_capitulos({"secoes": [{"titulo": "Pessoal", "itens": [_item(frase)], "leitura": "",
                                                    "nao_se_sabe": ["Custo mensal da folha", "Total de terceirizados e de cedidos",
                                                                    "Número total de servidores"]}]}, None, None, FOLHA)
    assert md.index("48.565 professores") < md.index("_Conferência por código:") < md.index("## 6. Orçamento")
    # o que o quadro da folha já traz não aparece como "não se sabe"
    assert "_Não se sabe:_ Total de terceirizados e de cedidos." in md and "Custo mensal da folha" not in md


def test_capitulos_com_a_lei_e_nao_se_sabe_sem_o_que_o_app_tem(funcoes):
    from transicao import caderno, documentos
    lei = caderno.orcamento_na_lei("SEEDUC")
    dossie = funcoes.acrescentar_itens({"itens": []}, caderno.itens_da_lei(lei))
    atribuicoes = next(i["id"] for i in dossie["itens"] if i["afirmacao"].startswith("Atribuições de "))
    diag = {"secoes": [
        {"titulo": "O que faz", "leitura": "", "itens": [
            _item("A SEEDUC executa a política estadual de educação.", "confirmado em fonte oficial", atribuicoes),
            _item("A Inspeção Escolar acompanha 1.244 escolas da rede estadual.")],
         "nao_se_sabe": ["Lei de criação e regimento atualizado", "Número de matrículas em 2026"]},
        {"titulo": "Orçamento e execução", "leitura": "", "itens": [_item("Foram empenhados R$ 5.067.060.625,05.")],
         "nao_se_sabe": ["Valor da SEEDUC no PLOA 2027 (PL 8.378/26) em documento oficial", "Execução por fonte vinculada"]}],
        "organograma": [{"unidade": "Gabinete", "sigla": "", "subordinada_a": "", "titular": "", "rotulo": "informado pelo órgão"}]}
    md = documentos.markdown_capitulos(diag, None, None, FOLHA, "SEEDUC", dossie, lei)
    # 1. a LOA abre o capítulo, por código (com o ato de criação); o item do modelo sobre a mesma fonte não repete
    assert ("## 1. O que faz\n- Na LOA 2026: A Secretaria de Estado de Educação é órgão integrante da estrutura da "
            "Administração Direta do Poder Executivo do Estado, criada pelo Decreto Lei nº 1, de 15 de março de 1975") in md
    assert "_(fonte oficial ✔: LOA 2026, Volume II, p. 172)_" in md and "executa a política estadual de educação.\n" not in md
    assert "Lei de criação" not in md and "_Não se sabe:_ Número de matrículas em 2026." in md
    # 2. as unidades orçamentárias do órgão (o DEGASE aparece)
    assert ("- Unidades orçamentárias do órgão na LOA 2026 e no PLOA 2027: Secretaria de Estado de Educação; Departamento "
            "Geral de Ações Socio-Educativas; Conselho Estadual de Educação. _(fonte oficial ✔: LOA 2026, Volume II)_") in md
    # 6. o quadro da lei, por código, e o "não se sabe" do PLOA some
    for linha in ["**Orçamento na lei** (LOA 2026, Volume II e PLOA 2027, Volume II; fonte oficial ✔)",
                  "| Secretaria de Estado de Educação | R$ 6.702.485.057 | R$ 7.654.748.512 |",
                  "| Departamento Geral de Ações Socio-Educativas | R$ 479.889.772 | R$ 499.330.060 |",
                  "| **Total do órgão** | **R$ 7.182.384.829** | **R$ 8.154.088.572** |",
                  "_Não se sabe:_ Execução por fonte vinculada."]:
        assert linha in md, linha
    assert "no PLOA 2027 (PL 8.378/26)" not in md
    # sem a lei (sigla fora da tabela), nada muda no que o modelo disse
    sem = documentos.markdown_capitulos(diag, None, None, FOLHA, "X", dossie, None)
    assert "Lei de criação e regimento atualizado" in sem and "no PLOA 2027 (PL 8.378/26)" in sem and "Orçamento na lei" not in sem
    # as fontes: as bases lidas por código entram, sem códigos de item
    fontes = documentos.fontes_do_dossie(diag, dossie, FOLHA, lei)
    assert "- [Caderno de RH (SEPLAG), folha de setembro de 2026](https://www.rj.gov.br/gesperj/) · ✔ base oficial, lida por código" in fontes
    assert "- LOA 2026, Volume II · ✔ base oficial, lida por código" in fontes and "- PLOA 2027, Volume II ·" in fontes
    assert not re.search(r"\b[OE]\d+\b", fontes)


def test_mais_itens_nos_blocos_mais_densos(llm, funcoes):
    trecho = "Empenhado até 23/10/2026: R$ 398.750.000,00"
    itens = [{"texto": f"Afirmação {k}.", "origem": "relatorio", "item": "", "trecho": trecho} for k in range(1, 11)]
    llm.diagnostico_orgao = {"secoes": [{"titulo": t, "itens": itens} for t in
                                        ("Programas e ações", "Contratos", "Pendências com controle e justiça", "Pessoal")]}
    diag = funcoes.extrair_diagnostico("m", {"itens": []}, RELATORIO, "Secretaria de Exemplo")
    quantos = {s["titulo"]: len(s["itens"]) for s in diag["secoes"]}
    assert quantos["Programas e ações"] == quantos["Contratos"] == quantos["Pendências com controle e justiça"] == 8
    assert quantos["Pessoal"] == 6
    pedido = funcoes.PROMPT_DIAGNOSTICO_ORGAO
    for trecho_do_pedido in ['até 8 em "Programas e ações", "Contratos" e "Pendências com controle e justiça"',
                             "de que tamanho é", "Primeiro os que dão a ESCALA da secretaria",
                             'NÃO é "não se sabe"', 'registre o que o DOSSIÊ traz\nde inquérito, operação, auditoria']:
        assert trecho_do_pedido in pedido, trecho_do_pedido
    assert "venceram nos últimos 90 dias" in funcoes.PROMPT_CONTRATOS and "vencido há pouco" in funcoes.MOTIVOS_CONTRATO


def test_rodada_gera_o_dossie_com_a_lei_e_sem_cara_de_relatorio_de_riscos(llm):
    import docx
    from transicao import analise
    r = analise.analisar_orgao("SEEDUC", RELATORIO, CFG)
    md = r["dossie_md"]
    # a LOA e o PLOA entram como fatos do dossiê (o diagnóstico e os riscos os veem) e como quadro, por código
    itens = r["registro"]["dossie"]["itens"]
    assert any(i["afirmacao"].startswith("No PLOA 2027, a proposta para Secretaria de Estado de Educação") and
               i["tipo_fonte"] == "documento_oficial" and i["checagem"] == "conferido" for i in itens)
    assert r["registro"]["orcamento_na_lei"]["total_ploa"] == 8154088572
    assert "| Secretaria de Estado de Educação | R$ 6.702.485.057 | R$ 7.654.748.512 |" in md
    assert "| Dotação inicial na LOA 2026 | R$ 6.702.485.057 (órgão, com as outras unidades: R$ 7.182.384.829) |" in md
    assert "(Caderno de RH da SEPLAG, LOA 2026 e PLOA 2027)" in md.split("\n")[1]
    # o dossiê não fala de riscos nem de agentes, não corta nomes e não tem "(s)"
    for fora in ("Confiança", "Analisa riscos", "agentes de IA", "(s)", "…", "os ids são", "(informado pelo órgão)"):
        assert fora not in md, fora
    assert "| Contrato 99/2026 | Empresa X | Manutenção predial | R$ 398.750.000,00 | 15/12/2026 |" in md
    assert "- **Contrato 99/2026 (Empresa X):** vence em breve, valor alto. Vence antes da posse." in md
    assert md.rstrip().endswith("Método e conferências no arquivo de auditoria._")
    assert "; Caderno de RH da SEPLAG, LOA 2026 e PLOA 2027 entram por código, das bases oficiais." in md
    textos = [p.text for p in docx.Document(io.BytesIO(r["dossie_docx"])).paragraphs]
    assert "Antes de ler" in textos and "6. Orçamento" in textos
    # secretaria fora da tabela: o dossiê sai como antes, sem o quadro da lei
    outro = analise.analisar_orgao("Secretaria de Exemplo", RELATORIO, CFG)["dossie_md"]
    assert "Orçamento na lei" not in outro and "PLOA 2027" not in outro.split("\n")[1]


def test_corte_minimo_nao_vira_cerca_de_zero_por_cento(funcoes):
    texto = "Relatório da secretaria com texto corrido. " * 40
    _, avisos = funcoes.limpar_relatorio(texto, limite=len(texto.strip()) - 5)
    corte = next(a for a in avisos if "foi cortado" in a)
    assert "(menos de 1%)" in corte and "cerca de 0%" not in corte
    _, avisos = funcoes.limpar_relatorio(texto, limite=len(texto) // 2)
    assert "(cerca de 4" in next(a for a in avisos if "foi cortado" in a) or "(cerca de 5" in next(a for a in avisos if "foi cortado" in a)
    # no dossiê, todo o material lido em parte cabe numa linha
    md = funcoes.antes_de_ler_dossie("10/11/2026", ["A.pdf (lidos 266 mil de 435 mil caracteres)", "B.xlsx (lidos 133 mil de 12,3 milhões caracteres)"])
    assert md.count("Material lido em parte") == 1 and "A.pdf (lidos 266 mil de 435 mil caracteres); B.xlsx" in md
    assert "imprensa" not in md and "Confiança" not in md
