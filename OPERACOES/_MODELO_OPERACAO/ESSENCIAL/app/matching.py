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
do anterior; ordem de execução: D1 → D2 → A1 → A2 → A3 → A4 → A5 → D3 → D4.

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
  - D3 (integridade de nota): para os itens que ainda sobraram 'nd'/'nm'
    após o A5, restringe às CHV_NFE onde a nota é "íntegra" — mesma
    contagem de itens **e** mesmo somatório de VL_ITEM entre o lado XML (BC2)
    e o lado SPED (BC1), ver _integridade_por_nota — e casa, só dentro
    dessas notas, por similaridade de descrição normalizada > LIMIAR_D3
    (0,70), 1-para-1. Ver _match_d3_por_nota.
  - D4 (último recurso): para os itens que ainda sobraram 'nd'/'nm' após
    o D3, casa dentro da mesma CHV_NFE só por similaridade de descrição
    normalizada > LIMIAR_D4 (0,70), 1-para-1, sem exigir GTIN, valor ou
    integridade de nota. Ver _match_d4_por_nota.

Ordem avaliada e mantida (ver memoria/2026-07-09.md): mover D3/D4 pra antes
da família A piora o resultado (rebaixa itens de evidência forte — código
exato confirmado — pra evidência fraca — só similaridade — e em geraldo
chega a perder matches líquidos pela atribuição gulosa 1-para-1). D3/D4
vs A5 especificamente: testado e são mecanismos disjuntos na prática (zero
itens mudam de rótulo trocando a ordem entre eles).

Não Declarados e Não Matches (antes de A1/A2/A3/A4/A5/D3/D4):
  - 'nd' (Não Declarado) — a CHV_NFE inteira não aparece na BC1.
  - 'nm' (Não Match) — a CHV_NFE existe na BC1, mas o item não passou nem no
    D1 nem no D2.
Itens 'nd'/'nm' recuperados por A1, A2, A3, A4, A5, D3 ou D4 mudam de
status para 'A1'/'A2'/'A3'/'A4'/'A5'/'D3'/'D4'; os que não encontram
correspondência em nenhum deles mantêm 'ND'/'NM'.

Consistência de Unicidade — um item da BC1 (declaração) não pode ser
"consumido" por dois matches diferentes (1 para 1) — vale entre D1, D2, D3
e D4 (os que consomem uma linha específica da BC1). A família A é só lookup
histórico e não consome linha da BC1, não entra nessa exclusão.

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
import re
import sys
from pathlib import Path

_APP_DIR = Path(__file__).parent
if str(_APP_DIR) not in sys.path:
    sys.path.insert(0, str(_APP_DIR))

import numpy as np
import pandas as pd

import loader
import scoring

