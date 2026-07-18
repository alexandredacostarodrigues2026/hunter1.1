# Estágio 6 — VAMOS ORGANIZAR (Menu de Navegação)

> Índice geral: [ESTAGIOS_PROJETO.md](../../ESTAGIOS_PROJETO.md)

## Objetivo

Reorganizar a tela única do Streamlit (todos os painéis dos Estágios
1-2-3-5 empilhados verticalmente numa página só) em grupos navegáveis, para
o auditor não precisar rolar por todos os KPIs/tabelas de uma vez. Não muda
nenhuma lógica de carga, matching ou consolidação — é reorganização de UI
sobre painéis que já existiam.

## Como funciona

Controlado por `st.session_state["pagina_ativa"]` (`None` = Menu Principal;
`"extracao"`; `"matching"`; `"segregados"`; `"construcao"`;
`"auditoria1"`), inicializado em `main.py` no início de `main()`. `main.py`
despacha para uma das funções de `interface.py` conforme o valor:

- **`interface.render_menu_principal()`** — 5 botões (`st.columns(5)`):
  "📥 EXTRAÇÃO", "🧩 MATCHING (BC3)", "🔀 SEGREGADOS", "📊 TABELAS
  ENTRADAS / SAÍDAS / ESTOQUES" (renomeado de "🚧 PAINÉIS EM CONSTRUÇÃO"
  em 2026-07-14, ver seção própria abaixo) e "📑 AUDITORIA1: COMPARAÇÃO
  ENTRADAS-SAÍDAS-ESTOQUES" (2026-07-15, ver seção própria abaixo). Cada
  um seta `pagina_ativa` e chama `st.rerun()`.
- **`interface.render_pagina_extracao()`** — botão de retorno
  (`_botao_voltar_menu()`) + `render_configuracao_periodo()` +
  `render_carga_operacao()` (já inclui os alertas de cobertura do Período
  de Auditoria e de Ancoragem de Estoque/Bloco H) + `render_entidade_auditada()`
  (só depois de `dados_carregados=True`). Mesmo conteúdo que antes ficava
  direto em `main.py`, sem nenhuma mudança de comportamento.
