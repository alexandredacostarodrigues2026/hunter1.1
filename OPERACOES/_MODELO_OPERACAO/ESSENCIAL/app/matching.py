"""Motor de Matching (Etapa 1): cruza a BC2 (XML — itens de Emissão de
Terceiros) com a BC1 (SPED — sped_entradas_terceiros) para produzir a BC3
(resultado do cruzamento), sem depender de NUM_ITEM como chave — a ordem
sequencial dos itens no XML do fornecedor não necessariamente bate com a
ordem de escrituração no SPED do declarante.

Matching em dois níveis, sempre dentro da MESMA CHV_NFE (cada nível só
tenta casar o que sobrou do anterior):
  - Tipo 1: mesmo EAN/GTIN (COD_BARRA do SPED == cean do XML, comparados após
    normalização — ver _normalizar_gtin) **e** similaridade de descrição
    (xprod x DESCR_ITEM) > LIMIAR_TIPO1 (0,90).
  - Tipo 2 (fallback): para os itens que não casaram no Tipo 1, mesmo Valor
    Total (VL_ITEM idêntico) **e** similaridade de descrição > LIMIAR_TIPO2
    (0,60).

Não Declarados e Não Matches:
  - 'nd' (Não Declarado) — a CHV_NFE inteira não aparece na BC1.
  - 'nm' (Não Match) — a CHV_NFE existe na BC1, mas o item não passou nem no
    Tipo 1 nem no Tipo 2.

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

_COL_DESCR_XML = "fatoitemnfe_infnfe_det_prod_xprod"
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

        val_bc2 = pd.to_numeric(grupo_bc2["VL_ITEM"], errors="coerce").round(2).to_numpy()
        val_bc1 = pd.to_numeric(grupo_bc1["VL_ITEM"], errors="coerce").round(2).to_numpy()
        mask_valor = val_bc2[:, None] == val_bc1[None, :]

        mask_final = (matriz > LIMIAR_TIPO2) & mask_valor
        correspondencias.update(
            _atribuir_1_para_1(mask_final, matriz, grupo_bc2.index, grupo_bc1.index)
        )

    return correspondencias


def executar_matching() -> "tuple[pd.DataFrame, dict]":
    """Executa o cruzamento BC2 (XML, ET) x BC1 (SPED) em dois níveis e
    devolve a BC3: uma linha por item da BC2, com DESCR_ITEM_DECLARACAO/
    COD_ITEM_DECLARACAO trazidos do BC1 quando houver correspondência
    (Tipo 1 ou Tipo 2), 'nd' quando a CHV_NFE não estiver declarada, ou 'nm'
    quando a CHV_NFE existir mas o item não passar em nenhum dos dois tipos."""
    df_bc2, meta_bc2 = loader.montar_bc2()
    df_bc1, meta_bc1 = loader.load_declaracao_entradas_terceiros()

    erros = list(meta_bc2.get("erros", [])) + list(meta_bc1.get("erros", []))
    if df_bc2.empty or df_bc1.empty:
        meta = {"origem_dados": "BC3", "erros": erros, "total_linhas": 0}
        return pd.DataFrame(), meta

    df_bc2 = df_bc2.reset_index(drop=True)
    df_bc1 = df_bc1.reset_index(drop=True)

    # ── Tipo 1: GTIN + similaridade > 0,90 ──────────────────────────────────
    match_tipo1 = _match_tipo1_por_nota(df_bc2, df_bc1)
    indices_bc1_usados = {v[0] for v in match_tipo1.values()}

    pendentes_idx = df_bc2.index.difference(pd.Index(match_tipo1.keys()))
    df_bc2_pend = df_bc2.loc[pendentes_idx]
    df_bc1_disp = df_bc1.loc[~df_bc1.index.isin(indices_bc1_usados)]

    # ── Tipo 2 (fallback): Valor + similaridade > 0,60 ──────────────────────
    match_tipo2 = _match_tipo2_por_nota(df_bc2_pend, df_bc1_disp)

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

    contagem_tipo = df_bc3["MATCH_TIPO"].value_counts().to_dict()
    meta = {
        "origem_dados": "BC3",
        "total_linhas": len(df_bc3),
        "erros": erros,
        "match_tipo1": contagem_tipo.get("TIPO_1", 0),
        "match_tipo2": contagem_tipo.get("TIPO_2", 0),
        "nao_declarado": contagem_tipo.get("ND", 0),   # chave inteira ausente do SPED
        "sem_match_item": contagem_tipo.get("NM", 0),  # chave declarada, item nao casou em nenhum tipo
    }
    return df_bc3, meta
