# Bases embutidas

Dados oficiais que o app usa sozinho, por código, sem passar pelo modelo.

- `folha_rh_AAAA-MM.csv`: folha de pessoal por órgão, do **Caderno de RH** mensal da SEPLAG
  (https://www.rj.gov.br/gesperj/). Por sigla: vínculos ativos, dispêndio do mês, remuneração média, servidores
  efetivos (com idade e tempo de exercício médios) e os não efetivos (cargo em comissão, temporário, requisitado e
  outros). Órgão que não aparece na tabela de efetivos do Caderno não tem servidor efetivo lotado. Para cada órgão, o
  app usa sempre o nome mais atualizado. Hoje há os Cadernos de setembro e de março de 2026.
- `siglas_2026.json`: (1) a unidade orçamentária principal de cada sigla na LOA 2026, conferida uma a uma; o caderno
  acha a secretaria por ela, mesmo quando a pasta vem só com a sigla (as vinculadas são as do mesmo órgão). (2) As
  secretarias que saíram do Caderno de RH na reforma de 2026 e a sucessora: SEAP → SEPPENRJ, SEM → SEMPI e
  SEDIPAF → SEAPPA, confirmadas na PLOA 2027; SECTI, SEDEICS e SEENEMAR → SEDES e SEIJES → SEDSODH, por notícia
  (entram com o rótulo de imprensa). A folha usa a sucessora e diz o que aconteceu e que os números são de toda a
  sucessora. Sem sucessora conhecida, fica com o último Caderno em que aparece. Só entra sucessão com fonte.

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

## Orçamento e Plano de Governo (caderno executivo)

- `loa_2026.json` e `ploa_2027.json`: por unidade orçamentária, cada ação do "Demonstrativo da despesa por programa
  de trabalho" (Volume 2, todas as fontes, R$ 1,00), com as principais atribuições da unidade. Lidos por
  `scripts/orcamento_loa.py`, que confere a soma das ações contra o total declarado de cada unidade (todas conferem).
- `plano_governo_2027_2030.json`: os trechos do Plano do Rio Real 2027-2030, com página, eixo e tema; compromissos
  são os itens de lista. Lido por `scripts/plano_governo.py` (PyMuPDF, leitura por blocos, por causa das duas colunas).

Para atualizar (LOA nova, PLOA retificada, plano revisado), rode o script com o PDF novo e troque o arquivo.
