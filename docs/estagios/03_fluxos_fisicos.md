# Estágio 3 — Fluxos Físicos (Lado XML)

> Índice geral: [ESTAGIOS_PROJETO.md](../../ESTAGIOS_PROJETO.md)

## Objetivo

Reclassificar os itens de NF-e (Estágio 1) pela movimentação física **real**
da auditada, em vez do `tpnf` isolado. `tpnf` (0=entrada, 1=saída) reflete a
perspectiva de quem **emite** a NF-e, não necessariamente a da auditada: numa
ET normal (fornecedor emite, auditada é destinatária), o fornecedor registra
`tpnf=1` (saída dele) para o que é, fisicamente, uma **entrada** na
auditada. A classificação ingênua por `tpnf` isolado subestima brutalmente
as entradas físicas — validado nas 3 operações reais (ver seção "Resultado
real" abaixo).

## Entrada

- `nfe_entradas`/`nfe_saidas` (Estágio 1) — situação válida + CFOP fora da
  watchlist (`mask_principal`, ver `loader._classificar_itens_nfe()`).
- CNPJ da entidade auditada já fixado (`loader.obter_entidade_auditada()`).

## Como funciona

`loader._classificar_itens_nfe()` cruza `tpnf` com o papel da auditada na
nota (CNPJ emitente vs. destinatário, campos `fatonfe_infnfe_emit_cnpj`/
`fatonfe_infnfe_dest_cnpj` do XML), aplicando ao pé da letra a regra
definida em `r_definição entradas_saidas_xml.txt` (raiz do projeto — fonte
original desta classificação, "somente xml"):

- **`entradas_real`** — `(auditada destinatária E tpnf=1)` OU
  `(auditada emitente E tpnf=0)`.
- **`saidas_real`** — `(auditada destinatária E tpnf=0)` OU
  `(auditada emitente E tpnf=1)`.

Ambas rodam só sobre `mask_principal` (mesma base de `nfe_entradas`/
`nfe_saidas`) — situação irregular e CFOP de watchlist já foram segregados
no Estágio 1, então os grupos reais contêm só movimentação física válida.

Cada linha também ganha a coluna **`AUDITADA_PAPEL`** (`"DESTINATARIA"` ou
`"EMITENTE"`, `""` se a entidade auditada ainda não foi fixada) — usada
depois pelo Estágio 4 para decidir qual cenário da hierarquia de datas
aplicar. **Importante: `entradas_real`/`saidas_real` não é o mesmo grupo que
`PASTA_ORIGEM` (ET/EP por pasta de origem do XML)** — a regra acima roda
sobre `tpnf`+papel, então `xml_entradas_real` normalmente é majoritariamente
`PASTA_ORIGEM='ET'`, mas também inclui uma fatia de `PASTA_ORIGEM='EP'`
(auditada emitente com `tpnf=0` — ex.: devolução recebida, ver seção
"Validação contra a TABELA ENTRADAS de referência" abaixo). Ver também
`CNPJ EMIT = CNPJ DEST.txt` na pasta `regra de negócios unificadas/`, raiz
do projeto — regra correlata, mas sobre um caso específico de exclusão de
CFOP de baixa de estoque (5927/6927), não sobre a classificação
entradas/saídas em si.

## Saída

- **`xml_entradas_real`** / **`xml_saidas_real`** — persistidas via
  `loader.persistir_nfe()`, sempre criadas (mesmo vazias, ex.: entidade
  auditada ainda não fixada). Consultáveis por
  `loader.consultar_totais_entradas_saidas_real()` /
  `loader.consultar_fluxo_real(direcao, limite)`.
- Painel: `interface.render_fluxos_fisicos()` — KPIs + botões "Visualizar
  Entradas"/"Visualizar Saídas" (exclusivos entre si), prévia formatada com
  o Dicionário de Campos.

## Enriquecimento com a BC3 (desde 2026-07-14)

`loader.consultar_fluxo_real()` traz também, via `LEFT JOIN` por `ID_UNICO`
com `bc3` (Estágio 2 — Matching, mesmo helper `loader._montar_join_bc3()`
usado pelo [Estágio 4](04_cronologia_ano_eleito.md)):
`COD_ITEM_DECLARACAO`, `DESCR_ITEM_DECLARACAO`,
`FATOR_MULTIPLICADOR_SUGERIDO`, `DT_E_S`, `DT_FIN`. Não altera nem persiste
`xml_entradas_real`/`xml_saidas_real` — é só uma leitura enriquecida para
exibição, calculada a cada consulta.

Na prévia (`interface._COLUNAS_PREVIEW_FLUXOS_REAIS`), `COD_ITEM_DECLARACAO`
("Cód. Auditada", ver `DICIONARIO DE CAMPOS.txt`) e
`FATOR_MULTIPLICADOR_SUGERIDO` ("Fator Sugerido") aparecem lado a lado com o
produto do fornecedor (`fatoitemnfe_infnfe_det_prod_cprod`/`_xprod`) — só
populados quando a `bc3` já foi gerada e tem correspondência para o item.

**`bc3` é exclusivamente sobre emissão de terceiros (ET)** — cruza BC2 (XML,
filtrado a `PASTA_ORIGEM='ET'`) × BC1 (declaração de entradas de terceiros
do auditado, `IND_OPER=0`+`IND_EMIT=1`). Não existe BC1 de saídas, então em
"Saídas" essas colunas ficam sempre `NULL`. E, como `xml_entradas_real`
inclui uma fatia de `PASTA_ORIGEM='EP'` (ver seção "Como funciona" acima),
mesmo em "Entradas" esses itens de origem EP ficam estruturalmente sem
`COD_ITEM_DECLARACAO` válido — não é uma falha de declaração, é que a `bc3`
nunca tenta casá-los (ver detalhamento em
[Estágio 4 — Divergências de dados da bc3](04_cronologia_ano_eleito.md)).

## Validação contra a TABELA ENTRADAS de referência (só geraldo)

A operação `geraldo_2020_2024` tem um Excel de referência na raiz da pasta
da operação — `TABELA ENTRADAS A SE EXPORTADA AO HUNTER
(69488f78-131b-433b-9d3f-83142236d794).xlsx` — que é o "gabarito" externo
contra o qual `xml_entradas_real` deve ser conferido (mesmo Excel usado pelo
painel `interface.render_auditoria_divergencia_entradas()`, ver conversa
anterior). Ele já vem com a coluna `tipo_emissao`/`ENTRADA_SAIDA` marcando
`ET`/`EP` linha a linha, o que permite comparar por origem (consulta direta
em 2026-07-14):

| Origem | TABELA ENTRADAS (Excel) | `xml_entradas_real` (Hunter) | Diferença |
|---|---|---|---|
| ET | 18.925 | 19.181 | +256 |
| EP | 252 | 252 | 0 |
| **Total** | **19.177** | **19.433** | **+256** |

A fatia EP bate **exatamente** (252 = 252) — confirma que a regra de
`r_definição entradas_saidas_xml.txt` está capturando corretamente as
entradas de origem EP (auditada emitente, `tpnf=0`). Toda a diferença
(+256) está do lado ET.

> Nota: esse +256 (ET, comparação direta 2026-07-14) **não é diretamente
> comparável** aos números do painel de Auditoria (Estágio 1,
> `interface.render_auditoria_divergencia_entradas()`) vistos antes nesta
> conversa (total Excel 19.177, total `estoque_entradas` 16.420, divergência
> não identificada de 3.011) — aquele painel compara por `CHV_NFE` +
> contagem de itens por nota, com um snapshot do banco de 2026-07-13,
> enquanto `xml_entradas_real` já está em 19.433 agora (a base cresceu
> entre as duas datas, mesma discrepância já registrada em
> [Estágio 4](04_cronologia_ano_eleito.md)). Os dois são indícios da mesma
> família de divergência ET, mas não a mesma métrica — não tratar um como
> substituto do outro sem revalidar.

## Resultado real (validado nas 3 operações, 2026-07-12)

A reclassificação por papel da auditada é substancialmente diferente (e
mais correta) da classificação ingênua por `tpnf` isolado:

| Operação | `nfe_entradas` (tpnf isolado) | `xml_entradas_real` (papel da auditada) |
|---|---|---|
| geraldo_2020_2024 | 733 | 16.420 |
| PB2 | 43 | 4.564 |
| cometa | 850 | 10.802 |

## Ver também

- [Estágio 1 — Extração](01_extracao.md) — origem de `nfe_entradas`/
  `nfe_saidas` e do CNPJ da entidade auditada.
- [Estágio 4 — Cronologia e Ano Eleito](04_cronologia_ano_eleito.md) — usa
  `xml_entradas_real`/`xml_saidas_real` + `AUDITADA_PAPEL` como base; mesmo
  enriquecimento com a `bc3` (`loader._montar_join_bc3()`) desta prévia.
- [Estágio 2 — Criação BC3](02_criacao_bc3.md) — origem de
  `COD_ITEM_DECLARACAO`/`DESCR_ITEM_DECLARACAO`/
  `FATOR_MULTIPLICADOR_SUGERIDO`/`DT_E_S`/`DT_FIN`, trazidos aqui via
  `loader.consultar_fluxo_real()`.
- `r_definição entradas_saidas_xml.txt` (raiz do projeto) — fonte original
  da regra `tpnf` × papel da auditada implementada em
  `_classificar_itens_nfe()`.
- `regra de negócios unificadas/CNPJ EMIT = CNPJ DEST.txt` (raiz do
  projeto) — regra correlata sobre exclusão de CFOP de baixa de estoque
  (5927/6927), não a origem da classificação entradas/saídas em si.
- `TABELA ENTRADAS A SE EXPORTADA AO HUNTER
  (69488f78-131b-433b-9d3f-83142236d794).xlsx` (pasta da operação
  `geraldo_2020_2024`) — gabarito externo usado na seção "Validação contra
  a TABELA ENTRADAS de referência" acima e pelo painel de Auditoria
  (Estágio 1).
