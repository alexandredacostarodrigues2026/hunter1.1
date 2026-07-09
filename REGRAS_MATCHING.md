# Regras de Matching (BC2 × BC1 → BC3)

> Fonte única e sempre atualizada dos critérios de cada Tipo do motor de
> Matching. Sempre que `matching.py` mudar (novo tipo, limiar ajustado, ordem
> de execução alterada), atualizar este arquivo na mesma edição, em todas as
> operações (ver `OPERACOES/*/ESSENCIAL/app/matching.py` — código-fonte em
> `geraldo_2020_2024`, sincronizado para `PB2`, `cometa` e `_MODELO_OPERACAO`).

Implementação de referência: `matching.py` (docstring do módulo + função
`executar_matching()`).

> **Numeração renomeada em 2026-07-09** (Tipo 1→D1, Tipo 2→D2, Tipo 3→A1,
> Tipo 3.1→A2, Tipo 3.2→A3, Tipo 3.3→A4, Tipo 3.4→A5, Tipo 4→D3, Tipo 5→D4).
> Ver `HIERARQUIA_TIPOS_TP_ALEXANDRE_vs_TP_IA.md` para a proposta original e
> o raciocínio. Critérios, limiares e ordem de execução não mudaram — só os
> nomes/rótulos (inclusive os valores gravados em `MATCH_TIPO` no banco).

## Visão geral

Cruza a BC2 (XML — itens de Emissão de Terceiros) com a BC1 (SPED —
`sped_entradas_terceiros`) para produzir a BC3, sem depender de `NUM_ITEM`
como chave — a ordem sequencial dos itens no XML do fornecedor não
necessariamente bate com a ordem de escrituração no SPED do declarante.

Duas famílias:

- **Família D (Direto)** — D1, D2, D3, D4 — casam sempre **dentro da mesma
  `CHV_NFE`**.
- **Família A (Aprendizado)** — A1, A2, A3, A4, A5 — dicionário de
  aprendizado histórico e **não exigem a mesma `CHV_NFE`** — recuperam
  inclusive itens cuja nota inteira não está declarada (`nd`).

Cada nível só tenta casar o que sobrou do nível anterior.

## Ordem de execução e critérios

| Ordem | Tipo | Critério | Limiar | Exige mesma CHV_NFE? | Roda sobre |
|---|---|---|---|---|---|
| 1 | **D1** | mesmo EAN/GTIN (`COD_BARRA` SPED == `cean` XML, normalizados) **e** similaridade de descrição normalizada (`xprod` × `DESCR_ITEM`) | `LIMIAR_D1 = 0,90` | Sim | todos os itens |
| 2 | **D2** (fallback) | mesmo Valor Total do item (`VL_ITEM` idêntico — valor daquela linha/produto, não da nota inteira) **e** similaridade de descrição normalizada | `LIMIAR_D2 = 0,60` | Sim | sobra do D1 |
| 3 | **A1** (aprendizado histórico) | dicionário construído só com matches confirmados de D1/D2: `CNPJ_EMITENTE + COD_ITEM (XML) + ANO_EMISSAO` | sem limiar (lookup exato) | Não | `nd`/`nm` restantes |
| 4 | **A2** (aprendizado por descrição) | igual ao A1, trocando `COD_ITEM` pela descrição exata normalizada do XML (`xprod`): `CNPJ_EMITENTE + DESCR_ITEM (normalizada) + ANO_EMISSAO` | sem limiar | Não | `nd`/`nm` restantes após A1 |
| 5 | **A3** (aprendizado por código, sem ano) | fallback do A1: mesma chave, mas **sem** `ANO_EMISSAO` — `CNPJ_EMITENTE + COD_ITEM` | sem limiar | Não | `nd`/`nm` restantes após A2 |
| 6 | **A4** (aprendizado por descrição, sem ano) | fallback do A2: mesma chave, mas **sem** `ANO_EMISSAO` — `CNPJ_EMITENTE + DESCR_ITEM (normalizada)` | sem limiar | Não | `nd`/`nm` restantes após A3 |
| 7 | **A5** (aprendizado só por descrição) | fallback do A4: relaxa também o `CNPJ_EMITENTE` — chave só `DESCR_ITEM (normalizada)` | sem limiar | Não | `nd`/`nm` restantes após A4 |
| 8 | **D3** (integridade de nota) | restringe às `CHV_NFE` "íntegras": mesma **contagem de itens da nota** (nº de linhas XML == nº de linhas SPED, para aquela `CHV_NFE`) **e** mesma **soma de `VL_ITEM` da nota** (somatório de todos os itens do XML == somatório de todos os itens do SPED, para aquela `CHV_NFE`) — e casa, só dentro dessas notas, por similaridade normalizada, 1-para-1 | `LIMIAR_D3 = 0,70` | Sim (dentro das notas íntegras) | `nd`/`nm` restantes após A5 |
| 9 | **D4** (último recurso) | casa só por similaridade de descrição normalizada, 1-para-1, sem exigir GTIN, valor ou integridade de nota | `LIMIAR_D4 = 0,70` | Sim | `nd`/`nm` restantes após D3 |

