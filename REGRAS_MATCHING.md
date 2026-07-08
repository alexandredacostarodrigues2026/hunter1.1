# Regras de Matching (BC2 × BC1 → BC3)

> Fonte única e sempre atualizada dos critérios de cada Tipo do motor de
> Matching. Sempre que `matching.py` mudar (novo tipo, limiar ajustado, ordem
> de execução alterada), atualizar este arquivo na mesma edição, em todas as
> operações (ver `OPERACOES/*/ESSENCIAL/app/matching.py` — código-fonte em
> `geraldo_2020_2024`, sincronizado para `PB2`, `cometa` e `_MODELO_OPERACAO`).

Implementação de referência: `matching.py` (docstring do módulo + função
`executar_matching()`).

## Visão geral

Cruza a BC2 (XML — itens de Emissão de Terceiros) com a BC1 (SPED —
`sped_entradas_terceiros`) para produzir a BC3, sem depender de `NUM_ITEM`
como chave — a ordem sequencial dos itens no XML do fornecedor não
necessariamente bate com a ordem de escrituração no SPED do declarante.

Os Tipos 1, 2, 4 e 5 casam sempre **dentro da mesma `CHV_NFE`**. Os Tipos 3,
3.1, 3.2, 3.3 e 3.4 são um dicionário de aprendizado histórico e **não
exigem a mesma `CHV_NFE`** — recuperam inclusive itens cuja nota inteira não
está declarada (`nd`). Cada nível só tenta casar o que sobrou do nível
anterior.

## Ordem de execução e critérios

| Ordem | Tipo | Critério | Limiar | Exige mesma CHV_NFE? | Roda sobre |
|---|---|---|---|---|---|
| 1 | **Tipo 1** | mesmo EAN/GTIN (`COD_BARRA` SPED == `cean` XML, normalizados) **e** similaridade de descrição (`xprod` × `DESCR_ITEM`) | `LIMIAR_TIPO1 = 0,90` | Sim | todos os itens |
| 2 | **Tipo 2** (fallback) | mesmo Valor Total do item (`VL_ITEM` idêntico — valor daquela linha/produto, não da nota inteira) **e** similaridade de descrição | `LIMIAR_TIPO2 = 0,60` | Sim | sobra do Tipo 1 |
| 3 | **Tipo 3** (aprendizado histórico) | dicionário construído só com matches confirmados de Tipo 1/2: `CNPJ_EMITENTE + COD_ITEM (XML) + ANO_EMISSAO` | sem limiar (lookup exato) | Não | `nd`/`nm` restantes |
| 4 | **Tipo 3.1** (aprendizado por descrição) | igual ao Tipo 3, trocando `COD_ITEM` pela descrição exata do XML (`xprod`): `CNPJ_EMITENTE + DESCR_ITEM (exata) + ANO_EMISSAO` | sem limiar | Não | `nd`/`nm` restantes após Tipo 3 |
| 5 | **Tipo 3.2** (aprendizado por código, sem ano) | fallback do Tipo 3: mesma chave, mas **sem** `ANO_EMISSAO` — `CNPJ_EMITENTE + COD_ITEM` | sem limiar | Não | `nd`/`nm` restantes após Tipo 3.1 |
| 6 | **Tipo 3.3** (aprendizado por descrição, sem ano) | fallback do Tipo 3.1: mesma chave, mas **sem** `ANO_EMISSAO` — `CNPJ_EMITENTE + DESCR_ITEM (exata)` | sem limiar | Não | `nd`/`nm` restantes após Tipo 3.2 |
| 7 | **Tipo 3.4** (aprendizado só por descrição) | fallback do Tipo 3.3: relaxa também o `CNPJ_EMITENTE` — chave só `DESCR_ITEM (exata)` | sem limiar | Não | `nd`/`nm` restantes após Tipo 3.3 |
| 8 | **Tipo 4** (integridade de nota) | restringe às `CHV_NFE` "íntegras": mesma **contagem de itens da nota** (nº de linhas XML == nº de linhas SPED, para aquela `CHV_NFE`) **e** mesma **soma de `VL_ITEM` da nota** (somatório de todos os itens do XML == somatório de todos os itens do SPED, para aquela `CHV_NFE`) — e casa, só dentro dessas notas, por similaridade, 1-para-1 | `LIMIAR_TIPO4 = 0,70` | Sim (dentro das notas íntegras) | `nd`/`nm` restantes após Tipo 3.4 |
| 9 | **Tipo 5** (último recurso) | casa só por similaridade de descrição, 1-para-1, sem exigir GTIN, valor ou integridade de nota | `LIMIAR_TIPO5 = 0,70` | Sim | `nd`/`nm` restantes após Tipo 4 |

