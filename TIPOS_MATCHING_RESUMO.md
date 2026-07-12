# Tipos de Matching — Resumo

Versão enxuta de `REGRAS_MATCHING.md` (ver lá os detalhes/critérios completos). Atualizar os dois sempre que um Tipo mudar.

> Numeração renomeada em 2026-07-09 (Tipo 1→D1, Tipo 2→D2, Tipo 3→A1, Tipo 3.1→A2, Tipo 3.2→A3, Tipo 3.3→A4, Tipo 3.4→A5, Tipo 4→D3, Tipo 5→D4 — nomes válidos naquela data). D5 (consolidação N-para-1) e D6 (valor + desempate por texto) adicionados em 2026-07-10. **Renumerada em 2026-07-11** pra refletir a ordem de execução real (D5→D3, D3→D4, D4→D5; D1/D2/D6 e a família A não mudam) — ver histórico em `REGRAS_MATCHING.md`. Duas famílias: **D** (Direto, mesma nota) e **A** (Aprendizado, dicionário histórico). D6 não exige nota íntegra (diferente do D4).

| Tipo | Critério | Mesma CHV_NFE? | Mesmo ano? |
|---|---|:---:|:---:|
| D1 | Mesmo GTIN/EAN + similaridade > 90% | Sim | — |
| D2 | Mesmo Valor Total do item (VL_ITEM, não da nota) + similaridade > 60% | Sim | — |
| A1 | Aprendizado: CNPJ + código + ano | Não | Sim |
| A2 | Aprendizado: CNPJ + descrição exata + ano | Não | Sim |
| A3 | Aprendizado: CNPJ + código (sem exigir ano) | Não | Não |
| A4 | Aprendizado: CNPJ + descrição exata (sem exigir ano) | Não | Não |
| A5 | Aprendizado: só descrição exata (sem exigir CNPJ nem ano) | Não | Não |
| D3 | Consolidação N-para-1: vários itens do XML → 1 linha "sortido"/consolidada do SPED, por cobertura de radical (ponderada por raridade do token) + soma exata de VL_ITEM | Sim | — |
| D4 | Nota íntegra: mesma contagem de itens da nota **e** mesma soma de VL_ITEM da nota (XML × SPED) + similaridade > 70% | Sim | — |
| D5 | Só similaridade > 70%, sem GTIN/valor/integridade | Sim | — |
| D6 | Sem exigir nota íntegra: casa por VALOR idêntico; se o valor empatar (2+ itens), desempata por similaridade de descrição só entre os empatados — descarta apenas se a similaridade também empatar (exceto duplicatas idênticas nos dois lados, aí confirma); último recurso de tudo | Sim | — |
| ND | Não Declarado — CHV_NFE não está na BC1 | — | — |
| NM | Sem Match — CHV_NFE está na BC1, item não casou | — | — |

Ordem de execução: D1 → D2 → A1 → A2 → A3 → A4 → A5 → D3 → D4 → D5 → D6 (cada nível só tenta casar o que sobrou do anterior; a numeração da família D agora é literal com a ordem de execução). D3 é o único tipo N-para-1 (todos os outros são 1-para-1); roda antes do D4/D5 para não perder a linha consolidada do SPED para um match 1-para-1 por coincidência. D6 roda por último de tudo — é o critério com menos evidência (zero texto).

"—" = não é um critério aplicável a esse Tipo (D1/D2/D4/D5 já operam dentro da mesma nota por definição; ND/NM são status, não critério de match).

## Fator multiplicador sugerido

Adicionado em 2026-07-11: coluna `FATOR_MULTIPLICADOR_SUGERIDO` na BC3, calculada quando `VL_ITEM` bate entre XML e SPED = `_VALOR_UNIT_ORIGINAL` (unitário XML) ÷ `VALOR_UNITARIO_DECLARACAO` (unitário SPED, novo campo derivado na BC1 como `VL_ITEM/QTD`). Sinaliza divergência de unidade/embalagem (fator = N inteiro = provável caixa/fardo de N unidades). Normalizado pro inteiro mais próximo quando a diferença é só ruído de arredondamento (tolerância de 1% — item vendido por peso, ex., nunca fecha exato); fator não-inteiro que sobra da normalização é sinal de algo mais sério que embalagem, candidato a revisão manual. Calculado em D1-D6 (nunca em D3, que é N-para-1) e propagado pro A1-A5 via dicionário de aprendizado. Ver `REGRAS_MATCHING.md` para detalhes.

## DT_E_S/DT_FIN na BC3

Adicionado em 2026-07-12: colunas `DT_E_S` (data de entrada/saída efetiva, Campo 11 do C100) e `DT_FIN` (data final do período de apuração, Campo 05 do Registro 0000) trazidas da BC1 pra BC3 — mesmo tratamento de `COD_ITEM_DECLARACAO`/`DESCR_ITEM_DECLARACAO` (sentinela `'nd'`/`'nm'`, propagadas em D1-D6, herdadas via dicionário de aprendizado em A1-A5). Alicerce da hierarquia `DATA_ELEITA`/`ANO_ELEITO` do Estágio 4 (ver `docs/estagios/04_cronologia_ano_eleito.md`). Não muda nenhum critério, limiar ou contagem de match.
