"""Análise da Transição: uma tela só. Sobe o .zip, escolhe os órgãos, processa e baixa os resultados.

Execução local:
    pip install -r requirements.txt
    streamlit run app.py
A chave da API fica no arquivo .env (ANTHROPIC_API_KEY=...) ou nos Secrets do Streamlit.
"""
import csv
import hashlib
import importlib
import sys
import tempfile
import threading
import zipfile
from datetime import date, datetime
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

import transicao
from transicao import analise, entrada
from transicao.config import MODELOS

load_dotenv()

# custo por secretaria com dossiê enviado, em US$ (Sonnet no auxiliar, Opus nos riscos e agentes): estimativa a partir
# das chamadas do modelo novo; quando o app pesquisa o dossiê, soma cerca de 50%
SEM_DOSSIE = "— (o app pesquisa)"
CUSTO_POR_ORGAO = {True: (0.7, 1.2), False: (1.3, 2.2)}
PESO_COM_PESQUISA = 1.5


@st.cache_resource(show_spinner=False)
def _trabalhos():
    """A análise roda num fio à parte e fica na memória do app (todas as abas veem) até ele reiniciar."""
    return {}


def trabalho_atual():
    t = _trabalhos()
    return t[max(t)] if t else None


def iniciar(orgaos, cfg, economico):
    atual = trabalho_atual()
    if atual and atual["situacao"] == "rodando":
        raise RuntimeError("já há uma análise em andamento")
    trabalho = {"id": datetime.now().strftime("%Y%m%d%H%M%S%f"), "situacao": "rodando", "inicio": datetime.now(),
                "fim": None, "log": [], "total": len(orgaos), "economico": economico, "zip": None, "erro": None,
                "saida": Path(tempfile.mkdtemp(prefix="analise_"))}
    _trabalhos()[trabalho["id"]] = trabalho
    threading.Thread(target=_executar, args=(trabalho, orgaos, dict(cfg), economico), daemon=True).start()


def _executar(trabalho, orgaos, cfg, economico):
    log = lambda linha: trabalho["log"].append(f"{datetime.now():%H:%M:%S} {linha}") if len(trabalho["log"]) < 5000 else None
    try:
        analise.rodar_orgaos(orgaos, cfg, trabalho["saida"], economico=economico, log=log)
        trabalho["zip"] = analise.zipar(trabalho["saida"])
        trabalho["situacao"] = "concluído"
    except Exception as e:
        trabalho["erro"] = f"{type(e).__name__}: {e}"[:500]
        trabalho["situacao"] = "erro"
    finally:
        trabalho["fim"] = datetime.now()


# --- CÓDIGO ATUALIZADO --------------------------------------------------------------------------
# O Streamlit Cloud recarrega o app.py quando o repositório muda, mas mantém na memória os módulos de transicao/ já
# importados. Sem isto, a tela nova rodaria com a lógica antiga até alguém reiniciar o app.
PASTA_CODIGO = Path(__file__).resolve().parent / "transicao"
ORDEM_MODULOS = ["config", "modelo", "entrada", "pesquisa", "verificacao", "confronto", "produtos", "riscos",
                 "documentos", "painel", "lote_api", "analise"]


def _assinatura_codigo():
    return hashlib.md5(b"".join(p.read_bytes() for p in sorted(PASTA_CODIGO.glob("*.py")))).hexdigest()


@st.cache_resource(show_spinner=False)
def _codigo_carregado():
    return {"assinatura": _assinatura_codigo()}


def atualizar_codigo():
    """Recarrega transicao/ se o código mudou desde que foi carregado. Com análise em andamento, espera ela acabar
    (recarregar no meio trocaria as funções que a análise está usando). Devolve True se o código está atualizado."""
    carregado = _codigo_carregado()
    atual = _assinatura_codigo()
    if carregado["assinatura"] == atual:
        return True
    rodando = trabalho_atual()
    if rodando and rodando["situacao"] == "rodando":
        return False
    for nome in ORDEM_MODULOS:
        modulo = sys.modules.get(f"transicao.{nome}")
        if modulo is not None:
            importlib.reload(modulo)
    importlib.reload(sys.modules["transicao"])
    carregado["assinatura"] = atual
    return True


def linhas(trabalho):
    caminho = Path(trabalho["saida"]) / "resumo.csv"
    try:
        with open(caminho, encoding="utf-8-sig") as f:
            return list(csv.DictReader(f, delimiter=";"))
    except (OSError, csv.Error):
        return []


