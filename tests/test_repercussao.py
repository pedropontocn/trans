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
        _achado(assunto="Proporção sem percentual", texto="Menos da metade das 8.012 viaturas está em operação."),
        _achado(assunto="Recomendação", texto="É preciso recompor a frota de 8.012 viaturas."),
        _achado(assunto="Trecho inventado", texto="A corporação tem 900 blindados parados.",
                trecho="A corporação tem 900 blindados parados por falta de peças desde 2024."),
        _achado(assunto="A mesma frota, de novo"),
        _achado(assunto="Efetivo abaixo do previsto em lei", tema="Efetivo e pessoal", bloco="bloco que não existe",
                texto="O efetivo previsto em lei é de 60.448 policiais militares e 43.442 estão na ativa.",
                trecho="O efetivo previsto em lei é de 60.448 policiais militares. Atualmente, 43.442 estão na ativa."),
        _achado(assunto="", manchete="", texto="x"), "lixo"]}
    sinais = alertas.sinais(MATERIAL_PM)
    r = alertas.repercussao(CFG["modelo"], MATERIAL_PM, sinais)
    assert [(a["id"], a["assunto"]) for a in r["achados"]] == [("N1", "Frota de viaturas fora de operação"),
                                                              ("N2", "Efetivo abaixo do previsto em lei")]
    assert r["achados"][0]["rotulo"] == "informado pelo órgão" and r["achados"][0]["trecho"] == FROTA
    assert r["achados"][0]["trechos"] == [FROTA] and r["achados"][0]["tipo"] == "dado" and r["partes"] == 1
    assert r["achados"][0]["manchete"] == "Frota de viaturas fora de operação"       # sem manchete, vale o assunto
    assert r["achados"][1]["bloco"] == "Pessoal"                        # bloco inválido: vai o do tema
    motivos = {x["assunto"]: x["motivo"] for x in r["recusados"]}
    assert motivos["Número que não está no trecho"] == "número que os trechos não sustentam: 4500"
    assert motivos["Proporção sem percentual"] == "proporção por extenso sem base: menos da metade"
    assert motivos["Recomendação"].startswith("recomendação")
    assert motivos["Trecho inventado"].startswith("trecho não encontrado no material")
    assert motivos["A mesma frota, de novo"] == "repetido" and motivos[""] == "campo em branco"
    assert r["uso"][0]["etapa"] == "leitura de repercussão pública"
    # o pedido: o material em cache, o olhar de repórter, o que procurar e as pistas separadas por código
    pedido = llm.pedido_repercussao
    for trecho in ["procura manchete", "dinheiro parado ou mal gasto", "bandeira ou promessa que ficou no papel",
                   "meio de trabalho parado ou degradado", "tema sensível por natureza, mesmo numa linha só",
                   "vigilância e reconhecimento facial", "INCOERÊNCIA do próprio material", "O sistema refaz a conta",
                   "Não use fato que não\nesteja no material", "liste também as AUSÊNCIAS do material inteiro",
                   "SINAIS que o sistema separou por código", "(Frota e veículos) [relatorio_pm.pdf · 4.4 Patrimônio e frota] "
                   "A frota da Corporação é composta por 8.012 viaturas"]:
        assert trecho in pedido, trecho
    usuario = llm.chamadas[-1]["mensagens"][1]["content"]
    assert usuario[0]["cache_control"] and "<relatorio>" in usuario[0]["text"]
    # sem material, nenhuma chamada
    antes = len(llm.chamadas)
    assert alertas.repercussao(CFG["modelo"], "", sinais)["achados"] == [] and len(llm.chamadas) == antes


MATERIAL_LONGO = MATERIAL_PM + """
4.6.2 Execução por ação

| Ação | Dotação atualizada | Empenhado |
|---|---|---|
| 4945 Operação Contenção/Barricada Zero | 200.000.000,00 | 0,00 |
| 2345 Gestão da frota | 95.200.000,00 | 49.712.300,00 |

O resumo deste relatório registra que a frota está 64% operacional.
Kit operacional entregue a 5.489 policiais, para meta de 14.000.

8.3 Demandas judiciais

A Operação Contenção, de 28/10/2025, é o foco atual da ADPF 635 no Supremo Tribunal Federal.
"""


