"""Motor de Matching (Etapa 1): cruza a BC2 (XML — itens de Emissão de
Terceiros) com a BC1 (SPED — sped_entradas_terceiros) para produzir a BC3
(resultado do cruzamento), sem depender de NUM_ITEM como chave — a ordem
sequencial dos itens no XML do fornecedor não necessariamente bate com a
ordem de escrituração no SPED do declarante.

Matching em seis níveis, os cinco primeiros sempre dentro da MESMA CHV_NFE
(cada nível só tenta casar o que sobrou do anterior):
  - Tipo 1: mesmo EAN/GTIN (COD_BARRA do SPED == cean do XML, comparados após
    normalização — ver _normalizar_gtin) **e** similaridade de descrição
    (xprod x DESCR_ITEM) > LIMIAR_TIPO1 (0,90).
  - Tipo 2 (fallback): para os itens que não casaram no Tipo 1, mesmo Valor
    Total (VL_ITEM idêntico) **e** similaridade de descrição > LIMIAR_TIPO2
    (0,60).
  - Tipo 3 (aprendizado histórico): para os itens que sobraram como 'nd' ou
    'nm', busca num dicionário de aprendizado — construído só a partir dos
    matches já confirmados em Tipo 1/Tipo 2 — a combinação CNPJ_EMITENTE +
    COD_ITEM (XML) + ANO_EMISSAO (dígitos 3-4 da CHV_NFE). Não depende de
    similaridade de texto nem de a nota estar declarada: sinaliza como aquele
    fornecedor/código costuma ser escriturado, mesmo quando a nota nem consta
    na declaração ('nd'). Ver _match_tipo3.
  - Tipo 3.1 (aprendizado histórico por descrição): igual ao Tipo 3, mas
    troca COD_ITEM pela descrição exata do produto no XML (xprod) na chave
    de aprendizado — CNPJ_EMITENTE + DESCR_ITEM (XML, exata) + ANO_EMISSAO.
    Cobre fornecedores cujo código interno varia mas cuja descrição de texto
    é estável. Roda sobre o que sobrou 'nd'/'nm' após o Tipo 3. Ver
    _match_tipo3_1.
  - Tipo 3.2 (aprendizado histórico por código, sem exigir mesmo ano):
    fallback do Tipo 3 — mesma chave (CNPJ_EMITENTE + COD_ITEM), mas sem o
    ANO_EMISSAO. Cobre o caso de um fornecedor/código já 100% reconhecido em
    um ano (ex.: 2024, via Tipo 1/2), mas sem nenhuma âncora confirmada no
    ano da nota pendente (ex.: 2023) — sem essa chave mais ampla, o Tipo 3
    nunca recupera essas notas, mesmo sendo claramente o mesmo produto. Roda
    sobre o que sobrou 'nd'/'nm' após o Tipo 3.1. Ver _match_tipo3_2.
  - Tipo 3.3 (aprendizado histórico por descrição, sem exigir mesmo ano):
    mesma ideia do Tipo 3.2, mas com a chave do Tipo 3.1 (CNPJ_EMITENTE +
    DESCR_ITEM exata), também sem ANO_EMISSAO. Roda sobre o que sobrou
    'nd'/'nm' após o Tipo 3.2. Ver _match_tipo3_3.
  - Tipo 3.4 (aprendizado histórico por descrição, sem exigir CNPJ nem
    ano): fallback do Tipo 3.3, relaxando também o CNPJ_EMITENTE — chave só
    a descrição exata do XML (DESCR_ITEM). Nível mais amplo/permissivo da
    família de aprendizado por descrição: cobre a mesma descrição de texto
    vinda de fornecedores diferentes. Roda sobre o que sobrou 'nd'/'nm'
    após o Tipo 3.3. Ver _match_tipo3_4.
  - Tipo 4 (integridade de nota): para os itens que ainda sobraram 'nd'/'nm'
    após o Tipo 3.4, restringe às CHV_NFE onde a nota é "íntegra" — mesma
    contagem de itens **e** mesmo somatório de VL_ITEM entre o lado XML (BC2)
    e o lado SPED (BC1), ver _integridade_por_nota — e casa, só dentro
    dessas notas, por similaridade de descrição > LIMIAR_TIPO4 (0,70),
    1-para-1. Ver _match_tipo4_por_nota.
  - Tipo 5 (último recurso): para os itens que ainda sobraram 'nd'/'nm' após
    o Tipo 4, casa dentro da mesma CHV_NFE só por similaridade de descrição
    > LIMIAR_TIPO5 (0,70), 1-para-1, sem exigir GTIN, valor ou integridade
    de nota. Ver _match_tipo5_por_nota.

Não Declarados e Não Matches (antes do Tipo 3/3.1/3.2/3.3/3.4/4/5):
  - 'nd' (Não Declarado) — a CHV_NFE inteira não aparece na BC1.
  - 'nm' (Não Match) — a CHV_NFE existe na BC1, mas o item não passou nem no
    Tipo 1 nem no Tipo 2.
Itens 'nd'/'nm' recuperados pelo Tipo 3, 3.1, 3.2, 3.3, 3.4, 4 ou 5 mudam de
status para
'TIPO_3'/'TIPO_3_1'/'TIPO_3_2'/'TIPO_3_3'/'TIPO_3_4'/'TIPO_4'/'TIPO_5'; os
que não encontram correspondência em nenhum deles mantêm 'ND'/'NM'.

Consistência de Unicidade — um item da BC1 (declaração) não pode ser
"consumido" por dois matches diferentes (1 para 1), nem entre os dois tipos.

ID_UNICO (já presente em BC1 e BC2) segue existindo só para rastreabilidade
interna — não é usado como chave de ligação. Regra Operacional R07: as
colunas de ligação (CHV_NFE, COD_ITEM, NUM_ITEM, CFOP) continuam com
dtype=str.

Implementação vetorizada (sem .iterrows()/.apply() linha a linha) para
escalar a operações com milhões de itens: agrupado por CHV_NFE, com a
matriz de similaridade calculada em lote por nota via scoring.matriz_similaridade()
(rapidfuzz.process.cdist, implementado em C) — o laço em Python passa a ser
por NOTA, não por ITEM. As máscaras de GTIN (Tipo 1) e Valor (Tipo 2) são
comparações vetorizadas (NumPy broadcasting) sobre essa mesma matriz, e a
atribuição gulosa (maior score primeiro, 1-para-1) usa np.argsort sobre os
pares que já passam nas duas condições de cada tipo.
"""
import sys
from pathlib import Path

