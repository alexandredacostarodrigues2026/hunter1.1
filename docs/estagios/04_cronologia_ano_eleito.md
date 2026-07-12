# Estágio 4 — Cronologia e Ano Eleito

> Índice geral: [ESTAGIOS_PROJETO.md](../../ESTAGIOS_PROJETO.md)

## Objetivo

Definir, para cada item de `xml_entradas_real`/`xml_saidas_real` (Estágio
3), uma única data de referência (**`DATA_ELEITA`**) e o ano correspondente
(**`ANO_ELEITO`**, `AAAA`) — a chave de agrupamento para os relatórios
anuais de movimentação e a "data oficial" que alimentará o cálculo de saldo
de estoque (última etapa do Estágio 4, ainda pendente).

## Entrada

- `xml_entradas_real` / `xml_saidas_real` (Estágio 3), já com
  `AUDITADA_PAPEL`.
- `bc3` (Estágio 2 — Matching) — desde 2026-07-12, `matching.py` propaga
  também `DT_E_S`/`DT_FIN` da BC1 para a `bc3` (mesmo tratamento de
  `COD_ITEM_DECLARACAO`/`DESCR_ITEM_DECLARACAO`: sentinela `'nd'`/`'nm'`
  para item não declarado/sem match, herdado via dicionário de aprendizado
  para A1-A5 — ver `REGRAS_MATCHING.md`).

## Como funciona

1. **Enriquecimento** (`loader._enriquecer_fluxo_real_com_bc3()`): `LEFT
   JOIN` por `ID_UNICO` entre `xml_entradas_real`/`xml_saidas_real` e `bc3`,
   trazendo `DT_E_S`/`DT_FIN`. `LEFT JOIN` (não `INNER`) para não descartar
   item sem `bc3` gerada ainda ou sem correspondência — fica com
   `DT_E_S`/`DT_FIN` `NULL` (cascade automático pro XML, ver hierarquia
   abaixo). Degrada graciosamente se a `bc3` persistida for de uma versão
   anterior à propagação de `DT_E_S`/`DT_FIN` (checa o schema antes do
   join).
2. **Hierarquia de datas** (`loader._aplicar_data_eleita()`), por cenário
   (`AUDITADA_PAPEL`):

   | Prioridade | Cenário A — `DESTINATARIA` (ET) | Cenário B — `EMITENTE` (EP) |
   |---|---|---|
   | 1ª | `DT_E_S` (C100, BC1, via bc3) | `dhSaiEnt` (XML) |
   | 2ª | `DT_FIN` (Registro 0000, BC1, via bc3) | `DT_E_S` (C100, BC1, via bc3) |
   | 3ª | `dhSaiEnt` (XML) | `DT_FIN` (Registro 0000, BC1, via bc3) |
   | 4ª | `dhEmi` (XML) | `dhEmi` (XML) |

   Usa a primeira data válida (pandas `combine_first`, aplicado igualmente
   ao valor cru e ao ano derivado, sempre alinhados). `DT_E_S`/`DT_FIN` são
   validados no formato SPED `DDMMAAAA` (8 dígitos); `dhSaiEnt`/`dhEmi` no
   formato ISO 8601 do XML (`AAAA-MM-DD...`). Sentinela `'nd'`/`'nm'` da
   `bc3` e `NULL` genuíno (item sem `bc3`/join sem correspondência) reprovam
   a validação de formato automaticamente — não é preciso checar
   `MATCH_TIPO` explicitamente para cair no fallback do XML.
3. **Persistência** (`loader.persistir_estoque_entradas_saidas()`): grava
   `estoque_entradas`/`estoque_saidas` no DuckDB. Exige
   `xml_entradas_real`/`xml_saidas_real` já persistidas (Estágio 3); `bc3`
   é opcional (sem ela, `DT_E_S`/`DT_FIN` ficam `NULL` e a hierarquia cai
   direto pro XML).

