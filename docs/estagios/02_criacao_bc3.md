# Estágio 2 — Criação BC3

> Índice geral: [ESTAGIOS_PROJETO.md](../../ESTAGIOS_PROJETO.md)

## Objetivo

Para cada produto ET do fornecedor (BC2, lado XML), buscar o código de
produto correspondente usado pelo auditado na sua declaração (BC1, lado
SPED) — sem depender de `NUM_ITEM` como chave, já que a ordem sequencial
dos itens no XML do fornecedor não necessariamente bate com a ordem de
escrituração no SPED do declarante.

**Escopo: exclusivamente Emissão de Terceiros (ET).** A BC2 só existe para
`PASTA_ORIGEM='ET'` (ver [Estágio 1](01_extracao.md)) e a BC1 só cobre
entradas de terceiros (`IND_OPER=0`+`IND_EMIT=1`) — não existe BC1 de
saídas nem de emissão própria. Consequência: a `bc3` nunca tenta casar
itens de `PASTA_ORIGEM='EP'`, mesmo quando esses itens fazem parte de
`xml_entradas_real` (Estágio 3, que inclui uma fatia estrutural de EP —
auditada emitente com `tpnf=0`). Não é uma falha de declaração para esses
itens: é fora de escopo por construção. Ver números reais segregados por
origem em [Estágio 4 — Divergências de dados da
bc3](04_cronologia_ano_eleito.md).

## Entrada

- BC2 e BC1, produzidos no [Estágio 1 — Extração](01_extracao.md).
- Desde 2026-07-12, a BC1 também traz `DT_E_S` (data de entrada/saída
  efetiva, Campo 11 do C100) e `DT_FIN` (data final do período de apuração,
  Campo 05 do Registro 0000) — alicerce do
  [Estágio 4](../../ESTAGIOS_PROJETO.md), ainda não consumido pelo Matching
  desta etapa (critérios do Estágio 2 continuam sendo só GTIN/valor/texto,
  ver `REGRAS_MATCHING.md`). Detalhes completos em
  [Estágio 1 — Datas na BC1](01_extracao.md#datas-na-bc1-dt_e_sdt_fin--alicerce-do-estágio-4).

## Como funciona

Motor de Matching (`matching.py`, função `executar_matching()`): cruza BC2
× BC1 em múltiplos níveis, do critério mais forte (GTIN/EAN) ao mais fraco
(valor, com desempate por texto), cada nível só tentando casar o que
sobrou do nível anterior. Duas famílias:

- **Direto (D1-D6)** — sempre dentro da mesma `CHV_NFE`.
- **Aprendizado (A1-A5)** — dicionário histórico, não exige mesma
  `CHV_NFE`, recupera inclusive notas inteiras não declaradas.

Critérios, limiares, ordem de execução e o histórico completo de decisões
(inclusive casos reais que motivaram cada ajuste) estão em
**[REGRAS_MATCHING.md](../../REGRAS_MATCHING.md)** — fonte única, não
duplicada aqui.

## Saída

- **BC3** — uma linha por item da BC2, com `COD_ITEM_DECLARACAO`/
  `DESCR_ITEM_DECLARACAO` trazidos da BC1 quando há correspondência
  (sentinela `'nd'` = não declarado, `'nm'` = sem match — nunca `NULL`
  cru), `MATCH_TIPO`/`MATCH_SCORE` indicando como e com que confiança, e
  `FATOR_MULTIPLICADOR_SUGERIDO` sinalizando possível divergência de
  unidade/embalagem entre as duas bases (só calculado quando o `VL_ITEM`
  bate entre XML e SPED para o par — fica `NaN` de propósito nos matches
  D3, consolidação N-para-1, onde o valor individual nunca bate com a
  linha consolidada do SPED).
- Persistida via `loader.persistir_bc3()`, consultável por
  `loader.consultar_bc3()`/`loader.consultar_totais_bc3()` (contagem por
  `MATCH_TIPO`) / `loader.bc3_ja_gerada()`.

## Painel — `interface.render_bc3()`

"Matching (Etapa 1) — BC2 × BC1 = BC3": caption explica os 11 critérios
(D1-D6/A1-A5) em prosa (mesmo conteúdo resumido de
[REGRAS_MATCHING.md](../../REGRAS_MATCHING.md)). Botão "Gerar Matching
(BC3)"/"Regerar Matching (BC3)" (pode levar ~1 minuto — similaridade de
texto item a item — por isso fica atrás de um botão explícito, não roda
automaticamente na carga geral). Quando já gerada, mostra 14 KPIs em linha
(`st.columns(14)`): Matches D1, D2, A1-A5, D3-D6, "Não Declarado (nd)",
"Sem Match (nm)" e a Taxa de Match (`total_casados / total_itens`).

