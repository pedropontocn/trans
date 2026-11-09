"""A análise de cada secretaria e o processamento de várias.

Para cada secretaria: dossiê (enviado pela equipe ou pesquisado) → confronto com o relatório, calendário e diagnóstico
→ vencimentos com a régua de risco → análise de riscos → revisão por cinco agentes independentes → consolidação
→ conferência e prioridade por código → documento curto (montado por código) → revisão de neutralidade.
Também por secretaria, montados por código (sem custo de modelo): o calendário em Excel e os dados do painel (JSON).
No fim do lote, um resumo com situação e custo de cada secretaria. O painel e o calendário unificados ficam para depois.
"""
import csv
import hashlib
import io
import json
import os
import re
import threading
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime
from pathlib import Path

from . import checklist, confronto as conf, revisao, documentos, entrada, folha, modelo, painel, pesquisa, produtos, riscos, verificacao
from .config import MIN_ITENS_DOSSIE, PARALELOS_DIRETO, VERSAO, esquema_de_modelos

JUNTAS = False          # no modo econômico, as etapas independentes vão juntas para a mesma fila da Batch API


class ErroAnalise(Exception):
    pass


def _seguro(funcao, vazio):
    """Roda uma etapa complementar; se falhar, devolve o resultado vazio com o erro, sem derrubar a análise."""
    def rodar():
        try:
            return funcao()
        except Exception as e:
            return {**vazio, "erro": f"{type(e).__name__}: {e}"[:300]}
    return rodar


def _so_contratos_da_secretaria(dossie):
    """Contratos: só vale o que a secretaria informou. Itens de contrato do órgão vindos da pesquisa em fontes
    públicas ficam no registro, marcados, mas não entram na análise, no calendário nem nos documentos."""
    for i in dossie.get("itens") or []:
        if i.get("camada") == "orgao" and i.get("bloco") == "contratos_convenios" and i.get("incluir", True):
            i["incluir"], i["fora_por"] = False, "contrato de base externa: só vale o que a secretaria informou"