LIMIAR_D1 = 0.90  # mesmo GTIN/EAN + similaridade
LIMIAR_D2 = 0.60  # mesmo Valor Total + similaridade
LIMIAR_D3 = 0.70  # nota integra (mesma contagem/valor) + similaridade
LIMIAR_D4 = 0.70  # ultimo recurso: so similaridade, mesma chave

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
    de nota (D3)."""
    return pd.to_numeric(
        serie.astype(str).str.strip().str.replace(",", ".", regex=False),
        errors="coerce",
    )


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
        return pd.DataFrame(columns=["COD_ITEM_DECLARACAO", "DESCR_ITEM_DECLARACAO"])

    aprendizado = pd.DataFrame({
        "_CHAVE": _chave_a1(confirmados),
        "COD_ITEM_DECLARACAO": confirmados["COD_ITEM_DECLARACAO"].to_numpy(),
        "DESCR_ITEM_DECLARACAO": confirmados["DESCR_ITEM_DECLARACAO"].to_numpy(),
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
    achou = cod_encontrado.notna()
    if not achou.any():
        return 0

    idx_achou = achou[achou].index
    df_bc3.loc[idx_achou, "MATCH_TIPO"]            = "A1"
    df_bc3.loc[idx_achou, "COD_ITEM_DECLARACAO"]   = cod_encontrado.loc[idx_achou].values
    df_bc3.loc[idx_achou, "DESCR_ITEM_DECLARACAO"] = descr_encontrado.loc[idx_achou].values
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
        return pd.DataFrame(columns=["COD_ITEM_DECLARACAO", "DESCR_ITEM_DECLARACAO"])

    aprendizado = pd.DataFrame({
        "_CHAVE": _chave_a2(confirmados),
        "COD_ITEM_DECLARACAO": confirmados["COD_ITEM_DECLARACAO"].to_numpy(),
        "DESCR_ITEM_DECLARACAO": confirmados["DESCR_ITEM_DECLARACAO"].to_numpy(),
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
    achou = cod_encontrado.notna()
    if not achou.any():
        return 0

    idx_achou = achou[achou].index
    df_bc3.loc[idx_achou, "MATCH_TIPO"]            = "A2"
    df_bc3.loc[idx_achou, "COD_ITEM_DECLARACAO"]   = cod_encontrado.loc[idx_achou].values
    df_bc3.loc[idx_achou, "DESCR_ITEM_DECLARACAO"] = descr_encontrado.loc[idx_achou].values
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
        return pd.DataFrame(columns=["COD_ITEM_DECLARACAO", "DESCR_ITEM_DECLARACAO"])

    aprendizado = pd.DataFrame({
        "_CHAVE": _chave_a3(confirmados),
        "COD_ITEM_DECLARACAO": confirmados["COD_ITEM_DECLARACAO"].to_numpy(),
        "DESCR_ITEM_DECLARACAO": confirmados["DESCR_ITEM_DECLARACAO"].to_numpy(),
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
    achou = cod_encontrado.notna()
    if not achou.any():
        return 0

    idx_achou = achou[achou].index
    df_bc3.loc[idx_achou, "MATCH_TIPO"]            = "A3"
    df_bc3.loc[idx_achou, "COD_ITEM_DECLARACAO"]   = cod_encontrado.loc[idx_achou].values
    df_bc3.loc[idx_achou, "DESCR_ITEM_DECLARACAO"] = descr_encontrado.loc[idx_achou].values
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
        return pd.DataFrame(columns=["COD_ITEM_DECLARACAO", "DESCR_ITEM_DECLARACAO"])

    aprendizado = pd.DataFrame({
        "_CHAVE": _chave_a4(confirmados),
        "COD_ITEM_DECLARACAO": confirmados["COD_ITEM_DECLARACAO"].to_numpy(),
        "DESCR_ITEM_DECLARACAO": confirmados["DESCR_ITEM_DECLARACAO"].to_numpy(),
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
    achou = cod_encontrado.notna()
    if not achou.any():
        return 0

    idx_achou = achou[achou].index
    df_bc3.loc[idx_achou, "MATCH_TIPO"]            = "A4"
    df_bc3.loc[idx_achou, "COD_ITEM_DECLARACAO"]   = cod_encontrado.loc[idx_achou].values
    df_bc3.loc[idx_achou, "DESCR_ITEM_DECLARACAO"] = descr_encontrado.loc[idx_achou].values
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
        return pd.DataFrame(columns=["COD_ITEM_DECLARACAO", "DESCR_ITEM_DECLARACAO"])

    aprendizado = pd.DataFrame({
        "_CHAVE": _chave_a5(confirmados),
        "COD_ITEM_DECLARACAO": confirmados["COD_ITEM_DECLARACAO"].to_numpy(),
        "DESCR_ITEM_DECLARACAO": confirmados["DESCR_ITEM_DECLARACAO"].to_numpy(),
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
    achou = cod_encontrado.notna()
    if not achou.any():
        return 0

    idx_achou = achou[achou].index
    df_bc3.loc[idx_achou, "MATCH_TIPO"]            = "A5"
    df_bc3.loc[idx_achou, "COD_ITEM_DECLARACAO"]   = cod_encontrado.loc[idx_achou].values
    df_bc3.loc[idx_achou, "DESCR_ITEM_DECLARACAO"] = descr_encontrado.loc[idx_achou].values
    return int(achou.sum())


def _integridade_por_nota(df_bc2: pd.DataFrame, df_bc1: pd.DataFrame) -> set:
    """Calcula, por CHV_NFE, a contagem de itens e o somatório de VL_ITEM em
    cada lado (XML/BC2 e SPED/BC1) e devolve o conjunto de CHV_NFE onde
    ambos batem exatamente ("nota íntegra") — pré-requisito do D3.
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