def test_reporter_cruza_secoes_faz_conta_e_aponta_incoerencia_e_ausencia(llm):
    """O que a leitura amarrada demais não fazia: juntar trechos de seções diferentes, escrever o percentual que o
    material não escreve, arredondar, apontar número que não bate e o que o relatório não traz. Tudo conferido."""
    from transicao import alertas
    barricada = "| 4945 Operação Contenção/Barricada Zero | 200.000.000,00 | 0,00 |"
    adpf = "A Operação Contenção, de 28/10/2025, é o foco atual da ADPF 635 no Supremo Tribunal Federal."
    kit = "Kit operacional entregue a 5.489 policiais, para meta de 14.000."
    resumo = "O resumo deste relatório registra que a frota está 64% operacional."
    gestao = "| 2345 Gestão da frota | 95.200.000,00 | 49.712.300,00 |"
    novo = lambda **c: {"tema": "Outros", "bloco": "Orçamento e execução", "tipo": "dado", "potencial": "matéria", **c}
    llm.repercussao = {"achados": [
        novo(manchete="Só 39% dos PMs receberam o kit operacional", assunto="Kit operacional", potencial="nota",
             texto="Foram equipados 5.489 policiais de uma meta de 14.000.", trechos=[kit]),
        novo(manchete="Barricada Zero teve R$ 200 milhões no orçamento e nenhum empenho", assunto="Barricada Zero",
             potencial="capa", janela="herança",
             texto="A ação 4945 tem R$ 200 milhões de dotação e R$ 0,00 empenhado. A Operação Contenção, de 28/10/2025, "
                   "é o foco atual da ADPF 635.", trechos=[barricada, adpf]),
        novo(manchete="Menos da metade das viaturas da PM está rodando", assunto="Frota", potencial="capa",
             tipo="incoerência", tema="Frota e veículos",
             texto="Das 8.012 viaturas, 3.902 estão operacionais (48,7%), menos da metade; o resumo fala em 64% operacional. "
                   "Estão fora de operação 4.110, e a gestão da frota empenhou R$ 49,7 milhões de R$ 95,2 milhões (52%).",
             trechos=[FROTA, resumo, gestao]),
        novo(manchete="Relatório não informa mortes por intervenção policial", assunto="Letalidade policial",
             tipo="ausência", potencial="nota", termos=["letalidade", "mortes por intervenção", "morte por intervenção"],
             texto="O material não traz número de mortes por intervenção policial."),
        # recusados: a conta não fecha; percentual tirado de data; ausência do que o material traz; ausência com número
        novo(manchete="Só 45% dos PMs receberam o kit", assunto="Conta errada", texto="5.489 de 14.000.", trechos=[kit]),
        novo(manchete="Operação em 28/10/2025", assunto="Percentual de data", trechos=[adpf],
             texto="A operação de 28/10/2025 responde por 35,7% do total."),
        novo(manchete="Relatório não fala da frota", assunto="Ausência falsa", tipo="ausência",
             termos=["viaturas", "frota inexistente"], texto="O material não trata da frota."),
        novo(manchete="Faltam os 300 casos", assunto="Ausência com número", tipo="ausência",
             termos=["letalidade", "autos de resistência"], texto="O material não traz os 300 casos."),
    ]}
    r = alertas.repercussao(CFG["modelo"], MATERIAL_LONGO)
    # do maior potencial para o menor; dentro do potencial, a ordem da leitura
    assert [(a["id"], a["potencial"], a["assunto"]) for a in r["achados"]] == [
        ("N1", "capa", "Barricada Zero"), ("N2", "capa", "Frota"), ("N3", "nota", "Kit operacional"),
        ("N4", "nota", "Letalidade policial")]
    n1, n2, _, n4 = r["achados"]
    assert n1["trechos"] == [barricada, adpf] and n1["trecho"] == barricada + " […] " + adpf and n1["janela"] == "herança"
    assert n2["tipo"] == "incoerência" and n2["rotulo"] == "leitura da análise (IA)"
    assert n4["tipo"] == "ausência" and n4["trechos"] == [] and n4["termos"][0] == "letalidade"
    motivos = {x["assunto"]: x["motivo"] for x in r["recusados"]}
    assert motivos == {"Conta errada": "número que os trechos não sustentam: 45%",
                       "Percentual de data": "número que os trechos não sustentam: 357%",
                       "Ausência falsa": "o material traz o termo: viaturas", "Ausência com número": "ausência com número"}
    # as contas que o código aceita, uma a uma
    assert alertas._numeros_sem_base("39% de 14.000; R$ 49,7 milhões; 4.110 fora; 52%; 17 mil a menos", [
        kit, gestao, "8.012 viaturas, 3.902 operacionais", "efetivo de 60.448 e 43.442 na ativa"]) == []
    assert alertas._numeros_sem_base("R$ 49,8 milhões e 40%", [kit, gestao]) == ["498", "40%"]
    assert alertas._proporcao_sem_base("mais da metade (48,7%) e a maioria", [FROTA]) == ["a maioria"[2:], "mais da metade"]
    # a seção do documento
    md = alertas.markdown_das_manchetes(r["achados"])
    assert md.startswith("## O que pode virar notícia\n_Leitura da IA sobre o material da secretaria, feita como a imprensa")
    assert md.index("**Potencial de capa**") < md.index("**Rendem nota**") and "**Rendem matéria**" not in md
    assert ("- **Barricada Zero teve R$ 200 milhões no orçamento e nenhum empenho.** A ação 4945 tem R$ 200 milhões de "
            "dotação e R$ 0,00 empenhado.") in md and "_(herança da gestão que sai)_" in md
    assert "- **Menos da metade das viaturas da PM está rodando.** Incoerência do material. Das 8.012" in md
    assert "- **Relatório não informa mortes por intervenção policial.** Ausência no material. O material não traz" in md
    assert alertas.markdown_das_manchetes([]) == ""