Funções correspondentes em `matching.py`: `_match_tipo1_por_nota`,
`_match_tipo2_por_nota`, `_match_tipo3`, `_match_tipo3_1`, `_match_tipo3_2`,
`_match_tipo3_3`, `_match_tipo3_4`, `_match_tipo4_por_nota`,
`_match_tipo5_por_nota`.

## Dicionário de aprendizado (Tipo 3/3.1/3.2/3.3/3.4)

- Construído **a cada execução do Matching**, exclusivamente a partir das
  linhas já confirmadas como `TIPO_1`/`TIPO_2` naquela mesma rodada — nunca a
  partir de Tipo 3/3.1/3.2/3.3/3.4 (evita encadeamento/loop de aprendizado
  sobre aprendizado).
- Em caso de chave repetida (mais de um par histórico para a mesma chave),
  prevalece a primeira ocorrência (`drop_duplicates`).
- Aplica-se tanto a itens `nd` (nota inteira não declarada) quanto `nm`
  (nota declarada, item sem match) — requisito explícito: o padrão de
  escrituração de um fornecedor/código pode ser reconhecido mesmo quando a
  nota específica nem consta na declaração.
- Tipo 3/3.1 exigem o mesmo `ANO_EMISSAO` (dígitos 3-4 da `CHV_NFE`, campo
  "AA" da chave de acesso). Tipo 3.2/3.3 existem porque essa exigência de ano
  pode deixar sem recuperação um fornecedor/código 100% reconhecido em um
  ano mas sem nenhuma âncora Tipo 1/2 confirmada no ano da nota pendente —
  ver `memoria/2026-07-08.md` para o caso real que motivou o Tipo 3.2/3.3.
- Tipo 3.4 relaxa mais um degrau: nem `ANO_EMISSAO` nem `CNPJ_EMITENTE` —
  só a descrição exata do XML. É o nível mais amplo/permissivo da família de
  aprendizado por descrição (risco maior de falso positivo entre
  fornecedores diferentes que descrevem o produto igual, por isso roda por
  último dentro dessa família, só sobre o que sobrou de todos os anteriores).

## Não Declarados e Não Matches (status antes do Tipo 3 em diante)

- `nd` (Não Declarado) — a `CHV_NFE` inteira não aparece na BC1.
- `nm` (Não Match) — a `CHV_NFE` existe na BC1, mas o item não passou nem no
  Tipo 1 nem no Tipo 2.

Itens `nd`/`nm` recuperados por qualquer um dos Tipos 3, 3.1, 3.2, 3.3, 3.4,
4 ou 5 mudam de status para
`TIPO_3`/`TIPO_3_1`/`TIPO_3_2`/`TIPO_3_3`/`TIPO_3_4`/`TIPO_4`/`TIPO_5`
respectivamente. Os que não encontram correspondência em nenhum deles mantêm
`ND`/`NM`.

## Consistência de unicidade

Um item da BC1 (declaração) não pode ser "consumido" por dois matches
diferentes (1 para 1) — vale entre Tipo 1, Tipo 2, Tipo 4 e Tipo 5 (os que
consomem uma linha específica da BC1). O Tipo 3/3.1/3.2/3.3/3.4 é só lookup
histórico e não consome linha da BC1, não entra nessa exclusão.

## Correções de dados que afetam o Matching

- **Vírgula decimal do SPED**: `VL_ITEM` do lado SPED (BC1) pode vir com
  vírgula decimal (`"33,6"`), enquanto o XML (BC2) sempre usa ponto. A
  comparação numérica usa `matching._valor_numerico()` (substitui vírgula por
  ponto antes de `pd.to_numeric()`) em `_match_tipo2_por_nota()` e
  `_integridade_por_nota()` — sem isso, `pd.to_numeric()` descarta o valor
  como `NaN` e quebra silenciosamente o Tipo 2 e o Tipo 4.

## Histórico de mudanças

- 2026-07-07: implementados Tipo 3, Tipo 3.1, Tipo 4, Tipo 5; correção da
  vírgula decimal do SPED; ajuste de `LIMIAR_TIPO4`/`LIMIAR_TIPO5` de 0,50
  para 0,70.
- 2026-07-08: implementados Tipo 3.2 e Tipo 3.3 (fallback do Tipo 3/3.1 sem
  exigir o mesmo `ANO_EMISSAO`) — motivado por um caso real na operação PB2
  (CNPJ `11372084000615`, `COD_ITEM 1010005`: notas de 2023 ficavam `nd` por
  falta de âncora Tipo 1/2 confirmada em 2023, mesmo o fornecedor/código
  sendo 100% reconhecido em 2024). Operação `cometa` passou a integrar a
  sincronização de código a partir desta data.
- 2026-07-08 (mesmo dia): implementado Tipo 3.4 (fallback do Tipo 3.3,
  relaxando também o `CNPJ_EMITENTE` — chave só pela descrição exata do
  XML). Validado em memória na base real da PB2: recuperou mais 21 itens
  (sem perda — total de itens da BC3 permaneceu 4.519).
