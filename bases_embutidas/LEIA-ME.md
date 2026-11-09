# Bases embutidas

Dados oficiais que o app usa sozinho, por código, sem passar pelo modelo.

- `folha_rh_AAAA-MM.csv`: folha de pessoal por órgão, do **Caderno de RH** mensal da SEPLAG
  (https://www.rj.gov.br/gesperj/). Por sigla: vínculos ativos, dispêndio do mês, remuneração média, servidores
  efetivos (com idade e tempo de exercício médios) e os não efetivos (cargo em comissão, temporário, requisitado e
  outros). Órgão que não aparece na tabela de efetivos do Caderno não tem servidor efetivo lotado. O app usa o arquivo
  mais recente.

Para atualizar a folha, baixe o Caderno do mês e rode:

    python scripts/caderno_rh.py Caderno_de_RH-Mes2026.pdf 2026-MM "URL do PDF no site da SEPLAG"

Limites do Caderno: não cruza órgão com tipo de vínculo (o não efetivo junta comissionados, temporários e
requisitados) e não cobre PGE, DPGE e Cehab. A pasta pode ser trocada pela variável `PASTA_BASES`.

## Contexto do Estado (`contexto_estado.json`)

A pesquisa do contexto do Estado (situação fiscal, orçamento, órgãos de controle, prioridades do governo eleito) que
serve a todas as secretarias. O app usa esta, sem custo, em vez de pesquisar a cada rodada. A atual foi pesquisada
pelo próprio app em 08/11/2026, com os links conferidos por código.

Para atualizar: rode uma análise com "Pesquisar de novo o contexto do Estado" marcado. O `.zip` sai com um
`contexto_estado.json` novo; troque o arquivo desta pasta por ele. `ESTADO_EMBUTIDO=0` nos Secrets desliga o uso.
