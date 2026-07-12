"""Motor de Matching (Etapa 1): cruza a BC2 (XML — itens de Emissão de
Terceiros) com a BC1 (SPED — sped_entradas_terceiros) para produzir a BC3
(resultado do cruzamento), sem depender de NUM_ITEM como chave — a ordem
sequencial dos itens no XML do fornecedor não necessariamente bate com a
ordem de escrituração no SPED do declarante.

Numeração dos Tipos (renomeada em 2026-07-09 — ver HIERARQUIA_TIPOS_TP_ALEXANDRE_vs_TP_IA.md):
duas famílias, em vez de uma sequência plana única. Família D = Direto,
sempre dentro da MESMA CHV_NFE. Família A = Aprendizado (dicionário
histórico), não exige mesma CHV_NFE — recupera inclusive itens cuja nota
inteira não está declarada ('nd'). Cada nível só tenta casar o que sobrou
do anterior; ordem de execução: D1 → D2 → A1 → A2 → A3 → A4 → A5 → D3 → D4 → D5 → D6.

  - D1: mesmo EAN/GTIN (COD_BARRA do SPED == cean do XML, comparados após
    normalização — ver _normalizar_gtin) **e** similaridade de descrição
    normalizada (xprod x DESCR_ITEM) > LIMIAR_D1 (0,90).
  - D2 (fallback): para os itens que não casaram no D1, mesmo Valor
    Total (VL_ITEM idêntico) **e** similaridade de descrição normalizada >
    LIMIAR_D2 (0,60).
  - A1 (aprendizado histórico): para os itens que sobraram como 'nd' ou
    'nm', busca num dicionário de aprendizado — construído só a partir dos
    matches já confirmados em D1/D2 — a combinação CNPJ_EMITENTE +
    COD_ITEM (XML) + ANO_EMISSAO (dígitos 3-4 da CHV_NFE). Não depende de
    similaridade de texto nem de a nota estar declarada: sinaliza como aquele
    fornecedor/código costuma ser escriturado, mesmo quando a nota nem consta
    na declaração ('nd'). Ver _match_a1.
  - A2 (aprendizado histórico por descrição): igual ao A1, mas
    troca COD_ITEM pela descrição exata normalizada do produto no XML
    (xprod) na chave de aprendizado — CNPJ_EMITENTE + DESCR_ITEM (XML,
    normalizada) + ANO_EMISSAO. Cobre fornecedores cujo código interno varia
    mas cuja descrição de texto é estável. Roda sobre o que sobrou 'nd'/'nm'
    após o A1. Ver _match_a2.
  - A3 (aprendizado histórico por código, sem exigir mesmo ano):
    fallback do A1 — mesma chave (CNPJ_EMITENTE + COD_ITEM), mas sem o
    ANO_EMISSAO. Cobre o caso de um fornecedor/código já 100% reconhecido em
    um ano (ex.: 2024, via D1/D2), mas sem nenhuma âncora confirmada no
    ano da nota pendente (ex.: 2023) — sem essa chave mais ampla, o A1
    nunca recupera essas notas, mesmo sendo claramente o mesmo produto. Roda
    sobre o que sobrou 'nd'/'nm' após o A2. Ver _match_a3.
  - A4 (aprendizado histórico por descrição, sem exigir mesmo ano):
    mesma ideia do A3, mas com a chave do A2 (CNPJ_EMITENTE +
    DESCR_ITEM normalizada), também sem ANO_EMISSAO. Roda sobre o que sobrou
    'nd'/'nm' após o A3. Ver _match_a4.
  - A5 (aprendizado histórico por descrição, sem exigir CNPJ nem
    ano): fallback do A4, relaxando também o CNPJ_EMITENTE — chave só
    a descrição normalizada do XML (DESCR_ITEM). Nível mais amplo/permissivo
    da família de aprendizado por descrição: cobre a mesma descrição de texto
    vinda de fornecedores diferentes. Roda sobre o que sobrou 'nd'/'nm'
    após o A4. Ver _match_a5.
  - D3 (consolidação N-para-1): para os itens que ainda sobraram 'nd'/'nm'
    após o A5, agrupa vários itens do XML numa única linha do SPED quando o
    SPED declara o produto de forma consolidada (ex.: "ESM LUDURANA BL
    SORTIDO 8ML" representando a soma de N tons vendidos separadamente no
    XML). Quem entra no grupo candidato é decidido por cobertura do radical
    da descrição do SPED no item do XML, por token e ponderada por raridade
    (idf) — ver _cobertura_radical — mas quem CONFIRMA o match é sempre a
    soma de VL_ITEM do grupo batendo exatamente com o VL_ITEM da linha do
    SPED (>= LIMIAR_D3_COBERTURA = 0,60 de cobertura, >= _MIN_ITENS_D3 = 2
    itens). Roda antes do D4/D5 de propósito (ver nota abaixo). Ver
    _match_d3_por_nota.
  - D4 (integridade de nota): para os itens que ainda sobraram 'nd'/'nm'
    após o D3, restringe às CHV_NFE onde os itens PENDENTES/DISPONÍVEIS
    (não a nota inteira original) são "íntegros" entre si — mesma contagem
    e mesmo somatório de VL_ITEM entre o que sobrou no lado XML (BC2) e o
    que sobrou no lado SPED (BC1), ver _integridade_por_nota — e casa, só
    dentro dessas notas, por similaridade de descrição normalizada >
    LIMIAR_D4 (0,70), 1-para-1. Ver _match_d4_por_nota.
  - D5 (último recurso): para os itens que ainda sobraram 'nd'/'nm' após
    o D4, casa dentro da mesma CHV_NFE só por similaridade de descrição
    normalizada > LIMIAR_D5 (0,70), 1-para-1, sem exigir GTIN, valor ou
    integridade de nota. Ver _match_d5_por_nota.
  - D6 (valor + desempate por texto — último recurso de tudo): para os
    itens que ainda sobraram 'nd'/'nm' após o D5, casa dentro da mesma
    CHV_NFE, item a item, por VALOR idêntico. Cobre o caso em que a
    descrição do SPED é genérica ou simplesmente errada (ex. real, CHV_NFE
    25230207555419000310550010001677321501275587: "MOLHO BILLY JACK
    CHEDDAR 200G" no XML casando com "MOLHO TRÊS QUEIJOS STELLA D'ORO 240G"
    no SPED, valor 16,32 — zero similaridade de texto). Não exige "nota
    íntegra" (diferente do D4): testado e descartado em 2026-07-10 — como
    A1-A5 não consome BC1, a integridade da nota (contagem/soma) ficava
    poluída por linhas já usadas por aprendizado pra outros itens da mesma
    nota, bloqueando pares isoladamente reconciliáveis (ver
    _match_d6_por_nota para o caso real). A segurança do D6 vem só da
    unicidade de valor: valor único dos dois lados dentro da nota confirma
    direto (score 1.0). Valor **empatado** (2+ itens com o mesmo valor em
    qualquer lado) não é descartado de cara: desempata por similaridade de
    descrição normalizada só entre os itens empatados naquele valor — o par
    de maior similaridade confirma (score = similaridade); só fica sem
    match se a maior similaridade também empatar entre 2+ pares (aí não há
    nenhum sinal, nem valor nem texto, pra decidir, e o código não
    adivinha). Ver _match_d6_por_nota e _atribuir_1_para_1_sem_empate.

Ordem avaliada e mantida (ver memoria/2026-07-09.md): mover D4/D5 pra antes
da família A piora o resultado (rebaixa itens de evidência forte — código
exato confirmado — pra evidência fraca — só similaridade — e em geraldo
chega a perder matches líquidos pela atribuição gulosa 1-para-1). D4/D5
vs A5 especificamente: testado e são mecanismos disjuntos na prática (zero
itens mudam de rótulo trocando a ordem entre eles). D3 roda antes do D4/D5
(não depois) porque D5, sendo 1-para-1 só por similaridade, pode "roubar"
por coincidência de texto a linha do SPED que na verdade é uma consolidação
— ex.: um caso real onde só 1 de 5 itens de uma família (variação de
fragrância) venceu sozinho no D5 contra a linha "SORTIDO" do SPED, deixando
os outros 4 permanentemente 'NM' sem chance de o D3 formar o grupo certo.
D6 roda por último de tudo (depois do D5, não antes) porque é o critério
com menos evidência (zero texto) — só entra sobre o que nenhum outro tipo,
que tem alguma evidência de texto/código, conseguiu casar.

Não Declarados e Não Matches (antes de A1/A2/A3/A4/A5/D3/D4/D5/D6):
  - 'nd' (Não Declarado) — a CHV_NFE inteira não aparece na BC1.
  - 'nm' (Não Match) — a CHV_NFE existe na BC1, mas o item não passou nem no
    D1 nem no D2.
Itens 'nd'/'nm' recuperados por A1, A2, A3, A4, A5, D3, D4, D5 ou D6 mudam
de status para 'A1'/'A2'/'A3'/'A4'/'A5'/'D3'/'D4'/'D5'/'D6'; os que não
encontram correspondência em nenhum deles mantêm 'ND'/'NM'.

Consistência de Unicidade — um item da BC1 (declaração) não pode ser
"consumido" por dois matches de TIPOS diferentes — vale entre D1, D2, D4,
D5, D3 e D6 (os que consomem uma linha específica da BC1). A família A é só
lookup histórico e não consome linha da BC1, não entra nessa exclusão.
Dentro do D3 especificamente, uma mesma linha da BC1 é referenciada por
vários itens do BC2 ao mesmo tempo — é uma consolidação N-para-1
intencional (o único tipo que faz isso), não uma exceção à regra: a
exclusão continua valendo entre D3 e os outros tipos (D1-D5, D6, todos
1-para-1).

ID_UNICO (já presente em BC1 e BC2) segue existindo só para rastreabilidade
interna — não é usado como chave de ligação. Regra Operacional R07: as
colunas de ligação (CHV_NFE, COD_ITEM, NUM_ITEM, CFOP) continuam com
dtype=str.

Implementação vetorizada (sem .iterrows()/.apply() linha a linha) para
escalar a operações com milhões de itens: agrupado por CHV_NFE, com a
matriz de similaridade calculada em lote por nota via scoring.matriz_similaridade()
(rapidfuzz.process.cdist, implementado em C) — o laço em Python passa a ser
por NOTA, não por ITEM. As máscaras de GTIN (D1) e Valor (D2) são
comparações vetorizadas (NumPy broadcasting) sobre essa mesma matriz, e a
atribuição gulosa (maior score primeiro, 1-para-1) usa np.argsort sobre os
pares que já passam nas duas condições de cada tipo.
"""
import math
import re
import sys
from pathlib import Path

