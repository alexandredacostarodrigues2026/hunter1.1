# Estágio 2 — Criação BC3

> Índice geral: [ESTAGIOS_PROJETO.md](../../ESTAGIOS_PROJETO.md)

## Objetivo

Para cada produto ET do fornecedor (BC2, lado XML), buscar o código de
produto correspondente usado pelo auditado na sua declaração (BC1, lado
SPED) — sem depender de `NUM_ITEM` como chave, já que a ordem sequencial
dos itens no XML do fornecedor não necessariamente bate com a ordem de
escrituração no SPED do declarante.

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
  `DESCR_ITEM_DECLARACAO` trazidos da BC1 quando há correspondência,
  `MATCH_TIPO`/`MATCH_SCORE` indicando como e com que confiança, e
  `FATOR_MULTIPLICADOR_SUGERIDO` sinalizando possível divergência de
  unidade/embalagem entre as duas bases.
- Persistida via `loader.persistir_bc3()`, consultável por
  `loader.consultar_bc3()`/`loader.consultar_totais_bc3()`.

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
  `MATCH_TIPO`, `MATCH_SCORE`, `FATOR_MULTIPLICADOR_SUGERIDO`). `LEFT JOIN`
  pra não descartar item de ET sem `bc3` gerada ainda ou sem
  correspondência — só fica com as colunas de enriquecimento em `NULL`.
- Usada em `interface.render_bc3()` (expander "Visualizar resultado do
  Matching (BC3)") para mostrar produto do fornecedor (XML) e produto da
  auditada (declaração) lado a lado. A exportação completa (CSV) continua
  servindo direto da tabela `bc3`, sem o join.
- A hierarquia dos 11 níveis (D1-D6/A1-A5) é preservada na prévia: `MATCH_TIPO`
  vem direto da `bc3`, sem nenhuma transformação.
- Exige `ID_UNICO` em `nfe_entradas` (schema atual); bases persistidas com
  uma versão de `loader.py` anterior a essa coluna precisam recarregar
  ("Carregar novamente") — a função degrada graciosamente (vazio + log) em
  vez de quebrar a tela, e nunca regera dado sozinha.
- Detalhes completos: ver seção "Prévia enriquecida de ET" em
  [REGRAS_MATCHING.md](../../REGRAS_MATCHING.md).

## Ver também

- [REGRAS_MATCHING.md](../../REGRAS_MATCHING.md) — critérios completos de
  D1-D6/A1-A5, seção por seção, com histórico de mudanças.
- [TIPOS_MATCHING_RESUMO.md](../../TIPOS_MATCHING_RESUMO.md) — versão
  enxuta em tabela.
- `matching.py` (`OPERACOES/*/ESSENCIAL/app/`) — implementação de
  referência.
