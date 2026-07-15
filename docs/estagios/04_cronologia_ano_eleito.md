# Estágio 4 — Cronologia e Ano Eleito

> Índice geral: [ESTAGIOS_PROJETO.md](../../ESTAGIOS_PROJETO.md)

## Objetivo

Definir, para cada item de `xml_entradas_real`/`xml_saidas_real` (Estágio
3), uma única data de referência (**`DATA_ELEITA`**) e o ano correspondente
(**`ANO_ELEITO`**, `AAAA`) — a chave de agrupamento por ano para os
relatórios de movimentação (`estoque_entradas`/`estoque_saidas`). **Este
estágio não forma estoque** (apesar do nome das tabelas de saída — legado
de antes da decisão de separar as etapas): o resultado continua sendo
movimentação (entradas e saídas), só que agora com data/ano oficial
atribuído a cada item. O estoque propriamente dito (inventário declarado,
com Estoque Inicial/Final por item) só passa a existir no [Estágio
5](05_tabela_estoque.md); comparar esse inventário com a movimentação
gerada aqui para aplicar a RN1 e achar divergências fica pra uma etapa
futura (ver "Estágio 4 concluído" abaixo).

## Entrada

- `xml_entradas_real` / `xml_saidas_real` (Estágio 3), já com
  `AUDITADA_PAPEL`.
- `bc3` (Estágio 2 — Matching) — desde 2026-07-12, `matching.py` propaga
  também `DT_E_S`/`DT_FIN` da BC1 para a `bc3` (mesmo tratamento de
  `COD_ITEM_DECLARACAO`/`DESCR_ITEM_DECLARACAO`: sentinela `'nd'`/`'nm'`
  para item não declarado/sem match, herdado via dicionário de aprendizado
  para A1-A5 — ver `REGRAS_MATCHING.md`).

## Como funciona

1. **Enriquecimento** (`loader._enriquecer_fluxo_real_com_bc3()`, via o
   helper compartilhado `loader._montar_join_bc3()`): `LEFT JOIN` por
   `ID_UNICO` entre `xml_entradas_real`/`xml_saidas_real` e `bc3`, trazendo
   `COD_ITEM_DECLARACAO`, `DESCR_ITEM_DECLARACAO`,
   `FATOR_MULTIPLICADOR_SUGERIDO`, `DT_E_S` e `DT_FIN` — desde 2026-07-14,
   não só as datas. Essas 5 colunas passam a existir em
   `estoque_entradas`/`estoque_saidas` (mesmo enriquecimento usado pela
   prévia "Entradas Reais" do [Estágio 3](03_fluxos_fisicos.md), que lê
   direto do banco sem persistir nada). `LEFT JOIN` (não `INNER`) para não
   descartar item sem `bc3` gerada ainda ou sem correspondência — fica com
   essas colunas `NULL` (cascade automático pro XML nas datas, ver
   hierarquia abaixo). Degrada graciosamente se a `bc3` persistida for de
   uma versão anterior à propagação de `DT_E_S`/`DT_FIN` (checa o schema
   antes do join; `COD_ITEM_DECLARACAO`/`DESCR_ITEM_DECLARACAO`/
   `FATOR_MULTIPLICADOR_SUGERIDO` existem desde a primeira versão da `bc3`).
   Em `estoque_saidas` essas colunas ficam sempre `NULL` na prática — `bc3`
   só cobre entradas de terceiros (ver "Limitação real conhecida" abaixo).
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
   direto pro XML). Painel próprio desde 2026-07-14 —
   `interface.render_estoque_entradas_saidas()`, dentro de "TABELAS
   ENTRADAS / SAÍDAS / ESTOQUES" (ver [Estágio 6](06_menu_navegacao.md)):
   botão Gerar/Regerar + KPIs + toggle Entradas/Saídas com
   `loader.estoque_entradas_saidas_ja_gerado()`/
   `consultar_totais_estoque_entradas_saidas()`/
   `consultar_estoque_entradas_saidas()`. Até então essa função existia
   desde 2026-07-12 mas nunca era chamada de lugar nenhum da interface —
   pendência registrada e fechada no mesmo dia da criação do Estágio 6.

## Divergências de dados da bc3 — `COD_ITEM_DECLARACAO`/`FATOR_MULTIPLICADOR_SUGERIDO`