_APP_DIR = Path(__file__).parent
if str(_APP_DIR) not in sys.path:
    sys.path.insert(0, str(_APP_DIR))

import numpy as np
import pandas as pd
from rapidfuzz import fuzz

import loader
import scoring

LIMIAR_D1 = 0.90  # mesmo GTIN/EAN + similaridade
LIMIAR_D2 = 0.60  # mesmo Valor Total + similaridade
LIMIAR_D4 = 0.70  # nota integra (mesma contagem/valor) + similaridade
LIMIAR_D5 = 0.70  # ultimo recurso: so similaridade, mesma chave
LIMIAR_D3_TOKEN = 0.82      # match individual por token do radical (tolera abreviacao: ESM~ESMALTE)
LIMIAR_D3_COBERTURA = 0.60  # fracao (ponderada por idf) do radical do SPED que precisa aparecer no item
_MIN_ITENS_D3 = 2            # abaixo disso ja seria D4/D5 normal (1-para-1)
TOLERANCIA_FATOR_ARREDONDAMENTO = 0.01  # 1% -- normaliza ruido de arredondamento do FATOR_MULTIPLICADOR_SUGERIDO pro inteiro mais proximo

_COL_DESCR_XML = "fatoitemnfe_infnfe_det_prod_xprod"
_COL_CNPJ_EMIT_XML = "fatonfe_infnfe_emit_cnpj"
_SEM_GTIN = {"", "SEM GTIN", "NAN", "NONE"}

_RE_CARACTERE_ESPECIAL = re.compile(r"[^\w\s]|_", re.UNICODE)


def _normalizar_descricao(serie: pd.Series) -> pd.Series:
    """Remove caracteres especiais (#, /, -, ., etc.) da descrição antes de
    comparar — o mesmo produto pode vir escrito com pontuação diferente entre
    XML e SPED, ou entre duas notas do mesmo fornecedor (ex.: "REF 0065/01"
    vs "REF 0065-01"), e o caractere sozinho não carrega informação sobre o
    produto em si. Mantém letras (com acento), números e espaços; colapsa
    espaços múltiplos resultantes da remoção."""
    limpo = serie.astype(str).str.upper().str.replace(_RE_CARACTERE_ESPECIAL, " ", regex=True)
    return limpo.str.split().str.join(" ")


def _normalizar_gtin(serie: pd.Series) -> np.ndarray:
    """Normaliza GTIN/EAN para comparação: remove zeros à esquerda, pois o
    SPED (registro 0200) grava o código padronizado em 14 posições (GTIN-14),
    enquanto o XML (campo cean) traz o valor cru, tipicamente em 13 dígitos
    (GTIN-13) — sem essa normalização, "7898034920103" (XML) nunca bate com
    "07898034920103" (SPED), mesmo sendo o mesmo produto. Um valor 100% zeros
    (placeholder de "sem GTIN" do SPED) vira string vazia após o lstrip, caindo
    naturalmente em _SEM_GTIN."""
    return serie.astype(str).str.strip().str.upper().str.lstrip("0").to_numpy()


def _matriz_similaridade(grupo_bc2: pd.DataFrame, grupo_bc1: pd.DataFrame) -> np.ndarray:
    descricoes_bc2 = _normalizar_descricao(grupo_bc2[_COL_DESCR_XML]).tolist()
    descricoes_bc1 = _normalizar_descricao(grupo_bc1["DESCR_ITEM"]).tolist()
    return scoring.matriz_similaridade(descricoes_bc2, descricoes_bc1)


def _atribuir_1_para_1(mask: np.ndarray, matriz_score: np.ndarray, idx_bc2_grupo, idx_bc1_grupo) -> dict:
    """Dado um booleano 'mask' (pares elegíveis) e a matriz de score, faz a
    atribuição gulosa (maior score primeiro) 1-para-1 dentro do grupo/nota.
    Devolve {indice_bc2: (indice_bc1, score)}."""
    candidatos = np.argwhere(mask)
    if candidatos.size == 0:
        return {}
    scores = matriz_score[candidatos[:, 0], candidatos[:, 1]]
    ordem = np.argsort(-scores)

    correspondencias = {}
    usados_i, usados_j = set(), set()
    for pos in ordem:
        i, j = candidatos[pos]
        if i in usados_i or j in usados_j:
            continue
        correspondencias[idx_bc2_grupo[i]] = (idx_bc1_grupo[j], float(scores[pos]))
        usados_i.add(i)
        usados_j.add(j)
    return correspondencias


def _match_d1_por_nota(df_bc2: pd.DataFrame, df_bc1: pd.DataFrame) -> dict:
    """D1: dentro da mesma CHV_NFE, mesmo EAN/GTIN E similaridade de
    descrição > LIMIAR_D1. Devolve {indice_bc2: (indice_bc1, score)}."""
    if df_bc2.empty or df_bc1.empty:
        return {}

    grupos_bc1 = {chv: grp for chv, grp in df_bc1.groupby("CHV_NFE")}
    correspondencias: dict = {}

    for chv, grupo_bc2 in df_bc2.groupby("CHV_NFE"):
        grupo_bc1 = grupos_bc1.get(chv)
        if grupo_bc1 is None or grupo_bc1.empty:
            continue

        matriz = _matriz_similaridade(grupo_bc2, grupo_bc1)

        gtin_bc2 = _normalizar_gtin(grupo_bc2["COD_BARRA"])
        gtin_bc1 = _normalizar_gtin(grupo_bc1["COD_BARRA"])
        gtin_valido_bc2 = ~np.isin(gtin_bc2, list(_SEM_GTIN))
        mask_gtin = gtin_valido_bc2[:, None] & (gtin_bc2[:, None] == gtin_bc1[None, :])

        mask_final = (matriz > LIMIAR_D1) & mask_gtin
        correspondencias.update(
            _atribuir_1_para_1(mask_final, matriz, grupo_bc2.index, grupo_bc1.index)
        )

    return correspondencias


def _valor_numerico(serie: pd.Series) -> pd.Series:
    """Converte VL_ITEM para numérico tolerando separador decimal por
    vírgula — o SPED/EFD grava valores não-inteiros como "33,60" (formato
    BR), enquanto o XML sempre usa ponto ("33.60"). Sem essa normalização,
    pd.to_numeric() descarta como NaN qualquer VL_ITEM do lado SPED com
    vírgula (bug real encontrado: ~82% das linhas da BC1 nesta operação),
    quebrando o casamento por Valor Total (D2) e a soma de integridade
    de nota (D4)."""
    return pd.to_numeric(
        serie.astype(str).str.strip().str.replace(",", ".", regex=False),
        errors="coerce",
    )


def _normalizar_fator(fator: np.ndarray) -> np.ndarray:
    """Normaliza o FATOR_MULTIPLICADOR_SUGERIDO pro inteiro mais próximo
    quando a diferença é só ruído de arredondamento (dentro de
    TOLERANCIA_FATOR_ARREDONDAMENTO, 1%) — sem isso, item vendido por peso
    (KG) gera fatores tipo 1,0001 ou 0,9999 em vez de 1,0 exato: o SPED só
    grava QTD (com poucas casas decimais, ex. "0,532") e VL_ITEM (já
    arredondado a centavos), então recalcular o unitário como
    VL_ITEM/QTD e comparar contra o unitário do XML não fecha
    exatamente, mesmo sem nenhuma divergência real de unidade/embalagem
    (caso real, operação PB2, CHV_NFE
    25251047508411114402552000000087151002911336: CARNE DE SOL CX MOLE KG,
    QTD 0,532, unitário XML 52,90, unitário SPED derivado 28,14/0,532 =
    52,8947 — fator cru 1,0001, normalizado pra 1,0). Fatores de embalagem
    de verdade (ex. caixa de 6, 12, 24 unidades) são sempre números
    inteiros, então arredondar só dentro da tolerância não confunde um
    fator genuíno com ruído — só limpa o ruído em torno de cada inteiro."""
    inteiro_mais_proximo = np.round(fator)
    tolerancia_absoluta = TOLERANCIA_FATOR_ARREDONDAMENTO * np.maximum(np.abs(inteiro_mais_proximo), 1.0)
    com_ruido = np.abs(fator - inteiro_mais_proximo) <= tolerancia_absoluta
    return np.where(com_ruido, inteiro_mais_proximo, fator)