_APP_DIR = Path(__file__).parent
if str(_APP_DIR) not in sys.path:
    sys.path.insert(0, str(_APP_DIR))

import numpy as np
import pandas as pd

import loader
import scoring

LIMIAR_TIPO1 = 0.90  # mesmo GTIN/EAN + similaridade
LIMIAR_TIPO2 = 0.60  # mesmo Valor Total + similaridade
LIMIAR_TIPO4 = 0.70  # nota integra (mesma contagem/valor) + similaridade
LIMIAR_TIPO5 = 0.70  # ultimo recurso: so similaridade, mesma chave

_COL_DESCR_XML = "fatoitemnfe_infnfe_det_prod_xprod"
_COL_CNPJ_EMIT_XML = "fatonfe_infnfe_emit_cnpj"
_SEM_GTIN = {"", "SEM GTIN", "NAN", "NONE"}


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
    descricoes_bc2 = grupo_bc2[_COL_DESCR_XML].astype(str).tolist()
    descricoes_bc1 = grupo_bc1["DESCR_ITEM"].astype(str).tolist()
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


def _match_tipo1_por_nota(df_bc2: pd.DataFrame, df_bc1: pd.DataFrame) -> dict:
    """Tipo 1: dentro da mesma CHV_NFE, mesmo EAN/GTIN E similaridade de
    descrição > LIMIAR_TIPO1. Devolve {indice_bc2: (indice_bc1, score)}."""
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

        mask_final = (matriz > LIMIAR_TIPO1) & mask_gtin
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
    quebrando o casamento por Valor Total (Tipo 2) e a soma de integridade
    de nota (Tipo 4)."""
    return pd.to_numeric(
        serie.astype(str).str.strip().str.replace(",", ".", regex=False),
        errors="coerce",
    )


def _match_tipo2_por_nota(df_bc2: pd.DataFrame, df_bc1: pd.DataFrame) -> dict:
    """Tipo 2 (fallback): dentro da mesma CHV_NFE, mesmo Valor Total (VL_ITEM
    idêntico) E similaridade de descrição > LIMIAR_TIPO2. Chamado só com os
    itens que sobraram do Tipo 1. Devolve {indice_bc2: (indice_bc1, score)}."""
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

        mask_final = (matriz > LIMIAR_TIPO2) & mask_valor
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


def _chave_aprendizado(df: pd.DataFrame) -> pd.Series:
    """Monta a chave de vínculo do dicionário de aprendizado (Tipo 3):
    CNPJ_EMITENTE (XML) + COD_ITEM (XML, normalizado) + ANO_EMISSAO (dígitos
    3-4 da CHV_NFE)."""
    return pd.Series(
        df[_COL_CNPJ_EMIT_XML].astype(str).str.strip().to_numpy()
        + "|" + _normalizar_codigo(df["COD_ITEM"])
        + "|" + _extrair_ano_emissao(df["CHV_NFE"]),
        index=df.index,
    )


def _montar_dicionario_aprendizado(df_bc3: pd.DataFrame) -> pd.DataFrame:
    """Constrói o dicionário de aprendizado exclusivamente a partir dos
    matches já confirmados de Tipo 1 e Tipo 2: mapeia CNPJ_EMITENTE +
    COD_ITEM (XML) + ANO_EMISSAO -> COD_ITEM_DECLARACAO/DESCR_ITEM_DECLARACAO
    já vinculados historicamente. Em caso de chaves repetidas (mesmo
    fornecedor/código/ano com mais de um par histórico), prevalece a
    primeira ocorrência."""
    confirmados = df_bc3[df_bc3["MATCH_TIPO"].isin(("TIPO_1", "TIPO_2"))]
    if confirmados.empty:
        return pd.DataFrame(columns=["COD_ITEM_DECLARACAO", "DESCR_ITEM_DECLARACAO"])

    aprendizado = pd.DataFrame({
        "_CHAVE": _chave_aprendizado(confirmados),
        "COD_ITEM_DECLARACAO": confirmados["COD_ITEM_DECLARACAO"].to_numpy(),
        "DESCR_ITEM_DECLARACAO": confirmados["DESCR_ITEM_DECLARACAO"].to_numpy(),
    })
    return aprendizado.drop_duplicates("_CHAVE").set_index("_CHAVE")


def _match_tipo3(df_bc3: pd.DataFrame) -> int:
    """Tipo 3 (aprendizado histórico): para itens 'ND' ou 'NM', busca no
    dicionário de aprendizado (montado só a partir de matches confirmados de
    Tipo 1/Tipo 2 — ver _montar_dicionario_aprendizado) a combinação
    CNPJ_EMITENTE + COD_ITEM (XML) + ANO_EMISSAO. Encontrando, preenche
    COD_ITEM_DECLARACAO/DESCR_ITEM_DECLARACAO com o histórico e muda o status
    para 'TIPO_3' — inclusive para 'ND' (sinaliza ao auditor como o produto
    costuma ser escriturado quando a nota é declarada). Sem correspondência,
    mantém o status original ('ND'/'NM'). Devolve a quantidade recuperada.
    Muta df_bc3 in-place."""
    dicionario = _montar_dicionario_aprendizado(df_bc3)
    if dicionario.empty:
        return 0

    alvo_mask = df_bc3["MATCH_TIPO"].isin(("ND", "NM"))
    if not alvo_mask.any():
        return 0

    chave_alvo = _chave_aprendizado(df_bc3.loc[alvo_mask])
    cod_encontrado   = chave_alvo.map(dicionario["COD_ITEM_DECLARACAO"])
    descr_encontrado = chave_alvo.map(dicionario["DESCR_ITEM_DECLARACAO"])
    achou = cod_encontrado.notna()
    if not achou.any():
        return 0

    idx_achou = achou[achou].index
    df_bc3.loc[idx_achou, "MATCH_TIPO"]            = "TIPO_3"
    df_bc3.loc[idx_achou, "COD_ITEM_DECLARACAO"]   = cod_encontrado.loc[idx_achou].values
    df_bc3.loc[idx_achou, "DESCR_ITEM_DECLARACAO"] = descr_encontrado.loc[idx_achou].values
    return int(achou.sum())


def _chave_aprendizado_31(df: pd.DataFrame) -> pd.Series:
    """Monta a chave de vínculo do dicionário de aprendizado (Tipo 3.1):
    igual à do Tipo 3 (_chave_aprendizado), mas troca COD_ITEM pela
    descrição exata do produto no XML (_COL_DESCR_XML, normalizada por
    strip/upper — sem similaridade fuzzy) — CNPJ_EMITENTE (XML) + DESCR_ITEM
    (XML, exata) + ANO_EMISSAO (dígitos 3-4 da CHV_NFE)."""
    return pd.Series(
        df[_COL_CNPJ_EMIT_XML].astype(str).str.strip().to_numpy()
        + "|" + df[_COL_DESCR_XML].astype(str).str.strip().str.upper().to_numpy()
        + "|" + _extrair_ano_emissao(df["CHV_NFE"]),
        index=df.index,
    )


def _montar_dicionario_aprendizado_31(df_bc3: pd.DataFrame) -> pd.DataFrame:
    """Constrói o dicionário de aprendizado do Tipo 3.1 exclusivamente a
    partir dos matches já confirmados de Tipo 1 e Tipo 2 (mesma base do
    Tipo 3 — ver _montar_dicionario_aprendizado): mapeia CNPJ_EMITENTE +
    DESCR_ITEM (XML, exata) + ANO_EMISSAO -> COD_ITEM_DECLARACAO/
    DESCR_ITEM_DECLARACAO já vinculados historicamente. Em caso de chaves
    repetidas, prevalece a primeira ocorrência."""
    confirmados = df_bc3[df_bc3["MATCH_TIPO"].isin(("TIPO_1", "TIPO_2"))]
    if confirmados.empty:
        return pd.DataFrame(columns=["COD_ITEM_DECLARACAO", "DESCR_ITEM_DECLARACAO"])

    aprendizado = pd.DataFrame({
        "_CHAVE": _chave_aprendizado_31(confirmados),
        "COD_ITEM_DECLARACAO": confirmados["COD_ITEM_DECLARACAO"].to_numpy(),
        "DESCR_ITEM_DECLARACAO": confirmados["DESCR_ITEM_DECLARACAO"].to_numpy(),
    })
    return aprendizado.drop_duplicates("_CHAVE").set_index("_CHAVE")


def _match_tipo3_1(df_bc3: pd.DataFrame) -> int:
    """Tipo 3.1 (aprendizado histórico por descrição exata): igual ao Tipo 3
    (_match_tipo3), mas usa a descrição exata do produto no XML no lugar de
    COD_ITEM na chave de aprendizado — cobre fornecedores cujo código
    interno varia mas cuja descrição de texto é estável. Roda sobre o que
    sobrou 'ND'/'NM' após o Tipo 3. Sem correspondência, mantém o status
    original ('ND'/'NM'). Devolve a quantidade recuperada. Muta df_bc3
    in-place."""
    dicionario = _montar_dicionario_aprendizado_31(df_bc3)
    if dicionario.empty:
        return 0

    alvo_mask = df_bc3["MATCH_TIPO"].isin(("ND", "NM"))
    if not alvo_mask.any():
        return 0

    chave_alvo = _chave_aprendizado_31(df_bc3.loc[alvo_mask])
    cod_encontrado   = chave_alvo.map(dicionario["COD_ITEM_DECLARACAO"])
    descr_encontrado = chave_alvo.map(dicionario["DESCR_ITEM_DECLARACAO"])
    achou = cod_encontrado.notna()
    if not achou.any():
        return 0

    idx_achou = achou[achou].index
    df_bc3.loc[idx_achou, "MATCH_TIPO"]            = "TIPO_3_1"
    df_bc3.loc[idx_achou, "COD_ITEM_DECLARACAO"]   = cod_encontrado.loc[idx_achou].values
    df_bc3.loc[idx_achou, "DESCR_ITEM_DECLARACAO"] = descr_encontrado.loc[idx_achou].values
    return int(achou.sum())


def _chave_aprendizado_32(df: pd.DataFrame) -> pd.Series:
    """Monta a chave de vínculo do dicionário de aprendizado (Tipo 3.2):
    igual à do Tipo 3 (_chave_aprendizado), mas sem o ANO_EMISSAO —
    CNPJ_EMITENTE + COD_ITEM (XML, normalizado). Fallback para quando o
    Tipo 3 não encontra âncora confirmada (Tipo 1/Tipo 2) no mesmo ano da
    nota pendente, mesmo com o fornecedor/código já reconhecido em outro
    ano."""
    return pd.Series(
        df[_COL_CNPJ_EMIT_XML].astype(str).str.strip().to_numpy()
        + "|" + _normalizar_codigo(df["COD_ITEM"]),
        index=df.index,
    )


def _montar_dicionario_aprendizado_32(df_bc3: pd.DataFrame) -> pd.DataFrame:
    """Constrói o dicionário de aprendizado do Tipo 3.2 exclusivamente a
    partir dos matches já confirmados de Tipo 1 e Tipo 2 (mesma base do
    Tipo 3 — ver _montar_dicionario_aprendizado): mapeia CNPJ_EMITENTE +
    COD_ITEM (XML) -> COD_ITEM_DECLARACAO/DESCR_ITEM_DECLARACAO já vinculados
    historicamente, sem distinguir por ano. Em caso de chaves repetidas
    (mesmo fornecedor/código em anos diferentes com pares históricos
    diferentes), prevalece a primeira ocorrência."""
    confirmados = df_bc3[df_bc3["MATCH_TIPO"].isin(("TIPO_1", "TIPO_2"))]
    if confirmados.empty:
        return pd.DataFrame(columns=["COD_ITEM_DECLARACAO", "DESCR_ITEM_DECLARACAO"])

    aprendizado = pd.DataFrame({
        "_CHAVE": _chave_aprendizado_32(confirmados),
        "COD_ITEM_DECLARACAO": confirmados["COD_ITEM_DECLARACAO"].to_numpy(),
        "DESCR_ITEM_DECLARACAO": confirmados["DESCR_ITEM_DECLARACAO"].to_numpy(),
    })
    return aprendizado.drop_duplicates("_CHAVE").set_index("_CHAVE")


def _match_tipo3_2(df_bc3: pd.DataFrame) -> int:
    """Tipo 3.2 (aprendizado histórico por código, sem exigir mesmo ano):
    fallback do Tipo 3 (_match_tipo3) para itens 'ND'/'NM' cujo CNPJ+código
    não tem nenhuma âncora confirmada (Tipo 1/Tipo 2) no próprio ano da
    nota, mas tem em outro ano — cobre fornecedor/código estável ano a ano.
    Roda sobre o que sobrou 'ND'/'NM' após o Tipo 3.1. Sem correspondência,
    mantém o status original. Devolve a quantidade recuperada. Muta df_bc3
    in-place."""
    dicionario = _montar_dicionario_aprendizado_32(df_bc3)
    if dicionario.empty:
        return 0

    alvo_mask = df_bc3["MATCH_TIPO"].isin(("ND", "NM"))
    if not alvo_mask.any():
        return 0

    chave_alvo = _chave_aprendizado_32(df_bc3.loc[alvo_mask])
    cod_encontrado   = chave_alvo.map(dicionario["COD_ITEM_DECLARACAO"])
    descr_encontrado = chave_alvo.map(dicionario["DESCR_ITEM_DECLARACAO"])
    achou = cod_encontrado.notna()
    if not achou.any():
        return 0

    idx_achou = achou[achou].index
    df_bc3.loc[idx_achou, "MATCH_TIPO"]            = "TIPO_3_2"
    df_bc3.loc[idx_achou, "COD_ITEM_DECLARACAO"]   = cod_encontrado.loc[idx_achou].values
    df_bc3.loc[idx_achou, "DESCR_ITEM_DECLARACAO"] = descr_encontrado.loc[idx_achou].values
    return int(achou.sum())


def _chave_aprendizado_33(df: pd.DataFrame) -> pd.Series:
    """Monta a chave de vínculo do dicionário de aprendizado (Tipo 3.3):
    igual à do Tipo 3.1 (_chave_aprendizado_31), mas sem o ANO_EMISSAO —
    CNPJ_EMITENTE + DESCR_ITEM (XML, exata). Mesma ideia de fallback do
    Tipo 3.2, só que pela descrição exata em vez do código."""
    return pd.Series(
        df[_COL_CNPJ_EMIT_XML].astype(str).str.strip().to_numpy()
        + "|" + df[_COL_DESCR_XML].astype(str).str.strip().str.upper().to_numpy(),
        index=df.index,
    )


def _montar_dicionario_aprendizado_33(df_bc3: pd.DataFrame) -> pd.DataFrame:
    """Constrói o dicionário de aprendizado do Tipo 3.3 exclusivamente a
    partir dos matches já confirmados de Tipo 1 e Tipo 2 (mesma base do
    Tipo 3 — ver _montar_dicionario_aprendizado): mapeia CNPJ_EMITENTE +
    DESCR_ITEM (XML, exata) -> COD_ITEM_DECLARACAO/DESCR_ITEM_DECLARACAO já
    vinculados historicamente, sem distinguir por ano. Em caso de chaves
    repetidas, prevalece a primeira ocorrência."""
    confirmados = df_bc3[df_bc3["MATCH_TIPO"].isin(("TIPO_1", "TIPO_2"))]
    if confirmados.empty:
        return pd.DataFrame(columns=["COD_ITEM_DECLARACAO", "DESCR_ITEM_DECLARACAO"])

    aprendizado = pd.DataFrame({
        "_CHAVE": _chave_aprendizado_33(confirmados),
        "COD_ITEM_DECLARACAO": confirmados["COD_ITEM_DECLARACAO"].to_numpy(),
        "DESCR_ITEM_DECLARACAO": confirmados["DESCR_ITEM_DECLARACAO"].to_numpy(),
    })
    return aprendizado.drop_duplicates("_CHAVE").set_index("_CHAVE")


def _match_tipo3_3(df_bc3: pd.DataFrame) -> int:
    """Tipo 3.3 (aprendizado histórico por descrição, sem exigir mesmo ano):
    fallback do Tipo 3.1 (_match_tipo3_1), mesma lógica de relaxamento de
    ano do Tipo 3.2, mas usando a descrição exata do XML como chave. Roda
    sobre o que sobrou 'ND'/'NM' após o Tipo 3.2. Sem correspondência,
    mantém o status original. Devolve a quantidade recuperada. Muta df_bc3
    in-place."""
    dicionario = _montar_dicionario_aprendizado_33(df_bc3)
    if dicionario.empty:
        return 0

    alvo_mask = df_bc3["MATCH_TIPO"].isin(("ND", "NM"))
    if not alvo_mask.any():
        return 0

    chave_alvo = _chave_aprendizado_33(df_bc3.loc[alvo_mask])
    cod_encontrado   = chave_alvo.map(dicionario["COD_ITEM_DECLARACAO"])
    descr_encontrado = chave_alvo.map(dicionario["DESCR_ITEM_DECLARACAO"])
    achou = cod_encontrado.notna()
    if not achou.any():
        return 0

    idx_achou = achou[achou].index
    df_bc3.loc[idx_achou, "MATCH_TIPO"]            = "TIPO_3_3"
    df_bc3.loc[idx_achou, "COD_ITEM_DECLARACAO"]   = cod_encontrado.loc[idx_achou].values
    df_bc3.loc[idx_achou, "DESCR_ITEM_DECLARACAO"] = descr_encontrado.loc[idx_achou].values
    return int(achou.sum())


def _chave_aprendizado_34(df: pd.DataFrame) -> pd.Series:
    """Monta a chave de vínculo do dicionário de aprendizado (Tipo 3.4):
    igual à do Tipo 3.3 (_chave_aprendizado_33), mas sem o CNPJ_EMITENTE —
    só a descrição exata do produto no XML (_COL_DESCR_XML, normalizada por
    strip/upper). Fallback mais amplo da família "descrição exata": cobre a
    mesma descrição de texto vinda de fornecedores diferentes, quando nem o
    CNPJ nem o ano têm âncora confirmada em comum."""
    return pd.Series(
        df[_COL_DESCR_XML].astype(str).str.strip().str.upper().to_numpy(),
        index=df.index,
    )


def _montar_dicionario_aprendizado_34(df_bc3: pd.DataFrame) -> pd.DataFrame:
    """Constrói o dicionário de aprendizado do Tipo 3.4 exclusivamente a
    partir dos matches já confirmados de Tipo 1 e Tipo 2 (mesma base do
    Tipo 3 — ver _montar_dicionario_aprendizado): mapeia DESCR_ITEM (XML,
    exata) -> COD_ITEM_DECLARACAO/DESCR_ITEM_DECLARACAO já vinculados
    historicamente, sem distinguir por CNPJ nem por ano. Em caso de chaves
    repetidas, prevalece a primeira ocorrência."""
    confirmados = df_bc3[df_bc3["MATCH_TIPO"].isin(("TIPO_1", "TIPO_2"))]
    if confirmados.empty:
        return pd.DataFrame(columns=["COD_ITEM_DECLARACAO", "DESCR_ITEM_DECLARACAO"])

    aprendizado = pd.DataFrame({
        "_CHAVE": _chave_aprendizado_34(confirmados),
        "COD_ITEM_DECLARACAO": confirmados["COD_ITEM_DECLARACAO"].to_numpy(),
        "DESCR_ITEM_DECLARACAO": confirmados["DESCR_ITEM_DECLARACAO"].to_numpy(),
    })
    return aprendizado.drop_duplicates("_CHAVE").set_index("_CHAVE")


def _match_tipo3_4(df_bc3: pd.DataFrame) -> int:
    """Tipo 3.4 (aprendizado histórico por descrição, sem exigir CNPJ nem
    ano): fallback do Tipo 3.3 (_match_tipo3_3), relaxando também o
    CNPJ_EMITENTE — usa só a descrição exata do XML como chave. É o nível
    mais amplo/permissivo da família de aprendizado por descrição, por isso
    roda por último dentro dela, sobre o que sobrou 'ND'/'NM' após o Tipo
    3.3. Sem correspondência, mantém o status original. Devolve a
    quantidade recuperada. Muta df_bc3 in-place."""
    dicionario = _montar_dicionario_aprendizado_34(df_bc3)
    if dicionario.empty:
        return 0

    alvo_mask = df_bc3["MATCH_TIPO"].isin(("ND", "NM"))
    if not alvo_mask.any():
        return 0

    chave_alvo = _chave_aprendizado_34(df_bc3.loc[alvo_mask])
    cod_encontrado   = chave_alvo.map(dicionario["COD_ITEM_DECLARACAO"])
    descr_encontrado = chave_alvo.map(dicionario["DESCR_ITEM_DECLARACAO"])
    achou = cod_encontrado.notna()
    if not achou.any():
        return 0

    idx_achou = achou[achou].index
    df_bc3.loc[idx_achou, "MATCH_TIPO"]            = "TIPO_3_4"
    df_bc3.loc[idx_achou, "COD_ITEM_DECLARACAO"]   = cod_encontrado.loc[idx_achou].values
    df_bc3.loc[idx_achou, "DESCR_ITEM_DECLARACAO"] = descr_encontrado.loc[idx_achou].values
    return int(achou.sum())


def _integridade_por_nota(df_bc2: pd.DataFrame, df_bc1: pd.DataFrame) -> set:
    """Calcula, por CHV_NFE, a contagem de itens e o somatório de VL_ITEM em
    cada lado (XML/BC2 e SPED/BC1) e devolve o conjunto de CHV_NFE onde
    ambos batem exatamente ("nota íntegra") — pré-requisito do Tipo 4.
    Usa as bases completas (todos os itens da nota, não só os pendentes),
    já que a integridade é uma propriedade estrutural da nota inteira."""
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


def _match_tipo4_por_nota(df_bc2: pd.DataFrame, df_bc1: pd.DataFrame, chaves_integras: set) -> dict:
    """Tipo 4 (integridade de nota): restringe às CHV_NFE "íntegras" (mesma
    contagem de itens e mesmo somatório de VL_ITEM entre XML e SPED — ver
    _integridade_por_nota) e casa, dentro delas, só por similaridade de
    descrição > LIMIAR_TIPO4, 1-para-1 (_atribuir_1_para_1). Chamado só com
    os itens que sobraram 'nd'/'nm' após Tipo 1/2/3. Devolve
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
        mask_final = matriz > LIMIAR_TIPO4
        correspondencias.update(
            _atribuir_1_para_1(mask_final, matriz, grupo_bc2.index, grupo_bc1.index)
        )

    return correspondencias


