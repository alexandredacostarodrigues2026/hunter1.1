# Estágios do Projeto (AI_HUNTER1.1)

Índice dos grandes estágios do fluxo Hunter, do dado bruto (XML/SPED) até o
cruzamento final. Cada estágio tem seu detalhamento em `docs/estagios/`.
Fonte original da lista: `estágios.txt` (raiz).

| # | Estágio | Status | Detalhe |
|---|---|---|---|
| 1 | Extração | ✅ Implementado (XML: nfe_entradas/saidas + analise/situacao ET-EP; SPED: sped_itens/produtos/unidades; BC2/BC1; Período de Auditoria) | [docs/estagios/01_extracao.md](docs/estagios/01_extracao.md) |
| 2 | Criação BC3 — busca de código de produto do auditado para produtos ET do fornecedor | ✅ Implementado | [docs/estagios/02_criacao_bc3.md](docs/estagios/02_criacao_bc3.md) |
| 3 | Criação das entradas, saídas e estoques (movimentação) para fins de cruzamento | ✅ Implementado (xml_entradas_real/xml_saidas_real; prévia enriquecida com COD_ITEM_DECLARACAO/FATOR_MULTIPLICADOR_SUGERIDO da bc3 desde 2026-07-14) | [docs/estagios/03_fluxos_fisicos.md](docs/estagios/03_fluxos_fisicos.md) |
| 4 | Implantação das regras das datas nas ET e nas EP | ✅ Implementado (DATA_ELEITA/ANO_ELEITO, tabelas estoque_entradas/estoque_saidas — **ainda é movimentação, não estoque**, apesar do nome; ganhou primeiro painel próprio na UI em 2026-07-14, dentro de "Tabelas Entradas / Saídas / Estoques") | [docs/estagios/04_cronologia_ano_eleito.md](docs/estagios/04_cronologia_ano_eleito.md) |
| 5 | Geração da Tabela de Estoque (consolidação do inventário declarado, Bloco H) | ✅ Implementado (estoque_anual_consolidado — foco só em consolidação; **é aqui que o "estoque" passa a existir de fato**; regra de continuidade corrigida em 2026-07-17, desvio de 1 ano; Auditoria de Divergência de Estoque vs. Excel de referência implementada e fechando 100% nas 3 operações reais desde 2026-07-18 — restrita ao Período de Auditoria configurado, ver AUDITORIA1 no Estágio 6; cálculo de divergência/RN1 propriamente dito — cruzando contra a movimentação do Estágio 4 — fica pra uma etapa futura, Estágio 15) | [docs/estagios/05_tabela_estoque.md](docs/estagios/05_tabela_estoque.md) |
| 6 | VAMOS ORGANIZAR (Menu de Navegação) — reorganiza a tela única em 4 grupos navegáveis: "Extração" (Período/Carga/Entidade Auditada), "Matching (BC3)" (Estágio 2 — motor D1-D6/A1-A5, com BC1 como subcomponente num expander), "Segregados" (CFOPs Não Autorizados/Notas Não Autorizadas — não entram no cômputo do cruzamento) e "Tabelas Entradas / Saídas / Estoques" (Estágios 3-5 + Auditoria; renomeado de "Painéis em Construção" em 2026-07-14) | 🚧 Em andamento | [docs/estagios/06_menu_navegacao.md](docs/estagios/06_menu_navegacao.md) |
| 7 | Escolha do Produto Alvo — seleciona, entre os produtos movimentados/declarados, quais serão efetivamente auditados | 🚧 Em andamento (7.1, 7.2 e 7.2.1 implementados) | sem doc própria ainda |
| 7.1 | Fixação da Descrição Relevante — elege a descrição mais frequente (moda) por COD_ITEM entre entradas, saídas (Estágio 4) e estoque (Estágio 5), padronizando o nome "oficial" do produto pra relatórios e seleção de itens pra auditoria física | ✅ Implementado (`produto_alvo`; botão de 6º nível próprio no Menu Principal — "🏷️ DESCRIÇÃO RELEVANTE" — em vez de sub-painel dentro de "Tabelas Entradas/Saídas/Estoques" como a nota de numeração original previa; código normalizado ANTES da moda desde 2026-07-19 — achado real: código curto colidindo entre 4 paddings diferentes elegia a descrição errada; testado nas 3 operações reais: geraldo 6.138 produtos, PB2 269, cometa 2.513) | sem doc própria ainda; ver `interface.render_pagina_descricao_relevante()`/`loader.montar_produto_alvo()` |
| 7.2 | Cruzamento por Valor — aplica EI+Compras=Vendas+EF por (Ano, Produto) em R$, identidade pela Descrição Relevante (7.1); Compras/Estoque pela visão da auditada, Vendas pela visão física do XML; indicadores de risco (Divergência absoluta, Infração, % Diverg) ordenados por maior divergência | ✅ Implementado (`cruzamento_valor`; botão de 7º nível próprio no Menu Principal — "📉 7.2: CRUZAMENTO POR VALOR"; Vendas corrigida em 2026-07-18 pra usar `cprod` do XML + excluir autoemissão — ver `docs/estagios/06_menu_navegacao.md`; validado contra referência de produção do usuário — "FRALDA NENE BABY 3" fecha 100% nos 4 anos; direção de `INFRACAO` (2026-07-19) confirmada contra a RN1 já documentada; teto ">1000%" e formatação BR na tela desde 2026-07-19; testado nas 3 operações reais) | sem doc própria ainda; ver `interface.render_pagina_cruzamento_valor()`/`loader.gerar_cruzamento_valor()` |
| 7.2.1 | Cruzamento por Produto — condensa o 7.2 (uma linha por Ano+Produto) numa linha por Descrição Relevante, somando os valores financeiros e recalculando Infração/% Diverg sobre os totais acumulados; drill-down pro detalhamento anual de um produto selecionado | ✅ Implementado (`cruzamento_produto`; botão de 8º nível próprio no Menu Principal — "📊 7.2.1: CRUZAMENTO POR PRODUTO"; direção de `INFRACAO` (2026-07-19) mantida igual ao 7.2, confirmada com o usuário antes de implementar por divergir do texto da Solicitação Técnica; testado ao vivo na geraldo — 5.721 produtos condensados) | sem doc própria ainda; ver `interface.render_pagina_cruzamento_produto()`/`loader.gerar_cruzamento_produto()` |
| 15 | Cálculo de divergência RN1 (Estoque Inicial + Compras = Vendas + Estoque Final) — compara o inventário declarado (Estágio 5) com a movimentação real (Estágio 4), com a lógica de PU (preço unitário) e omissão do texto original | ⏳ Planejado — o Estágio 7.2 já monta a identidade EI+C=V+EF em valor, mas sem a lógica de PU/omissão do texto original (condições c>0/c=0, tie-break) | sem doc própria ainda; ver `regra de negócios unificadas/regra negocio_pu_rn1_ei+c=v+ef_1.txt` (raiz) e nota em [docs/estagios/04_cronologia_ano_eleito.md](docs/estagios/04_cronologia_ano_eleito.md) |

