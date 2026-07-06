"""Motor de Matching (Etapa 1): cruza a BC2 (XML — itens de Emissão de
Terceiros) com a BC1 (SPED — sped_entradas_terceiros) para produzir a BC3
(resultado do cruzamento), sem depender de NUM_ITEM como chave — a ordem
sequencial dos itens no XML do fornecedor não necessariamente bate com a
ordem de escrituração no SPED do declarante.

Hierarquia de chaves (cada nível só tenta casar o que sobrou do anterior):
  1. Match Principal — CHV_NFE + VL_ITEM (valor exato, arredondado a 2 casas).
  2. Match Secundário — dentro da MESMA CHV_NFE: similaridade de texto
     (produto do XML x DESCR_ITEM do SPED), sugerido quando score >
     LIMIAR_SIMILARIDADE. (O passo de GTIN/EAN — COD_BARRA — foi suspenso;
     o fallback do Principal vai direto para o Fuzzy.)
  3. Sem match em nenhum critério — duas situações distintas:
     a. 'nd' (não declarado) — a CHV_NFE inteira não aparece na BC1: a nota
        de compra não foi encontrada na declaração (possível compra não
        declarada, não é só um item sem match).
     b. 'nm' (não match) — a CHV_NFE existe na BC1, mas este item específico
        não bateu por nenhum dos critérios (valor, similaridade).

ID_UNICO (já presente em BC1 e BC2) segue existindo só para rastreabilidade
interna — não é usado como chave de ligação.

Implementação vetorizada (sem .iterrows()/.apply() linha a linha) para
escalar a operações com milhões de itens:
  - Match Principal: merge (hash join) por (CHV_NFE, valor, rank de
    ocorrência) — o "rank" (posição da ocorrência dentro do grupo, via
    groupby().cumcount()) é o que garante 1-para-1 mesmo com valores
    repetidos dentro da mesma chave, sem precisar de laço item a item.
  - Fuzzy: agrupado por CHV_NFE, com a matriz de similaridade calculada em
    lote por nota (rapidfuzz.process.cdist, implementado em C) em vez de
    comparar item a item — o laço em Python passa a ser por NOTA, não por
    ITEM (uma nota típica tem poucos itens; milhões de itens tendem a virar
    "só" dezenas/centenas de milhares de notas).
"""
import sys
from pathlib import Path

_APP_DIR = Path(__file__).parent
if str(_APP_DIR) not in sys.path:
    sys.path.insert(0, str(_APP_DIR))

import numpy as np
import pandas as pd
from rapidfuzz import fuzz, process

import loader

LIMIAR_SIMILARIDADE = 0.85

_COL_DESCR_XML = "fatoitemnfe_infnfe_det_prod_xprod"


def _arredondar_valor(serie: pd.Series) -> pd.Series:
    return pd.to_numeric(serie, errors="coerce").round(2)


def _match_exato_vetorizado(df_bc2: pd.DataFrame, df_bc1: pd.DataFrame, colunas_chave: list) -> dict:
    """Match exato 1-para-1 via merge (hash join) por 'colunas_chave' (ex.:
    ['CHV_NFE', '_VAL'] ou ['CHV_NFE', 'COD_BARRA']). Usa groupby().cumcount()
    como "rank de ocorrência" para casar duplicatas em ordem, sem laço
    item a item. Devolve {indice_bc2: indice_bc1}."""
    if df_bc2.empty or df_bc1.empty:
        return {}

    bc2 = df_bc2[colunas_chave].copy()
    bc2["_IDX_BC2"] = df_bc2.index
    bc2["_RANK"] = bc2.groupby(colunas_chave).cumcount()

    bc1 = df_bc1[colunas_chave].copy()
    bc1["_IDX_BC1"] = df_bc1.index
    bc1["_RANK"] = bc1.groupby(colunas_chave).cumcount()

    merged = bc2.merge(bc1, on=colunas_chave + ["_RANK"], how="inner")
    return dict(zip(merged["_IDX_BC2"], merged["_IDX_BC1"]))


def _match_fuzzy_por_nota(df_bc2: pd.DataFrame, df_bc1: pd.DataFrame) -> dict:
    """Similaridade de texto entre a descrição do produto no XML e no SPED,
    calculada em LOTE por nota (rapidfuzz.process.cdist) — o laço Python é
    por CHV_NFE (nota), não por item. Dentro de cada nota, faz atribuição
    gulosa (maior score primeiro) para não usar o mesmo item da BC1 duas
    vezes. Devolve {indice_bc2: (indice_bc1, score)}."""
    if df_bc2.empty or df_bc1.empty:
        return {}

    grupos_bc1 = {chv: grp for chv, grp in df_bc1.groupby("CHV_NFE")}
    correspondencias: dict = {}

    for chv, grupo_bc2 in df_bc2.groupby("CHV_NFE"):
        grupo_bc1 = grupos_bc1.get(chv)
        if grupo_bc1 is None or grupo_bc1.empty:
            continue

        descricoes_bc2 = grupo_bc2[_COL_DESCR_XML].astype(str).tolist()
        descricoes_bc1 = grupo_bc1["DESCR_ITEM"].astype(str).tolist()

        matriz = process.cdist(descricoes_bc2, descricoes_bc1, scorer=fuzz.token_sort_ratio) / 100.0

        acima_limiar = np.argwhere(matriz > LIMIAR_SIMILARIDADE)
        if acima_limiar.size == 0:
            continue
        scores = matriz[acima_limiar[:, 0], acima_limiar[:, 1]]
        ordem = np.argsort(-scores)  # maior score primeiro

        usados_i, usados_j = set(), set()
        idx_bc2_grupo = grupo_bc2.index
        idx_bc1_grupo = grupo_bc1.index
        for pos in ordem:
            i, j = acima_limiar[pos]
            if i in usados_i or j in usados_j:
                continue
            correspondencias[idx_bc2_grupo[i]] = (idx_bc1_grupo[j], float(scores[pos]))
            usados_i.add(i)
            usados_j.add(j)

    return correspondencias


