"""Motor de Matching (Etapa 1): cruza a BC2 (XML — itens de Emissão de
Terceiros) com a BC1 (SPED — sped_entradas_terceiros) para produzir a BC3
(resultado do cruzamento), sem depender de NUM_ITEM como chave — a ordem
sequencial dos itens no XML do fornecedor não necessariamente bate com a
ordem de escrituração no SPED do declarante.

Regra de elegibilidade + match único (correspondência por valor removida):
  1. Elegibilidade por nota: só se tenta casar os itens de uma CHV_NFE
     quando a quantidade de linhas (itens) da BC2 para aquela nota é IGUAL
     à quantidade de linhas da BC1 para a mesma nota. Se as quantidades
     forem diferentes, nenhum item daquela nota é comparado — todos ficam
     como 'nm' (a nota existe na declaração, mas a correspondência item a
     item não é tentada por divergência na quantidade de linhas).
  2. Match (Fuzzy) — dentro das notas elegíveis, similaridade de texto
     (produto do XML x DESCR_ITEM do SPED), sugerido quando score >
     LIMIAR_SIMILARIDADE.
  3. Sem match — duas situações distintas:
     a. 'nd' (não declarado) — a CHV_NFE inteira não aparece na BC1: a nota
        de compra não foi encontrada na declaração (possível compra não
        declarada, não é só um item sem match).
     b. 'nm' (não match) — a CHV_NFE existe na BC1, mas a nota não é
        elegível (quantidade de linhas diferente) ou o item não bateu a
        similaridade de texto.

ID_UNICO (já presente em BC1 e BC2) segue existindo só para rastreabilidade
interna — não é usado como chave de ligação.

Implementação vetorizada (sem .iterrows()/.apply() linha a linha) para
escalar a operações com milhões de itens:
  - Elegibilidade por nota: contagem de itens por CHV_NFE em cada lado
    (groupby().size(), vetorizado) comparada de uma vez (join de Series).
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

LIMIAR_SIMILARIDADE = 0.50

_COL_DESCR_XML = "fatoitemnfe_infnfe_det_prod_xprod"


def _chaves_com_mesma_quantidade_de_linhas(df_bc2: pd.DataFrame, df_bc1: pd.DataFrame) -> set:
    """Compara, por CHV_NFE, a quantidade de itens da BC2 com a quantidade
    de itens da BC1 — devolve o conjunto de chaves onde as quantidades são
    iguais (únicas elegíveis para tentar o match por nota)."""
    contagem_bc2 = df_bc2.groupby("CHV_NFE").size()
    contagem_bc1 = df_bc1.groupby("CHV_NFE").size()
    comparacao = pd.DataFrame({"bc2": contagem_bc2, "bc1": contagem_bc1}).dropna()
    return set(comparacao[comparacao["bc2"] == comparacao["bc1"]].index)


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
    trazidos do BC1 quando houver correspondência por similaridade de texto
    (só tentada em notas com a mesma quantidade de itens nos dois lados),
    'nd' quando a nota inteira não estiver declarada, ou 'nm' quando a nota
    existir mas não for elegível ou o item não bater a similaridade."""
    df_bc2, meta_bc2 = loader.montar_bc2()
    df_bc1, meta_bc1 = loader.load_declaracao_entradas_terceiros()

    erros = list(meta_bc2.get("erros", [])) + list(meta_bc1.get("erros", []))
    if df_bc2.empty or df_bc1.empty:
        meta = {"origem_dados": "BC3", "erros": erros, "total_linhas": 0}
        return pd.DataFrame(), meta

    df_bc2 = df_bc2.reset_index(drop=True)
    df_bc1 = df_bc1.reset_index(drop=True)

    # ── Elegibilidade: só notas com a MESMA quantidade de linhas nos dois lados ──
    chaves_elegiveis = _chaves_com_mesma_quantidade_de_linhas(df_bc2, df_bc1)
    df_bc2_elegivel = df_bc2[df_bc2["CHV_NFE"].isin(chaves_elegiveis)]
    df_bc1_elegivel = df_bc1[df_bc1["CHV_NFE"].isin(chaves_elegiveis)]

    # ── Match (Fuzzy): similaridade de texto, só dentro das notas elegíveis ──
    match_fuzzy = _match_fuzzy_por_nota(df_bc2_elegivel, df_bc1_elegivel)

    # ── Monta a BC3 vetorizadamente (sem laço por linha) ────────────────────
    df_bc3 = df_bc2.copy()
    chaves_declaradas = set(df_bc1["CHV_NFE"])
    nao_declarado = ~df_bc3["CHV_NFE"].isin(chaves_declaradas)

    df_bc3["MATCH_TIPO"] = np.where(nao_declarado, "ND", "NM")
    df_bc3["MATCH_SCORE"] = 0.0
    df_bc3["DESCR_ITEM_DECLARACAO"] = np.where(nao_declarado, "nd", "nm")
    df_bc3["COD_ITEM_DECLARACAO"]   = np.where(nao_declarado, "nd", "nm")

    def _aplicar(mapa_idx_bc1: dict, tipo: str, scores: dict):
        if not mapa_idx_bc1:
            return
        idxs_bc2 = list(mapa_idx_bc1.keys())
        idxs_bc1 = list(mapa_idx_bc1.values())
        df_bc3.loc[idxs_bc2, "MATCH_TIPO"]  = tipo
        df_bc3.loc[idxs_bc2, "MATCH_SCORE"] = [round(scores[i], 4) for i in idxs_bc2]
        df_bc3.loc[idxs_bc2, "DESCR_ITEM_DECLARACAO"] = df_bc1.loc[idxs_bc1, "DESCR_ITEM"].values
        df_bc3.loc[idxs_bc2, "COD_ITEM_DECLARACAO"]   = df_bc1.loc[idxs_bc1, "COD_ITEM"].values

    _aplicar(
        {k: v[0] for k, v in match_fuzzy.items()}, "SECUNDARIO_FUZZY",
        scores={k: v[1] for k, v in match_fuzzy.items()},
    )

    contagem_tipo = df_bc3["MATCH_TIPO"].value_counts().to_dict()
    meta = {
        "origem_dados": "BC3",
        "total_linhas": len(df_bc3),
        "erros": erros,
        "match_secundario_fuzzy": contagem_tipo.get("SECUNDARIO_FUZZY", 0),
        "nao_declarado": contagem_tipo.get("ND", 0),   # chave inteira ausente do SPED
        "sem_match_item": contagem_tipo.get("NM", 0),  # chave declarada mas nao elegivel/nao casada
    }
    return df_bc3, meta