def _match_tipo5_por_nota(df_bc2: pd.DataFrame, df_bc1: pd.DataFrame) -> dict:
    """Tipo 5 (último recurso): dentro da mesma CHV_NFE, casa só por
    similaridade de descrição > LIMIAR_TIPO5, 1-para-1 (_atribuir_1_para_1)
    — sem exigir GTIN, valor ou integridade de nota. Chamado só com os itens
    que sobraram 'nd'/'nm' após Tipo 1/2/3/4. Devolve
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
        mask_final = matriz > LIMIAR_TIPO5
        correspondencias.update(
            _atribuir_1_para_1(mask_final, matriz, grupo_bc2.index, grupo_bc1.index)
        )

    return correspondencias


def executar_matching() -> "tuple[pd.DataFrame, dict]":
    """Executa o cruzamento BC2 (XML, ET) x BC1 (SPED) em cinco níveis e
    devolve a BC3: uma linha por item da BC2, com DESCR_ITEM_DECLARACAO/
    COD_ITEM_DECLARACAO trazidos do BC1 quando houver correspondência
    (Tipo 1, 2, 3, 4 ou 5), 'nd' quando a CHV_NFE não estiver declarada, ou
    'nm' quando a CHV_NFE existir mas o item não passar em nenhum dos tipos."""
    df_bc2, meta_bc2 = loader.montar_bc2()
    df_bc1, meta_bc1 = loader.load_declaracao_entradas_terceiros()

    erros = list(meta_bc2.get("erros", [])) + list(meta_bc1.get("erros", []))
    if df_bc2.empty or df_bc1.empty:
        meta = {"origem_dados": "BC3", "erros": erros, "total_linhas": 0}
        return pd.DataFrame(), meta

    df_bc2 = df_bc2.reset_index(drop=True)
    df_bc1 = df_bc1.reset_index(drop=True)

    # Integridade de nota (contagem de itens + somatório de VL_ITEM iguais
    # entre XML e SPED) calculada sobre as bases completas, antes de
    # qualquer consumo por Tipo 1/2 — é propriedade da nota, não dos itens
    # ainda disponíveis (Tipo 4).
    chaves_integras = _integridade_por_nota(df_bc2, df_bc1)

    # ── Tipo 1: GTIN + similaridade > 0,90 ──────────────────────────────────
    match_tipo1 = _match_tipo1_por_nota(df_bc2, df_bc1)
    indices_bc1_usados = {v[0] for v in match_tipo1.values()}

    pendentes_idx = df_bc2.index.difference(pd.Index(match_tipo1.keys()))
    df_bc2_pend = df_bc2.loc[pendentes_idx]
    df_bc1_disp = df_bc1.loc[~df_bc1.index.isin(indices_bc1_usados)]

    # ── Tipo 2 (fallback): Valor + similaridade > 0,60 ──────────────────────
    match_tipo2 = _match_tipo2_por_nota(df_bc2_pend, df_bc1_disp)
    indices_bc1_usados |= {v[0] for v in match_tipo2.values()}

    # ── Monta a BC3 vetorizadamente (sem laço por linha) ────────────────────
    df_bc3 = df_bc2.copy()
    chaves_declaradas = set(df_bc1["CHV_NFE"])
    nao_declarado = ~df_bc3["CHV_NFE"].isin(chaves_declaradas)

    df_bc3["MATCH_TIPO"] = np.where(nao_declarado, "ND", "NM")
    df_bc3["MATCH_SCORE"] = 0.0
    df_bc3["DESCR_ITEM_DECLARACAO"] = np.where(nao_declarado, "nd", "nm")
    df_bc3["COD_ITEM_DECLARACAO"]   = np.where(nao_declarado, "nd", "nm")

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

    _aplicar(match_tipo1, "TIPO_1")
    _aplicar(match_tipo2, "TIPO_2")

    # ── Tipo 3: aprendizado histórico sobre o que sobrou como ND/NM ─────────
    _match_tipo3(df_bc3)

    # ── Tipo 3.1: mesmo aprendizado, por descrição exata (não COD_ITEM) ────
    _match_tipo3_1(df_bc3)

    # ── Tipo 3.2: mesmo aprendizado do Tipo 3, sem exigir o mesmo ano ──────
    _match_tipo3_2(df_bc3)

    # ── Tipo 3.3: mesmo aprendizado do Tipo 3.1, sem exigir o mesmo ano ────
    _match_tipo3_3(df_bc3)

    # ── Tipo 3.4: mesmo aprendizado do Tipo 3.3, sem exigir o mesmo CNPJ ───
    _match_tipo3_4(df_bc3)

    # ── Tipo 4: integridade de nota sobre o que ainda sobrou ND/NM ──────────
    idx_pendente_tipo4 = df_bc3.index[df_bc3["MATCH_TIPO"].isin(("ND", "NM"))]
    df_bc2_pend_tipo4 = df_bc2.loc[idx_pendente_tipo4]
    df_bc1_disp_tipo4 = df_bc1.loc[~df_bc1.index.isin(indices_bc1_usados)]
    match_tipo4 = _match_tipo4_por_nota(df_bc2_pend_tipo4, df_bc1_disp_tipo4, chaves_integras)
    _aplicar(match_tipo4, "TIPO_4")
    indices_bc1_usados |= {v[0] for v in match_tipo4.values()}

    # ── Tipo 5: ultimo recurso (so similaridade) sobre o que ainda sobrou ───
    idx_pendente_tipo5 = df_bc3.index[df_bc3["MATCH_TIPO"].isin(("ND", "NM"))]
    df_bc2_pend_tipo5 = df_bc2.loc[idx_pendente_tipo5]
    df_bc1_disp_tipo5 = df_bc1.loc[~df_bc1.index.isin(indices_bc1_usados)]
    match_tipo5 = _match_tipo5_por_nota(df_bc2_pend_tipo5, df_bc1_disp_tipo5)
    _aplicar(match_tipo5, "TIPO_5")

    contagem_tipo = df_bc3["MATCH_TIPO"].value_counts().to_dict()
    meta = {
        "origem_dados": "BC3",
        "total_linhas": len(df_bc3),
        "erros": erros,
        "match_tipo1": contagem_tipo.get("TIPO_1", 0),
        "match_tipo2": contagem_tipo.get("TIPO_2", 0),
        "match_tipo3": contagem_tipo.get("TIPO_3", 0),
        "match_tipo3_1": contagem_tipo.get("TIPO_3_1", 0),
        "match_tipo3_2": contagem_tipo.get("TIPO_3_2", 0),
        "match_tipo3_3": contagem_tipo.get("TIPO_3_3", 0),
        "match_tipo3_4": contagem_tipo.get("TIPO_3_4", 0),
        "match_tipo4": contagem_tipo.get("TIPO_4", 0),
        "match_tipo5": contagem_tipo.get("TIPO_5", 0),
        "nao_declarado": contagem_tipo.get("ND", 0),   # chave inteira ausente do SPED (apos Tipo 3/4/5)
        "sem_match_item": contagem_tipo.get("NM", 0),  # chave declarada, item nao casou em nenhum tipo (apos Tipo 3/4/5)
    }
    return df_bc3, meta
