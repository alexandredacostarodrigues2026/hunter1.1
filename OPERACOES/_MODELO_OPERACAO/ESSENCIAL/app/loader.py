"""Carregamento direto dos arquivos brutos de NF-e (XML) e SPED/EFD (DECLARAÇÃO).

Não há mais exportação via Qlik — a leitura é feita direto de:
  - 1-DOCFISCAIS/nf/*.txt   (NF-e item a item — lado XML)
  - 2-DECLARACAO/SPED/*.txt (EFD ICMS/IPI — lado DECLARAÇÃO)

Leiaute dos registros SPED reconstruído por amostragem dos arquivos reais,
seguindo o padrão público da EFD ICMS/IPI (ver GUIA PRÁTICO DA ESCRITURAÇÃO
FISCAL DIGITAL - EFD.pdf em 2-DECLARACAO/) — vale conferência pontual contra
o guia antes de uso em produção.
"""
import hashlib
import json
import logging
import os
import re
import sys
import unicodedata
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

import duckdb
import pandas as pd
import streamlit as st

_APP_DIR  = Path(__file__).parent
_ROOT_DIR = _APP_DIR.parent          # pasta ESSENCIAL/
for _p in [str(_APP_DIR), str(_ROOT_DIR)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

logger = logging.getLogger(__name__)

# HUNTER_OPERACAO_DIR permite apontar este mesmo motor para outra pasta de
# operação (usado pelo processar_operacoes.bat) — sem a variável, comportamento
# idêntico ao de sempre: operação = pasta-pai de ESSENCIAL/ (geraldo_2020_2024).
_OPERACAO_DIR_OVERRIDE = os.environ.get("HUNTER_OPERACAO_DIR")
if _OPERACAO_DIR_OVERRIDE:
    _OPERACAO_DIR = Path(_OPERACAO_DIR_OVERRIDE)
    _config_flat      = _OPERACAO_DIR / "config.json"
    _config_essencial = _OPERACAO_DIR / "ESSENCIAL" / "config" / "config.json"
    CONFIG_PATH = _config_flat if _config_flat.exists() else _config_essencial
else:
    _OPERACAO_DIR = _ROOT_DIR.parent     # pasta da operação (geraldo_2020_2024/)
    CONFIG_PATH = _ROOT_DIR / "config" / "config.json"

_BANCO_PATH = _ROOT_DIR / "banco" / "hunter.duckdb"

_CANDIDATOS_PROD = [
    "Descricao_do_Produto_ou_servicos",
    "DescItem",
    "XPROD",
    "DESCR_ITEM",
    "PRODUTO",
]

_REG_VALIDO = re.compile(r"^[0-9A-Z]{4}$")

# ── Regras de negócio de filtragem NF-e (Regra Operacional R07) ──────────────
# Exclusivo do lado XML — não se aplica ao EFD/SPED. Itens com CFOP na
# watchlist NÃO são descartados: são segregados (por item, não por chave
# inteira) para as tabelas de análise nfe_analise_et/nfe_analise_ep, mantendo
# os datasets principais (nfe_entradas/nfe_saidas) limpos sem perder dado.
_CFOP_WATCHLIST_GLOBAL = {  # aplicada a ET e EP
    "1922", "2922", "5922", "6922",   # Faturamento para Entrega Futura
    "1923", "2923", "5923", "6923",   # Venda à Ordem
}
_CFOP_WATCHLIST_ET = {"5927", "6927"}   # Emissão de Terceiros — baixa de estoque
_CFOP_WATCHLIST_EP = {"5929", "6929"}   # Emissão Própria — lançamentos ECF
# Nota: CFOP 5929 em registros de ET NÃO é segregado (segue para nfe_entradas/
# nfe_saidas normalmente) — não está na watchlist global nem na de ET.

# Situação da NF-e (fatonfe_informix_stnfeletronica): só documentos válidos
# (A=Autorizada, O=demais situações regulares) seguem para o fluxo principal
# ou para a conferência de CFOP — canceladas (C), denegadas, inutilizadas
# etc. são segregadas (não descartadas) em nfe_situacao_et/nfe_situacao_ep,
# ver _classificar_itens_nfe().
_SITUACOES_NFE_VALIDAS = {"A", "O"}

_COL_SITUACAO_NFE = "fatonfe_informix_stnfeletronica"
_COL_CFOP_NFE     = "fatoitemnfe_infnfe_det_prod_cfop"
_COL_CHAVE_NFE    = "fatonfe_infprot_chnfe"
_COL_NUM_ITEM_NFE = "fatoitemnfe_infnfe_det_nitem"


def load_config() -> dict:
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return json.load(f)


def _resolver_path(config: dict, chave: str, default: str) -> Path:
    """Resolve um caminho do config.json relativo à pasta da operação (ou absoluto)."""
    raw = config.get(chave, default)
    p = Path(raw)
    if p.is_absolute():
        return p
    return (_OPERACAO_DIR / raw).resolve()


def _normalizar_str(s: str) -> str:
    """Remove acentos, uppercase, trim."""
    s = str(s).strip().upper()
    return "".join(
        c for c in unicodedata.normalize("NFD", s)
        if unicodedata.category(c) != "Mn"
    )


def _normalizar_cnpj(valor: str) -> str:
    """Mantém só dígitos (tolera CNPJ com máscara ou zeros à esquerda divergentes)."""
    return re.sub(r"\D", "", str(valor))


# ── Lado XML — NF-e (1-DOCFISCAIS/nf/*.txt) ──────────────────────────────────

def _read_txt_pipe(path: Path) -> pd.DataFrame:
    """Lê arquivo .txt com header próprio, separador '|', tolerando múltiplos encodings.
    Não lê CSV nem qlik/ — só os .txt brutos de 1-DOCFISCAIS/nf/."""
    for enc in ("utf-8-sig", "utf-8", "latin-1", "cp1252"):
        try:
            df = pd.read_csv(
                path, sep="|", encoding=enc, dtype=str,
                on_bad_lines="skip", engine="python",
            )
            if len(df.columns) > 1:
                df.columns = [c.strip() for c in df.columns]
                return df.fillna("")
        except Exception:
            continue
    return pd.DataFrame()


def _localizar_arquivos_nfe(config: dict) -> list:
    pasta = _resolver_path(config, "nfe_path", "1-DOCFISCAIS/nf")
    if not pasta.exists():
        return []
    return sorted(pasta.rglob("*.txt"))


def _localizar_arquivos_nfe_subpasta(config: dict, subpasta: str) -> list:
    """Lista os .txt dentro de nfe_path/<subpasta>/ (ex.: 'ET', 'EP')."""
    pasta = _resolver_path(config, "nfe_path", "1-DOCFISCAIS/nf") / subpasta
    if not pasta.exists():
        return []
    return sorted(pasta.glob("*.txt"))


_BUCKETS_NFE = (
    "entradas", "saidas", "analise_et", "analise_ep", "situacao_et", "situacao_ep",
)


@st.cache_data(ttl=1800, show_spinner=False)
def _classificar_itens_nfe() -> dict:
    """Lê todos os .txt de nfe_path (ET+EP) e segrega POR ITEM (não por chave
    inteira) em 6 grupos, sem descartar nenhum registro:
      1. situação inválida (fora de A/O — canceladas, denegadas, inutilizadas)
         -> nfe_situacao_et / nfe_situacao_ep (pelo CNPJ nunca ir ao cruzamento
         físico nem à conferência de CFOP simbólico);
      2. dentre os de situação válida, CFOP na watchlist (faturamento futuro,
         venda à ordem, baixa de estoque/ECF) -> nfe_analise_et / nfe_analise_ep;
      3. o restante (situação válida + CFOP fora da watchlist) -> entradas/
         saídas (fluxo principal de cruzamento), conforme o tpnf.
    Devolve {'entradas','saidas','analise_et','analise_ep','situacao_et',
    'situacao_ep': DataFrame, 'erros': list, 'arquivos': list}."""
    config   = load_config()
    arquivos = _localizar_arquivos_nfe(config)
    vazio    = pd.DataFrame()
    resultado_vazio = {b: vazio for b in _BUCKETS_NFE}
    resultado_vazio.update({"erros": [], "arquivos": [str(a) for a in arquivos]})

    if not arquivos:
        resultado_vazio["erros"].append(
            f"Nenhum arquivo NF-e encontrado em {_resolver_path(config, 'nfe_path', '1-DOCFISCAIS/nf')}"
        )
        return resultado_vazio

    partes = []
    erros = []
    for arquivo in arquivos:
        try:
            df = _read_txt_pipe(arquivo)
            if df.empty or "fatonfe_infnfe_ide_tpnf" not in df.columns:
                erros.append(f"Arquivo sem coluna tpnf ou vazio: {arquivo.name}")
                continue
            df["PASTA_ORIGEM"]    = arquivo.parent.name.upper()
            df["ARQUIVO_ORIGEM"]  = arquivo.name
            partes.append(df)
        except Exception as exc:
            erros.append(f"Erro em {arquivo.name}: {exc}")
            logger.exception("Erro ao carregar NF-e %s", arquivo)

    if not partes:
        resultado_vazio["erros"] = erros
        return resultado_vazio

    combined = pd.concat(partes, ignore_index=True)
    combined["TIMESTAMP_CARGA"] = datetime.now().isoformat(timespec="seconds")

    col_prod = "fatoitemnfe_infnfe_det_prod_xprod"
    if col_prod in combined.columns:
        combined["PRODUTO_RAW"]         = combined[col_prod].astype(str)
        combined["PRODUTO_NORMALIZADO"] = combined[col_prod].apply(_normalizar_str)
    else:
        combined["PRODUTO_RAW"]         = ""
        combined["PRODUTO_NORMALIZADO"] = ""

    combined = _forcar_colunas_string(combined, [_COL_CHAVE_NFE, _COL_NUM_ITEM_NFE, _COL_CFOP_NFE])
    combined = _gerar_id_unico(combined, [_COL_CHAVE_NFE, _COL_NUM_ITEM_NFE])

    situacao = combined[_COL_SITUACAO_NFE].astype(str).str.strip() if _COL_SITUACAO_NFE in combined.columns else pd.Series("", index=combined.index)
    cfop     = combined[_COL_CFOP_NFE].astype(str).str.strip()
    pasta    = combined["PASTA_ORIGEM"]

    mask_situacao_valida = situacao.isin(_SITUACOES_NFE_VALIDAS)
    mask_situacao_et = ~mask_situacao_valida & (pasta == "ET")
    mask_situacao_ep = ~mask_situacao_valida & (pasta == "EP")

    mask_analise_et = mask_situacao_valida & (pasta == "ET") & cfop.isin(_CFOP_WATCHLIST_GLOBAL | _CFOP_WATCHLIST_ET)
    mask_analise_ep = mask_situacao_valida & (pasta == "EP") & cfop.isin(_CFOP_WATCHLIST_GLOBAL | _CFOP_WATCHLIST_EP)
    mask_principal  = mask_situacao_valida & ~(mask_analise_et | mask_analise_ep)

    tpnf = combined["fatonfe_infnfe_ide_tpnf"].astype(str).str.strip()

    df_entradas = combined[mask_principal & (tpnf == "0")].copy()
    df_entradas["ORIGEM_DADOS"] = "ENTRADAS"
    df_saidas = combined[mask_principal & (tpnf == "1")].copy()
    df_saidas["ORIGEM_DADOS"] = "SAIDAS"
    df_analise_et = combined[mask_analise_et].copy()
    df_analise_et["ORIGEM_DADOS"] = "ANALISE_ET"
    df_analise_ep = combined[mask_analise_ep].copy()
    df_analise_ep["ORIGEM_DADOS"] = "ANALISE_EP"
    df_situacao_et = combined[mask_situacao_et].copy()
    df_situacao_et["ORIGEM_DADOS"] = "SITUACAO_ET"
    df_situacao_ep = combined[mask_situacao_ep].copy()
    df_situacao_ep["ORIGEM_DADOS"] = "SITUACAO_EP"

    return {
        "entradas": df_entradas, "saidas": df_saidas,
        "analise_et": df_analise_et, "analise_ep": df_analise_ep,
        "situacao_et": df_situacao_et, "situacao_ep": df_situacao_ep,
        "erros": erros, "arquivos": [str(a) for a in arquivos],
    }


def _meta_nfe(df: pd.DataFrame, origem_dados: str, erros: list, arquivos: list) -> dict:
    return {
        "arquivos": arquivos, "origem_dados": origem_dados, "erros": erros,
        "total_linhas": len(df), "total_colunas": len(df.columns), "colunas": df.columns.tolist(),
    }


def load_entradas() -> "tuple[pd.DataFrame, dict]":
    """Carrega itens de NF-e de ENTRADA (tpnf=0), já sem os CFOPs segregados — lado XML."""
    r = _classificar_itens_nfe()
    return r["entradas"], _meta_nfe(r["entradas"], "ENTRADAS", r["erros"], r["arquivos"])


def load_saidas() -> "tuple[pd.DataFrame, dict]":
    """Carrega itens de NF-e de SAÍDA (tpnf=1), já sem os CFOPs segregados — lado XML."""
    r = _classificar_itens_nfe()
    return r["saidas"], _meta_nfe(r["saidas"], "SAIDAS", r["erros"], r["arquivos"])


def load_analise_et() -> "tuple[pd.DataFrame, dict]":
    """Itens de Emissão de Terceiros segregados por CFOP de watchlist
    (faturamento futuro/venda à ordem/baixa de estoque) — não entram no
    cruzamento principal, mas ficam preservados para análise."""
    r = _classificar_itens_nfe()
    return r["analise_et"], _meta_nfe(r["analise_et"], "ANALISE_ET", r["erros"], r["arquivos"])


def load_analise_ep() -> "tuple[pd.DataFrame, dict]":
    """Itens de Emissão Própria segregados por CFOP de watchlist
    (faturamento futuro/venda à ordem/lançamento ECF) — não entram no
    cruzamento principal, mas ficam preservados para análise."""
    r = _classificar_itens_nfe()
    return r["analise_ep"], _meta_nfe(r["analise_ep"], "ANALISE_EP", r["erros"], r["arquivos"])


# ── Base Comparativa 2 (BC2) — itens de NF-e de Emissão de Terceiros ────────
# Estruturação do lado XML para cruzamento com a declaração (BC1 = lado SPED,
# ver load_declaracao_entradas_terceiros()). Colunas renomeadas para o mesmo
# padrão de nomes curtos da BC1 (CHV_NFE, COD_ITEM, NUM_ITEM, UNID, QTD,
# VL_ITEM, COD_NCM, COD_BARRA), para que a Etapa 1 (Matching) compare os dois
# lados pela mesma chave sem precisar conhecer dois esquemas de nome
# diferentes.
_BC2_RENOMEAR_COLUNAS = {
    _COL_CHAVE_NFE:                             "CHV_NFE",
    _COL_NUM_ITEM_NFE:                          "NUM_ITEM",
    "fatoitemnfe_infnfe_det_prod_cean":         "COD_BARRA",
    "fatoitemnfe_infnfe_det_prod_cprod":        "COD_ITEM",
    "fatoitemnfe_infnfe_det_prod_ncm":          "COD_NCM",
    "fatoitemnfe_infnfe_det_prod_ucom":         "UNID",
    "fatoitemnfe_infnfe_det_prod_qcom":         "QTD",
    "fatoitemnfe_infnfe_det_prod_vuncom":       "_VALOR_UNIT_ORIGINAL",
    "fatoitemnfe_infnfe_det_prod_vprod":        "VL_ITEM",
}
_BC2_COLUNAS_FINAIS = [
    "CHV_NFE", "fatonfe_infnfe_emit_cnpj", "NUM_ITEM",
    "fatoitemnfe_infnfe_det_prod_xprod", "COD_BARRA", "COD_ITEM", "COD_NCM",
    "UNID", "QTD", "_VALOR_UNIT_ORIGINAL", "VL_ITEM",
    "ID_UNICO", "PASTA_ORIGEM", "ARQUIVO_ORIGEM",
]


def montar_bc2() -> "tuple[pd.DataFrame, dict]":
    """Monta a Base Comparativa 2 (BC2): itens de NF-e de Emissão de
    Terceiros (ET) — origem ET, situação válida (A/O — inválidas já foram
    para nfe_situacao_et em _classificar_itens_nfe()) e CFOP fora da
    watchlist de ET (5929 permanece no fluxo principal da BC2, só 5927/6927
    e a watchlist global são segregados para nfe_analise_et). Reaproveita os
    buckets 'entradas'+'saidas' já classificados (união = toda situação
    válida com CFOP fora da watchlist, independente do tpnf) e filtra só
    PASTA_ORIGEM=='ET'."""
    r = _classificar_itens_nfe()
    if r["entradas"].empty and r["saidas"].empty:
        meta = {"origem_dados": "BC2", "erros": r["erros"], "arquivos": r["arquivos"], "total_linhas": 0}
        return pd.DataFrame(), meta

    principal = pd.concat([r["entradas"], r["saidas"]], ignore_index=True)
    df = principal[principal["PASTA_ORIGEM"] == "ET"].copy()
    df = df.rename(columns=_BC2_RENOMEAR_COLUNAS)

    colunas = [c for c in _BC2_COLUNAS_FINAIS if c in df.columns]
    df = df[colunas]
    df = _forcar_colunas_string(df, ["CHV_NFE", "COD_ITEM", "NUM_ITEM"])

    meta = {
        "origem_dados": "BC2",
        "total_linhas": len(df), "total_colunas": len(df.columns), "colunas": df.columns.tolist(),
        "erros": r["erros"], "arquivos": r["arquivos"],
    }
    return df, meta


# ── Lado DECLARAÇÃO — SPED/EFD (2-DECLARACAO/SPED/*.txt) ─────────────────────

_CAMPOS_0200 = [
    "COD_ITEM", "DESCR_ITEM", "COD_BARRA", "COD_ANT_ITEM", "UNID_INV",
    "TIPO_ITEM", "COD_NCM", "EX_IPI", "COD_GEN", "COD_LST", "ALIQ_ICMS",
]
_CAMPOS_C100 = [
    "IND_OPER", "IND_EMIT", "COD_PART", "COD_MOD", "COD_SIT", "SER", "NUM_DOC",
    "CHV_NFE", "DT_DOC", "DT_E_S", "VL_DOC", "IND_PGTO", "VL_DESC", "VL_ABAT_NT",
    "VL_MERC", "IND_FRT", "VL_FRT", "VL_SEG", "VL_OUT_DA", "VL_BC_ICMS", "VL_ICMS",
    "VL_BC_ICMS_ST", "VL_ICMS_ST", "VL_IPI", "VL_PIS", "VL_COFINS", "VL_PIS_ST", "VL_COFINS_ST",
]
_CAMPOS_C170 = [
    "NUM_ITEM", "COD_ITEM", "DESCR_COMPL", "QTD", "UNID", "VL_ITEM", "VL_DESC",
    "IND_MOV", "CST_ICMS", "CFOP", "COD_NAT", "VL_BC_ICMS", "ALIQ_ICMS", "VL_ICMS",
    "VL_BC_ICMS_ST", "ALIQ_ST", "VL_ICMS_ST", "IND_APUR", "CST_IPI", "COD_ENQ",
    "VL_BC_IPI", "ALIQ_IPI", "VL_IPI", "CST_PIS", "VL_BC_PIS", "ALIQ_PIS_PERC",
    "QUANT_BC_PIS", "ALIQ_PIS_REAIS", "VL_PIS", "COD_CTA", "VL_ABAT_NAO_TRIB",
    "CST_COFINS", "VL_BC_COFINS", "ALIQ_COFINS_PERC", "QUANT_BC_COFINS",
    "ALIQ_COFINS_REAIS", "VL_COFINS", "COD_CTA_COFINS", "VL_ABAT_NAO_TRIB_COFINS",
]
_CAMPOS_H010 = [
    "COD_ITEM", "UNID", "QTD", "VL_UNIT", "VL_ITEM", "IND_PROP",
    "COD_PART", "TXT_COMPL", "COD_CTA", "VL_ITEM_IR",
]
_CAMPOS_0190 = ["UNID", "DESCR"]
_CAMPOS_0150 = [
    "COD_PART", "NOME", "COD_PAIS", "CNPJ", "CPF", "IE", "COD_MUN",
    "SUFRAMA", "END", "NUM", "COMPL", "BAIRRO",
]
_CAMPOS_0000 = [
    "COD_VER", "COD_FIN", "DT_INI", "DT_FIN", "NOME", "CNPJ", "CPF", "UF",
    "IE", "COD_MUN", "IM", "SUFRAMA", "IND_PERFIL", "IND_ATIV",
]


def _localizar_arquivos_sped(config: dict) -> list:
    pasta = _resolver_path(config, "sped_path", "2-DECLARACAO/SPED")
    if not pasta.exists():
        return []
    return sorted(p for p in pasta.glob("*.txt") if p.name.lower() != "base.txt")


def _iter_linhas_sped(path: Path):
    """Lê o arquivo tolerando qualquer byte (latin-1) e só repassa linhas SPED
    válidas (começam e terminam com '|', código de registro reconhecível),
    descartando o bloco de assinatura digital binária colado no final."""
    with open(path, encoding="latin-1", errors="replace") as f:
        for linha in f:
            linha = linha.rstrip("\r\n")
            if not (linha.startswith("|") and linha.endswith("|")):
                continue
            campos = linha.split("|")
            if len(campos) < 3 or not _REG_VALIDO.match(campos[1]):
                continue
            yield campos


def _competencia_arquivo(arquivo: Path) -> str:
    """Lê o registro 0000 do arquivo e devolve a competência (AAAAMM) via DT_INI."""
    for campos in _iter_linhas_sped(arquivo):
        if campos[1] == "0000":
            dt_ini = campos[4] if len(campos) > 4 else ""
            if len(dt_ini) == 8:
                return dt_ini[4:8] + dt_ini[2:4]  # DDMMAAAA -> AAAAMM
            return ""
    return ""


def _parse_registros_sped(arquivos: list, reg: str, campos_nomes: list) -> pd.DataFrame:
    """Extrai todas as ocorrências de um registro SPED (ex.: 0200, H010) dos arquivos."""
    linhas = []
    for arquivo in arquivos:
        competencia = _competencia_arquivo(arquivo)
        for campos in _iter_linhas_sped(arquivo):
            if campos[1] != reg:
                continue
            valores = campos[2:2 + len(campos_nomes)]
            valores += [""] * (len(campos_nomes) - len(valores))
            linha = dict(zip(campos_nomes, valores))
            linha["COMPETENCIA"]    = competencia
            linha["ARQUIVO_ORIGEM"] = arquivo.name
            linhas.append(linha)
    return pd.DataFrame(linhas)


def _forcar_colunas_string(df: pd.DataFrame, colunas: "list[str]") -> pd.DataFrame:
    """Garante dtype=str nas colunas de ligação entre registros SPED (COD_ITEM,
    UNID, CHV_NFE, ...) — evita que zeros à esquerda ou chaves de acesso longas
    sejam corrompidos por inferência numérica automática do Pandas
    (Regra Operacional R07)."""
    for col in colunas:
        if col in df.columns:
            df[col] = df[col].astype(str)
    return df


def _gerar_id_unico(df: pd.DataFrame, colunas: "list[str]", nome_coluna: str = "ID_UNICO") -> pd.DataFrame:
    """Cria uma coluna de ID único sintético — hash MD5 determinístico das
    chaves naturais informadas (ex.: CHV_NFE + NUM_ITEM). Determinístico (não
    UUID aleatório) de propósito: precisa ficar estável entre cargas, já que
    persistir_nfe/persistir_sped substituem a tabela inteira a cada carga
    (CREATE OR REPLACE) — um UUID aleatório mudaria a cada recarga e quebraria
    qualquer referência externa a essas linhas."""
    df = df.copy()
    if df.empty:
        df[nome_coluna] = pd.Series(dtype=str)
        return df
    faltantes = [c for c in colunas if c not in df.columns]
    if faltantes:
        df[nome_coluna] = ""
        return df
    chave_concat = df[colunas].astype(str).agg("|".join, axis=1)
    df[nome_coluna] = chave_concat.apply(lambda s: hashlib.md5(s.encode("utf-8")).hexdigest())
    return df


def _parse_itens_c170_com_c100(arquivos: list) -> pd.DataFrame:
    """Percorre C100/C170 sequencialmente — cada C170 herda dados do C100 mais recente."""
    linhas = []
    for arquivo in arquivos:
        competencia = _competencia_arquivo(arquivo)
        c100_atual: dict = {}
        for campos in _iter_linhas_sped(arquivo):
            reg = campos[1]
            if reg == "C100":
                valores = campos[2:2 + len(_CAMPOS_C100)]
                valores += [""] * (len(_CAMPOS_C100) - len(valores))
                c100_atual = dict(zip(_CAMPOS_C100, valores))
            elif reg == "C170":
                valores = campos[2:2 + len(_CAMPOS_C170)]
                valores += [""] * (len(_CAMPOS_C170) - len(valores))
                linha = dict(zip(_CAMPOS_C170, valores))
                linha["IND_OPER"]       = c100_atual.get("IND_OPER", "")
                linha["IND_EMIT"]       = c100_atual.get("IND_EMIT", "")
                linha["COD_PART"]       = c100_atual.get("COD_PART", "")
                linha["NUM_DOC"]        = c100_atual.get("NUM_DOC", "")
                linha["CHV_NFE"]        = c100_atual.get("CHV_NFE", "")
                linha["DT_DOC"]         = c100_atual.get("DT_DOC", "")
                linha["COD_MOD"]        = c100_atual.get("COD_MOD", "")
                linha["COMPETENCIA"]    = competencia
                linha["ARQUIVO_ORIGEM"] = arquivo.name
                linhas.append(linha)
    df = pd.DataFrame(linhas)
    df = _forcar_colunas_string(df, ["COD_ITEM", "UNID", "CHV_NFE", "NUM_ITEM", "COD_PART"])
    return _gerar_id_unico(df, ["CHV_NFE", "NUM_ITEM"])


@st.cache_data(ttl=1800, show_spinner=False)
def load_declaracao_itens() -> "tuple[pd.DataFrame, dict]":
    """Carrega itens de NF da declaração (C100+C170) — lado DECLARAÇÃO."""
    config   = load_config()
    arquivos = _localizar_arquivos_sped(config)
    meta: dict = {"arquivos": [str(a) for a in arquivos], "origem_dados": "DECLARACAO", "erros": []}

    if not arquivos:
        meta["erros"].append(f"Nenhum arquivo SPED encontrado em {_resolver_path(config, 'sped_path', '2-DECLARACAO/SPED')}")
        return pd.DataFrame(), meta

    try:
        df = _parse_itens_c170_com_c100(arquivos)
    except Exception as exc:
        meta["erros"].append(str(exc))
        logger.exception("Erro ao carregar itens da declaração: %s", exc)
        return pd.DataFrame(), meta

    if df.empty:
        meta["erros"].append("Nenhum registro C170 encontrado nos arquivos SPED.")
        return df, meta

    df["ORIGEM_DADOS"]    = "DECLARACAO"
    df["TIMESTAMP_CARGA"] = datetime.now().isoformat(timespec="seconds")
    df["PRODUTO_RAW"]         = df["DESCR_COMPL"].astype(str)
    df["PRODUTO_NORMALIZADO"] = df["DESCR_COMPL"].apply(_normalizar_str)

    meta["total_linhas"]  = len(df)
    meta["total_colunas"] = len(df.columns)
    meta["colunas"]       = df.columns.tolist()
    return df, meta


@st.cache_data(ttl=1800, show_spinner=False)
def load_declaracao_produtos() -> "tuple[pd.DataFrame, dict]":
    """Carrega o cadastro de produtos da declaração (registro 0200)."""
    config   = load_config()
    arquivos = _localizar_arquivos_sped(config)
    meta: dict = {"arquivos": [str(a) for a in arquivos], "origem_dados": "DECLARACAO_PRODUTOS", "erros": []}

    if not arquivos:
        meta["erros"].append(f"Nenhum arquivo SPED encontrado em {_resolver_path(config, 'sped_path', '2-DECLARACAO/SPED')}")
        return pd.DataFrame(), meta

    df = _parse_registros_sped(arquivos, "0200", _CAMPOS_0200)
    if df.empty:
        meta["erros"].append("Nenhum registro 0200 encontrado nos arquivos SPED.")
        return df, meta

    df = _forcar_colunas_string(df, ["COD_ITEM", "UNID_INV", "COD_BARRA", "COD_NCM"])
    df["PRODUTO_RAW"]         = df["DESCR_ITEM"].astype(str)
    df["PRODUTO_NORMALIZADO"] = df["DESCR_ITEM"].apply(_normalizar_str)

    meta["total_linhas"]  = len(df)
    meta["total_colunas"] = len(df.columns)
    meta["colunas"]       = df.columns.tolist()
    return df, meta


@st.cache_data(ttl=1800, show_spinner=False)
def load_declaracao_unidades() -> "tuple[pd.DataFrame, dict]":
    """Carrega o cadastro de unidades de medida da declaração (registro 0190) —
    chave de ligação para o campo 06 (UNID) do C170 e o campo 06 (UNID_INV) do 0200."""
    config   = load_config()
    arquivos = _localizar_arquivos_sped(config)
    meta: dict = {"arquivos": [str(a) for a in arquivos], "origem_dados": "DECLARACAO_UNIDADES", "erros": []}

    if not arquivos:
        meta["erros"].append(f"Nenhum arquivo SPED encontrado em {_resolver_path(config, 'sped_path', '2-DECLARACAO/SPED')}")
        return pd.DataFrame(), meta

    df = _parse_registros_sped(arquivos, "0190", _CAMPOS_0190)
    if df.empty:
        meta["erros"].append("Nenhum registro 0190 encontrado nos arquivos SPED.")
        return df, meta

    df = _forcar_colunas_string(df, ["UNID"])

    meta["total_linhas"]  = len(df)
    meta["total_colunas"] = len(df.columns)
    meta["colunas"]       = df.columns.tolist()
    return df, meta


@st.cache_data(ttl=1800, show_spinner=False)
def load_declaracao_participantes() -> "tuple[pd.DataFrame, dict]":
    """Carrega o cadastro de participantes da declaração (registro 0150) —
    chave de ligação para o campo 03 (COD_PART) do C100, usado para obter o
    CNPJ do emitente em load_declaracao_entradas_terceiros() (Regra
    Operacional R07: COD_PART e CNPJ tratados como string)."""
    config   = load_config()
    arquivos = _localizar_arquivos_sped(config)
    meta: dict = {"arquivos": [str(a) for a in arquivos], "origem_dados": "DECLARACAO_PARTICIPANTES", "erros": []}

    if not arquivos:
        meta["erros"].append(f"Nenhum arquivo SPED encontrado em {_resolver_path(config, 'sped_path', '2-DECLARACAO/SPED')}")
        return pd.DataFrame(), meta

    df = _parse_registros_sped(arquivos, "0150", _CAMPOS_0150)
    if df.empty:
        meta["erros"].append("Nenhum registro 0150 encontrado nos arquivos SPED.")
        return df, meta

    df = _forcar_colunas_string(df, ["COD_PART", "CNPJ"])

    meta["total_linhas"]  = len(df)
    meta["total_colunas"] = len(df.columns)
    meta["colunas"]       = df.columns.tolist()
    return df, meta


def _enriquecer_itens_com_cadastro(
    df_itens: pd.DataFrame, df_produtos: pd.DataFrame, df_unidades: pd.DataFrame,
) -> pd.DataFrame:
    """Junta itens (C170) com o cadastro de produto (0200, por COD_ITEM) e com a
    descrição da unidade de medida (0190, por UNID) — lógica de 'de-para':
      C170 (campo 03 COD_ITEM) -> 0200 (campo 02 COD_ITEM)
      C170 (campo 06 UNID)     -> 0190 (campo 02 UNID)
    """
    if df_itens.empty:
        return df_itens

    df = df_itens.copy()

    if not df_produtos.empty and "COD_ITEM" in df_produtos.columns:
        cols_0200 = ["COD_ITEM", "DESCR_ITEM", "COD_BARRA", "COD_NCM", "UNID_INV"]
        cols_0200 = [c for c in cols_0200 if c in df_produtos.columns]
        cadastro = df_produtos[cols_0200].drop_duplicates("COD_ITEM")
        df = df.merge(cadastro, on="COD_ITEM", how="left", suffixes=("", "_0200"))

    if not df_unidades.empty and "UNID" in df_unidades.columns:
        cadastro_unid = (
            df_unidades[["UNID", "DESCR"]]
            .rename(columns={"DESCR": "DESCR_UNID"})
            .drop_duplicates("UNID")
        )
        df = df.merge(cadastro_unid, on="UNID", how="left")

    return df


@st.cache_data(ttl=1800, show_spinner=False)
def load_declaracao_entradas_terceiros() -> "tuple[pd.DataFrame, dict]":
    """Chaves de entrada de emissão de terceiros: C100 com IND_OPER=0 (entrada)
    e IND_EMIT=1 (emitido por terceiros) + itens C170, enriquecidos com o
    cadastro de produto (0200), de unidade de medida (0190) e o CNPJ do
    emitente via cadastro de participantes (0150, ligado por COD_PART). Os
    filtros de CFOP e situação (Regra Operacional R07) são exclusivos do lado
    XML (_carregar_nfe) — não se aplicam à declaração (EFD/SPED). COD_ITEM,
    UNID, CHV_NFE e CNPJ tratados como string."""
    df_itens, meta_itens = load_declaracao_itens()
    if df_itens.empty:
        meta_itens["origem_dados"] = "DECLARACAO_ENTRADAS_TERCEIROS"
        return df_itens, meta_itens

    df = df_itens[
        (df_itens["IND_OPER"].astype(str).str.strip() == "0")
        & (df_itens["IND_EMIT"].astype(str).str.strip() == "1")
    ].copy()

    df_produtos, _     = load_declaracao_produtos()
    df_unidades, _     = load_declaracao_unidades()
    df_participantes, _ = load_declaracao_participantes()
    df = _enriquecer_itens_com_cadastro(df, df_produtos, df_unidades)

    if not df_participantes.empty and "COD_PART" in df.columns and "CNPJ" in df_participantes.columns:
        cadastro_part = df_participantes[["COD_PART", "CNPJ"]].drop_duplicates("COD_PART")
        df = df.merge(cadastro_part, on="COD_PART", how="left")
    else:
        df["CNPJ"] = ""

    df = _forcar_colunas_string(df, ["COD_ITEM", "UNID", "CHV_NFE", "CNPJ"])

    meta = {
        "origem_dados": "DECLARACAO_ENTRADAS_TERCEIROS",
        "total_linhas":  len(df),
        "total_colunas": len(df.columns),
        "colunas":       df.columns.tolist(),
        "erros": [],
    }
    return df, meta


# ── Identificação da entidade auditada (CNPJ/Razão Social) ───────────────────
# ET/ = auditada é destinatária (entrada de terceiros) | EP/ = auditada é emitente (emissão própria)

def _extrair_pares(arquivos: list, col_cnpj: str, col_nome: str) -> pd.DataFrame:
    """Lê os arquivos NF-e informados e devolve um DataFrame (CNPJ, RAZAO_SOCIAL),
    uma linha por item de NF-e, descartando linhas sem CNPJ."""
    partes = []
    for arquivo in arquivos:
        df = _read_txt_pipe(arquivo)
        if df.empty or col_cnpj not in df.columns or col_nome not in df.columns:
            continue
        par = pd.DataFrame({
            "CNPJ":          df[col_cnpj].apply(_normalizar_cnpj),
            "RAZAO_SOCIAL":  df[col_nome].astype(str).str.strip(),
        })
        partes.append(par[par["CNPJ"] != ""])
    if not partes:
        return pd.DataFrame(columns=["CNPJ", "RAZAO_SOCIAL"])
    return pd.concat(partes, ignore_index=True)


@st.cache_data(ttl=1800, show_spinner=False)
def identificar_entidade_auditada() -> dict:
    """Identifica o CNPJ/Razão Social com maior recorrência volumétrica entre
    ET/ (auditada=destinatária) e EP/ (auditada=emitente)."""
    config = load_config()
    arquivos_et = _localizar_arquivos_nfe_subpasta(config, "ET")
    arquivos_ep = _localizar_arquivos_nfe_subpasta(config, "EP")

    erros = []
    if not arquivos_et:
        erros.append("Nenhum arquivo encontrado em nfe_path/ET")
    if not arquivos_ep:
        erros.append("Nenhum arquivo encontrado em nfe_path/EP")

    pares_et = _extrair_pares(arquivos_et, "fatonfe_infnfe_dest_cnpj", "fatonfe_infnfe_dest_xnome")
    pares_ep = _extrair_pares(arquivos_ep, "fatonfe_infnfe_emit_cnpj", "fatonfe_infnfe_emit_xnome")
    combinado = pd.concat([pares_et, pares_ep], ignore_index=True)

    if combinado.empty:
        erros.append("Nenhum par CNPJ/Razão Social encontrado em ET/EP.")
        return {
            "cnpj": None, "razao_social": None, "ocorrencias": 0,
            "total_linhas_analisadas": 0,
            "por_fonte": {"ET": len(pares_et), "EP": len(pares_ep)},
            "erros": erros,
        }

    contagem_cnpj = combinado["CNPJ"].value_counts()
    cnpj_lider     = contagem_cnpj.index[0]
    ocorrencias    = int(contagem_cnpj.iloc[0])
    razao_social   = (
        combinado.loc[combinado["CNPJ"] == cnpj_lider, "RAZAO_SOCIAL"]
        .value_counts().index[0]
    )

    return {
        "cnpj": cnpj_lider,
        "razao_social": razao_social,
        "ocorrencias": ocorrencias,
        "total_linhas_analisadas": len(combinado),
        "por_fonte": {"ET": len(pares_et), "EP": len(pares_ep)},
        "erros": erros,
    }


def salvar_entidade_auditada(info: dict) -> None:
    """Grava o CNPJ/Razão Social identificados em config.json para uso global."""
    config = load_config()
    config["entidade_auditada"] = {
        "cnpj": info.get("cnpj"),
        "razao_social": info.get("razao_social"),
        "ocorrencias": info.get("ocorrencias"),
        "total_linhas_analisadas": info.get("total_linhas_analisadas"),
        "por_fonte": info.get("por_fonte"),
        "atualizado_em": datetime.now().isoformat(timespec="seconds"),
    }
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=4)


