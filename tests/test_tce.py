"""Cruzamento com os dados abertos do TCE-RJ: só multas e débitos (decisões do Tribunal), por código. A API é falsa
nos testes; as linhas têm o formato real de penalidades_ressarcimento_estado."""
import pytest

from test_analise import CFG, RELATORIO


def _linha(processo, condenacao, orgao, ano=2024, valor=3000.0, natureza="TOMADA DE CONTAS", ente="ESTADUAL"):
    return {"Processo": processo, "AnoCondenacao": ano, "ValorPenalidade": valor, "Condenacao": condenacao,
            "NomeOrgao": orgao, "TipoEnte": ente, "GrupoNatureza": natureza, "DataSessao": f"{ano}-04-01T00:00:00",
            "DataUltimaAtualizacao": "2026-11-10T18:51:28.927000"}


MULTAS = [
    _linha("100144-5/2022", "124/2024-0", "SEC EST EDUCACAO", natureza="RELATÓRIO DE AUDITORIA GOVERNAMENTAL"),
    _linha("100144-5/2022", "125/2024-0", "SEC EST EDUCACAO", natureza="RELATÓRIO DE AUDITORIA GOVERNAMENTAL"),
    _linha("100218-7/2016", "1077/2019-0", "SEC EST EDUCACAO", ano=2019, natureza="CONTRATO"),          # antiga
    _linha("100036-1/2018", "255/2025-1", "SEC EST SAÚDE", ano=2025),                                    # outra secretaria
    _linha("200001-1/2023", "10/2025-0", "PREFEITURA DE EXEMPLO", ano=2025, ente="MUNICIPAL"),
    _linha("100500-2/2023", "300/2025-0", "DEGASE-DEPART GERAL ACOES SOCIO-EDUCATIV", ano=2025, natureza="CONTRATO"),
]
DEBITOS = [   # a mesma condenação (258/2024) em uma linha por responsável: é UMA condenação, e o valor não se soma
    _linha("100372-5/2019", "258/2024-2", "SEC EST EDUCACAO", valor=160481.68),
    _linha("100372-5/2019", "258/2024-3", "SEC EST EDUCACAO", valor=160481.68),
    _linha("100372-5/2019", "258/2024-4", "SEC EST EDUCACAO", valor=160481.68),
    _linha("100372-5/2019", "259/2024-1", "SEC EST EDUCACAO", valor=173874.33),
    _linha("100036-1/2018", "253/2022-1", "SEC EST SAÚDE", ano=2022, valor=194161.27),
]


@pytest.fixture
def tce(monkeypatch, tmp_path):
    from transicao import tce
    monkeypatch.delenv("TCE_DESLIGADO", raising=False)
    monkeypatch.setenv("PASTA_REGISTROS", str(tmp_path / "registros"))
    tce._MEMORIA.clear()
    tce._FALHAS.clear()
    tce.pedidos = []

    def baixar(caminho, params):
        tce.pedidos.append((caminho, dict(params)))
        return MULTAS if params["tipo"] == "multa" else DEBITOS
    monkeypatch.setattr(tce, "_baixar_json", baixar)
    yield tce
    tce._MEMORIA.clear()
    tce._FALHAS.clear()


def test_nomes_do_tce_casam_com_a_secretaria_e_as_vinculadas(tce):
    seeduc = tce.alvos_da_secretaria("SEEDUC")
    assert tce.da_secretaria("SEC EST EDUCACAO", seeduc) == "secretaria"
    assert tce.da_secretaria("DEGASE-DEPART GERAL ACOES SOCIO-EDUCATIV", seeduc) == "vinculada"
    for outro in ["SEC EST SAÚDE", "FES - FUNDO ESTADUAL SAUDE", "SEC EST ADMINISTRACAO PENITENCIARIA",
                  "FAETEC-FUNDACAO APOIO ESCOLA TECNICA", "SEEDUCACAO QUALQUER", ""]:
        assert tce.da_secretaria(outro, seeduc) == "", outro
    seiop = tce.alvos_da_secretaria("SEIOP")
    assert tce.da_secretaria("SEC EST INFRA E OBRAS PÚBLICAS", seiop) == "secretaria"
    assert tce.da_secretaria("SEC EST INFRAESTRUTURA E OBRAS (EXTINTA)", seiop) == "antecessora (extinta)"
    assert tce.da_secretaria("EMOP-EMPRESA DE OBRAS PUBLICAS DO ERJ", seiop) == "vinculada"
    assert tce.da_secretaria("DER-RJ FUND DEPART ESTRADAS DE RODAGEM", seiop) == "vinculada"
    assert tce.da_secretaria("SEC EST CIDADES (EXTINTA)", seiop) == ""
    ses = tce.alvos_da_secretaria("SES")
    assert tce.da_secretaria("FES - FUNDO ESTADUAL SAUDE", ses) == "vinculada"
    assert tce.da_secretaria("SEC EST EDUCACAO", ses) == ""


