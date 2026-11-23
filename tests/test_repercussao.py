"""Sensibilidade a questões que podem virar notícia: o dado de estado (frota parada, efetivo abaixo do previsto, imóveis
sem regularização) não tem data nem contrato e não pode passar. O caso de regressão é o do relatório da PM, em que a
imprensa destacou números que estavam no material e não chegaram ao dossiê."""
import io
import re

from conftest import RELATORIO
from test_analise import CFG, capitulos_executivos

FROTA = ("A frota da Corporação é composta por 8.012 viaturas, das quais 3.902 estão operacionais (48,7%). As demais "
         "4.110 encontram-se fora de operação, sendo 1.917 em processo de leilão.")
MATERIAL_PM = f"""# ARQUIVO: relatorio_pm.pdf

4.4 Patrimônio e frota

{FROTA}

Dos 55 contratos de manutenção com oficinas, 33 estão com saldo esgotado e 22 permanecem ativos.

A sede do Regimento de Polícia Montada ocupa terreno do INSS, com ação de reintegração de posse transitada em julgado.

| Situação dos imóveis | Quantidade |
|---|---|
| Regularizados | 165 |
| Com pendências | 633 |

7.1 Força de trabalho

O efetivo previsto em lei é de 60.448 policiais militares. Atualmente, 43.442 estão na ativa.

A Secretaria foi criada pelo Decreto nº 46.544, de 2019, e atua nos 92 municípios do Estado.
O Programa Segurança Presente segue em execução normal, conforme o Processo SEI-350001/000123/2026.
8.1 Mapa de pendências por instância ........................................................ 59
"""


# --- A REDE POR CÓDIGO --------------------------------------------------------------------------------------------

def test_sinais_pegam_o_dado_de_estado_sem_data_e_sem_contrato():
    from transicao import alertas
    sinais = alertas.sinais(MATERIAL_PM)
    por_texto = {s["texto"]: s for s in sinais}
    frota = next(s for s in sinais if s["texto"].startswith("A frota da Corporação"))
    # "operacionais" não é palavra de alarme: o sinal vem da proporção (quantos existem e quantos funcionam)
    assert frota["forte"] and frota["tema"] == "Frota e veículos" and frota["alertas"] == ["disponibilidade"]
    assert frota["contexto"] == "relatorio_pm.pdf · 4.4 Patrimônio e frota"
    # a frase seguinte não repete o assunto: o tema vem do parágrafo
    paradas = next(s for s in sinais if s["texto"].startswith("As demais 4.110"))
    assert paradas["forte"] and paradas["tema"] == "Frota e veículos" and "fora de operação" in paradas["alertas"]
    assert next(s for s in sinais if "saldo esgotado" in s["texto"])["forte"]
    # sem número nenhum, mas com ordem judicial sobre um imóvel
    assert next(s for s in sinais if "reintegração de posse" in s["texto"])["forte"]
    # linha de tabela: o assunto está no cabeçalho, que vai no contexto
    pendencias = por_texto["Com pendências | 633"]
    assert pendencias["tema"] == "Imóveis e instalações" and "Situação dos imóveis | Quantidade" in pendencias["contexto"]
    # efetivo previsto e existente em frases separadas: as duas viram sinal, pelo parágrafo
    assert {"O efetivo previsto em lei é de 60.448 policiais militares.", "Atualmente, 43.442 estão na ativa."} <= set(por_texto)
    # rotina, ato de criação e linha de sumário não são sinal
    assert not any("92 municípios" in t or "Segurança Presente" in t or "Mapa de pendências" in t for t in por_texto)
    assert [s["id"] for s in sinais] == [f"S{k}" for k in range(1, len(sinais) + 1)]
    assert [s["peso"] for s in sinais] == sorted((s["peso"] for s in sinais), reverse=True)
    assert alertas.sinais("") == [] and alertas.texto_dos_sinais([]) == ""


