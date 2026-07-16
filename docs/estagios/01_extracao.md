# Estágio 1 — Extração

> Índice geral: [ESTAGIOS_PROJETO.md](../../ESTAGIOS_PROJETO.md)

## Objetivo

Ler os arquivos fiscais brutos (XML de NF-e do fornecedor e EFD/SPED do
auditado), transformá-los em tabelas estruturadas no DuckDB da operação, e
preparar as duas bases comparativas (BC2 lado XML, BC1 lado SPED) que
alimentam o Matching do Estágio 2. Inclui também a configuração do Período
de Auditoria (trava inicial de escopo temporal) e os alertas de cobertura
de dados.

## Configuração e Período de Auditoria

- **`loader.load_config()`** (`loader.py:88`) — lê `config.json` da
  operação. Caminho resolvido em `loader.py:39-47`: se a variável de
  ambiente `HUNTER_OPERACAO_DIR` estiver setada (usada por
  `processar_operacoes.bat` para apontar o mesmo motor para outra pasta de
  operação), tenta `config.json` na raiz dessa pasta, senão
  `ESSENCIAL/config/config.json`; sem a variável, sempre
  `ESSENCIAL/config/config.json` da operação atual.
- **`loader.salvar_periodo_auditoria(ano_inicial, ano_final)`**
  (`loader.py:111`) — grava 1 linha em `config_auditoria` no DuckDB
  (`CREATE OR REPLACE`, sempre substitui a configuração anterior). Anos
  gravados como string (Regra Operacional R07).
- **`loader.obter_periodo_auditoria()`** (`loader.py:124`) — lê
  `config_auditoria`; devolve `None` se o banco/tabela ainda não existem ou
  em caso de erro.
- **`loader.verificar_cobertura_periodo()`** (`loader.py:150`) — alerta
  informativo, não bloqueia carga. Calcula os anos exigidos:
  `anos_xml_necessarios = [AnoInicial-1 .. AnoFinal]` (a virada anterior ao
  início do período já precisa da base de comparação) e
  `anos_sped_necessarios = [AnoInicial .. AnoFinal+1]` (inclui o inventário
  de fechamento do último ano). Compara com os anos efetivamente presentes:
  XML via `SUBSTR(fatonfe_infprot_chnfe, 3, 2)` das 6 tabelas de
  `_TABELAS_XML_COBERTURA` (`nfe_entradas`, `nfe_saidas`,
  `nfe_analise_et`/`_ep`, `nfe_situacao_et`/`_ep`, `loader.py:144`); SPED
  via `COMPETENCIA` de `sped_itens`. `aplicavel=False` quando não há
  período configurado.
- **`loader.anos_declaracao_disponiveis()`** (`loader.py:204`) — lê a
  competência (Registro `0000`) direto dos arquivos brutos de
  `2-DECLARACAO/SPED/`, sem depender de persistência prévia — alimenta o
  alerta de Ancoragem de Estoque (o Estoque Final de um ano é declarado no
  SPED de competência do início do ano seguinte).
- Painel: **`interface.render_configuracao_periodo()`** — seleção de Ano
  Inicial/Final (janela dos últimos 9 anos), botão "Confirmar Período";
  já configurado, mostra o resumo fixo + botão "Alterar" e a cobertura
  necessária de XML/SPED.

## Lado XML (NF-e) — `1-DOCFISCAIS/nf/*.txt`

**`loader._classificar_itens_nfe()`** (`loader.py:274`, cacheada
`@st.cache_data(ttl=1800)`) é o coração do Estágio 1 no lado XML: lê todos
os `.txt` de `nfe_path` (subpastas `ET`/`EP`) via `_read_txt_pipe()`
(`loader.py:235`, separador `|`, tolera múltiplos encodings) e segrega POR
ITEM (não por chave inteira) em 8 grupos, sem descartar nenhum registro:

1. **Situação inválida** (fora de `{"A","O"}` — canceladas, denegadas,
   inutilizadas) → `nfe_situacao_et`/`nfe_situacao_ep`, por
   `PASTA_ORIGEM`.