Funções correspondentes em `matching.py`: `_match_d1_por_nota`,
`_match_d2_por_nota`, `_match_a1`, `_match_a2`, `_match_a3`,
`_match_a4`, `_match_a5`, `_match_d3_por_nota`,
`_match_d4_por_nota`.

## Dicionário de aprendizado (A1/A2/A3/A4/A5)

- Construído **a cada execução do Matching**, exclusivamente a partir das
  linhas já confirmadas como `D1`/`D2` naquela mesma rodada — nunca a
  partir de A1/A2/A3/A4/A5 (evita encadeamento/loop de aprendizado
  sobre aprendizado).
- Em caso de chave repetida (mais de um par histórico para a mesma chave),
  prevalece a primeira ocorrência (`drop_duplicates`).
- Aplica-se tanto a itens `nd` (nota inteira não declarada) quanto `nm`
  (nota declarada, item sem match) — requisito explícito: o padrão de
  escrituração de um fornecedor/código pode ser reconhecido mesmo quando a
  nota específica nem consta na declaração.
- A1/A2 exigem o mesmo `ANO_EMISSAO` (dígitos 3-4 da `CHV_NFE`, campo
  "AA" da chave de acesso). A3/A4 existem porque essa exigência de ano
  pode deixar sem recuperação um fornecedor/código 100% reconhecido em um
  ano mas sem nenhuma âncora D1/D2 confirmada no ano da nota pendente —
  ver `memoria/2026-07-08.md` para o caso real que motivou o A3/A4.
- A5 relaxa mais um degrau: nem `ANO_EMISSAO` nem `CNPJ_EMITENTE` —
  só a descrição normalizada do XML. É o nível mais amplo/permissivo da
  família de aprendizado por descrição (risco maior de falso positivo entre
  fornecedores diferentes que descrevem o produto igual, por isso roda por
  último dentro dessa família, só sobre o que sobrou de todos os anteriores).

## Não Declarados e Não Matches (status antes de A1 em diante)

- `nd` (Não Declarado) — a `CHV_NFE` inteira não aparece na BC1.
- `nm` (Não Match) — a `CHV_NFE` existe na BC1, mas o item não passou nem no
  D1 nem no D2.

Itens `nd`/`nm` recuperados por qualquer um dos A1, A2, A3, A4, A5,
D3 ou D4 mudam de status para
`A1`/`A2`/`A3`/`A4`/`A5`/`D3`/`D4`
respectivamente. Os que não encontram correspondência em nenhum deles mantêm
`ND`/`NM`.

## Consistência de unicidade

Um item da BC1 (declaração) não pode ser "consumido" por dois matches
diferentes (1 para 1) — vale entre D1, D2, D3 e D4 (os que
consomem uma linha específica da BC1). O A1/A2/A3/A4/A5 é só lookup
histórico e não consome linha da BC1, não entra nessa exclusão.

## Correções de dados que afetam o Matching