def obter_entidade_auditada() -> "dict | None":
    """Lê a entidade auditada já fixada em config.json (sem recalcular)."""
    return load_config().get("entidade_auditada")


def garantir_entidade_auditada(forcar: bool = False) -> dict:
    """Ponto de entrada único: devolve a entidade auditada já fixada, ou
    identifica e persiste agora se ainda não houver (ou se forcar=True)."""
    if not forcar:
        existente = obter_entidade_auditada()
        if existente:
            return existente
    info = identificar_entidade_auditada()
    if info.get("cnpj"):
        salvar_entidade_auditada(info)
    return info


# ── Upload de XML de NF-e (arraste e solte) — classificação ET/EP ────────────
# Não lê *.txt em lote: recebe XML individual em memória (drag-and-drop) e
# classifica conforme o CNPJ da entidade auditada já fixado (obter_entidade_auditada).

def _extrair_cnpjs_xml(conteudo: bytes) -> dict:
    """Parseia um XML de NF-e em memória e devolve {'emit': cnpj|None, 'dest': cnpj|None}.
    Tolerante a namespace (NFe usa xmlns portalfiscal) e a envelope <nfeProc> opcional."""
    raiz = ET.fromstring(conteudo)

    def _cnpj(tag: str) -> "str | None":
        el = raiz.find(f".//{{*}}{tag}/{{*}}CNPJ")
        return _normalizar_cnpj(el.text) if el is not None and el.text else None

    return {"emit": _cnpj("emit"), "dest": _cnpj("dest")}


