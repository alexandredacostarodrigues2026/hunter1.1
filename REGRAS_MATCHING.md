# Regras de Matching (BC2 × BC1 → BC3)

> Fonte única e sempre atualizada dos critérios de cada Tipo do motor de
> Matching. Sempre que `matching.py` mudar (novo tipo, limiar ajustado, ordem
> de execução alterada), atualizar este arquivo na mesma edição, em todas as
> operações (ver `OPERACOES/*/ESSENCIAL/app/matching.py` — código-fonte em
> `geraldo_2020_2024`, sincronizado para `PB2`, `cometa` e `_MODELO_OPERACAO`).

Implementação de referência: `matching.py` (docstring do módulo + função
`executar_matching()`).

> **Numeração renomeada em 2026-07-09** (Tipo 1→D1, Tipo 2→D2, Tipo 3→A1,
> Tipo 3.1→A2, Tipo 3.2→A3, Tipo 3.3→A4, Tipo 3.4→A5, Tipo 4→D3, Tipo 5→D4 —
> nomes válidos naquela data; ver renumeração de 2026-07-11 abaixo, que
> reatribuiu D3/D4/D5 pra refletir a ordem de execução).
> Ver `HIERARQUIA_TIPOS_TP_ALEXANDRE_vs_TP_IA.md` para a proposta original e
> o raciocínio. Critérios, limiares e ordem de execução não mudaram — só os
> nomes/rótulos (inclusive os valores gravados em `MATCH_TIPO` no banco).

## Visão geral

Cruza a BC2 (XML — itens de Emissão de Terceiros) com a BC1 (SPED —
`sped_entradas_terceiros`) para produzir a BC3, sem depender de `NUM_ITEM`
como chave — a ordem sequencial dos itens no XML do fornecedor não
necessariamente bate com a ordem de escrituração no SPED do declarante.

Duas famílias:

- **Família D (Direto)** — D1, D2, D4, D5, D3, D6 — casam sempre **dentro
  da mesma `CHV_NFE`**. Todos são 1-para-1 (um item do XML para uma linha do
  SPED), **exceto o D3**, que é N-para-1 de propósito (vários itens do XML
  para uma única linha "consolidada"/"sortido" do SPED).
- **Família A (Aprendizado)** — A1, A2, A3, A4, A5 — dicionário de
  aprendizado histórico e **não exigem a mesma `CHV_NFE`** — recuperam
  inclusive itens cuja nota inteira não está declarada (`nd`).

Cada nível só tenta casar o que sobrou do nível anterior.

## Ordem de execução e critérios

| Ordem | Tipo | Critério | Limiar | Exige mesma CHV_NFE? | Roda sobre |
|---|---|---|---|---|---|
| 1 | **D1** | mesmo EAN/GTIN (`COD_BARRA` SPED == `cean` XML, normalizados) **e** similaridade de descrição normalizada (`xprod` × `DESCR_ITEM`) | `LIMIAR_D1 = 0,90` | Sim | todos os itens |
| 2 | **D2** (fallback) | mesmo Valor Total do item (`VL_ITEM` idêntico — valor daquela linha/produto, não da nota inteira) **e** similaridade de descrição normalizada | `LIMIAR_D2 = 0,60` | Sim | sobra do D1 |
| 3 | **A1** (aprendizado histórico) | dicionário construído só com matches confirmados de D1/D2: `CNPJ_EMITENTE + COD_ITEM (XML) + ANO_EMISSAO` | sem limiar (lookup exato) | Não | `nd`/`nm` restantes |
| 4 | **A2** (aprendizado por descrição) | igual ao A1, trocando `COD_ITEM` pela descrição exata normalizada do XML (`xprod`): `CNPJ_EMITENTE + DESCR_ITEM (normalizada) + ANO_EMISSAO` | sem limiar | Não | `nd`/`nm` restantes após A1 |
| 5 | **A3** (aprendizado por código, sem ano) | fallback do A1: mesma chave, mas **sem** `ANO_EMISSAO` — `CNPJ_EMITENTE + COD_ITEM` | sem limiar | Não | `nd`/`nm` restantes após A2 |
| 6 | **A4** (aprendizado por descrição, sem ano) | fallback do A2: mesma chave, mas **sem** `ANO_EMISSAO` — `CNPJ_EMITENTE + DESCR_ITEM (normalizada)` | sem limiar | Não | `nd`/`nm` restantes após A3 |
| 7 | **A5** (aprendizado só por descrição) | fallback do A4: relaxa também o `CNPJ_EMITENTE` — chave só `DESCR_ITEM (normalizada)` | sem limiar | Não | `nd`/`nm` restantes após A4 |
| 8 | **D3** (consolidação N-para-1) | agrupa vários itens do XML numa única linha "consolidada"/"sortido" do SPED — ver seção própria abaixo | `LIMIAR_D3_COBERTURA = 0,60` (cobertura do radical) | Sim | `nd`/`nm` restantes após A5 |
| 9 | **D4** (integridade de nota) | restringe às `CHV_NFE` "íntegras": mesma **contagem de itens da nota** (nº de linhas XML == nº de linhas SPED, para aquela `CHV_NFE`) **e** mesma **soma de `VL_ITEM` da nota** (somatório de todos os itens do XML == somatório de todos os itens do SPED, para aquela `CHV_NFE`) — e casa, só dentro dessas notas, por similaridade normalizada, 1-para-1 | `LIMIAR_D4 = 0,70` | Sim (dentro das notas íntegras) | `nd`/`nm` restantes após D3 |
| 10 | **D5** (último recurso) | casa só por similaridade de descrição normalizada, 1-para-1, sem exigir GTIN, valor ou integridade de nota | `LIMIAR_D5 = 0,70` | Sim | `nd`/`nm` restantes após D4 |
| 11 | **D6** (valor + desempate por texto — último recurso de tudo) | dentro da mesma `CHV_NFE` (sem exigir nota íntegra), casa item a item por **VALOR idêntico**; se o valor empatar (2+ itens com o mesmo valor), desempata por similaridade de descrição só entre os empatados — descarta apenas se a similaridade também empatar | sem limiar de valor; desempate por similaridade sem limiar mínimo | Sim | `nd`/`nm` restantes após D5 |