2. Dentre os de situação válida, **CFOP na watchlist** (Regra Operacional
   R07, `loader.py:66-73`): `_CFOP_WATCHLIST_GLOBAL` (1922/2922/5922/6922
   faturamento futuro; 1923/2923/5923/6923 venda à ordem, aplica a ET+EP),
   `_CFOP_WATCHLIST_ET={5927,6927}` (baixa de estoque),
   `_CFOP_WATCHLIST_EP={5929,6929}` (lançamento ECF) → `nfe_analise_et`/
   `nfe_analise_ep`. Nota: CFOP 5929/6929 em registros de ET **não** é
   segregado — não está em nenhuma das duas watchlists aplicáveis a ET;
   CFOP 5927/6927 em registros de EP também **não** é segregado (flui
   normalmente) — 2026-07-16: uma tentativa de estender a watchlist de EP
   pra 5927/6927 (achado da operação cometa: 500 chaves de autoemissão,
   `emit_cnpj==dest_cnpj`, com esse CFOP inflando `estoque_entradas`) foi
   implementada e depois **revertida no mesmo dia** — o usuário confirmou
   que a exclusão de 5927/6927 é exclusiva de ET, em EP esse CFOP roda
   normalmente.
   Também segregado para `nfe_analise_et` (exclusivo de ET, independente de
   CFOP): **modelo 65/NFC-e** (`fatonfe_infnfe_ide_mod == "65"`,
   `_MODELO_NFCE`, `loader.py:71-76`) — vedado para registro de entrada
   pelo declarante (Guia Prático da EFD). Cada linha segregada ganha
   `MOTIVO_SEGREGACAO` ("CFOP Não Autorizado" ou "Modelo 65 Vedado em
   Entrada") para diferenciar o critério na prévia do painel.
3. O restante (situação válida + CFOP fora da watchlist, `mask_principal`)
   → `nfe_entradas`/`nfe_saidas`, conforme `tpnf` isolado (0/1).
4. Desse mesmo restante, a movimentação física **real** da auditada
   (cruzando `tpnf` com o papel dela na nota — emitente ou destinatária) →
   `entradas_real`/`saidas_real`. Isso já é o Estágio 3
   ([Fluxos Físicos](03_fluxos_fisicos.md)), incluído aqui só porque roda
   dentro da mesma função.

Cada linha ganha `ID_UNICO` (hash MD5 determinístico de `CHV_NFE`+`NUM_ITEM`,
`loader._gerar_id_unico()`, `loader.py:643`) — determinístico, não UUID
aleatório, porque `persistir_nfe`/`persistir_sped` recriam a tabela inteira
a cada carga (`CREATE OR REPLACE`) e um ID aleatório mudaria a cada recarga,
quebrando qualquer referência externa (ex.: o `LEFT JOIN` com a `bc3` no
Estágio 2/3/4).

Wrappers de compatibilidade: `load_entradas()`, `load_saidas()`,
`load_analise_et()`, `load_analise_ep()` (`loader.py:436-461`) — todos
redelegam a `_classificar_itens_nfe()`.

## BC2 — `loader.montar_bc2()` (`loader.py:490`)

Base Comparativa 2 (lado XML): reaproveita os buckets `entradas`+`saidas`
já classificados, filtra `PASTA_ORIGEM=='ET'` (situação válida + CFOP fora
da watchlist de ET, independente do `tpnf`) e renomeia as colunas para o
padrão curto compartilhado com a BC1 (`_BC2_RENOMEAR_COLUNAS`,
`loader.py:471`): `fatonfe_infprot_chnfe`→`CHV_NFE`,
`fatoitemnfe_infnfe_det_prod_cprod`→`COD_ITEM`,
`fatoitemnfe_infnfe_det_prod_cean`→`COD_BARRA`,
`fatoitemnfe_infnfe_det_prod_ncm`→`COD_NCM`,
`fatoitemnfe_infnfe_det_prod_ucom`→`UNID`,
`fatoitemnfe_infnfe_det_prod_qcom`→`QTD`,
`fatoitemnfe_infnfe_det_prod_vuncom`→`_VALOR_UNIT_ORIGINAL`,
`fatoitemnfe_infnfe_det_prod_vprod`→`VL_ITEM`. Colunas finais em
`_BC2_COLUNAS_FINAIS` (inclui `fatonfe_infnfe_emit_cnpj`, `ID_UNICO`,
`PASTA_ORIGEM`, `ARQUIVO_ORIGEM`).

## Lado SPED/EFD — `2-DECLARACAO/SPED/*.txt`

Parser sequencial, tolerante a bytes fora de UTF-8 (`latin-1`):

- **`loader._iter_linhas_sped()`** (`loader.py:563`) — só repassa linhas
  `|...|` com código de registro reconhecível (`_REG_VALIDO`, regex
  `^[0-9A-Z]{4}$`), descartando o bloco de assinatura digital binária
  colado no final do arquivo.
- **`loader._competencia_arquivo()`** (`loader.py:578`) — lê `DT_INI`
  (Campo 04) do Registro `0000` → competência `AAAAMM`.
- **`loader._dt_fin_arquivo()`** (`loader.py:589`) — lê `DT_FIN` (Campo 05)
  do `0000`, cru (`DDMMAAAA`) — 1 valor por arquivo, propagado depois pra
  todos os itens dele.
- **`loader._parse_registros_sped()`** (`loader.py:602`) — extrator
  genérico por código de registro, usado para `0200`, `0190`, `0150`.
- **`loader._parse_itens_c170_com_c100()`** (`loader.py:663`) — cada
  `C170` herda do `C100` mais recente: `IND_OPER`, `IND_EMIT`, `COD_PART`,
  `NUM_DOC`, `CHV_NFE`, `DT_DOC`, **`DT_E_S`** (ver seção dedicada abaixo),
  mais `DT_FIN` do `0000` do arquivo.

Campos extraídos por registro (constantes `_CAMPOS_*`, `loader.py:522-553`):

| Registro | Campos |
|---|---|
| `0000` | `COD_VER, COD_FIN, DT_INI, DT_FIN, NOME, CNPJ, CPF, UF, IE, COD_MUN, IM, SUFRAMA, IND_PERFIL, IND_ATIV` |
| `0150` | `COD_PART, NOME, COD_PAIS, CNPJ, CPF, IE, COD_MUN, SUFRAMA, END, NUM, COMPL, BAIRRO` |
| `0190` | `UNID, DESCR` |
| `0200` | `COD_ITEM, DESCR_ITEM, COD_BARRA, COD_ANT_ITEM, UNID_INV, TIPO_ITEM, COD_NCM, EX_IPI, COD_GEN, COD_LST, ALIQ_ICMS` |
| `C100` | `IND_OPER, IND_EMIT, COD_PART, COD_MOD, COD_SIT, SER, NUM_DOC, CHV_NFE, DT_DOC, DT_E_S, VL_DOC, ...` (impostos totais) |
| `C170` | `NUM_ITEM, COD_ITEM, DESCR_COMPL, QTD, UNID, VL_ITEM, VL_DESC, ...` (impostos item a item) |
| `H010` | `COD_ITEM, UNID, QTD, VL_UNIT, VL_ITEM, IND_PROP, COD_PART, TXT_COMPL, COD_CTA, VL_ITEM_IR` (Bloco H, ver [Estágio 5](05_tabela_estoque.md)) |

Loaders (todos `@st.cache_data(ttl=1800)`): `load_declaracao_itens()`
(`C100`+`C170`), `load_declaracao_produtos()` (`0200`),
`load_declaracao_unidades()` (`0190`), `load_declaracao_participantes()`
(`0150`), `load_declaracao_estoque()` (`H005`+`H010`, ver Estágio 5).

## BC1 — `loader.load_declaracao_entradas_terceiros()` (`loader.py:875`)

Base Comparativa 1 (lado SPED): filtra `df_itens` por `IND_OPER=="0"`
(entrada) **e** `IND_EMIT=="1"` (emitido por terceiros) — só entradas de
terceiros, não cobre emissão própria. Enriquece via
`_enriquecer_itens_com_cadastro()` (merge por `COD_ITEM`→Registro `0200` e
por `UNID`→Registro `0190`) e traz o CNPJ do emitente via participantes
`0150` (`COD_PART`). Deriva
`VALOR_UNITARIO_DECLARACAO = VL_ITEM/QTD` (o C170 não tem unitário direto,
diferente da BC2 que já vem com `_VALOR_UNIT_ORIGINAL` do XML). Inclui
`DT_E_S`/`DT_FIN` sem filtro adicional. Colunas forçadas string:
`COD_ITEM`, `UNID`, `CHV_NFE`, `CNPJ`.

### Datas na BC1 (`DT_E_S`/`DT_FIN`) — alicerce do Estágio 4

Implementado em 2026-07-12: além de `DT_DOC` (emissão do `C100`), a BC1
passou a trazer duas datas adicionais, necessárias para a hierarquia de
`DATA_ELEITA` do [Estágio 4](04_cronologia_ano_eleito.md):

- **`DT_E_S`** — Campo 11 do `C100`: data de entrada/saída efetiva da
  mercadoria (pode divergir da emissão da nota).
- **`DT_FIN`** — Campo 05 do `0000`: data final do período de apuração.
- Ambos `dtype=str` (R07 — datas cruas `DDMMAAAA`, nunca inferidas como
  número).
- **Uso**: cruzar `DT_E_S` com `DT_FIN` identifica escrituração
  extemporânea. Caso real (base do geraldo): `CHV_NFE
  25191203777995000190550040015236701115293266` — `DT_DOC` 24/12/2019,
  `DT_E_S` 02/01/2020, `DT_FIN` 31/01/2020 (mercadoria entrou em janeiro,
  declarada no período de janeiro — extemporânea em relação à emissão de
  dezembro).

## Entradas de terceiros persistidas — `sped_entradas_terceiros`

**`loader.gerar_entradas_terceiros()`** (`loader.py:1593`) chama
`load_declaracao_entradas_terceiros()` (a BC1) e persiste isoladamente a
tabela `sped_entradas_terceiros` (`CREATE OR REPLACE`) — explicitamente
**sob demanda**, não roda dentro de `persistir_sped()`. Suporte:
`entradas_terceiros_ja_geradas()`, `consultar_entradas_terceiros(limite)`.
Painel: `interface.render_entradas_terceiros()` — botão "Gerar chaves de
entrada de emissão de terceiros", prévia de 200 linhas + exportação CSV
completa sob demanda (`;`, `utf-8-sig`).

## Persistência

- **`loader.persistir_nfe(callback=None)`** — grava `nfe_entradas`,
  `nfe_saidas` (só se não vazias), e sempre cria (mesmo vazias)
  `nfe_analise_et`/`_ep`, `nfe_situacao_et`/`_ep`,
  `xml_entradas_real`/`xml_saidas_real` (Estágio 3) e `nfe_bc2` — 9 tabelas
  (9 passos na barra de progresso, ver `interface._barra_progresso`).
- **`loader.persistir_sped(callback=None)`** — grava `sped_itens`,
  `sped_produtos`, `sped_unidades`, `sped_estoque` — 4 tabelas (4 passos).
- Painel: **`interface.render_carga_operacao()`** — 3 barras de progresso
  independentes: (1) classificação de XML pendentes arquivo a arquivo
  (`loader.carregar_operacao()`), (2) NF-e (`persistir_nfe`, 9 passos),
  (3) SPED (`persistir_sped`, 4 passos). Mostra contagem de arquivos
  ET/EP/declarações + pendentes, alerta de Ancoragem de Estoque
  (`_render_alerta_ancoragem_estoque()`) e, após carregado, o alerta de
  cobertura do Período de Auditoria (`_render_alerta_cobertura_periodo()`).

## Painel de Monitoramento — Registros Segregados

**`interface.render_painel_analise()`** — mostra o que o Estágio 1 desviou
do fluxo principal sem descartar: CFOP de watchlist ou modelo 65/NFC-e em ET
(`nfe_analise_et`/`_ep`) e situação irregular (`nfe_situacao_et`/`_ep`).
Botão "Gerar Dados para Análise de CFOPs" → `loader.gerar_dados_analise()`
(persiste as 4 tabelas isoladamente). KPIs ET/EP + expander de prévia para
cada categoria (`interface._render_categoria_segregacao()`).

## Regra Operacional R07

Colunas de ligação (`CHV_NFE`, `COD_ITEM`, `NUM_ITEM`, `CFOP`, `UNID`,
`CNPJ`, `DT_E_S`, `DT_FIN`, anos, ...) sempre `dtype=str` — nunca inferência
numérica do Pandas, que corromperia zeros à esquerda ou dígitos de chaves de
acesso longas. Forçado via `loader._forcar_colunas_string()`.

## Nota sobre o layout SPED

O leiaute dos registros SPED usado neste parser foi reconstruído por
amostragem dos arquivos reais das operações, seguindo o padrão público da
EFD ICMS/IPI (ver `GUIA PRÁTICO DA ESCRITURAÇÃO FISCAL DIGITAL -
EFD.pdf` em `2-DECLARACAO/`) — vale conferência pontual contra o guia antes
de uso em produção com uma nova operação/layout de SPED não testado ainda.

## Ver também

- [Estágio 2 — Criação BC3](02_criacao_bc3.md) — usa BC2 e BC1 como entrada
  do Matching.
- [Estágio 3 — Fluxos Físicos](03_fluxos_fisicos.md) — `entradas_real`/
  `saidas_real`, gerados dentro da mesma `_classificar_itens_nfe()`.
- [Estágio 5 — Tabela de Estoque](05_tabela_estoque.md) — usa o Bloco H
  (`H005`+`H010`) extraído aqui.
- `r_definição entradas_saidas_xml.txt` (raiz do projeto) — regra de
  classificação `tpnf` × papel da auditada (Estágio 3, mas aplicada dentro
  de `_classificar_itens_nfe()`).
- [DICIONARIO DE CAMPOS.txt](../../DICIONARIO%20DE%20CAMPOS.txt) — nome
  amigável de cada campo técnico extraído.
