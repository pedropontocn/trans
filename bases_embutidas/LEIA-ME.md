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