## Como usar este índice

- Cada estágio novo ganha uma linha aqui e um arquivo próprio em
  `docs/estagios/NN_nome.md`.
- Atualizar o `Status` (⏳ Planejado / 🚧 Em andamento / ✅ Implementado)
  conforme o trabalho avança.
- Estágios que já têm documentação própria e detalhada em outro lugar do
  projeto (ex.: o motor de Matching em `REGRAS_MATCHING.md`) não duplicam o
  conteúdo aqui — o arquivo do estágio só resume e aponta pra fonte
  detalhada.
- Numeração não é estritamente sequencial (ver o salto 6 → 15): o Estágio 6
  original (cálculo de divergência RN1) foi renumerado para 15 em
  2026-07-14 para abrir espaço, no 6, para o menu de navegação — os números
  7-14 ficam reservados para painéis intermediários futuros, sem precisar
  renumerar de novo. **Atualizado 2026-07-18**: o Estágio 7 ("Escolha do
  Produto Alvo") usou esse espaço reservado, com sub-passos numerados
  `7.1`, `7.2`... (primeiro precedente de numeração `N.M` neste índice —
  o Estágio 6, "VAMOS ORGANIZAR", não teve seus grupos internos numerados
  dessa forma). O sub-passo 7.1 ("Fixação da Descrição Relevante") virou
  — por Solicitação Técnica explícita — botão de 6º nível PRÓPRIO no Menu
  Principal, não um sub-painel dentro de "Tabelas Entradas / Saídas /
  Estoques" como a reserva original previa; os números 8-14 continuam
  livres pra painéis futuros, do mesmo jeito (sub-painel ou botão
  próprio, a decidir caso a caso).