def _match_d3_por_nota(df_bc2: pd.DataFrame, df_bc1: pd.DataFrame, chaves_integras: set) -> dict:
    """D3 (integridade de nota): restringe às CHV_NFE "íntegras" (mesma
    contagem de itens e mesmo somatório de VL_ITEM entre XML e SPED — ver
    _integridade_por_nota) e casa, dentro delas, só por similaridade de
    descrição > LIMIAR_D3, 1-para-1 (_atribuir_1_para_1). Chamado só com
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
        mask_final = matriz > LIMIAR_D3
        correspondencias.update(
            _atribuir_1_para_1(mask_final, matriz, grupo_bc2.index, grupo_bc1.index)
        )

    return correspondencias


def _match_d4_por_nota(df_bc2: pd.DataFrame, df_bc1: pd.DataFrame) -> dict:
    """D4 (último recurso): dentro da mesma CHV_NFE, casa só por
    similaridade de descrição > LIMIAR_D4, 1-para-1 (_atribuir_1_para_1)
    — sem exigir GTIN, valor ou integridade de nota. Chamado só com os itens
    que sobraram 'nd'/'nm' após D1/D2/família A/D3. Devolve
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
        mask_final = matriz > LIMIAR_D4
        correspondencias.update(
            _atribuir_1_para_1(mask_final, matriz, grupo_bc2.index, grupo_bc1.index)
        )

    return correspondencias


def executar_matching() -> "tuple[pd.DataFrame, dict]":
    """Executa o cruzamento BC2 (XML, ET) x BC1 (SPED) em nove níveis (D1,
    D2, A1-A5, D3, D4) e devolve a BC3: uma linha por item da BC2, com
    DESCR_ITEM_DECLARACAO/COD_ITEM_DECLARACAO trazidos do BC1 quando houver
    correspondência, 'nd' quando a CHV_NFE não estiver declarada, ou 'nm'
    quando a CHV_NFE existir mas o item não passar em nenhum tipo."""
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
    # qualquer consumo por D1/D2 — é propriedade da nota, não dos itens
    # ainda disponíveis (D3).
    chaves_integras = _integridade_por_nota(df_bc2, df_bc1)

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

    # ── D3: integridade de nota sobre o que ainda sobrou ND/NM ──────────────
    idx_pendente_d3 = df_bc3.index[df_bc3["MATCH_TIPO"].isin(("ND", "NM"))]
    df_bc2_pend_d3 = df_bc2.loc[idx_pendente_d3]
    df_bc1_disp_d3 = df_bc1.loc[~df_bc1.index.isin(indices_bc1_usados)]
    match_d3 = _match_d3_por_nota(df_bc2_pend_d3, df_bc1_disp_d3, chaves_integras)
    _aplicar(match_d3, "D3")
    indices_bc1_usados |= {v[0] for v in match_d3.values()}

    # ── D4: ultimo recurso (so similaridade) sobre o que ainda sobrou ───────
    idx_pendente_d4 = df_bc3.index[df_bc3["MATCH_TIPO"].isin(("ND", "NM"))]
    df_bc2_pend_d4 = df_bc2.loc[idx_pendente_d4]
    df_bc1_disp_d4 = df_bc1.loc[~df_bc1.index.isin(indices_bc1_usados)]
    match_d4 = _match_d4_por_nota(df_bc2_pend_d4, df_bc1_disp_d4)
    _aplicar(match_d4, "D4")

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
        "nao_declarado": contagem_tipo.get("ND", 0),   # chave inteira ausente do SPED (apos familia A/D3/D4)
        "sem_match_item": contagem_tipo.get("NM", 0),  # chave declarada, item nao casou em nenhum tipo (apos familia A/D3/D4)
    }
    return df_bc3, meta
