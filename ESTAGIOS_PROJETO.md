# Estágios do Projeto (AI_HUNTER1.1)

Índice dos grandes estágios do fluxo Hunter, do dado bruto (XML/SPED) até o
cruzamento final. Cada estágio tem seu detalhamento em `docs/estagios/`.
Fonte original da lista: `estágios.txt` (raiz).

| # | Estágio | Status | Detalhe |
|---|---|---|---|
| 1 | Extração | ✅ Implementado | [docs/estagios/01_extracao.md](docs/estagios/01_extracao.md) |
| 2 | Criação BC3 — busca de código de produto do auditado para produtos ET do fornecedor | ✅ Implementado | [docs/estagios/02_criacao_bc3.md](docs/estagios/02_criacao_bc3.md) |
| 3 | Criação das entradas, saídas e estoques para fins de cruzamento | ✅ Implementado (xml_entradas_real/xml_saidas_real — falta a etapa de estoque em si, coberta pelo Estágio 4) | [docs/estagios/03_fluxos_fisicos.md](docs/estagios/03_fluxos_fisicos.md) |
| 4 | Implantação das regras das datas nas ET e nas EP | 🚧 Em andamento (DATA_ELEITA/ANO_ELEITO e estoque_entradas/estoque_saidas implementados; cálculo de saldo de estoque ainda pendente) | [docs/estagios/04_cronologia_ano_eleito.md](docs/estagios/04_cronologia_ano_eleito.md) |

## Como usar este índice

- Cada estágio novo ganha uma linha aqui e um arquivo próprio em
  `docs/estagios/NN_nome.md`.
- Atualizar o `Status` (⏳ Planejado / 🚧 Em andamento / ✅ Implementado)
  conforme o trabalho avança.
- Estágios que já têm documentação própria e detalhada em outro lugar do
  projeto (ex.: o motor de Matching em `REGRAS_MATCHING.md`) não duplicam o
  conteúdo aqui — o arquivo do estágio só resume e aponta pra fonte
  detalhada.