def analisar_orgao(nome, texto, cfg, estado=None, progresso=None, dossie=None, manifesto=None):
    """Analisa uma secretaria. texto: o relatório ou resumo enviado (pode ser vazio). dossie: o dossiê enviado pela
    equipe (pesquisa.dossie_enviado); sem ele, o app pesquisa as fontes públicas. Devolve o documento (Word), os
    eventos do calendário, os riscos (para o painel), o registro de auditoria e os números do resumo.
    Levanta ErroAnalise quando não há base para analisar."""
    progresso = progresso or (lambda _t: None)
    uso = modelo.novo_uso_do_fio()            # todas as chamadas desta secretaria registram aqui
    auxiliar, principal = cfg["modelo_auxiliar"], cfg["modelo"]
    relatorio, avisos = entrada.limpar_relatorio(texto) if (texto or "").strip() else ("", [])
    problemas = []

    if dossie is None:
        progresso("Pesquisando o dossiê em fontes públicas...")
        dossie = pesquisa.montar_dossie(cfg["modelo_pesquisa"], nome, cfg["data_corte"], cfg.get("foco", ""),
                                        estado=estado)
    # folha de pessoal da SEPLAG (Caderno de RH): dado oficial, entra por código
    sigla_orgao = entrada.sigla(nome) or (nome.strip() if re.fullmatch(r"[A-Z][A-Z0-9]{1,14}", nome.strip()) else "")
    pesquisa.acrescentar_itens(dossie, folha.itens(sigla_orgao))
    dossie["folha"] = folha.quadro(sigla_orgao)
    resumo_dos = pesquisa.resumo_dossie(dossie)
    if resumo_dos["itens"] < MIN_ITENS_DOSSIE or resumo_dos["orgao"] < 3:
        raise ErroAnalise(f"dossiê insuficiente ({resumo_dos['orgao']} itens sobre o órgão"
                          + (": confira se o arquivo traz fatos com link [título](https://...) ou a planilha de contratos)"
                             if dossie.get("origem") == "arquivo" else ")"))

    _so_contratos_da_secretaria(dossie)

    # confronto, calendário, diagnóstico e checklist leem o mesmo material (em cache): na Batch API vão juntos
    progresso("Diagnóstico, calendário, checklist e confronto com as fontes...")
    tarefas = [_seguro(lambda: conf.confrontar(auxiliar, dossie, relatorio),
                       {"divergencias": [], "descartadas": 0, "uso": []}),
               _seguro(lambda: produtos.extrair_calendario(auxiliar, dossie, relatorio, nome, cfg["data_corte"]),
                       {"eventos": [], "descartados": [], "uso": []}),
               _seguro(lambda: produtos.extrair_diagnostico(auxiliar, dossie, relatorio, nome),
                       {"secoes": [], "descartados": 0, "uso": []}),
               _seguro(lambda: checklist.responder(auxiliar, dossie, relatorio, nome), {"respostas": {}, "uso": []}),
               _seguro(lambda: produtos.extrair_contratos_criticos(auxiliar, dossie, relatorio, nome),
                       {"contratos": [], "descartados": 0, "uso": []})]
    feitos = modelo._em_paralelo(tarefas) if JUNTAS else [t() for t in tarefas]
    confronto, calendario, diagnostico, respostas_checklist, criticos = feitos
    for parte, rotulo in zip(feitos, ("confronto", "calendário", "diagnóstico", "checklist", "contratos críticos")):
        uso.extend(parte.pop("uso", None) or [])
        if parte.get("erro"):
            problemas.append(f"{rotulo}: {parte['erro']}")
    eventos = calendario.get("eventos") or []
    # calendário e contratos: só o que a secretaria informou
    calendario["descartados"] = (calendario.get("descartados") or []) + [
        {"data": f"{e['data']:%d/%m/%Y}", "evento": e["evento"], "motivo": "não veio da secretaria"}
        for e in eventos if e.get("origem") != "Informado pelo órgão"]
    eventos = [e for e in eventos if e.get("origem") == "Informado pelo órgão"]
    criticos["contratos"] = [c for c in criticos.get("contratos") or [] if c.get("rotulo") == "informado pelo órgão"]
    for sec in diagnostico.get("secoes") or []:
        if sec["titulo"] == "Contratos":
            sec["itens"] = [i for i in sec["itens"] if i["rotulo"] == "informado pelo órgão"]
    produtos.avaliar_riscos(eventos, cfg["data_corte"])
    if not any(s["itens"] for s in diagnostico.get("secoes") or []):
        raise ErroAnalise("o diagnóstico não trouxe nenhuma afirmação conferida"
                          + (f" ({diagnostico['erro']})" if diagnostico.get("erro") else ""))
    # o checklist: cada resposta conferida por código; o que ficou em branco vira lacuna visível
    cobertura = checklist.conferir(respostas_checklist.get("respostas") or {}, dossie, relatorio, eventos)

    progresso("Analisando riscos e decisões...")
    vencimentos = riscos.vencimentos_numerados(eventos)
    material = riscos.material(nome, diagnostico, vencimentos, conf.texto_confronto(confronto), cfg["data_corte"],
                               checklist.texto_para_analise(cobertura))
    analise = riscos.analisar(principal, material, uso)
    if not analise.get("riscos"):
        falha = modelo.ultima_falha()
        detalhe = (f" (motivo de parada: {falha[1]}; início da resposta: \"{falha[2]}\")" if falha
                   else " (o JSON veio sem a lista de riscos)")
        raise ErroAnalise("a análise de riscos não devolveu riscos legíveis" + detalhe)
    progresso("Seis agentes revisando a análise (cinco olhares e o advogado do diabo)...")
    esquema = esquema_de_modelos(principal, auxiliar, cfg.get("modelos_agentes"), cfg.get("familias"))
    modelos_agentes = esquema["agentes"]
    revisoes = riscos.revisar_por_agentes(principal, material, analise, uso, modelos_agentes)
    progresso("Consolidando...")
    final = riscos.consolidar(principal, material, analise, revisoes, uso)
    resultado = riscos.conferir_e_ordenar(final, diagnostico, vencimentos, dossie, cfg["data_corte"])
    # os seis agentes votam cada risco final: impacto, janela e sensibilidade política; o código apura
    progresso("Seis agentes votando, item a item, impacto, janela e sensibilidade política...")
    votacoes = riscos.votar_por_agentes(principal, material, resultado, uso, modelos_agentes)
    riscos.apurar_votos(resultado, votacoes, cfg["data_corte"])
    riscos.proveniencia(resultado["riscos"], revisoes, analise, final)   # quem apontou e quem contestou cada risco
    riscos.visoes_por_codigo(resultado["decisoes"], analise, revisoes)   # o que cada agente teme e valoriza, do bruto
    confianca = riscos.confianca(resumo_dos, resultado["riscos"], cobertura)

    contratos_criticos = criticos.get("contratos") or []          # os que a secretaria informou, conferidos

    def montar_corpo():
        return "\n\n".join([documentos.em_uma_pagina(resultado, cobertura, diagnostico.get("indicadores")),
                             documentos.markdown_capitulos(diagnostico, contratos_criticos),
                             documentos.markdown_riscos(resultado)])
    progresso("Revisando a neutralidade e o tom do texto...")
    # neutralidade: um modelo de outra família, quando há chave; no mínimo, um diferente do que escreveu. Ela aponta;
    # a revisão do texto reescreve no tom de análise (sem recomendação, sem responsável), com as travas do código
    neutralidade = _seguro(lambda: riscos.revisar_neutralidade(esquema["neutralidade"], montar_corpo(), uso),
                           {"modelo": esquema["neutralidade"]})()
    revisao_texto = revisao.revisar_texto(principal, resultado, uso, neutralidade.get("recomendacoes_implicitas"))
    corpo = montar_corpo()
    base = "\n".join([pesquisa.texto_dossie(dossie), relatorio, material])
    numeros = verificacao.verificar_numeros(corpo, base)

    uso_total = list(dossie.get("uso") or []) + uso
    custo, parcial = modelo.custo_estimado(uso_total)
    versao_prompt = hashlib.md5((pesquisa.PROMPT_PESQUISA + conf.PROMPT_CONFRONTO + produtos.PROMPT_CALENDARIO
                                 + produtos.PROMPT_DIAGNOSTICO_ORGAO + produtos.PROMPT_CONTRATOS
                                 + checklist.PROMPT_CHECKLIST + riscos.PROMPT_ANALISE
                                 + riscos.PROMPT_AGENTE + riscos.PROMPT_CONSOLIDACAO + riscos.PROMPT_VOTO
                                 + revisao.PROMPT_REVISAO).encode()).hexdigest()[:8]
    registro_id = f"{versao_prompt}-{hashlib.md5((material + relatorio).encode()).hexdigest()[:8]}"
    modelos = {"pesquisa": cfg["modelo_pesquisa"], "auxiliar": auxiliar, "debate": principal,
               "agentes": dict(zip((p[1] for p in riscos.PAPEIS), modelos_agentes)),
               "neutralidade": esquema["neutralidade"], "familias_de_fora": esquema["familias"]}
    nota = documentos.nota_final(registro_id, modelos, confianca, cfg["data_corte"], neutralidade, revisoes,
                                 revisao_texto)
    antes = documentos.antes_de_ler(confianca, cfg["data_corte"], documentos.cortes_de_leitura(manifesto, avisos))
    texto_dossie = documentos.dossie_secretaria(
        resultado, diagnostico, None, eventos, dossie, confronto, checklist.markdown(cobertura), nota,
        cobertura=cobertura, contratos_criticos=contratos_criticos, antes_md=antes, orgao=nome)
    texto_riscos = documentos.relatorio_riscos(resultado, cobertura, nota, antes_md=antes)
    revisao_texto["alertas_no_documento"] = revisao.alertas_do_documento(texto_riscos)   # a última conferência
    meta = {"orgao": cfg.get("orgao_emissor", ""), "unidade": cfg.get("unidade", ""), "para": cfg.get("para", ""),
            "assunto": nome, "tipo": "Dossiê da secretaria: como funciona hoje",
            "data": documentos._data_extenso(date.today()),
            "rodape_extra": f"apoio de IA, processamento automático, reg. {registro_id}"}
    para_json = lambda x: json.loads(json.dumps(x, ensure_ascii=False, default=str))
    registro = {
        "id": registro_id, "orgao": nome, "gerado_em": datetime.now().isoformat(timespec="seconds"),
        "versao": VERSAO, "versao_prompt": versao_prompt, "modelos": modelos, "avisos_relatorio": avisos,
        "dossie": json.loads(pesquisa.dossie_para_json(dossie)), "confronto": confronto, "diagnostico": diagnostico,
        "calendario": para_json(eventos), "calendario_descartados": calendario.get("descartados") or [],
        "analise_inicial": analise, "revisoes_dos_agentes": revisoes, "consolidacao": final,
        "votacao_dos_agentes": votacoes,
        "riscos": para_json(resultado), "checklist": cobertura, "contratos_criticos": contratos_criticos,
        "metodo_md": documentos.markdown_metodo(registro_id, modelos, resumo_dos, confianca, numeros, neutralidade,
                                               revisoes, resultado),
        "dossie_md": texto_dossie, "riscos_md": texto_riscos,
        "verificacao": {"numeros": numeros, "problemas": problemas, "neutralidade": neutralidade,
                        "revisao_do_texto": revisao_texto, "confianca": confianca},
        "uso_tokens": uso_total, "custo_estimado_usd": round(custo, 4), "custo_parcial": parcial,
    }
    texto_auditoria = documentos.auditoria_secretaria(resultado, dossie, confronto, registro["metodo_md"],
                                                      checklist.markdown(cobertura), diagnostico)
    registro["auditoria_md"] = texto_auditoria
    return {"dossie_docx": documentos.gerar_docx(texto_dossie, meta), "dossie_md": texto_dossie,
            "riscos_docx": documentos.gerar_docx(texto_riscos, dict(meta, tipo="Relatório de riscos e decisões urgentes")),
            "riscos_md": texto_riscos,
            "auditoria_md": texto_auditoria, "eventos": eventos,
            "descartados": [dict(d, orgao=nome) for d in calendario.get("descartados") or []],
            "riscos": [dict(r, orgao=nome) for r in resultado["riscos"]], "situacao": resultado["situacao"],
            "registro": registro, "custo": custo, "confianca": confianca["nivel"],
            "itens_dossie": resumo_dos["itens"],
            "dossie": "enviado" if dossie.get("origem") == "arquivo" else "pesquisado",
            "conferidos": resumo_dos["conferidos"], "n_riscos": len(resultado["riscos"]),
            "riscos_maxima_alta": sum(r["prioridade"] in ("Máxima", "Alta") for r in resultado["riscos"]),
            "agentes": sum(not r.get("erro") for r in revisoes),
            "nao_procurados": len(checklist.resumo(cobertura)["nao_procurados"]),
            "reescritos": len(revisao_texto["aceitos"]), "alertas_de_tom": len(revisao_texto["alertas_no_documento"]),
            "observacao": "; ".join([a.replace("⚠️ ", "") for a in avisos if "cortado" in a] + problemas
                                    + ([f"{len(revisao_texto['alertas_no_documento'])} trecho(s) com tom a conferir "
                                        "no relatório (ver auditoria)"] if revisao_texto["alertas_no_documento"] else []))[:300]}


