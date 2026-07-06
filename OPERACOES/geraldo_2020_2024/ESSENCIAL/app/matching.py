"""Motor de Matching (Etapa 1): cruza a BC2 (XML — itens de Emissão de
Terceiros) com a BC1 (SPED — sped_entradas_terceiros) para produzir a BC3
(resultado do cruzamento), sem depender de NUM_ITEM como chave — a ordem
sequencial dos itens no XML do fornecedor não necessariamente bate com a
ordem de escrituração no SPED do declarante.

Critério Primário — dentro da MESMA CHV_NFE, são candidatos todos os itens
do SPED cuja descrição (DESCR_ITEM) tenha similaridade de texto com a
descrição do XML (xprod) acima de LIMIAR_SIMILARIDADE (0,60).

Lógica de Desempate — quando um item do XML tem mais de um candidato acima
do limiar, o candidato escolhido é decidido nesta ordem de prioridade:
  1. Mesmo EAN/GTIN (COD_BARRA do SPED == cean do XML).
  2. Mesmo Valor Total do item (VL_ITEM).
  3. Maior score de similaridade (critério de desempate final).

Consistência de Unicidade — um item da BC1 (declaração) não pode ser usado
em mais de um match na mesma execução (1 para 1).

Classificação da BC3:
  - Match concluído (mesmo por desempate) -> traz DESCR_ITEM/COD_ITEM do SPED.
  - CHV_NFE não existe na BC1 -> 'nd' (Não Declarado).
  - CHV_NFE existe, mas nenhum item atinge similaridade > LIMIAR_SIMILARIDADE
    -> 'nm' (Não Match).

ID_UNICO (já presente em BC1 e BC2) segue existindo só para rastreabilidade
interna — não é usado como chave de ligação. Regra Operacional R07: as
colunas de ligação (CHV_NFE, COD_ITEM, NUM_ITEM, CFOP) continuam com
dtype=str — os campos numéricos (VL_ITEM) só são convertidos internamente,
em memória, para fins de comparação no desempate, sem alterar o tipo da
coluna persistida.

Implementação vetorizada (sem .iterrows()/.apply() linha a linha) para
escalar a operações com milhões de itens: agrupado por CHV_NFE, com a
matriz de similaridade calculada em lote por nota (rapidfuzz.process.cdist,
implementado em C) — o laço em Python passa a ser por NOTA, não por ITEM
(uma nota típica tem poucos itens; milhões de itens tendem a virar "só"
dezenas/centenas de milhares de notas). O desempate (GTIN/valor/score) é
resolvido com um np.lexsort vetorizado sobre todos os pares candidatos da
nota, não com laços aninhados.
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

LIMIAR_SIMILARIDADE = 0.60

_COL_DESCR_XML = "fatoitemnfe_infnfe_det_prod_xprod"
_SEM_GTIN = {"", "SEM GTIN", "NAN", "NONE"}


def _match_por_nota(df_bc2: pd.DataFrame, df_bc1: pd.DataFrame) -> dict:
    """Para cada CHV_NFE, considera candidatos todos os itens do SPED com
    similaridade de descrição > LIMIAR_SIMILARIDADE. Quando um item do XML
    tem mais de um candidato acima do limiar, desempata por (1) mesmo
    GTIN/EAN, (2) mesmo Valor Total, (3) maior score — nessa ordem de
    prioridade. Um item da BC1 só pode ser usado em um match. Devolve
    {indice_bc2: (indice_bc1, score)}."""
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
        linhas_i, linhas_j = acima_limiar[:, 0], acima_limiar[:, 1]
        scores = matriz[linhas_i, linhas_j]

        # Chaves de desempate, vetorizadas sobre todos os pares candidatos da nota
        gtin_bc2 = grupo_bc2["COD_BARRA"].astype(str).str.strip().str.upper().to_numpy()
        gtin_bc1 = grupo_bc1["COD_BARRA"].astype(str).str.strip().str.upper().to_numpy()
        val_bc2 = pd.to_numeric(grupo_bc2["VL_ITEM"], errors="coerce").round(2).to_numpy()
        val_bc1 = pd.to_numeric(grupo_bc1["VL_ITEM"], errors="coerce").round(2).to_numpy()

        gtin_i = gtin_bc2[linhas_i]
        gtin_valido = ~np.isin(gtin_i, list(_SEM_GTIN))
        gtin_bate = gtin_valido & (gtin_i == gtin_bc1[linhas_j])
        valor_bate = val_bc2[linhas_i] == val_bc1[linhas_j]

        # lexsort: a ULTIMA chave é a de maior prioridade -> ordem de
        # prioridade (crescente): score, valor_bate, gtin_bate. Tudo
        # decrescente (negativo) para os "melhores" pares virem primeiro.
        ordem = np.lexsort((-scores, -valor_bate.astype(int), -gtin_bate.astype(int)))

        usados_i, usados_j = set(), set()
        idx_bc2_grupo = grupo_bc2.index
        idx_bc1_grupo = grupo_bc1.index
        for pos in ordem:
            i, j = linhas_i[pos], linhas_j[pos]
            if i in usados_i or j in usados_j:
                continue
            correspondencias[idx_bc2_grupo[i]] = (idx_bc1_grupo[j], float(scores[pos]))
            usados_i.add(i)
            usados_j.add(j)

    return correspondencias


def executar_matching() -> "tuple[pd.DataFrame, dict]":
    """Executa o cruzamento BC2 (XML, ET) x BC1 (SPED) e devolve a BC3: uma
    linha por item da BC2, com DESCR_ITEM_DECLARACAO/COD_ITEM_DECLARACAO
    trazidos do BC1 quando houver correspondência (similaridade > 0,60,
    com desempate por GTIN/Valor/score), 'nd' quando a CHV_NFE não estiver
    declarada, ou 'nm' quando a CHV_NFE existir mas nenhum item atingir o
    limiar de similaridade."""
    df_bc2, meta_bc2 = loader.montar_bc2()
    df_bc1, meta_bc1 = loader.load_declaracao_entradas_terceiros()

    erros = list(meta_bc2.get("erros", [])) + list(meta_bc1.get("erros", []))
    if df_bc2.empty or df_bc1.empty:
        meta = {"origem_dados": "BC3", "erros": erros, "total_linhas": 0}
        return pd.DataFrame(), meta

    df_bc2 = df_bc2.reset_index(drop=True)
    df_bc1 = df_bc1.reset_index(drop=True)

    match = _match_por_nota(df_bc2, df_bc1)

    # ── Monta a BC3 vetorizadamente (sem laço por linha) ────────────────────
    df_bc3 = df_bc2.copy()
    chaves_declaradas = set(df_bc1["CHV_NFE"])
    nao_declarado = ~df_bc3["CHV_NFE"].isin(chaves_declaradas)

    df_bc3["MATCH_TIPO"] = np.where(nao_declarado, "ND", "NM")
    df_bc3["MATCH_SCORE"] = 0.0
    df_bc3["DESCR_ITEM_DECLARACAO"] = np.where(nao_declarado, "nd", "nm")
    df_bc3["COD_ITEM_DECLARACAO"]   = np.where(nao_declarado, "nd", "nm")

    if match:
        idxs_bc2 = list(match.keys())
        idxs_bc1 = [v[0] for v in match.values()]
        scores   = [v[1] for v in match.values()]
        df_bc3.loc[idxs_bc2, "MATCH_TIPO"]  = "SECUNDARIO_FUZZY"
        df_bc3.loc[idxs_bc2, "MATCH_SCORE"] = [round(s, 4) for s in scores]
        df_bc3.loc[idxs_bc2, "DESCR_ITEM_DECLARACAO"] = df_bc1.loc[idxs_bc1, "DESCR_ITEM"].values
        df_bc3.loc[idxs_bc2, "COD_ITEM_DECLARACAO"]   = df_bc1.loc[idxs_bc1, "COD_ITEM"].values

    contagem_tipo = df_bc3["MATCH_TIPO"].value_counts().to_dict()
    meta = {
        "origem_dados": "BC3",
        "total_linhas": len(df_bc3),
        "erros": erros,
        "match_secundario_fuzzy": contagem_tipo.get("SECUNDARIO_FUZZY", 0),
        "nao_declarado": contagem_tipo.get("ND", 0),   # chave inteira ausente do SPED
        "sem_match_item": contagem_tipo.get("NM", 0),  # chave declarada, nenhum item acima do limiar
    }
    return df_bc3, meta