Funções correspondentes em `matching.py`: `_match_d1_por_nota`,
`_match_d2_por_nota`, `_match_a1`, `_match_a2`, `_match_a3`,
`_match_a4`, `_match_a5`, `_match_d3_por_nota`, `_match_d4_por_nota`,
`_match_d5_por_nota`, `_match_d6_por_nota`.

## Consolidação N-para-1 (D3)

Motivado por um padrão real: o fornecedor pode declarar no SPED uma única
linha "consolidada" (ex.: `ESM LUDURANA BL SORTIDO 8ML`, `SHAMPOO
TOKBOTHANICO SORTIDO 500ML`) representando a soma de N produtos que, no XML,
vêm discriminados um a um (uma linha por tom/fragrância/sabor/tamanho). Sem o
D3, esses N itens do XML ficavam `NM` (ou, pior, 1 deles "vencia" sozinho no
D5 por coincidência de similaridade de texto contra a linha consolidada,
deixando os outros N-1 permanentemente `NM` — ver nota sobre a ordem de
execução abaixo).

- Avaliada e descartada em 2026-07-09 (ver Histórico de mudanças) por
  decisão do usuário; revisitada e implementada em 2026-07-10 com um
  critério mais robusto que a primeira tentativa descartada.
- **Quem entra no grupo candidato** (texto): para cada linha do SPED ainda
  não consumida por D1/D2, mede-se por **token** (não pela string inteira)
  se a descrição do SPED está coberta na descrição de cada item pendente do
  XML da mesma `CHV_NFE` — cada token do SPED é comparado (fuzzy,
  `rapidfuzz.fuzz.partial_ratio` ≥ 0,82, tolera abreviação: `ESM`~`ESMALTE`)
  contra os tokens do item, e a cobertura final é ponderada por **idf**
  (frequência inversa do token na base inteira de `DESCR_ITEM` do SPED) —
  token genérico (`OLEO`, `CREME`, `SORTIDO`, `CAPILAR`) pesa pouco; token
  raro (marca/linha do produto, ex.: `LUDURANA`, `FARMAX`, `MAXTON`) pesa
  muito. Item entra no grupo se cobertura ponderada ≥
  `LIMIAR_D3_COBERTURA = 0,60`. Essa ponderação por raridade é o que evita
  falso positivo por coincidência de palavra genérica entre produtos de
  marcas diferentes — sem ela (ex.: comparando a string inteira,
  `fuzz.token_set_ratio`), o protótipo gerava falsos positivos reais e
  verificáveis: `HAVAIANA COLOR AZUL NAVAL` recuperando itens `H.BRASIL
  AZUL NAVAL` (marca errada, só a cor bateu), `OLEO CAPILAR FARMAX`
  recuperando itens `FIXED` (marca errada, só a categoria+tamanho bateram),
  `TINTA MAXTON K.PRA.3.0` recuperando itens de tom `8.0`/`5.26` (tom
  errado, só a marca bateu).
- **Quem confirma o match** (número): do grupo candidato (texto), só
  confirma se tiver **≥ 2 itens** E a soma de `VL_ITEM` do grupo bater
  **exatamente** com o `VL_ITEM` da linha do SPED (mesma lógica de
  confirmação numérica do D1/D2, via `_valor_numerico`). O texto decide só
  quem *pode* entrar no grupo; o valor decide se o grupo *é* o match.
- **Ambiguidade**: se o mesmo item do XML aparece em mais de um grupo
  candidato (a soma bate exatamente em mais de uma linha do SPED — caso real
  observado: duas variações de tom de tintura com o mesmo valor total),
  **descarta todos os grupos envolvidos** em vez de arriscar uma atribuição
  errada — os itens ficam `ND`/`NM` para revisão manual.
- **Ordem de execução**: roda **antes** do D4/D5 (não depois), de propósito
  — D5 é 1-para-1 só por similaridade e pode "roubar" por coincidência de
  texto a linha do SPED que na verdade é uma consolidação (caso real
  observado: de 5 itens de uma família de fragrância, só 1 vencia sozinho no
  D5 contra a linha `SORTIDO`, deixando os outros 4 permanentemente `NM`
  sem chance de o D3 formar o grupo certo depois).
- Validado na base real do geraldo: 100 grupos, 498 itens recuperados de
  3.962 que estavam `NM`, zero ambiguidade/colisão, sem repetir nenhum dos
  falsos positivos observados no protótipo anterior (marca/tom trocado).

## D6 (só valor, com desempate por texto — último recurso de tudo)

Motivado por um caso real em que a descrição do SPED é genérica ou
simplesmente errada e não bate textualmente com o XML (ex.: `MOLHO BILLY
JACK CHEDDAR 200G` no XML casando com `MOLHO TRÊS QUEIJOS STELLA D'ORO
240G` no SPED — zero similaridade de texto).

**Caso real (operação `geraldo_2020_2024`)**, verificado no Qlik:
`CHV_NFE = 25230207555419000310550010001677321501275587`,
`CNPJ_EMITENTE = 07555419000310`. Item 51 do XML: `MOLHO BILLY JACK
CHEDDAR 200G` (`COD_ITEM = 28330`, `VL_ITEM = 16,32`) — ficava `NM`
(`MATCH_SCORE = 0.0`). Item correspondente no SPED: `MOLHO TRÊS QUEIJOS
STELLA D'ORO 240G` (`COD_ITEM = 00000000016435`, `VL_ITEM = 16,32`).