def test_cruzamento_conta_condenacoes_e_diz_o_que_a_secretaria_citou(tce):
    material = "O processo TCE-RJ nº 100.144-5/2022 trata da auditoria da merenda. Nada mais consta."
    c = tce.cruzar("SEEDUC", material, "10/11/2026")
    assert c["unidades"] == {"SEC EST EDUCACAO": "secretaria", "DEGASE-DEPART GERAL ACOES SOCIO-EDUCATIV": "vinculada"}
    assert not c["erros"] and len(c["penalidades"]) == 8                  # sem a Saúde e sem o município
    r = c["resumo"]
    assert r["desde"] == 2024                                              # o ano de corte e os dois anteriores
    assert (r["multas"], r["debitos"], r["processos"]) == (4, 2, 4)        # 258/2024 em três linhas é uma condenação
    assert (r["multas_recentes"], r["debitos_recentes"], r["processos_recentes"]) == (3, 2, 3)   # sem a de 2019
    assert r["processos_citados"] == 1 and r["processos_recentes_nao_citados"] == 2
    citados = {p["processo"] for p in c["penalidades"] if p["citado"]}
    assert citados == {"100144-5/2022"}                                    # achado com outra pontuação no material
    # os conjuntos são baixados uma vez por dia: a segunda secretaria não chama a API de novo
    tce.cruzar("SES", "", "10/11/2026")
    assert tce.pedidos == [("penalidades_ressarcimento_estado", {"tipo": "multa"}),
                           ("penalidades_ressarcimento_estado", {"tipo": "debito"})]


def test_fatos_pauta_e_secao_do_relatorio_sem_valor(tce):
    c = tce.cruzar("SEEDUC", "Processo 100144-5/2022.", "10/11/2026")
    fatos = tce.fatos(c)
    assert [f["id"] for f in fatos] == ["T1", "T2", "T3"]
    assert all(f["rotulo"] == "confirmado em fonte oficial" and f["url"].startswith("https://dados.tcerj.tc.br") for f in fatos)
    assert fatos[0]["texto"].startswith("De 2024 para cá, os dados abertos do TCE-RJ registram 3 condenações em multa e "
                                        "2 condenações em débito, em 3 processos do órgão e das vinculadas (consulta em ")
    assert fatos[1]["texto"] == ("2 desses processos do TCE-RJ não aparecem no material enviado pela secretaria: "
                                 "100372-5/2019, 100500-2/2023.")
    assert fatos[2]["texto"] == ("Processo TCE-RJ 100372-5/2019 (SEC EST EDUCACAO): 2 condenações em débito, sessão de "
                                 "01/04/2024, em tomada de contas. O processo não aparece no material da secretaria.")
    pauta = tce.para_a_pauta(c)
    assert len(pauta) == 1 and pauta[0]["apontado_por"] == ["Cruzamento com o TCE-RJ"]
    assert pauta[0]["o_que"] == ("Situação de 2 processos do TCE-RJ com multa ou débito de 2024 para cá que não aparecem "
                                 "no material (100372-5/2019, 100500-2/2023)")
    md = tce.markdown(c)
    assert "## Cruzamento com o TCE-RJ: multas e débitos" in md
    assert ("- **De 2024 para cá:** 3 condenações em multa e 2 condenações em débito, em 3 processos; 2 não aparecem "
            "no material.") in md
    assert "- **Ao todo na base:** 4 condenações em multa e 2 condenações em débito, em 4 processos." in md
    assert "| 100372-5/2019 | SEC EST EDUCACAO | 01/04/2024 | – | 2 | Tomada de contas | não |" in md
    assert "| 100144-5/2022 | SEC EST EDUCACAO | 01/04/2024 | 2 | – | Relatório de auditoria governamental | sim |" in md
    assert "100218-7/2016" not in md                                       # a de 2019 só conta no total
    # valor não entra em lugar nenhum: a base não diz a unidade e repete o débito por responsável
    tudo = md + " ".join(f["texto"] for f in fatos) + pauta[0]["o_que"]
    assert "R$" not in tudo.replace("(R$ ou UFIR-RJ)", "") and "160" not in tudo and "481" not in tudo and "(s)" not in tudo
    assert c["penalidades"][0]["valor_publicado"] is not None              # fica no registro de auditoria