def _match_d2_por_nota(df_bc2: pd.DataFrame, df_bc1: pd.DataFrame) -> dict:
    """D2 (fallback): dentro da mesma CHV_NFE, mesmo Valor Total (VL_ITEM
    idêntico) E similaridade de descrição > LIMIAR_D2. Chamado só com os
    itens que sobraram do D1. Devolve {indice_bc2: (indice_bc1, score)}."""
    if df_bc2.empty or df_bc1.empty:
        return {}

    grupos_bc1 = {chv: grp for chv, grp in df_bc1.groupby("CHV_NFE")}
    correspondencias: dict = {}

    for chv, grupo_bc2 in df_bc2.groupby("CHV_NFE"):
        grupo_bc1 = grupos_bc1.get(chv)
        if grupo_bc1 is None or grupo_bc1.empty:
            continue

        matriz = _matriz_similaridade(grupo_bc2, grupo_bc1)

        val_bc2 = _valor_numerico(grupo_bc2["VL_ITEM"]).round(2).to_numpy()
        val_bc1 = _valor_numerico(grupo_bc1["VL_ITEM"]).round(2).to_numpy()
        mask_valor = val_bc2[:, None] == val_bc1[None, :]

        mask_final = (matriz > LIMIAR_D2) & mask_valor
        correspondencias.update(
            _atribuir_1_para_1(mask_final, matriz, grupo_bc2.index, grupo_bc1.index)
        )

    return correspondencias


def _normalizar_codigo(serie: pd.Series) -> np.ndarray:
    """Normaliza código de item (COD_ITEM) para comparação: remove espaços e
    zeros à esquerda (Regra Operacional R07) — mesma lógica de
    _normalizar_gtin, aplicada ao código do item em vez do GTIN/EAN."""
    return serie.astype(str).str.strip().str.upper().str.lstrip("0").to_numpy()


def _extrair_ano_emissao(serie: pd.Series) -> np.ndarray:
    """Extrai o ano de emissão (2 dígitos) a partir dos dígitos 3-4 da
    CHV_NFE — chave de acesso da NF-e é UF(2)+AAMM(4)+CNPJ(14)+... , então as
    posições 3-4 (1-indexado) são o "AA" do campo AAMM."""
    return serie.astype(str).str.strip().str.slice(2, 4).to_numpy()


def _chave_a1(df: pd.DataFrame) -> pd.Series:
    """Monta a chave de vínculo do dicionário de aprendizado (A1):
    CNPJ_EMITENTE (XML) + COD_ITEM (XML, normalizado) + ANO_EMISSAO (dígitos
    3-4 da CHV_NFE)."""
    return pd.Series(
        df[_COL_CNPJ_EMIT_XML].astype(str).str.strip().to_numpy()
        + "|" + _normalizar_codigo(df["COD_ITEM"])
        + "|" + _extrair_ano_emissao(df["CHV_NFE"]),
        index=df.index,
    )


def _montar_dicionario_a1(df_bc3: pd.DataFrame) -> pd.DataFrame:
    """Constrói o dicionário de aprendizado exclusivamente a partir dos
    matches já confirmados de D1 e D2: mapeia CNPJ_EMITENTE +
    COD_ITEM (XML) + ANO_EMISSAO -> COD_ITEM_DECLARACAO/DESCR_ITEM_DECLARACAO
    já vinculados historicamente. Em caso de chaves repetidas (mesmo
    fornecedor/código/ano com mais de um par histórico), prevalece a
    primeira ocorrência."""
    confirmados = df_bc3[df_bc3["MATCH_TIPO"].isin(("D1", "D2"))]
    if confirmados.empty:
        return pd.DataFrame(columns=[
            "COD_ITEM_DECLARACAO", "DESCR_ITEM_DECLARACAO", "FATOR_MULTIPLICADOR_SUGERIDO",
            "DT_E_S", "DT_FIN",
        ])

    aprendizado = pd.DataFrame({
        "_CHAVE": _chave_a1(confirmados),
        "COD_ITEM_DECLARACAO": confirmados["COD_ITEM_DECLARACAO"].to_numpy(),
        "DESCR_ITEM_DECLARACAO": confirmados["DESCR_ITEM_DECLARACAO"].to_numpy(),
        "FATOR_MULTIPLICADOR_SUGERIDO": confirmados["FATOR_MULTIPLICADOR_SUGERIDO"].to_numpy(),
        "DT_E_S": confirmados["DT_E_S"].to_numpy(),
        "DT_FIN": confirmados["DT_FIN"].to_numpy(),
    })
    return aprendizado.drop_duplicates("_CHAVE").set_index("_CHAVE")


def _match_a1(df_bc3: pd.DataFrame) -> int:
    """A1 (aprendizado histórico): para itens 'ND' ou 'NM', busca no
    dicionário de aprendizado (montado só a partir de matches confirmados de
    D1/D2 — ver _montar_dicionario_a1) a combinação
    CNPJ_EMITENTE + COD_ITEM (XML) + ANO_EMISSAO. Encontrando, preenche
    COD_ITEM_DECLARACAO/DESCR_ITEM_DECLARACAO com o histórico e muda o status
    para 'A1' — inclusive para 'ND' (sinaliza ao auditor como o produto
    costuma ser escriturado quando a nota é declarada). Sem correspondência,
    mantém o status original ('ND'/'NM'). Devolve a quantidade recuperada.
    Muta df_bc3 in-place."""
    dicionario = _montar_dicionario_a1(df_bc3)
    if dicionario.empty:
        return 0

    alvo_mask = df_bc3["MATCH_TIPO"].isin(("ND", "NM"))
    if not alvo_mask.any():
        return 0

    chave_alvo = _chave_a1(df_bc3.loc[alvo_mask])
    cod_encontrado   = chave_alvo.map(dicionario["COD_ITEM_DECLARACAO"])
    descr_encontrado = chave_alvo.map(dicionario["DESCR_ITEM_DECLARACAO"])
    fator_encontrado = chave_alvo.map(dicionario["FATOR_MULTIPLICADOR_SUGERIDO"])
    dt_e_s_encontrado = chave_alvo.map(dicionario["DT_E_S"])
    dt_fin_encontrado = chave_alvo.map(dicionario["DT_FIN"])
    achou = cod_encontrado.notna()
    if not achou.any():
        return 0

    idx_achou = achou[achou].index
    df_bc3.loc[idx_achou, "MATCH_TIPO"]            = "A1"
    df_bc3.loc[idx_achou, "COD_ITEM_DECLARACAO"]   = cod_encontrado.loc[idx_achou].values
    df_bc3.loc[idx_achou, "DESCR_ITEM_DECLARACAO"] = descr_encontrado.loc[idx_achou].values
    df_bc3.loc[idx_achou, "FATOR_MULTIPLICADOR_SUGERIDO"] = fator_encontrado.loc[idx_achou].values
    df_bc3.loc[idx_achou, "DT_E_S"] = dt_e_s_encontrado.loc[idx_achou].values
    df_bc3.loc[idx_achou, "DT_FIN"] = dt_fin_encontrado.loc[idx_achou].values
    return int(achou.sum())


def _chave_a2(df: pd.DataFrame) -> pd.Series:
    """Monta a chave de vínculo do dicionário de aprendizado (A2):
    igual à do A1 (_chave_a1), mas troca COD_ITEM pela
    descrição exata do produto no XML (_COL_DESCR_XML, normalizada por
    _normalizar_descricao — maiúsculas, sem caracteres especiais — sem
    similaridade fuzzy) — CNPJ_EMITENTE (XML) + DESCR_ITEM (XML, exata) +
    ANO_EMISSAO (dígitos 3-4 da CHV_NFE)."""
    return pd.Series(
        df[_COL_CNPJ_EMIT_XML].astype(str).str.strip().to_numpy()
        + "|" + _normalizar_descricao(df[_COL_DESCR_XML]).to_numpy()
        + "|" + _extrair_ano_emissao(df["CHV_NFE"]),
        index=df.index,
    )


def _montar_dicionario_a2(df_bc3: pd.DataFrame) -> pd.DataFrame:
    """Constrói o dicionário de aprendizado do A2 exclusivamente a
    partir dos matches já confirmados de D1 e D2 (mesma base do
    A1 — ver _montar_dicionario_a1): mapeia CNPJ_EMITENTE +
    DESCR_ITEM (XML, exata) + ANO_EMISSAO -> COD_ITEM_DECLARACAO/
    DESCR_ITEM_DECLARACAO já vinculados historicamente. Em caso de chaves
    repetidas, prevalece a primeira ocorrência."""
    confirmados = df_bc3[df_bc3["MATCH_TIPO"].isin(("D1", "D2"))]
    if confirmados.empty:
        return pd.DataFrame(columns=[
            "COD_ITEM_DECLARACAO", "DESCR_ITEM_DECLARACAO", "FATOR_MULTIPLICADOR_SUGERIDO",
            "DT_E_S", "DT_FIN",
        ])

    aprendizado = pd.DataFrame({
        "_CHAVE": _chave_a2(confirmados),
        "COD_ITEM_DECLARACAO": confirmados["COD_ITEM_DECLARACAO"].to_numpy(),
        "DESCR_ITEM_DECLARACAO": confirmados["DESCR_ITEM_DECLARACAO"].to_numpy(),
        "FATOR_MULTIPLICADOR_SUGERIDO": confirmados["FATOR_MULTIPLICADOR_SUGERIDO"].to_numpy(),
        "DT_E_S": confirmados["DT_E_S"].to_numpy(),
        "DT_FIN": confirmados["DT_FIN"].to_numpy(),
    })
    return aprendizado.drop_duplicates("_CHAVE").set_index("_CHAVE")


