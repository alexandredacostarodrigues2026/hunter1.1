# Estágio 5 — Tabela de Estoque

> Índice geral: [ESTAGIOS_PROJETO.md](../../ESTAGIOS_PROJETO.md)

## Objetivo

Consolidar o inventário físico **já declarado** pela auditada no Bloco H do
SPED (Registros H005+H010) numa tabela única, uma linha por item×ano,
assegurando a continuidade cronológica dos saldos entre exercícios. Foco
**exclusivo** em consolidação — nenhuma fórmula de auditoria, cálculo de
movimentação (entradas/saídas) ou busca de divergência entra nesta etapa
(ver "Ver também" para onde isso vai quando for implementado).

## Entrada

- Registros H005 (cabeçalho do inventário — `DT_INV`, `VL_INV`, `MOT_INV`)
  e H010 (itens do inventário — `COD_ITEM`, `UNID`, `QTD`, `VL_UNIT`,
  `VL_ITEM`) dos arquivos SPED (`2-DECLARACAO/SPED/*.txt`).
- Registro 0200 (cadastro de produto) — só para trazer `DESCR_ITEM`.

## Como funciona

1. **`loader._parse_estoque_h005_h010()`** — percorre H005/H010
   sequencialmente (H005 é o pai; H010 os itens filhos, mesmo padrão de
   herança que C100→C170) e propaga `DT_INV`/`MOT_INV` do H005 mais recente
   pra cada H010. Diferente de C100/C170, H005 aparece **no máximo uma vez
   por arquivo** — o inventário é declarado uma vez por ano, tipicamente no
   primeiro/segundo mês competente do ano seguinte.
2. **Regra de continuidade** (`loader.montar_estoque_anual_consolidado()`):
   cada inventário declarado (identificado por `DT_INV`) vira, na mesma
   linha física, o Estoque Final do ano anterior a `DT_INV` **e**, ao mesmo
   tempo, o Estoque Inicial do ano de `DT_INV` — não são duas contagens
   físicas diferentes, é a mesma foto vista dos dois lados da virada do
   ano. Implementado com dois `DataFrame`s (um com `ANO_REFERENCIA = ano de
   DT_INV`, outro com `ANO_REFERENCIA = ano de DT_INV − 1`) unidos por
   `outer join` em `(ANO_REFERENCIA, COD_ITEM)`.
3. **Enriquecimento**: `DESCR_ITEM_DECLARACAO` vem do Registro 0200
   (`loader.load_declaracao_produtos()`), por `COD_ITEM`.

## Saída

- **`estoque_anual_consolidado`** — colunas `ANO_REFERENCIA`,
  `COD_ITEM_DECLARACAO`, `DESCR_ITEM_DECLARACAO`, `UNIDADE`,
  `QUANTIDADE_INICIAL`, `QUANTIDADE_FINAL`. Persistida via
  `loader.persistir_estoque_anual_consolidado()`, consultável por
  `loader.consultar_estoque_anual_consolidado()`/
  `loader.estoque_anual_ja_gerado()`.
- Painel: `interface.render_estoque_anual()` — botão "Gerar Tabela de
  Estoque" + prévia.
- **Ausência esperada, não bug**: o último ano coberto fica sem
  `QUANTIDADE_FINAL` (ainda não houve inventário de fechamento declarado
  pra ele); itens que somem/aparecem entre um inventário e o seguinte ficam
  sem `QUANTIDADE_INICIAL` ou `QUANTIDADE_FINAL` naquele ano específico —
  reflete a realidade declarada, não um erro de junção.

## Achado real — `MOT_INV` (motivo do inventário)

A especificação original desta etapa citava filtrar pelo motivo "01" (No
final do período, Campo 04 do H005). **Verificado nos 7 arquivos reais da
operação geraldo que têm H005: `MOT_INV` é sempre `"05"`, nunca
`"01"`.** Filtrar literalmente por `"01"` zeraria a tabela nesta base real.
Decisão: **não filtrar por um motivo específico** — todo H005 encontrado é
tratado como um fechamento de inventário válido (H005 é opcional no SPED,
só aparece quando a empresa de fato declara Bloco H naquele período, então
sua simples presença já é o sinal relevante).

## Regra Operacional R07

`ANO_REFERENCIA`, `COD_ITEM_DECLARACAO`, `DESCR_ITEM_DECLARACAO` e
`UNIDADE` sempre `dtype=str`. `QUANTIDADE_INICIAL`/`QUANTIDADE_FINAL` são
medidas numéricas de verdade (não códigos de ligação) — ficam `float`.

## Validação real (2026-07-12)

Comparado contra `DADOS BRUTOS/GERALDO_2020A2024/ESTOQUE(...).xlsx` — tabela
de referência já usada em outra aplicação do usuário (formato "longo": uma
linha por declaração H010, com colunas `EstFinal`/`EstInicial` marcando os
anos-fronteira, em vez do formato "largo" pedido nesta especificação):
**5.975 itens únicos em ambas** (match exato). Total de linhas próximo
(25.600 no Hunter vs. 25.590 na referência — diferença pequena, provável
snapshot de dados ligeiramente diferente entre as duas fontes). A
referência cobre até `ANO=2025`; os arquivos SPED atualmente na pasta do
projeto só vão até `DT_INV=31/12/2024` — a referência parece ter sido
gerada com uma declaração mais recente ainda não sincronizada nesta pasta.

Persistido nas 3 operações reais: geraldo 31.956 linhas, PB2 223, cometa
132.

## Ver também

- [Estágio 4 — Cronologia e Ano Eleito](04_cronologia_ano_eleito.md) —
  `DATA_ELEITA`/`ANO_ELEITO`, a mesma chave de ano usada aqui.
- `regra de negócios unificadas/regra negocio_pu_rn1_ei+c=v+ef_1.txt` (raiz
  do projeto) — fórmula RN1, ainda não aplicada (fica pra uma etapa futura
  que cruzaria esta tabela com `estoque_entradas`/`estoque_saidas`).
