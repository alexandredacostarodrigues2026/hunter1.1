# Estágio 1 — Extração

> Índice geral: [ESTAGIOS_PROJETO.md](../../ESTAGIOS_PROJETO.md)

## Objetivo

Ler os arquivos fiscais brutos (XML de NF-e do fornecedor e EFD/SPED do
auditado) e transformá-los em tabelas estruturadas no banco (DuckDB),
prontas para o cruzamento do Estágio 2.

## Entradas

- **XML/NF-e** (`1-DOCFISCAIS/nf/*.txt`) — extratos item-a-item das notas
  fiscais eletrônicas emitidas por terceiros (fornecedores) contra o
  auditado.
- **SPED/EFD ICMS-IPI** (`2-DECLARACAO/SPED/*.txt`) — escrituração fiscal
  digital do auditado, registros `0000`, `0150` (participantes), `0190`
  (unidades), `0200` (cadastro de produto), `C100`+`C170` (documentos e
  itens).

## O que acontece

1. **Classificação do XML** (`loader.classificar_xml_nfe`): cada NF-e é
   classificada em `ET` (Emissão de Terceiros — nota emitida pelo
   fornecedor contra o auditado) ou `EP` (Emissão Própria), e dentro disso
   segregada por situação fiscal (cancelada/denegada/inutilizada) e por
   CFOP (watchlist de entrega futura, venda à ordem, baixa de estoque) —
   nada é descartado, tudo vira uma tabela (`nfe_entradas`, `nfe_saidas`,
   `nfe_analise_et`, `nfe_analise_ep`, `nfe_situacao_et`, `nfe_situacao_ep`).
2. **Parsing do SPED** (`loader.load_declaracao_entradas_terceiros` e
   funções relacionadas): lê `C100`+`C170`, filtra `IND_OPER=0` (entrada) +
   `IND_EMIT=1` (terceiros), enriquece com o cadastro de produto (`0200`),
   unidade de medida (`0190`) e CNPJ do participante (`0150`).
3. **Persistência** (`loader.persistir_nfe`, `loader.persistir_sped`,
   `loader.carregar_operacao`): grava tudo em DuckDB
   (`OPERACOES/<operacao>/ESSENCIAL/banco/hunter.duckdb`), com
   `ID_UNICO` (hash MD5 determinístico) para rastreabilidade e as colunas
   de ligação (`CHV_NFE`, `COD_ITEM`, `NUM_ITEM`, `CFOP`, ...) sempre como
   `dtype=str` (Regra Operacional R07 — nunca inferidas como numéricas).

## Saídas (o que alimenta o Estágio 2)

- **BC2** (`loader.montar_bc2()`) — lado XML: itens de Emissão de
  Terceiros do fornecedor, já filtrados por situação/CFOP válidos.
- **BC1** (`loader.load_declaracao_entradas_terceiros()`) — lado SPED: itens
  de entrada de terceiros declarados pelo auditado.

## Datas na BC1 (`DT_E_S`/`DT_FIN`) — alicerce do Estágio 4

Implementado em 2026-07-12: além de `DT_DOC` (data de emissão do C100), a
BC1 passou a trazer duas datas adicionais, necessárias para o
[Estágio 4 — Implantação das regras das datas](../../ESTAGIOS_PROJETO.md):

- **`DT_E_S`** — Campo 11 do Registro `C100`: data de entrada/saída efetiva
  da mercadoria (para entradas, quando a mercadoria foi de fato recebida —
  pode divergir da emissão da nota). Herdado do C100 pra cada item (C170)
  do mesmo documento, junto com `DT_DOC` (`_parse_itens_c170_com_c100()`).
- **`DT_FIN`** — Campo 05 do Registro `0000`: data final do período de
  apuração do arquivo SPED (ex.: `31012024`). Um único valor por arquivo,
  capturado uma vez (`_dt_fin_arquivo()`) e propagado pra todos os itens
  daquele arquivo.
- Ambos tratados como `dtype=str` (Regra Operacional R07 — datas cruas
  `DDMMAAAA`, nunca inferidas como número, o que corromperia zeros à
  esquerda de dia/mês).
- **Uso pretendido**: cruzar `DT_E_S` com `DT_FIN` identifica escrituração
  extemporânea — mercadoria entrou num mês mas só foi declarada no período
  de apuração seguinte. Caso real observado na base do geraldo:
  `CHV_NFE 25191203777995000190550040015236701115293266` — `DT_DOC`
  24/12/2019 (nota emitida em dezembro), `DT_E_S` 02/01/2020 (mercadoria
  entrou em janeiro), `DT_FIN` 31/01/2020 (declarada dentro do período de
  janeiro — extemporânea em relação ao mês de emissão da nota).

## Ver também

- `loader.py` (`OPERACOES/*/ESSENCIAL/app/`) — implementação de referência.
- [DICIONARIO DE CAMPOS.txt](../../DICIONARIO%20DE%20CAMPOS.txt) — nome
  amigável de cada campo técnico extraído.
