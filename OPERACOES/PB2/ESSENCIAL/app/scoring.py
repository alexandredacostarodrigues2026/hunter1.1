"""Cálculo de score de correspondência entre produtos (rapidfuzz)."""
import sys
from pathlib import Path

_APP_DIR = Path(__file__).parent
if str(_APP_DIR) not in sys.path:
    sys.path.insert(0, str(_APP_DIR))

import pandas as pd
from rapidfuzz import fuzz


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