**`bc3` é exclusivamente sobre emissão de terceiros (ET)** — resultado do
Matching BC2 (XML, filtrado a `PASTA_ORIGEM='ET'`) × BC1 (declaração de
entradas de terceiros do auditado). `xml_entradas_real`, por outro lado, é
definida pela regra de `tpnf` × papel da auditada
(`r_definição entradas_saidas_xml.txt`, ver [Estágio
3](03_fluxos_fisicos.md)) — que inclui uma fatia estrutural de
`PASTA_ORIGEM='EP'` (auditada emitente com `tpnf=0`). A `bc3` nunca foi
desenhada pra cobrir essa fatia EP: não é uma falha de declaração, é fora
do escopo por construção. Por isso os números de cobertura da `bc3` só
fazem sentido quando segregados por `PASTA_ORIGEM`.

Além da ausência estrutural em EP, três motivos fazem `COD_ITEM_DECLARACAO`
ficar sem valor útil mesmo dentro de ET:

1. **Sem `bc3`** — item sem linha correspondente na `bc3` (`join` sem
   correspondência por `ID_UNICO`, ou `bc3` ainda não gerada): fica `NULL`
   genuíno.
2. **`'nd'`** (não declarado) — sentinela da `bc3`: o item do XML não achou
   nenhuma declaração correspondente na BC1/SPED do auditado.
3. **`'nm'`** (sem match) — sentinela da `bc3`: havia declaração candidata,
   mas nenhum nível do Matching (D1-D6/A1-A5) conseguiu confirmar o par
   (ver `REGRAS_MATCHING.md`).

`FATOR_MULTIPLICADOR_SUGERIDO` diverge ainda mais: mesmo entre os itens com
`COD_ITEM_DECLARACAO` real, o fator só é calculado quando o `VL_ITEM`
(valor total da linha) bate entre XML e SPED para aquele par — se não bate,
ou se o match é D3 (N-para-1, onde o `VL_ITEM` individual nunca bate com o
consolidado do SPED, só a soma do grupo), fica `NaN` de propósito (ver
comentário em `matching.py`, função `_aplicar()`).

Números reais, segregados por `PASTA_ORIGEM` (consulta direta às bases,
2026-07-14):

| Operação | Origem | Total | Com `COD_ITEM_DECLARACAO` real | `'nd'` | `'nm'` | Sem `bc3` |
|---|---|---|---|---|---|---|
| geraldo_2020_2024 | ET | 19.181 | 14.892 (77,6%) | 386 | 890 | 3.013 |
| geraldo_2020_2024 | EP | 252 | 4 (1,6%) | 237 | 0 | 11 |
| PB2 | ET | 4.514 | 1.673 (37,1%) | 2.841 | 0 | 0 |
| PB2 | EP | 50 | 0 (0%) | 3 | 0 | 47 |
| cometa | ET | 9.542 | 8.293 (86,9%) | 1.249 | 0 | 0 |
| cometa | EP | 1.260 | 19 (1,5%) | 27 | 0 | 1.214 |

A fatia EP confirma a expectativa: cobertura residual (0-1,6%) nas 3
operações — os poucos casos com código "real" em EP (4 no geraldo, 19 no
cometa) são coincidência de `ID_UNICO`, não match genuíno pretendido pela
`bc3`, e não foram investigados a fundo.

**Dentro de ET**, a cobertura varia bastante entre operações: cometa 86,9%,
geraldo 77,6%, PB2 apenas 37,1% — quase dois terços dos itens ET de PB2
caem em `'nd'`. Ao contrário do que uma leitura só do total combinado
sugeria, essa taxa baixa de PB2 **não é explicada pela fatia EP** (que é
pequena, só 50 itens/1,1% do total de PB2) — é um gap real dentro do
próprio universo ET, ainda não investigado (pode ser cobertura real da
BC1/SPED dessa operação ou característica do negócio).

Em `estoque_saidas` essas três colunas ficam sempre `NULL`/sentinela
ausente — a `bc3` não cobre saídas de forma nenhuma (nem ET nem EP).

