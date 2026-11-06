"""Análise da Transição: uma tela só. Sobe o .zip, escolhe os órgãos, processa e baixa os resultados.

Execução local:
    pip install -r requirements.txt
    streamlit run app.py
A chave da API fica no arquivo .env (ANTHROPIC_API_KEY=...) ou nos Secrets do Streamlit.
A senha de acesso (APP_SENHA=...) fica no mesmo lugar; sem ela, o app abre para qualquer um que tenha o link.
"""
import csv
import hashlib
import hmac
import json
import os
import shutil
import threading
import zipfile
from datetime import date, datetime
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

from transicao import VERSAO, analise, entrada
from transicao.config import MODELOS

load_dotenv()

# custo por secretaria com dossiê enviado, em US$ (Sonnet no auxiliar, Opus nos riscos e agentes): estimativa a partir
# das chamadas do modelo novo; quando o app pesquisa o dossiê, soma cerca de 50%
SEM_DOSSIE = "— (o app pesquisa)"
CUSTO_POR_ORGAO = {True: (0.7, 1.2), False: (1.3, 2.2)}
PESO_COM_PESQUISA = 1.5


# Cada análise grava numa pasta própria em registros/ (fora do Git). O que foi enviado e escolhido fica em
# entrada.json e entrada/, e cada órgão concluído deixa seu resultado: se o app reiniciar no meio, a tela oferece
# retomar e só o que faltou é analisado de novo.
REGISTROS = Path(os.getenv("PASTA_REGISTROS") or "registros")


@st.cache_resource(show_spinner=False)
def _trabalhos():
    """A análise roda num fio à parte e fica na memória do app (todas as abas veem) até ele reiniciar."""
    return {}


def trabalho_atual():
    t = _trabalhos()
    return t[max(t)] if t else None


def montar_orgaos(enviados, dossies_enviados, cada_pasta):
    """Lê os envios (lista de (nome, bytes)) e devolve a lista de órgãos da tabela e os dossiês por rótulo."""
    orgaos_lidos = entrada.orgaos_do_envio(enviados, cada_pasta)
    todos_dossies = entrada.dossies_do_envio(dossies_enviados)
    dossies = {d["orgao"]: d for d in todos_dossies}
    sobrando = entrada.casar_dossies(orgaos_lidos, todos_dossies)
    # secretaria com dossiê e sem documento enviado: pode ser analisada só com o dossiê (desmarcada)
    return orgaos_lidos + entrada.orgaos_so_com_dossie(sobrando), dossies


def aplicar_escolhas(orgaos, dossies, escolhas):
    """escolhas: [{"indice", "nome", "dossie"}] da tabela. Devolve os órgãos a analisar, com o dossiê escolhido."""
    escolhidos = []
    for e in escolhas:
        o = orgaos[e["indice"]]
        escolhido = dict(o, nome=e["nome"] or o["nome"])
        if e.get("dossie") in dossies:
            escolhido["ler_dossie"] = entrada.ler_dossie_de(dossies[e["dossie"]])
        else:
            escolhido.pop("ler_dossie", None)
        escolhidos.append(escolhido)
    return escolhidos


def guardar_entrada(saida, enviados, dossies_enviados, cada_pasta, escolhas, cfg, economico):
    """Grava o que foi enviado e escolhido, para a análise poder ser retomada depois de um reinício."""
    for sub, arquivos in (("arquivos", enviados), ("dossies", dossies_enviados)):
        pasta = saida / "entrada" / sub
        pasta.mkdir(parents=True, exist_ok=True)
        for k, (nome, dados) in enumerate(arquivos):
            (pasta / f"{k:03d}_{Path(nome).name}").write_bytes(dados)
    (saida / "entrada.json").write_text(json.dumps(
        {"inicio": datetime.now().isoformat(timespec="seconds"), "cada_pasta": cada_pasta, "escolhas": escolhas,
         "cfg": cfg, "economico": economico, "total": len(escolhas)}, ensure_ascii=False, indent=1), encoding="utf-8")