def classificar_xml_nfe(nome_arquivo: str, conteudo: bytes) -> dict:
    """Classifica um XML de NF-e como ET (auditada=destinatária) ou EP (auditada=emitente),
    com base no CNPJ já fixado em obter_entidade_auditada()."""
    resultado: dict = {"arquivo": nome_arquivo, "status": None, "pasta": None, "mensagem": ""}

    entidade = obter_entidade_auditada()
    if not entidade or not entidade.get("cnpj"):
        resultado["status"] = "erro"
        resultado["mensagem"] = "Entidade auditada ainda não foi fixada (rode a identificação antes do upload)."
        return resultado

    cnpj_auditada = entidade["cnpj"]

    try:
        cnpjs = _extrair_cnpjs_xml(conteudo)
    except ET.ParseError as exc:
        resultado["status"] = "erro_esquema"
        resultado["mensagem"] = f"XML inválido/mal formado: {exc}"
        return resultado

    if cnpjs["dest"] == cnpj_auditada:
        resultado["pasta"] = "ET"
    elif cnpjs["emit"] == cnpj_auditada:
        resultado["pasta"] = "EP"
    else:
        resultado["status"] = "cnpj_nao_identificado"
        resultado["mensagem"] = (
            f"CNPJ da auditada ({cnpj_auditada}) não consta em <emit> nem <dest> "
            f"(emit={cnpjs['emit']}, dest={cnpjs['dest']})."
        )
        return resultado

    resultado["status"] = "classificado"
    return resultado


