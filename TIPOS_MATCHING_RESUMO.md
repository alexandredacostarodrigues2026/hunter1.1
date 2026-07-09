# Tipos de Matching — Resumo

Versão enxuta de `REGRAS_MATCHING.md` (ver lá os detalhes/critérios completos). Atualizar os dois sempre que um Tipo mudar.

> Numeração renomeada em 2026-07-09 (Tipo 1→D1, Tipo 2→D2, Tipo 3→A1, Tipo 3.1→A2, Tipo 3.2→A3, Tipo 3.3→A4, Tipo 3.4→A5, Tipo 4→D3, Tipo 5→D4). Duas famílias: **D** (Direto, mesma nota) e **A** (Aprendizado, dicionário histórico).

| Tipo | Critério | Mesma CHV_NFE? | Mesmo ano? |
|---|---|:---:|:---:|
| D1 | Mesmo GTIN/EAN + similaridade > 90% | Sim | — |
| D2 | Mesmo Valor Total do item (VL_ITEM, não da nota) + similaridade > 60% | Sim | — |
| A1 | Aprendizado: CNPJ + código + ano | Não | Sim |
| A2 | Aprendizado: CNPJ + descrição exata + ano | Não | Sim |
| A3 | Aprendizado: CNPJ + código (sem exigir ano) | Não | Não |
| A4 | Aprendizado: CNPJ + descrição exata (sem exigir ano) | Não | Não |
| A5 | Aprendizado: só descrição exata (sem exigir CNPJ nem ano) | Não | Não |
| D3 | Nota íntegra: mesma contagem de itens da nota **e** mesma soma de VL_ITEM da nota (XML × SPED) + similaridade > 70% | Sim | — |
| D4 | Só similaridade > 70%, sem GTIN/valor/integridade | Sim | — |
| ND | Não Declarado — CHV_NFE não está na BC1 | — | — |
| NM | Sem Match — CHV_NFE está na BC1, item não casou | — | — |

Ordem de execução: D1 → D2 → A1 → A2 → A3 → A4 → A5 → D3 → D4 (cada nível só tenta casar o que sobrou do anterior).

"—" = não é um critério aplicável a esse Tipo (D1/D2/D3/D4 já operam dentro da mesma nota por definição; ND/NM são status, não critério de match).
