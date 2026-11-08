# Dossiês embutidos

O pacote de dossiês da Equipe de Transição que o app usa sozinho, sem precisar de envio: para cada secretaria que
aparecer na análise, o app procura aqui a pesquisa com citações (`SIGLA_pesquisa.md`). A tabela
`00_CONSOLIDACAO_ESTADUAL.md` traz só sigla e nome, para ligar cada pesquisa à secretaria.

As bases de contratos do SIGA e do PNCP foram tiradas do pacote (planilhas de vencimentos, painéis e dossiês
reduzidos): trazem datas e situações defasadas. Contratos e calendário saem só do que a secretaria informou. Se um
pacote novo trouxer esses arquivos, o app os ignora.

- Para atualizar, troque o `.zip` por um mais novo (a data no nome do arquivo, `dd-mm-aaaa`, aparece na tela).
- Um pacote enviado na tela vale sobre o embutido para as secretarias que ele cobrir.
- A pasta pode ser trocada pela variável `PASTA_DOSSIES`.