def _match_a2(df_bc3: pd.DataFrame) -> int:
    """A2 (aprendizado histórico por descrição exata): igual ao A1
    (_match_a1), mas usa a descrição exata do produto no XML no lugar de
    COD_ITEM na chave de aprendizado — cobre fornecedores cujo código
    interno varia mas cuja descrição de texto é estável. Roda sobre o que
    sobrou 'ND'/'NM' após o A1. Sem correspondência, mantém o status
    original ('ND'/'NM'). Devolve a quantidade recuperada. Muta df_bc3
    in-place."""
    dicionario = _montar_dicionario_a2(df_bc3)
    if dicionario.empty:
        return 0

    alvo_mask = df_bc3["MATCH_TIPO"].isin(("ND", "NM"))
    if not alvo_mask.any():
        return 0

    chave_alvo = _chave_a2(df_bc3.loc[alvo_mask])
    cod_encontrado   = chave_alvo.map(dicionario["COD_ITEM_DECLARACAO"])
    descr_encontrado = chave_alvo.map(dicionario["DESCR_ITEM_DECLARACAO"])
    fator_encontrado = chave_alvo.map(dicionario["FATOR_MULTIPLICADOR_SUGERIDO"])
    dt_e_s_encontrado = chave_alvo.map(dicionario["DT_E_S"])
    dt_fin_encontrado = chave_alvo.map(dicionario["DT_FIN"])
    achou = cod_encontrado.notna()
    if not achou.any():
        return 0

    idx_achou = achou[achou].index
    df_bc3.loc[idx_achou, "MATCH_TIPO"]            = "A2"
    df_bc3.loc[idx_achou, "COD_ITEM_DECLARACAO"]   = cod_encontrado.loc[idx_achou].values
    df_bc3.loc[idx_achou, "DESCR_ITEM_DECLARACAO"] = descr_encontrado.loc[idx_achou].values
    df_bc3.loc[idx_achou, "FATOR_MULTIPLICADOR_SUGERIDO"] = fator_encontrado.loc[idx_achou].values
    df_bc3.loc[idx_achou, "DT_E_S"] = dt_e_s_encontrado.loc[idx_achou].values
    df_bc3.loc[idx_achou, "DT_FIN"] = dt_fin_encontrado.loc[idx_achou].values
    return int(achou.sum())


def _chave_a3(df: pd.DataFrame) -> pd.Series:
    """Monta a chave de vínculo do dicionário de aprendizado (A3):
    igual à do A1 (_chave_a1), mas sem o ANO_EMISSAO —
    CNPJ_EMITENTE + COD_ITEM (XML, normalizado). Fallback para quando o
    A1 não encontra âncora confirmada (D1/D2) no mesmo ano da
    nota pendente, mesmo com o fornecedor/código já reconhecido em outro
    ano."""
    return pd.Series(
        df[_COL_CNPJ_EMIT_XML].astype(str).str.strip().to_numpy()
        + "|" + _normalizar_codigo(df["COD_ITEM"]),
        index=df.index,
    )


def _montar_dicionario_a3(df_bc3: pd.DataFrame) -> pd.DataFrame:
    """Constrói o dicionário de aprendizado do A3 exclusivamente a
    partir dos matches já confirmados de D1 e D2 (mesma base do
    A1 — ver _montar_dicionario_a1): mapeia CNPJ_EMITENTE +
    COD_ITEM (XML) -> COD_ITEM_DECLARACAO/DESCR_ITEM_DECLARACAO já vinculados
    historicamente, sem distinguir por ano. Em caso de chaves repetidas
    (mesmo fornecedor/código em anos diferentes com pares históricos
    diferentes), prevalece a primeira ocorrência."""
    confirmados = df_bc3[df_bc3["MATCH_TIPO"].isin(("D1", "D2"))]
    if confirmados.empty:
        return pd.DataFrame(columns=[
            "COD_ITEM_DECLARACAO", "DESCR_ITEM_DECLARACAO", "FATOR_MULTIPLICADOR_SUGERIDO",
            "DT_E_S", "DT_FIN",
        ])

    aprendizado = pd.DataFrame({
        "_CHAVE": _chave_a3(confirmados),
        "COD_ITEM_DECLARACAO": confirmados["COD_ITEM_DECLARACAO"].to_numpy(),
        "DESCR_ITEM_DECLARACAO": confirmados["DESCR_ITEM_DECLARACAO"].to_numpy(),
        "FATOR_MULTIPLICADOR_SUGERIDO": confirmados["FATOR_MULTIPLICADOR_SUGERIDO"].to_numpy(),
        "DT_E_S": confirmados["DT_E_S"].to_numpy(),
        "DT_FIN": confirmados["DT_FIN"].to_numpy(),
    })
    return aprendizado.drop_duplicates("_CHAVE").set_index("_CHAVE")


def _match_a3(df_bc3: pd.DataFrame) -> int:
    """A3 (aprendizado histórico por código, sem exigir mesmo ano):
    fallback do A1 (_match_a1) para itens 'ND'/'NM' cujo CNPJ+código
    não tem nenhuma âncora confirmada (D1/D2) no próprio ano da
    nota, mas tem em outro ano — cobre fornecedor/código estável ano a ano.
    Roda sobre o que sobrou 'ND'/'NM' após o A2. Sem correspondência,
    mantém o status original. Devolve a quantidade recuperada. Muta df_bc3
    in-place."""
    dicionario = _montar_dicionario_a3(df_bc3)
    if dicionario.empty:
        return 0

    alvo_mask = df_bc3["MATCH_TIPO"].isin(("ND", "NM"))
    if not alvo_mask.any():
        return 0

    chave_alvo = _chave_a3(df_bc3.loc[alvo_mask])
    cod_encontrado   = chave_alvo.map(dicionario["COD_ITEM_DECLARACAO"])
    descr_encontrado = chave_alvo.map(dicionario["DESCR_ITEM_DECLARACAO"])
    fator_encontrado = chave_alvo.map(dicionario["FATOR_MULTIPLICADOR_SUGERIDO"])
    dt_e_s_encontrado = chave_alvo.map(dicionario["DT_E_S"])
    dt_fin_encontrado = chave_alvo.map(dicionario["DT_FIN"])
    achou = cod_encontrado.notna()
    if not achou.any():
        return 0

    idx_achou = achou[achou].index
    df_bc3.loc[idx_achou, "MATCH_TIPO"]            = "A3"
    df_bc3.loc[idx_achou, "COD_ITEM_DECLARACAO"]   = cod_encontrado.loc[idx_achou].values
    df_bc3.loc[idx_achou, "DESCR_ITEM_DECLARACAO"] = descr_encontrado.loc[idx_achou].values
    df_bc3.loc[idx_achou, "FATOR_MULTIPLICADOR_SUGERIDO"] = fator_encontrado.loc[idx_achou].values
    df_bc3.loc[idx_achou, "DT_E_S"] = dt_e_s_encontrado.loc[idx_achou].values
    df_bc3.loc[idx_achou, "DT_FIN"] = dt_fin_encontrado.loc[idx_achou].values
    return int(achou.sum())


def _chave_a4(df: pd.DataFrame) -> pd.Series:
    """Monta a chave de vínculo do dicionário de aprendizado (A4):
    igual à do A2 (_chave_a2), mas sem o ANO_EMISSAO —
    CNPJ_EMITENTE + DESCR_ITEM (XML, exata). Mesma ideia de fallback do
    A3, só que pela descrição exata em vez do código."""
    return pd.Series(
        df[_COL_CNPJ_EMIT_XML].astype(str).str.strip().to_numpy()
        + "|" + _normalizar_descricao(df[_COL_DESCR_XML]).to_numpy(),
        index=df.index,
    )


def _montar_dicionario_a4(df_bc3: pd.DataFrame) -> pd.DataFrame:
    """Constrói o dicionário de aprendizado do A4 exclusivamente a
    partir dos matches já confirmados de D1 e D2 (mesma base do
    A1 — ver _montar_dicionario_a1): mapeia CNPJ_EMITENTE +
    DESCR_ITEM (XML, exata) -> COD_ITEM_DECLARACAO/DESCR_ITEM_DECLARACAO já
    vinculados historicamente, sem distinguir por ano. Em caso de chaves
    repetidas, prevalece a primeira ocorrência."""
    confirmados = df_bc3[df_bc3["MATCH_TIPO"].isin(("D1", "D2"))]
    if confirmados.empty:
        return pd.DataFrame(columns=[
            "COD_ITEM_DECLARACAO", "DESCR_ITEM_DECLARACAO", "FATOR_MULTIPLICADOR_SUGERIDO",
            "DT_E_S", "DT_FIN",
        ])

    aprendizado = pd.DataFrame({
        "_CHAVE": _chave_a4(confirmados),
        "COD_ITEM_DECLARACAO": confirmados["COD_ITEM_DECLARACAO"].to_numpy(),
        "DESCR_ITEM_DECLARACAO": confirmados["DESCR_ITEM_DECLARACAO"].to_numpy(),
        "FATOR_MULTIPLICADOR_SUGERIDO": confirmados["FATOR_MULTIPLICADOR_SUGERIDO"].to_numpy(),
        "DT_E_S": confirmados["DT_E_S"].to_numpy(),
        "DT_FIN": confirmados["DT_FIN"].to_numpy(),
    })
    return aprendizado.drop_duplicates("_CHAVE").set_index("_CHAVE")


