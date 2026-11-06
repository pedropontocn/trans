"""A análise de cada órgão e o processamento de vários órgãos.

Para cada órgão: dossiê de fontes públicas → insumos → (confronto com o relatório, calendário e diagnóstico, juntos)
→ rodadas do debate → mapa de tensões verificado → memorando → revisão de neutralidade → um documento Word único.
No fim do lote: o calendário consolidado de todos os órgãos e um resumo com situação e custo de cada um.
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

from . import debate, documentos, entrada, modelo, pesquisa, produtos, verificacao
from .config import MIN_ITENS_DOSSIE, VERSAO

class ErroAnalise(Exception):
    pass


def _cenario(insumos, dossie, com_dossie=False):
    """O cenário do debate. Nas chamadas com o material em cache, o dossiê já está no começo da mensagem."""
    resumo = pesquisa.resumo_dossie(dossie)
    fatos = (pesquisa.texto_dossie(dossie) or "(sem dossiê)") if com_dossie else (
        f"Os {resumo['itens']} itens do dossiê (ids E1, E2... para o Estado e O1, O2... para o órgão) estão no "
        "material de referência, entre <dossie> e </dossie>. Use os ids como fonte.")
    sem_voz = (insumos.get("sem_voz") or "").strip()
    return (f"CENÁRIO / PROBLEMA CENTRAL:\n{insumos['problema']}\n\nFATOS:\n{fatos}\n\n"
            f"PERSONAS:\n{insumos['personas']}\n\n"
            + (f"GRUPOS AFETADOS SEM VOZ NO DEBATE (não simule a posição deles; registre a ausência):\n{sem_voz}\n\n"
               if sem_voz else "")
            + f"LACUNAS DE DADOS:\n{insumos['lacunas']}")


def _seguro(funcao, vazio):
    """Roda uma etapa complementar; se falhar, devolve o resultado vazio com o erro, sem derrubar a análise."""
    def rodar():
        try:
            return funcao()
        except Exception as e:
            return {**vazio, "erro": f"{type(e).__name__}: {e}"[:300]}
    return rodar


def _debater(cfg, mensagens, progresso):
    """As rodadas do debate. Devolve (mapa de tensões, problemas, rodadas válidas, rodadas feitas)."""
    modelo_debate, auxiliar, n = cfg["modelo"], cfg["modelo_auxiliar"], cfg.get("n_rodadas", 3)
    if n == 1:
        progresso("Debate (1 rodada)...")
        tm, _, motivo, problemas = modelo.chamar_com_validacao(
            modelo_debate, mensagens, debate.FERRAMENTA_TENSION_MAP, debate.SCHEMA_TENSION_MAP, "tension map")
        if tm is None:
            raise ErroAnalise("o debate não devolveu um mapa de tensões válido"
                              + (" (resposta cortada pelo limite de tokens)" if motivo == "length" else ""))
        return tm, problemas, [(1, tm)], 1
    progresso(f"Debate: {'até ' if cfg.get('parar_cedo') else ''}{n} rodadas independentes...")
    resultados, _ = debate.rodar_rodadas(modelo_debate, mensagens, n,
                                         modelo_checagem=auxiliar if cfg.get("parar_cedo") else None)
    validas = [(i, tm) for i, (tm, _, _) in enumerate(resultados, 1) if debate._tm_valido(tm)]
    if not validas:
        raise ErroAnalise("nenhuma rodada do debate devolveu um mapa de tensões válido")
    if len(validas) == 1:
        return validas[0][1], modelo.validar(validas[0][1], debate.SCHEMA_TENSION_MAP) + [
            "só uma rodada válida: estabilidade não medida"], validas, len(resultados)
    progresso("Consolidando as rodadas e medindo a estabilidade...")
    consolidado, _, _, problemas = modelo.chamar_com_validacao(
        auxiliar, [{"role": "system", "content": debate.PROMPT_CONSOLIDACAO},
                   {"role": "user", "content": "RODADAS:\n" + json.dumps({f"R{i}": tm for i, tm in validas},
                                                                      ensure_ascii=False)}],
        debate.FERRAMENTA_CONSOLIDACAO, debate.SCHEMA_CONSOLIDACAO, "consolidação", max_tokens=16000)
    if consolidado is None:
        return validas[0][1], ["a consolidação falhou; usando a rodada 1 sem medir estabilidade"], validas, len(resultados)
    tm = debate.aplicar_estabilidade(consolidado, validas, len(resultados), previstas=n)
    problemas = modelo.validar(tm, debate.SCHEMA_TENSION_MAP)
    if tm.get("estabilidade") is None:
        problemas.append("a consolidação não indicou de quais rodadas veio cada trade-off; estabilidade não medida")
    return tm, problemas, validas, len(resultados)


def _memorando(modelo_debate, mensagens):
    texto, _, motivo = modelo.chamar_modelo(modelo_debate, mensagens, 16000, etapa="memorando")
    for _ in range(2):                         # cortado: pede para continuar de onde parou
        if motivo != "length":
            break
        mais, _, motivo = modelo.chamar_modelo(
            modelo_debate, mensagens + [{"role": "assistant", "content": texto},
                                        {"role": "user", "content": "Continue o memorando exatamente de onde parou, "
                                         "sem repetir nada do que já escreveu e sem comentários."}],
            8000, etapa="memorando (continuação)")
        texto = texto.rstrip() + ("\n" if mais.lstrip().startswith(("|", "#", "-")) else " ") + mais.lstrip()
    return texto.strip(), motivo == "length"


def analisar_orgao(nome, texto, cfg, estado=None, progresso=None, dossie=None):
    """Analisa um órgão. texto: o relatório ou resumo do órgão (pode ser vazio). dossie: o dossiê enviado pela equipe
    (pesquisa.dossie_enviado); sem ele, o app pesquisa as fontes públicas. Devolve um dicionário com o
    documento (Word), os eventos do calendário, o registro de auditoria e os números do resumo do lote.
    Levanta ErroAnalise quando não há base para analisar (dossiê insuficiente, insumos ou debate inválidos)."""
    progresso = progresso or (lambda _t: None)
    uso = modelo.novo_uso_do_fio()            # todas as chamadas deste órgão registram aqui
    auxiliar, modelo_debate = cfg["modelo_auxiliar"], cfg["modelo"]
    relatorio, avisos = entrada.limpar_relatorio(texto) if (texto or "").strip() else ("", [])

    if dossie is None:
        progresso("Pesquisando o dossiê em fontes públicas...")
        dossie = pesquisa.montar_dossie(cfg["modelo_pesquisa"], nome, cfg["data_corte"], cfg.get("foco", ""),
                                        estado=estado)
    resumo_dos = pesquisa.resumo_dossie(dossie)
    if resumo_dos["itens"] < MIN_ITENS_DOSSIE or resumo_dos["orgao"] < 3:
        raise ErroAnalise(f"dossiê insuficiente ({resumo_dos['orgao']} itens sobre o órgão"
                          + (": confira se o arquivo traz fatos com link [título](https://...) ou a planilha de contratos)"
                             if dossie.get("origem") == "arquivo" else ")"))

    progresso("Preparando os insumos do debate...")
    campos, uso_insumos, _ = debate.preparar_insumos(auxiliar, dossie, cfg.get("foco", ""))
    uso.extend(uso_insumos)
    insumos = {c: modelo.como_texto(campos.get(c, "")) for c in ("problema", "personas", "lacunas", "sem_voz")}
    if not insumos["problema"].strip() or not insumos["personas"].strip():
        raise ErroAnalise("os insumos do debate vieram incompletos")

    # confronto, calendário e diagnóstico leem o mesmo material: na Batch API vão juntos; fora dela, em sequência
    progresso("Confrontando o relatório com as fontes, montando o calendário e o diagnóstico...")
    tarefas = [_seguro(lambda: debate.confrontar(auxiliar, dossie, relatorio),
                       {"divergencias": [], "descartadas": 0, "uso": []}),
               _seguro(lambda: produtos.extrair_calendario(auxiliar, dossie, relatorio, nome, cfg["data_corte"]),
                       {"eventos": [], "descartados": [], "uso": []}),
               _seguro(lambda: produtos.extrair_diagnostico(auxiliar, dossie, relatorio, nome),
                       {"secoes": [], "lacunas": [], "descartados": 0, "uso": []})]
    feitos = modelo._em_paralelo(tarefas) if debate.RODADAS_JUNTAS else [t() for t in tarefas]
    confronto, calendario, diagnostico = feitos
    if dossie.get("contratos"):               # vencimentos da planilha de contratos: entram por código, sem o modelo
        calendario["eventos"] = produtos.juntar_eventos(
            produtos.eventos_de_contratos(dossie["contratos"], nome, cfg["data_corte"]), calendario.get("eventos") or [])
    produtos.avaliar_riscos(calendario.get("eventos") or [], cfg["data_corte"])
    for parte in feitos:
        uso.extend(parte.pop("uso", None) or [])

    txt_confronto = debate.texto_confronto(confronto)
    cenario = _cenario(insumos, dossie)
    material = pesquisa.material_referencia(dossie, relatorio)
    mensagens = modelo.mensagens_com_cache(
        modelo_debate, debate.PROMPT_ETAPA_1, material,
        cenario + ("\n\n" + txt_confronto if txt_confronto else "") + "\n\nExecute o protocolo e registre o Tension Map.")
    tm, problemas, validas, rodadas_feitas = _debater(cfg, mensagens, progresso)

    base = "\n".join([pesquisa.texto_dossie(dossie), relatorio, insumos["problema"], insumos["lacunas"]])
    tm, evidencias = verificacao.verificar_evidencias(tm, base, dossie, relatorio)

    urgencias = produtos.pontos_de_urgencia(calendario.get("eventos") or [], dossie, confronto)
    progresso("Escrevendo o documento (riscos e decisões urgentes)...")
    cenario_completo = _cenario(insumos, dossie, com_dossie=True)
    memorando, cortado = _memorando(modelo_debate, [
        {"role": "system", "content": debate.PROMPT_ETAPA_2},
        {"role": "user", "content": cenario_completo + "\n\n" + debate.conteudo_autodeclaracao(relatorio)
         + ("\n\n" + txt_confronto if txt_confronto else "")
         + ("\n\n" + urgencias if urgencias else "")
         + "\n\nTENSION MAP (já verificado):\n" + json.dumps(tm, ensure_ascii=False, indent=2)}])
    if cortado:
        problemas.append("o memorando foi cortado pelo limite de tokens")
    numeros = verificacao.verificar_numeros(memorando, base)

    progresso("Revisando a neutralidade...")
    neutralidade = _seguro(lambda: debate.revisar_neutralidade(auxiliar, memorando, tm),
                           {"modelo": auxiliar})()
    confianca = verificacao.confianca_calculada(resumo_dos, tm.get("estabilidade"), evidencias)
    memorando = documentos.inserir_sobre_documento(
        memorando, documentos.sobre_o_documento(resumo_dos, cfg["data_corte"], confianca))

    uso_total = list(dossie.get("uso") or []) + uso
    custo, parcial = modelo.custo_estimado(uso_total)
    versao_prompt = hashlib.md5((pesquisa.PROMPT_PESQUISA + debate.PROMPT_INSUMOS + debate.PROMPT_CONFRONTO
                                 + debate.PROMPT_ETAPA_1 + debate.PROMPT_CONSOLIDACAO + debate.PROMPT_ETAPA_2
                                 + produtos.PROMPT_CALENDARIO + produtos.PROMPT_DIAGNOSTICO_ORGAO).encode()).hexdigest()[:8]
    registro_id = f"{versao_prompt}-{hashlib.md5((cenario_completo + relatorio).encode()).hexdigest()[:8]}"
    eventos = calendario.get("eventos") or []
    verificacao_md = documentos.markdown_verificacao(
        evidencias, numeros, registro_id, modelo_debate, confianca, tm, neutralidade, resumo_dos, confronto)
    texto_doc = documentos.documento_orgao(
        memorando, diagnostico, eventos, dossie, confronto,
        documentos.anexo_debate(tm, insumos["personas"]), verificacao_md)
    meta = {"orgao": cfg.get("orgao_emissor", ""), "unidade": cfg.get("unidade", ""), "para": cfg.get("para", ""),
            "assunto": nome, "tipo": "Riscos e decisões urgentes da transição", "data": documentos._data_extenso(date.today()),
            "rodape_extra": f"apoio de IA, processamento automático, reg. {registro_id}"}
    registro = {
        "id": registro_id, "orgao": nome, "gerado_em": datetime.now().isoformat(timespec="seconds"),
        "versao": VERSAO, "versao_prompt": versao_prompt,
        "modelos": {"pesquisa": cfg["modelo_pesquisa"], "auxiliar": auxiliar, "debate": modelo_debate},
        "rodadas": rodadas_feitas, "rodadas_previstas": cfg.get("n_rodadas", 3), "avisos_relatorio": avisos,
        "insumos": insumos, "dossie": json.loads(pesquisa.dossie_para_json(dossie)),
        "confronto": confronto, "diagnostico": diagnostico,
        "calendario": [{**e, "data": e["data"].isoformat()} for e in eventos],
        "calendario_descartados": calendario.get("descartados") or [],
        "tension_maps_por_rodada": {f"R{i}": t for i, t in validas}, "tension_map": tm, "memorando": memorando,
        "verificacao": {"evidencias": evidencias, "numeros": numeros, "problemas": problemas,
                        "neutralidade": neutralidade, "confianca": confianca},
        "uso_tokens": uso_total, "custo_estimado_usd": round(custo, 4), "custo_parcial": parcial,
    }
    return {"documento": documentos.gerar_docx(texto_doc, meta), "documento_md": texto_doc, "eventos": eventos,
            "descartados": [dict(d, orgao=nome) for d in calendario.get("descartados") or []],
            "registro": registro, "custo": custo, "confianca": confianca["nivel"],
            "itens_dossie": resumo_dos["itens"],
            "dossie": "enviado" if dossie.get("origem") == "arquivo" else "pesquisado", "conferidos": resumo_dos["conferidos"],
            "trade_offs": len(tm.get("trade_offs") or []),
            "observacao": "; ".join([a.replace("⚠️ ", "") for a in avisos if "cortado" in a] + problemas)[:300]}


# --- VÁRIOS ÓRGÃOS ------------------------------------------------------------------------

COLUNAS_RESUMO = ["orgao", "situacao", "dossie", "itens_dossie", "conferidos", "trade_offs", "datas_calendario", "confianca",
                  "custo_usd", "minutos", "observacao"]


def _gravar_resumo(saida, linhas, custo_estado):
    with open(saida / "resumo.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=COLUNAS_RESUMO, delimiter=";")
        w.writeheader()
        w.writerows(linhas)
    total = sum(l["custo_usd"] for l in linhas) + custo_estado
    (saida / "LEIA-ME.txt").write_text(
        "Resultados da análise dos órgãos\n\n"
        "- documentos/: um Word por órgão, com decisões, diagnóstico e anexos (fontes, debate, verificação).\n"
        "- calendario_consolidado.xlsx: as datas conferidas de todos os órgãos, numa planilha só.\n"
        "- resumo.csv: situação, números e custo de cada órgão.\n"
        "- auditoria/: o registro completo de cada análise (para conferência técnica).\n\n"
        f"Órgãos concluídos: {sum(l['situacao'] == 'concluído' for l in linhas)} de {len(linhas)}. "
        f"Custo estimado: US$ {total:.2f} (inclui US$ {custo_estado:.2f} da pesquisa sobre o Estado).\n"
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
    saida = Path(saida)
    (saida / "documentos").mkdir(parents=True, exist_ok=True)
    (saida / "auditoria").mkdir(exist_ok=True)
    fila = None
    if economico:
        from .lote_api import FilaBatch
        fila = FilaBatch(cliente=cliente_batch, prazo=time.time() + prazo_minutos * 60, log=log,
                         **({"quieto": 0.2, "intervalo": 0.2} if cliente_batch is not None else {}))
        debate.RODADAS_JUNTAS = True
        log(f"Modo econômico: Batch API, até {paralelos} órgãos ao mesmo tempo.")
    chamada = fila.completion(lambda **kw: modelo._completion_litellm(**kw)) if fila else None

    try:
        modelo.usar_completion(chamada)
        log("Pesquisando o contexto do Estado (uma vez para todos os órgãos)...")
        modelo.novo_uso_do_fio()
        estado = pesquisa.pesquisar_estado(cfg["modelo_pesquisa"], cfg["data_corte"], cfg.get("foco", ""))
        custo_estado, _ = modelo.custo_estimado(estado.get("uso") or [])
        log(f"Estado: {len(estado.get('itens') or [])} itens.")

        linhas, eventos, descartados, trava = {}, {}, {}, threading.Lock()

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
                             trade_offs=r["trade_offs"], datas_calendario=len(r["eventos"]), confianca=r["confianca"],
                             custo_usd=round(r["custo"], 3), observacao=r["observacao"])
                with trava:
                    eventos[k], descartados[k] = r["eventos"], r["descartados"]
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
        return resultado
    finally:
        modelo.usar_completion(None)
        debate.RODADAS_JUNTAS = False
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
