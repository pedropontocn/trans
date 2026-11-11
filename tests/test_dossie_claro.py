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


def test_contratos_em_lista_sem_corte(funcoes):
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
    # um item por contrato, sempre na mesma ordem: contrato e contratado, valor, vigência; objeto, destaque, situação
    assert md.split("\n")[0] == (
        "- **Contrato Emergencial PED nº 09/2026 – Centro de Desenvolvimento Pessoal - CDP** · R$158.997.240,00 · até "
        "11/06/2027. Profissionais de apoio escolar para estudantes da Educação Especial e com TEA. Emergencial, serviço "
        "essencial, valor alto. É um contrato emergencial com saldo informado de R$47.699.172,00; a licitação regular está "
        "em ajustes.")
    assert md.split("\n")[1] == ("- **TAC 08/2026 – AGILE CORP SERVIÇOS ESPECIALIZADOS LTDA** · R$ 14.196.481,17 · vigência não "
                                 "informada. Serviços de limpeza da rede estadual por Termo de Ajuste de Contas. Serviço essencial.")
    assert "…" not in md and "|" not in md                                  # nada cortado; a caixa é a do material; sem tabela
    assert md.endswith("_Todos informados pela secretaria. As datas de todos os contratos informados estão no calendário (Excel)._")
    # mais contratos do que cabem: a nota diz quantos, sem "(s)"
    muitos = [c(contrato=f"Contrato {k}/2026", contratado=f"Empresa {k}", objeto="x", valor=f"R$ {k}.000,00", vigencia="")
              for k in range(1, 15)]
    md = documentos.markdown_contratos_criticos(muitos)
    assert "Os 10 mais críticos dos 14 que a leitura do material destacou." in md and "(s)" not in md
    assert md.count("\n- **Contrato ") == 9
    # o contrato que não veio da secretaria (dado antigo) traz a base
    outro = documentos.markdown_contratos_criticos([c(contrato="Contrato 1/2026", contratado="A", objeto="Limpeza", valor="R$ 1,0 mi",
                                                      vigencia="01/12/2026", rotulo="dado do SIGA/PNCP")])
    assert "Todos informados pela secretaria" not in outro and outro.split("\n")[0].endswith(")_")


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
    assert md.index("48.565 professores") < md.index("_Conferência por código:") < md.index("## c) Contratos")
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
    assert ("## 2. Funcionamento atual\n- Na LOA 2026: A Secretaria de Estado de Educação é órgão integrante da estrutura da "
            "Administração Direta do Poder Executivo do Estado, criada pelo Decreto Lei nº 1, de 15 de março de 1975") in md
    assert "_(fonte oficial ✔: LOA 2026, Volume II, p. 172)_" in md and "executa a política estadual de educação.\n" not in md
    assert "Lei de criação" not in md and "_Não se sabe:_ Número de matrículas em 2026." in md
    # 2. as unidades orçamentárias do órgão (o DEGASE aparece)
    assert ("- Unidades orçamentárias do órgão na LOA 2026 e no PLOA 2027: Secretaria de Estado de Educação; Departamento "
            "Geral de Ações Socio-Educativas; Conselho Estadual de Educação. _(fonte oficial ✔: LOA 2026, Volume II)_") in md
    # 6. o quadro da lei, por código, e o "não se sabe" do PLOA some
    for linha in ["**Orçamento na lei, por unidade orçamentária** (LOA 2026, Volume II e PLOA 2027, Volume II; fonte oficial ✔)",
                  "| Secretaria de Estado de Educação | R$ 6.702.485.057 | R$ 7.654.748.512 | +R$ 952.263.455 (+14,2%) |",
                  "| Departamento Geral de Ações Socio-Educativas | R$ 479.889.772 | R$ 499.330.060 | +R$ 19.440.288 (+4,1%) |",
                  "| Conselho Estadual de Educação | R$ 10.000 | R$ 10.000 | sem variação |",
                  "| **Total do órgão** | **R$ 7.182.384.829** | **R$ 8.154.088.572** | **+R$ 971.703.743 (+13,5%)** |",
                  "_Não se sabe:_ Execução por fonte vinculada."]:
        assert linha in md, linha
    assert "no PLOA 2027 (PL 8.378/26)" not in md
    # sem a lei (sigla fora da tabela), nada muda no que o modelo disse
    sem = documentos.markdown_capitulos(diag, None, None, FOLHA, "X", dossie, None)
    assert "Lei de criação e regimento atualizado" in sem and "no PLOA 2027 (PL 8.378/26)" in sem and "Orçamento na lei" not in sem
    assert "plano de governo" not in md and "## 3." not in md and "## g)" not in md   # sem cruzamento e sem leitura, não aparecem
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
    for trecho_do_pedido in ['até 8 em "Programas e ações", "Contratos", "Pendências com controle e justiça" e',
                             "- Funcionamento das unidades: como cada subsecretaria ou unidade principal atua",
                             "- Dificuldades e problemas: os entraves que a própria secretaria aponta",
                             "cargos existentes, ocupados e vagos", "execução por ação orçamentária em 2025 e 2026",
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
    assert "| Secretaria de Estado de Educação | R$ 6.702.485.057 | R$ 7.654.748.512 | +R$ 952.263.455 (+14,2%) |" in md
    assert "| Dotação inicial na LOA 2026 | R$ 6.702.485.057 (órgão, com as outras unidades: R$ 7.182.384.829) |" in md
    assert "(Caderno de RH da SEPLAG, LOA 2026 e PLOA 2027)" in md.split("\n")[0]
    # o dossiê não fala de riscos nem de agentes, não corta nomes e não tem "(s)"
    for fora in ("Confiança", "Analisa riscos", "agentes de IA", "(s)", "…", "os ids são", "(informado pelo órgão)"):
        assert fora not in md, fora
    assert ("- **Contrato 99/2026 – Empresa X** · R$ 398.750.000,00 · até 15/12/2026. Manutenção predial. Vence em breve, "
            "valor alto. Vence antes da posse.") in md
    assert md.rstrip().endswith("Método e conferências no arquivo de auditoria._")
    assert "; Caderno de RH da SEPLAG, LOA 2026 e PLOA 2027 entram por código, das bases oficiais." in md
    textos = [p.text for p in docx.Document(io.BytesIO(r["dossie_docx"])).paragraphs]
    assert "Antes de ler" not in textos and "Panorama" in textos and "a) Planejamento e execução orçamentária" in textos
    assert sum(len(p) for p in md.split("## Panorama")[0].split("\n")) < 520        # o preâmbulo cabe em poucas linhas
    # secretaria fora da tabela: o dossiê sai como antes, sem o quadro da lei
    outro = analise.analisar_orgao("Secretaria de Exemplo", RELATORIO, CFG)["dossie_md"]
    assert "Orçamento na lei" not in outro and "PLOA 2027" not in outro.split("\n")[0]


def test_corte_minimo_nao_vira_cerca_de_zero_por_cento(funcoes):
    texto = "Relatório da secretaria com texto corrido. " * 40
    _, avisos = funcoes.limpar_relatorio(texto, limite=len(texto.strip()) - 5)
    corte = next(a for a in avisos if "foi cortado" in a)
    assert "(menos de 1%)" in corte and "cerca de 0%" not in corte
    _, avisos = funcoes.limpar_relatorio(texto, limite=len(texto) // 2)
    assert "(cerca de 4" in next(a for a in avisos if "foi cortado" in a) or "(cerca de 5" in next(a for a in avisos if "foi cortado" in a)
    # no dossiê, todo o material lido em parte cabe numa linha
    md = funcoes.antes_de_ler_dossie("10/11/2026", ["A.pdf (lidos 266 mil de 435 mil caracteres)", "B.xlsx (lidos 133 mil de 12,3 milhões de caracteres)"])
    assert md.count("Material lido em parte") == 1 and "A.pdf (lidos 266 mil de 435 mil caracteres); B.xlsx" in md
    assert "imprensa" not in md and "Confiança" not in md and "##" not in md and "\n- " not in md
    assert funcoes.cortes_de_leitura({"cortados": [{"arquivo": "B.xlsx", "caracteres": 12337906, "usados": 133000}]}) == [
        "B.xlsx (lidos 133 mil de 12,3 milhões de caracteres)"]
    com = funcoes.antes_de_ler_dossie("10/11/2026", None, ["LOA 2026"], imprensa=True)
    assert '"fonte oficial ✔" ou "imprensa ✔" (só nas pendências). Contratos: só os que a secretaria informou._' in com
    assert "(LOA 2026)" in com and "Material lido em parte" not in com


def test_nota_em_italico_no_word_mesmo_com_sublinhado_no_nome_do_arquivo(funcoes):
    import docx
    md = ("_Material lido em parte: SEEDUC_Transicao_Modelo_2026.xlsx (lidos 133 mil de 12,3 milhões de caracteres)._\n\n"
          "_Não se sabe:_ Organograma atualizado.\n\n_uma nota_ e depois _outra nota_\n\nTexto comum.")
    pars = [p for p in docx.Document(io.BytesIO(funcoes.gerar_docx(md, {"orgao": "x", "assunto": "y", "tipo": "z", "data": "w"}))).paragraphs]
    nota = next(p for p in pars if p.text.startswith("Material lido em parte"))
    assert nota.text.endswith("caracteres).") and "SEEDUC_Transicao_Modelo_2026.xlsx" in nota.text    # sem "_" nas pontas
    assert all(r.italic for r in nota.runs)
    comum = next(p for p in pars if p.text == "Texto comum.")
    assert not any(r.italic for r in comum.runs)
    # parágrafo que só começa e termina com trechos em itálico não é uma nota inteira
    assert any(p.text == "uma nota e depois outra nota" for p in pars)
    assert any(p.text == "Não se sabe: Organograma atualizado." for p in pars)


def test_orcamento_por_unidade_em_detalhe(funcoes):
    from transicao import caderno, documentos
    lei = caderno.orcamento_na_lei("SEEDUC")
    seeduc, degase, cee = lei["unidades"]
    # as ações de cada unidade fecham com o total da unidade nas duas leis
    for u in (seeduc, degase, cee):
        assert sum(a["loa"] or 0 for a in u["acoes"]) == u["loa"] and sum(a["ploa"] or 0 for a in u["acoes"]) == u["ploa"]
    # a ação que muda de subfunção de uma lei para a outra é a mesma ação (não "extinta" e "nova")
    rede = [a for a in seeduc["acoes"] if a["acao"] == "1546"]
    assert len(rede) == 1 and (rede[0]["loa"], rede[0]["ploa"]) == (334689368, 173027800)
    md = documentos._quadro_da_lei(lei)
    for linha in [
        "**Secretaria de Estado de Educação** (unidade orçamentária 18010): LOA 2026 R$ 6.702.485.057; PLOA 2027 "
        "R$ 7.654.748.512; variação +R$ 952.263.455 (+14,2%). No PLOA 2027, os programas de gestão administrativa e "
        "encargos somam R$ 6.329.757.820 (82,7%) e as ações finalísticas, R$ 1.324.990.692 (17,3%).",
        "| Ação (como está na lei) | LOA 2026 | PLOA 2027 | Variação |",
        "| 4968 – Remun. profis. em ef. ex. - Ens Med - 1070 (gestão) | – | R$ 2.841.492.907 | nova no PLOA 2027 |",
        "| 2660 – Pessoal e Encargos Sociais (gestão) | R$ 462.217.963 | R$ 211.944.071 | −R$ 250.273.892 (−54,1%) |",
        "**Departamento Geral de Ações Socio-Educativas** (unidade orçamentária 18020): LOA 2026 R$ 479.889.772; PLOA 2027 "
        "R$ 499.330.060; variação +R$ 19.440.288 (+4,1%).",
        "| 2660 – Pessoal e Encargos Sociais (gestão) | R$ 310.255.159 | R$ 361.244.971 | +R$ 50.989.812 (+16,4%) |"]:
        assert linha in md, linha
    assert "não está no PLOA 2027" not in md.split("**Departamento")[0]          # nenhuma das maiores sumiu de verdade
    # o resto das ações vai somado, e a soma da tabela é o total da unidade
    bloco = md.split("**Secretaria de Estado de Educação** (unidade")[1].split("**Departamento")[0]
    valores = lambda col: [int(l.split("|")[col].replace("R$", "").replace(".", "").strip() or 0)
                           for l in bloco.split("\n") if l.startswith("| ") and "Ação (como" not in l and "–  " not in l
                           and l.split("|")[col].strip() != "–"]
    assert sum(valores(3)) == 7654748512 and sum(valores(2)) == 6702485057
    assert re.search(r"\| Outras \d+ ações \| R\$ [\d.]+ \| R\$ [\d.]+ \|", bloco)
    # unidade residual (R$ 10 mil) fica só na tabela dos totais
    assert "**Conselho Estadual de Educação** (unidade" not in md
    assert documentos._variacao(100, 150) == "+R$ 50 (+50,0%)" and documentos._variacao(200, 150) == "−R$ 50 (−25,0%)"
    assert documentos._variacao(None, 5) == "–" and documentos._variacao(5, 5) == "sem variação"
    # no Word, as tabelas por unidade saem inteiras
    import docx
    doc = docx.Document(io.BytesIO(funcoes.gerar_docx("## 6. Orçamento\n" + md, {"orgao": "x", "assunto": "y", "tipo": "z", "data": "w"})))
    assert len(doc.tables) == 3


def test_cruzamento_com_o_plano_de_governo_conferido_por_codigo(llm, funcoes):
    from transicao import caderno, documentos
    lei = caderno.orcamento_na_lei("SEEDUC")
    plano = {t["id"]: t for t in caderno.plano()["trechos"]}
    cita = lambda k, n=10: " ".join(plano[k]["texto"].replace("\x07", " ").split()[:n])
    fatos = [{"id": "F13", "texto": "Foram ofertadas 193.026.460 refeições até a data-base."},
             {"id": "V4", "texto": "ARP de absorventes, R$ 1.374.895,36 (Fim da requisição), em 28/10/2026"}]
    llm.cruzamento_plano = {"compromissos": [
        {"trecho_id": "P24.9", "citacao": cita("P24.9"), "fatos": ["V4", "F999"], "acoes": []},
        {"trecho_id": "P22.9", "citacao": cita("P22.9"), "fatos": ["F13"],
         "acoes": ["18010:12.306.0443.2421", "18010:12.122.0002.2660", "99999:inventada"]},
        {"trecho_id": "P22.4", "citacao": cita("P22.4"), "fatos": [], "acoes": []},
        {"trecho_id": "P22.5", "citacao": "reforço escolar para todos os alunos da rede", "fatos": [], "acoes": []},   # não é literal
        {"trecho_id": "P22.9", "citacao": cita("P22.9"), "fatos": [], "acoes": []},                                     # repetido
        {"trecho_id": "P999.1", "citacao": "x", "fatos": [], "acoes": []},                                              # não existe
        {"trecho_id": next(k for k, t in plano.items() if t["tipo"] != "compromisso"), "citacao": "x"}]}               # não é compromisso
    uso = []
    c = caderno.cruzar_plano(CFG["modelo_auxiliar"], "SEEDUC – Secretaria de Estado de Educação", lei, fatos, uso)
    assert [x["id"] for x in c["compromissos"]] == ["P22.4", "P22.9", "P24.9"]            # na ordem do plano
    assert [r["trecho_id"] for r in c["recusados"]] == ["P22.5"] and c["no_plano"] == 170
    merenda = c["compromissos"][1]
    assert [f["id"] for f in merenda["fatos"]] == ["F13"]
    assert [a["chave"] for a in merenda["acoes"]] == ["18010:12.306.0443.2421"]           # ação de gestão e inventada caem
    assert [f["id"] for f in c["compromissos"][2]["fatos"]] == ["V4"]                     # fato que não existe cai
    assert uso and uso[0]["etapa"] == "dossiê: cruzamento com o plano de governo"
    # o pedido leva os compromissos, os fatos com id e só as ações finalísticas
    assert '"id": "P22.4"' in llm.pedido_plano and '"id": "V4"' in llm.pedido_plano and "Oferta de Nutrição Escolar" in llm.pedido_plano
    assert "Pessoal e Encargos Sociais" not in llm.pedido_plano and "\\u0007" not in llm.pedido_plano
    # no documento, compacto: quem tem correspondência numa linha; os sem correspondência juntos
    md = documentos.markdown_plano(c)
    for linha in [
        "**Para 2027: o que o plano de governo prevê para a área**",
        "_3 compromissos do Plano de Governo 2027–2030 (Plano do Rio Real) tratam da área da secretaria.",
        "- **Estrutura digna e escola aberta** (p. 22). Hoje, no material: Foram ofertadas 193.026.460 refeições até a "
        "data-base. No orçamento: ação 2421, Oferta de Nutrição Escolar, PLOA 2027 R$ 396.962.081 (LOA 2026 R$ 251.981.179).",
        "- **Escola Para Elas** (p. 24). Hoje, no material: ARP de absorventes, R$ 1.374.895,36 (Fim da requisição), em 28/10/2026.",
        "- **Sem correspondência apontada nos fatos levantados do material nem no orçamento (1):** Alfabetização na idade "
        "certa em regime de colaboração com os municípios (p. 22)."]:
        assert linha in md, linha
    assert "\x07" not in md and "(s)" not in md and "…" not in md and len(md.split("\n")) == 5
    assert documentos._nome_do_compromisso("Vem Pra Aula: alerta precoce de evasão pela frequência.") == "Vem Pra Aula"
    # nenhum compromisso apontado: o capítulo diz isso; sem a base do plano: nada
    llm.cruzamento_plano = {"compromissos": []}
    vazio = caderno.cruzar_plano(CFG["modelo_auxiliar"], "X", None, [], [])
    assert "nenhum que trate diretamente da área da secretaria" in documentos.markdown_plano(vazio)
    assert documentos.markdown_plano(None) == ""
    fontes = documentos.fontes_do_dossie({}, {}, None, None, c)
    assert "- Plano de Governo 2027–2030 (Plano do Rio Real) · compromisso de governo, lido da base embutida" in fontes


def test_rodada_do_dossie_cruza_o_plano_e_so_no_dossie(llm):
    from transicao import analise, caderno
    plano = {t["id"]: t for t in caderno.plano()["trechos"]}
    llm.cruzamento_plano = {"compromissos": [{"trecho_id": "P22.9", "citacao": " ".join(plano["P22.9"]["texto"].replace("\x07", " ").split()[:8]),
                                              "fatos": ["F2", "V1"], "acoes": ["18010:12.306.0443.2421"]}]}
    r = analise.analisar_orgao("SEEDUC", RELATORIO, CFG)
    md = r["dossie_md"]
    orcamento = md.split("## a) Planejamento e execução orçamentária")[1].split("## b) Cargos")[0]
    assert "**Para 2027: o que o plano de governo prevê para a área**" in orcamento and "- **Estrutura digna e escola aberta** (p. 22)." in orcamento
    assert "ação 2421, Oferta de Nutrição Escolar" in md and "Plano de Governo 2027–2030 (Plano do Rio Real) ·" in md
    assert r["registro"]["cruzamento_plano"]["compromissos"][0]["id"] == "P22.9"
    assert any(u["etapa"] == "dossiê: cruzamento com o plano de governo" for u in r["registro"]["uso_tokens"])
    # os fatos do pedido: os do diagnóstico e os do calendário da secretaria
    assert '"id": "F2"' in llm.pedido_plano and '"id": "V1"' in llm.pedido_plano
    assert "Plano de governo" not in r["riscos_md"]
    # sem o dossiê entre os produtos, o cruzamento não roda
    antes = sum("Você cruza o Plano de Governo" in str(c["mensagens"][0]["content"]) for c in llm.chamadas)
    r = analise.analisar_orgao("SEEDUC", RELATORIO, dict(CFG, produtos=["riscos"]))
    assert sum("Você cruza o Plano de Governo" in str(c["mensagens"][0]["content"]) for c in llm.chamadas) == antes
    assert r["registro"]["cruzamento_plano"] is None