- **Vírgula decimal do SPED**: `VL_ITEM` do lado SPED (BC1) pode vir com
  vírgula decimal (`"33,6"`), enquanto o XML (BC2) sempre usa ponto. A
  comparação numérica usa `matching._valor_numerico()` (substitui vírgula por
  ponto antes de `pd.to_numeric()`) em `_match_d2_por_nota()` e
  `_integridade_por_nota()` — sem isso, `pd.to_numeric()` descarta o valor
  como `NaN` e quebra silenciosamente o D2 e o D3.
- **Caracteres especiais na descrição**: `DESCR_ITEM`/`xprod` podem vir com
  pontuação divergente entre XML e SPED, ou entre duas notas do mesmo
  fornecedor, para o mesmo produto (`"REF 0065/01"` vs `"REF 0065-01"`,
  `"SH#400ML"` vs `"SH 400ML"`). `matching._normalizar_descricao()` (maiúsculas
  + remove tudo que não é letra/número/espaço, via `re.sub(r"[^\w\s]|_", " ",
  ...)`, colapsando espaços) é aplicada antes de qualquer comparação de
  descrição: na matriz de similaridade (D1/D2/D3/D4, `_matriz_similaridade`)
  e nas chaves exatas do dicionário de aprendizado por descrição (A2/A4/A5,
  `_chave_a2/_a4/_a5`). Sem isso, um caractere de
  pontuação sozinho derrubava a similaridade (D1/D2/D3/D4) ou quebrava a
  igualdade exata (A2/A4/A5), gerando `NM`/`ND` que na verdade eram o
  mesmo produto. Validado nas 3 operações: `NM` caiu 21,5%
  (geraldo), 70% (cometa) e 62% (PB2) — persistido em produção nas 3 bases.

## Histórico de mudanças

- 2026-07-07: implementados Tipo 3, Tipo 3.1, Tipo 4, Tipo 5 (nomes da época
  — ver renomeação de 2026-07-09 abaixo); correção da vírgula decimal do
  SPED; ajuste de `LIMIAR_TIPO4`/`LIMIAR_TIPO5` de 0,50 para 0,70.
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
- 2026-07-09: discutida e descartada a inversão de ordem (Tipo 4/5 antes do
  aprendizado 3.x) — simulação real mostrou que só piora (rebaixa itens de
  evidência forte pra fraca e, em geraldo, perde 15 matches líquidos por
  causa da atribuição gulosa 1-para-1). Testado especificamente Tipo 3.4 vs
  Tipo 4/5 (a dupla mais discutível) — zero itens mudam de rótulo nas 3
  operações, então a ordem entre eles é irrelevante na prática hoje. Também
  avaliada e descartada a ideia de um "Tipo 6" (consolidação N-para-1 de
  linhas "SORTIDO" do SPED) — real e mensurável (~1.754 itens candidatos em
  geraldo), mas não implementada por decisão do usuário. Implementada
  `_normalizar_descricao()` (remove caracteres especiais antes de comparar
  descrição), aplicada em todos os Tipos que usam texto — ver seção
  "Correções de dados que afetam o Matching".
- 2026-07-09 (mesmo dia): renomeados todos os Tipos pra nomenclatura
  `tp_ia` (Tipo 1→D1, Tipo 2→D2, Tipo 3→A1, Tipo 3.1→A2, Tipo 3.2→A3,
  Tipo 3.3→A4, Tipo 3.4→A5, Tipo 4→D3, Tipo 5→D4) — ver
  `HIERARQUIA_TIPOS_TP_ALEXANDRE_vs_TP_IA.md`. Renomeados também as funções
  internas de `matching.py` (`_match_tipoN_...` → `_match_dN_.../_match_aN`),
  os limiares (`LIMIAR_TIPON` → `LIMIAR_DN`), os KPIs do painel
  (`interface.py`) e os totais lidos do banco (`loader.consultar_totais_bc3`).
  Critérios/limiares/ordem não mudaram, só os nomes — inclusive os valores
  gravados em `MATCH_TIPO`. Re-persistido nas 3 operações reais (bug real
  encontrado e corrigido no processo: `_BANCO_PATH` em `loader.py` não
  respeita `HUNTER_OPERACAO_DIR`, só `CONFIG_PATH` respeita — ver memória
  `feedback_hunter_operacao_dir_banco_path`).