def _md5(conteudo: bytes) -> str:
    return hashlib.md5(conteudo).hexdigest()


def salvar_xml_classificado(nome_arquivo: str, conteudo: bytes, pasta: str) -> dict:
    """Grava o XML em nfe_path/<pasta>/, sem sobrepor arquivo existente
    (mesmo nome ou mesmo conteúdo/MD5)."""
    config = load_config()
    destino_dir = _resolver_path(config, "nfe_path", "1-DOCFISCAIS/nf") / pasta
    destino_dir.mkdir(parents=True, exist_ok=True)
    destino = destino_dir / nome_arquivo

    if destino.exists():
        return {"status": "duplicado", "mensagem": f"Já existe um arquivo com este nome em {pasta}/."}

    novo_md5 = _md5(conteudo)
    for existente in destino_dir.glob("*.xml"):
        if _md5(existente.read_bytes()) == novo_md5:
            return {"status": "duplicado", "mensagem": f"Conteúdo idêntico ao arquivo {existente.name} já existente em {pasta}/."}

    destino.write_bytes(conteudo)
    return {"status": "salvo", "mensagem": f"Salvo em {pasta}/{nome_arquivo}", "caminho": str(destino)}


def processar_upload_xml(nome_arquivo: str, conteudo: bytes) -> dict:
    """Pipeline completo para um XML recebido via arraste-e-solte:
    classifica (ET/EP) e grava, sem sobrepor duplicados."""
    resultado = classificar_xml_nfe(nome_arquivo, conteudo)
    if resultado["status"] != "classificado":
        return resultado
    info_salvo = salvar_xml_classificado(nome_arquivo, conteudo, resultado["pasta"])
    resultado.update(info_salvo)
    return resultado


