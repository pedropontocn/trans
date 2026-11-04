# Painel de Deliberação e Análise de Transição

Aplicação em Streamlit que apoia a transição de governo na Secretaria de Estado das Cidades (SECID). A partir do
relatório de transição, um conselho de personas simulado por modelos de linguagem expõe trade-offs, conflitos e
riscos. O painel **não decide e não recomenda**: entrega um Tension Map, um memorando executivo com matriz de risco
e uma verificação automática do que foi citado.

## Como rodar

```bash
pip install -r requirements.txt
streamlit run app.py
```

A chave da API fica num arquivo `.env` na raiz do projeto, que **não** vai para o GitHub (está no `.gitignore`):

```
ANTHROPIC_API_KEY=...
```

## Como funciona uma análise

1. **Extração.** O relatório (PDF, DOCX ou XLSX) é convertido em texto. Saem as orientações de preenchimento, a
   seção 9 (pontos focais) e os e-mails. Um modelo mais barato preenche os campos da barra lateral: problema
   central, fatos, personas e lacunas.
2. **Debate (Fases 1 a 4).** O modelo do debate roda o protocolo em 1 a 5 rodadas independentes (padrão: 3). Com
   mais de uma rodada, uma chamada de consolidação agrupa os trade-offs e indica de quais rodadas veio cada um; o
   código calcula a estabilidade. Só entram no memorando os trade-offs que aparecem na maioria das rodadas; os
   demais ficam como sinais fracos.
3. **Memorando (Fase 5).** Duas páginas com síntese, os três principais trade-offs, decisões da semana, dados
   faltantes, custo de não decidir e matriz de risco. Sai em Word com cabeçalho institucional.
4. **Verificação, feita por código e não pelo modelo:**
   - trechos citados como evidência de nível 1 e 2 são procurados no relatório; o que não for encontrado vira nível 5;
   - valores em R$, percentuais e datas do memorando são conferidos no relatório;
   - citações de lei vão para uma lista de revisão da assessoria jurídica;
   - a completude do relatório (campos "a complementar", datas e valores em branco) é medida por seção;
   - a confiança da análise é calculada a partir da completude, das evidências rebaixadas e da estabilidade;
   - um modelo diferente do que escreveu o memorando revisa a **neutralidade**: se os dois polos de cada trade-off
     têm o mesmo peso e se há trechos que recomendam uma opção de forma disfarçada. Os trechos apontados são
     conferidos no memorando; os que não existem são descartados.
5. **Registro.** Cada rodada é gravada em `registros/`, com modelo, versão do prompt, insumos, resultado da
   verificação, tokens e custo. A pasta não vai para o GitHub. No Streamlit Cloud ela é apagada quando o app
   reinicia, então use o botão **Registro (.json)** para baixar e guardar a trilha de cada análise.

## Diagnóstico de lacunas e ofício (antes do debate)

Relatórios podem chegar com informações faltando ou suprimidas. Antes do debate, o botão **Diagnosticar lacunas do
relatório** procura quatro tipos de lacuna:

| Tipo | Exemplo | Como é encontrada |
|---|---|---|
| Campo em branco | "Dotação atualizada: [A complementar]" | Por código, e o modelo agrupa por assunto |
| Inconsistência | Números que não fecham; fontes que se contradizem | Pelo modelo |
| Resposta evasiva | Obra "paralisada" sem causa, prazo ou contrato | Pelo modelo |
| Omissão | Obra da base de projetos que não aparece no relatório; seção de órgãos de controle vazia | Pelo modelo, cruzando com a base de projetos (upload opcional, XLSX ou CSV) |

Cada lacuna traz um trecho do relatório ou da base que a evidencia, e o código confere esse trecho. Lacuna sem
evidência conferida fica fora do ofício. A materialidade (crítica, relevante, acessória) decide o que entra por
padrão: críticas e relevantes. A tabela é editável: dá para incluir, excluir e reescrever cada pedido.

**Pedidos já feitos.** O diagnóstico também confere, item por item, se o relatório atende os ofícios que a Equipe
de Transição já enviou (nº 02, 06, 07 e 08/2026 para todas as pastas; 03, 04, 05 e 09 para as pastas específicas,
marcados conforme o nome da secretaria). Cada item sai como atendido, parcial, não atendido ou não avaliado. Atendido
e parcial precisam de trecho do relatório, conferido por código. Antes de reiterar um item "não atendido", o código
procura no relatório termos daquele item; se encontrar, o item fica desmarcado, com aviso para conferir. Isso funciona
com qualquer formato de relatório, já que o modelo de relatório é de uso recomendado, mas não obrigatório.