## Prévia enriquecida — BC3 expandida de volta para o ET

Além da BC3 "crua" (só as ~12 colunas reduzidas da BC2), o painel do
Matching exibe uma prévia que expande o resultado de volta para o dataset
bruto de ET (`nfe_entradas`, gerado no [Estágio 1](01_extracao.md)) — todas
as colunas originais do XML (data de emissão, emitente, endereço etc.), não
só as reduzidas pela BC2.

- **`loader.consultar_nfe_entradas_bc3()`** — `LEFT JOIN` por `ID_UNICO`
  (chave sintética determinística, presente nos dois lados) entre
  `nfe_entradas` (filtrado a `PASTA_ORIGEM='ET'`) e `bc3` (só as colunas de
  enriquecimento: `COD_ITEM_DECLARACAO`, `DESCR_ITEM_DECLARACAO`,
  `MATCH_TIPO`, `MATCH_SCORE`, `FATOR_MULTIPLICADOR_SUGERIDO`, `DT_E_S`,
  `DT_FIN`). `LEFT JOIN` pra não descartar item de ET sem `bc3` gerada
  ainda ou sem correspondência — só fica com as colunas de enriquecimento
  em `NULL`.
- Usada em `interface.render_bc3()` (expander "Visualizar resultado do
  Matching (BC3)") para mostrar produto do fornecedor (XML) e produto da
  auditada (declaração) lado a lado (`interface._COLUNAS_PREVIEW_BC3`).
  A exportação completa (CSV) continua servindo direto da tabela `bc3`,
  sem o join (botão "Preparar exportação completa" — sob demanda, porque
  ler a `bc3` inteira pode ser pesado em bases com milhões de linhas).
- A hierarquia dos 11 níveis (D1-D6/A1-A5) é preservada na prévia: `MATCH_TIPO`
  vem direto da `bc3`, sem nenhuma transformação.
- Exige `ID_UNICO` em `nfe_entradas` (schema atual); bases persistidas com
  uma versão de `loader.py` anterior a essa coluna precisam recarregar
  ("Carregar novamente") — a função degrada graciosamente (vazio + log) em
  vez de quebrar a tela, e nunca regera dado sozinha.
- **Desde 2026-07-14**, a montagem do fragmento SQL (colunas + `LEFT JOIN`)
  é compartilhada via `loader._montar_join_bc3()` entre esta função,
  `loader._enriquecer_fluxo_real_com_bc3()` (Estágio 4) e
  `loader.consultar_fluxo_real()` (Estágio 3, prévia "Entradas Reais") —
  as três trazem o mesmo conjunto de colunas da `bc3`, com o mesmo
  tratamento de degradação (schema antigo/tabela ausente).
- Detalhes completos: ver seção "Prévia enriquecida de ET" em
  [REGRAS_MATCHING.md](../../REGRAS_MATCHING.md).

## Ver também

- [REGRAS_MATCHING.md](../../REGRAS_MATCHING.md) — critérios completos de
  D1-D6/A1-A5, seção por seção, com histórico de mudanças.
- [TIPOS_MATCHING_RESUMO.md](../../TIPOS_MATCHING_RESUMO.md) — versão
  enxuta em tabela.
- `matching.py` (`OPERACOES/*/ESSENCIAL/app/`) — implementação de
  referência.
- [Estágio 3 — Fluxos Físicos](03_fluxos_fisicos.md) — enriquecimento da
  prévia "Entradas Reais" com colunas da `bc3` (mesmo helper
  `loader._montar_join_bc3()`).
- [Estágio 4 — Cronologia e Ano Eleito](04_cronologia_ano_eleito.md) —
  enriquecimento de `estoque_entradas`/`estoque_saidas` com `DT_E_S`/
  `DT_FIN` da `bc3`, e a análise completa de cobertura ET × EP.
