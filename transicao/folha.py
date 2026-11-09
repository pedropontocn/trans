"""Folha de pessoal por órgão, do Caderno de RH da SEPLAG (bases embutidas em bases_embutidas/folha_rh_AAAA-MM.csv,
gerada por scripts/caderno_rh.py). Entra no dossiê de cada secretaria como dado oficial, por código: vínculos ativos,
dispêndio do mês, remuneração média e quantos são servidores efetivos. O que não é efetivo (cargo em comissão,
temporário, requisitado e outros) é o que sai ou pode sair na troca de governo: é a medida do risco de apagão."""
import csv
import json
import os
from functools import lru_cache
from pathlib import Path

PASTA_BASES = Path(__file__).resolve().parent.parent / "bases_embutidas"
APELIDOS = {"SEAPA": "SEAPPA"}            # sigla no dossiê da equipe → sigla no Caderno
MESES = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro",
         "novembro", "dezembro"]


@lru_cache(maxsize=4)
def _bases(pasta):
    """As competências embutidas, da mais recente para a mais antiga: [(competência, {sigla: linha})]."""
    saida = []
    for arquivo in sorted(Path(pasta).glob("folha_rh_*.csv"), reverse=True):
        with open(arquivo, encoding="utf-8") as f:
            linhas = {l["sigla"].upper(): l for l in csv.DictReader(f)}
        if linhas:
            saida.append((next(iter(linhas.values()))["competencia"], linhas))
    return saida


@lru_cache(maxsize=4)
def _sucessoras(pasta):
    try:
        return json.loads((Path(pasta) / "siglas_2026.json").read_text(encoding="utf-8"))["sucessoras"]
    except (OSError, ValueError, KeyError):
        return {}


def linha(sigla, pasta=None):
    """A linha da folha do órgão, ou None. Vale sempre o nome mais atualizado: órgão que saiu do Caderno mais recente
    e tem sucessora conhecida (bases_embutidas/siglas_2026.json, com a fonte) usa a linha da sucessora, marcada em
    "sucessao"; sem sucessora conhecida, fica com o último Caderno em que apareceu, marcado em "fora_do_mais_recente"."""
    sigla = (sigla or "").strip().upper()
    sigla = APELIDOS.get(sigla, sigla)
    pasta = str(pasta or os.getenv("PASTA_BASES") or PASTA_BASES)
    bases = _bases(pasta)
    if not bases:
        return None
    suc = _sucessoras(pasta).get(sigla)
    if sigla not in bases[0][1] and suc and suc["atual"] in bases[0][1]:
        l = dict(bases[0][1][suc["atual"]])
        l["fora_do_mais_recente"] = ""
        l["sucessao"] = dict(suc, antiga=sigla)
        return l
    for competencia, linhas in bases:
        if sigla in linhas:
            l = dict(linhas[sigla])
            l["fora_do_mais_recente"] = bases[0][0] if competencia != bases[0][0] else ""
            l["sucessao"] = None
            return l
    return None


def _extenso(competencia):
    ano, mes = competencia.split("-")
    return f"{MESES[int(mes) - 1]} de {ano}"


def _reais(v):
    inteiro, _, dec = f"{float(v):,.2f}".partition(".")
    return f"R$ {inteiro.replace(',', '.')},{dec}"


def _int(v):
    return f"{int(float(v)):,}".replace(",", ".")


def competencia_extenso(l):
    return _extenso(l["competencia"])


def itens(sigla, pasta=None):
    """Os fatos da folha para o dossiê do órgão (itens brutos, bloco "pessoal"), ou lista vazia."""
    l = linha(sigla, pasta)
    if not l:
        return []
    quando = competencia_extenso(l)
    base = {"bloco": "pessoal", "camada": "orgao", "fonte": f"Caderno de RH (SEPLAG), folha de {quando}",
            "data_fonte": quando, "url": l["url"], "trecho": "", "tipo_fonte": "dado_oficial", "confianca": "alta",
            "checagem": "conferido"}
    nome = l["sigla"]
    fatos, aviso = [], []
    if suc := l["sucessao"]:
        texto = (f"{suc['antiga']} {suc['como']}; no Caderno de RH de {quando}, a secretaria aparece como {nome}, e os "
                 f"números da folha são os de toda a {nome}.")
        if suc.get("oficial"):                   # confirmada na PLOA 2027, base oficial embutida
            aviso = [dict(base, fonte="Projeto de Lei Orçamentária 2027 (PLOA), Volume II", url=suc.get("fonte", ""),
                          data_fonte="2026", tipo_fonte="documento_oficial",
                          afirmacao=f"{texto} {suc['oficial'][0].upper()}{suc['oficial'][1:]}.")]
        else:                                    # só em notícia: entra com a fonte e o rótulo de imprensa
            aviso = [dict(base, fonte="Imprensa: " + suc["fonte"].split("/")[2].removeprefix("www."), url=suc["fonte"],
                          data_fonte="2026", tipo_fonte="imprensa", confianca="media", checagem="", afirmacao=texto)]
    fatos += [f"Em {quando}, {nome} tinha {_int(l['vinculos_ativos'])} vínculos ativos, com dispêndio de "
             f"R$ {l['dispendio_mes_mi'].replace('.', ',')} milhões na folha do mês e remuneração média de "
             f"{_reais(l['remuneracao_media'])}."]
    if l["efetivos_na_tabela_8"] == "sim":
        fatos.append(f"Desses vínculos, {_int(l['efetivos'])} {'é de servidor efetivo/concursado' if l['efetivos'] == '1' else 'são de servidores efetivos/concursados'}, com idade média de "
                     f"{l['idade_media_efetivos']} anos e {l['tempo_exercicio_medio_efetivos']} anos de exercício em média; "
                     f"os outros {_int(l['nao_efetivos'])} ({l['pct_nao_efetivos'].replace('.', ',')}%) são cargos em "
                     "comissão, temporários, requisitados ou de outro vínculo não efetivo.")
    else:
        fatos.append(f"{nome} não aparece na tabela de servidores efetivos por órgão do Caderno de RH de {quando}: "
                     f"nenhum dos {_int(l['vinculos_ativos'])} vínculos ativos é de servidor efetivo/concursado; todos são "
                     "cargos em comissão, temporários, requisitados ou de outro vínculo não efetivo.")
    if l["fora_do_mais_recente"]:
        fatos.append(f"{nome} não aparece no Caderno de RH de {_extenso(l['fora_do_mais_recente'])}, o mais recente; "
                     f"os números acima são os do último Caderno em que aparece, de {quando}.")
    return aviso + [dict(base, afirmacao=f) for f in fatos]


def quadro(sigla, pasta=None):
    """Os números da folha para a tabela do capítulo de pessoal, ou None."""
    l = linha(sigla, pasta)
    if not l:
        return None
    return {"competencia": competencia_extenso(l), "url": l["url"], "vinculos": _int(l["vinculos_ativos"]),
            "efetivos": _int(l["efetivos"]), "nao_efetivos": _int(l["nao_efetivos"]),
            "pct_nao_efetivos": f"{l['pct_nao_efetivos'].replace('.', ',')}%",
            "folha_mes": f"R$ {l['dispendio_mes_mi'].replace('.', ',')} mi",
            "remuneracao_media": _reais(l["remuneracao_media"]), "pct": float(l["pct_nao_efetivos"] or 0),
            "fora_do_mais_recente": _extenso(l["fora_do_mais_recente"]) if l["fora_do_mais_recente"] else "",
            "sigla": l["sigla"], "sucessao": l["sucessao"]}
