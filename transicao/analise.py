"""A análise de cada secretaria e o processamento de várias.

Para cada secretaria: dossiê (enviado pela equipe ou pesquisado) → confronto com o relatório, calendário e diagnóstico
→ vencimentos com a régua de risco → análise de riscos → revisão por cinco agentes independentes → consolidação
→ conferência e prioridade por código → documento curto (montado por código) → revisão de neutralidade.
No fim do lote: o calendário consolidado, o painel estadual e um resumo com situação e custo de cada secretaria.
"""
import csv
import hashlib
import io
import json
import threading
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime
from pathlib import Path

from . import confronto as conf, documentos, entrada, modelo, painel, pesquisa, produtos, riscos, verificacao
from .config import MIN_ITENS_DOSSIE, VERSAO

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


def analisar_orgao(nome, texto, cfg, estado=None, progresso=None, dossie=None):
    """Analisa uma secretaria. texto: o relatório ou resumo enviado (pode ser vazio). dossie: o dossiê enviado pela
    equipe (pesquisa.dossie_enviado); sem ele, o app pesquisa as fontes públicas. Devolve o documento (Word), os
    eventos do calendário, os riscos (para o painel estadual), o registro de auditoria e os números do resumo.
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
    resumo_dos = pesquisa.resumo_dossie(dossie)
    if resumo_dos["itens"] < MIN_ITENS_DOSSIE or resumo_dos["orgao"] < 3:
        raise ErroAnalise(f"dossiê insuficiente ({resumo_dos['orgao']} itens sobre o órgão"
                          + (": confira se o arquivo traz fatos com link [título](https://...) ou a planilha de contratos)"
                             if dossie.get("origem") == "arquivo" else ")"))

    # confronto, calendário e diagnóstico leem o mesmo material (em cache): na Batch API vão juntos
    progresso("Diagnóstico, calendário e confronto com as fontes...")
    tarefas = [_seguro(lambda: conf.confrontar(auxiliar, dossie, relatorio),
                       {"divergencias": [], "descartadas": 0, "uso": []}),
               _seguro(lambda: produtos.extrair_calendario(auxiliar, dossie, relatorio, nome, cfg["data_corte"]),
                       {"eventos": [], "descartados": [], "uso": []}),
               _seguro(lambda: produtos.extrair_diagnostico(auxiliar, dossie, relatorio, nome),
                       {"secoes": [], "descartados": 0, "uso": []})]
    feitos = modelo._em_paralelo(tarefas) if JUNTAS else [t() for t in tarefas]
    confronto, calendario, diagnostico = feitos
    for parte, rotulo in zip(feitos, ("confronto", "calendário", "diagnóstico")):
        uso.extend(parte.pop("uso", None) or [])
        if parte.get("erro"):
            problemas.append(f"{rotulo}: {parte['erro']}")
    eventos = calendario.get("eventos") or []
    if dossie.get("contratos"):               # vencimentos da planilha de contratos: entram por código, sem o modelo
        eventos = produtos.juntar_eventos(produtos.eventos_de_contratos(dossie["contratos"], nome, cfg["data_corte"]),
                                          eventos)
    produtos.avaliar_riscos(eventos, cfg["data_corte"])
    if not any(s["itens"] for s in diagnostico.get("secoes") or []):
        raise ErroAnalise("o diagnóstico não trouxe nenhuma afirmação conferida"
                          + (f" ({diagnostico['erro']})" if diagnostico.get("erro") else ""))

    progresso("Analisando riscos e decisões...")
    vencimentos = riscos.vencimentos_numerados(eventos)
    material = riscos.material(nome, diagnostico, vencimentos, conf.texto_confronto(confronto), cfg["data_corte"])
    analise = riscos.analisar(principal, material, uso)
    if not analise.get("riscos"):
        raise ErroAnalise("a análise de riscos não devolveu riscos legíveis")
    progresso("Cinco agentes revisando a análise...")
    revisoes = riscos.revisar_por_agentes(principal, material, analise, uso)
    progresso("Consolidando...")
    final = riscos.consolidar(principal, material, analise, revisoes, uso)
    resultado = riscos.conferir_e_ordenar(final, diagnostico, vencimentos, dossie, cfg["data_corte"])
    confianca = riscos.confianca(resumo_dos, resultado["riscos"])

    ficha = produtos.ficha_contratos(eventos)
    corpo = "\n\n".join([documentos.em_uma_pagina(resultado), documentos.markdown_diagnostico(diagnostico, ficha),
                          documentos.markdown_riscos(resultado)])
    base = "\n".join([pesquisa.texto_dossie(dossie), relatorio, material])
    numeros = verificacao.verificar_numeros(corpo, base)
    progresso("Revisando a neutralidade...")
    neutralidade = _seguro(lambda: riscos.revisar_neutralidade(auxiliar, corpo, uso), {"modelo": auxiliar})()

    uso_total = list(dossie.get("uso") or []) + uso
    custo, parcial = modelo.custo_estimado(uso_total)
    versao_prompt = hashlib.md5((pesquisa.PROMPT_PESQUISA + conf.PROMPT_CONFRONTO + produtos.PROMPT_CALENDARIO
                                 + produtos.PROMPT_DIAGNOSTICO_ORGAO + riscos.PROMPT_ANALISE + riscos.PROMPT_AGENTE
                                 + riscos.PROMPT_CONSOLIDACAO).encode()).hexdigest()[:8]
    registro_id = f"{versao_prompt}-{hashlib.md5((material + relatorio).encode()).hexdigest()[:8]}"
    modelos = {"pesquisa": cfg["modelo_pesquisa"], "auxiliar": auxiliar, "debate": principal}
    texto_doc = documentos.documento_secretaria(
        resultado, diagnostico, ficha, eventos, dossie, confronto, resumo_dos,
        documentos.markdown_metodo(registro_id, modelos, resumo_dos, confianca, numeros, neutralidade, revisoes,
                                   resultado),
        documentos.sobre_o_documento(cfg["data_corte"], confianca))
    meta = {"orgao": cfg.get("orgao_emissor", ""), "unidade": cfg.get("unidade", ""), "para": cfg.get("para", ""),
            "assunto": nome, "tipo": "Diagnóstico, riscos e decisões urgentes da transição",
            "data": documentos._data_extenso(date.today()),
            "rodape_extra": f"apoio de IA, processamento automático, reg. {registro_id}"}
    para_json = lambda x: json.loads(json.dumps(x, ensure_ascii=False, default=str))
    registro = {
        "id": registro_id, "orgao": nome, "gerado_em": datetime.now().isoformat(timespec="seconds"),
        "versao": VERSAO, "versao_prompt": versao_prompt, "modelos": modelos, "avisos_relatorio": avisos,
        "dossie": json.loads(pesquisa.dossie_para_json(dossie)), "confronto": confronto, "diagnostico": diagnostico,
        "calendario": para_json(eventos), "calendario_descartados": calendario.get("descartados") or [],
        "analise_inicial": analise, "revisoes_dos_agentes": revisoes, "consolidacao": final,
        "riscos": para_json(resultado), "documento_md": texto_doc,
        "verificacao": {"numeros": numeros, "problemas": problemas, "neutralidade": neutralidade,
                        "confianca": confianca},
        "uso_tokens": uso_total, "custo_estimado_usd": round(custo, 4), "custo_parcial": parcial,
    }
    return {"documento": documentos.gerar_docx(texto_doc, meta), "documento_md": texto_doc, "eventos": eventos,
            "descartados": [dict(d, orgao=nome) for d in calendario.get("descartados") or []],
            "riscos": [dict(r, orgao=nome) for r in resultado["riscos"]], "situacao": resultado["situacao"],
            "registro": registro, "custo": custo, "confianca": confianca["nivel"],
            "itens_dossie": resumo_dos["itens"],
            "dossie": "enviado" if dossie.get("origem") == "arquivo" else "pesquisado",
            "conferidos": resumo_dos["conferidos"], "n_riscos": len(resultado["riscos"]),
            "riscos_maxima_alta": sum(r["prioridade"] in ("Máxima", "Alta") for r in resultado["riscos"]),
            "agentes": sum(not r.get("erro") for r in revisoes),
            "observacao": "; ".join([a.replace("⚠️ ", "") for a in avisos if "cortado" in a] + problemas)[:300]}


# --- VÁRIOS ÓRGÃOS ------------------------------------------------------------------------

COLUNAS_RESUMO = ["orgao", "situacao", "dossie", "itens_dossie", "conferidos", "riscos", "riscos_maxima_alta",
                  "agentes", "datas_calendario", "confianca",
                  "custo_usd", "minutos", "observacao"]


def _gravar_resumo(saida, linhas, custo_estado):
    with open(saida / "resumo.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=COLUNAS_RESUMO, delimiter=";")
        w.writeheader()
        w.writerows(linhas)
    total = sum(l["custo_usd"] for l in linhas) + custo_estado
    (saida / "LEIA-ME.txt").write_text(
        "Resultados da análise das secretarias\n\n"
        "- painel_estadual.docx: as urgências de todas as secretarias, com a mesma régua, num documento só.\n"
        "- documentos/: um Word por secretaria: em uma página, diagnóstico, riscos e decisões urgentes, anexos.\n"
        "- calendario_consolidado.xlsx: os vencimentos de todas as secretarias; a aba Prioridades vem primeiro.\n"
        "- resumo.csv: situação, números e custo de cada órgão.\n"
        "- auditoria/: o registro completo de cada análise (para conferência técnica).\n\n"
        f"Órgãos concluídos: {sum(l['situacao'] == 'concluído' for l in linhas)} de {len(linhas)}. "
        f"Custo estimado: US$ {total:.2f} (inclui US$ {custo_estado:.2f} da pesquisa sobre o Estado e do painel estadual).\n"
        "Documentos gerados com apoio de IA, sem revisão da equipe: confira antes de usar.\n", encoding="utf-8")


def _gravar_calendario(saida, todos_eventos, todos_descartados, data_corte):
    if todos_eventos:
        (saida / "calendario_consolidado.xlsx").write_bytes(documentos.calendario_xlsx(
            todos_eventos, todos_descartados, "Calendário consolidado de vencimentos críticos", data_corte))


def rodar_orgaos(orgaos, cfg, saida, economico=False, cliente_batch=None, paralelos=40, prazo_minutos=23 * 60,
                 log=print):
    """Analisa os órgãos e grava os resultados em `saida`. orgaos: lista de {"nome", "texto"} ou {"nome", "ler"}
    (ler() devolve o texto e o manifesto do que foi lido; ver entrada.orgaos_do_envio).
    No modo econômico, os órgãos rodam em paralelo e as chamadas à Anthropic vão pela Batch API (metade do preço)."""
    global JUNTAS
    saida = Path(saida)
    (saida / "documentos").mkdir(parents=True, exist_ok=True)
    (saida / "auditoria").mkdir(exist_ok=True)
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
        log("Pesquisando o contexto do Estado (uma vez para todos os órgãos)...")
        modelo.novo_uso_do_fio()
        estado = pesquisa.pesquisar_estado(cfg["modelo_pesquisa"], cfg["data_corte"], cfg.get("foco", ""))
        custo_estado, _ = modelo.custo_estimado(estado.get("uso") or [])
        log(f"Estado: {len(estado.get('itens') or [])} itens.")

        linhas, eventos, descartados, todos_riscos, situacoes, trava = {}, {}, {}, {}, {}, threading.Lock()

        def um(k, orgao):
            modelo.usar_completion(chamada)
            inicio = time.time()
            nome = orgao["nome"]
            linha = {c: "" for c in COLUNAS_RESUMO}
            linha.update(orgao=nome, situacao="erro", custo_usd=0.0)
            pasta = entrada.slug(nome)
            log(f"[{k}/{len(orgaos)}] {nome}: começando")
            try:
                texto = orgao.get("texto", "")
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
                r = analisar_orgao(nome, texto, cfg, estado=estado, dossie=dossie,
                                   progresso=lambda t: log(f"[{k}] {t}"))
                (saida / "documentos" / f"{pasta}.docx").write_bytes(r["documento"])
                (saida / "auditoria" / f"{pasta}.json").write_text(
                    json.dumps(r["registro"], ensure_ascii=False, indent=2, default=str), encoding="utf-8")
                linha.update(situacao="concluído", dossie=r["dossie"], itens_dossie=r["itens_dossie"], conferidos=r["conferidos"],
                             riscos=r["n_riscos"], riscos_maxima_alta=r["riscos_maxima_alta"], agentes=r["agentes"],
                             datas_calendario=len(r["eventos"]), confianca=r["confianca"],
                             custo_usd=round(r["custo"], 3), observacao=r["observacao"])
                with trava:
                    eventos[k], descartados[k] = r["eventos"], r["descartados"]
                    todos_riscos[k], situacoes[k] = r["riscos"], (nome, r["situacao"])
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
                _gravar_calendario(saida, [e for i in sorted(eventos) for e in eventos[i]],
                                   [d for i in sorted(descartados) for d in descartados[i]], cfg["data_corte"])
            log(f"[{k}/{len(orgaos)}] {nome} → {linha['situacao']}"
                + (f": {linha['observacao']}" if linha["observacao"] else "")
                + f" ({linha['minutos']} min, US$ {linha['custo_usd']:.2f})")
            return linha

        trabalhadores = max(1, min(paralelos, len(orgaos))) if fila else 1
        with ThreadPoolExecutor(max_workers=trabalhadores) as ex:
            resultado = list(ex.map(lambda par: um(*par), enumerate(orgaos, 1)))

        riscos_lote = [r for k in sorted(todos_riscos) for r in todos_riscos[k]]
        if riscos_lote:
            log("Montando o painel estadual...")
            modelo.novo_uso_do_fio()
            try:
                doc_painel, uso_painel = painel.painel_estadual(
                    riscos_lote, [situacoes[k] for k in sorted(situacoes)],
                    [e for k in sorted(eventos) for e in eventos[k]], cfg, linhas=[linhas[k] for k in sorted(linhas)])
                (saida / "painel_estadual.docx").write_bytes(doc_painel)
                custo_estado += modelo.custo_estimado(uso_painel)[0]
                _gravar_resumo(saida, [linhas[k] for k in sorted(linhas)], custo_estado)
            except Exception as e:
                log(f"O painel estadual não pôde ser montado: {type(e).__name__}: {e}"[:300])
        return resultado
    finally:
        modelo.usar_completion(None)
        JUNTAS = False
        if fila:
            fila.encerrar()
            log(f"Modo econômico: {fila.enviados} lote(s) enviados à Batch API.")


def zipar(pasta):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as z:
        for arquivo in sorted(Path(pasta).rglob("*")):
            if arquivo.is_file():
                z.write(arquivo, arquivo.relative_to(pasta))
    return buffer.getvalue()