def test_material_longo_e_lido_em_partes_e_o_mesmo_dado_nao_entra_duas_vezes(llm, monkeypatch):
    from transicao import alertas
    monkeypatch.setattr(alertas, "TAMANHO_DA_PARTE", 700)
    partes = alertas.partes_do_material(MATERIAL_LONGO, 700)
    n = len(partes)
    assert n >= 3 and "".join(partes) == MATERIAL_LONGO and all(p.endswith("\n") for p in partes)
    assert len(alertas.partes_do_material("x\n" * 400_000)) == alertas.MAXIMO_DE_PARTES
    frota = lambda **c: _achado(**{"manchete": "Frota parada", "potencial": "nota", **c})
    llm.repercussao = {"achados": []}
    llm.repercussao_por_parte = {
        1: {"achados": [frota()]},
        n: {"achados": [frota(potencial="capa", manchete="Menos da metade das viaturas roda (48,7%)",
                              trechos=["O resumo deste relatório registra que a frota está 64% operacional.", FROTA],
                              texto="Das 8.012 viaturas, 3.902 estão operacionais (48,7%); o resumo fala em 64%.")]}}
    sinais = alertas.sinais(MATERIAL_LONGO)
    r = alertas.repercussao(CFG["modelo"], MATERIAL_LONGO, sinais)
    assert r["partes"] == n and len(llm.pedidos_repercussao) == n
    # o mesmo dado achado em duas partes: fica o de maior potencial, com os trechos dos dois
    assert len(r["achados"]) == 1 and r["achados"][0]["potencial"] == "capa"
    assert r["achados"][0]["manchete"] == "Menos da metade das viaturas roda (48,7%)" and len(r["achados"][0]["trechos"]) == 2
    assert [x["motivo"] for x in r["recusados"]] == ["repetido"] and len(r["uso"]) == n
    primeiro = next(p for p in llm.pedidos_repercussao if f"PARTE 1 de {n} do material" in p)
    assert "<parte>\n# ARQUIVO: relatorio_pm.pdf" in primeiro and "liste também as AUSÊNCIAS" in primeiro
    assert "A frota da Corporação é composta por 8.012 viaturas" in primeiro          # a pista é da parte
    outros = [p for p in llm.pedidos_repercussao if f"PARTE 1 de {n} do material" not in p]
    assert not any("AUSÊNCIAS" in p or "A frota da Corporação é composta" in p.split("</parte>")[1] for p in outros)
    # acima do limite: os de menor potencial ficam de fora dos documentos e vão para a auditoria
    monkeypatch.setattr(alertas, "LIMITE_ACHADOS", 1)
    llm.repercussao_por_parte = {1: {"achados": [frota(), _achado(**EFETIVO, potencial="capa")]}}
    r = alertas.repercussao(CFG["modelo"], MATERIAL_LONGO)
    assert [a["assunto"] for a in r["achados"]] == ["Efetivo abaixo do previsto em lei"]
    assert r["fora_do_limite"] == [{"manchete": "Frota parada", "texto": _achado()["texto"]}]
    conta = alertas.conta(r, [], {})
    assert alertas.observacao(conta) == "1 achado(s) de repercussão acima do limite (ver auditoria)"
    assert "passaram do limite de 1" in alertas.markdown_da_conta(conta)


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
    # no relatório saem todos, tenham ou não virado ponto de atenção, na seção própria
    md = funcoes.relatorio_riscos({"riscos": [], "pedir": []}, None, "nota", repercussao=achados)
    assert "## O que pode virar notícia\n_Leitura da IA sobre o material da secretaria" in md
    assert "- **Frota de viaturas fora de operação.** Das 8.012 viaturas da frota, 3.902 estão operacionais" in md
    assert "- **Sede do Regimento de Polícia Montada.** A sede do Regimento" in md
    assert "O que pode virar notícia" not in funcoes.relatorio_riscos({"riscos": [], "pedir": []}, None, "nota")
    # a ausência não tem trecho: não vira ponto crítico nem item do diagnóstico (é leitura, não fato do órgão)
    ausencia = {"id": "N9", "tipo": "ausência", "trecho": "", "trechos": [], "assunto": "x", "texto": "y", "bloco": "Pessoal",
                "rotulo": "leitura da análise (IA)", "origem": ""}
    assert riscos.juntar_achados(dict(pontos), [ausencia]) == {}
    from transicao import produtos
    diag = {"secoes": [{"titulo": "Pessoal", "itens": []}]}
    assert produtos.incorporar_achados(diag, [ausencia]) == [] and diag["secoes"][0]["itens"] == []


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
    # a seção "O que pode virar notícia" sai nos dois documentos, com tudo o que a leitura achou
    for doc_md, doc_docx in ((r["riscos_md"], r["riscos_docx"]), (md, r["dossie_docx"])):
        assert "## O que pode virar notícia" in doc_md and "**Rendem nota**" in doc_md
        assert "- **Frota de viaturas fora de operação.** Das 8.012 viaturas" in doc_md
        textos = [p.text for p in docx.Document(io.BytesIO(doc_docx)).paragraphs]
        assert "O que pode virar notícia" in textos and "Rendem nota" in textos
    assert md.index("## O que pode virar notícia") < md.index("**Fontes:**")
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