# --- TELA ------------------------------------------------------------------------------------

st.set_page_config(page_title="Análise da Transição", page_icon="🏛️", layout="wide")
if not atualizar_codigo():
    st.warning("Há uma versão nova do código. Ela entra em uso quando a análise em andamento terminar.")
st.title("🏛️ Análise da Transição")
st.caption("Para cada secretaria, um documento curto: em uma página, diagnóstico, riscos e decisões urgentes, com "
           "anexos de fontes e vencimentos. Para o conjunto, o painel estadual de urgências e o calendário em Excel. "
           "Expõe riscos e escolhas para quem decide: não recomenda.")

with st.sidebar:
    st.header("Modelos")
    modelo_pesquisa = st.selectbox("Pesquisa em fontes públicas", MODELOS, index=MODELOS.index("anthropic/claude-haiku-5-5"),
                                   help="Busca na web e monta o dossiê. A Anthropic cobra US$ 10 por mil buscas, além dos tokens.")
    modelo_auxiliar = st.selectbox("Auxiliar", MODELOS, index=MODELOS.index("anthropic/claude-sonnet-5-5"),
                                   help="Diagnóstico, calendário, confronto com o relatório e revisão de neutralidade.")
    modelo_debate = st.selectbox("Riscos e agentes", MODELOS, index=MODELOS.index("anthropic/claude-opus-5-5"),
                                 help="Escreve a análise de riscos, faz os cinco agentes revisores e a consolidação.")
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
    st.caption(f"Versão {transicao.VERSAO}")

trabalho = trabalho_atual()


@st.fragment(run_every=15)
def andamento():
    t = trabalho_atual()
    if not t:
        return
    feitas = linhas(t)
    minutos = ((t["fim"] or datetime.now()) - t["inicio"]).total_seconds() / 60
    if t["situacao"] == "rodando":
        st.info(f"⏳ Analisando {t['total']} secretaria(s)" + (" no modo econômico" if t["economico"] else "")
                + f": {len(feitas)} pronto(s), {minutos:.0f} min até agora. Pode fechar a página: a análise continua. "
                  "Não reinicie o app nem faça merge no GitHub até terminar.")
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
                    orgaos_lidos = entrada.orgaos_do_envio([(a.name, a.getvalue()) for a in enviados], cada_pasta)
                    todos_dossies = entrada.dossies_do_envio([(a.name, a.getvalue()) for a in dossies_enviados])
                    st.session_state["dossies"] = {d["orgao"]: d for d in todos_dossies}
                    sobrando = entrada.casar_dossies(orgaos_lidos, todos_dossies)
                    # secretaria com dossiê e sem documento enviado: pode ser analisada só com o dossiê (desmarcada)
                    st.session_state["orgaos"] = orgaos_lidos + entrada.orgaos_so_com_dossie(sobrando)
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
                escolhidos = []
                for o, r in zip(orgaos, registros):
                    if not r.get("analisar"):
                        continue
                    escolhido = dict(o, nome=str(r["orgao"]).strip() or o["nome"])
                    if r.get("dossie") in dossies:                  # o dossiê escolhido na tabela vale
                        escolhido["ler_dossie"] = entrada.ler_dossie_de(dossies[r["dossie"]])
                    else:
                        escolhido.pop("ler_dossie", None)
                    escolhidos.append(escolhido)
                faixa = CUSTO_POR_ORGAO[economico]
                peso = sum(1 if o.get("ler_dossie") else PESO_COM_PESQUISA for o in escolhidos)
                st.caption(f"Estimativa: US$ {faixa[0] * peso:.0f} a {faixa[1] * peso:.0f} para "
                           f"{len(escolhidos)} secretaria(s), mais o painel estadual. O valor real sai no resumo. Não envie documentos sigilosos.")
                if st.button(f"▶️ Analisar {len(escolhidos)} secretaria(s)", type="primary", width="stretch",
                             disabled=not escolhidos):
                    cfg = {"modelo_pesquisa": modelo_pesquisa, "modelo_auxiliar": modelo_auxiliar, "modelo": modelo_debate,
                           "data_corte": data_corte.strftime("%d/%m/%Y"),
                           "foco": foco.strip(), "orgao_emissor": orgao_emissor, "unidade": unidade, "para": para}
                    try:
                        iniciar(escolhidos, cfg, economico)
                        st.rerun()
                    except RuntimeError as e:
                        st.error(str(e))