def test_um_so_processo_e_tudo_citado(tce, monkeypatch):
    monkeypatch.setattr(tce, "_baixar_json", lambda caminho, params: MULTAS[:1] if params["tipo"] == "multa" else [])
    c = tce.cruzar("SEEDUC", "sem número de processo", "10/11/2026")
    fatos = tce.fatos(c)
    assert fatos[0]["texto"].startswith("De 2024 para cá, os dados abertos do TCE-RJ registram 1 condenação em multa, em "
                                        "1 processo do órgão")
    assert fatos[1]["texto"] == "O processo TCE-RJ 100144-5/2022 não aparece no material enviado pela secretaria."
    assert tce.para_a_pauta(c)[0]["o_que"].startswith("Situação do processo do TCE-RJ 100144-5/2022, com multa ou débito")
    assert "em 1 processo; 1 não aparece no material." in tce.markdown(c)
    tce._MEMORIA.clear()
    c = tce.cruzar("SEEDUC", "Ver o processo 100144-5/2022.", "10/11/2026")
    assert len(tce.fatos(c)) == 1 and tce.para_a_pauta(c) == [] and "todos aparecem no material." in tce.markdown(c)


def test_sem_condenacao_e_sem_acesso(tce, monkeypatch, tmp_path):
    c = tce.cruzar("SETUR", "", "10/11/2026")
    assert c["resumo"]["condenacoes"] == 0 and tce.fatos(c) == [] and tce.para_a_pauta(c) == []
    assert "Nenhuma multa ou débito em processos do órgão" in tce.markdown(c)
    # API fora do ar (e sem a cópia do dia em disco): nada quebra, nada vira fato, e o relatório diz que não cruzou
    tce._MEMORIA.clear()
    monkeypatch.setenv("PASTA_REGISTROS", str(tmp_path / "outra"))

    def fora(caminho, params):
        tce.pedidos.append("falha")
        raise OSError("timed out")
    monkeypatch.setattr(tce, "_baixar_json", fora)
    c = tce.cruzar("SEEDUC", "", "10/11/2026")
    assert len(c["erros"]) == 2 and c["penalidades"] == [] and tce.fatos(c) == [] and tce.para_a_pauta(c) == []
    assert "O cruzamento com os dados abertos do TCE-RJ não foi feito nesta rodada: multas: OSError: timed out" in tce.markdown(c)
    # a falha não vale pelo dia inteiro, mas também não é tentada de novo a cada secretaria
    antes = len(tce.pedidos)
    tce.cruzar("SES", "", "10/11/2026")
    assert len(tce.pedidos) == antes
    tce._FALHAS.clear()
    monkeypatch.setattr(tce, "_baixar_json", lambda caminho, params: MULTAS if params["tipo"] == "multa" else DEBITOS)
    assert tce.cruzar("SEEDUC", "", "10/11/2026")["resumo"]["condenacoes"] == 6
    assert tce.markdown(None) == "" and tce.fatos(None) == [] and tce.para_a_pauta(None) == []


def test_so_um_conjunto_fora_do_ar_avisa_que_a_contagem_esta_incompleta(tce, monkeypatch):
    def metade(caminho, params):
        if params["tipo"] == "debito":
            raise OSError("timed out")
        return MULTAS
    monkeypatch.setattr(tce, "_baixar_json", metade)
    md = tce.markdown(tce.cruzar("SEEDUC", "", "10/11/2026"))
    assert "- **Contagem incompleta:** parte da base não pôde ser consultada nesta rodada (debitos: OSError: timed out)." in md
    assert "3 condenações em multa, em 2 processos" in md


