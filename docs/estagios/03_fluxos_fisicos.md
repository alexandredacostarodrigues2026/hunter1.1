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
`fatonfe_infnfe_dest_cnpj` do XML):

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
aplicar (não é o mesmo que `PASTA_ORIGEM`/ET-EP por pasta: `entradas_real`
e `saidas_real` podem conter uma mistura de papéis, ver
`CNPJ EMIT = CNPJ DEST.txt` na pasta `regra de negócios unificadas/`, raiz
do projeto).

## Saída

- **`xml_entradas_real`** / **`xml_saidas_real`** — persistidas via
  `loader.persistir_nfe()`, sempre criadas (mesmo vazias, ex.: entidade
  auditada ainda não fixada). Consultáveis por
  `loader.consultar_totais_entradas_saidas_real()` /
  `loader.consultar_fluxo_real(direcao, limite)`.
- Painel: `interface.render_fluxos_fisicos()` — KPIs + botões "Visualizar
  Entradas"/"Visualizar Saídas" (exclusivos entre si), prévia formatada com
  o Dicionário de Campos.

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
  `xml_entradas_real`/`xml_saidas_real` + `AUDITADA_PAPEL` como base.
- `regra de negócios unificadas/CNPJ EMIT = CNPJ DEST.txt` (raiz do
  projeto) — regra de negócio original que motivou o cruzamento tpnf ×
  papel da auditada.