def executar_matching() -> "tuple[pd.DataFrame, dict]":
    """Executa o cruzamento BC2 (XML, ET) x BC1 (SPED) e devolve a BC3: uma
    linha por item da BC2, com DESCR_ITEM_DECLARACAO/COD_ITEM_DECLARACAO
    trazidos do BC1 quando houver correspondência (por qualquer um dos
    critérios), 'nd' quando a nota inteira não estiver declarada, ou 'nm'
    quando a nota existir mas o item não bater por nenhum critério."""
    df_bc2, meta_bc2 = loader.montar_bc2()
    df_bc1, meta_bc1 = loader.load_declaracao_entradas_terceiros()

    erros = list(meta_bc2.get("erros", [])) + list(meta_bc1.get("erros", []))
    if df_bc2.empty or df_bc1.empty:
        meta = {"origem_dados": "BC3", "erros": erros, "total_linhas": 0}
        return pd.DataFrame(), meta

    df_bc2 = df_bc2.reset_index(drop=True)
    df_bc1 = df_bc1.reset_index(drop=True)

    df_bc2 = df_bc2.assign(_VAL=_arredondar_valor(df_bc2["VL_ITEM"]))
    df_bc1 = df_bc1.assign(_VAL=_arredondar_valor(df_bc1["VL_ITEM"]))

    # ── 1. Match Principal: CHV_NFE + VL_ITEM ───────────────────────────────
    match_principal = _match_exato_vetorizado(df_bc2, df_bc1, ["CHV_NFE", "_VAL"])
    indices_bc1_usados = set(match_principal.values())

    pendentes_idx = df_bc2.index.difference(pd.Index(match_principal.keys()))
    df_bc2_pend = df_bc2.loc[pendentes_idx]
    df_bc1_disp = df_bc1.loc[~df_bc1.index.isin(indices_bc1_usados)]

    # ── 2. Match Secundário: similaridade de texto (por nota, em lote) ──────
    # Passo de GTIN/EAN (COD_BARRA) suspenso — o fallback do Principal vai
    # direto para o Fuzzy.
    match_fuzzy = _match_fuzzy_por_nota(df_bc2_pend, df_bc1_disp)

    # ── Monta a BC3 vetorizadamente (sem laço por linha) ────────────────────
    df_bc3 = df_bc2.drop(columns=["_VAL"]).copy()
    chaves_declaradas = set(df_bc1["CHV_NFE"])
    nao_declarado = ~df_bc3["CHV_NFE"].isin(chaves_declaradas)

    df_bc3["MATCH_TIPO"] = np.where(nao_declarado, "ND", "NM")
    df_bc3["MATCH_SCORE"] = 0.0
    df_bc3["DESCR_ITEM_DECLARACAO"] = np.where(nao_declarado, "nd", "nm")
    df_bc3["COD_ITEM_DECLARACAO"]   = np.where(nao_declarado, "nd", "nm")

    def _aplicar(mapa_idx_bc1: dict, tipo: str, scores: dict = None):
        if not mapa_idx_bc1:
            return
        idxs_bc2 = list(mapa_idx_bc1.keys())
        idxs_bc1 = list(mapa_idx_bc1.values())
        df_bc3.loc[idxs_bc2, "MATCH_TIPO"]  = tipo
        df_bc3.loc[idxs_bc2, "MATCH_SCORE"] = 1.0 if scores is None else [round(scores[i], 4) for i in idxs_bc2]
        df_bc3.loc[idxs_bc2, "DESCR_ITEM_DECLARACAO"] = df_bc1.loc[idxs_bc1, "DESCR_ITEM"].values
        df_bc3.loc[idxs_bc2, "COD_ITEM_DECLARACAO"]   = df_bc1.loc[idxs_bc1, "COD_ITEM"].values

    _aplicar(match_principal, "PRINCIPAL_VALOR")
    _aplicar(
        {k: v[0] for k, v in match_fuzzy.items()}, "SECUNDARIO_FUZZY",
        scores={k: v[1] for k, v in match_fuzzy.items()},
    )

    contagem_tipo = df_bc3["MATCH_TIPO"].value_counts().to_dict()
    meta = {
        "origem_dados": "BC3",
        "total_linhas": len(df_bc3),
        "erros": erros,
        "match_principal": contagem_tipo.get("PRINCIPAL_VALOR", 0),
        "match_secundario_fuzzy": contagem_tipo.get("SECUNDARIO_FUZZY", 0),
        "nao_declarado": contagem_tipo.get("ND", 0),   # chave inteira ausente do SPED
        "sem_match_item": contagem_tipo.get("NM", 0),  # chave declarada, item nao casado
    }
    return df_bc3, meta