**Não exige mais "nota íntegra"** (removido em 2026-07-10, no mesmo dia da
criação do D6): a versão original restringia o D6 às `CHV_NFE` onde a nota
inteira batia em contagem de itens e soma de `VL_ITEM` (mesmo pré-requisito
do D4). Mas o A1-A5 (aprendizado) não consome BC1 — vários itens do XML
podem apontar pro mesmo código/descrição histórica sem "reservar" uma linha
específica da BC1. Isso significa que uma linha da BC1 já usada por A1-A5
pra resolver OUTROS itens da mesma nota continua contando como "disponível"
no cálculo de integridade, inflando a contagem/soma do lado SPED. Resultado
real: na própria nota do exemplo acima, a nota inteira tinha 54 itens no
XML contra 40 no SPED (diferença de 14, toda por consolidações A1/A3 em
produtos sem nenhuma relação com o MOLHO — ex.: 8 variações de `BARRA CER
GRANO FIBRA` no XML viraram 1 linha `BARRA CERAIS GRANO FIBRA SORTIDA 20G`
no SPED) — isso bloqueava o D6 de sequer tentar o par MOLHO BILLY JACK ×
MOLHO TRÊS QUEIJOS, mesmo esse par sendo, isoladamente, valor único nos
dois lados. Recalcular a integridade só com os itens pendentes/disponíveis
(em vez da nota inteira) foi tentado primeiro, mas não resolveu — as
linhas já "usadas" por A1-A5 continuam no pool de disponíveis mesmo
restringindo aos pendentes. Decisão do usuário: abandonar a exigência de
integridade de nota no D6 — a segurança passa a vir só da unicidade de
valor (+ desempate por texto, com descarte em caso de empate duplo). O D4
continua exigindo integridade normalmente.

- Roda **por último de tudo** (depois do D5, não antes) — é o critério com
  menos evidência garantida (o valor pode não vir acompanhado de texto), só
  entra sobre o que nenhum outro tipo, que tem alguma evidência de
  texto/código, conseguiu casar.
- Casa, dentro da mesma `CHV_NFE`, item a item por `VL_ITEM` idêntico
  (`_valor_numerico`).
- Valor **único** dos dois lados dentro da nota (exatamente 1 item do XML e
  1 do SPED com aquele valor) confirma direto, `MATCH_SCORE = 1.0`.
- Valor **empatado** (2+ itens com o mesmo valor em qualquer lado, dentro
  da mesma nota) — implementado em 2026-07-10 (mesmo dia da criação do D6),
  a pedido do usuário: em vez de descartar todo o grupo, desempata por
  **similaridade de descrição normalizada** (`_matriz_similaridade`, mesmo
  cálculo usado em D1-D3), calculada só entre os itens empatados naquele
  valor específico — o par de maior similaridade é confirmado
  (`MATCH_SCORE` = a própria similaridade, não 1.0), e o processo se repete
  para os itens remanescentes do grupo (`_atribuir_1_para_1_sem_empate`).
  Só fica sem match (ambos os lados) se a maior similaridade **também**
  empatar entre 2+ pares candidatos — aí não há nenhum sinal, nem valor nem
  texto, pra decidir qual par é o certo, e o código não tenta adivinhar.
  **Exceção** (implementada em 2026-07-10, mesmo dia, a partir de um caso
  real trazido pelo usuário — `CHV_NFE
  25250819447771000150550010000128321164733115`, operação PB2: 2 itens
  `PAP HIG MILI F. DUPLA 30M C/4 FD C/24` no XML, valor 5,99 cada, ficavam
  `NM` mesmo havendo 2 itens `PAP HIG CONFOFEX FS 30M NEUT L12 P11` no
  SPED, mesmo valor): quando os pares empatados no topo são todos o
  **mesmo par de descrições normalizadas** (itens duplicados idênticos dos
  dois lados — mesma descrição, mesmo valor, repetidos N vezes em cada
  lado), o empate é só de posição/índice, não de conteúdo — não há
  ambiguidade real sobre qual produto é (as ocorrências são
  intercambiáveis entre si). Nesse caso confirma mesmo assim (em vez de
  descartar), com `MATCH_SCORE` = a similaridade entre as descrições
  (nesse exemplo, 0,50 — texto bem diferente entre as duas nomenclaturas,
  mas o valor batendo em dobro nos dois lados, com descrição idêntica
  dentro de cada lado, já é suficiente). Validado na base real do
  geraldo: recuperou mais 48 itens (D6 de 2.477 para 2.525, NM de 938
  para 890); PB2 recuperou 2 itens (D6 de 15 para 17, NM de 2 para 0);
  cometa sem mudança.

**Resultado consolidado no geraldo** (soma dos três ajustes de
2026-07-10 — desempate por texto + remoção da exigência de integridade +
exceção de duplicatas idênticas): D6 foi de 1.721 → **2.525** itens
recuperados (NM caiu de 1.694 para **890**). PB2: D6 foi de 15 para
**17** (NM de 2 para **0**), só por causa da exceção de duplicatas
idênticas. Cometa sem mudança (D6 = 29) — não tinha casos afetados por
nenhum dos três ajustes.

## Fator multiplicador sugerido (embalagem/unidade)

Implementado em 2026-07-11, a pedido do usuário: para todo item confirmado
(qualquer Tipo D1-D6, e propagado também pro A1-A5), quando o `VL_ITEM`
(valor total da linha) bate exatamente entre XML e SPED, calcula-se um
sinal adicional — não usado como critério de match, só informativo — que
ajuda a identificar divergência de unidade/embalagem entre as duas bases:

```
FATOR_MULTIPLICADOR_SUGERIDO = _VALOR_UNIT_ORIGINAL (unitário do XML)
                                ÷ VALOR_UNITARIO_DECLARACAO (unitário do SPED)
```

- **`VALOR_UNITARIO_DECLARACAO`** (novo campo da BC1) — o SPED/EFD (registro
  C170) não traz um campo de valor unitário direto, só `QTD` e `VL_ITEM`
  (valor total da linha); derivado em
  `loader.load_declaracao_entradas_terceiros()` como `VL_ITEM ÷ QTD`
  (`QTD` zero ou ausente vira `NaN`, sem tentar adivinhar). A BC2 (XML) já
  traz o unitário faturado direto (`_VALOR_UNIT_ORIGINAL`, campo `vUnCom`
  da NFe), não precisou derivar nada do lado XML.