# --- VÁRIOS ÓRGÃOS ------------------------------------------------------------------------

COLUNAS_RESUMO = ["orgao", "situacao", "dossie", "itens_dossie", "conferidos", "riscos", "riscos_maxima_alta",
                  "agentes", "datas_calendario", "nao_procurados", "confianca",
                  "custo_usd", "minutos", "observacao"]


def _gravar_resumo(saida, linhas, custo_estado):
    with open(saida / "resumo.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=COLUNAS_RESUMO, delimiter=";")
        w.writeheader()
        w.writerows(linhas)
    total = sum(l["custo_usd"] for l in linhas) + custo_estado
    (saida / "LEIA-ME.txt").write_text(
        "Resultados da análise das secretarias\n\n"
        "- paineis/: os dados do painel de cada secretaria em JSON (pontos de decisão com janela, prazo, prioridade e\n"
        "  repercussão política, na mesma régua para todas), prontos para o painel unificado.\n"
        "- dossies/: o dossiê de cada secretaria, atualizado com o que ela informou (resumo e números-chave; contratos,\n"
        "  pessoal, passivos, orçamento e obras; o que a secretaria informou x o que as fontes mostram; cobertura do\n"
        "  checklist; fontes).\n"
        "- riscos/: o relatório de riscos de cada secretaria, em até 3 páginas (riscos com prazo, janela,\n"
        "  prioridade, sensibilidade política e revisão dos agentes; informações que faltam).\n"
        "- calendarios/: o calendário de vencimentos de cada secretaria em Excel, só com as datas que ela informou; a\n"
        "  aba Prioridades vem primeiro.\n"
        "- resumo.csv: situação, números e custo de cada órgão.\n"
        "- auditoria/: o registro completo de cada análise em JSON (dossiê e conferências, revisões dos seis agentes,\n"
        "  objeções risco a risco, método, descartes, custo).\n\n"
        f"Órgãos concluídos: {sum(l['situacao'] == 'concluído' for l in linhas)} de {len(linhas)}. "
        f"Custo estimado: US$ {total:.2f} (inclui US$ {custo_estado:.2f} da pesquisa sobre o Estado).\n"
        "Documentos gerados com apoio de IA, sem revisão da equipe: confira antes de usar.\n", encoding="utf-8")


# --- RETOMADA DO DISCO ---------------------------------------------------------------------
# Cada órgão concluído deixa em auditoria/<pasta>_resultado.json o que o lote precisa dele (linha do resumo, eventos,
# riscos, situação). Se a análise cair no meio (reinício do app, queda de rede), rodar de novo na mesma pasta pula os
# órgãos prontos e só refaz o que faltou; o painel e o calendário são remontados com todos.

def _para_json(obj):
    if isinstance(obj, date):
        return {"__data__": obj.isoformat()}
    raise TypeError(f"não sei gravar {type(obj).__name__}")


def _de_json(d):
    if "__data__" in d and len(d) == 1:
        return date.fromisoformat(d["__data__"])
    return d


def gravar_resultado(saida, pasta, linha, r):
    (Path(saida) / "auditoria" / f"{pasta}_resultado.json").write_text(json.dumps(
        {"versao": VERSAO, "linha": linha, "eventos": r["eventos"], "descartados": r["descartados"],
         "riscos": r["riscos"], "situacao": r["situacao"]}, ensure_ascii=False, default=_para_json), encoding="utf-8")


def resultado_pronto(saida, pasta):
    """O resultado gravado de um órgão já concluído nesta pasta, ou None. Exige o documento junto."""
    saida = Path(saida)
    caminho = saida / "auditoria" / f"{pasta}_resultado.json"
    if not caminho.exists() or not (saida / "riscos" / f"{pasta}_riscos.docx").exists():
        return None
    try:
        dados = json.loads(caminho.read_text(encoding="utf-8"), object_hook=_de_json)
    except (OSError, ValueError):
        return None
    if dados.get("versao") != VERSAO or dados.get("linha", {}).get("situacao") != "concluído":
        return None
    return dados


def prontos(saida):
    """Os órgãos já concluídos numa pasta de saída (nome -> pasta), para a tela dizer o que vai ser pulado."""
    saida = Path(saida)
    nomes = {}
    for caminho in sorted((saida / "auditoria").glob("*_resultado.json")) if (saida / "auditoria").exists() else []:
        pasta = caminho.name[:-len("_resultado.json")]
        dados = resultado_pronto(saida, pasta)
        if dados:
            nomes[dados["linha"]["orgao"]] = pasta
    return nomes


def _gravar_painel_e_calendario(saida, pasta, nome, riscos_orgao, situacao, eventos_orgao, descartados_orgao, cfg,
                                linha, sobrescrever=True):
    """O calendário da secretaria (Excel) e os dados do painel (JSON, para o painel unificado), montados por código,
    sem chamada ao modelo. Saem sempre, mesmo sem data ou sem risco. O painel em Word por secretaria saiu: repetia a
    tabela de decisões urgentes do relatório de riscos."""
    calendario = saida / "calendarios" / f"{pasta}_calendario.xlsx"
    if sobrescrever or not calendario.exists():
        calendario.write_bytes(documentos.calendario_xlsx(
            eventos_orgao or [], [dict(d, orgao=d.get("orgao") or nome) for d in descartados_orgao or []],
            f"Calendário de vencimentos críticos – {nome}", cfg["data_corte"]))
    arquivo = saida / "paineis" / f"{pasta}_painel.json"
    if sobrescrever or not arquivo.exists():
        arquivo.write_text(json.dumps(painel.dados_do_painel(nome, riscos_orgao or [], situacao, cfg["data_corte"]),
                                      ensure_ascii=False, indent=1, default=str), encoding="utf-8")


def rodar_orgaos(orgaos, cfg, saida, economico=False, cliente_batch=None, paralelos=40, prazo_minutos=23 * 60,
                 log=print, retomar=True):
    """Analisa os órgãos e grava os resultados em `saida`. orgaos: lista de {"nome", "texto"} ou {"nome", "ler"}
    (ler() devolve o texto e o manifesto do que foi lido; ver entrada.orgaos_do_envio).
    No modo econômico, os órgãos rodam em paralelo e as chamadas à Anthropic vão pela Batch API (metade do preço).
    Com retomar, um órgão já concluído na mesma pasta de saída (auditoria/<pasta>_resultado.json e o documento) não é
    analisado de novo: o lote reaproveita o resultado e só refaz o que faltou."""
    global JUNTAS
    saida = Path(saida)
    for sub in ("paineis", "dossies", "riscos", "calendarios", "auditoria"):
        (saida / sub).mkdir(parents=True, exist_ok=True)
    fila = None
    if economico:
        from .lote_api import FilaBatch
        fila = FilaBatch(cliente=cliente_batch, prazo=time.time() + prazo_minutos * 60, log=log,
                         **({"quieto": 0.2, "intervalo": 0.2} if cliente_batch is not None else {}))
        JUNTAS = True
        log(f"Modo econômico: Batch API, até {paralelos} órgãos ao mesmo tempo.")
    chamada = fila.completion(lambda **kw: modelo._completion_litellm(**kw)) if fila else None

    try:
        modelo.usar_completion(chamada)
        modelo.novo_uso_do_fio()
        estado, reaproveitada = _estado_do_dia(cfg, log)
        custo_estado, _ = modelo.custo_estimado(estado.get("uso") or []) if not reaproveitada else (0.0, False)
        log(f"Estado: {len(estado.get('itens') or [])} itens" + (" (pesquisa de hoje reaproveitada, sem custo)." if reaproveitada else "."))

        linhas, eventos, descartados, todos_riscos, situacoes, trava = {}, {}, {}, {}, {}, threading.Lock()
        pastas = _pastas_unicas(o["nome"] for o in orgaos)

        def um(k, orgao):
            modelo.usar_completion(chamada)
            modelo.novo_uso_do_fio()         # o fio é reaproveitado: sem isso, um erro cedo herdaria o custo do órgão anterior
            inicio = time.time()
            nome = orgao["nome"]
            linha = {c: "" for c in COLUNAS_RESUMO}
            linha.update(orgao=nome, situacao="erro", custo_usd=0.0)
            pasta = pastas[k - 1]
            pronto = resultado_pronto(saida, pasta) if retomar else None
            if pronto and pronto["linha"].get("orgao") == nome:
                linha = pronto["linha"]
                with trava:
                    eventos[k], descartados[k] = pronto["eventos"], pronto["descartados"]
                    todos_riscos[k], situacoes[k] = pronto["riscos"], (nome, pronto["situacao"])
                    linhas[k] = linha
                    _gravar_resumo(saida, [linhas[i] for i in sorted(linhas)], custo_estado)
                try:                                       # se a pasta perdeu o painel ou o calendário, remonta
                    _gravar_painel_e_calendario(saida, pasta, nome, pronto["riscos"], pronto["situacao"],
                                                pronto["eventos"], pronto["descartados"], cfg, linha, sobrescrever=False)
                except Exception as e:
                    log(f"[{k}] painel/calendário não remontados: {type(e).__name__}: {e}"[:300])
                log(f"[{k}/{len(orgaos)}] {nome}: já estava pronto nesta pasta, reaproveitado")
                modelo.usar_completion(None)
                return linha
            log(f"[{k}/{len(orgaos)}] {nome}: começando")
            try:
                texto, manifesto = orgao.get("texto", ""), None
                if orgao.get("ler"):
                    texto, manifesto = orgao["ler"]()
                    (saida / "auditoria" / f"{pasta}_arquivos_lidos.json").write_text(
                        json.dumps(manifesto, ensure_ascii=False, indent=2), encoding="utf-8")
                    if not texto.strip():
                        raise ErroAnalise("nenhum arquivo do órgão pôde ser lido")
                dossie = None
                if orgao.get("ler_dossie"):
                    log(f"[{k}] Conferindo os links do dossiê enviado...")
                    dossie = pesquisa.dossie_enviado(orgao["ler_dossie"](), nome, cfg["data_corte"], estado=estado)
                r = analisar_orgao(nome, texto, cfg, estado=estado, dossie=dossie, manifesto=manifesto,
                                   progresso=lambda t: log(f"[{k}] {t}"))
                (saida / "dossies" / f"{pasta}_dossie.docx").write_bytes(r["dossie_docx"])
                (saida / "riscos" / f"{pasta}_riscos.docx").write_bytes(r["riscos_docx"])
                (saida / "auditoria" / f"{pasta}.json").write_text(
                    json.dumps(r["registro"], ensure_ascii=False, indent=2, default=str), encoding="utf-8")
                linha.update(situacao="concluído", dossie=r["dossie"], itens_dossie=r["itens_dossie"], conferidos=r["conferidos"],
                             riscos=r["n_riscos"], riscos_maxima_alta=r["riscos_maxima_alta"], agentes=r["agentes"],
                             datas_calendario=len(r["eventos"]), nao_procurados=r["nao_procurados"],
                             confianca=r["confianca"],
                             custo_usd=round(r["custo"], 3), observacao=r["observacao"])
                with trava:
                    eventos[k], descartados[k] = r["eventos"], r["descartados"]
                    todos_riscos[k], situacoes[k] = r["riscos"], (nome, r["situacao"])
                gravar_resultado(saida, pasta, dict(linha, minutos=round((time.time() - inicio) / 60, 1)), r)
                try:
                    _gravar_painel_e_calendario(saida, pasta, nome, r["riscos"], r["situacao"], r["eventos"],
                                                r["descartados"], cfg, linha)
                except Exception as e:
                    log(f"[{k}] painel/calendário não montados: {type(e).__name__}: {e}"[:300])
            except Exception as e:
                linha["observacao"] = f"{type(e).__name__}: {e}"[:300]
                custo, _ = modelo.custo_estimado(modelo.uso_do_fio())
                linha["custo_usd"] = round(custo, 3)
            finally:
                linha["minutos"] = round((time.time() - inicio) / 60, 1)
                modelo.usar_completion(None)
            with trava:
                linhas[k] = linha
                _gravar_resumo(saida, [linhas[i] for i in sorted(linhas)], custo_estado)
            log(f"[{k}/{len(orgaos)}] {nome} → {linha['situacao']}"
                + (f": {linha['observacao']}" if linha["observacao"] else "")
                + f" ({linha['minutos']} min, US$ {linha['custo_usd']:.2f})")
            return linha

        trabalhadores = max(1, min(paralelos if fila else PARALELOS_DIRETO, len(orgaos)))
        with ThreadPoolExecutor(max_workers=trabalhadores) as ex:
            resultado = list(ex.map(lambda par: um(*par), enumerate(orgaos, 1)))

        return resultado
    finally:
        modelo.usar_completion(None)
        JUNTAS = False
        if fila:
            fila.encerrar()
            log(f"Modo econômico: {fila.enviados} lote(s) enviados à Batch API.")


def _estado_do_dia(cfg, log):
    """A pesquisa do contexto do Estado é a mesma para todos os órgãos e para todas as rodadas do dia com a mesma data
    de corte, modelo e foco: fica guardada em disco (pasta de registros) e é reaproveitada. Devolve (estado,
    reaproveitada)."""
    pasta = Path(os.getenv("PASTA_REGISTROS") or "registros") / "estado"
    chave = modelo.chave_guardada("estado", VERSAO, pesquisa.PROMPT_PESQUISA, cfg["modelo_pesquisa"], cfg["data_corte"],
                                  cfg.get("foco", ""), date.today().isoformat())[:20]
    arquivo = pasta / f"{date.today():%Y-%m-%d}_{chave}.json"
    try:
        if arquivo.exists():
            estado = json.loads(arquivo.read_text(encoding="utf-8"))
            if estado.get("itens"):
                log("Contexto do Estado: reaproveitando a pesquisa de hoje...")
                return estado, True
    except (OSError, ValueError):
        pass
    log("Pesquisando o contexto do Estado (uma vez para todos os órgãos)...")
    estado = pesquisa.pesquisar_estado(cfg["modelo_pesquisa"], cfg["data_corte"], cfg.get("foco", ""))
    try:
        pasta.mkdir(parents=True, exist_ok=True)
        arquivo.write_text(json.dumps(estado, ensure_ascii=False, default=str), encoding="utf-8")
    except OSError:
        pass
    return estado, False


def _pastas_unicas(nomes):
    """Nome de arquivo de cada órgão, sem repetir: nomes que só diferem em acento ou pontuação não se sobrescrevem."""
    usadas, pastas = set(), []
    for nome in nomes:
        base = entrada.slug(nome)
        pasta, n = base, 2
        while pasta in usadas:
            pasta, n = f"{base}_{n}", n + 1
        usadas.add(pasta)
        pastas.append(pasta)
    return pastas


def zipar(pasta, ignorar=()):
    """O .zip da pasta de saída. ignorar: nomes (na raiz da pasta) que ficam de fora, como a entrada gravada."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as z:
        for arquivo in sorted(Path(pasta).rglob("*")):
            relativo = arquivo.relative_to(pasta)
            if arquivo.is_file() and relativo.parts[0] not in ignorar:
                z.write(arquivo, relativo)
    return buffer.getvalue()