def test_quantidade_nao_e_data_nem_numero_de_norma_ou_de_processo():
    from transicao import alertas
    frase = ("Decreto nº 46.544, de 2019; Lei 8.666; art. 42; SEI-350001/000123/2026; em 15/02/2027; 92 municípios; "
             "8.012 viaturas; 48,7%; R$ 6 milhões")
    assert alertas.quantidades(frase) == [("92", False), ("8012", False), ("487", True), ("6", False)]
    assert alertas._distintivos(frase) == {"8012", "487"}


# --- A LEITURA DE REPERCUSSÃO PÚBLICA (MODELO, CONFERIDA POR CÓDIGO) ----------------------------------------------

def _achado(**campos):
    base = {"assunto": "Frota de viaturas fora de operação", "tema": "Frota e veículos",
            "bloco": "Patrimônio, frota e meios operacionais",
            "texto": "Das 8.012 viaturas da frota, 3.902 estão operacionais (48,7%) e 4.110 estão fora de operação.",
            "trecho": FROTA}
    return {**base, **campos}


def test_leitura_de_repercussao_so_aceita_o_que_confere_no_material(llm):
    from transicao import alertas
    llm.repercussao = {"achados": [
        _achado(),
        _achado(assunto="Número que não está no trecho",
                texto="Das 8.012 viaturas, 4.500 estão fora de operação."),
        _achado(assunto="Proporção por extenso", texto="Menos da metade das 8.012 viaturas está em operação."),
        _achado(assunto="Recomendação", texto="É preciso recompor a frota de 8.012 viaturas."),
        _achado(assunto="Trecho inventado", texto="A corporação tem 900 blindados parados.",
                trecho="A corporação tem 900 blindados parados por falta de peças desde 2024."),
        _achado(assunto="A mesma frota, de novo"),
        _achado(assunto="Efetivo abaixo do previsto em lei", tema="Efetivo e pessoal", bloco="bloco que não existe",
                texto="O efetivo previsto em lei é de 60.448 policiais militares e 43.442 estão na ativa.",
                trecho="O efetivo previsto em lei é de 60.448 policiais militares. Atualmente, 43.442 estão na ativa."),
        _achado(assunto="", texto="x"), "lixo"]}
    sinais = alertas.sinais(MATERIAL_PM)
    r = alertas.repercussao(CFG["modelo"], MATERIAL_PM, sinais)
    assert [(a["id"], a["assunto"]) for a in r["achados"]] == [("N1", "Frota de viaturas fora de operação"),
                                                              ("N2", "Efetivo abaixo do previsto em lei")]
    assert r["achados"][0]["rotulo"] == "informado pelo órgão" and r["achados"][0]["trecho"] == FROTA
    assert r["achados"][1]["bloco"] == "Pessoal"                        # bloco inválido: vai o do tema
    motivos = {x["assunto"]: x["motivo"] for x in r["recusados"]}
    assert motivos["Número que não está no trecho"] == "número que não está no trecho: 4500"
    assert motivos["Proporção por extenso"].startswith("proporção por extenso que não está no trecho: metade")
    assert motivos["Recomendação"].startswith("recomendação")
    assert motivos["Trecho inventado"] == "trecho não encontrado no material"
    assert motivos["A mesma frota, de novo"] == "repetido" and motivos[""] == "campo em branco"
    assert r["uso"][0]["etapa"] == "leitura de repercussão pública"
    # o pedido: o material em cache, o olhar de repórter, o dado de estado e as pistas separadas por código
    pedido = llm.pedido_repercussao
    for trecho in ["procura o\nque vira notícia", "meio de trabalho parado ou degradado", "falta de gente",
                   "patrimônio irregular ou em risco", "DADO DE ESTADO, mesmo sem prazo, sem contrato",
                   "SINAIS que o sistema separou por código", "(Frota e veículos) [relatorio_pm.pdf · 4.4 Patrimônio e frota] "
                   "A frota da Corporação é composta por 8.012 viaturas"]:
        assert trecho in pedido, trecho
    usuario = llm.chamadas[-1]["mensagens"][1]["content"]
    assert usuario[0]["cache_control"] and "<relatorio>" in usuario[0]["text"]
    # sem material, nenhuma chamada
    antes = len(llm.chamadas)
    assert alertas.repercussao(CFG["modelo"], "", sinais)["achados"] == [] and len(llm.chamadas) == antes