def _match_a4(df_bc3: pd.DataFrame) -> int:
    """A4 (aprendizado histórico por descrição, sem exigir mesmo ano):
    fallback do A2 (_match_a2), mesma lógica de relaxamento de
    ano do A3, mas usando a descrição exata do XML como chave. Roda
    sobre o que sobrou 'ND'/'NM' após o A3. Sem correspondência,
    mantém o status original. Devolve a quantidade recuperada. Muta df_bc3
    in-place."""
    dicionario = _montar_dicionario_a4(df_bc3)
    if dicionario.empty:
        return 0

    alvo_mask = df_bc3["MATCH_TIPO"].isin(("ND", "NM"))
    if not alvo_mask.any():
        return 0

    chave_alvo = _chave_a4(df_bc3.loc[alvo_mask])
    cod_encontrado   = chave_alvo.map(dicionario["COD_ITEM_DECLARACAO"])
    descr_encontrado = chave_alvo.map(dicionario["DESCR_ITEM_DECLARACAO"])
    fator_encontrado = chave_alvo.map(dicionario["FATOR_MULTIPLICADOR_SUGERIDO"])
    dt_e_s_encontrado = chave_alvo.map(dicionario["DT_E_S"])
    dt_fin_encontrado = chave_alvo.map(dicionario["DT_FIN"])
    achou = cod_encontrado.notna()
    if not achou.any():
        return 0

    idx_achou = achou[achou].index
    df_bc3.loc[idx_achou, "MATCH_TIPO"]            = "A4"
    df_bc3.loc[idx_achou, "COD_ITEM_DECLARACAO"]   = cod_encontrado.loc[idx_achou].values
    df_bc3.loc[idx_achou, "DESCR_ITEM_DECLARACAO"] = descr_encontrado.loc[idx_achou].values
    df_bc3.loc[idx_achou, "FATOR_MULTIPLICADOR_SUGERIDO"] = fator_encontrado.loc[idx_achou].values
    df_bc3.loc[idx_achou, "DT_E_S"] = dt_e_s_encontrado.loc[idx_achou].values
    df_bc3.loc[idx_achou, "DT_FIN"] = dt_fin_encontrado.loc[idx_achou].values
    return int(achou.sum())


def _chave_a5(df: pd.DataFrame) -> pd.Series:
    """Monta a chave de vínculo do dicionário de aprendizado (A5):
    igual à do A4 (_chave_a4), mas sem o CNPJ_EMITENTE —
    só a descrição exata do produto no XML (_COL_DESCR_XML, normalizada por
    _normalizar_descricao). Fallback mais amplo da família "descrição exata": cobre a
    mesma descrição de texto vinda de fornecedores diferentes, quando nem o
    CNPJ nem o ano têm âncora confirmada em comum."""
    return pd.Series(
        _normalizar_descricao(df[_COL_DESCR_XML]).to_numpy(),
        index=df.index,
    )


def _montar_dicionario_a5(df_bc3: pd.DataFrame) -> pd.DataFrame:
    """Constrói o dicionário de aprendizado do A5 exclusivamente a
    partir dos matches já confirmados de D1 e D2 (mesma base do
    A1 — ver _montar_dicionario_a1): mapeia DESCR_ITEM (XML,
    exata) -> COD_ITEM_DECLARACAO/DESCR_ITEM_DECLARACAO já vinculados
    historicamente, sem distinguir por CNPJ nem por ano. Em caso de chaves
    repetidas, prevalece a primeira ocorrência."""
    confirmados = df_bc3[df_bc3["MATCH_TIPO"].isin(("D1", "D2"))]
    if confirmados.empty:
        return pd.DataFrame(columns=[
            "COD_ITEM_DECLARACAO", "DESCR_ITEM_DECLARACAO", "FATOR_MULTIPLICADOR_SUGERIDO",
            "DT_E_S", "DT_FIN",
        ])

    aprendizado = pd.DataFrame({
        "_CHAVE": _chave_a5(confirmados),
        "COD_ITEM_DECLARACAO": confirmados["COD_ITEM_DECLARACAO"].to_numpy(),
        "DESCR_ITEM_DECLARACAO": confirmados["DESCR_ITEM_DECLARACAO"].to_numpy(),
        "FATOR_MULTIPLICADOR_SUGERIDO": confirmados["FATOR_MULTIPLICADOR_SUGERIDO"].to_numpy(),
        "DT_E_S": confirmados["DT_E_S"].to_numpy(),
        "DT_FIN": confirmados["DT_FIN"].to_numpy(),
    })
    return aprendizado.drop_duplicates("_CHAVE").set_index("_CHAVE")


def _match_a5(df_bc3: pd.DataFrame) -> int:
    """A5 (aprendizado histórico por descrição, sem exigir CNPJ nem
    ano): fallback do A4 (_match_a4), relaxando também o
    CNPJ_EMITENTE — usa só a descrição exata do XML como chave. É o nível
    mais amplo/permissivo da família de aprendizado por descrição, por isso
    roda por último dentro dela, sobre o que sobrou 'ND'/'NM' após o
    A4. Sem correspondência, mantém o status original. Devolve a
    quantidade recuperada. Muta df_bc3 in-place."""
    dicionario = _montar_dicionario_a5(df_bc3)
    if dicionario.empty:
        return 0

    alvo_mask = df_bc3["MATCH_TIPO"].isin(("ND", "NM"))
    if not alvo_mask.any():
        return 0

    chave_alvo = _chave_a5(df_bc3.loc[alvo_mask])
    cod_encontrado   = chave_alvo.map(dicionario["COD_ITEM_DECLARACAO"])
    descr_encontrado = chave_alvo.map(dicionario["DESCR_ITEM_DECLARACAO"])
    fator_encontrado = chave_alvo.map(dicionario["FATOR_MULTIPLICADOR_SUGERIDO"])
    dt_e_s_encontrado = chave_alvo.map(dicionario["DT_E_S"])
    dt_fin_encontrado = chave_alvo.map(dicionario["DT_FIN"])
    achou = cod_encontrado.notna()
    if not achou.any():
        return 0

    idx_achou = achou[achou].index
    df_bc3.loc[idx_achou, "MATCH_TIPO"]            = "A5"
    df_bc3.loc[idx_achou, "COD_ITEM_DECLARACAO"]   = cod_encontrado.loc[idx_achou].values
    df_bc3.loc[idx_achou, "DESCR_ITEM_DECLARACAO"] = descr_encontrado.loc[idx_achou].values
    df_bc3.loc[idx_achou, "FATOR_MULTIPLICADOR_SUGERIDO"] = fator_encontrado.loc[idx_achou].values
    df_bc3.loc[idx_achou, "DT_E_S"] = dt_e_s_encontrado.loc[idx_achou].values
    df_bc3.loc[idx_achou, "DT_FIN"] = dt_fin_encontrado.loc[idx_achou].values
    return int(achou.sum())


def _idf_lookup(df_bc1: pd.DataFrame) -> "tuple[dict, float]":
    """Calcula a frequência (document frequency) de cada token normalizado
    da descrição do SPED, na base inteira (não só a nota) — usado pelo D3
    para ponderar cada palavra do radical pela raridade dela: token genérico
    (OLEO, CREME, SORTIDO) pesa pouco; token raro (marca/linha do produto,
    ex.: LUDURANA, FARMAX) pesa muito. Devolve (mapa token -> idf, idf padrão
    para um token nunca visto — tratado como o mais raro possível)."""
    descricoes_norm = _normalizar_descricao(df_bc1["DESCR_ITEM"])
    n_total = len(descricoes_norm)
    doc_freq: dict = {}
    for descr in descricoes_norm:
        for tok in set(descr.split()):
            doc_freq[tok] = doc_freq.get(tok, 0) + 1
    idf_map = {tok: math.log((n_total + 1) / (freq + 1)) + 1.0 for tok, freq in doc_freq.items()}
    idf_padrao = math.log(n_total + 1) + 1.0
    return idf_map, idf_padrao


def _cobertura_radical(tokens_sped: list, tokens_item: list, idf_map: dict, idf_padrao: float) -> float:
    """Mede quanto do radical do SPED (tokens_sped) está presente no item do
    XML (tokens_item) — por token (fuzz.partial_ratio, tolera abreviação:
    ESM~ESMALTE), não pela string inteira, ponderado por idf (ver
    _idf_lookup). Ao ponderar por raridade, uma coincidência só de palavras
    genéricas (ex.: "OLEO CAPILAR ... 60ML" entre marcas diferentes, FARMAX x
    FIXED) não é suficiente para gerar cobertura alta — é preciso que a(s)
    palavra(s) rara(s)/distintiva(s) (a marca ou linha do produto) também
    batam."""
    if not tokens_sped or not tokens_item:
        return 0.0
    peso_total = sum(idf_map.get(t, idf_padrao) for t in tokens_sped)
    if peso_total == 0:
        return 0.0
    peso_batido = 0.0
    for t in tokens_sped:
        melhor = max((fuzz.partial_ratio(t, ti) / 100.0 for ti in tokens_item), default=0.0)
        if melhor >= LIMIAR_D3_TOKEN:
            peso_batido += idf_map.get(t, idf_padrao)
    return peso_batido / peso_total


