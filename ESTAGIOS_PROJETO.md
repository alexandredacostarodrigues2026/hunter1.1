# Estágios do Projeto (AI_HUNTER1.1)

Índice dos grandes estágios do fluxo Hunter, do dado bruto (XML/SPED) até o
cruzamento final. Cada estágio tem seu detalhamento em `docs/estagios/`.
Fonte original da lista: `estágios.txt` (raiz).

| # | Estágio | Status | Detalhe |
|---|---|---|---|
| 1 | Extração | ✅ Implementado (XML: nfe_entradas/saidas + analise/situacao ET-EP; SPED: sped_itens/produtos/unidades; BC2/BC1; Período de Auditoria) | [docs/estagios/01_extracao.md](docs/estagios/01_extracao.md) |
| 2 | Criação BC3 — busca de código de produto do auditado para produtos ET do fornecedor | ✅ Implementado | [docs/estagios/02_criacao_bc3.md](docs/estagios/02_criacao_bc3.md) |
| 3 | Criação das entradas, saídas e estoques (movimentação) para fins de cruzamento | ✅ Implementado (xml_entradas_real/xml_saidas_real; prévia enriquecida com COD_ITEM_DECLARACAO/FATOR_MULTIPLICADOR_SUGERIDO da bc3 desde 2026-07-14) | [docs/estagios/03_fluxos_fisicos.md](docs/estagios/03_fluxos_fisicos.md) |
| 4 | Implantação das regras das datas nas ET e nas EP | ✅ Implementado (DATA_ELEITA/ANO_ELEITO, tabelas estoque_entradas/estoque_saidas — **ainda é movimentação, não estoque**, apesar do nome; ver Objetivo do detalhe) | [docs/estagios/04_cronologia_ano_eleito.md](docs/estagios/04_cronologia_ano_eleito.md) |
| 5 | Geração da Tabela de Estoque (consolidação do inventário declarado, Bloco H) | ✅ Implementado (estoque_anual_consolidado — foco só em consolidação; **é aqui que o "estoque" passa a existir de fato**; cálculo de divergência/RN1 fica pra uma etapa futura, Estágio 15) | [docs/estagios/05_tabela_estoque.md](docs/estagios/05_tabela_estoque.md) |
| 6 | VAMOS ORGANIZAR (Menu de Navegação) — reorganiza a tela única em 3 grupos navegáveis: "Extração" (Período/Carga/Entidade Auditada), "Segregados" (CFOPs Não Autorizados/Notas Não Autorizadas — não entram no cômputo do cruzamento) e "Painéis em Construção" (Estágios 2-3-5 + BC1/Auditoria) | 🚧 Em andamento | [docs/estagios/06_menu_navegacao.md](docs/estagios/06_menu_navegacao.md) |
| 15 | Cálculo de divergência RN1 (Estoque Inicial + Compras = Vendas + Estoque Final) — compara o inventário declarado (Estágio 5) com a movimentação real (Estágio 4) | ⏳ Planejado — nenhuma função no código a executa ainda | sem doc própria ainda; ver `regra de negócios unificadas/regra negocio_pu_rn1_ei+c=v+ef_1.txt` (raiz) e nota em [docs/estagios/04_cronologia_ano_eleito.md](docs/estagios/04_cronologia_ano_eleito.md) |

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
  7-14 ficam reservados para painéis intermediários futuros dentro do grupo
  "Painéis em Construção", sem precisar renumerar de novo.