def _achados_conferidos(llm, *brutos):
    from transicao import alertas
    llm.repercussao = {"achados": list(brutos)}
    return alertas.repercussao(CFG["modelo"], MATERIAL_PM)["achados"]


EFETIVO = dict(assunto="Efetivo abaixo do previsto em lei", tema="Efetivo e pessoal", bloco="Pessoal",
               texto="O efetivo previsto em lei é de 60.448 policiais militares e 43.442 estão na ativa.",
               trecho="O efetivo previsto em lei é de 60.448 policiais militares. Atualmente, 43.442 estão na ativa.")
MONTADA = dict(assunto="Sede do Regimento de Polícia Montada", tema="Imóveis e instalações",
               bloco="Pendências com controle e justiça",
               texto="A sede do Regimento de Polícia Montada ocupa terreno do INSS e há reintegração de posse "
                     "transitada em julgado.",
               trecho="A sede do Regimento de Polícia Montada ocupa terreno do INSS, com ação de reintegração de posse "
                      "transitada em julgado.")


# --- NO DOSSIÊ ----------------------------------------------------------------------------------------------------

def test_achado_entra_no_bloco_do_diagnostico_e_o_que_ja_esta_la_e_so_marcado(llm, funcoes):
    from transicao import produtos
    achados = _achados_conferidos(llm, _achado(), _achado(**EFETIVO), _achado(**MONTADA))
    it = lambda k, texto: {"id": f"F{k}", "texto": texto, "rotulo": "informado pelo órgão", "url": "", "origem_item": ""}
    diag = {"secoes": [{"titulo": t, "itens": [], "leitura": "", "nao_se_sabe": []} for t in produtos.SECOES_DIAGNOSTICO]}
    secao = {s["titulo"]: s for s in diag["secoes"]}
    secao["Pessoal"]["itens"] = [it(1, "A secretaria informa 43.442 policiais na ativa, para efetivo legal de 60.448.")]
    secao["Patrimônio, frota e meios operacionais"]["itens"] = [it(2, "A corporação tem 798 imóveis.")]
    registro = produtos.incorporar_achados(diag, achados)
    assert registro == [{"achado": "N1", "situacao": 'incluído em "Patrimônio, frota e meios operacionais"', "item": "F3"},
                        {"achado": "N2", "situacao": "já estava no diagnóstico", "item": "F1"},
                        {"achado": "N3", "situacao": 'incluído em "Pendências com controle e justiça"', "item": "F4"}]
    meios = secao["Patrimônio, frota e meios operacionais"]["itens"]
    assert [i["id"] for i in meios] == ["F3", "F2"] and meios[0]["repercussao"] and meios[0]["texto"].startswith("Das 8.012")
    assert secao["Pessoal"]["itens"][0]["repercussao"] and len(secao["Pessoal"]["itens"]) == 1
    # no dossiê executivo: capítulo próprio para os meios, numeração corrida, e o achado de bloco que não tem capítulo
    # (controle e justiça) não some: entra em "Dificuldades e gargalos"
    md = funcoes.capitulos_executivos(diag)
    assert capitulos_executivos(md) == ["Força de trabalho", "Frota, patrimônio e meios operacionais", "Dificuldades e gargalos"]
    assert "## 2. Frota, patrimônio e meios operacionais\n- Das 8.012 viaturas da frota, 3.902 estão operacionais" in md
    assert "## 3. Dificuldades e gargalos\n- A sede do Regimento de Polícia Montada ocupa terreno do INSS" in md
    # no resumo executivo, o fato vai marcado para ter prioridade nos destaques
    fatos = {f["id"]: f for f in funcoes.fatos_para_o_resumo_do_dossie(diag)}
    assert fatos["F3"]["origem"].endswith("repercussão pública") and fatos["F4"]["origem"].endswith("repercussão pública")
    assert not fatos["F2"]["origem"].endswith("repercussão pública")
    from transicao import executivo
    assert 'Fato com "repercussão pública" na origem' in executivo.PROMPT_RESUMO_DOSSIE
    # o roteiro completo (usado na conferência de números) também traz o bloco
    assert "Frota, patrimônio e meios operacionais" in funcoes.markdown_capitulos(diag, [])
    assert produtos.incorporar_achados({"secoes": []}, achados) == []


