"""Motor de Matching (Etapa 1): cruza a BC2 (XML — itens de Emissão de
Terceiros) com a BC1 (SPED — sped_entradas_terceiros) para produzir a BC3
(resultado do cruzamento), sem depender de NUM_ITEM como chave — a ordem
sequencial dos itens no XML do fornecedor não necessariamente bate com a
ordem de escrituração no SPED do declarante.

Hierarquia de chaves (cada nível só tenta casar o que sobrou do anterior):
  1. Match Principal — CHV_NFE + VL_ITEM (valor exato, arredondado a 2 casas).
  2. Match Secundário — dentro da MESMA CHV_NFE:
     a. COD_BARRA (GTIN/EAN) exato.
     b. Similaridade de texto (produto do XML x DESCR_ITEM do SPED),
        sugerido quando score > LIMIAR_SIMILARIDADE.
  3. Sem match em nenhum critério — duas situações distintas:
     a. 'nd' (não declarado) — a CHV_NFE inteira não aparece na BC1: a nota
        de compra não foi encontrada na declaração (possível compra não
        declarada, não é só um item sem match).
     b. 'nm' (não match) — a CHV_NFE existe na BC1, mas este item específico
        não bateu por nenhum dos critérios (valor, GTIN, similaridade).

ID_UNICO (já presente em BC1 e BC2) segue existindo só para rastreabilidade
interna — não é usado como chave de ligação.
"""
import sys
from pathlib import Path

_APP_DIR = Path(__file__).parent
if str(_APP_DIR) not in sys.path:
    sys.path.insert(0, str(_APP_DIR))

import pandas as pd

import loader
import scoring

LIMIAR_SIMILARIDADE = 0.85

_COL_DESCR_XML = "fatoitemnfe_infnfe_det_prod_xprod"
_SEM_GTIN = {"", "SEM GTIN", "NAN", "NONE"}


def _arredondar_valor(serie: pd.Series) -> pd.Series:
    return pd.to_numeric(serie, errors="coerce").round(2)


def _match_principal(df_bc2: pd.DataFrame, df_bc1: pd.DataFrame) -> dict:
    """Match exato por (CHV_NFE, VL_ITEM arredondado) — 1 para 1: cada linha
    do BC1 só pode ser usada em uma correspondência. Devolve
    {indice_bc2: indice_bc1}."""
    valores_bc1 = _arredondar_valor(df_bc1["VL_ITEM"])
    disponiveis: dict = {}
    for idx_bc1, chv in df_bc1["CHV_NFE"].items():
        disponiveis.setdefault((chv, valores_bc1.loc[idx_bc1]), []).append(idx_bc1)

    valores_bc2 = _arredondar_valor(df_bc2["VL_ITEM"])
    correspondencias = {}
    for idx_bc2, chv in df_bc2["CHV_NFE"].items():
        candidatos = disponiveis.get((chv, valores_bc2.loc[idx_bc2]))
        if candidatos:
            correspondencias[idx_bc2] = candidatos.pop(0)
    return correspondencias


def _match_secundario(
    df_bc2: pd.DataFrame, df_bc1: pd.DataFrame,
    indices_bc2_pendentes: list, indices_bc1_usados: set,
) -> dict:
    """Para os itens do BC2 que não casaram no match principal, tenta,
    dentro da MESMA chave de acesso: (a) COD_BARRA exato; (b) similaridade
    de texto (produto do XML x DESCR_ITEM do SPED) acima do limiar. Devolve
    {indice_bc2: (indice_bc1, tipo_match, score)}."""
    disponiveis_por_chave: dict = {}
    for idx_bc1, chv in df_bc1["CHV_NFE"].items():
        if idx_bc1 in indices_bc1_usados:
            continue
        disponiveis_por_chave.setdefault(chv, []).append(idx_bc1)

    correspondencias = {}
    for idx_bc2 in indices_bc2_pendentes:
        row_bc2 = df_bc2.loc[idx_bc2]
        candidatos_idx = [
            i for i in disponiveis_por_chave.get(row_bc2["CHV_NFE"], [])
            if i not in indices_bc1_usados
        ]
        if not candidatos_idx:
            continue
        candidatos = df_bc1.loc[candidatos_idx]

        # (a) GTIN/EAN exato
        cod_barra_bc2 = str(row_bc2.get("COD_BARRA", "")).strip().upper()
        if cod_barra_bc2 not in _SEM_GTIN:
            iguais = candidatos[candidatos["COD_BARRA"].astype(str).str.strip().str.upper() == cod_barra_bc2]
            if not iguais.empty:
                escolhido = iguais.index[0]
                correspondencias[idx_bc2] = (escolhido, "SECUNDARIO_GTIN", 1.0)
                indices_bc1_usados.add(escolhido)
                continue

        # (b) similaridade de texto
        descricao_bc2 = row_bc2.get(_COL_DESCR_XML, "")
        idx_melhor, score = scoring.melhor_similaridade(descricao_bc2, candidatos["DESCR_ITEM"].astype(str))
        if idx_melhor is not None and score > LIMIAR_SIMILARIDADE:
            correspondencias[idx_bc2] = (idx_melhor, "SECUNDARIO_FUZZY", score)
            indices_bc1_usados.add(idx_melhor)

    return correspondencias


