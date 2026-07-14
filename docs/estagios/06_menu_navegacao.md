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
`"extracao"`; `"segregados"`; `"construcao"`), inicializado em `main.py` no
início de `main()`. `main.py` despacha para uma das funções de
`interface.py` conforme o valor:

- **`interface.render_menu_principal()`** — 3 botões (`st.columns(3)`):
  "📥 EXTRAÇÃO", "🔀 SEGREGADOS" e "🚧 PAINÉIS EM CONSTRUÇÃO". Cada um seta
  `pagina_ativa` e chama `st.rerun()`.
- **`interface.render_pagina_extracao()`** — botão de retorno
  (`_botao_voltar_menu()`) + `render_configuracao_periodo()` +
  `render_carga_operacao()` (já inclui os alertas de cobertura do Período
  de Auditoria e de Ancoragem de Estoque/Bloco H) + `render_entidade_auditada()`
  (só depois de `dados_carregados=True`). Mesmo conteúdo que antes ficava
  direto em `main.py`, sem nenhuma mudança de comportamento.
- **`interface.render_pagina_segregados()`** (botão próprio desde
  2026-07-14) — botão de retorno + (se `dados_carregados`)
  `render_painel_analise()`: "CFOPs Não Autorizados" (com o botão "CFOPS
  SEGREGADOS", união ET+EP) e "Notas Não Autorizadas" — nomes de exibição
  escolhidos pelo usuário em 2026-07-14 (ver seção "Nomes de exibição"
  abaixo).
- **`interface.render_pagina_construcao()`** — botão de retorno + (se
  `dados_carregados`) `render_entradas_terceiros()` (BC1),
  `render_bc3()` (Estágio 2), `render_fluxos_fisicos()` (Estágio 3),
  `render_estoque_anual()` (Estágio 5) e
  `render_auditoria_divergencia_entradas()`. Sem `dados_carregados`, mostra
  só um aviso orientando a ir em "Extração" primeiro.
- **`interface._botao_voltar_menu()`** — botão "⬅️ Voltar ao Menu
  Principal" no topo dos 3 painéis; seta `pagina_ativa=None` e chama
  `st.rerun()`.

**O Estágio 4** (Cronologia/`DATA_ELEITA`) não tem painel próprio (ver
[docs/estagios/04_cronologia_ano_eleito.md](04_cronologia_ano_eleito.md)) —
por isso não aparece em "Painéis em Construção".

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

## Decisão de agrupamento — BC1/Auditoria em "Construção"

A especificação original só detalhou o conteúdo de "Extração" (Período +
Carga + Entidade Auditada) e citou "Painéis em Construção" como "Estágios 2
ao 5 (Matching BC3, Fluxos Físicos, Estoque Anual, etc.)". Dois painéis não
foram explicitamente posicionados: `render_entradas_terceiros()` (geração
da BC1/`sped_entradas_terceiros`) e `render_auditoria_divergencia_entradas()`
(Excel × Hunter). Ambos ficaram em "Painéis em Construção" — são painéis de
análise/conferência sobre o resultado do cruzamento, não dados desviados
dele (diferente de "Segregados") — mas essa é uma interpretação, não uma
instrução explícita; ajustar se o usuário quiser outro agrupamento.

## Ver também

- [Estágio 15 — Cálculo de divergência RN1](../../ESTAGIOS_PROJETO.md) —
  próximo painel a entrar no grupo "Painéis em Construção" quando for
  implementado; motivo da renumeração 6→15 deste estágio.
- `main.py` / `interface.py` (`OPERACOES/*/ESSENCIAL/app/`) — implementação
  de referência.