O painel gera a **minuta de ofício** em Word, no padrão ofício, da Equipe de Transição ao titular da pasta, com os
reiteração dos itens não atendidos de cada ofício anterior, os demais pedidos agrupados por seção, referência aos
ofícios e canal de resposta já preenchidos, prazo de 5 dias úteis (com feriados nacionais e do RJ; confira o calendário oficial) e
um parágrafo pedindo que o órgão declare expressamente o que não existir ou não puder ser enviado. Também baixa a
matriz de lacunas em CSV.

Se houver lacunas críticas, o painel avisa antes do debate. Dá para deliberar mesmo assim; nesse caso, as lacunas
entram no contexto do debate como nível 5. Quando o órgão responder, a comparação com a análise anterior mostra o
que foi preenchido.

## Modo "Personas independentes"

No modo rápido, um único modelo simula todas as personas numa chamada, e as rodadas medem se ele é consistente.
No modo **Personas independentes**, o debate acontece de verdade:

1. **Fase 1:** cada persona propõe o seu plano numa chamada própria.
2. **Fase 2:** cada persona recebe os planos das outras e os critica.
3. **Fase 2.5:** cada persona recebe as críticas que sofreu e decide revisar, defender ou manter o plano.
4. **Fase 3:** um modelo de outra família (Gemini, por padrão) dá notas aos planos finais sem saber quem os
   propôs. O código embaralha os planos e retira deles os nomes e ids das personas.
5. **Fase 4:** o modelo do debate extrai o Tension Map do histórico real. O código confere se cada polo foi
   defendido por uma persona que de fato participou.

O histórico completo aparece na aba **Debate** e vai para o registro. Personas que não respondem ficam de fora,
com aviso; com menos de 3, o debate não acontece. Os modelos Gemini usam a `GEMINI_API_KEY` dos Secrets.

Com o Sonnet 5.5 nas personas e o Opus 5.5 na síntese e no memorando, uma análise custa cerca de US$ 0,60. O custo
exibido no painel não inclui o Gemini, que ainda não tem preço cadastrado (aparece marcado com *).

## Comparar com uma análise anterior

Para acompanhar a evolução do relatório até a posse, suba na barra lateral o **registro (.json) de uma análise
anterior** junto com o relatório novo. O painel mostra numa aba própria, e numa seção do Word:

- **relatório:** seções que ficaram completas, seções com mais pendências e valores em R$ que mudaram (por código);
- **trade-offs:** os que se mantiveram (e se mudaram de estabilidade, evidência ou posição), os novos e os que
  saíram. Um modelo barato pareia os trade-offs pelo mecanismo causal; o código descarta ids inexistentes ou repetidos;
- **matriz de risco:** riscos novos, que saíram e que mudaram de probabilidade ou impacto (por código);
- **completude e confiança**, antes e depois.

Registros gerados antes da versão 1.6 não guardam os valores do relatório; nesse caso só as pendências são comparadas.

## Custo aproximado

Com o Opus 5.5 no debate, o Sonnet 5.5 na extração e 3 rodadas, uma análise completa custa cerca de
US$ 0,50 a 0,60. O valor real de cada análise aparece no painel e no registro.

## Testes

Os testes **não chamam nenhuma API**: o modelo é substituído por uma versão falsa, e o relatório usado é fictício
(`tests/fixtures/relatorio_exemplo.md`). Rodam de graça, no computador ou no GitHub Actions.

```bash
pip install -r requirements-dev.txt
pytest -q tests
```

O GitHub Actions roda os testes a cada push na `main` e a cada pull request (`.github/workflows/testes.yml`).

## Estrutura

| Arquivo | O que é |
|---|---|
| `app.py` | O painel (Streamlit) |
| `tests/` | Testes automáticos e relatório fictício |
| `requirements.txt` | Dependências para rodar o painel |
| `requirements-dev.txt` | Dependências para rodar os testes |
| `orquestrador.py`, `validador.py`, `prompts.py` | Versão anterior, em linha de comando, com auditoria cruzada por modelos Gemini. Não é usada pelo `app.py`. |

## Cuidados

- Não envie ao painel propostas de licitação em andamento, processos sigilosos ou dados pessoais além do necessário.
  O texto vai para a API do provedor do modelo.
- O memorando é gerado com apoio de IA e diz isso no rodapé e na seção de verificação. Ele não substitui a revisão
  técnica e jurídica.