# --- NA ANÁLISE DE RISCOS -----------------------------------------------------------------------------------------

def test_achado_vira_ponto_critico_e_o_que_nao_vira_risco_sai_em_lista_propria(llm, funcoes):
    from transicao import riscos
    achados = _achados_conferidos(llm, _achado(), _achado(**EFETIVO), _achado(**MONTADA))
    pontos = {"P1": {"assunto": "Efetivo", "tipo": riscos.TIPOS_DE_PONTO[10], "rotulo": "informado pelo órgão",
                     "texto": "O efetivo previsto em lei é de 60.448 policiais militares. Atualmente, 43.442 estão na ativa.",
                     "origem": "material enviado pela secretaria"}}
    de_para = riscos.juntar_achados(pontos, achados)
    assert de_para == {"N1": "P2", "N2": "P1", "N3": "P3"}
    assert pontos["P2"] == {"assunto": "Frota de viaturas fora de operação", "tipo": riscos.TIPO_REPERCUSSAO,
                            "texto": FROTA, "origem": "material enviado pela secretaria",
                            "rotulo": "informado pelo órgão", "achado": "N1"}
    assert pontos["P1"]["tipo"].endswith("; " + riscos.TIPO_REPERCUSSAO)
    assert riscos.juntar_achados(pontos, achados) == de_para and len(pontos) == 3          # de novo, nada muda
    # a análise recebe o tipo e a regra: condição de estado é risco mesmo sem data
    material = riscos.material("PM", {"secoes": []}, {}, pontos=pontos)
    assert f"- [P2] ({riscos.TIPO_REPERCUSSAO}) Frota de viaturas fora de operação: A frota da Corporação" in material
    for trecho in ["CONDIÇÃO DE ESTADO também é risco, mesmo sem data e sem contrato", "REPERCUSSÃO PÚBLICA: o ponto P",
                   "meio de trabalho parado ou degradado (frota, viaturas, equipamentos, sistemas"]:
        assert trecho in riscos.PROMPT_ANALISE, trecho
    assert "condição de estado que compromete a operação, mesmo sem prazo" in riscos.PROMPT_PONTOS
    assert "Meios operacionais e patrimônio" in riscos.CATEGORIAS
    # o que virou risco: citado como fato (P1) ou com os números no texto do risco; o resto sai na lista própria
    resultado = {"riscos": [{"id": "R1", "titulo": "Efetivo abaixo do previsto", "fatos": ["P1"], "causa": "x"},
                            {"id": "R2", "titulo": "Sede do Regimento de Polícia Montada com reintegração de posse",
                             "causa": "O terreno é do INSS e a reintegração transitou em julgado.", "fatos": ["F9"]}]}
    fora = funcoes.achados_fora_dos_riscos(achados, resultado, de_para)
    assert [a["id"] for a in fora] == ["N1"]
    md = funcoes.relatorio_riscos({"riscos": [], "pedir": []}, None, "nota", repercussao=fora)
    assert ("## Outros dados com possível repercussão pública\n_Dados que a secretaria informou e que não estão nos pontos "
            "de atenção acima.") in md
    assert "- **Frota de viaturas fora de operação.** Das 8.012 viaturas da frota, 3.902 estão operacionais" in md
    assert "Outros dados com possível repercussão" not in funcoes.relatorio_riscos({"riscos": [], "pedir": []}, None, "nota")


