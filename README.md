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