def ler_entrada(saida):
    """O que foi gravado por guardar_entrada, ou None se a pasta não tiver uma entrada completa."""
    try:
        dados = json.loads((saida / "entrada.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    envios = {}
    for sub in ("arquivos", "dossies"):
        pasta = saida / "entrada" / sub
        envios[sub] = [(a.name[4:], a.read_bytes()) for a in sorted(pasta.iterdir())] if pasta.exists() else []
    return {**dados, **envios}


def interrompida():
    """A pasta da análise mais recente que ficou sem terminar (tem entrada e não tem o .zip), ou None."""
    if not REGISTROS.exists():
        return None
    for pasta in sorted(REGISTROS.glob("analise_*"), reverse=True):
        if (pasta / "entrada.json").exists() and not (pasta / "resultados.zip").exists():
            return pasta
        if (pasta / "resultados.zip").exists():
            return None                           # a mais recente terminou: nada a retomar
    return None


def iniciar(orgaos, cfg, economico, saida=None):
    atual = trabalho_atual()
    if atual and atual["situacao"] == "rodando":
        raise RuntimeError("já há uma análise em andamento")
    ident = datetime.now().strftime("%Y%m%d%H%M%S%f")
    saida = saida or REGISTROS / f"analise_{ident}"
    saida.mkdir(parents=True, exist_ok=True)
    trabalho = {"id": ident, "situacao": "rodando", "inicio": datetime.now(), "fim": None, "log": [],
                "total": len(orgaos), "economico": economico, "zip": None, "erro": None, "saida": saida,
                "ja_prontos": len(analise.prontos(saida))}
    _trabalhos()[trabalho["id"]] = trabalho
    threading.Thread(target=_executar, args=(trabalho, orgaos, dict(cfg), economico), daemon=True).start()
    return trabalho


def _executar(trabalho, orgaos, cfg, economico):
    log = lambda linha: trabalho["log"].append(f"{datetime.now():%H:%M:%S} {linha}") if len(trabalho["log"]) < 5000 else None
    try:
        analise.rodar_orgaos(orgaos, cfg, trabalho["saida"], economico=economico, log=log)
        trabalho["zip"] = analise.zipar(trabalho["saida"], ignorar=("entrada", "entrada.json", "resultados.zip"))
        (Path(trabalho["saida"]) / "resultados.zip").write_bytes(trabalho["zip"])
        trabalho["situacao"] = "concluído"
    except Exception as e:
        trabalho["erro"] = f"{type(e).__name__}: {e}"[:500]
        trabalho["situacao"] = "erro"
    finally:
        trabalho["fim"] = datetime.now()


def retomar(saida):
    """Remonta os órgãos a partir do que foi gravado e continua a análise na mesma pasta."""
    dados = ler_entrada(saida)
    if not dados:
        raise RuntimeError("a entrada gravada desta análise não pôde ser lida")
    orgaos, dossies = montar_orgaos(dados["arquivos"], dados["dossies"], dados["cada_pasta"])
    escolhidos = aplicar_escolhas(orgaos, dossies, dados["escolhas"])
    return iniciar(escolhidos, dados["cfg"], dados["economico"], saida=saida)


def linhas(trabalho):
    caminho = Path(trabalho["saida"]) / "resumo.csv"
    try:
        with open(caminho, encoding="utf-8-sig") as f:
            return list(csv.DictReader(f, delimiter=";"))
    except (OSError, csv.Error):
        return []


# --- TELA ------------------------------------------------------------------------------------

st.set_page_config(page_title="Análise da Transição", page_icon="🏛️", layout="wide")
st.title("🏛️ Análise da Transição")
st.caption("Para cada secretaria, um documento curto: em uma página, diagnóstico, riscos e decisões urgentes, com "
           "anexos de fontes e vencimentos. Para o conjunto, o painel estadual de urgências e o calendário em Excel. "
           "Expõe riscos e escolhas para quem decide: não recomenda.")


def _senha_do_app():
    try:
        senha = st.secrets.get("APP_SENHA")
    except Exception:                       # sem arquivo de Secrets
        senha = None
    return senha or os.getenv("APP_SENHA") or ""


# A análise em andamento e o .zip ficam na memória do app e valem para todas as abas: sem senha, quem tiver o link vê
# o andamento e baixa os documentos das secretarias.
SENHA = _senha_do_app()
if SENHA and not st.session_state.get("autenticado"):
    with st.form("entrar"):
        digitada = st.text_input("Senha de acesso", type="password")
        if st.form_submit_button("Entrar", type="primary"):
            if hmac.compare_digest(digitada.encode(), SENHA.encode()):
                st.session_state["autenticado"] = True
                st.rerun()
            st.error("Senha incorreta.")
    st.stop()
if not SENHA:
    st.sidebar.warning("Sem senha de acesso: quem tiver o link vê e baixa as análises. Defina APP_SENHA nos Secrets.")

with st.sidebar:
    st.header("Modelos")
    modelo_pesquisa = st.selectbox("Pesquisa em fontes públicas", MODELOS, index=MODELOS.index("anthropic/claude-haiku-5-5"),
                                   help="Busca na web e monta o dossiê. A Anthropic cobra US$ 10 por mil buscas, além dos tokens.")
    modelo_auxiliar = st.selectbox("Auxiliar", MODELOS, index=MODELOS.index("anthropic/claude-sonnet-5-5"),
                                   help="Diagnóstico, calendário, confronto com o relatório e revisão de neutralidade.")
    modelo_debate = st.selectbox("Riscos e agentes", MODELOS, index=MODELOS.index("anthropic/claude-opus-5-5"),
                                 help="Escreve a análise de riscos, faz os cinco agentes revisores e a consolidação.")
    modelos_agentes = st.text_input(
        "Modelos dos agentes revisores (opcional)", value="",
        placeholder="ex.: anthropic/claude-opus-5-5, gemini/gemini-2.5-pro, openai/gpt-5",
        help="Nomes de modelos (LiteLLM) separados por vírgula, que se revezam entre os cinco agentes. Vazio: todos "
             "usam o modelo de riscos. Modelos de outros provedores precisam da chave deles nos Secrets "
             "(GEMINI_API_KEY, OPENAI_API_KEY) e não entram na estimativa de custo.")
    economico = st.checkbox("Modo econômico (Batch API)", value=True,
                            help="Metade do preço dos tokens. Cada etapa espera a fila da Anthropic: o total leva de "
                                 "uma a algumas horas, com todos os órgãos em paralelo.")
    st.header("Análise")
    data_corte = st.date_input("Data de corte", value=date.today(), format="DD/MM/YYYY")
    foco = st.text_input("Foco (opcional)", placeholder="ex.: contratos que vencem até março")
    with st.expander("Cabeçalho do documento"):
        orgao_emissor = st.text_input("Órgão", value="Equipe de Transição")
        unidade = st.text_input("De (unidade)", value="")
        para = st.text_input("Para", value="")
    st.caption(f"Versão {VERSAO}")

trabalho = trabalho_atual()

if not trabalho and (pendente := interrompida()):
    dados = ler_entrada(pendente) or {}
    feitos = len(analise.prontos(pendente))
    st.warning(f"⚠️ A análise iniciada em {dados.get('inicio', '?')[:16].replace('T', ' ')} foi interrompida (o app "
               f"reiniciou): {feitos} de {dados.get('total', '?')} secretaria(s) já estavam prontas. "
               "Retomar continua só o que faltou, na mesma pasta.")
    col1, col2 = st.columns(2)
    if col1.button("▶️ Retomar a análise interrompida", type="primary", width="stretch"):
        try:
            retomar(pendente)
            st.rerun()
        except Exception as e:
            st.error(f"Não foi possível retomar: {type(e).__name__}: {e}")
    if col2.button("Descartar e começar outra", width="stretch"):
        shutil.rmtree(pendente, ignore_errors=True)
        st.rerun()
    st.stop()


@st.fragment(run_every=15)
def andamento():
    t = trabalho_atual()
    if not t:
        return
    feitas = linhas(t)
    minutos = ((t["fim"] or datetime.now()) - t["inicio"]).total_seconds() / 60
    if t["situacao"] == "rodando":
        st.info(f"⏳ Analisando {t['total']} secretaria(s)" + (" no modo econômico" if t["economico"] else "")
                + (f" (retomada: {t['ja_prontos']} já estavam prontas)" if t.get("ja_prontos") else "")
                + f": {len(feitas)} pronto(s), {minutos:.0f} min até agora. Pode fechar a página: a análise continua. "
                  "Se o app reiniciar, a tela oferece retomar do ponto em que parou.")
        st.progress(len(feitas) / max(t["total"], 1))
    elif t["situacao"] == "concluído":
        ok = sum(l.get("situacao") == "concluído" for l in feitas)
        custo = sum(float(l.get("custo_usd") or 0) for l in feitas)
        st.success(f"✅ Pronto em {minutos:.0f} min: {ok} de {t['total']} secretaria(s). "
                   f"Custo estimado: US$ {custo:.2f}".replace(".", ",") + " (mais a pesquisa do Estado e o painel; ver LEIA-ME).")
    else:
        st.error(f"A análise parou: {t['erro']}")
    if feitas:
        st.dataframe([{"Órgão": l["orgao"], "Situação": l["situacao"], "Itens do dossiê": l["itens_dossie"],
                       "Riscos (máx./alta)": f"{l['riscos']} ({l['riscos_maxima_alta']})" if l["riscos"] else "",
                       "Datas": l["datas_calendario"], "Confiança": l["confianca"],
                       "US$": l["custo_usd"], "Observação": l["observacao"]} for l in feitas],
                     hide_index=True, width="stretch")
    with st.expander("Registro do andamento"):
        st.code("\n".join(t["log"][-200:]) or "(começando)", language=None)
    if t["situacao"] != "rodando" and st.session_state.get("visto") != t["id"]:
        st.session_state["visto"] = t["id"]
        st.rerun(scope="app")                     # mostra o botão de download, que fica fora deste trecho


if trabalho:
    andamento()
    if trabalho["situacao"] != "rodando":
        if trabalho.get("zip"):
            st.download_button("⬇️ Baixar os resultados (.zip)", trabalho["zip"], type="primary", width="stretch",
                               file_name=f"transicao_{trabalho['inicio']:%Y-%m-%d_%H%M}.zip", mime="application/zip")
        st.button("Começar outra análise", on_click=lambda: _trabalhos().pop(trabalho["id"], None))

if not trabalho or trabalho["situacao"] != "rodando":
    if not trabalho:
        enviados = st.file_uploader("Arquivos das secretarias (.zip, Word, PDF ou Excel)",
                                    type=["zip", "docx", "pdf", "xlsx", "xls"],
                                    accept_multiple_files=True)
        modo = st.radio("Como os arquivos estão organizados?",
                        ["Cada arquivo é o resumo de um órgão", "Cada pasta é um órgão (documentos brutos)"],
                        horizontal=True,
                        help="Resumos: o nome do órgão vem do nome do arquivo. Documentos brutos: suba o .zip da pasta "
                             "que tem uma subpasta por órgão; o app lê os Word, PDF e planilhas de cada uma.")
        dossies_enviados = st.file_uploader(
            "Dossiês das secretarias (opcional: o .zip da equipe, ou Word, PDF e Markdown)", type=["zip", "docx", "pdf", "md", "txt"],
            accept_multiple_files=True,
            help="O .zip de dossiês da equipe (por sigla: pesquisa com citações, painel do SIGA/PNCP e planilha de "
                 "vencimentos) ou um arquivo por secretaria. Para o órgão que tiver dossiê, o app não pesquisa a web: "
                 "confere os links do dossiê e põe os vencimentos da planilha direto no calendário.")
        enviados, dossies_enviados = enviados or [], dossies_enviados or []
        if enviados or dossies_enviados:
            cada_pasta = modo.startswith("Cada pasta")
            assinatura = hashlib.md5(b"".join(a.name.encode() + a.getvalue() for a in enviados + dossies_enviados)
                                     + str(cada_pasta).encode()).hexdigest()
            if st.session_state.get("lidos") != assinatura:
                try:
                    st.session_state["orgaos"], st.session_state["dossies"] = montar_orgaos(
                        [(a.name, a.getvalue()) for a in enviados], [(a.name, a.getvalue()) for a in dossies_enviados],
                        cada_pasta)
                except zipfile.BadZipFile as e:
                    st.session_state["orgaos"] = []
                    st.error(f"Não foi possível abrir o .zip: {e}")
                st.session_state["lidos"] = assinatura
                st.session_state.pop("tabela", None)
            orgaos = st.session_state.get("orgaos") or []
            dossies = st.session_state.get("dossies") or {}
            so_dossie = [o for o in orgaos if o.get("so_dossie")]
            if so_dossie and enviados:
                st.caption(f"{len(so_dossie)} secretaria(s) têm dossiê, mas nenhum documento enviado: aparecem no fim da "
                           "tabela, desmarcadas. Marque as que quiser analisar só com o dossiê. Se o dossiê é de uma "
                           "secretaria que tem documento, escolha-o na coluna Dossiê da linha do documento.")
            if not orgaos:
                st.warning("Não achei nenhum órgão no envio. Confira se escolheu a organização certa acima.")
            else:
                tabela = st.data_editor(
                    [{"analisar": not o.get("so_dossie") or not enviados, "orgao": o["nome"],
                      "arquivos": ", ".join(o["arquivos"])[:200] or "— (só o dossiê)",
                      "dossie": o.get("dossie_rotulo") or SEM_DOSSIE} for o in orgaos],
                    key="tabela", hide_index=True, width="stretch", disabled=["arquivos"],
                    column_config={"analisar": st.column_config.CheckboxColumn("Analisar"),
                                   "orgao": st.column_config.TextColumn("Órgão (corrija se precisar)"),
                                   "arquivos": st.column_config.TextColumn("Arquivos ou pastas"),
                                   "dossie": st.column_config.SelectboxColumn(
                                       "Dossiê (escolha se não casou)", options=[SEM_DOSSIE] + list(dossies),
                                       required=True)})
                registros = tabela.to_dict("records") if hasattr(tabela, "to_dict") else list(tabela)
                escolhas = [{"indice": i, "nome": str(r["orgao"]).strip(), "dossie": r.get("dossie")}
                            for i, r in enumerate(registros) if r.get("analisar")]
                escolhidos = aplicar_escolhas(orgaos, dossies, escolhas)   # o dossiê escolhido na tabela vale
                faixa = CUSTO_POR_ORGAO[economico]
                peso = sum(1 if o.get("ler_dossie") else PESO_COM_PESQUISA for o in escolhidos)
                st.caption(f"Estimativa: US$ {faixa[0] * peso:.0f} a {faixa[1] * peso:.0f} para "
                           f"{len(escolhidos)} secretaria(s), mais o painel estadual. O valor real sai no resumo. Não envie documentos sigilosos.")
                if st.button(f"▶️ Analisar {len(escolhidos)} secretaria(s)", type="primary", width="stretch",
                             disabled=not escolhidos):
                    cfg = {"modelo_pesquisa": modelo_pesquisa, "modelo_auxiliar": modelo_auxiliar, "modelo": modelo_debate,
                           "modelos_agentes": [m.strip() for m in modelos_agentes.split(",") if m.strip()],
                           "data_corte": data_corte.strftime("%d/%m/%Y"),
                           "foco": foco.strip(), "orgao_emissor": orgao_emissor, "unidade": unidade, "para": para}
                    try:
                        saida = REGISTROS / f"analise_{datetime.now():%Y%m%d%H%M%S%f}"
                        saida.mkdir(parents=True, exist_ok=True)
                        guardar_entrada(saida, [(a.name, a.getvalue()) for a in enviados],
                                        [(a.name, a.getvalue()) for a in dossies_enviados], cada_pasta, escolhas, cfg,
                                        economico)
                        iniciar(escolhidos, cfg, economico, saida=saida)
                        st.rerun()
                    except RuntimeError as e:
                        st.error(str(e))