- **`interface.render_pagina_matching()`** (botão próprio desde
  2026-07-14, mesmo dia da promoção de "Segregados") — botão de retorno +
  (se `dados_carregados`) só `render_bc3()` (Estágio 2). Posicionado logo
  após "Extração" a pedido do usuário — BC3 é o motor que "completa" as
  notas de entrada e viabiliza os estágios seguintes (Fluxos Físicos,
  Cronologia). `render_bc3()` traz, num `st.expander` no topo ("Chaves de
  entrada de emissão de terceiros da declaração (base comparativa 1)"),
  a BC1 (`render_entradas_terceiros()`) — subcomponente do Matching desde
  2026-07-14, ver seção própria abaixo.
- **`interface.render_pagina_segregados()`** (botão próprio desde
  2026-07-14) — botão de retorno + (se `dados_carregados`)
  `render_painel_analise()`: "CFOPs Não Autorizados" (com o botão "CFOPS
  SEGREGADOS", união ET+EP) e "Notas Não Autorizadas" — nomes de exibição
  escolhidos pelo usuário em 2026-07-14 (ver seção "Nomes de exibição"
  abaixo).
- **`interface.render_pagina_construcao()`** (botão "TABELAS ENTRADAS /
  SAÍDAS / ESTOQUES" desde 2026-07-14 — mesma função/`pagina_ativa=
  "construcao"` de quando se chamava "Painéis em Construção") — botão de
  retorno + (se `dados_carregados`) `render_fluxos_fisicos()` (Estágio 3,
  prévia sob demanda, não persiste), `render_estoque_entradas_saidas()`
  (Estágio 4 — **primeiro painel deste estágio na UI, 2026-07-14**, ver
  seção própria abaixo) e `render_estoque_anual()` (Estágio 5, Estoques).
  Sem `dados_carregados`, mostra só um aviso orientando a ir em "Extração"
  primeiro. `render_auditoria_divergencia_entradas()` saiu daqui em
  2026-07-15 — ver `render_pagina_auditoria1()` logo abaixo.
- **`interface.render_pagina_auditoria1()`** (botão "AUDITORIA1:
  COMPARAÇÃO ENTRADAS-SAÍDAS-ESTOQUES", próprio desde 2026-07-15) — botão
  de retorno + (se `dados_carregados`) `render_auditoria_divergencia_
  entradas()` (Hunter `estoque_entradas` × Excel de referência). Ver seção
  própria abaixo.
- **`interface._botao_voltar_menu()`** — botão "⬅️ Voltar ao Menu
  Principal" no topo das 5 páginas; seta `pagina_ativa=None` e chama
  `st.rerun()`.

Nenhuma tabela do DuckDB é criada, apagada ou reprocessada por este
estágio — a troca de página não afeta os dados já carregados, porque eles
vivem no banco, não em `session_state`.

## "Segregados" ganhou botão próprio (2026-07-14)

Primeira versão deste estágio colocou `render_painel_analise()` dentro de
"Painéis em Construção", junto com BC3/Fluxos Físicos/Estoque Anual. O
usuário corrigiu: registros segregados (CFOP de watchlist — entrega
futura, venda à ordem, baixa de estoque, lançamento ECF — e situação
irregular — cancelada, denegada, inutilizada) são desviados de propósito
pela Etapa 1 (`loader._classificar_itens_nfe()`, `mask_analise_et/ep` e
`mask_situacao_et/ep`) e **nunca entram no cômputo do cruzamento/Matching**
— não são resultado de cruzamento, então misturá-los com os painéis que
mostram esse resultado (BC3, Fluxos Físicos, Estoque Anual) confundia a
navegação. Agora tem botão dedicado no Menu Principal, separado dos dois
outros grupos.

## Nomes de exibição — "Não Autorizados" (2026-07-14)

A pedido do usuário, as duas categorias trocaram de rótulo na UI (só o
texto exibido — `categoria='cfop'`/`'situacao'`, `nfe_analise_et/ep` e
`nfe_situacao_et/ep` continuam com os mesmos nomes técnicos internos):

- "CFOP de Watchlist" → **"CFOPs Não Autorizados"**
- "Situação Irregular" → **"Notas Não Autorizadas"**

**Ressalva técnica** (levantada antes da mudança, o usuário optou por
seguir mesmo assim): os CFOPs desta categoria (`5922/6922` entrega futura,
`5923/6923` venda à ordem, `5927/6927` baixa de estoque, `5929/6929`
lançamento ECF) são **válidos e autorizados** — o que os tira do
cruzamento principal é a natureza simbólica/não física da operação, não
uma questão de autorização. "Não Autorizados" aqui é o nome de exibição
escolhido para o grupo (itens que não entram no cômputo do cruzamento),
não uma afirmação fiscal de que o CFOP em si carece de autorização. Só
`nfe_situacao_et/ep` ("Notas Não Autorizadas") corresponde de fato a
`fatonfe_informix_stnfeletronica` fora de `{"A","O"}` — mais próximo do
sentido literal do nome.

## "Matching (BC3)" ganhou botão próprio (2026-07-14, mesmo dia)

BC3 entrou em "Painéis em Construção" primeiro (como primeiro item do
grupo, a pedido do usuário), depois foi promovido a botão de primeiro
nível no Menu Principal, posicionado logo após "Extração" — mesmo
tratamento que "Segregados" já tinha recebido antes no mesmo dia. Razão:
BC3 (Matching BC2×BC1, Estágio 2) não é só "mais um painel de resultado"
— é o motor central que produz o dado que os estágios seguintes (Fluxos
Físicos, Cronologia) dependem para fazer sentido, então mereceu destaque
equivalente ao de "Extração" em vez de ficar agrupado com Fluxos
Físicos/Estoque Anual/Auditoria.

## BC1 virou subcomponente do Matching, não painel independente (2026-07-14)

Ainda no mesmo dia da promoção de "Matching (BC3)" a botão próprio, o
usuário pediu mais um ajuste: `render_entradas_terceiros()` (BC1) saiu de
`render_pagina_construcao()` e passou a viver **dentro de `render_bc3()`**,
num `st.expander("Chaves de entrada de emissão de terceiros da declaração
(base comparativa 1)")` no topo do painel de Matching, antes dos KPIs
D1-D6/A1-A5. Implementado como uma chamada normal a
`render_entradas_terceiros()` dentro do bloco `with st.expander(...):` —
sem duplicar a lógica da função, só mudando onde ela é desenhada na tela.
Motivo: BC1 é a base de comparação oficial que o Matching usa pra
"completar" as notas de entrada — deixou de ser um painel independente e
virou parte do fluxo de trabalho do Matching. Aproveitado para também
aplicar `_preparar_preview()` (nomes amigáveis do Dicionário de Campos) na
prévia em tela dessa tabela, que antes só traduzia colunas na exportação
CSV, não no `st.dataframe` da tela.

## "Painéis em Construção" renomeado para "TABELAS ENTRADAS / SAÍDAS / ESTOQUES" (2026-07-14)

Depois que BC3 e BC1 saíram para "Matching (BC3)" e os Registros
Segregados para "Segregados", o que sobrou em "Painéis em Construção"
(Fluxos Físicos + Estoque Anual + Auditoria) já não era mais um cajado de
"tudo que ainda tá em construção" — o nome genérico deixou de refletir o
conteúdo. Usuário pediu o rótulo "TABELAS ENTRADAS / SAÍDAS / ESTOQUES",
alinhado ao conteúdo real: Fluxos Físicos tem o toggle Entradas/Saídas
Reais, Estoque Anual é a Tabela de Estoque. Só o texto do botão mudou —
`render_pagina_construcao()`/`pagina_ativa="construcao"` continuam com os
mesmos nomes internos, e o conteúdo do painel (incluindo a Auditoria de
Divergência, que não está no nome) não mudou.

## Estágio 4 ganhou seu primeiro painel na UI (2026-07-14, mesmo dia)

Logo depois de renomear o botão, o usuário pediu que ele "já gere
Entradas e Saídas já enriquecidas com dados de BC3" — até então,
`loader.persistir_estoque_entradas_saidas()` (Estágio 4) existia desde
2026-07-12 mas **nunca era chamada de lugar nenhum da interface**
(pendência registrada repetidamente ao longo do dia). Nova
`interface.render_estoque_entradas_saidas()`, inserida entre Fluxos
Físicos e Estoque Anual em `render_pagina_construcao()`:

- Botão "Gerar"/"Regerar Entradas/Saídas Enriquecidas" (mesmo padrão do
  Estoque Anual) → `loader.persistir_estoque_entradas_saidas()` —
  persiste `estoque_entradas`/`estoque_saidas` de verdade (diferente da
  prévia do Estágio 3, que só calcula na hora, sem gravar nada).
- KPIs "Entradas Enriquecidas"/"Saídas Enriquecidas" +
  toggle "Visualizar Entradas"/"Visualizar Saídas" (mesmo padrão de
  Fluxos Físicos) — prévia com `COD_ITEM_DECLARACAO`/
  `DESCR_ITEM_DECLARACAO`/`FATOR_MULTIPLICADOR_SUGERIDO` (bc3, Estágio 2)
  e `DATA_ELEITA`/`ANO_ELEITO` (hierarquia de datas), nomes traduzidos
  via `_preparar_preview()`.
- Novas funções de apoio em `loader.py`:
  `estoque_entradas_saidas_ja_gerado()`, `consultar_totais_estoque_
  entradas_saidas()`, `consultar_estoque_entradas_saidas(direcao, limite)`
  — mesmo padrão das funções equivalentes do Estágio 3/5, nenhuma
  existia antes (só a persistência, sem consulta/checagem).
- Validado ao vivo: regenerar em cima da base real do geraldo produziu
  19.433 entradas / 92.441 saídas — bate exatamente com
  `xml_entradas_real`/`xml_saidas_real` (Estágio 3), confirmando que é
  uma enriquecida 1:1, sem perda nem duplicação de linha.

## Decisão de agrupamento — Auditoria em "Construção" (histórico, superado em 2026-07-15)

A especificação original só detalhou o conteúdo de "Extração" (Período +
Carga + Entidade Auditada) e citou "Painéis em Construção" como "Estágios 2
ao 5 (Matching BC3, Fluxos Físicos, Estoque Anual, etc.)" — na época BC3 e
BC1 ainda faziam parte desse grupo (ver seções acima para as duas
promoções posteriores). `render_auditoria_divergencia_entradas()`
(Excel × Hunter) não foi explicitamente posicionado — ficou em "Painéis em
Construção" (painel de análise/conferência sobre o resultado do
cruzamento, não dado desviado dele, diferente de "Segregados") — era uma
interpretação, não uma instrução explícita. Resolvido em 2026-07-15: ver
"AUDITORIA1 ganhou botão próprio" abaixo.

## AUDITORIA1 ganhou botão próprio (2026-07-15)

Solicitação técnica formal pediu "um ponto de acesso formal e renomeado"
pra este estudo — até então ele rodava sem botão próprio, escondido no fim
de "TABELAS ENTRADAS / SAÍDAS / ESTOQUES" (ver seção anterior). A lógica
de negócio em si já satisfazia integralmente o que a solicitação pedia —
`loader.auditar_divergencia_entradas()` já usava `estoque_entradas`
(Estágio 4) como base do Hunter (não tabela bruta de XML), já cruzava só
por `CHV_NFE` + contagem de itens (nunca por código de produto), já lia o
Excel de referência por glob (`TABELA ENTRADAS*.xlsx`) na pasta raiz da
própria operação ativa (`_OPERACAO_DIR`, que pra geraldo já resolve
exatamente pro caminho pedido na solicitação) e já mostrava os 5
indicadores + botão "Investigar Chaves Divergentes" pedidos. A mudança
real foi só de navegação:

- Novo `interface.render_pagina_auditoria1()`: botão de retorno + (se
  `dados_carregados`) `render_auditoria_divergencia_entradas()` — reusa a
  função existente, sem duplicar lógica.
- `render_auditoria_divergencia_entradas()` saiu do fim de
  `render_pagina_construcao()`.
- Novo 5º botão no Menu Principal, posicionado logo após "TABELAS
  ENTRADAS / SAÍDAS / ESTOQUES": "📑 AUDITORIA1: COMPARAÇÃO
  ENTRADAS-SAÍDAS-ESTOQUES".
- **Ajuste de UX aproveitado na mesma mudança**: antes, sem Excel de
  referência a função retornava silenciosamente (`return` sem nada
  desenhado) — razoável quando embutida entre outros painéis numa página
  cheia, mas resultaria numa página "AUDITORIA1" em branco (só o botão de
  retorno) pra quem não é a geraldo. Trocado por um `st.info()` explicando
  que o estudo só se aplica a operações com esse Excel.

## Análise bidirecional de chaves — "Resíduo Hunter"/"Resíduo CSV" (2026-07-15, mesmo dia)

Solicitação técnica seguinte pediu pra isolar, dentro da página AUDITORIA1,
as chaves que existem só de um lado ou só do outro — diferente de
"Investigar Chaves Divergentes" (que reconcilia por CONTAGEM de itens
dentro de cada chave já presente no Excel), esta é uma checagem de
presença/ausência TOTAL da `CHV_NFE`:

- **`loader.auditar_divergencia_entradas()`** ganhou duas chaves novas no
  dict de retorno: `residuo_hunter` (linhas de `estoque_entradas` cuja
  `CHV_NFE` não aparece em nenhuma linha do Excel — `set(hunter_entradas.
  index) - set(excel_por_chave.index)`) e `residuo_csv` (linhas do Excel
  cuja `CHV_NFE` não aparece em NENHUMA das 4 fontes do Hunter —
  `estoque_entradas`, `xml_saidas_real`, `nfe_situacao_et/ep`,
  `nfe_analise_et/ep`). Novo helper `_detalhar_chaves_hunter_ausentes_no_
  excel()` monta o detalhe (`CHV_NFE`, `DATA_ELEITA`, `VL_ITEM`,
  `EMITENTE`) via `INNER JOIN` no DuckDB contra as chaves residuais
  (registradas como view temporária) — mesmo padrão de outras junções do
  módulo, evita passar milhares de chaves numa cláusula `IN` do SQL.
- **Validação cruzada**: `len(residuo_hunter)` bate exatamente com o
  `resumo['itens_hunter_ausentes_no_excel']` que já existia (15 itens/8
  chaves únicas na base real do geraldo) — confirma que o novo cálculo é
  consistente com o que já era reportado só como total agregado.
- **`residuo_csv` usa colunas específicas do layout do Excel da geraldo**
  (`DataFinal`→`DATA`, `Sum(Valor_total_prod)`→`VALOR`) — checadas com
  `if c in df_excel.columns` antes de selecionar, pra não quebrar se outra
  operação vier a ter um Excel de referência com layout diferente no
  futuro.
- **Interface**: nova seção "Detalhamento de Chaves Ausentes" dentro de
  `render_auditoria_divergencia_entradas()`, com dois botões — "🔍 Chaves
  do Hunter ausentes no CSV (N chave(s) única(s))" e "📂 Chaves do CSV
  ausentes no Hunter (N chave(s) única(s))" — cada um revela o
  `st.dataframe()` correspondente (mesmo padrão de toggle via
  `session_state` do "Investigar Chaves Divergentes").
- Validado ao vivo (Playwright): na base real do geraldo, "Resíduo Hunter"
  mostra 8 chaves únicas (15 itens) com as 4 colunas pedidas; "Resíduo
  CSV" mostra 0 chaves (consistente — a divergência não identificada
  total também é 0 nesta base agora).

## Auditoria estendida para saídas (2026-07-17)

Pedido do usuário ("estenda a auditoria para as saídas") depois de fechar
a auditoria de entradas nas 3 operações reais (PB_2023_2025 e cometa
zerando 100%, ver `r_extracao.txt` regra 25). Espelho quase completo de
`auditar_divergencia_entradas()`/`render_auditoria_divergencia_entradas()`,
com os papéis principal/reconciliação invertidos:

- **`loader.auditar_divergencia_saidas()`**: compara o Excel de
  referência de saídas (`*SAIDAS*.xlsx` na raiz da operação, via novo
  `loader._localizar_excel_saidas_referencia()`/`carregar_excel_saidas_
  referencia()`, mesmo critério de busca genérica por substring —
  case/acento-insensível via `_normalizar_str()`, já que "SAÍDA" tem
  acento e um `.upper()` puro não bastaria) com `estoque_saidas`
  (principal) e `xml_entradas_real` (primeiro fallback de reconciliação)
  — inverso exato da auditoria de entradas, que usa `estoque_entradas`
  como principal e `xml_saidas_real` como fallback. `nfe_situacao_et/ep`
  e `nfe_analise_et/ep` são os mesmos dois níveis seguintes, sem duplicar
  lógica (não têm direção — servem os dois estudos). Devolve o mesmo
  formato/nomes de coluna (`ITENS_ENTRADAS_REAIS`/`ITENS_SAIDAS_REAIS`
  etc.) que a versão entradas.
- **`loader.MSG_SEM_EXCEL_SAIDAS_REFERENCIA`**: sentinela irmã de
  `MSG_SEM_EXCEL_ENTRADAS_REFERENCIA`, mesmo papel (distinguir "arquivo
  não existe" de erro real de leitura).
- **`loader._detalhar_chaves_hunter_ausentes_no_excel()`** ganhou
  parâmetro `tabela` (default `"estoque_entradas"`) em vez de duplicar a
  função só pra trocar o nome da tabela — chamada com
  `tabela="estoque_saidas"` na auditoria de saídas.
- **`loader._coluna_valor_excel_referencia()`** (novo helper): a coluna de
  valor no Excel de referência varia por export — a TABELA ENTRADAS da
  geraldo/PB tem `Sum(Valor_total_prod)` E `$VT`, mas a TABELA SAÍDAS só
  tem `$VT`. Checa nessa ordem de prioridade em vez de um nome fixo
  (usado nas duas auditorias agora, não só na de saídas).
- **`interface.render_auditoria_divergencia_saidas()`**: mesma estrutura
  de `render_auditoria_divergencia_entradas()` (KPIs, "Investigar Chaves
  Divergentes", "Detalhamento de Chaves Ausentes"), com `HUNTER_SAIDAS_
  QTD` como métrica principal na prévia (`_COLUNAS_PREVIEW_DIVERGENCIA_
  SAIDAS`) e chaves de `session_state`/`key=` próprias (sufixo
  `_saidas`) — sem isso os botões colidiriam com os da seção de entradas
  (mesmo `key=` do Streamlit não pode se repetir na mesma página).
- **`render_pagina_auditoria1()`**: chama as duas funções em sequência —
  cada seção aparece (ou não) de forma independente, conforme a operação
  tiver o respectivo Excel de referência.
- Validado ao vivo (runtime portátil de cada operação + Playwright,
  porta descartável 8601): PB_2023_2025 (11.359 Excel × 11.362 Hunter,
  resíduo 0) e cometa (204.382 × 204.428, resíduo 0) fecham 100%; geraldo
  tem 1.372 chaves de resíduo ainda não investigadas (fica pra sessão
  futura). Confirmado que os dois painéis alternam estado
  independentemente (clique num não afeta o outro).

## Botão "Regenerar Entradas e Saídas" (2026-07-17, mesmo dia)

Achado real na geraldo: um arquivo XML de 2019 foi removido de
`1-DOCFISCAIS/nf/ET/`, mas ninguém rodou `persistir_nfe()`/`persistir_
estoque_entradas_saidas()` depois — o banco (e a Auditoria1) ficou
desatualizado sem nenhum aviso visível; o usuário só descobriu comparando
contra o Excel de referência. Antes disso, regenerar exigia dois passos
manuais em páginas diferentes: "Carregar novamente" em EXTRAÇÃO
(`persistir_nfe`, Estágio 1) e "Regerar Entradas/Saídas Enriquecidas" em
"TABELAS ENTRADAS/SAÍDAS/ESTOQUES" (`persistir_estoque_entradas_saidas`,
Estágio 4) — fácil rodar só um dos dois e achar que está tudo atualizado.

- Novo botão **"🔄 Regenerar Entradas e Saídas (Estágio 1 + 4)"** no topo
  de `render_pagina_auditoria1()`, antes das duas auditorias — roda
  `persistir_nfe()` (relê os `.txt` já classificados em `ET`/`EP`) e, se
  sem erro, `persistir_estoque_entradas_saidas()` em seguida, num só
  clique.
- **Não chama `st.rerun()`**: as duas auditorias já são renderizadas
  logo abaixo, no mesmo ciclo de execução do script — leem o banco recém
  atualizado sem precisar de rerun. Um rerun faria a mensagem de sucesso
  (com os totais regenerados) sumir antes do usuário conseguir ler —
  achado ao testar com Playwright a primeira versão do botão.
- **Escopo deliberadamente limitado**: só relê XML já classificado em
  `ET`/`EP` — não roda `loader.carregar_operacao()` (classificação de
  XML novo ainda pendente na raiz de `1-DOCFISCAIS/nf/`), que continua
  sendo exclusivo do botão "Carregar novamente" da página EXTRAÇÃO.
- Validado ao vivo (Playwright, porta descartável 8601): clique mostra
  spinner, depois mensagem de sucesso com os totais
  (`"✅ Regenerado: N entradas reais, N saídas reais → N entradas / N
  saídas enriquecidas."`), seguida das duas auditorias já com dados
  frescos, tudo no mesmo carregamento de página.

## Auditoria de Divergência de Estoque (2026-07-17, mesmo dia)

Terceiro espelho na página AUDITORIA1, pedido pelo usuário logo após fechar
entradas/saídas ("falta agora para os estoques") — ver detalhamento técnico
em [docs/estagios/05_tabela_estoque.md](05_tabela_estoque.md#validação-real-2026-07-12-aprofundada-2026-07-17).

- **`loader.auditar_divergencia_estoque()`**: diferente das duas
  auditorias acima (que cruzam por `CHV_NFE` + contagem de itens, sem
  valor, com waterfall de reconciliação em várias tabelas), aqui a
  comparação é direta de QUANTIDADE por `(COD_ITEM, ANO_REFERENCIA)` —
  ausência de um lado vira quantidade 0, capturando o resíduo
  bidirecional dentro da própria tabela de divergência (sem seção
  "Resíduo Hunter/CSV" separada, diferente das outras duas).
- **`interface.render_auditoria_divergencia_estoque()`**: 4 KPIs (Pares
  Item×Ano, Divergentes, Só no Excel, Só no Hunter) + botão "Investigar
  Itens Divergentes", chamada logo após `render_auditoria_divergencia_
  saidas()` em `render_pagina_auditoria1()`.
- **Achado real ao validar contra a base da geraldo**: quase 100% dos
  pares divergiam (28.705/38.111) — não era bug da auditoria nova, era um
  desvio sistemático de 1 ano em `montar_estoque_anual_consolidado()`
  (Estágio 5): o código gravava `EI(ano_inv)`/`EF(ano_inv-1)`, o oposto do
  que o próprio docstring da função sempre documentou no exemplo
  (`EF(2020)`/`EI(2021)` pra `DT_INV=31/12/2020`). Confirmado deslocando
  `ANO_REFERENCIA` em +1 ano: 31.954/31.955 quantidades bateram
  exatamente. Corrigido nas 4 pastas e `estoque_anual_consolidado`
  regenerado nas 3 operações reais.
- **Revisão "modelo do CSV" (mesmo dia)**: primeira versão comparava
  contra `estoque_anual_consolidado` já expandido no formato "largo"
  (EI/EF separados — 223 linhas na PB, contra 127 do Excel bruto).
  Usuário notou o descompasso e pediu pra comparar na MESMA granularidade
  do Excel — uma linha por declaração física de inventário. Confirmado
  que `load_declaracao_estoque()` (H010 cru, pré-Estágio 5) já bate quase
  exato com o Excel nas 3 operações (geraldo 25.600×25.590, PB2 127×127
  exato, cometa 75×75 exato) — reescrito `carregar_excel_estoque_
  referencia()` e novo `loader._declaracoes_estoque_hunter()` pra comparar
  direto nessa granularidade, dispensando o Estágio 5 como pré-requisito.
- **Investigação do `COD_ITEM=4` da cometa (a pedido do usuário)**: falso
  positivo, não divergência real. `COD_ITEM=4` é usado por dois produtos
  diferentes no SPED cru desta operação (`"0000000004"` = FEIJAO CARIOCA
  AG, `"4"` sem padding = FEIJAO MACASSAR) — colidem no mesmo código
  normalizado. O Excel de referência tem a MESMA colisão (2 linhas,
  descrições diferentes), e os valores batiam perfeitamente par a par
  (17.933,5 e 6.873,7 dos dois lados) — mas `groupby(...).first()`
  comparava a declaração errada entre si, reportando 11.059,8 de
  divergência que não existia. Trocado por nova
  `loader._ordenar_duplicatas_por_quantidade()`: quando há mais de uma
  linha por `(COD_ITEM, ANO)` de um lado, casa pela quantidade mais
  próxima (ótimo pra minimizar diferença total) em vez de pela ordem do
  arquivo — mesma técnica resolve de quebra a duplicidade da geraldo,
  agora isolando corretamente as 10 declarações espúrias de `31/01/2020`
  como "só no Hunter" em vez de mascará-las.
- Divergência final: **0/127 (PB2 — reconciliação total), 0/75 (cometa —
  reconciliação total, incluindo o `COD_ITEM=4`), 10/25.600 (geraldo — as
  10 duplicidades conhecidas de `31/01/2020`, nenhuma divergência real de
  valor)**.
- **Escopo pelo Período de Auditoria (2026-07-18)**: usuário avisou que o
  período da geraldo mudou pra 2021-2024 e reafirmou a regra de mapeamento
  estoque↔declaração (consistente com a correção de 1 ano acima, e
  confirmada de forma independente por um comentário pré-existente em
  `loader.verificar_cobertura_periodo()`). `config_auditoria` já tinha
  período configurado nas 3 operações reais (geraldo 2021-2024, PB2
  2023-2025, cometa 2021-2025), mas a auditoria de estoque ignorava esse
  escopo — comparava todos os anos presentes nos dados brutos. Confirmado
  com o usuário (`AskUserQuestion`) e filtrado `ANO_REFERENCIA` por
  `obter_periodo_auditoria()` em `auditar_divergencia_estoque()` (sem
  período configurado, mantém mostrando tudo); `resumo['periodo']`
  devolvido pra UI mostrar o escopo aplicado. **As 3 operações reais
  fecham 100% agora**: geraldo 0/15.840 (era 10/25.600 — as 10
  duplicidades de `31/01/2020` caem fora do período 2021-2024), PB2 0/127
  (sem mudança), cometa 0/67 (era 0/75 — só reduziu o universo de pares,
  já não tinha divergência de valor).
- Validado via script direto contra as 3 bases reais (`loader.
  auditar_divergencia_estoque()` importado com o runtime portátil de cada
  operação) — sem Playwright nesta sessão (ferramenta de browser
  indisponível); recomenda-se um clique manual em "AUDITORIA1" na próxima
  sessão com Streamlit rodando pra confirmar visualmente os 3 painéis.

## Filtro de Período de Auditoria estendido pra entradas/saídas (2026-07-18, mesmo dia)

Depois do filtro acima (só na auditoria de estoque), usuário perguntou
"de não estender o filtro? como assim?" — achado que eu tinha registrado
por engano uma confirmação que nunca foi dada (a pergunta anterior era só
sobre o Estágio 5/Tabela de Estoque, não sobre entradas/saídas).
Perguntado de novo especificamente, usuário confirmou: quer o mesmo
filtro de Período de Auditoria nas auditorias de entradas e saídas
também.

- Novas `loader._filtrar_serie_chv_por_periodo()`/`_filtrar_df_chv_por_
  periodo()`: filtram por ano embutido nos dígitos 3-4 da `CHV_NFE` ('AA'
  → '20AA'), recebendo o `periodo` já resolvido como parâmetro (evita
  reabrir o banco a cada série filtrada).
- Aplicado em `auditar_divergencia_entradas()`/`auditar_divergencia_
  saidas()`: `df_excel` e as 4 séries Hunter (principal, fallback,
  situação, análise CFOP) filtradas ANTES do waterfall de reconciliação.
  `resumo['periodo']` devolvido igual à auditoria de estoque.
- Nova `interface._texto_periodo_auditoria()` — legenda compartilhada
  pelas 3 auditorias (a de estoque usava uma versão inline duplicada,
  refatorada pra reusar a mesma função).
- **Reconciliação continua 100% nas 3 operações reais, mesmo restrita ao
  período**: geraldo (entradas 12.614×12.855, saídas 37.300×37.541), PB2
  (entradas 1.279×1.282, saídas 11.359×11.362 — sem mudança, período já
  cobria tudo), cometa (entradas 6.583×6.629, saídas 179.303×179.349) —
  todas com resíduo 0.
- Agora **as 3 auditorias da página AUDITORIA1 respeitam o Período de
  Auditoria** de forma consistente.

## 6º botão — "DESCRIÇÃO RELEVANTE" (Estágio 7.1, 2026-07-18)

Solicitação Técnica pedindo um novo módulo pra eleger, por `COD_ITEM`, a
descrição estatisticamente mais frequente (moda) entre as 3 tabelas
enriquecidas que carregam `COD_ITEM_DECLARACAO`/`DESCR_ITEM_DECLARACAO`
— usuário chama essas 3 fontes informalmente de "entradas, saídas e
estoque" (nomes reais no DuckDB mantidos sem mudança: `estoque_entradas`/
`estoque_saidas`, Estágio 4; `estoque_anual_consolidado`, Estágio 5) — um
mesmo produto pode ter grafias diferentes entre as 3 fontes (erro de
digitação, abreviação, atualização de cadastro). Serve de nome "oficial"
pra padronizar relatórios e apoiar a seleção de produtos pra auditoria
física.

Numeração: Estágio 7 é "Escolha do Produto Alvo" (mais amplo, ainda em
andamento); este módulo é o sub-passo **7.1** ("Fixação da Descrição
Relevante") — primeiro precedente de numeração `N.M` no projeto (o
Estágio 6 não numerou seus 6 grupos internos dessa forma). Sub-passos
seguintes (7.2 em diante) ainda não especificados.

- **`loader.montar_produto_alvo()`/`persistir_produto_alvo()`**: `UNION
  ALL` das 3 tabelas fonte (só as que já existirem — não exige as 3),
  excluindo `COD_ITEM_DECLARACAO` nulo ou igual (case-insensitive) a
  `'nd'`/`'nm'` — sentinelas de "não declarado"/"não mapeado" do Matching
  (BC3). Agrupa por `(COD_ITEM, DESCR)` contando ocorrências; elege a
  maior contagem por `COD_ITEM`, empate desempatado em ordem alfabética
  (A-Z) via `sort_values([...], ascending=[True, False, True]) +
  groupby(...).first()` — mesmo idioma de `_ordenar_duplicatas_por_
  quantidade()` (2026-07-17). Persiste em `produto_alvo` (colunas
  `COD_ITEM`, `DESCR_ALVO`, Regra R07 — `COD_ITEM` string).
- **Achado real ao filtrar 'nd'/'nm'**: `COD_ITEM_DECLARACAO` NÃO é
  sempre numérico (diferente do Bloco H usado na Auditoria de Estoque) —
  a cometa tem códigos alfanuméricos legítimos (`"125KGRAXA"`, `"CQ4533T"`,
  `"PO916UNF"`). Por isso o filtro de sentinela é por IGUALDADE exata
  (case-insensitive), não por substring "contém nd/nm" — substring
  arriscaria excluir um código real que só coincidentemente contivesse
  essas letras.
- **`interface.render_descricao_relevante()`/`render_pagina_
  descricao_relevante()`**: mesmo padrão "Gerar/Regerar" + prévia (200
  linhas) + total de `render_estoque_anual()`, com `_preparar_preview()`
  traduzindo `COD_ITEM`/`DESCR_ALVO` pelo Dicionário de Campos ("Cod.
  Produto"/"Descrição Relevante", 2 entradas novas em `DICIONARIO DE
  CAMPOS.txt`).
- **Navegação**: `render_menu_principal()` ganhou um 6º botão ("🏷️
  DESCRIÇÃO RELEVANTE", `pagina_ativa="descricao_relevante"`) — a
  Solicitação Técnica pediu explicitamente um botão de PRIMEIRO NÍVEL no
  Menu Principal, não um sub-painel dentro de "TABELAS ENTRADAS / SAÍDAS
  / ESTOQUES" (que é onde a nota de numeração original de 2026-07-14
  reservava os números 7-14) — ver nota atualizada em
  `ESTAGIOS_PROJETO.md`. `main.py` ganhou o roteamento correspondente.
- **Validado nas 3 operações reais** (script direto, runtime portátil de
  cada uma): geraldo 6.138 produtos únicos, PB2 269, cometa 2.617 — sem
  nenhum código `'nd'`/`'nm'` ou nulo remanescente. Nenhuma das 3
  operações tem hoje um `COD_ITEM` com mais de uma descrição distinta
  entre as 3 fontes (moda sempre trivial na prática atual — a lógica de
  desempate por ordem alfabética existe pra quando isso deixar de ser
  verdade, não foi exercitada com um caso real de empate).

## 7º botão — "7.2: CRUZAMENTO POR VALOR" (Estágio 7.2, 2026-07-18, mesmo dia)

Solicitação Técnica seguinte, pedindo um segundo sub-passo do Estágio 7
("Escolha do Produto Alvo"): elevar a métrica de análise de QUANTIDADE
(Auditoria de Estoque, Estágio 5) pra VALOR (R$), aplicando a identidade
contábil `EI + Compras = Vendas + EF` por `(ANO, COD_ITEM)` — perspectiva
híbrida definida pelo usuário: Compras (`estoque_entradas`) e Estoque
(Bloco H) pela visão da própria auditada, Vendas (`estoque_saidas`) pela
visão física do XML.

- **Lacuna de dados achada antes de implementar**: `estoque_anual_
  consolidado` (Estágio 5) não tem NENHUMA coluna de valor — só
  `QUANTIDADE_INICIAL`/`QUANTIDADE_FINAL`. O `VL_ITEM` do inventário
  existe no SPED cru (H010), mas nunca foi carregado pra tabela
  consolidada. **Perguntado ao usuário antes de mexer** (`AskUserQuestion`):
  construir uma função paralela que lê `VL_ITEM` direto do SPED cru (sem
  tocar o Estágio 5) ou estender o schema de `estoque_anual_consolidado`
  (exigiria regenerar as 3 operações reais). Confirmado: função paralela
  — `loader._valores_estoque_hunter()`, mesma técnica de `_declaracoes_
  estoque_hunter()` (Auditoria de Estoque), mas no formato "largo"
  (EI/EF na mesma linha, não uma linha por declaração) porque o relatório
  pedido precisa das duas colunas juntas por `(ANO, COD_ITEM)`.
- **Segundo achado real**: `fatoitemnfe_infnfe_det_prod_vprod` ("Valor
  bruto do produto", a coluna de valor de `estoque_entradas`/
  `estoque_saidas` — não existe coluna literal `VL_ITEM` nessas tabelas)
  é gravada como `VARCHAR`, quebrando `SUM()` direto no DuckDB
  (`Binder Error: no function matches sum(VARCHAR)`) — achado só ao
  testar contra as 3 bases reais. Corrigido com `SUM(TRY_CAST(... AS
  DOUBLE))`; confirmado que a coluna é sempre decimal com PONTO nas 3
  operações reais (nunca vírgula, nunca nula/vazia), então não precisou
  de `REPLACE` de vírgula.
- **`loader._valores_por_ano_item(tabela, coluna_ano)`**: soma o valor
  por `(COD_ITEM_DECLARACAO, coluna_ano)` numa tabela do Estágio 4 —
  usada pra Compras (`estoque_entradas`, `ANO_ELEITO`) e Vendas
  (`estoque_saidas`, `ANO_ELEITO`).
- **`loader.gerar_cruzamento_valor()`**: `outer merge` de Compras/Vendas/
  Estoque por `(ANO, COD_ITEM)`, ausência de uma métrica vira 0 (mesmo
  padrão das 3 auditorias), depois `INNER JOIN` com `produto_alvo`
  (Estágio 7.1) — itens sem `DESCR_ALVO` (código `'nd'`/`'nm'`/nulo)
  ficam de fora, mesmo critério de 7.1. Calcula `TOTAL_DEBITO=EI+COMPRAS`,
  `TOTAL_CREDITO=VENDAS+EF`, `DIVERGENCIA=TOTAL_DEBITO-TOTAL_CREDITO`.
  Restrito ao Período de Auditoria configurado (confirmado com o usuário
  — consistente com as 3 auditorias de AUDITORIA1).
- **`interface.render_cruzamento_valor()`/`render_pagina_
  cruzamento_valor()`**: botão "Gerar/Regerar" + prévia, com filtro
  `st.multiselect` por Ano e `st.text_input` de busca por Descrição
  (aplicados sobre a tabela já persistida, sem reprocessar). Tradução via
  Dicionário de Campos (8 entradas novas: `ANO`, `EI`, `COMPRAS`,
  `TOTAL_DEBITO`, `VENDAS`, `EF`, `TOTAL_CREDITO`, `DIVERGENCIA`).
- **Navegação**: 7º botão em `render_menu_principal()` ("📉 7.2:
  CRUZAMENTO POR VALOR", `pagina_ativa="cruzamento_valor"`) + roteamento
  em `main.py` — mesmo padrão de botão de 1º nível do Estágio 7.1.
- **Relação com o Estágio 15 (RN1)**: este painel já monta a identidade
  `EI+C=V+EF` em valor, mas SEM a lógica de PU (preço unitário) e
  omissão do texto original da RN1 (condições `c>0`/`c=0`, cálculo de PU
  distinto pra cada uma) — isso continua reservado pro Estágio 15.
- **Validado nas 3 operações reais** (script direto): geraldo 17.889
  linhas/5.717 produtos, PB2 350 linhas/252 produtos, cometa 3.152
  linhas/2.616 produtos — sem erro nas 3, divergências reais e variadas
  (ex.: cometa tem itens com Compras alta e Vendas zerada no período —
  achado a investigar por auditoria física, não um bug desta função).

## Ver também

- [Estágio 15 — Cálculo de divergência RN1](../../ESTAGIOS_PROJETO.md) —
  próximo painel a entrar no grupo "Painéis em Construção" quando for
  implementado; motivo da renumeração 6→15 deste estágio.
- `main.py` / `interface.py` (`OPERACOES/*/ESSENCIAL/app/`) — implementação
  de referência.