def nome_operacao() -> str:
    """Nome da pasta da operação ativa (ex.: 'geraldo_2020_2024')."""
    return _OPERACAO_DIR.name


def _localizar_xmls_pendentes(config: dict) -> list:
    """XML soltos direto em nfe_path/ (fora de ET/EP) — ainda não classificados."""
    pasta = _resolver_path(config, "nfe_path", "1-DOCFISCAIS/nf")
    if not pasta.exists():
        return []
    return sorted(pasta.glob("*.xml"))


def processar_arquivo_pendente(caminho: Path) -> dict:
    """Classifica e grava um XML pendente lido do disco; remove o original da
    raiz quando classificado com sucesso (mover de fato). Em duplicado/erro,
    o original permanece em nfe_path/ para o usuário ver o que ficou pendente."""
    conteudo = caminho.read_bytes()
    resultado = processar_upload_xml(caminho.name, conteudo)
    if resultado["status"] == "salvo":
        caminho.unlink()
    return resultado


def dados_ja_carregados() -> bool:
    """True se a operação já tem uma carga anterior persistida no DuckDB
    (nfe_entradas/nfe_saidas + sped_itens, com linhas) — consulta o banco
    direto, sem depender de st.session_state (que reseta a cada nova sessão/
    reabertura do navegador). Usado para não exigir uma nova carga toda vez
    que o front é aberto, quando os dados já estão persistidos."""
    if not _BANCO_PATH.exists():
        return False
    try:
        with duckdb.connect(str(_BANCO_PATH), read_only=True) as con:
            tabelas = {r[0] for r in con.execute("SHOW TABLES").fetchall()}
            tem_nfe  = any(t in tabelas for t in ("nfe_entradas", "nfe_saidas"))
            tem_sped = "sped_itens" in tabelas
            if not (tem_nfe and tem_sped):
                return False
            for tabela in ("nfe_entradas", "nfe_saidas", "sped_itens"):
                if tabela in tabelas and con.execute(f"SELECT COUNT(*) FROM {tabela}").fetchone()[0] > 0:
                    return True
            return False
    except Exception:
        logger.exception("Erro ao verificar carga existente em %s", _BANCO_PATH)
        return False