def test_fichas_nao_tiram_do_funil_o_que_o_modelo_achou_no_resto_do_material(llm):
    from transicao import riscos
    literal = "Quatro concorrências estão adiadas sine die, somando R$ 120.500.000,00"
    llm.pontos_criticos = {"pontos": [{"assunto": "Quatro concorrências de obras adiadas", "tipo": riscos.TIPOS_DE_PONTO[7],
                                       "trecho": literal}]}
    fichas = [{"titulo": f"Programa número {k} da carteira", "grupo": "3.1", "secao": f"3.1.{k}", "pagina": k,
               "campos": {"pontos_criticos": f"Pendência do programa {k}"}} for k in range(1, 41)]
    p = riscos.pontos_criticos(CFG["modelo_auxiliar"], RELATORIO, {"secao3": [{"fichas": fichas}]})
    assert len(p["pontos"]) == riscos.LIMITE_PONTOS and len(p["fora_do_limite"]) == 41 - riscos.LIMITE_PONTOS
    # antes, as 40 fichas ocupavam todos os lugares e o ponto do modelo ficava de fora
    assert p["pontos"]["P2"]["assunto"] == "Quatro concorrências de obras adiadas"
    assert "SINAIS que o sistema separou" not in llm.pedido_pontos                      # sem sinais, o pedido não muda
    from transicao import alertas
    riscos.pontos_criticos(CFG["modelo_auxiliar"], MATERIAL_PM, None, sinais=alertas.sinais(MATERIAL_PM))
    assert "SINAIS que o sistema separou por código" in llm.chamadas[-1]["mensagens"][1]["content"][-1]["text"]


# --- A CONTA E A RODADA INTEIRA -----------------------------------------------------------------------------------

def test_conta_diz_o_que_chegou_a_cada_produto(llm):
    from transicao import alertas
    achados = _achados_conferidos(llm, _achado(), _achado(**EFETIVO), _achado(**MONTADA))
    sinais = alertas.sinais(MATERIAL_PM)
    dossie = "## 5. Frota\n- Das 8.012 viaturas da frota, 3.902 estão operacionais (48,7%).\n- Reintegração de posse do terreno do INSS ocupado pela sede do Regimento de Polícia Montada, transitada em julgado."
    conta = alertas.conta({"achados": achados, "recusados": [{"assunto": "x", "motivo": "repetido"}]}, sinais,
                          {"dossiê": dossie, "relatório de riscos": "## 1. Tema\nNada sobre o assunto.", "painel": ""},
                          cobertos={"relatório de riscos": {"N2"}})
    assert conta["produtos"] == ["dossiê", "relatório de riscos"]
    assert {a["id"]: a["em"] for a in conta["achados"]} == {"N1": ["dossiê"], "N2": ["relatório de riscos"], "N3": ["dossiê"]}
    assert conta["sinais"] == len(sinais) and conta["sinais_fortes"] == sum(s["forte"] for s in sinais)
    fora = [s["texto"] for s in conta["sinais_fortes_fora"]]
    assert any("saldo esgotado" in t for t in fora) and not any(t.startswith("A frota da Corporação") for t in fora)
    assert alertas.observacao(conta) == "3 dado(s) de repercussão pública fora de algum produto (ver auditoria)"
    md = alertas.markdown_da_conta(conta)
    assert "## Sensibilidade a questões de repercussão pública" in md and "| Frota e veículos | dossiê |" in md
    assert "Achados recusados pela conferência (1):" in md and "Dos 55 contratos de manutenção com oficinas" in md
    tudo_certo = alertas.conta({"achados": achados}, [], {"dossiê": dossie}, cobertos={"dossiê": {"N2"}})
    assert alertas.observacao(tudo_certo) == "" and alertas.observacao(None) == ""
    assert alertas.observacao(alertas.conta({"achados": [], "erro": "Timeout"}, [], {})) == "leitura de repercussão falhou (ver auditoria)"