def _match_d3_por_nota(df_bc2: pd.DataFrame, df_bc1: pd.DataFrame, idf_map: dict, idf_padrao: float) -> dict:
    """D3 (consolidação N-para-1): dentro da mesma CHV_NFE, agrupa vários
    itens do XML numa única linha do SPED quando o SPED declara o produto de
    forma consolidada (ex.: "ESM LUDURANA BL SORTIDO 8ML" representando a
    soma de N tons vendidos separadamente no XML). Para cada linha do SPED
    ainda disponível, mede — por token, ponderado por raridade (ver
    _cobertura_radical) — se o radical da descrição do SPED está presente em
    cada item pendente do XML da mesma nota; entra no grupo candidato quem
    tiver cobertura >= LIMIAR_D3_COBERTURA. Um grupo só confirma o match se
    tiver >= _MIN_ITENS_D3 itens E a soma de VL_ITEM do grupo bater
    exatamente com o VL_ITEM da linha do SPED (mesma lógica de confirmação
    numérica do D1/D2 — ver _valor_numerico) — o texto só decide QUEM entra
    no grupo candidato, quem CONFIRMA o match é sempre o valor. Se o mesmo
    item aparecer em mais de um grupo candidato (ambíguo — a soma bate em
    mais de uma linha do SPED, ex.: duas variações de tom/tinta com o mesmo
    valor total), descarta todos os grupos envolvidos em vez de arriscar uma
    atribuição errada — fica 'ND'/'NM' para revisão manual. Chamado só com
    os itens que sobraram 'nd'/'nm' após D1/D2/família A. Devolve
    {indice_bc2: (indice_bc1, cobertura)}."""
    if df_bc2.empty or df_bc1.empty:
        return {}

    grupos_bc1 = {chv: grp for chv, grp in df_bc1.groupby("CHV_NFE")}
    candidatos_grupo = []  # [(set(indices_bc2), indice_bc1, cobertura_media)]

    for chv, grupo_bc2 in df_bc2.groupby("CHV_NFE"):
        grupo_bc1 = grupos_bc1.get(chv)
        if grupo_bc1 is None or grupo_bc1.empty:
            continue

        tokens_bc2 = _normalizar_descricao(grupo_bc2[_COL_DESCR_XML]).str.split()
        val_bc2 = _valor_numerico(grupo_bc2["VL_ITEM"]).round(2)

        for idx_bc1, linha_bc1 in grupo_bc1.iterrows():
            tokens_sped = _normalizar_descricao(pd.Series([linha_bc1["DESCR_ITEM"]])).iloc[0].split()
            if not tokens_sped:
                continue
            coberturas = tokens_bc2.apply(lambda toks: _cobertura_radical(tokens_sped, toks, idf_map, idf_padrao))
            mask = coberturas >= LIMIAR_D3_COBERTURA
            if mask.sum() < _MIN_ITENS_D3:
                continue
            valor_sped = _valor_numerico(pd.Series([linha_bc1["VL_ITEM"]])).round(2).iloc[0]
            if val_bc2[mask].sum().round(2) != valor_sped:
                continue
            idx_bc2_grupo = set(grupo_bc2.index[mask])
            candidatos_grupo.append((idx_bc2_grupo, idx_bc1, float(coberturas[mask].mean())))

    contagem_item: dict = {}
    for idxs, _, _ in candidatos_grupo:
        for i in idxs:
            contagem_item[i] = contagem_item.get(i, 0) + 1
    itens_ambiguos = {i for i, n in contagem_item.items() if n > 1}

    correspondencias: dict = {}
    for idxs, idx_bc1, cobertura_media in candidatos_grupo:
        if idxs & itens_ambiguos:
            continue
        for i in idxs:
            correspondencias[i] = (idx_bc1, cobertura_media)
    return correspondencias


def _integridade_por_nota(df_bc2: pd.DataFrame, df_bc1: pd.DataFrame) -> set:
    """Calcula, por CHV_NFE, a contagem de itens e o somatório de VL_ITEM em
    cada lado (XML/BC2 e SPED/BC1) e devolve o conjunto de CHV_NFE onde
    ambos batem exatamente ("nota íntegra") — pré-requisito do D4 e do D6.

    Recebe só os itens PENDENTES (BC2) e DISPONÍVEIS/não consumidos (BC1)
    no momento em que é chamada (D4 e D6 recalculam a cada um, com o
    recorte da vez) — não a nota inteira original. Motivo: partes da mesma
    nota podem já ter sido resolvidas antes por mecanismos N-para-1 (A1-A5,
    que não consomem BC1; D3, que consolida N itens do XML numa só linha
    do SPED). Isso muda a contagem "bruta" de itens da nota sem que haja
    divergência real no que ainda falta casar — calcular a integridade
    sobre a nota inteira bloquearia D4/D6 numa nota onde só o RESTANTE
    pendente (não a nota completa) é que precisa estar íntegro. Caso real
    que motivou a mudança (2026-07-10): CHV_NFE
    25230207555419000310550010001677321501275587 tem 54 itens no XML x 40
    no SPED (nota inteira) — diferença de 14 causada por consolidações
    A1-A5 em produtos sem nenhuma relação com o par pendente (`MOLHO BILLY
    JACK CHEDDAR 200G` x `MOLHO TRÊS QUEIJOS STELLA D'ORO 240G`, ambos
    16,32); usando a nota inteira, esse par nunca era nem tentado pelo D6,
    apesar de ser, isoladamente, valor único dos dois lados."""
    contagem_bc2 = df_bc2.groupby("CHV_NFE").size()
    contagem_bc1 = df_bc1.groupby("CHV_NFE").size()

    valor_bc2 = _valor_numerico(df_bc2["VL_ITEM"])
    valor_bc1 = _valor_numerico(df_bc1["VL_ITEM"])
    soma_bc2 = valor_bc2.groupby(df_bc2["CHV_NFE"]).sum().round(2)
    soma_bc1 = valor_bc1.groupby(df_bc1["CHV_NFE"]).sum().round(2)

    chaves_comuns = contagem_bc2.index.intersection(contagem_bc1.index)
    mesma_contagem = contagem_bc2.loc[chaves_comuns].to_numpy() == contagem_bc1.loc[chaves_comuns].to_numpy()
    mesmo_valor    = soma_bc2.loc[chaves_comuns].to_numpy() == soma_bc1.loc[chaves_comuns].to_numpy()

    return set(chaves_comuns[mesma_contagem & mesmo_valor])


def _match_d4_por_nota(df_bc2: pd.DataFrame, df_bc1: pd.DataFrame, chaves_integras: set) -> dict:
    """D4 (integridade de nota): restringe às CHV_NFE "íntegras" (mesma
    contagem de itens e mesmo somatório de VL_ITEM entre XML e SPED — ver
    _integridade_por_nota) e casa, dentro delas, só por similaridade de
    descrição > LIMIAR_D4, 1-para-1 (_atribuir_1_para_1). Chamado só com
    os itens que sobraram 'nd'/'nm' após D1/D2/família A. Devolve
    {indice_bc2: (indice_bc1, score)}."""
    if df_bc2.empty or df_bc1.empty or not chaves_integras:
        return {}

    grupos_bc1 = {chv: grp for chv, grp in df_bc1.groupby("CHV_NFE")}
    correspondencias: dict = {}

    for chv, grupo_bc2 in df_bc2.groupby("CHV_NFE"):
        if chv not in chaves_integras:
            continue
        grupo_bc1 = grupos_bc1.get(chv)
        if grupo_bc1 is None or grupo_bc1.empty:
            continue

        matriz = _matriz_similaridade(grupo_bc2, grupo_bc1)
        mask_final = matriz > LIMIAR_D4
        correspondencias.update(
            _atribuir_1_para_1(mask_final, matriz, grupo_bc2.index, grupo_bc1.index)
        )

    return correspondencias


def _match_d5_por_nota(df_bc2: pd.DataFrame, df_bc1: pd.DataFrame) -> dict:
    """D5 (último recurso): dentro da mesma CHV_NFE, casa só por
    similaridade de descrição > LIMIAR_D5, 1-para-1 (_atribuir_1_para_1)
    — sem exigir GTIN, valor ou integridade de nota. Chamado só com os itens
    que sobraram 'nd'/'nm' após D1/D2/família A/D4. Devolve
    {indice_bc2: (indice_bc1, score)}."""
    if df_bc2.empty or df_bc1.empty:
        return {}

    grupos_bc1 = {chv: grp for chv, grp in df_bc1.groupby("CHV_NFE")}
    correspondencias: dict = {}

    for chv, grupo_bc2 in df_bc2.groupby("CHV_NFE"):
        grupo_bc1 = grupos_bc1.get(chv)
        if grupo_bc1 is None or grupo_bc1.empty:
            continue

        matriz = _matriz_similaridade(grupo_bc2, grupo_bc1)
        mask_final = matriz > LIMIAR_D5
        correspondencias.update(
            _atribuir_1_para_1(mask_final, matriz, grupo_bc2.index, grupo_bc1.index)
        )

    return correspondencias


def _atribuir_1_para_1_sem_empate(
    matriz_score: np.ndarray,
    idx_bc2_grupo: list,
    idx_bc1_grupo: list,
    descr_bc2_grupo: list,
    descr_bc1_grupo: list,
) -> dict:
    """Atribuição gulosa 1-para-1 por maior score (mesma ideia de
    _atribuir_1_para_1), mas usada quando o score é o desempate de uma
    ambiguidade (ver _match_d6_por_nota): a cada rodada, só confirma o par
    de maior score se ele for **único** entre os pares ainda disponíveis —
    se o maior score estiver empatado entre 2+ pares, para imediatamente e
    deixa os pares restantes sem match (ambiguidade não resolvida por
    desempate não é resolvida por sorteio/ordem arbitrária).

    Exceção: se os pares empatados no topo forem todos o MESMO par de
    descrições normalizadas (ex.: 2 linhas idênticas do XML — mesma
    descrição, mesmo valor — pra 2 linhas idênticas do SPED), o empate é só
    de posição/índice, não de conteúdo — não há ambiguidade real sobre QUAL
    produto é (as duas linhas de cada lado são, pro efeito de descrição,
    intercambiáveis); nesse caso confirma mesmo assim, em vez de descartar
    (caso real, CHV_NFE 25250819447771000150550010000128321164733115,
    operação PB2: 2 itens `PAP HIG MILI F. DUPLA 30M C/4 FD C/24` no XML,
    valor 5,99 cada, batendo com 2 itens `PAP HIG CONFOFEX FS 30M NEUT L12
    P11` no SPED, mesmo valor — descrição idêntica nos dois lados, sem
    nenhuma outra pista pra distinguir uma ocorrência da outra, mas também
    sem motivo real pra descartar). Devolve {indice_bc2: (indice_bc1,
    score)}."""
    linhas, colunas = matriz_score.shape
    restantes = {(i, j) for i in range(linhas) for j in range(colunas)}
    correspondencias: dict = {}

    while restantes:
        melhor = max(matriz_score[i, j] for i, j in restantes)
        empatados = [(i, j) for i, j in restantes if matriz_score[i, j] == melhor]
        if len(empatados) != 1:
            pares_conteudo = {(descr_bc2_grupo[i], descr_bc1_grupo[j]) for i, j in empatados}
            if len(pares_conteudo) != 1:
                break
        i, j = empatados[0]
        correspondencias[idx_bc2_grupo[i]] = (idx_bc1_grupo[j], float(melhor))
        restantes = {(a, b) for (a, b) in restantes if a != i and b != j}

    return correspondencias


