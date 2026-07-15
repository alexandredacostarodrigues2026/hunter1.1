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

## Ver também

- [Estágio 15 — Cálculo de divergência RN1](../../ESTAGIOS_PROJETO.md) —
  próximo painel a entrar no grupo "Painéis em Construção" quando for
  implementado; motivo da renumeração 6→15 deste estágio.
- `main.py` / `interface.py` (`OPERACOES/*/ESSENCIAL/app/`) — implementação
  de referência.