- **Quando é calculado**: só quando `VL_ITEM(XML) == VL_ITEM(SPED)` pra
  aquele par confirmado (mesma regra de "bater" usada no D2/D6 —
  `_valor_numerico(...).round(2)`), dentro de `_aplicar()` em
  `executar_matching()`. Se o total não bate, fica `NULL` — o fator só faz
  sentido quando o valor da transação já foi confirmado como igual; sem
  isso, dividir os unitários não teria base de comparação confiável.
- **D3 (N-para-1) nunca tem fator** (fica `NULL` de propósito): o `VL_ITEM`
  de cada item individual do grupo não é igual ao `VL_ITEM` da linha
  consolidada do SPED — só a SOMA do grupo bate — então a condição acima
  nunca é satisfeita item a item, e o fator não faria sentido numa
  consolidação de qualquer forma.
- **Extensão pro A1-A5**: o dicionário de aprendizado (só alimentado por
  D1/D2 confirmados, ver seção abaixo) agora também carrega o
  `FATOR_MULTIPLICADOR_SUGERIDO` calculado naquele match original, junto
  com `COD_ITEM_DECLARACAO`/`DESCR_ITEM_DECLARACAO` — quando um item
  `ND`/`NM` é recuperado por A1-A5, herda o mesmo fator histórico (mesma
  lógica de "sugestão baseada em padrão", não confirmação — é o mesmo
  espírito do resto da família A).
- **Interpretação**: fator = 1 = unidades compatíveis entre as duas bases.
  Fator = N (N inteiro, tipicamente a QTD de uma embalagem) = provável
  divergência de unidade — ex. real validado na base do geraldo: `QUERO
  MAIONESE SH 1780 24X200G` (XML, caixa de 24) batendo com `MAIONESE QUERO
  SACHE 200GR` (SPED, unidade) → fator 24,0; `DETERG LIMPAMIL LIMAO 6X2L`
  (XML, fardo de 6) batendo com `DETERGENTE LIMAO 6X2 LT` (SPED, unidade)
  → fator 6,0. Fator não-inteiro (ex.: 0,0167, 1,25) que sobra depois da
  normalização abaixo é sinal de algo mais sério que embalagem — pode ser
  um match coincidente de valor entre produtos de tamanho/composição
  diferente (ex. real: `CACHAÇA YPIÓCA PRATA 965ML` casando por valor com
  `CACHAÇA YPIÓCA PRATA 1L` — tamanhos diferentes, fator 0,0167 — candidato
  a revisão manual, não a embalagem).
- **Normalização de ruído de arredondamento** (`_normalizar_fator`,
  `TOLERANCIA_FATOR_ARREDONDAMENTO = 0,01` = 1%): implementado em
  2026-07-11 (mesmo dia), a partir de um caso real trazido pelo usuário —
  operação PB2, `CHV_NFE 25251047508411114402552000000087151002911336`,
  item `CARNE DE SOL CX MOLE KG` (produto vendido por peso): o SPED só
  grava `QTD` (`0,532`) e `VL_ITEM` (`28,14`, já arredondado a centavos),
  não o unitário direto — recalcular `VL_ITEM ÷ QTD` (52,8947) e comparar
  contra o unitário do XML (52,90) não fecha exatamente por causa do
  arredondamento em cascata, mesmo sem nenhuma divergência real de
  unidade. Isso gerava fatores tipo `1,0001`/`0,9999` em vez de `1,0`
  exato — ruído, não sinal. Como fatores de embalagem de verdade são
  sempre inteiros (caixa/fardo de N unidades), qualquer fator dentro de 1%
  do inteiro mais próximo é arredondado pra esse inteiro; fora dessa
  tolerância, mantém o valor calculado (é esse resíduo que sinaliza
  divergência real — ver item acima). Sincronizado nas 4 operações e
  re-persistido em produção — contagens de match idênticas, só o fator
  ficou limpo (em PB2, por exemplo, todos os fatores calculados na base
  ficaram inteiros depois da normalização).
- Coluna nova na BC3: `FATOR_MULTIPLICADOR_SUGERIDO` (não entra no
  `DICIONARIO DE CAMPOS.txt` — segue o mesmo precedente de `MATCH_TIPO`/
  `MATCH_SCORE`/`DESCR_ITEM_DECLARACAO`/`COD_ITEM_DECLARACAO`, campos
  sintéticos do Matching que já são autoexplicativos e não passam pelo
  dicionário geral).
- Sincronizado nas 4 operações e re-persistido em produção (geraldo, PB2,
  cometa) sem alterar nenhuma contagem de match — é um campo adicional,
  não muda critério nem ordem de execução.

## DT_E_S/DT_FIN propagados pra BC3 (alicerce do Estágio 4)

Implementado em 2026-07-12, junto com a hierarquia de `DATA_ELEITA`/
`ANO_ELEITO` do [Estágio 4](docs/estagios/04_cronologia_ano_eleito.md).