def _match_d6_por_nota(df_bc2: pd.DataFrame, df_bc1: pd.DataFrame) -> dict:
    """D6 (só valor, com desempate por texto — último recurso): dentro da
    mesma CHV_NFE, casa item a item por VALOR idêntico (_valor_numerico) —
    ao contrário de D1-D3, que sempre exigem algum sinal de texto junto com
    o valor/código, o D6 casa primariamente só por valor. Existe pra cobrir
    o caso em que a descrição do SPED é genérica ou simplesmente errada (o
    item declarado não tem nada a ver textualmente com o item do XML, ex.:
    "MOLHO BILLY JACK CHEDDAR 200G" no XML casando com "MOLHO TRÊS QUEIJOS
    STELLA D'ORO 240G" no SPED, CHV_NFE
    25230207555419000310550010001677321501275587).

    Não exige mais "nota íntegra" (contagem/soma da nota inteira batendo) —
    removido em 2026-07-10: A1-A5 não consomem BC1 (múltiplos itens do XML
    podem apontar pro mesmo código/descrição histórica), então uma linha da
    BC1 já "usada" por A1-A5 pra OUTRO item da mesma nota continua contando
    como "disponível" no cálculo de integridade, inflando a contagem/soma do
    lado SPED e derrubando a checagem mesmo quando o par pendente em
    questão é, isoladamente, perfeitamente reconciliável (caso real: nessa
    mesma CHV_NFE acima, a nota inteira nunca batia em contagem — 54 itens
    no XML x 40 no SPED, por causa de consolidações A1/A3 em produtos sem
    nenhuma relação com o MOLHO — e isso bloqueava o D6 de tentar o par
    MOLHO, mesmo ele tendo valor único nos dois lados). A segurança do D6
    passa a vir só da unicidade de valor (e do desempate por texto quando
    empata) — ver abaixo.

    Quando o valor é único dos dois lados dentro da nota (exatamente 1 item
    do XML e 1 do SPED com aquele valor), confirma direto, score 1.0. Quando
    há **empate de valor** (2+ itens do XML e/ou do SPED com o mesmo valor
    dentro da nota), o valor sozinho não decide — desempata por
    similaridade de descrição normalizada (_matriz_similaridade, mesmo
    cálculo do D1-D3) entre só os itens empatados naquele valor: o par de
    maior similaridade é confirmado (score = similaridade), e assim
    sucessivamente para os itens remanescentes do grupo. Só fica sem match
    (ambos os lados) se a maior similaridade também empatar entre 2+ pares
    candidatos — aí não há nenhum sinal (nem valor, nem texto) pra decidir
    qual par é o certo, e o código não tenta adivinhar (ver
    _atribuir_1_para_1_sem_empate).

    Chamado só com os itens que sobraram 'nd'/'nm' após D1/D2/família
    A/D3/D4/D5 — roda por último de propósito: é o critério com menos
    evidência (o valor pode não vir acompanhado de texto), só entra depois
    que todos os outros, que têm alguma evidência de texto/código, já
    tiveram a chance de casar primeiro. Devolve {indice_bc2: (indice_bc1,
    score)}."""
    if df_bc2.empty or df_bc1.empty:
        return {}

    grupos_bc1 = {chv: grp for chv, grp in df_bc1.groupby("CHV_NFE")}
    correspondencias: dict = {}

    for chv, grupo_bc2 in df_bc2.groupby("CHV_NFE"):
        grupo_bc1 = grupos_bc1.get(chv)
        if grupo_bc1 is None or grupo_bc1.empty:
            continue

        val_bc2 = _valor_numerico(grupo_bc2["VL_ITEM"]).round(2)
        val_bc1 = _valor_numerico(grupo_bc1["VL_ITEM"]).round(2)

        for valor in pd.unique(val_bc2.dropna()):
            idx_bc2_valor = val_bc2.index[val_bc2 == valor]
            idx_bc1_valor = val_bc1.index[val_bc1 == valor]
            if idx_bc1_valor.empty:
                continue

            if len(idx_bc2_valor) == 1 and len(idx_bc1_valor) == 1:
                correspondencias[idx_bc2_valor[0]] = (idx_bc1_valor[0], 1.0)
                continue

            # empate de valor (produto) em pelo menos um dos lados: desempata
            # por similaridade de descricao, so entre os itens empatados
            # nesse valor especifico — ver _atribuir_1_para_1_sem_empate.
            sub_bc2 = grupo_bc2.loc[idx_bc2_valor]
            sub_bc1 = grupo_bc1.loc[idx_bc1_valor]
            matriz = _matriz_similaridade(sub_bc2, sub_bc1)
            descr_bc2_norm = _normalizar_descricao(sub_bc2[_COL_DESCR_XML]).tolist()
            descr_bc1_norm = _normalizar_descricao(sub_bc1["DESCR_ITEM"]).tolist()
            correspondencias.update(
                _atribuir_1_para_1_sem_empate(
                    matriz, list(idx_bc2_valor), list(idx_bc1_valor), descr_bc2_norm, descr_bc1_norm
                )
            )

    return correspondencias