> Nota: os totais de `xml_entradas_real` acima (ET+EP somados: 19.433 no
> geraldo, consultados agora em 2026-07-14) já não batem com os
> 16.420/4.564/10.802 da tabela "Resultado real" mais abaixo (validada em
> 2026-07-12) — o `geraldo_2020_2024` cresceu. A base foi recarregada entre
> as duas datas; a tabela de "Resultado real" está desatualizada e não foi
> revalidada aqui (fora do escopo desta edição). Ver também a validação
> contra a `TABELA ENTRADAS A SE EXPORTADA AO HUNTER` (gabarito externo, só
> geraldo) na seção "Validação contra a TABELA ENTRADAS de referência" do
> [Estágio 3](03_fluxos_fisicos.md).

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

`DT_E_S`, `DT_FIN`, `DATA_ELEITA`, `ANO_ELEITO`, `COD_ITEM_DECLARACAO` e
`DESCR_ITEM_DECLARACAO` sempre `dtype=str` — nunca inferência numérica
(`ANO_ELEITO`, apesar de só conter dígitos, nunca vira `int`). Duas
famílias de tratamento em `persistir_estoque_entradas_saidas()`:

- `DATA_ELEITA`/`ANO_ELEITO` nunca são `NULL` de verdade (sempre `""` na
  pior hipótese, ver `_aplicar_hierarquia_data()`) — forçadas com
  `loader._forcar_colunas_string()` (`astype(str)` cru).
- `DT_E_S`/`DT_FIN`/`COD_ITEM_DECLARACAO`/`DESCR_ITEM_DECLARACAO` podem
  vir `NULL` genuíno do `LEFT JOIN` com a `bc3` (item sem correspondência)
  — usam `.where(col.isna(), col.astype(str))`, preservando `NULL` como
  `NULL` em vez de virar o literal `"None"`. **Bug real encontrado e
  corrigido em 2026-07-14**: a versão anterior usava
  `_forcar_colunas_string()` (cru) também para `COD_ITEM_DECLARACAO`, o
  que transformava o `NULL` do `LEFT JOIN` no texto literal `"None"` —
  em PB2 e cometa isso inflou artificialmente a contagem de itens "com
  código real" em `estoque_saidas` (qualquer filtro `WHERE ... IS NOT
  NULL` contava o texto `"None"` como valor presente). Depois do fix e
  de regenerar as 3 operações reais, a cobertura de `COD_ITEM_DECLARACAO`
  em `estoque_saidas` caiu para o valor estrutural esperado (residual,
  perto de zero — ver tabela em "Divergências de dados da bc3" acima).

## Estágio 4 concluído — cálculo de divergência fica pra uma etapa futura

`DATA_ELEITA`/`ANO_ELEITO` fecham o escopo deste estágio. O cálculo de
saldo de estoque em si (regra RN1 — Estoque Inicial + Compras = Vendas +
Estoque Final, ver `regra de negócios unificadas/regra
negocio_pu_rn1_ei+c=v+ef_1.txt`, raiz do projeto) foi deliberadamente
**redefinido pra fora** do Estágio 4/5: o [Estágio 5](05_tabela_estoque.md)
só consolida o inventário já declarado (sem fórmula nenhuma); comparar esse
inventário com `estoque_entradas`/`estoque_saidas` (agrupados por
`ANO_ELEITO`) pra aplicar a RN1 e achar divergências é o Estágio 15 do
[índice geral](../../ESTAGIOS_PROJETO.md) — `⏳ Planejado`, sem nenhuma
função implementada ainda (confirmado por busca no código). Renumerado de
6 para 15 em 2026-07-14 para abrir espaço, no 6, para o menu de navegação
([Estágio 6 — VAMOS ORGANIZAR](06_menu_navegacao.md)).

## Ver também

- [Estágio 3 — Fluxos Físicos](03_fluxos_fisicos.md) — origem de
  `xml_entradas_real`/`xml_saidas_real`/`AUDITADA_PAPEL`.
- [Estágio 5 — Tabela de Estoque](05_tabela_estoque.md) — consolidação do
  inventário declarado (Bloco H), usa a mesma base de dados desta etapa.
- [Estágio 2 — Criação BC3](02_criacao_bc3.md) — origem de `DT_E_S`/`DT_FIN`
  via `bc3`.
- [Estágio 1 — Extração](01_extracao.md) — origem de `DT_E_S`/`DT_FIN` na
  BC1 (seção "Datas na BC1").
- `regra de negócios unificadas/` (raiz do projeto) — regras de negócio
  originais (datas ET/EP, RN1 de estoque) que motivaram este estágio.
