# Hierarquia dos Tipos de Matching — `tp_alexandre` vs `tp_ia`

> **ADOTADO em 2026-07-09.** O `tp_ia` deixou de ser proposta — foi
> implementado em `matching.py` (funções, limiares e valores gravados em
> `MATCH_TIPO`), sincronizado nas 4 operações e re-persistido nas 3 bases
> reais (geraldo, cometa, PB2). A seção `tp_alexandre` abaixo fica só como
> registro histórico de como a numeração era antes. A fonte viva das regras
> (já com a numeração nova) é `REGRAS_MATCHING.md`.

## `tp_alexandre` — hierarquia atual (snapshot em 2026-07-09)

Numeração única e sequencial, na ordem de execução real do `matching.py`.
Cresceu de forma incremental: Tipo 1/2 primeiro, Tipo 3 depois como
dicionário de aprendizado, Tipo 3.1 para trocar a chave por descrição,
Tipo 3.2/3.3 no dia seguinte para resolver um caso real de fornecedor sem
âncora no ano (PB2, CNPJ `11372084000615`), Tipo 3.4 no mesmo dia relaxando
mais um degrau (CNPJ), e Tipo 4/5 como redes de segurança finais.

| Ordem | Tipo | Chave/critério | Mesma CHV_NFE? |
|---|---|---|:---:|
| 1 | Tipo 1 | GTIN/EAN + similaridade > 90% | Sim |
| 2 | Tipo 2 | Valor do item (VL_ITEM) + similaridade > 60% | Sim |
| 3 | Tipo 3 | Aprendizado: CNPJ + código + ano | Não |
| 4 | Tipo 3.1 | Aprendizado: CNPJ + descrição exata + ano | Não |
| 5 | Tipo 3.2 | Aprendizado: CNPJ + código (sem ano) | Não |
| 6 | Tipo 3.3 | Aprendizado: CNPJ + descrição exata (sem ano) | Não |
| 7 | Tipo 3.4 | Aprendizado: só descrição exata (sem CNPJ nem ano) | Não |
| 8 | Tipo 4 | Integridade da nota (contagem + soma de VL_ITEM) + similaridade > 70% | Sim |
| 9 | Tipo 5 | Só similaridade > 70%, sem GTIN/valor/integridade | Sim |

**Característica da hierarquia:** numeração plana (1 dimensão), que
documenta a *ordem cronológica de descoberta* de cada caso real — não a
estrutura lógica das chaves. Por isso o "3.x" mistura duas famílias
diferentes (matching direto vs. aprendizado histórico) no meio da
sequência, e dentro do próprio 3.x mistura três eixos independentes (código
× descrição, com/sem ano, com/sem CNPJ) numa numeração só.

## `tp_ia` — hierarquia proposta

Duas famílias, separadas pelo que de fato as distingue: exigir a mesma nota
(`CHV_NFE`) ou não. Dentro de cada família, os níveis formam uma escada de
especificidade explícita (o nome já diz o que exige), em vez de um número
que só faz sentido lendo a tabela.

### Família D — Direto (dentro da mesma CHV_NFE, 1 execução por item)

| Nível | Equivale a | Chave/critério |
|---|---|---|
| D1 | Tipo 1 | GTIN/EAN + similaridade > 90% |
| D2 | Tipo 2 | Valor do item + similaridade > 60% |
| D3 | Tipo 4 | Integridade da nota (contagem + soma) + similaridade > 70% |
| D4 | Tipo 5 | Só similaridade > 70% (último recurso, sem âncora) |

### Família A — Aprendizado (dicionário histórico, cross-nota)

Eixo único e explícito de especificidade da chave — cada nível remove
exatamente **uma** dimensão do anterior:

| Nível | Equivale a | Chave | Dimensão removida |
|---|---|---|---|
| A1 | Tipo 3 | CNPJ + código + ano | — (mais específico) |
| A2 | Tipo 3.1 | CNPJ + descrição + ano | troca código→descrição |
| A3 | Tipo 3.2 | CNPJ + código | remove ano |
| A4 | Tipo 3.3 | CNPJ + descrição | remove ano |
| A5 | Tipo 3.4 | só descrição | remove CNPJ |

### Ordem de execução (idêntica à atual, só renomeada)

D1 → D2 → A1 → A2 → A3 → A4 → A5 → D3 → D4

(D3/D4 continuam por último porque são as redes de segurança mais permissivas
e mais caras/arriscadas — integridade de nota e similaridade pura.)

### Assimetria notada (gap na hierarquia atual, para decisão — não implementado)

A família A tem um nível "só descrição" (A5) mas não tem o equivalente "só
código" (CNPJ removido, mantendo código). Isso não é acidente: código de
item é convenção interna de cada fornecedor, então o mesmo código em
fornecedores diferentes tende a ser coincidência, não o mesmo produto — ao
contrário da descrição, que tende a ser comparável entre
fornecedores. Recomendação: manter a assimetria (não criar um "A6 só
código"), mas deixar isso registrado para não parecer uma lacuna
esquecida.

### Por que isso ajuda

- O nome do nível já informa o critério (`A3` = "aprendizado, ainda exige
  CNPJ, já não exige ano") sem precisar decorar a tabela.
- Separa visualmente o que é "matching dentro da nota" (D) do que é
  "aprendizado cross-nota" (A) — hoje isso só existe em prosa
  (`REGRAS_MATCHING.md`), não na numeração.
- Facilita adicionar um novo nível no futuro sem forçar decimais em cascata
  (ex.: um "D5" ou "A6" tem lugar óbvio; hoje um novo caso como o do PB2
  exigiria inventar "Tipo 3.5" ou reabrir a numeração de Tipo 4/5).

### Custo de adotar

`tp_ia` é só uma reorganização de nomes/documentação. Adotá-la de fato no
código significaria renomear os valores gravados em `MATCH_TIPO`
(`TIPO_1` → `D1` etc.) em `matching.py` nas 4 operações
(`geraldo_2020_2024`, `PB2`, `cometa`, `_MODELO_OPERACAO`), no Streamlit
(interface.py, colunas exibidas) e em qualquer CSV/BC3 já persistida — não
é uma mudança trivial, então proponho tratar isso como decisão separada,
só depois de validar se a hierarquia em si faz sentido.