def executar_matching() -> "tuple[pd.DataFrame, dict]":
    """Executa o cruzamento BC2 (XML, ET) x BC1 (SPED) em onze níveis (D1,
    D2, A1-A5, D3, D4, D5, D6) e devolve a BC3: uma linha por item da BC2, com
    DESCR_ITEM_DECLARACAO/COD_ITEM_DECLARACAO/DT_E_S/DT_FIN trazidos do BC1
    quando houver correspondência, 'nd' quando a CHV_NFE não estiver
    declarada, ou 'nm' quando a CHV_NFE existir mas o item não passar em
    nenhum tipo. DT_E_S/DT_FIN (alicerce do Estágio 4 — hierarquia de
    DATA_ELEITA, ver docs/estagios/) seguem exatamente o mesmo tratamento de
    COD_ITEM_DECLARACAO/DESCR_ITEM_DECLARACAO: propagados em _aplicar() para
    D1-D6 e herdados via dicionário de aprendizado para A1-A5 (mesmo padrão
    do FATOR_MULTIPLICADOR_SUGERIDO, ver REGRAS_MATCHING.md)."""
    df_bc2, meta_bc2 = loader.montar_bc2()
    df_bc1, meta_bc1 = loader.load_declaracao_entradas_terceiros()

    erros = list(meta_bc2.get("erros", [])) + list(meta_bc1.get("erros", []))
    if df_bc2.empty or df_bc1.empty:
        meta = {"origem_dados": "BC3", "erros": erros, "total_linhas": 0}
        return pd.DataFrame(), meta

    df_bc2 = df_bc2.reset_index(drop=True)
    df_bc1 = df_bc1.reset_index(drop=True)

    # ── D1: GTIN + similaridade > 0,90 ──────────────────────────────────────
    match_d1 = _match_d1_por_nota(df_bc2, df_bc1)
    indices_bc1_usados = {v[0] for v in match_d1.values()}

    pendentes_idx = df_bc2.index.difference(pd.Index(match_d1.keys()))
    df_bc2_pend = df_bc2.loc[pendentes_idx]
    df_bc1_disp = df_bc1.loc[~df_bc1.index.isin(indices_bc1_usados)]

    # ── D2 (fallback): Valor + similaridade > 0,60 ──────────────────────────
    match_d2 = _match_d2_por_nota(df_bc2_pend, df_bc1_disp)
    indices_bc1_usados |= {v[0] for v in match_d2.values()}

    # ── Monta a BC3 vetorizadamente (sem laço por linha) ────────────────────
    df_bc3 = df_bc2.copy()
    chaves_declaradas = set(df_bc1["CHV_NFE"])
    nao_declarado = ~df_bc3["CHV_NFE"].isin(chaves_declaradas)

    df_bc3["MATCH_TIPO"] = np.where(nao_declarado, "ND", "NM")
    df_bc3["MATCH_SCORE"] = 0.0
    df_bc3["DESCR_ITEM_DECLARACAO"] = np.where(nao_declarado, "nd", "nm")
    df_bc3["COD_ITEM_DECLARACAO"]   = np.where(nao_declarado, "nd", "nm")
    df_bc3["DT_E_S"] = np.where(nao_declarado, "nd", "nm")
    df_bc3["DT_FIN"] = np.where(nao_declarado, "nd", "nm")
    df_bc3["FATOR_MULTIPLICADOR_SUGERIDO"] = np.nan

    def _aplicar(mapa_idx_bc1: dict, tipo: str):
        if not mapa_idx_bc1:
            return
        idxs_bc2 = list(mapa_idx_bc1.keys())
        idxs_bc1 = [v[0] for v in mapa_idx_bc1.values()]
        scores   = [v[1] for v in mapa_idx_bc1.values()]
        df_bc3.loc[idxs_bc2, "MATCH_TIPO"]  = tipo
        df_bc3.loc[idxs_bc2, "MATCH_SCORE"] = [round(s, 4) for s in scores]
        df_bc3.loc[idxs_bc2, "DESCR_ITEM_DECLARACAO"] = df_bc1.loc[idxs_bc1, "DESCR_ITEM"].values
        df_bc3.loc[idxs_bc2, "COD_ITEM_DECLARACAO"]   = df_bc1.loc[idxs_bc1, "COD_ITEM"].values
        df_bc3.loc[idxs_bc2, "DT_E_S"] = df_bc1.loc[idxs_bc1, "DT_E_S"].values
        df_bc3.loc[idxs_bc2, "DT_FIN"] = df_bc1.loc[idxs_bc1, "DT_FIN"].values

        # Fator multiplicador sugerido: só quando o VL_ITEM (valor total da
        # linha) bate entre XML e SPED pra aquele par — se bate, a diferença
        # entre os unitários (_VALOR_UNIT_ORIGINAL do XML dividido pelo
        # VALOR_UNITARIO_DECLARACAO derivado na BC1, ver loader.py) sinaliza
        # possível divergência de unidade/embalagem entre as duas bases (ex.:
        # XML fatura por caixa, SPED escritura por unidade — o total pode
        # bater mesmo assim, mas o unitário difere por um fator múltiplo).
        # D3 (N-para-1) nunca bate aqui, de propósito: o VL_ITEM de cada item
        # individual do grupo não é igual ao VL_ITEM da linha consolidada do
        # SPED (só a SOMA do grupo bate) — fica NaN, corretamente, já que o
        # fator não faz sentido item a item numa consolidação.
        val_xml = _valor_numerico(df_bc3.loc[idxs_bc2, "VL_ITEM"]).round(2).to_numpy()
        val_decl = _valor_numerico(df_bc1.loc[idxs_bc1, "VL_ITEM"]).round(2).to_numpy()
        bate = val_xml == val_decl
        if bate.any():
            unit_xml = _valor_numerico(df_bc3.loc[idxs_bc2, "_VALOR_UNIT_ORIGINAL"]).to_numpy()
            unit_decl = df_bc1.loc[idxs_bc1, "VALOR_UNITARIO_DECLARACAO"].to_numpy(dtype=float)
            with np.errstate(divide="ignore", invalid="ignore"):
                fator = np.where(bate & (unit_decl != 0) & ~np.isnan(unit_decl), unit_xml / unit_decl, np.nan)
                fator = _normalizar_fator(fator)
            df_bc3.loc[idxs_bc2, "FATOR_MULTIPLICADOR_SUGERIDO"] = np.round(fator, 4)

    _aplicar(match_d1, "D1")
    _aplicar(match_d2, "D2")

    # ── A1: aprendizado histórico sobre o que sobrou como ND/NM ─────────────
    _match_a1(df_bc3)

    # ── A2: mesmo aprendizado, por descrição exata (não COD_ITEM) ───────────
    _match_a2(df_bc3)

    # ── A3: mesmo aprendizado do A1, sem exigir o mesmo ano ──────────────────
    _match_a3(df_bc3)

    # ── A4: mesmo aprendizado do A2, sem exigir o mesmo ano ──────────────────
    _match_a4(df_bc3)

    # ── A5: mesmo aprendizado do A4, sem exigir o mesmo CNPJ ─────────────────
    _match_a5(df_bc3)

    # ── D3: consolidacao N-para-1 (linhas "sortido"/agregadas do SPED) ──────
    # Roda antes do D4/D5 de proposito: D5 (so similaridade, 1-para-1) pode
    # "roubar" por coincidencia de texto uma linha do SPED que na verdade e
    # uma consolidacao (ex.: um dos N itens do grupo vence sozinho por
    # similaridade, e os outros N-1 ficam NM para sempre, sem chance de o
    # D3 formar o grupo certo).
    idf_map, idf_padrao = _idf_lookup(df_bc1)
    idx_pendente_d3 = df_bc3.index[df_bc3["MATCH_TIPO"].isin(("ND", "NM"))]
    df_bc2_pend_d3 = df_bc2.loc[idx_pendente_d3]
    df_bc1_disp_d3 = df_bc1.loc[~df_bc1.index.isin(indices_bc1_usados)]
    match_d3 = _match_d3_por_nota(df_bc2_pend_d3, df_bc1_disp_d3, idf_map, idf_padrao)
    _aplicar(match_d3, "D3")
    indices_bc1_usados |= {v[0] for v in match_d3.values()}

    # ── D4: integridade de nota sobre o que ainda sobrou ND/NM ──────────────
    # Integridade (contagem de itens + somatório de VL_ITEM iguais entre XML
    # e SPED) recalculada aqui, só com os itens PENDENTES/DISPONÍVEIS neste
    # ponto — não com a nota inteira original. Motivo: outras partes da
    # mesma nota podem já ter sido resolvidas antes (D1/D2/família
    # A/D3) de forma N-para-1 (ex.: A1-A5 não consome BC1; D3 consolida N
    # itens do XML numa só linha do SPED) — isso muda a contagem de itens
    # "brutos" da nota sem que isso signifique divergência real no que
    # ainda falta casar. Calcular a integridade sobre a nota inteira
    # original bloquearia D4/D6 numa nota onde o RESTANTE pendente é, na
    # verdade, perfeitamente íntegro (caso real, CHV_NFE
    # 25230207555419000310550010001677321501275587: nota inteira tem 54
    # itens no XML x 40 no SPED — diferença de 14, toda por consolidações
    # A1-A5 em OUTROS produtos da nota — mas os itens que sobraram pendentes
    # continuavam batendo 1-para-1 em contagem e valor).
    idx_pendente_d4 = df_bc3.index[df_bc3["MATCH_TIPO"].isin(("ND", "NM"))]
    df_bc2_pend_d4 = df_bc2.loc[idx_pendente_d4]
    df_bc1_disp_d4 = df_bc1.loc[~df_bc1.index.isin(indices_bc1_usados)]
    chaves_integras_d4 = _integridade_por_nota(df_bc2_pend_d4, df_bc1_disp_d4)
    match_d4 = _match_d4_por_nota(df_bc2_pend_d4, df_bc1_disp_d4, chaves_integras_d4)
    _aplicar(match_d4, "D4")
    indices_bc1_usados |= {v[0] for v in match_d4.values()}

    # ── D5: ultimo recurso (so similaridade) sobre o que ainda sobrou ───────
    idx_pendente_d5 = df_bc3.index[df_bc3["MATCH_TIPO"].isin(("ND", "NM"))]
    df_bc2_pend_d5 = df_bc2.loc[idx_pendente_d5]
    df_bc1_disp_d5 = df_bc1.loc[~df_bc1.index.isin(indices_bc1_usados)]
    match_d5 = _match_d5_por_nota(df_bc2_pend_d5, df_bc1_disp_d5)
    _aplicar(match_d5, "D5")
    indices_bc1_usados |= {v[0] for v in match_d5.values()}

    # ── D6: ultimo recurso de tudo (so valor, com desempate por texto) ──────
    # Roda depois do D5 de proposito: eh o criterio com menos evidencia (o
    # valor pode nao vir acompanhado de texto) — so entra sobre o que nenhum
    # outro tipo, que tem alguma evidencia de texto/codigo, conseguiu casar.
    # Nao exige mais "nota integra" (ver docstring de _match_d6_por_nota) —
    # A1-A5 nao consome BC1, entao a integridade da nota inteira/pendente
    # fica poluida por linhas ja "usadas" por aprendizado pra outros itens,
    # bloqueando pares que sao, isoladamente, perfeitamente reconciliaveis
    # (valor unico dos dois lados). A seguranca do D6 vem da unicidade de
    # valor + desempate por texto (com descarte em caso de empate duplo).
    idx_pendente_d6 = df_bc3.index[df_bc3["MATCH_TIPO"].isin(("ND", "NM"))]
    df_bc2_pend_d6 = df_bc2.loc[idx_pendente_d6]
    df_bc1_disp_d6 = df_bc1.loc[~df_bc1.index.isin(indices_bc1_usados)]
    match_d6 = _match_d6_por_nota(df_bc2_pend_d6, df_bc1_disp_d6)
    _aplicar(match_d6, "D6")

    contagem_tipo = df_bc3["MATCH_TIPO"].value_counts().to_dict()
    meta = {
        "origem_dados": "BC3",
        "total_linhas": len(df_bc3),
        "erros": erros,
        "match_d1": contagem_tipo.get("D1", 0),
        "match_d2": contagem_tipo.get("D2", 0),
        "match_a1": contagem_tipo.get("A1", 0),
        "match_a2": contagem_tipo.get("A2", 0),
        "match_a3": contagem_tipo.get("A3", 0),
        "match_a4": contagem_tipo.get("A4", 0),
        "match_a5": contagem_tipo.get("A5", 0),
        "match_d3": contagem_tipo.get("D3", 0),
        "match_d4": contagem_tipo.get("D4", 0),
        "match_d5": contagem_tipo.get("D5", 0),
        "match_d6": contagem_tipo.get("D6", 0),
        "nao_declarado": contagem_tipo.get("ND", 0),   # chave inteira ausente do SPED (apos familia A/D3/D4/D5/D6)
        "sem_match_item": contagem_tipo.get("NM", 0),  # chave declarada, item nao casou em nenhum tipo (apos familia A/D3/D4/D5/D6)
    }
    return df_bc3, meta