## Limitação real conhecida — `dhSaiEnt` ausente da extração

O pipeline de extração de XML deste projeto (arquivos `.txt` gerados via
Qlik em `1-DOCFISCAIS/nf/`) **não inclui o campo `dhSaiEnt`** — só `dhEmi`
(`fatonfe_infnfe_ide_dhemi*`). Verificado nos headers reais de ET e EP
(operação geraldo). Consequência prática:

- **Cenário A (ET)**: a 3ª prioridade (`dhSaiEnt`) nunca contribui —
  cascade direto de `DT_FIN` pra `dhEmi` quando `DT_E_S`/`DT_FIN` não
  estão disponíveis. Sem impacto grande: `DT_E_S`/`DT_FIN` cobrem a
  maioria dos casos (ver resultado real abaixo).
- **Cenário B (EP)**: a 1ª prioridade (`dhSaiEnt`) nunca contribui, **e**
  a BC1 (`load_declaracao_entradas_terceiros()`) só cobre declarações de
  **entrada de terceiros** (`IND_OPER=0`+`IND_EMIT=1`) — não existe BC1
  para os itens de emissão própria (saídas). Ou seja, para
  `AUDITADA_PAPEL='EMITENTE'`, as 3 primeiras prioridades são
  estruturalmente inaplicáveis nesta base, e `DATA_ELEITA` cai sempre em
  `dhEmi` (4ª prioridade). Confirmado na base real do geraldo:
  `estoque_saidas` tem `DT_E_S`/`DT_FIN` `NULL` em 100% das linhas.
- O código está correto e completo pela especificação (a hierarquia de 4
  níveis existe pronta para o dia em que `dhSaiEnt` passar a ser extraído,
  ou uma BC1 de saídas for implementada) — a limitação é de
  disponibilidade de dado na fonte, não da lógica.

## Resultado real (validado nas 3 operações, 2026-07-12)

| Operação | `estoque_entradas` | `estoque_saidas` | `DATA_ELEITA` vazia |
|---|---|---|---|
| geraldo_2020_2024 | 16.420 | 60.623 | 0 (nas duas) |
| PB2 | 4.564 | 11.362 | 0 (nas duas) |
| cometa | 10.802 | 179.349 | 0 (nas duas) |

Em `estoque_entradas` (geraldo): 14.896 itens usaram `DT_E_S` diretamente
(1ª prioridade), os demais caíram pro fallback do XML (`dhEmi`) — sobretudo
itens `ND`/`NM` na `bc3`.

## Regra Operacional R07

`DT_E_S`, `DT_FIN`, `DATA_ELEITA` e `ANO_ELEITO` sempre `dtype=str` — nunca
inferência numérica (`ANO_ELEITO`, apesar de só conter dígitos, nunca vira
`int`). Forçado explicitamente antes de persistir
(`loader._forcar_colunas_string()`).

## Pendente (fecha o Estágio 4)

- Cálculo de saldo de estoque (Estoque Inicial + Compras = Vendas + Estoque
  Final — regra RN1, ver `regra de negócios unificadas/regra
  negocio_pu_rn1_ei+c=v+ef_1.txt`, raiz do projeto) usando `ANO_ELEITO`
  como chave de agrupamento anual.

## Ver também

- [Estágio 3 — Fluxos Físicos](03_fluxos_fisicos.md) — origem de
  `xml_entradas_real`/`xml_saidas_real`/`AUDITADA_PAPEL`.
- [Estágio 2 — Criação BC3](02_criacao_bc3.md) — origem de `DT_E_S`/`DT_FIN`
  via `bc3`.
- [Estágio 1 — Extração](01_extracao.md) — origem de `DT_E_S`/`DT_FIN` na
  BC1 (seção "Datas na BC1").
- `regra de negócios unificadas/` (raiz do projeto) — regras de negócio
  originais (datas ET/EP, RN1 de estoque) que motivaram este estágio.