def test_rodada_inteira_leva_o_dado_que_vira_noticia_aos_dois_produtos(llm):
    import docx
    from transicao import analise
    relatorio = RELATORIO + "\n\n" + MATERIAL_PM
    llm.repercussao = {"achados": [_achado(), _achado(**EFETIVO)]}
    r = analise.analisar_orgao("Secretaria de Exemplo", relatorio, CFG)
    reg = r["registro"]
    # a leitura de repercussão roda com o modelo principal, sobre o material inteiro, com as pistas do código
    chamada = next(c for c in llm.chamadas if "LEITURA DE REPERCUSSÃO PÚBLICA" in str(c["mensagens"]))
    assert chamada["modelo"] == CFG["modelo"] and "8.012 viaturas" in str(chamada["mensagens"])
    assert "SINAIS que o sistema separou por código" in llm.mensagem_diagnostico_orgao
    # dossiê: o dado está no capítulo dos meios, na frente, e o efetivo em "Força de trabalho"
    md = r["dossie_md"]
    assert "Frota, patrimônio e meios operacionais" in capitulos_executivos(md)
    assert re.search(r"## \d+\. Frota, patrimônio e meios operacionais\n- Das 8\.012 viaturas da frota, 3\.902 estão operacionais", md)
    assert "O efetivo previsto em lei é de 60.448 policiais militares e 43.442 estão na ativa." in md
    textos = [p.text for p in docx.Document(io.BytesIO(r["dossie_docx"])).paragraphs]
    assert any("3.902 estão operacionais (48,7%)" in t for t in textos)
    # relatório de riscos: a análise (falsa) não fez risco com a frota; o dado sai, por código, na lista própria
    assert "## Outros dados com possível repercussão pública" in r["riscos_md"]
    assert "- **Frota de viaturas fora de operação.** Das 8.012 viaturas" in r["riscos_md"]
    textos = [p.text for p in docx.Document(io.BytesIO(r["riscos_docx"])).paragraphs]
    assert "Outros dados com possível repercussão pública" in textos
    # a análise de riscos recebeu os achados como pontos críticos com id
    pontos = reg["pontos_criticos"]["pontos"]
    assert [p["assunto"] for p in pontos.values() if p["tipo"] == "dado com potencial de repercussão pública"] == [
        "Frota de viaturas fora de operação", "Efetivo abaixo do previsto em lei"]
    # a conta, no registro e na auditoria: os dois achados nos dois produtos, nada a acusar
    conta = reg["repercussao_publica"]
    assert [a["em"] for a in conta["achados"]] == [["dossiê", "relatório de riscos"]] * 2
    assert conta["nos_pontos_criticos"] and [x["situacao"] for x in conta["no_diagnostico"]] == [
        'incluído em "Patrimônio, frota e meios operacionais"', 'incluído em "Pessoal"']
    assert conta["sinais_fortes"] >= 4 and r["observacao"] == ""        # nem o falso alerta de tom da nota final
    assert reg["verificacao"]["revisao_do_texto"]["alertas_no_documento"] == []
    assert "## Sensibilidade a questões de repercussão pública" in reg["auditoria_md"]
    assert not any("repercussão" in p for p in reg["verificacao"]["problemas"])


def test_rodada_segue_se_a_leitura_de_repercussao_falhar(llm, monkeypatch):
    from transicao import alertas, analise

    def falha(*a, **k):
        raise RuntimeError("serviço indisponível")
    monkeypatch.setattr(alertas, "repercussao", falha)
    r = analise.analisar_orgao("Secretaria de Exemplo", RELATORIO, CFG)
    assert r["dossie_md"] and r["riscos_md"]
    assert r["registro"]["repercussao_publica"]["erro"].startswith("RuntimeError")
    assert "leitura de repercussão pública: RuntimeError" in "; ".join(r["registro"]["verificacao"]["problemas"])
    assert "A leitura de repercussão falhou nesta rodada" in r["registro"]["auditoria_md"]