def test_entidade_abreviada_e_nome_antigo_sem_ligacao_confirmada(tce, monkeypatch):
    # o TCE abrevia demais ("PRODERJ - CENTRO TECN DA INF E COMUNI RJ"): a tabela conferida liga pelo código da LOA
    assert tce.da_secretaria("PRODERJ - CENTRO TECN DA INF E COMUNI RJ", tce.alvos_da_secretaria("SETD")) == "vinculada"
    assert tce.da_secretaria("UERJ-FUND UNIVERSIDADE DO ESTADO RJ", tce.alvos_da_secretaria("SECTI")) == "vinculada"
    assert tce.da_secretaria("PRODERJ - CENTRO TECN DA INF E COMUNI RJ", tce.alvos_da_secretaria("SEEDUC")) == ""
    assert tce.da_secretaria("SEC EST TRABALHO E RENDA (EXTINTA)", tce.alvos_da_secretaria("SETRAB")) == "antecessora (extinta)"
    # "SEC EST INFRAESTRUTURA E CIDADES" pode ser antecessora da SEIOP e da SECID: não entra na contagem de nenhuma,
    # e o relatório das duas diz que ficou de fora, com os processos
    linhas = [_linha("300001-1/2021", "50/2025-0", "SEC EST INFRAESTRUTURA E CIDADES", ano=2025),
              _linha("300002-2/2021", "51/2025-0", "SEC EST INFRAESTRUTURA E CIDADES", ano=2025),
              _linha("300003-3/2015", "52/2019-0", "SEC EST INFRAESTRUTURA E CIDADES", ano=2019),      # antiga: nem aparece
              _linha("300004-4/2022", "53/2025-0", "SEC EST INFRA E OBRAS PÚBLICAS", ano=2025)]
    monkeypatch.setattr(tce, "_baixar_json", lambda caminho, params: linhas if params["tipo"] == "multa" else [])
    for sigla, condenacoes in (("SEIOP", 1), ("SECID", 0)):
        c = tce.cruzar(sigla, "", "10/11/2026")
        assert c["resumo"]["condenacoes"] == condenacoes
        assert c["a_confirmar"] == {"SEC EST INFRAESTRUTURA E CIDADES": ["300001-1/2021", "300002-2/2021"]}
        md = tce.markdown(c)
        assert ('- **Nome antigo, fora da contagem:** a base traz 2 processos com condenação de 2024 para cá em nome de '
                '"SEC EST INFRAESTRUTURA E CIDADES", que pode ser antecessora desta secretaria. A ligação não está '
                'confirmada; por isso não entram acima: 300001-1/2021, 300002-2/2021.') in md
        assert all("300001" not in f["texto"] for f in tce.fatos(c))
    assert "Nenhuma multa ou débito em processos do órgão" in tce.markdown(tce.cruzar("SECID", "", "10/11/2026"))
    assert tce.cruzar("SEEDUC", "", "10/11/2026")["a_confirmar"] == {}


def test_resposta_que_nao_e_lista_vira_erro(tce, monkeypatch):
    monkeypatch.setattr(tce, "_baixar_json", lambda caminho, params: {"detail": "Not Found"})
    c = tce.cruzar("SEEDUC", "", "10/11/2026")
    assert c["penalidades"] == [] and "não veio como lista" in c["erros"][0]


def test_rodada_com_o_tce_traz_a_secao_os_fatos_e_a_pauta(llm, tce):
    import io
    import docx
    from transicao import analise
    llm.analise_riscos["riscos"][0]["fatos"] = ["F1", "O3", "T3"]
    r = analise.analisar_orgao("SEEDUC", RELATORIO, CFG)
    md = r["riscos_md"]
    assert "## Cruzamento com o TCE-RJ: multas e débitos" in md
    assert "[T3] Processo TCE-RJ 100372-5/2019 (SEC EST EDUCACAO): 2 condenações em débito" in llm.material_riscos
    assert "MULTAS E DÉBITOS NO TCE-RJ (decisões do Tribunal, dos dados abertos):" in llm.material_riscos
    r1 = next(x for x in r["riscos"] if x["id"] == "R1")
    assert "T3" in r1["fatos"]                                             # o id T é fato válido para o risco
    assert "[TCE-RJ, dados abertos (multas e débitos)](https://dados.tcerj.tc.br/api/v1/docs)" in md
    assert "(T3)" not in md
    # o que o TCE tem e a secretaria não citou abre a pauta de investigação
    pauta = md.split("## Informações que faltam: a pauta de investigação")[1]
    primeira = [l for l in pauta.split("\n") if l.startswith("| 1 |")][0]
    assert "Situação de 3 processos do TCE-RJ" in primeira and primeira.rstrip().endswith("| TCE-RJ |")
    assert r["registro"]["cruzamento_tce"]["resumo"]["processos_recentes_nao_citados"] == 3
    textos = [p.text for p in docx.Document(io.BytesIO(r["riscos_docx"])).paragraphs]
    assert "Cruzamento com o TCE-RJ: multas e débitos" in textos
