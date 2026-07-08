# Tipos de Matching — Resumo

Versão enxuta de `REGRAS_MATCHING.md` (ver lá os detalhes/critérios completos). Atualizar os dois sempre que um Tipo mudar.

| Tipo | Critério | Mesma CHV_NFE? | Mesmo ano? |
|---|---|:---:|:---:|
| 1 | Mesmo GTIN/EAN + similaridade > 90% | Sim | — |
| 2 | Mesmo Valor Total do item (VL_ITEM, não da nota) + similaridade > 60% | Sim | — |
| 3 | Aprendizado: CNPJ + código + ano | Não | Sim |
| 3.1 | Aprendizado: CNPJ + descrição exata + ano | Não | Sim |
| 3.2 | Aprendizado: CNPJ + código (sem exigir ano) | Não | Não |
| 3.3 | Aprendizado: CNPJ + descrição exata (sem exigir ano) | Não | Não |
| 3.4 | Aprendizado: só descrição exata (sem exigir CNPJ nem ano) | Não | Não |
| 4 | Nota íntegra: mesma contagem de itens da nota **e** mesma soma de VL_ITEM da nota (XML × SPED) + similaridade > 70% | Sim | — |
| 5 | Só similaridade > 70%, sem GTIN/valor/integridade | Sim | — |
| ND | Não Declarado — CHV_NFE não está na BC1 | — | — |
| NM | Sem Match — CHV_NFE está na BC1, item não casou | — | — |

"—" = não é um critério aplicável a esse Tipo (Tipo 1/2/4/5 já operam dentro da mesma nota por definição; ND/NM são status, não critério de match).
