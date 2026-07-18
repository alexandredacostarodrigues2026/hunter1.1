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
   linha física, o Estoque Final do ano de `DT_INV` **e**, ao mesmo tempo,
   o Estoque Inicial do ano SEGUINTE a `DT_INV` — não são duas contagens
   físicas diferentes, é a mesma foto vista dos dois lados da virada do ano
   (ex.: `DT_INV=31/12/2020` é EF(2020) e EI(2021)). Implementado com dois
   `DataFrame`s (um com `ANO_REFERENCIA = ano de DT_INV`, outro com
   `ANO_REFERENCIA = ano de DT_INV + 1`) unidos por `outer join` em
   `(ANO_REFERENCIA, COD_ITEM)`. **Corrigido 2026-07-17**: até então o
   código fazia o oposto (EI no ano de `DT_INV`, EF no ano anterior) — um
   desvio sistemático de 1 ano, achado pela Auditoria de Divergência de
   Estoque comparando contra `ESTOQUE(...).xlsx` (ver seção "Validação
   real" abaixo).
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

## Validação real (2026-07-12, aprofundada 2026-07-17)

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

Esta validação de 2026-07-12 só conferiu o UNIVERSO de itens (mesmos
COD_ITEM nas duas fontes) e a contagem de linhas — não as QUANTIDADES por
`(COD_ITEM, ANO_REFERENCIA)`. A Auditoria de Divergência de Estoque
(`interface.render_auditoria_divergencia_estoque()`, 2026-07-17) fechou
essa lacuna e achou o desvio sistemático de 1 ano corrigido acima: antes da
correção, quase 100% dos pares comparados divergiam (28.705/38.111 na
geraldo; 319/319 na PB2; 188/188 na cometa).

A primeira versão da auditoria comparava contra `estoque_anual_
consolidado` já expandido no formato "largo" (EI/EF separados, 223 linhas
na PB) — usuário pediu pra comparar "no modelo do CSV" em vez disso: uma
linha por declaração física de inventário, igual ao Excel de referência,
sem passar pelo formato item×ano do Estágio 5. Revisado no mesmo dia:
`auditar_divergencia_estoque()` agora lê H010 cru direto (`loader.
_declaracoes_estoque_hunter()`) e compara 1:1 contra o Excel — total de
linhas bate quase exato nas 3 operações reais (**geraldo 25.590×25.600,
PB2 127×127 exato, cometa 75×75 exato**), dispensando o Estágio 5 como
pré-requisito desta auditoria.

Investigando os poucos pares divergentes restantes (a pedido do usuário),
achado um segundo problema: quando `(COD_ITEM, ANO_REFERENCIA)` tem mais
de uma linha de um lado (código de item reutilizado por dois produtos
diferentes no SPED, ou a duplicidade de `31/01/2020` da geraldo), a
comparação usava `groupby(...).first()` — pegava a declaração na ordem de
leitura do arquivo, não a mais parecida, criando falsos positivos (ex.:
cometa `COD_ITEM=4` reportava divergência de 11.059,8 entre duas
declarações que na verdade batiam exatas cada uma com seu par certo).
Trocado por `_ordenar_duplicatas_por_quantidade()` — casa duplicatas pela
quantidade mais próxima entre os dois lados (ótimo pra minimizar a soma
das diferenças, não é heurística arbitrária). Resultado: **0/127 (PB2),
0/75 (cometa — reconciliação total, incluindo o caso `COD_ITEM=4`),
10/25.600 (geraldo — as 10 declarações duplicadas de `31/01/2020`, agora
corretamente isoladas como "só no Hunter" em vez de mascaradas por
`.first()`)**.

**Escopo pelo Período de Auditoria (2026-07-18)**: as 10 declarações
duplicadas de `31/01/2020` da geraldo ficaram sem divergência de VALOR,
mas ainda inflavam a contagem de pares porque a auditoria comparava TODOS
os anos presentes nos dados, mesmo fora do período fiscalizado
configurado (`config_auditoria`, EXTRAÇÃO). Usuário confirmou o período
mudou pra 2021-2024 na geraldo e reafirmou a regra: "Para auditar o
período de 2021 a 2024, o sistema processará os estoques finais de 2021,
2022, 2023 e 2024, que são extraídos respectivamente das declarações de
2022, 2023, 2024 e 2025" — consistente com a correção do desvio de 1 ano
acima ("declaração de X" = arquivo filed no ano X, `DT_INV` do ano X-1) e
confirmado de forma independente por um comentário pré-existente em
`loader.verificar_cobertura_periodo()`. `auditar_divergencia_estoque()`
agora filtra `ANO_REFERENCIA` por `obter_periodo_auditoria()` quando
configurado (sem período, mantém mostrando tudo). Resultado final: **as 3
operações reais fecham 100% — geraldo 0/15.840 (era 10/25.600), PB2
0/127 (sem mudança), cometa 0/67 (era 0/75)**.

## Ver também

- Auditoria de Divergência de Estoque (`interface.render_auditoria_
  divergencia_estoque()`, `loader.auditar_divergencia_estoque()`,
  2026-07-17) — compara esta tabela com `ESTOQUE(...).xlsx` por
  `(COD_ITEM, ANO_REFERENCIA)`, direto na página AUDITORIA1 (mesmo grupo
  das auditorias de entradas/saídas). Foi essa comparação que achou o
  desvio de 1 ano corrigido acima.
- [Estágio 4 — Cronologia e Ano Eleito](04_cronologia_ano_eleito.md) —
  `DATA_ELEITA`/`ANO_ELEITO`, a mesma chave de ano usada aqui; produz
  `estoque_entradas`/`estoque_saidas`, que ainda é movimentação, não
  estoque — o "estoque" de fato só passa a existir aqui, no Estágio 5.
- [ESTAGIOS_PROJETO.md](../../ESTAGIOS_PROJETO.md) — Estágio 15 (⏳
  Planejado): cálculo de divergência RN1, que compararia esta tabela com
  `estoque_entradas`/`estoque_saidas` do Estágio 4. Renumerado de 6 para 15
  em 2026-07-14 (Estágio 6 agora é o menu de navegação).
- `regra de negócios unificadas/regra negocio_pu_rn1_ei+c=v+ef_1.txt` (raiz
  do projeto) — fórmula RN1 em si (Estoque Inicial + Compras = Vendas +
  Estoque Final), ainda não implementada em nenhuma função do código
  (confirmado por busca — só existe o comentário registrando a decisão de
  adiar, `loader.py:1973`).
