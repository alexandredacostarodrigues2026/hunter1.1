"""Cálculo de score de correspondência entre produtos (rapidfuzz)."""
import sys
from pathlib import Path

_APP_DIR = Path(__file__).parent
if str(_APP_DIR) not in sys.path:
    sys.path.insert(0, str(_APP_DIR))

import numpy as np
import pandas as pd
from rapidfuzz import fuzz, process


def matriz_similaridade(descricoes_a: list, descricoes_b: list) -> np.ndarray:
    """Calcula, em lote (rapidfuzz.process.cdist, implementado em C), a matriz
    de similaridade (0 a 1) entre duas listas de descrições — usada pelo
    Matching (Etapa 1, matching.py) para comparar de uma vez todos os itens de
    uma nota, sem laço item a item."""
    return process.cdist(descricoes_a, descricoes_b, scorer=fuzz.token_sort_ratio) / 100.0


def similaridade(a: str, b: str) -> float:
    """Similaridade normalizada entre 0 e 1 entre duas strings (rapidfuzz
    token_sort_ratio — tolera palavras fora de ordem, ex.: "ARROZ TIO JOAO 5KG"
    vs "TIO JOAO ARROZ 5KG")."""
    a, b = str(a or "").strip(), str(b or "").strip()
    if not a or not b:
        return 0.0
    return fuzz.token_sort_ratio(a, b) / 100.0


def melhor_similaridade(referencia: str, candidatos: pd.Series):
    """Compara 'referencia' contra cada valor de 'candidatos' (Series de
    strings) e devolve (indice, score) do mais parecido. Devolve (None, 0.0)
    se 'candidatos' estiver vazia."""
    if candidatos.empty:
        return None, 0.0
    scores = candidatos.apply(lambda valor: similaridade(referencia, valor))
    idx_melhor = scores.idxmax()
    return idx_melhor, float(scores.loc[idx_melhor])
