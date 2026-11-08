"""Folha de pessoal por órgão, do Caderno de RH da SEPLAG (base embutida em bases_embutidas/folha_rh_AAAA-MM.csv,
gerada por scripts/caderno_rh.py). Entra no dossiê de cada secretaria como dado oficial, por código: vínculos ativos,
dispêndio do mês, remuneração média e quantos são servidores efetivos. O que não é efetivo (cargo em comissão,
temporário, requisitado e outros) é o que sai ou pode sair na troca de governo: é a medida do risco de apagão."""
import csv
import os
from functools import lru_cache
from pathlib import Path

PASTA_BASES = Path(__file__).resolve().parent.parent / "bases_embutidas"
APELIDOS = {"SEAPA": "SEAPPA"}            # sigla no dossiê da equipe → sigla no Caderno
MESES = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro",
         "novembro", "dezembro"]


@lru_cache(maxsize=4)
def _base(pasta):
    arquivos = sorted(Path(pasta).glob("folha_rh_*.csv"))
    if not arquivos:
        return {}
    with open(arquivos[-1], encoding="utf-8") as f:                 # a competência mais recente
        return {l["sigla"].upper(): l for l in csv.DictReader(f)}


def linha(sigla, pasta=None):
    """A linha da folha do órgão, ou None."""
    sigla = (sigla or "").strip().upper()
    return _base(str(pasta or os.getenv("PASTA_BASES") or PASTA_BASES)).get(APELIDOS.get(sigla, sigla))


def _reais(v):
    inteiro, _, dec = f"{float(v):,.2f}".partition(".")
    return f"R$ {inteiro.replace(',', '.')},{dec}"


def _int(v):
    return f"{int(float(v)):,}".replace(",", ".")


def competencia_extenso(l):
    ano, mes = l["competencia"].split("-")
    return f"{MESES[int(mes) - 1]} de {ano}"


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
    fatos = [f"Em {quando}, {nome} tinha {_int(l['vinculos_ativos'])} vínculos ativos, com dispêndio de "
             f"R$ {l['dispendio_mes_mi'].replace('.', ',')} milhões na folha do mês e remuneração média de "
             f"{_reais(l['remuneracao_media'])}."]
    if l["efetivos_na_tabela_8"] == "sim":
        fatos.append(f"Desses vínculos, {_int(l['efetivos'])} são de servidores efetivos/concursados, com idade média de "
                     f"{l['idade_media_efetivos']} anos e {l['tempo_exercicio_medio_efetivos']} anos de exercício em média; "
                     f"os outros {_int(l['nao_efetivos'])} ({l['pct_nao_efetivos'].replace('.', ',')}%) são cargos em "
                     "comissão, temporários, requisitados ou de outro vínculo não efetivo.")
    else:
        fatos.append(f"{nome} não aparece na tabela de servidores efetivos por órgão do Caderno de RH de {quando}: "
                     f"nenhum dos {_int(l['vinculos_ativos'])} vínculos ativos é de servidor efetivo/concursado; todos são "
                     "cargos em comissão, temporários, requisitados ou de outro vínculo não efetivo.")
    return [dict(base, afirmacao=f) for f in fatos]


def quadro(sigla, pasta=None):
    """Os números da folha para a tabela do capítulo de pessoal, ou None."""
    l = linha(sigla, pasta)
    if not l:
        return None
    return {"competencia": competencia_extenso(l), "url": l["url"], "vinculos": _int(l["vinculos_ativos"]),
            "efetivos": _int(l["efetivos"]), "nao_efetivos": _int(l["nao_efetivos"]),
            "pct_nao_efetivos": f"{l['pct_nao_efetivos'].replace('.', ',')}%",
            "folha_mes": f"R$ {l['dispendio_mes_mi'].replace('.', ',')} mi",
            "remuneracao_media": _reais(l["remuneracao_media"]), "pct": float(l["pct_nao_efetivos"] or 0)}