- **Mesmo tratamento de `COD_ITEM_DECLARACAO`/`DESCR_ITEM_DECLARACAO`**:
  sentinela `'nd'`/`'nm'` (item não declarado/sem match) nos defaults
  iniciais de `df_bc3`; propagados de `df_bc1` em `_aplicar()` (D1, D2, D3,
  D4, D5, D6); herdados via dicionário de aprendizado (A1-A5) — mesmo
  precedente do `FATOR_MULTIPLICADOR_SUGERIDO` (2026-07-11): o dicionário
  (construído só a partir de D1/D2 confirmados, ver seção "Dicionário de
  aprendizado" abaixo) agora também carrega `DT_E_S`/`DT_FIN` do match
  original.
- **Fonte**: `DT_E_S` (Campo 11 do Registro C100) e `DT_FIN` (Campo 05 do
  Registro 0000) — colunas da BC1 desde 2026-07-12 (ver seção "Datas na
  BC1" em `docs/estagios/01_extracao.md`).
- **Colunas novas na BC3**: `DT_E_S`, `DT_FIN` — mesmo precedente de
  `MATCH_TIPO`/`FATOR_MULTIPLICADOR_SUGERIDO`, não entram no
  `DICIONARIO DE CAMPOS.txt`.
- **Uso**: `loader._enriquecer_fluxo_real_com_bc3()` faz `LEFT JOIN` por
  `ID_UNICO` entre `xml_entradas_real`/`xml_saidas_real` (Estágio 3) e a
  `bc3`, trazendo essas duas colunas — base da hierarquia de
  `DATA_ELEITA` do Estágio 4. Não muda nenhum critério, limiar ou
  contagem de match do Matching em si.
- Sincronizado nas 4 operações; `bc3` re-persistida em produção (geraldo,
  PB2, cometa) — contagens de match idênticas às de antes desta mudança
  (16.408/4.519/9.625 itens, respectivamente).

## Prévia enriquecida de ET (`loader.consultar_nfe_entradas_bc3`)

Implementado em 2026-07-12, a pedido do usuário: expande a `bc3` (resultado
do Matching) de volta para o dataset bruto de ET, em vez de mostrar só as
~12 colunas reduzidas que a BC2/BC3 carregam.

- **Como funciona**: `LEFT JOIN` por `ID_UNICO` (chave sintética MD5
  determinística, ver `loader._gerar_id_unico()`, presente nos dois lados)
  entre `nfe_entradas` (tabela persistida, todas as colunas originais do
  XML — data de emissão, emitente, endereço etc. — filtrada a
  `PASTA_ORIGEM='ET'`) e `bc3` (só as colunas de enriquecimento do Matching:
  `COD_ITEM_DECLARACAO`, `DESCR_ITEM_DECLARACAO`, `MATCH_TIPO`,
  `MATCH_SCORE`, `FATOR_MULTIPLICADOR_SUGERIDO`). `LEFT JOIN` (não
  `INNER`): item de ET sem `bc3` gerada ainda, ou sem correspondência, não
  cai da lista — só fica com as colunas de enriquecimento em `NULL`.
- **Hierarquia dos 11 níveis preservada**: `MATCH_TIPO` vem direto da `bc3`
  sem nenhuma transformação/agregação — os mesmos rótulos D1-D6/A1-A5/ND/NM
  descritos nas seções acima aparecem tal qual na prévia.
- **Regra R07**: `COD_ITEM_DECLARACAO`/`DESCR_ITEM_DECLARACAO`/`MATCH_TIPO`
  forçados a string após a consulta — mas sem usar `_forcar_colunas_string`
  (que faz `astype(str)` cru): um `NULL` genuíno de `LEFT JOIN` viraria o
  literal `"None"` na tela; a conversão aqui preserva `NULL` como `NULL` e
  só converte os valores não nulos.
- **Painel**: `interface.render_bc3()` — o expander "Visualizar resultado
  do Matching (BC3)" passou a usar essa consulta na prévia (produto do
  fornecedor, XML, ao lado de produto da auditada, declaração). A
  exportação completa (CSV) continua servindo direto da tabela `bc3` (sem
  o join), sem mudança.
- **Pré-requisito de schema**: exige `ID_UNICO` em `nfe_entradas` — bases
  persistidas com uma versão de `loader.py` anterior à introdução do
  `ID_UNICO` não têm essa coluna. Nesse caso a função devolve vazio (loga
  aviso, não quebra a tela) e a interface mostra um aviso orientando a
  recarregar ("Carregar novamente" na Carga de XML) — nunca regera dado
  sozinha como diagnóstico silencioso. Caso real encontrado ao implementar:
  `PB2` estava nesse estado (schema antigo, 74 colunas sem `ID_UNICO`);
  `geraldo_2020_2024` e `cometa` já tinham o schema atual.

## Dicionário de aprendizado (A1/A2/A3/A4/A5)

- Construído **a cada execução do Matching**, exclusivamente a partir das
  linhas já confirmadas como `D1`/`D2` naquela mesma rodada — nunca a
  partir de A1/A2/A3/A4/A5 (evita encadeamento/loop de aprendizado
  sobre aprendizado).
- Em caso de chave repetida (mais de um par histórico para a mesma chave),
  prevalece a primeira ocorrência (`drop_duplicates`).
- Aplica-se tanto a itens `nd` (nota inteira não declarada) quanto `nm`
  (nota declarada, item sem match) — requisito explícito: o padrão de
  escrituração de um fornecedor/código pode ser reconhecido mesmo quando a
  nota específica nem consta na declaração.
- A1/A2 exigem o mesmo `ANO_EMISSAO` (dígitos 3-4 da `CHV_NFE`, campo
  "AA" da chave de acesso). A3/A4 existem porque essa exigência de ano
  pode deixar sem recuperação um fornecedor/código 100% reconhecido em um
  ano mas sem nenhuma âncora D1/D2 confirmada no ano da nota pendente —
  ver `memoria/2026-07-08.md` para o caso real que motivou o A3/A4.
- A5 relaxa mais um degrau: nem `ANO_EMISSAO` nem `CNPJ_EMITENTE` —
  só a descrição normalizada do XML. É o nível mais amplo/permissivo da
  família de aprendizado por descrição (risco maior de falso positivo entre
  fornecedores diferentes que descrevem o produto igual, por isso roda por
  último dentro dessa família, só sobre o que sobrou de todos os anteriores).

## Não Declarados e Não Matches (status antes de A1 em diante)

- `nd` (Não Declarado) — a `CHV_NFE` inteira não aparece na BC1.
- `nm` (Não Match) — a `CHV_NFE` existe na BC1, mas o item não passou nem no
  D1 nem no D2.

Itens `nd`/`nm` recuperados por qualquer um dos A1, A2, A3, A4, A5,
D3, D4, D5 ou D6 mudam de status para
`A1`/`A2`/`A3`/`A4`/`A5`/`D3`/`D4`/`D5`/`D6`
respectivamente. Os que não encontram correspondência em nenhum deles mantêm
`ND`/`NM`.

## Consistência de unicidade

Um item da BC1 (declaração) não pode ser "consumido" por dois matches de
TIPOS diferentes — vale entre D1, D2, D4, D5, D3 e D6 (os que
consomem uma linha específica da BC1). O A1/A2/A3/A4/A5 é só lookup
histórico e não consome linha da BC1, não entra nessa exclusão. Dentro do
D3 especificamente, uma mesma linha da BC1 é referenciada por vários itens
da BC2 ao mesmo tempo — é uma consolidação N-para-1 intencional (o único
tipo que faz isso), não uma exceção à regra: a exclusão continua valendo
entre D3 e os outros tipos (D1-D5, D6, todos 1-para-1).

## Correções de dados que afetam o Matching

- **Vírgula decimal do SPED**: `VL_ITEM` do lado SPED (BC1) pode vir com
  vírgula decimal (`"33,6"`), enquanto o XML (BC2) sempre usa ponto. A
  comparação numérica usa `matching._valor_numerico()` (substitui vírgula por
  ponto antes de `pd.to_numeric()`) em `_match_d2_por_nota()` e
  `_integridade_por_nota()` — sem isso, `pd.to_numeric()` descarta o valor
  como `NaN` e quebra silenciosamente o D2 e o D4.
- **Caracteres especiais na descrição**: `DESCR_ITEM`/`xprod` podem vir com
  pontuação divergente entre XML e SPED, ou entre duas notas do mesmo
  fornecedor, para o mesmo produto (`"REF 0065/01"` vs `"REF 0065-01"`,
  `"SH#400ML"` vs `"SH 400ML"`). `matching._normalizar_descricao()` (maiúsculas
  + remove tudo que não é letra/número/espaço, via `re.sub(r"[^\w\s]|_", " ",
  ...)`, colapsando espaços) é aplicada antes de qualquer comparação de
  descrição: na matriz de similaridade (D1/D2/D4/D5, `_matriz_similaridade`)
  e nas chaves exatas do dicionário de aprendizado por descrição (A2/A4/A5,
  `_chave_a2/_a4/_a5`). Sem isso, um caractere de
  pontuação sozinho derrubava a similaridade (D1/D2/D4/D5) ou quebrava a
  igualdade exata (A2/A4/A5), gerando `NM`/`ND` que na verdade eram o
  mesmo produto. Validado nas 3 operações: `NM` caiu 21,5%
  (geraldo), 70% (cometa) e 62% (PB2) — persistido em produção nas 3 bases.

## Histórico de mudanças

- 2026-07-07: implementados Tipo 3, Tipo 3.1, Tipo 4, Tipo 5 (nomes da época
  — ver renomeação de 2026-07-09 abaixo); correção da vírgula decimal do
  SPED; ajuste de `LIMIAR_TIPO4`/`LIMIAR_TIPO5` de 0,50 para 0,70.
- 2026-07-08: implementados Tipo 3.2 e Tipo 3.3 (fallback do Tipo 3/3.1 sem
  exigir o mesmo `ANO_EMISSAO`) — motivado por um caso real na operação PB2
  (CNPJ `11372084000615`, `COD_ITEM 1010005`: notas de 2023 ficavam `nd` por
  falta de âncora Tipo 1/2 confirmada em 2023, mesmo o fornecedor/código
  sendo 100% reconhecido em 2024). Operação `cometa` passou a integrar a
  sincronização de código a partir desta data.
- 2026-07-08 (mesmo dia): implementado Tipo 3.4 (fallback do Tipo 3.3,
  relaxando também o `CNPJ_EMITENTE` — chave só pela descrição exata do
  XML). Validado em memória na base real da PB2: recuperou mais 21 itens
  (sem perda — total de itens da BC3 permaneceu 4.519).
- 2026-07-09: discutida e descartada a inversão de ordem (Tipo 4/5 antes do
  aprendizado 3.x) — simulação real mostrou que só piora (rebaixa itens de
  evidência forte pra fraca e, em geraldo, perde 15 matches líquidos por
  causa da atribuição gulosa 1-para-1). Testado especificamente Tipo 3.4 vs
  Tipo 4/5 (a dupla mais discutível) — zero itens mudam de rótulo nas 3
  operações, então a ordem entre eles é irrelevante na prática hoje. Também
  avaliada e descartada a ideia de um "Tipo 6" (consolidação N-para-1 de
  linhas "SORTIDO" do SPED) — real e mensurável (~1.754 itens candidatos em
  geraldo), mas não implementada por decisão do usuário. Implementada
  `_normalizar_descricao()` (remove caracteres especiais antes de comparar
  descrição), aplicada em todos os Tipos que usam texto — ver seção
  "Correções de dados que afetam o Matching".
- 2026-07-09 (mesmo dia): renomeados todos os Tipos pra nomenclatura
  `tp_ia` (Tipo 1→D1, Tipo 2→D2, Tipo 3→A1, Tipo 3.1→A2, Tipo 3.2→A3,
  Tipo 3.3→A4, Tipo 3.4→A5, Tipo 4→D3, Tipo 5→D4) — ver
  `HIERARQUIA_TIPOS_TP_ALEXANDRE_vs_TP_IA.md`. Renomeados também as funções
  internas de `matching.py` (`_match_tipoN_...` → `_match_dN_.../_match_aN`),
  os limiares (`LIMIAR_TIPON` → `LIMIAR_DN`), os KPIs do painel
  (`interface.py`) e os totais lidos do banco (`loader.consultar_totais_bc3`).
  Critérios/limiares/ordem não mudaram, só os nomes — inclusive os valores
  gravados em `MATCH_TIPO`. Re-persistido nas 3 operações reais (bug real
  encontrado e corrigido no processo: `_BANCO_PATH` em `loader.py` não
  respeita `HUNTER_OPERACAO_DIR`, só `CONFIG_PATH` respeita — ver memória
  `feedback_hunter_operacao_dir_banco_path`).
- 2026-07-10: implementado D5 (consolidação N-para-1) — ver seção própria
  acima. Revisita a ideia de "Tipo 6" descartada em 2026-07-09, com um
  critério novo (cobertura por token ponderada por idf, não similaridade de
  string inteira) desenhado especificamente para evitar os falsos positivos
  de marca/modelo trocado observados num protótipo inicial mais simples
  (comparação de string inteira via `fuzz.token_set_ratio`): `HAVAIANA
  COLOR AZUL NAVAL` recuperando itens `H.BRASIL`, `OLEO CAPILAR FARMAX`
  recuperando itens `FIXED`, `TINTA MAXTON K.PRA.3.0` recuperando itens de
  tom `8.0`. Também descarta grupos ambíguos (mesmo item batendo soma exata
  em mais de uma linha do SPED) em vez de arriscar. Roda entre a família A e
  o D3/D4 (antes, não depois — D4 podia "roubar" a linha consolidada do
  SPED por coincidência de texto, 1-para-1, impedindo o D5 de formar o
  grupo certo depois). Validado na base real do geraldo: 100 grupos, 498
  itens recuperados (de 3.962 `NM`), zero colisão.
- 2026-07-10 (mesmo dia): implementado D6 (nota íntegra, só valor — último
  recurso de tudo) — ver seção própria acima. Cobre o caso em que a
  descrição do SPED é genérica ou errada (zero similaridade de texto com o
  XML), mas a nota fechar em contagem de itens e valor total (mesmo
  critério do D3) garante, por eliminação, que os itens que sobraram são o
  mesmo produto (caso real, `CHV_NFE 25230207555419000310550010001677321501275587`:
  `MOLHO BILLY JACK CHEDDAR 200G` no XML casando com `MOLHO TRÊS QUEIJOS
  STELLA D'ORO 240G` no SPED). Roda por último de tudo (depois do D4), por
  ser o critério com menos evidência. Sincronizado nas 4 operações
  (`geraldo_2020_2024`, `PB2`, `cometa`, `_MODELO_OPERACAO`).
- 2026-07-10 (mesmo dia): **D5 e D6 persistidos em produção** (BC3
  regenerada via `loader.persistir_bc3()`, rodando o python.exe portátil de
  cada operação) em `geraldo_2020_2024`, `PB2` e `cometa`. Resultado:
  geraldo — D5 = 498, D6 = 1.721 (de 16.408 itens; ND 477, NM 1.694); PB2 —
  D5 = 0, D6 = 15 (de 4.519 itens; ND 2.842, NM 2); cometa — D5 = 0, D6 = 29
  (de 9.625 itens; ND 1.251, NM 0). `_MODELO_OPERACAO` não tem base real,
  não se aplica.
- 2026-07-10 (mesmo dia): D6 ganhou desempate por similaridade de texto em
  caso de empate de valor — ver seção própria acima e
  `_atribuir_1_para_1_sem_empate`. Antes, qualquer empate de valor
  descartava o grupo inteiro (sem match); agora só descarta se a
  similaridade de desempate também empatar. Sincronizado nas 4 operações e
  re-persistido em produção: geraldo — D6 subiu de 1.721 para 2.029 (+308
  itens recuperados, NM caiu de 1.694 para 1.386); PB2 e cometa sem
  mudança (sem casos de empate de valor no D6 dessas bases).
- 2026-07-10 (mesmo dia): identificado, a partir de um caso real trazido
  pelo usuário (o próprio `CHV_NFE 25230207555419000310550010001677321501275587`
  usado como exemplo do D6), que a exigência de "nota íntegra" do D6 nunca
  vinha realmente confirmando aquele match — a nota inteira tem 54 itens no
  XML contra 40 no SPED (diferença de 14, causada por consolidações A1/A3
  em produtos sem nenhuma relação com o par MOLHO), reprovando a checagem
  de integridade da nota inteira. Primeira tentativa de correção
  (recalcular integridade só com os itens pendentes/disponíveis, em vez da
  nota inteira, aplicada também ao D3) não foi suficiente: como A1-A5 não
  consome BC1, linhas já usadas por aprendizado pra outros itens da mesma
  nota continuam contando como "disponíveis", poluindo a contagem/soma
  mesmo restrita aos pendentes. Decisão do usuário: manter a correção de
  escopo (pendente, não nota inteira) no D3, e **remover completamente a
  exigência de nota íntegra do D6** — a segurança do D6 passa a vir só da
  unicidade de valor + desempate por texto (já implementado). Sincronizado
  nas 4 operações e re-persistido em produção: geraldo — D6 subiu de 2.029
  para **2.477** (NM caiu de 1.386 para **938**; os 2 matches que o D3
  tinha antes passaram a ser pegos pelo D4, sem perda — D4 subiu de 47
  para 49, D3 foi a 0); PB2 e cometa sem mudança (D6 = 15 e 29).
- 2026-07-10 (mesmo dia): identificado, a partir de outro caso real trazido
  pelo usuário (`CHV_NFE 25250819447771000150550010000128321164733115`,
  operação PB2), que o desempate por texto do D6 descartava
  desnecessariamente casos de **duplicatas idênticas**: 2 itens `PAP HIG
  MILI F. DUPLA 30M C/4 FD C/24` no XML (mesma descrição, valor 5,99 cada)
  ficavam `NM` mesmo havendo exatamente 2 itens `PAP HIG CONFOFEX FS 30M
  NEUT L12 P11` no SPED (mesma descrição, mesmo valor) — o empate de
  similaridade era só de posição (as 2 ocorrências de cada lado são
  idênticas entre si), não de conteúdo, mas a regra descartava mesmo
  assim. Adicionada exceção em `_atribuir_1_para_1_sem_empate`: quando os
  pares empatados no topo correspondem todos ao mesmo par de descrições
  normalizadas, confirma em vez de descartar — ver seção própria acima.
  Sincronizado nas 4 operações e re-persistido em produção: geraldo — D6
  subiu de 2.477 para **2.525** (NM caiu de 938 para **890**); PB2 — D6
  subiu de 15 para **17** (NM caiu de 2 para **0**); cometa sem mudança
  (D6 = 29).
- 2026-07-11: implementado `FATOR_MULTIPLICADOR_SUGERIDO` (ver seção
  própria acima) — a pedido do usuário, sinaliza divergência de
  unidade/embalagem entre XML e SPED quando o `VL_ITEM` já bate. Passo 1:
  novo campo `VALOR_UNITARIO_DECLARACAO` na BC1 (`VL_ITEM/QTD`, derivado
  em `loader.py`, já que o SPED/C170 não traz unitário direto). Passo 2:
  fator calculado em `_aplicar()` pra D1/D2/D5/D3/D4/D6 (NULL quando
  `VL_ITEM` não bate, e sempre NULL em D5 por ser N-para-1) e propagado
  pro dicionário de aprendizado (A1-A5). Não muda nenhum critério nem
  contagem de match — só adiciona uma coluna informativa. Sincronizado
  nas 4 operações e re-persistido em produção (geraldo, PB2, cometa),
  contagens de match idênticas às de antes desta mudança.
- 2026-07-11 (mesmo dia): normalizado o `FATOR_MULTIPLICADOR_SUGERIDO` pro
  inteiro mais próximo quando a diferença é só ruído de arredondamento
  (`_normalizar_fator`, tolerância de 1%) — ver seção própria acima. Caso
  real que motivou (operação PB2, `CHV_NFE
  25251047508411114402552000000087151002911336`, item `CARNE DE SOL CX
  MOLE KG`): fator cru vinha `1,0001` em vez de `1,0` exato por causa do
  arredondamento em cascata de item vendido por peso (SPED só grava
  `QTD`/`VL_ITEM`, não o unitário). Sincronizado nas 4 operações e
  re-persistido em produção — contagens de match idênticas; em PB2, todos
  os fatores calculados ficaram inteiros após a normalização; em geraldo,
  sobraram 46 fatores não-inteiros (fora da tolerância de 1%), candidatos
  reais a revisão manual.
- 2026-07-11 (mesmo dia): **renumerada a família D pra refletir a ordem de
  execução real**, a pedido do usuário. Desde a criação do D5
  (consolidação, 2026-07-10), a numeração da família D não
  batia mais com a ordem em que os tipos rodam (D5 executava antes de
  D3/D4, apesar do número maior). Renomeação (nomes válidos até aqui →
  nomes novos, a partir de agora): `D5` (consolidação N-para-1) → `D3`;
  `D3` (integridade de nota) → `D4`; `D4` (último recurso, só
  similaridade) → `D5`. `D1`, `D2`, `D6` e toda a família `A` **não
  mudam**. Agora a ordem de execução da família D é literal: D1 → D2 → D3
  → D4 → D5 → D6 (com a família A rodando entre D2 e D3). Renomeadas
  também as funções internas de `matching.py`
  (`_match_d5_por_nota`→`_match_d3_por_nota`,
  `_match_d3_por_nota`→`_match_d4_por_nota`,
  `_match_d4_por_nota`→`_match_d5_por_nota`), os limiares
  (`LIMIAR_D5_TOKEN`/`LIMIAR_D5_COBERTURA`→`LIMIAR_D3_TOKEN`/`LIMIAR_D3_COBERTURA`,
  `LIMIAR_D3`→`LIMIAR_D4`, `LIMIAR_D4`→`LIMIAR_D5`), `_MIN_ITENS_D5`→
  `_MIN_ITENS_D3`, os KPIs do painel (`interface.py`) e os totais lidos do
  banco (`loader.consultar_totais_bc3`). Critérios, limiares e ordem de
  execução real não mudaram — só os nomes, inclusive os valores gravados
  em `MATCH_TIPO`. Re-persistido nas 3 operações reais (geraldo, PB2,
  cometa); contagens migraram corretamente pros novos rótulos (validado
  caso a caso contra os totais anteriores à renomeação).
- 2026-07-12: implementada a prévia enriquecida de ET
  (`loader.consultar_nfe_entradas_bc3`, ver seção própria acima) — expande
  a `bc3` de volta pro dataset bruto de ET (`nfe_entradas`) via `LEFT JOIN`
  por `ID_UNICO`, pra mostrar produto do fornecedor (XML) e produto da
  auditada (declaração) lado a lado no painel do Matching. Não muda nenhum
  critério, limiar ou contagem de match — só a forma de exibição da
  prévia. Sincronizado nas 4 operações. Achado no processo: `PB2` tinha
  `nfe_entradas` persistida com schema antigo (sem `ID_UNICO`) — tratado
  com degradação graciosa (função devolve vazio + log, interface avisa
  que precisa recarregar) em vez de quebrar a tela; não regerado
  automaticamente (decisão: nunca `persistir_*` como diagnóstico
  silencioso).
- 2026-07-12 (mesmo dia): propagados `DT_E_S`/`DT_FIN` pra `bc3` (ver seção
  própria acima) — alicerce da hierarquia de `DATA_ELEITA`/`ANO_ELEITO` do
  [Estágio 4](docs/estagios/04_cronologia_ano_eleito.md). Mesmo tratamento
  de `COD_ITEM_DECLARACAO`/`DESCR_ITEM_DECLARACAO` (defaults `'nd'`/`'nm'`,
  propagação em `_aplicar()`, herança via dicionário de aprendizado A1-A5).
  Não muda nenhum critério, limiar ou contagem de match. Sincronizado nas 4
  operações; `bc3` re-persistida em produção (geraldo, PB2, cometa) —
  contagens de match idênticas às de antes desta mudança.