def persistir_nfe(callback=None) -> dict:
    """Persiste NF-e em DuckDB: tabelas nfe_entradas/nfe_saidas (dataset
    principal — situação válida e CFOP fora da watchlist), nfe_analise_et/
    nfe_analise_ep (situação válida mas CFOP de watchlist),
    nfe_situacao_et/nfe_situacao_ep (situação inválida — canceladas,
    denegadas, inutilizadas) e nfe_bc2 (Base Comparativa 2 — itens de
    Emissão de Terceiros já com nomes de coluna normalizados para cruzar
    com a BC1/SPED). callback(etapa, n) chamado apos cada tabela.
    Retorna {tabela: n_linhas}."""
    _BANCO_PATH.parent.mkdir(parents=True, exist_ok=True)
    resultado = {}
    try:
        classificado = _classificar_itens_nfe()
        with duckdb.connect(str(_BANCO_PATH)) as con:
            for tabela, chave, nome_view, sempre_criar in (
                ("nfe_entradas",    "entradas",    "_df_nfe_entradas",    False),
                ("nfe_saidas",      "saidas",      "_df_nfe_saidas",      False),
                # tabelas de segregação são sempre criadas (mesmo vazias)
                # para que analise_ja_gerada() consiga rastrear que a carga
                # já rodou, independente de terem encontrado algo ou não.
                ("nfe_analise_et",  "analise_et",  "_df_nfe_analise_et",  True),
                ("nfe_analise_ep",  "analise_ep",  "_df_nfe_analise_ep",  True),
                ("nfe_situacao_et", "situacao_et", "_df_nfe_situacao_et", True),
                ("nfe_situacao_ep", "situacao_ep", "_df_nfe_situacao_ep", True),
            ):
                df = classificado[chave]
                if not df.empty or sempre_criar:
                    con.register(nome_view, df)
                    con.execute(f"CREATE OR REPLACE TABLE {tabela} AS SELECT * FROM {nome_view}")
                    con.unregister(nome_view)
                resultado[tabela] = len(df)
                if callback:
                    callback(tabela, resultado[tabela])

            df_bc2, _ = montar_bc2()
            if not df_bc2.empty:
                con.register("_df_nfe_bc2", df_bc2)
                con.execute("CREATE OR REPLACE TABLE nfe_bc2 AS SELECT * FROM _df_nfe_bc2")
                con.unregister("_df_nfe_bc2")
            resultado["nfe_bc2"] = len(df_bc2)
            if callback:
                callback("nfe_bc2", resultado["nfe_bc2"])
    except Exception as exc:
        logger.exception("Erro ao persistir NF-e: %s", exc)
        resultado["erro"] = str(exc)
    return resultado


def persistir_sped(callback=None) -> dict:
    """Persiste SPED (C100+C170, 0200, 0190, H010) em DuckDB: tabelas sped_itens,
    sped_produtos, sped_unidades e sped_estoque. callback(etapa, n) chamado apos
    cada tabela. As chaves de entrada de emissão de terceiros (sped_entradas_
    terceiros) são geradas à parte, sob demanda, por gerar_entradas_terceiros()."""
    config = load_config()
    _BANCO_PATH.parent.mkdir(parents=True, exist_ok=True)
    resultado = {}
    try:
        arquivos_sped = _localizar_arquivos_sped(config)
        with duckdb.connect(str(_BANCO_PATH)) as con:
            df_sped_itens = _parse_itens_c170_com_c100(arquivos_sped)
            if not df_sped_itens.empty:
                con.register("_df_sped_itens", df_sped_itens)
                con.execute("CREATE OR REPLACE TABLE sped_itens AS SELECT * FROM _df_sped_itens")
            resultado["sped_itens"] = len(df_sped_itens)
            if callback:
                callback("sped_itens", resultado["sped_itens"])

            df_sped_prod = _parse_registros_sped(arquivos_sped, "0200", _CAMPOS_0200)
            if not df_sped_prod.empty:
                df_sped_prod = _forcar_colunas_string(df_sped_prod, ["COD_ITEM", "UNID_INV", "COD_BARRA", "COD_NCM"])
                con.register("_df_sped_prod", df_sped_prod)
                con.execute("CREATE OR REPLACE TABLE sped_produtos AS SELECT * FROM _df_sped_prod")
            resultado["sped_produtos"] = len(df_sped_prod)
            if callback:
                callback("sped_produtos", resultado["sped_produtos"])

            df_sped_unid = _parse_registros_sped(arquivos_sped, "0190", _CAMPOS_0190)
            if not df_sped_unid.empty:
                df_sped_unid = _forcar_colunas_string(df_sped_unid, ["UNID"])
                con.register("_df_sped_unid", df_sped_unid)
                con.execute("CREATE OR REPLACE TABLE sped_unidades AS SELECT * FROM _df_sped_unid")
            resultado["sped_unidades"] = len(df_sped_unid)
            if callback:
                callback("sped_unidades", resultado["sped_unidades"])

            df_sped_est = _parse_registros_sped(arquivos_sped, "H010", _CAMPOS_H010)
            if not df_sped_est.empty:
                con.register("_df_sped_est", df_sped_est)
                con.execute("CREATE OR REPLACE TABLE sped_estoque AS SELECT * FROM _df_sped_est")
            resultado["sped_estoque"] = len(df_sped_est)
            if callback:
                callback("sped_estoque", resultado["sped_estoque"])
    except Exception as exc:
        logger.exception("Erro ao persistir SPED: %s", exc)
        resultado["erro"] = str(exc)
    return resultado


def entradas_terceiros_ja_geradas() -> bool:
    """True se sped_entradas_terceiros já existe persistida (com linhas) no
    DuckDB da operação — mesma lógica de dados_ja_carregados(), para não
    reprocessar sempre que o front é reaberto."""
    if not _BANCO_PATH.exists():
        return False
    try:
        with duckdb.connect(str(_BANCO_PATH), read_only=True) as con:
            tabelas = {r[0] for r in con.execute("SHOW TABLES").fetchall()}
            if "sped_entradas_terceiros" not in tabelas:
                return False
            return con.execute("SELECT COUNT(*) FROM sped_entradas_terceiros").fetchone()[0] > 0
    except Exception:
        logger.exception("Erro ao verificar sped_entradas_terceiros existente em %s", _BANCO_PATH)
        return False


def consultar_entradas_terceiros(limite: "int | None" = 200) -> "tuple[pd.DataFrame, int]":
    """Lê a tabela sped_entradas_terceiros já persistida (sem reprocessar
    XML/SPED), devolvendo uma amostra (até 'limite' linhas) e o total real de
    linhas da tabela — usado para exibir a prévia sem regerar o dataset.
    limite=None devolve a tabela inteira (usado para exportação completa)."""
    if not _BANCO_PATH.exists():
        return pd.DataFrame(), 0
    try:
        with duckdb.connect(str(_BANCO_PATH), read_only=True) as con:
            total = con.execute("SELECT COUNT(*) FROM sped_entradas_terceiros").fetchone()[0]
            query = (
                "SELECT * FROM sped_entradas_terceiros" if limite is None
                else f"SELECT * FROM sped_entradas_terceiros LIMIT {limite}"
            )
            df = con.execute(query).df()
        return df, total
    except Exception:
        logger.exception("Erro ao consultar sped_entradas_terceiros em %s", _BANCO_PATH)
        return pd.DataFrame(), 0