def executar_matching() -> "tuple[pd.DataFrame, dict]":
    """Executa o cruzamento BC2 (XML, ET) x BC1 (SPED) e devolve a BC3: uma
    linha por item da BC2, com DESCR_ITEM_DECLARACAO/COD_ITEM_DECLARACAO
    trazidos do BC1 quando houver correspondência (por qualquer um dos
    critérios) ou 'nd' quando não houver nenhuma."""
    df_bc2, meta_bc2 = loader.montar_bc2()
    df_bc1, meta_bc1 = loader.load_declaracao_entradas_terceiros()

    erros = list(meta_bc2.get("erros", [])) + list(meta_bc1.get("erros", []))
    if df_bc2.empty or df_bc1.empty:
        meta = {"origem_dados": "BC3", "erros": erros, "total_linhas": 0}
        return pd.DataFrame(), meta

    df_bc2 = df_bc2.reset_index(drop=True)
    df_bc1 = df_bc1.reset_index(drop=True)

    match_principal = _match_principal(df_bc2, df_bc1)
    indices_bc1_usados = set(match_principal.values())
    pendentes = [i for i in df_bc2.index if i not in match_principal]
    match_secundario = _match_secundario(df_bc2, df_bc1, pendentes, indices_bc1_usados)
    chaves_declaradas = set(df_bc1["CHV_NFE"])

    linhas = []
    for idx_bc2, row_bc2 in df_bc2.iterrows():
        linha = row_bc2.to_dict()
        if idx_bc2 in match_principal:
            idx_bc1 = match_principal[idx_bc2]
            linha["MATCH_TIPO"]  = "PRINCIPAL_VALOR"
            linha["MATCH_SCORE"] = 1.0
            linha["DESCR_ITEM_DECLARACAO"] = df_bc1.at[idx_bc1, "DESCR_ITEM"]
            linha["COD_ITEM_DECLARACAO"]   = df_bc1.at[idx_bc1, "COD_ITEM"]
        elif idx_bc2 in match_secundario:
            idx_bc1, tipo, score = match_secundario[idx_bc2]
            linha["MATCH_TIPO"]  = tipo
            linha["MATCH_SCORE"] = round(score, 4)
            linha["DESCR_ITEM_DECLARACAO"] = df_bc1.at[idx_bc1, "DESCR_ITEM"]
            linha["COD_ITEM_DECLARACAO"]   = df_bc1.at[idx_bc1, "COD_ITEM"]
        elif row_bc2["CHV_NFE"] not in chaves_declaradas:
            # a chave de acesso inteira não aparece na declaração (SPED) —
            # possível compra não declarada, não é só um item sem match.
            linha["MATCH_TIPO"]  = "ND"
            linha["MATCH_SCORE"] = 0.0
            linha["DESCR_ITEM_DECLARACAO"] = "nd"
            linha["COD_ITEM_DECLARACAO"]   = "nd"
        else:
            # a nota existe na declaração, mas este item específico não bateu
            # por nenhum dos critérios (valor, GTIN, similaridade de texto).
            linha["MATCH_TIPO"]  = "NM"
            linha["MATCH_SCORE"] = 0.0
            linha["DESCR_ITEM_DECLARACAO"] = "nm"
            linha["COD_ITEM_DECLARACAO"]   = "nm"
        linhas.append(linha)

    df_bc3 = pd.DataFrame(linhas)
    contagem_tipo = df_bc3["MATCH_TIPO"].value_counts().to_dict()

    meta = {
        "origem_dados": "BC3",
        "total_linhas": len(df_bc3),
        "erros": erros,
        "match_principal": contagem_tipo.get("PRINCIPAL_VALOR", 0),
        "match_secundario_gtin": contagem_tipo.get("SECUNDARIO_GTIN", 0),
        "match_secundario_fuzzy": contagem_tipo.get("SECUNDARIO_FUZZY", 0),
        "nao_declarado": contagem_tipo.get("ND", 0),   # chave inteira ausente do SPED
        "sem_match_item": contagem_tipo.get("NM", 0),  # chave declarada, item nao casado
    }
    return df_bc3, meta