def gerar_entradas_terceiros() -> "tuple[pd.DataFrame, dict]":
    """Gera (load_declaracao_entradas_terceiros) e persiste isoladamente a
    tabela sped_entradas_terceiros — ação sob demanda (botão dedicado da
    interface), sem reprocessar NF-e nem as demais tabelas SPED."""
    df, meta = load_declaracao_entradas_terceiros()
    _BANCO_PATH.parent.mkdir(parents=True, exist_ok=True)
    try:
        with duckdb.connect(str(_BANCO_PATH)) as con:
            if not df.empty:
                con.register("_df_entradas_terceiros", df)
                con.execute("CREATE OR REPLACE TABLE sped_entradas_terceiros AS SELECT * FROM _df_entradas_terceiros")
    except Exception as exc:
        logger.exception("Erro ao persistir sped_entradas_terceiros: %s", exc)
        meta = dict(meta)
        meta["erros"] = list(meta.get("erros", [])) + [str(exc)]
    return df, meta


# ── Painel de monitoramento — CFOPs segregados (nfe_analise_et/ep) ──────────

_DICIONARIO_CAMPOS_PATH = _OPERACAO_DIR.parent.parent / "DICIONARIO DE CAMPOS.txt"


def carregar_dicionario_campos() -> dict:
    """Lê DICIONARIO DE CAMPOS.txt (campo_tecnico;nome_amigavel) da raiz do
    projeto — usado para renomear colunas técnicas (fatonfe_.../
    fatoitemnfe_...) para nomes amigáveis na exibição. Devolve {} se o
    arquivo não existir (portabilidade — não é obrigatório para a app rodar)."""
    if not _DICIONARIO_CAMPOS_PATH.exists():
        return {}
    dicionario: dict = {}
    try:
        with open(_DICIONARIO_CAMPOS_PATH, encoding="utf-8") as f:
            for linha in f:
                linha = linha.strip()
                if not linha or linha.startswith("#") or ";" not in linha:
                    continue
                campo, _, amigavel = linha.partition(";")
                if campo.strip() == "campo_tecnico":
                    continue
                dicionario[campo.strip()] = amigavel.strip()
    except Exception:
        logger.exception("Erro ao ler dicionário de campos em %s", _DICIONARIO_CAMPOS_PATH)
        return {}
    return dicionario


_TABELAS_SEGREGACAO = (
    "nfe_analise_et", "nfe_analise_ep", "nfe_situacao_et", "nfe_situacao_ep",
)
_CHAVES_SEGREGACAO = {
    "nfe_analise_et": "analise_et", "nfe_analise_ep": "analise_ep",
    "nfe_situacao_et": "situacao_et", "nfe_situacao_ep": "situacao_ep",
}


def analise_ja_gerada() -> bool:
    """True se as 4 tabelas de segregação (nfe_analise_et/ep — CFOP de
    watchlist — e nfe_situacao_et/ep — situação inválida) já existem
    persistidas no DuckDB da operação (mesma lógica de dados_ja_carregados/
    entradas_terceiros_ja_geradas) — permanecem mesmo vazias (0 linhas), já
    que persistir_nfe()/gerar_dados_analise() sempre as criam."""
    if not _BANCO_PATH.exists():
        return False
    try:
        with duckdb.connect(str(_BANCO_PATH), read_only=True) as con:
            tabelas = {r[0] for r in con.execute("SHOW TABLES").fetchall()}
            return set(_TABELAS_SEGREGACAO).issubset(tabelas)
    except Exception:
        logger.exception("Erro ao verificar tabelas de análise existentes em %s", _BANCO_PATH)
        return False


def consultar_totais_analise() -> dict:
    """Retorna {'nfe_analise_et': n, 'nfe_analise_ep': n, 'nfe_situacao_et': n,
    'nfe_situacao_ep': n} lendo direto do DuckDB (sem reprocessar) —
    alimenta os KPIs do painel de monitoramento."""
    totais = {t: 0 for t in _TABELAS_SEGREGACAO}
    if not _BANCO_PATH.exists():
        return totais
    try:
        with duckdb.connect(str(_BANCO_PATH), read_only=True) as con:
            tabelas = {r[0] for r in con.execute("SHOW TABLES").fetchall()}
            for tabela in totais:
                if tabela in tabelas:
                    totais[tabela] = con.execute(f"SELECT COUNT(*) FROM {tabela}").fetchone()[0]
    except Exception:
        logger.exception("Erro ao consultar totais de análise em %s", _BANCO_PATH)
    return totais


def consultar_chaves_analise(fluxo: str = "ET", categoria: str = "cfop", limite: int = 100) -> "tuple[pd.DataFrame, int]":
    """Lê uma das 4 tabelas de segregação já persistida (sem reprocessar
    XML), devolvendo uma amostra (até 'limite' linhas) e o total real de
    linhas. categoria='cfop' -> nfe_analise_et/ep; categoria='situacao' ->
    nfe_situacao_et/ep."""
    prefixo = "nfe_analise" if categoria.lower() == "cfop" else "nfe_situacao"
    tabela = f"{prefixo}_{fluxo.lower()}"
    if not _BANCO_PATH.exists():
        return pd.DataFrame(), 0
    try:
        with duckdb.connect(str(_BANCO_PATH), read_only=True) as con:
            tabelas = {r[0] for r in con.execute("SHOW TABLES").fetchall()}
            if tabela not in tabelas:
                return pd.DataFrame(), 0
            total = con.execute(f"SELECT COUNT(*) FROM {tabela}").fetchone()[0]
            df = con.execute(f"SELECT * FROM {tabela} LIMIT {limite}").df()
        return df, total
    except Exception:
        logger.exception("Erro ao consultar %s em %s", tabela, _BANCO_PATH)
        return pd.DataFrame(), 0


def gerar_dados_analise() -> dict:
    """Gera (via _classificar_itens_nfe, cacheada) e persiste isoladamente as
    4 tabelas de segregação (nfe_analise_et/ep + nfe_situacao_et/ep) — ação
    sob demanda (botão dedicado), sem reprocessar nfe_entradas/nfe_saidas
    nem o SPED. Sempre cria as quatro tabelas (mesmo vazias) para que
    analise_ja_gerada() rastreie corretamente que a geração já rodou."""
    classificado = _classificar_itens_nfe()
    _BANCO_PATH.parent.mkdir(parents=True, exist_ok=True)
    resultado = {}
    try:
        with duckdb.connect(str(_BANCO_PATH)) as con:
            for tabela, chave in _CHAVES_SEGREGACAO.items():
                df = classificado[chave]
                con.register("_df_tmp_analise", df)
                con.execute(f"CREATE OR REPLACE TABLE {tabela} AS SELECT * FROM _df_tmp_analise")
                con.unregister("_df_tmp_analise")
                resultado[tabela] = len(df)
    except Exception as exc:
        logger.exception("Erro ao persistir tabelas de análise: %s", exc)
        resultado["erro"] = str(exc)
    return resultado


def persistir_banco(callback=None) -> dict:
    """Persiste NF-e + SPED em sequência. Mantido para uso no CLI (__main__)."""
    res = {}
    res.update(persistir_nfe(callback))
    res.update(persistir_sped(callback))
    return res


def bc3_ja_gerada() -> bool:
    """True se a tabela bc3 (resultado do Matching BC2 x BC1) já existe no
    DuckDB da operação (mesma lógica de dados_ja_carregados/analise_ja_gerada)."""
    if not _BANCO_PATH.exists():
        return False
    try:
        with duckdb.connect(str(_BANCO_PATH), read_only=True) as con:
            tabelas = {r[0] for r in con.execute("SHOW TABLES").fetchall()}
            return "bc3" in tabelas
    except Exception:
        logger.exception("Erro ao verificar tabela bc3 existente em %s", _BANCO_PATH)
        return False


def consultar_bc3(limite: "int | None" = 200) -> "tuple[pd.DataFrame, int]":
    """Lê a tabela bc3 já persistida (sem reprocessar o matching), devolvendo
    uma amostra (até 'limite' linhas) e o total real de linhas. limite=None
    devolve a tabela inteira (usado para exportação completa, não para a
    prévia na tela)."""
    if not _BANCO_PATH.exists():
        return pd.DataFrame(), 0
    try:
        with duckdb.connect(str(_BANCO_PATH), read_only=True) as con:
            tabelas = {r[0] for r in con.execute("SHOW TABLES").fetchall()}
            if "bc3" not in tabelas:
                return pd.DataFrame(), 0
            total = con.execute("SELECT COUNT(*) FROM bc3").fetchone()[0]
            query = "SELECT * FROM bc3" if limite is None else f"SELECT * FROM bc3 LIMIT {limite}"
            df = con.execute(query).df()
        return df, total
    except Exception:
        logger.exception("Erro ao consultar bc3 em %s", _BANCO_PATH)
        return pd.DataFrame(), 0


def consultar_totais_bc3() -> dict:
    """Retorna a contagem de itens da BC3 por tipo de match (TIPO_1, TIPO_2,
    TIPO_3, TIPO_4, ND, NM), lendo direto do DuckDB (sem reprocessar) —
    alimenta os KPIs do painel de Matching. Rótulos de versões anteriores da
    lógica de matching (SECUNDARIO_FUZZY, SECUNDARIO_GTIN, PRINCIPAL_VALOR)
    podem ainda aparecer em bases já geradas antes dessas mudanças e não
    regeradas — por isso não são somados a nenhum tipo atual, só deixam de
    ter contador próprio."""
    totais = {"TIPO_1": 0, "TIPO_2": 0, "TIPO_3": 0, "TIPO_4": 0, "ND": 0, "NM": 0}
    if not _BANCO_PATH.exists():
        return totais
    try:
        with duckdb.connect(str(_BANCO_PATH), read_only=True) as con:
            tabelas = {r[0] for r in con.execute("SHOW TABLES").fetchall()}
            if "bc3" not in tabelas:
                return totais
            linhas = con.execute("SELECT MATCH_TIPO, COUNT(*) FROM bc3 GROUP BY MATCH_TIPO").fetchall()
            for tipo, n in linhas:
                if tipo in totais:
                    totais[tipo] = n
    except Exception:
        logger.exception("Erro ao consultar totais da bc3 em %s", _BANCO_PATH)
    return totais


def persistir_bc3(callback=None) -> dict:
    """Executa o Matching (Etapa 1 — BC2 x BC1, ver matching.py) e persiste
    o resultado na tabela bc3. Import de matching.py feito dentro da função
    (lazy import) para evitar import circular, já que matching.py importa
    loader.py para ler BC2/BC1."""
    import matching  # lazy import — ver docstring
    _BANCO_PATH.parent.mkdir(parents=True, exist_ok=True)
    resultado = {}
    try:
        df_bc3, meta = matching.executar_matching()
        with duckdb.connect(str(_BANCO_PATH)) as con:
            if not df_bc3.empty:
                con.register("_df_bc3", df_bc3)
                con.execute("CREATE OR REPLACE TABLE bc3 AS SELECT * FROM _df_bc3")
                con.unregister("_df_bc3")
        resultado["bc3"] = len(df_bc3)
        resultado["meta"] = meta
        if callback:
            callback("bc3", resultado["bc3"])
    except Exception as exc:
        logger.exception("Erro ao persistir BC3: %s", exc)
        resultado["erro"] = str(exc)
    return resultado


def carregar_operacao(progresso=None) -> list:
    """Ponto de entrada único da carga: escaneia nfe_path/ por XML pendentes e
    classifica cada um em ET/EP. Usuário só precisa apontar a operação (já
    implícito — a ESSENCIAL/ roda dentro da pasta da operação).

    Cargas podem ser grandes — se 'progresso' for informado (callable), é
    chamado como progresso(indice, total, resultado) logo após cada arquivo
    ser processado, para acompanhamento em tempo real (painel ou console)."""
    config = load_config()
    pendentes = _localizar_xmls_pendentes(config)
    total = len(pendentes)
    resultados = []
    for indice, caminho in enumerate(pendentes, start=1):
        resultado = processar_arquivo_pendente(caminho)
        resultados.append(resultado)
        if progresso:
            progresso(indice, total, resultado)
    return resultados


def pre_visualizar_carga() -> dict:
    """Resumo do que existe/está pendente, sem gravar nada — para o usuário
    conferir antes de confirmar a carga (quantidade + caminho por pasta, e uma
    previsão de classificação ET/EP/rejeitado para os XML ainda pendentes)."""
    config       = load_config()
    pasta_nfe    = _resolver_path(config, "nfe_path", "1-DOCFISCAIS/nf")
    pasta_sped   = _resolver_path(config, "sped_path", "2-DECLARACAO/SPED")
    et_arquivos  = _localizar_arquivos_nfe_subpasta(config, "ET")
    ep_arquivos  = _localizar_arquivos_nfe_subpasta(config, "EP")
    sped_arquivos = _localizar_arquivos_sped(config)
    pendentes    = _localizar_xmls_pendentes(config)

    previsao_et = previsao_ep = previsao_rejeitado = 0
    for caminho in pendentes:
        resultado = classificar_xml_nfe(caminho.name, caminho.read_bytes())
        if resultado["pasta"] == "ET":
            previsao_et += 1
        elif resultado["pasta"] == "EP":
            previsao_ep += 1
        else:
            previsao_rejeitado += 1

    return {
        "et":          {"quantidade": len(et_arquivos),   "caminho": str(pasta_nfe / "ET")},
        "ep":          {"quantidade": len(ep_arquivos),   "caminho": str(pasta_nfe / "EP")},
        "declaracoes": {"quantidade": len(sped_arquivos), "caminho": str(pasta_sped)},
        "pendentes": {
            "quantidade":          len(pendentes),
            "caminho":             str(pasta_nfe),
            "previsao_et":         previsao_et,
            "previsao_ep":         previsao_ep,
            "previsao_rejeitado":  previsao_rejeitado,
        },
    }


@st.cache_data(ttl=1800, show_spinner=False)
def load_declaracao_estoque() -> "tuple[pd.DataFrame, dict]":
    """Carrega o inventário da declaração (registro H010 — estoque real, não o template ESTOQUE/base.csv)."""
    config   = load_config()
    arquivos = _localizar_arquivos_sped(config)
    meta: dict = {"arquivos": [str(a) for a in arquivos], "origem_dados": "DECLARACAO_ESTOQUE", "erros": []}

    if not arquivos:
        meta["erros"].append(f"Nenhum arquivo SPED encontrado em {_resolver_path(config, 'sped_path', '2-DECLARACAO/SPED')}")
        return pd.DataFrame(), meta

    df = _parse_registros_sped(arquivos, "H010", _CAMPOS_H010)
    if df.empty:
        meta["erros"].append("Nenhum registro H010 encontrado nos arquivos SPED.")
        return df, meta

    meta["total_linhas"]  = len(df)
    meta["total_colunas"] = len(df.columns)
    meta["colunas"]       = df.columns.tolist()
    return df, meta


if __name__ == "__main__":
    # Ponto de entrada para carregar_xml.bat — roda fora do Streamlit, aponta
    # para a operação via HUNTER_OPERACAO_DIR (ou a própria pasta-pai, se a
    # variável não estiver definida). Mostra prévia, pede confirmação e exibe
    # progresso em tempo real — cargas podem ser grandes, o usuário acompanha.
    print(f"Operacao: {nome_operacao()}")
    _resumo = pre_visualizar_carga()
    print(f"{_resumo['et']['quantidade']} arquivo(s) em ET: {_resumo['et']['caminho']}")
    print(f"{_resumo['ep']['quantidade']} arquivo(s) em EP: {_resumo['ep']['caminho']}")
    print(f"{_resumo['declaracoes']['quantidade']} arquivo(s) de declaracao (SPED): {_resumo['declaracoes']['caminho']}")

    _pend = _resumo["pendentes"]
    if _pend["quantidade"] == 0:
        print(f"Nenhum XML pendente em {_pend['caminho']}")
        sys.exit(0)

    print(
        f"{_pend['quantidade']} XML pendente(s) em {_pend['caminho']} "
        f"(previsao: {_pend['previsao_et']} para ET, {_pend['previsao_ep']} para EP, "
        f"{_pend['previsao_rejeitado']} nao identificado(s))"
    )

    _resposta = input("Deseja efetuar a carga? (S/N): ").strip().upper()
    if _resposta != "S":
        print("Operacao cancelada pelo usuario.")
        sys.exit(0)

    _log_dir = _OPERACAO_DIR / "logs"
    _log_dir.mkdir(parents=True, exist_ok=True)
    _log_path = _log_dir / f"carga_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"

    def _emitir(msg: str) -> None:
        print(msg)
        with open(_log_path, "a", encoding="utf-8") as _f:
            _f.write(msg + "\n")

    def _progresso(indice, total, resultado):
        _emitir(f"[{indice}/{total}] {resultado}")

    carregar_operacao(progresso=_progresso)

    _emitir("Atualizando banco de dados...")

    def _cb_banco(etapa: str, n: int) -> None:
        _emitir(f"  {etapa}: {n} registros")

    _res_banco = persistir_banco(callback=_cb_banco)
    if "erro" in _res_banco:
        _emitir(f"ERRO ao atualizar banco: {_res_banco['erro']}")
    else:
        _total = sum(v for k, v in _res_banco.items() if k != "erro")
        _emitir(f"Banco atualizado: {_total} registros no total.")
    _emitir(f"Log salvo em: {_log_path}")
