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
import numpy as np
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
# nfe_saidas normalmente) — não está na watchlist global nem na de ET. CFOP
# 5927/6927 em registros de EP também NÃO é segregado (flui normalmente) —
# 2026-07-16: uma tentativa de estender a watchlist de EP pra 5927/6927
# (achado da operação cometa: autoemissão com esse CFOP inflando
# estoque_entradas) foi revertida — confirmado pelo usuário que 5927/6927
# roda normalmente em EP, a exclusão é exclusiva de ET.

# Modelo 65 (NFC-e) é vedado para registro de entrada pelo declarante (Guia
# Prático da EFD) — item de ET com esse modelo é segregado independente de
# situação/CFOP, mesmo critério de bloqueio dos demais grupos de análise
# acima. Não se aplica a EP (NFC-e em saída/venda ao consumidor é normal).
_COL_MODELO_NFE  = "fatonfe_infnfe_ide_mod"
_MODELO_NFCE     = "65"   # Regra Operacional R07: modelo como string

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


# ── Estágio 1 — Período de Auditoria (trava inicial de escopo temporal) ────
# Define o intervalo de anos que a auditoria cobre — gravado uma única vez
# por operação (config_auditoria, 1 linha, CREATE OR REPLACE substitui a
# anterior). Alimenta o resumo informativo de quais pastas de XML/SPED
# precisam existir pra garantir os cruzamentos de "virada de ano" (Estágio
# 4 — DATA_ELEITA; Estágio 5 — continuidade Estoque Final/Inicial): a
# virada anterior ao início do período (XML de AnoInicial-1) e o
# fechamento de inventário do fim do período (Declarações de AnoFinal+1).

def salvar_periodo_auditoria(ano_inicial: str, ano_final: str) -> None:
    """Grava o período de auditoria (Estágio 1) em `config_auditoria` no
    DuckDB da operação — sempre 1 linha (`CREATE OR REPLACE` substitui a
    config anterior, mesmo padrão de outras tabelas de configuração única
    deste projeto). Regra Operacional R07: anos sempre string."""
    _BANCO_PATH.parent.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame({"ano_inicial": [str(ano_inicial)], "ano_final": [str(ano_final)]})
    with duckdb.connect(str(_BANCO_PATH)) as con:
        con.register("_df_config_auditoria", df)
        con.execute("CREATE OR REPLACE TABLE config_auditoria AS SELECT * FROM _df_config_auditoria")
        con.unregister("_df_config_auditoria")


def obter_periodo_auditoria() -> "dict | None":
    """Lê o período de auditoria já gravado (`config_auditoria`) — `None`
    se ainda não foi definido (tabela/banco ainda não existem) ou em caso
    de erro de leitura."""
    if not _BANCO_PATH.exists():
        return None
    try:
        with duckdb.connect(str(_BANCO_PATH), read_only=True) as con:
            tabelas = {r[0] for r in con.execute("SHOW TABLES").fetchall()}
            if "config_auditoria" not in tabelas:
                return None
            linha = con.execute("SELECT ano_inicial, ano_final FROM config_auditoria LIMIT 1").fetchone()
        if linha is None:
            return None
        return {"ano_inicial": str(linha[0]), "ano_final": str(linha[1])}
    except Exception:
        logger.exception("Erro ao ler config_auditoria em %s", _BANCO_PATH)
        return None


_TABELAS_XML_COBERTURA = (
    "nfe_entradas", "nfe_saidas", "nfe_analise_et", "nfe_analise_ep",
    "nfe_situacao_et", "nfe_situacao_ep",
)


def verificar_cobertura_periodo() -> dict:
    """Estágio 1 — Alerta de Carga: confere se os dados já persistidos
    (XML e SPED) cobrem os anos exigidos pelo Período de Auditoria já
    configurado (ver `obter_periodo_auditoria()`). Não bloqueia nada — é um
    alerta informativo, não um filtro de carga. Anos exigidos: XML de
    `AnoInicial-1` até `AnoFinal` (a virada anterior ao início do período já
    precisa da base de comparação); SPED de `AnoInicial` até `AnoFinal+1`
    (o inventário de fechamento do último ano) — mesma regra usada no
    resumo informativo de `interface.render_configuracao_periodo()`. Ano
    presente = pelo menos 1 registro daquele ano em qualquer tabela
    correspondente (não confere os 12 meses, só presença). `aplicavel` é
    `False` quando não há período configurado — nada a checar."""
    periodo = obter_periodo_auditoria()
    if not periodo:
        return {"aplicavel": False}

    ano_ini = int(periodo["ano_inicial"])
    ano_fim = int(periodo["ano_final"])
    anos_xml_necessarios = list(range(ano_ini - 1, ano_fim + 1))
    anos_sped_necessarios = list(range(ano_ini, ano_fim + 2))

    anos_xml_presentes: set = set()
    anos_sped_presentes: set = set()
    if _BANCO_PATH.exists():
        try:
            with duckdb.connect(str(_BANCO_PATH), read_only=True) as con:
                tabelas = {r[0] for r in con.execute("SHOW TABLES").fetchall()}
                tabelas_xml = [t for t in _TABELAS_XML_COBERTURA if t in tabelas]
                if tabelas_xml:
                    uniao = " UNION ALL ".join(
                        f"SELECT CAST('20' || SUBSTR(fatonfe_infprot_chnfe, 3, 2) AS INTEGER) AS ANO FROM {t}"
                        for t in tabelas_xml
                    )
                    linhas = con.execute(f"SELECT DISTINCT ANO FROM ({uniao})").fetchall()
                    anos_xml_presentes = {r[0] for r in linhas}
                if "sped_itens" in tabelas:
                    linhas = con.execute(
                        "SELECT DISTINCT CAST(SUBSTR(COMPETENCIA, 1, 4) AS INTEGER) AS ANO FROM sped_itens"
                    ).fetchall()
                    anos_sped_presentes = {r[0] for r in linhas}
        except Exception:
            logger.exception("Erro ao verificar cobertura do período em %s", _BANCO_PATH)

    return {
        "aplicavel": True,
        "ano_inicial": ano_ini,
        "ano_final": ano_fim,
        "anos_xml_necessarios": anos_xml_necessarios,
        "anos_xml_faltando": [a for a in anos_xml_necessarios if a not in anos_xml_presentes],
        "anos_sped_necessarios": anos_sped_necessarios,
        "anos_sped_faltando": [a for a in anos_sped_necessarios if a not in anos_sped_presentes],
    }


def anos_declaracao_disponiveis() -> set:
    """Anos de competência presentes nos arquivos brutos de 2-DECLARACAO/SPED
    (lido do registro 0000 via `_competencia_arquivo()`, sem depender de
    persistência prévia) — usado pelo aviso de Ancoragem de Estoque (Bloco H)
    em `interface.render_carga_operacao()`: o estoque final de um ano é
    declarado no SPED de competência do início do ano seguinte."""
    config = load_config()
    anos = set()
    for arquivo in _localizar_arquivos_sped(config):
        competencia = _competencia_arquivo(arquivo)
        if len(competencia) >= 4:
            anos.add(competencia[:4])
    return anos


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
    "entradas_real", "saidas_real",
)


@st.cache_data(ttl=1800, show_spinner=False)
def _classificar_itens_nfe() -> dict:
    """Lê todos os .txt de nfe_path (ET+EP) e segrega POR ITEM (não por chave
    inteira) em 8 grupos, sem descartar nenhum registro:
      1. situação inválida (fora de A/O — canceladas, denegadas, inutilizadas)
         -> nfe_situacao_et / nfe_situacao_ep (pelo CNPJ nunca ir ao cruzamento
         físico nem à conferência de CFOP simbólico);
      2. dentre os de situação válida, CFOP na watchlist (faturamento futuro,
         venda à ordem, baixa de estoque/ECF) OU, exclusivo de ET, modelo 65
         (NFC-e, vedado para entrada) -> nfe_analise_et / nfe_analise_ep;
      3. o restante (situação válida + CFOP fora da watchlist) -> entradas/
         saídas (fluxo principal de cruzamento), conforme o tpnf;
      4. desse mesmo restante, movimentação física real da auditada (não só
         tpnf isolado — cruza com o papel da auditada na nota, emitente ou
         destinatária, ver bloco "entradas/saídas reais" abaixo) ->
         entradas_real / saidas_real.
    Devolve {'entradas','saidas','analise_et','analise_ep','situacao_et',
    'situacao_ep','entradas_real','saidas_real': DataFrame, 'erros': list,
    'arquivos': list}."""
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

    modelo = combined[_COL_MODELO_NFE].astype(str).str.strip() if _COL_MODELO_NFE in combined.columns else pd.Series("", index=combined.index)

    mask_situacao_valida = situacao.isin(_SITUACOES_NFE_VALIDAS)
    mask_situacao_et = ~mask_situacao_valida & (pasta == "ET")
    mask_situacao_ep = ~mask_situacao_valida & (pasta == "EP")

    mask_cfop_et      = mask_situacao_valida & (pasta == "ET") & cfop.isin(_CFOP_WATCHLIST_GLOBAL | _CFOP_WATCHLIST_ET)
    mask_cfop_ep      = mask_situacao_valida & (pasta == "EP") & cfop.isin(_CFOP_WATCHLIST_GLOBAL | _CFOP_WATCHLIST_EP)
    mask_modelo65_et  = mask_situacao_valida & (pasta == "ET") & (modelo == _MODELO_NFCE)

    mask_analise_et = mask_cfop_et | mask_modelo65_et
    mask_analise_ep = mask_cfop_ep
    mask_principal  = mask_situacao_valida & ~(mask_analise_et | mask_analise_ep)

    # Rótulo do motivo de segregação (só preenchido nas linhas de
    # nfe_analise_et/ep) — alimenta a exibição no painel "SEGREGADOS"
    # (interface._COLUNAS_PREVIEW_ANALISE), distinguindo os dois critérios
    # de bloqueio sem precisar de uma nona tabela.
    combined["MOTIVO_SEGREGACAO"] = np.select(
        [mask_modelo65_et, mask_cfop_et | mask_cfop_ep],
        ["Modelo 65 Vedado em Entrada", "CFOP Não Autorizado"],
        default="",
    )

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

    # ── Entradas/saídas REAIS — movimentação física da auditada ─────────────
    # tpnf isolado (0=entrada/1=saída) reflete a perspectiva de quem EMITE a
    # NF-e, não necessariamente a da auditada: numa ET normal (fornecedor
    # emite, auditada é destinatária), o fornecedor registra tpnf=1 (saída
    # dele) para o que é, fisicamente, uma ENTRADA na auditada. Cruza tpnf
    # com o papel da auditada na nota (emit/dest, via CNPJ já fixado em
    # obter_entidade_auditada()) pra chegar na direção física real — ver
    # "regra de negócios unificadas/CNPJ EMIT = CNPJ DEST.txt" (raiz).
    # Roda só sobre mask_principal (situação válida + fora da watchlist) —
    # mesma base de entradas/saídas acima — pra conter só movimentação
    # física válida (situação irregular e CFOP de watchlist já segregados).
    entidade_auditada = obter_entidade_auditada()
    cnpj_auditada = (entidade_auditada or {}).get("cnpj")

    if cnpj_auditada:
        emit_cnpj = (
            combined["fatonfe_infnfe_emit_cnpj"].apply(_normalizar_cnpj)
            if "fatonfe_infnfe_emit_cnpj" in combined.columns
            else pd.Series("", index=combined.index)
        )
        dest_cnpj = (
            combined["fatonfe_infnfe_dest_cnpj"].apply(_normalizar_cnpj)
            if "fatonfe_infnfe_dest_cnpj" in combined.columns
            else pd.Series("", index=combined.index)
        )
        auditada_destinataria = dest_cnpj == cnpj_auditada
        auditada_emitente     = emit_cnpj == cnpj_auditada
    else:
        # Entidade auditada ainda não fixada (garantir_entidade_auditada()
        # não rodou) — sem CNPJ de referência não dá pra determinar o papel
        # da auditada na nota; grupos reais ficam vazios (não quebram a carga).
        auditada_destinataria = pd.Series(False, index=combined.index)
        auditada_emitente     = pd.Series(False, index=combined.index)

    # Autoemissão (emit_cnpj==dest_cnpj==cnpj_auditada, aqui capturada como
    # auditada_destinataria & auditada_emitente ambos True) com CFOP de baixa
    # de estoque (mesmo conjunto de _CFOP_WATCHLIST_ET — "5927"/"6927") na
    # pasta EP: achado real 2026-07-17, operação PB_2023_2025 (chaves
    # ...23605850/...23540314) — por ser autoemissão, a linha bate nos dois
    # papéis ao mesmo tempo e contava como ENTRADA real E saída real
    # simultaneamente, inflando estoque_entradas com o próprio lançamento
    # simbólico de baixa que a empresa já registra como saída. Exclusão só
    # de mask_entrada_real (não da watchlist de CFOP nem de mask_principal)
    # — nfe_saidas/xml_saidas_real continuam contando essas linhas
    # normalmente, só não duplicam também como entrada.
    mask_baixa_estoque_autoemissao_ep = (
        (pasta == "EP") & cfop.isin(_CFOP_WATCHLIST_ET) & auditada_destinataria & auditada_emitente
    )

    mask_entrada_real = mask_principal & (
        (auditada_destinataria & (tpnf == "1")) | (auditada_emitente & (tpnf == "0"))
    ) & ~mask_baixa_estoque_autoemissao_ep
    mask_saida_real = mask_principal & (
        (auditada_destinataria & (tpnf == "0")) | (auditada_emitente & (tpnf == "1"))
    )
    # Papel da auditada na nota (não é PASTA_ORIGEM/ET-EP por pasta — é o
    # papel real por CNPJ, ver bloco acima) — persistido junto com
    # entradas_real/saidas_real como alicerce do Estágio 4 (cenário A/B da
    # hierarquia de DATA_ELEITA, ver montar_estoque_entradas/_saidas()):
    # Cenário A (auditada destinatária) e Cenário B (auditada emitente) usam
    # prioridades diferentes de data.
    combined["AUDITADA_PAPEL"] = np.select(
        [auditada_destinataria, auditada_emitente],
        ["DESTINATARIA", "EMITENTE"],
        default="",
    )

    df_entradas_real = combined[mask_entrada_real].copy()
    df_entradas_real["ORIGEM_DADOS"] = "ENTRADAS_REAL"
    df_saidas_real = combined[mask_saida_real].copy()
    df_saidas_real["ORIGEM_DADOS"] = "SAIDAS_REAL"

    return {
        "entradas": df_entradas, "saidas": df_saidas,
        "analise_et": df_analise_et, "analise_ep": df_analise_ep,
        "situacao_et": df_situacao_et, "situacao_ep": df_situacao_ep,
        "entradas_real": df_entradas_real, "saidas_real": df_saidas_real,
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
    (faturamento futuro/venda à ordem/baixa de estoque) ou por modelo 65
    (NFC-e, vedado para entrada) — não entram no cruzamento principal, mas
    ficam preservados para análise (ver MOTIVO_SEGREGACAO)."""
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


def _dt_fin_arquivo(arquivo: Path) -> str:
    """Lê o registro 0000 do arquivo e devolve DT_FIN (Campo 05) — data final
    do período de apuração a que a declaração se refere (ex.: 31012024,
    DDMMAAAA cru, sem conversão), propagada depois pra todos os itens (C170)
    daquele arquivo (ver _parse_itens_c170_com_c100()). Usada para auditoria
    temporal: cruzar com DT_E_S do C170/C100 identifica escrituração
    extemporânea (nota de um mês declarada só no mês seguinte)."""
    for campos in _iter_linhas_sped(arquivo):
        if campos[1] == "0000":
            return campos[5] if len(campos) > 5 else ""
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


def _numero_decimal_br(serie: pd.Series) -> pd.Series:
    """Converte string numérica em formato BR (vírgula decimal, ex.:
    "33,60") pra float, tolerando também vir em ponto — o SPED/EFD grava
    campos numéricos com vírgula, mas alguns valores já vêm em ponto.
    Mesma lógica de matching._valor_numerico(), duplicada aqui (não
    importada) porque loader.py é importado por matching.py — importar de
    volta criaria ciclo."""
    return pd.to_numeric(
        serie.astype(str).str.strip().str.replace(",", ".", regex=False),
        errors="coerce",
    )


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
    """Percorre C100/C170 sequencialmente — cada C170 herda dados do C100 mais
    recente, inclusive DT_E_S (Campo 11 do C100 — data de entrada/saída
    efetiva da mercadoria) e DT_FIN (Campo 05 do Registro 0000 — data final
    do período de apuração do arquivo), usadas para auditoria temporal
    (identificar escrituração extemporânea)."""
    linhas = []
    for arquivo in arquivos:
        competencia = _competencia_arquivo(arquivo)
        dt_fin = _dt_fin_arquivo(arquivo)
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
                linha["DT_E_S"]         = c100_atual.get("DT_E_S", "")
                linha["DT_FIN"]         = dt_fin
                linha["COD_MOD"]        = c100_atual.get("COD_MOD", "")
                linha["COMPETENCIA"]    = competencia
                linha["ARQUIVO_ORIGEM"] = arquivo.name
                linhas.append(linha)
    df = pd.DataFrame(linhas)
    df = _forcar_colunas_string(
        df, ["COD_ITEM", "UNID", "CHV_NFE", "NUM_ITEM", "COD_PART", "DT_E_S", "DT_FIN"]
    )
    return _gerar_id_unico(df, ["CHV_NFE", "NUM_ITEM"])


def _parse_estoque_h005_h010(arquivos: list) -> pd.DataFrame:
    """Percorre H005/H010 sequencialmente — cada H010 herda DT_INV (Campo 02)
    e MOT_INV (Campo 04) do H005 mais recente (registro pai, ver Guia
    Prático EFD). Diferente de C100/C170 (repete N vezes por arquivo), H005
    aparece no máximo uma vez por arquivo — o inventário é declarado uma vez
    por ano, tipicamente no primeiro mês competente. Alicerce do Estágio 5
    (ver montar_estoque_anual_consolidado())."""
    linhas = []
    for arquivo in arquivos:
        h005_atual: dict = {}
        for campos in _iter_linhas_sped(arquivo):
            reg = campos[1]
            if reg == "H005":
                h005_atual = {
                    "DT_INV": campos[2] if len(campos) > 2 else "",
                    "VL_INV": campos[3] if len(campos) > 3 else "",
                    "MOT_INV": campos[4] if len(campos) > 4 else "",
                }
            elif reg == "H010":
                valores = campos[2:2 + len(_CAMPOS_H010)]
                valores += [""] * (len(_CAMPOS_H010) - len(valores))
                linha = dict(zip(_CAMPOS_H010, valores))
                linha["DT_INV"]         = h005_atual.get("DT_INV", "")
                linha["MOT_INV"]        = h005_atual.get("MOT_INV", "")
                linha["ARQUIVO_ORIGEM"] = arquivo.name
                linhas.append(linha)
    df = pd.DataFrame(linhas)
    return _forcar_colunas_string(df, ["COD_ITEM", "UNID", "DT_INV", "MOT_INV"])


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
    emitente via cadastro de participantes (0150, ligado por COD_PART).
    Inclui DT_E_S (Campo 11 do C100 — data de entrada/saída efetiva da
    mercadoria) e DT_FIN (Campo 05 do Registro 0000 — data final do período
    de apuração), herdados de load_declaracao_itens()/
    _parse_itens_c170_com_c100() sem filtragem adicional aqui — usados para
    auditoria temporal (escrituração extemporânea, ver REGRAS_MATCHING.md/
    docs/estagios). Os filtros de CFOP e situação (Regra Operacional R07)
    são exclusivos do lado XML (_carregar_nfe) — não se aplicam à declaração
    (EFD/SPED). COD_ITEM, UNID, CHV_NFE, CNPJ, DT_E_S e DT_FIN tratados como
    string."""
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

    # Valor unitário do produto na declaração: a BC1 (SPED/EFD) não traz um
    # campo de valor unitário direto no C170 — só QTD e VL_ITEM (valor total
    # da linha) — diferente da BC2 (XML), que traz o unitário faturado
    # (vUnCom) direto. Derivado aqui como VL_ITEM/QTD pra poder comparar com
    # o unitário do XML (_VALOR_UNIT_ORIGINAL) e sinalizar divergência de
    # unidade/embalagem entre as duas bases (ex.: XML fatura por caixa, SPED
    # escritura por unidade — o valor TOTAL do item pode bater mesmo assim,
    # mas o unitário difere por um fator múltiplo). QTD == 0 ou ausente
    # produz NaN (não dá pra derivar), sem tentar adivinhar.
    qtd_num = _numero_decimal_br(df["QTD"]) if "QTD" in df.columns else pd.Series(dtype=float)
    vl_item_num = _numero_decimal_br(df["VL_ITEM"]) if "VL_ITEM" in df.columns else pd.Series(dtype=float)
    df["VALOR_UNITARIO_DECLARACAO"] = (vl_item_num / qtd_num.replace(0, np.nan)).round(4)

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
    denegadas, inutilizadas), xml_entradas_real/xml_saidas_real (mesmo
    universo de nfe_entradas/nfe_saidas, mas reclassificado pela
    movimentação física real da auditada — tpnf cruzado com o papel dela
    na nota, emitente ou destinatária — ver _classificar_itens_nfe()) e
    nfe_bc2 (Base Comparativa 2 — itens de Emissão de Terceiros já com
    nomes de coluna normalizados para cruzar com a BC1/SPED).
    callback(etapa, n) chamado apos cada tabela. Retorna {tabela: n_linhas}."""
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
                # xml_entradas_real/xml_saidas_real também sempre criadas
                # (mesmo vazias, ex.: entidade auditada ainda não fixada) —
                # o painel principal consulta essas tabelas direto.
                ("xml_entradas_real", "entradas_real", "_df_xml_entradas_real", True),
                ("xml_saidas_real",   "saidas_real",   "_df_xml_saidas_real",   True),
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


_TABELAS_ENTRADAS_SAIDAS_REAL = ("xml_entradas_real", "xml_saidas_real")
_TABELAS_ENTRADAS_SAIDAS_REAL_POR_DIRECAO = {
    "entradas": "xml_entradas_real", "saidas": "xml_saidas_real",
}


def consultar_totais_entradas_saidas_real() -> dict:
    """Retorna {'xml_entradas_real': n, 'xml_saidas_real': n} lendo direto do
    DuckDB (sem reprocessar) — alimenta os KPIs do painel principal (Carga de
    XML) com a movimentação física real da auditada (ver _classificar_itens_nfe()).
    0 tanto se a tabela ainda não existe (carga não rodou) quanto se existe
    vazia (ex.: entidade auditada ainda não fixada em obter_entidade_auditada())."""
    totais = {t: 0 for t in _TABELAS_ENTRADAS_SAIDAS_REAL}
    if not _BANCO_PATH.exists():
        return totais
    try:
        with duckdb.connect(str(_BANCO_PATH), read_only=True) as con:
            tabelas = {r[0] for r in con.execute("SHOW TABLES").fetchall()}
            for tabela in totais:
                if tabela in tabelas:
                    totais[tabela] = con.execute(f"SELECT COUNT(*) FROM {tabela}").fetchone()[0]
    except Exception:
        logger.exception("Erro ao consultar totais de entradas/saídas reais em %s", _BANCO_PATH)
    return totais


def _montar_join_bc3(con, tabelas: set, incluir_match: bool = False) -> "tuple[str, str]":
    """Monta os fragmentos SQL (colunas, join) pra trazer os campos da bc3
    (Estágio 2 — Matching) via LEFT JOIN por ID_UNICO — reusado por
    consultar_fluxo_real() (Estágio 3), _enriquecer_fluxo_real_com_bc3()
    (Estágio 4) e consultar_nfe_entradas_bc3() (prévia do Estágio 2). LEFT
    JOIN (não INNER) pra não descartar item sem bc3 gerada ainda ou sem
    correspondência. Degrada graciosamente com colunas NULL tipadas quando a
    tabela bc3 não existe, ou quando existe mas é de uma versão anterior à
    propagação de DT_E_S/DT_FIN (checa o schema antes de referenciar essas
    duas colunas — as demais, COD_ITEM_DECLARACAO/DESCR_ITEM_DECLARACAO/
    FATOR_MULTIPLICADOR_SUGERIDO, existem desde a primeira versão da bc3, ver
    matching.py). incluir_match=True também traz MATCH_TIPO/MATCH_SCORE (só
    usado pela prévia enriquecida do Estágio 2, consultar_nfe_entradas_bc3())."""
    tem_bc3 = "bc3" in tabelas
    colunas_schema_bc3 = (
        {r[0] for r in con.execute("DESCRIBE bc3").fetchall()} if tem_bc3 else set()
    )
    tem_datas_bc3 = "DT_E_S" in colunas_schema_bc3
    colunas = (
        "b.COD_ITEM_DECLARACAO, b.DESCR_ITEM_DECLARACAO, b.FATOR_MULTIPLICADOR_SUGERIDO"
        if tem_bc3 else
        "CAST(NULL AS VARCHAR) AS COD_ITEM_DECLARACAO, "
        "CAST(NULL AS VARCHAR) AS DESCR_ITEM_DECLARACAO, "
        "CAST(NULL AS DOUBLE) AS FATOR_MULTIPLICADOR_SUGERIDO"
    )
    if incluir_match:
        colunas += (
            ", b.MATCH_TIPO, b.MATCH_SCORE" if tem_bc3 else
            ", CAST(NULL AS VARCHAR) AS MATCH_TIPO, CAST(NULL AS DOUBLE) AS MATCH_SCORE"
        )
    colunas += (
        ", b.DT_E_S, b.DT_FIN" if tem_datas_bc3 else
        ", CAST(NULL AS VARCHAR) AS DT_E_S, CAST(NULL AS VARCHAR) AS DT_FIN"
    )
    join = "LEFT JOIN bc3 b ON n.ID_UNICO = b.ID_UNICO" if tem_bc3 else ""
    return colunas, join


def consultar_fluxo_real(direcao: str, limite: "int | None" = 200) -> "tuple[pd.DataFrame, int]":
    """Lê xml_entradas_real (direcao='entradas') ou xml_saidas_real
    (direcao='saidas') já persistidas (sem reprocessar) — mesma movimentação
    física real da auditada de consultar_totais_entradas_saidas_real().
    Enriquecida com COD_ITEM_DECLARACAO/DESCR_ITEM_DECLARACAO/
    FATOR_MULTIPLICADOR_SUGERIDO/DT_E_S/DT_FIN da bc3 (Estágio 2 — Matching)
    via LEFT JOIN por ID_UNICO (ver _montar_join_bc3()) — mesmo
    enriquecimento usado pelo Estágio 4 (_enriquecer_fluxo_real_com_bc3()),
    aqui só para exibição (não persiste nada). Item sem bc3 gerada ainda ou
    sem correspondência fica com essas colunas NULL, nunca é descartado.
    Mesmo padrão de consultar_bc3()/consultar_entradas_terceiros(): devolve
    uma amostra (até 'limite' linhas) e o total real. limite=None devolve a
    tabela inteira. direcao fora de {'entradas','saidas'} devolve vazio."""
    tabela = _TABELAS_ENTRADAS_SAIDAS_REAL_POR_DIRECAO.get(direcao)
    if tabela is None or not _BANCO_PATH.exists():
        return pd.DataFrame(), 0
    try:
        with duckdb.connect(str(_BANCO_PATH), read_only=True) as con:
            tabelas = {r[0] for r in con.execute("SHOW TABLES").fetchall()}
            if tabela not in tabelas:
                return pd.DataFrame(), 0
            colunas_bc3, join_bc3 = _montar_join_bc3(con, tabelas)
            base_sql = f"SELECT n.*, {colunas_bc3} FROM {tabela} n {join_bc3}"
            total = con.execute(f"SELECT COUNT(*) FROM ({base_sql})").fetchone()[0]
            query = base_sql if limite is None else f"{base_sql} LIMIT {limite}"
            df = con.execute(query).df()
        # Regra Operacional R07: colunas expandidas da declaração seguem como
        # string, preservando NULL genuíno (item sem bc3/join sem
        # correspondência) em vez de virar o literal "None" na tela — mesmo
        # tratamento de consultar_nfe_entradas_bc3().
        for col in ("COD_ITEM_DECLARACAO", "DESCR_ITEM_DECLARACAO", "DT_E_S", "DT_FIN"):
            if col in df.columns:
                df[col] = df[col].where(df[col].isna(), df[col].astype(str))
        return df, total
    except Exception:
        logger.exception("Erro ao consultar %s em %s", tabela, _BANCO_PATH)
        return pd.DataFrame(), 0


# ── Estágio 4 — Cronologia e Ano Eleito (estoque_entradas/estoque_saidas) ───
# DATA_ELEITA/ANO_ELEITO: hierarquia de datas por cenário ("Figura 1"),
# aplicada sobre xml_entradas_real/xml_saidas_real (Estágio 3) enriquecidos
# com DT_E_S/DT_FIN da bc3 (Estágio 2 — Matching, propagados em
# matching.executar_matching(), ver REGRAS_MATCHING.md).
#   Cenário A (AUDITADA_PAPEL='DESTINATARIA', ET): DT_E_S > DT_FIN >
#     dhSaiEnt (XML) > dhEmi (XML).
#   Cenário B (AUDITADA_PAPEL='EMITENTE', EP): dhSaiEnt (XML) > DT_E_S >
#     DT_FIN > dhEmi (XML).
# 'nd'/'nm' (sentinelas da bc3 — item não declarado/sem match) e NULL
# genuíno (LEFT JOIN sem correspondência) são tratados como ausentes —
# cascade automático pras prioridades seguintes, sem checar MATCH_TIPO
# explicitamente: o valor sentinela/NULL já reprova a validação de formato.
# DATA_ORIGINAL/ANO_ORIGINAL: dado "cru" do XML (dhEmi), sempre o mesmo pros
# dois cenários — não passa pela hierarquia acima, existe só pra auditoria
# de conformidade (medir a defasagem entre emissão do fornecedor e
# DATA_ELEITA/escrituração real). Confirmado com o usuário em 2026-07-15
# que essa hierarquia (DATA_ELEITA priorizando SPED sobre XML pro ET) é a
# regra final — ver docs/estagios/04_cronologia_ano_eleito.md.
# DATA_ELEITA_ORIGEM: rótulo simplificado ('declaração'/'xml') da fonte que
# venceu a hierarquia — ver _ORIGEM_POR_COLUNA logo abaixo.
_COL_DHSAIENT_XML = "fatonfe_infnfe_ide_dhsaient"  # campo opcional do XML
# (dhSaiEnt); não populado neste pipeline de extração até a data desta
# implementação (2026-07-12) — ausente da tabela, cascade automático pra
# próxima prioridade. Mantido pelo nome pra funcionar sozinho se a extração
# passar a trazê-lo no futuro.
_COL_DHEMI_XML = "fatonfe_infnfe_ide_dhemi"

_ORDEM_CENARIO_A_ET = ["DT_E_S", "DT_FIN", _COL_DHSAIENT_XML, _COL_DHEMI_XML]
_ORDEM_CENARIO_B_EP = [_COL_DHSAIENT_XML, "DT_E_S", "DT_FIN", _COL_DHEMI_XML]

# DATA_ELEITA_ORIGEM (2026-07-15): rótulo simplificado da fonte que venceu a
# hierarquia acima, pra filtro rápido do auditor e futuro KPI de "Aderência à
# Escrituração" — 'declaração' quando veio do SPED (DT_E_S/DT_FIN), 'xml'
# quando veio do documento fiscal (dhSaiEnt/dhEmi). Não existem rótulos mais
# detalhados antes desta implementação (não havia coluna de origem alguma).
_ORIGEM_DECLARACAO = "declaração"
_ORIGEM_XML = "xml"
_ORIGEM_POR_COLUNA = {
    "DT_E_S": _ORIGEM_DECLARACAO,
    "DT_FIN": _ORIGEM_DECLARACAO,
    _COL_DHSAIENT_XML: _ORIGEM_XML,
    _COL_DHEMI_XML: _ORIGEM_XML,
}


def _so_string_valida(serie: pd.Series, regex: str) -> pd.Series:
    """Valida uma série de datas contra 'regex' (fullmatch). NaN genuíno
    (ex.: LEFT JOIN sem correspondência em bc3) e valores fora do padrão
    (inclusive sentinelas 'nd'/'nm') viram NaN — nunca convertidos na string
    literal 'None'/'nan' (só stringifica valores realmente presentes)."""
    presente = serie.notna()
    valores_str = pd.Series(np.nan, index=serie.index, dtype=object)
    valores_str.loc[presente] = serie.loc[presente].astype(str).str.strip()
    bate = valores_str.notna() & valores_str.str.fullmatch(regex).fillna(False)
    return valores_str.where(bate)


def _candidato_data_ano(df: pd.DataFrame, coluna: str) -> "tuple[pd.Series, pd.Series]":
    """Valida e extrai (valor, ano) de uma coluna candidata da hierarquia de
    DATA_ELEITA — formato SPED DDMMAAAA (DT_E_S/DT_FIN, vindas da BC1 via
    bc3) ou ISO 8601 (campos do XML, dhEmi/dhSaiEnt). Coluna ausente do
    DataFrame (ex.: dhSaiEnt não extraído) devolve tudo NaN — cascade
    automático pra próxima prioridade."""
    if coluna not in df.columns:
        vazio = pd.Series(np.nan, index=df.index, dtype=object)
        return vazio, vazio
    if coluna in ("DT_E_S", "DT_FIN"):
        valor = _so_string_valida(df[coluna], r"\d{8}")
        ano = valor.where(valor.isna(), valor.str[4:8])
    else:
        valor = _so_string_valida(df[coluna], r"\d{4}-\d{2}-\d{2}.*")
        ano = valor.where(valor.isna(), valor.str[:4])
    return valor, ano


def _aplicar_hierarquia_data(df: pd.DataFrame, ordem: "list[str]") -> "tuple[pd.Series, pd.Series, pd.Series]":
    """Aplica a hierarquia de datas (Figura 1): 'ordem' é a lista de colunas
    candidatas já na ordem de prioridade (1a a 4a). Usa a 1a data válida
    encontrada (pandas combine_first) tanto pro valor cru (DATA_ELEITA)
    quanto pro ano (ANO_ELEITO) e pro rótulo de origem (DATA_ELEITA_ORIGEM,
    'declaração'/'xml' — ver _ORIGEM_POR_COLUNA) — os três sempre alinhados,
    porque origem/ano são derivados da mesma validação em
    _candidato_data_ano(). Devolve (data_eleita, ano_eleito,
    data_eleita_origem), string, vazias quando nenhuma das 4 fontes tem data
    válida (Regra Operacional R07 — sem inferência numérica)."""
    valor_final = pd.Series(np.nan, index=df.index, dtype=object)
    ano_final = pd.Series(np.nan, index=df.index, dtype=object)
    origem_final = pd.Series(np.nan, index=df.index, dtype=object)
    for coluna in ordem:
        valor, ano = _candidato_data_ano(df, coluna)
        valor_final = valor_final.combine_first(valor)
        ano_final = ano_final.combine_first(ano)
        origem_candidata = pd.Series(_ORIGEM_POR_COLUNA[coluna], index=df.index, dtype=object).where(valor.notna())
        origem_final = origem_final.combine_first(origem_candidata)
    return (
        valor_final.fillna("").astype(str),
        ano_final.fillna("").astype(str),
        origem_final.fillna("").astype(str),
    )


def _enriquecer_fluxo_real_com_bc3(direcao: str) -> pd.DataFrame:
    """Lê xml_entradas_real/xml_saidas_real (Estágio 3, já persistida) e
    enriquece com COD_ITEM_DECLARACAO/DESCR_ITEM_DECLARACAO/
    FATOR_MULTIPLICADOR_SUGERIDO/DT_E_S/DT_FIN da bc3 (Estágio 2 — Matching)
    via LEFT JOIN por ID_UNICO (ver _montar_join_bc3()). Alicerce do Estágio
    4 — colunas ausentes (bc3 não gerada ou sem correspondência) ficam NULL
    (cascade automático pro XML em _candidato_data_ano() para as datas)."""
    tabela = _TABELAS_ENTRADAS_SAIDAS_REAL_POR_DIRECAO.get(direcao)
    if tabela is None or not _BANCO_PATH.exists():
        return pd.DataFrame()
    try:
        with duckdb.connect(str(_BANCO_PATH), read_only=True) as con:
            tabelas = {r[0] for r in con.execute("SHOW TABLES").fetchall()}
            if tabela not in tabelas:
                return pd.DataFrame()
            colunas_bc3, join_bc3 = _montar_join_bc3(con, tabelas)
            df = con.execute(f"SELECT n.*, {colunas_bc3} FROM {tabela} n {join_bc3}").df()
        return df
    except Exception:
        logger.exception("Erro ao enriquecer %s com bc3 em %s", tabela, _BANCO_PATH)
        return pd.DataFrame()


def _aplicar_data_eleita(df: pd.DataFrame) -> pd.DataFrame:
    """Cria DATA_ELEITA/ANO_ELEITO/DATA_ELEITA_ORIGEM em 'df' (precisa de
    AUDITADA_PAPEL, DT_E_S, DT_FIN, dhSaiEnt/dhEmi já presentes — ver
    montar_estoque_entradas()/montar_estoque_saidas()): Cenário A
    (AUDITADA_PAPEL='DESTINATARIA', ET) usa _ORDEM_CENARIO_A_ET; Cenário B
    (AUDITADA_PAPEL='EMITENTE', EP) usa _ORDEM_CENARIO_B_EP.
    DATA_ELEITA_ORIGEM é o rótulo simplificado da fonte que venceu —
    'declaração' (DT_E_S/DT_FIN) ou 'xml' (dhSaiEnt/dhEmi), ver
    _ORIGEM_POR_COLUNA. Também cria DATA_ORIGINAL/ANO_ORIGINAL — dado "cru"
    do XML (dhEmi), sempre igual pros dois cenários, nunca tocado pela
    hierarquia acima (campo de auditoria paralelo, pra medir a defasagem
    entre emissão do fornecedor e DATA_ELEITA). Regra R07: DATA_ELEITA/
    ANO_ELEITO/DATA_ELEITA_ORIGEM/DATA_ORIGINAL/ANO_ORIGINAL sempre string
    ("" quando dhEmi ausente/inválido, nunca NULL)."""
    df = df.copy()
    papel = df["AUDITADA_PAPEL"] if "AUDITADA_PAPEL" in df.columns else pd.Series("", index=df.index)
    mask_cenario_a = papel == "DESTINATARIA"

    data_a, ano_a, origem_a = _aplicar_hierarquia_data(df, _ORDEM_CENARIO_A_ET)
    data_b, ano_b, origem_b = _aplicar_hierarquia_data(df, _ORDEM_CENARIO_B_EP)

    df["DATA_ELEITA"]        = data_a.where(mask_cenario_a, data_b)
    df["ANO_ELEITO"]         = ano_a.where(mask_cenario_a, ano_b)
    df["DATA_ELEITA_ORIGEM"] = origem_a.where(mask_cenario_a, origem_b)

    data_original, ano_original = _candidato_data_ano(df, _COL_DHEMI_XML)
    df["DATA_ORIGINAL"] = data_original.fillna("").astype(str)
    df["ANO_ORIGINAL"]  = ano_original.fillna("").astype(str)
    return df


def montar_estoque_entradas() -> pd.DataFrame:
    """Estágio 4: xml_entradas_real (Estágio 3) enriquecido com
    COD_ITEM_DECLARACAO/DESCR_ITEM_DECLARACAO/FATOR_MULTIPLICADOR_SUGERIDO/
    DT_E_S/DT_FIN da bc3 (Estágio 2) + DATA_ELEITA/ANO_ELEITO/
    DATA_ELEITA_ORIGEM (hierarquia da Figura 1 + rótulo 'declaração'/'xml'
    da fonte vencedora) + DATA_ORIGINAL/ANO_ORIGINAL (dhEmi cru, paralelo à
    hierarquia)."""
    return _aplicar_data_eleita(_enriquecer_fluxo_real_com_bc3("entradas"))


def montar_estoque_saidas() -> pd.DataFrame:
    """Estágio 4: xml_saidas_real (Estágio 3) enriquecido com
    COD_ITEM_DECLARACAO/DESCR_ITEM_DECLARACAO/FATOR_MULTIPLICADOR_SUGERIDO/
    DT_E_S/DT_FIN da bc3 (Estágio 2) + DATA_ELEITA/ANO_ELEITO/
    DATA_ELEITA_ORIGEM (hierarquia da Figura 1 + rótulo 'declaração'/'xml'
    da fonte vencedora) + DATA_ORIGINAL/ANO_ORIGINAL (dhEmi cru, paralelo à
    hierarquia). Na prática, a bc3 só cobre entradas de terceiros (BC2 x
    BC1), então COD_ITEM_DECLARACAO/DESCR_ITEM_DECLARACAO/
    FATOR_MULTIPLICADOR_SUGERIDO/DT_E_S/DT_FIN ficam NULL em
    estoque_saidas — mesmo caso já documentado para DT_E_S/DT_FIN (ver
    "Limitação real conhecida" em docs/estagios/04_cronologia_ano_eleito.md).
    DATA_ELEITA_ORIGEM fica sempre 'xml' em estoque_saidas nesta base, pelo
    mesmo motivo (sem BC1 de saídas, a hierarquia cai sempre pro XML).
    DATA_ORIGINAL/ANO_ORIGINAL não dependem da bc3 (só do XML), então ficam
    preenchidas normalmente também em estoque_saidas."""
    return _aplicar_data_eleita(_enriquecer_fluxo_real_com_bc3("saidas"))


_TABELAS_ESTOQUE = {
    "estoque_entradas": montar_estoque_entradas, "estoque_saidas": montar_estoque_saidas,
}
_TABELAS_ESTOQUE_POR_DIRECAO = {
    "entradas": "estoque_entradas", "saidas": "estoque_saidas",
}


def persistir_estoque_entradas_saidas(callback=None) -> dict:
    """Estágio 4: persiste estoque_entradas/estoque_saidas no DuckDB —
    xml_entradas_real/xml_saidas_real (Estágio 3) enriquecidos com
    COD_ITEM_DECLARACAO/DESCR_ITEM_DECLARACAO/FATOR_MULTIPLICADOR_SUGERIDO/
    DT_E_S/DT_FIN da bc3 (Estágio 2), DATA_ELEITA/ANO_ELEITO/
    DATA_ELEITA_ORIGEM (hierarquia da Figura 1, ver _aplicar_data_eleita() —
    DATA_ELEITA_ORIGEM é 'declaração' quando a data veio do SPED ou 'xml'
    quando veio do documento fiscal) e DATA_ORIGINAL/ANO_ORIGINAL (dhEmi
    cru do XML, paralelo à hierarquia — não sofre nenhuma lógica de
    prioridade, sempre o mesmo valor pros dois cenários). Exige
    xml_entradas_real/xml_saidas_real já persistidas (persistir_nfe()) — bc3
    é opcional (sem ela, as colunas dela ficam NULL e a hierarquia de datas
    cai direto pras datas do XML; DATA_ORIGINAL/ANO_ORIGINAL não dependem da
    bc3). callback(etapa, n) chamado após cada tabela. Retorna
    {tabela: n_linhas}."""
    _BANCO_PATH.parent.mkdir(parents=True, exist_ok=True)
    resultado = {}
    try:
        # Monta os DataFrames ANTES de abrir a conexão de escrita —
        # montar_fn() (montar_estoque_entradas/_saidas) abre sua própria
        # conexão de leitura em _enriquecer_fluxo_real_com_bc3(); o DuckDB
        # não permite duas conexões (leitura + escrita) simultâneas pro
        # mesmo arquivo com configuração diferente.
        dados = {tabela: montar_fn() for tabela, montar_fn in _TABELAS_ESTOQUE.items()}
        with duckdb.connect(str(_BANCO_PATH)) as con:
            for tabela, df in dados.items():
                # Regra Operacional R07: DATA_ELEITA/ANO_ELEITO/
                # DATA_ELEITA_ORIGEM/DATA_ORIGINAL/ANO_ORIGINAL nunca são
                # NULL de verdade (sempre "" na pior hipótese, ver
                # _aplicar_hierarquia_data()/_aplicar_data_eleita()) —
                # astype(str) cru é seguro pras cinco. Já DT_E_S/DT_FIN/
                # COD_ITEM_DECLARACAO/
                # DESCR_ITEM_DECLARACAO podem vir NULL genuíno do LEFT
                # JOIN com a bc3 (item sem correspondência) — astype(str)
                # cru transformaria esse NULL no literal "None" (achado
                # real, 2026-07-14: PB2/cometa ficaram com ~99% dos itens
                # de saída com o texto "None" em vez de NULL de verdade em
                # COD_ITEM_DECLARACAO, distorcendo qualquer `WHERE ... IS
                # NOT NULL` rio abaixo — mesmo tratamento já usado em
                # consultar_fluxo_real()/consultar_nfe_entradas_bc3()).
                df = _forcar_colunas_string(
                    df,
                    ["DATA_ELEITA", "ANO_ELEITO", "DATA_ELEITA_ORIGEM", "DATA_ORIGINAL", "ANO_ORIGINAL"],
                )
                for col in ("DT_E_S", "DT_FIN", "COD_ITEM_DECLARACAO", "DESCR_ITEM_DECLARACAO"):
                    if col in df.columns:
                        df[col] = df[col].where(df[col].isna(), df[col].astype(str))
                if not df.empty:
                    con.register("_df_tmp_estoque", df)
                    con.execute(f"CREATE OR REPLACE TABLE {tabela} AS SELECT * FROM _df_tmp_estoque")
                    con.unregister("_df_tmp_estoque")
                resultado[tabela] = len(df)
                if callback:
                    callback(tabela, resultado[tabela])
    except Exception as exc:
        logger.exception("Erro ao persistir estoque_entradas/estoque_saidas: %s", exc)
        resultado["erro"] = str(exc)
    return resultado


def estoque_entradas_saidas_ja_gerado() -> bool:
    """True se estoque_entradas/estoque_saidas (Estágio 4) já foram
    persistidas nesta operação — mesmo padrão de bc3_ja_gerada()/
    estoque_anual_ja_gerado(). Basta uma das duas tabelas existir (ambas
    são sempre criadas juntas por persistir_estoque_entradas_saidas(),
    mesmo que vazias)."""
    if not _BANCO_PATH.exists():
        return False
    try:
        with duckdb.connect(str(_BANCO_PATH), read_only=True) as con:
            tabelas = {r[0] for r in con.execute("SHOW TABLES").fetchall()}
            return "estoque_entradas" in tabelas or "estoque_saidas" in tabelas
    except Exception:
        logger.exception("Erro ao verificar estoque_entradas/estoque_saidas em %s", _BANCO_PATH)
        return False


def consultar_totais_estoque_entradas_saidas() -> dict:
    """Retorna {'estoque_entradas': n, 'estoque_saidas': n} lendo direto do
    DuckDB (sem reprocessar) — 0 tanto se a tabela ainda não existe quanto
    se existe vazia."""
    totais = {t: 0 for t in _TABELAS_ESTOQUE}
    if not _BANCO_PATH.exists():
        return totais
    try:
        with duckdb.connect(str(_BANCO_PATH), read_only=True) as con:
            tabelas = {r[0] for r in con.execute("SHOW TABLES").fetchall()}
            for tabela in totais:
                if tabela in tabelas:
                    totais[tabela] = con.execute(f"SELECT COUNT(*) FROM {tabela}").fetchone()[0]
    except Exception:
        logger.exception("Erro ao consultar totais de estoque_entradas/estoque_saidas em %s", _BANCO_PATH)
    return totais


def consultar_estoque_entradas_saidas(direcao: str, limite: "int | None" = 200) -> "tuple[pd.DataFrame, int]":
    """Lê estoque_entradas (direcao='entradas') ou estoque_saidas
    (direcao='saidas') já persistidas (Estágio 4 — sem reprocessar): mesmas
    colunas do XML + COD_ITEM_DECLARACAO/DESCR_ITEM_DECLARACAO/
    FATOR_MULTIPLICADOR_SUGERIDO/DT_E_S/DT_FIN (bc3, Estágio 2) +
    DATA_ELEITA/ANO_ELEITO/DATA_ELEITA_ORIGEM + DATA_ORIGINAL/ANO_ORIGINAL
    (Estágio 4). Mesmo padrão de
    consultar_fluxo_real(): devolve amostra (até 'limite' linhas) e total
    real; limite=None devolve a tabela inteira. direcao fora de
    {'entradas','saidas'} devolve vazio."""
    tabela = _TABELAS_ESTOQUE_POR_DIRECAO.get(direcao)
    if tabela is None or not _BANCO_PATH.exists():
        return pd.DataFrame(), 0
    try:
        with duckdb.connect(str(_BANCO_PATH), read_only=True) as con:
            tabelas = {r[0] for r in con.execute("SHOW TABLES").fetchall()}
            if tabela not in tabelas:
                return pd.DataFrame(), 0
            total = con.execute(f"SELECT COUNT(*) FROM {tabela}").fetchone()[0]
            query = f"SELECT * FROM {tabela}" if limite is None else f"SELECT * FROM {tabela} LIMIT {limite}"
            df = con.execute(query).df()
        return df, total
    except Exception:
        logger.exception("Erro ao consultar %s em %s", tabela, _BANCO_PATH)
        return pd.DataFrame(), 0


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

            df_sped_est = _parse_estoque_h005_h010(arquivos_sped)
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


def consultar_nfe_entradas_bc3(limite: "int | None" = 200) -> "tuple[pd.DataFrame, int]":
    """Expande a BC3 (resultado do Matching) de volta para o dataset bruto de
    ET em `nfe_entradas` — LEFT JOIN por ID_UNICO (chave sintética presente
    nos dois lados, ver _gerar_id_unico()) entre `nfe_entradas` (filtrado a
    PASTA_ORIGEM='ET' — todas as colunas originais do XML, não só as ~12
    reduzidas da BC2/BC3: data, participante etc.) e `bc3` (só as colunas de
    enriquecimento do Matching: COD_ITEM_DECLARACAO, DESCR_ITEM_DECLARACAO,
    MATCH_TIPO, MATCH_SCORE, FATOR_MULTIPLICADOR_SUGERIDO, DT_E_S, DT_FIN
    — as duas últimas só se a bc3 persistida já tiver esse schema, ver
    Estágio 4 em docs/estagios/04_cronologia_ano_eleito.md). Preserva a
    hierarquia de 11 níveis do Matching (D1-D6/A1-A5, ver REGRAS_MATCHING.md)
    porque MATCH_TIPO vem direto da bc3 sem nenhuma transformação. Item de ET
    sem `bc3` gerada ainda (ou sem correspondência) some/fica NULL nas
    colunas de enriquecimento (LEFT JOIN), nunca derruba a linha do ET.
    Devolve uma amostra (até 'limite' linhas) e o total real de linhas.
    limite=None devolve a tabela inteira (exportação completa)."""
    if not _BANCO_PATH.exists():
        return pd.DataFrame(), 0
    try:
        with duckdb.connect(str(_BANCO_PATH), read_only=True) as con:
            tabelas = {r[0] for r in con.execute("SHOW TABLES").fetchall()}
            if "nfe_entradas" not in tabelas:
                return pd.DataFrame(), 0
            colunas_nfe_entradas = {r[0] for r in con.execute("DESCRIBE nfe_entradas").fetchall()}
            if "ID_UNICO" not in colunas_nfe_entradas:
                # nfe_entradas persistida antes do ID_UNICO existir no schema
                # (versão antiga de loader.py) — sem a chave de junção não dá
                # pra expandir com a bc3. Precisa recarregar (Carregar
                # novamente) pra regravar nfe_entradas com o schema atual;
                # não regerado aqui de forma automática (Regra: nunca
                # persistir_* como diagnóstico silencioso).
                logger.warning(
                    "nfe_entradas em %s não tem ID_UNICO (schema desatualizado) — "
                    "recarregue os dados (Carregar novamente) para habilitar a prévia enriquecida.",
                    _BANCO_PATH,
                )
                return pd.DataFrame(), 0
            colunas_bc3, join_bc3 = _montar_join_bc3(con, tabelas, incluir_match=True)
            base_sql = (
                f"SELECT n.*, {colunas_bc3} "
                f"FROM nfe_entradas n {join_bc3} "
                "WHERE n.PASTA_ORIGEM = 'ET'"
            )
            total = con.execute(f"SELECT COUNT(*) FROM ({base_sql})").fetchone()[0]
            query = base_sql if limite is None else f"{base_sql} LIMIT {limite}"
            df = con.execute(query).df()
        # Regra Operacional R07: códigos expandidos da declaração seguem
        # como string (nunca inferência numérica) — mesmo com NULL do LEFT
        # JOIN misturado a 'nd'/'nm' (itens ND/NM) e a códigos reais. Não usa
        # _forcar_colunas_string() aqui (ela faz astype(str) cru, que
        # transformaria NULL genuíno de LEFT JOIN — item de ET sem
        # correspondência em bc3 — no literal "None" na tela): só converte
        # os valores não nulos, preservando NULL como NULL.
        for col in ("COD_ITEM_DECLARACAO", "DESCR_ITEM_DECLARACAO", "MATCH_TIPO", "DT_E_S", "DT_FIN"):
            if col in df.columns:
                df[col] = df[col].where(df[col].isna(), df[col].astype(str))
        return df, total
    except Exception:
        logger.exception("Erro ao consultar nfe_entradas x bc3 em %s", _BANCO_PATH)
        return pd.DataFrame(), 0


def consultar_totais_bc3() -> dict:
    """Retorna a contagem de itens da BC3 por tipo de match (D1, D2,
    A1, A2, A3, A4, A5, D3, D4, D5, D6, ND, NM) — numeração renomeada em
    2026-07-09, ver HIERARQUIA_TIPOS_TP_ALEXANDRE_vs_TP_IA.md; D3
    (consolidação N-para-1) adicionado em 2026-07-10; D6 (nota íntegra, só
    valor) adicionado em 2026-07-10), lendo direto do DuckDB (sem
    reprocessar) — alimenta os KPIs do painel de Matching. Rótulos de
    versões anteriores da lógica de matching (SECUNDARIO_FUZZY,
    SECUNDARIO_GTIN, PRINCIPAL_VALOR, TIPO_1..TIPO_5) podem ainda aparecer em
    bases já geradas antes dessas mudanças e não regeradas — por isso não são
    somados a nenhum tipo atual, só deixam de ter contador próprio."""
    totais = {
        "D1": 0, "D2": 0, "A1": 0, "A2": 0, "A3": 0,
        "A4": 0, "A5": 0, "D3": 0, "D4": 0, "D5": 0, "D6": 0, "ND": 0, "NM": 0,
    }
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
    """Carrega o inventário da declaração (Bloco H — H005+H010, estoque
    real, não o template ESTOQUE/base.csv). Inclui DT_INV/MOT_INV do H005
    pai — alicerce do Estágio 5 (ver montar_estoque_anual_consolidado())."""
    config   = load_config()
    arquivos = _localizar_arquivos_sped(config)
    meta: dict = {"arquivos": [str(a) for a in arquivos], "origem_dados": "DECLARACAO_ESTOQUE", "erros": []}

    if not arquivos:
        meta["erros"].append(f"Nenhum arquivo SPED encontrado em {_resolver_path(config, 'sped_path', '2-DECLARACAO/SPED')}")
        return pd.DataFrame(), meta

    df = _parse_estoque_h005_h010(arquivos)
    if df.empty:
        meta["erros"].append("Nenhum registro H010 encontrado nos arquivos SPED.")
        return df, meta

    meta["total_linhas"]  = len(df)
    meta["total_colunas"] = len(df.columns)
    meta["colunas"]       = df.columns.tolist()
    return df, meta


# ── Estágio 5 — Tabela de Estoque (estoque_anual_consolidado) ───────────────
# Foco exclusivo: consolidar o inventário JÁ DECLARADO no SPED (Bloco H) por
# item x ano, aplicando a regra de continuidade cronológica. Não calcula
# entradas/saídas nem divergências (RN1, EI+C=V+EF) — isso fica pra uma
# etapa futura, que cruzaria esta tabela com estoque_entradas/estoque_saidas
# (Estágio 4). Achado real na base do geraldo: o MOT_INV (motivo do
# inventário) do H005 é sempre "05" nesta operação, nunca "01" ("No final
# do período") — a especificação original citava "01", mas filtrar por esse
# valor literal zeraria a tabela nesta base real. Em vez de filtrar por um
# motivo específico, todo H005 encontrado é tratado como um fechamento de
# inventário válido (H005 é opcional no SPED — só aparece quando a empresa
# de fato declara Bloco H naquele período).
_COLUNAS_ESTOQUE_ANUAL = [
    "ANO_REFERENCIA", "COD_ITEM_DECLARACAO", "DESCR_ITEM_DECLARACAO",
    "UNIDADE", "QUANTIDADE_INICIAL", "QUANTIDADE_FINAL",
]


def montar_estoque_anual_consolidado() -> pd.DataFrame:
    """Estágio 5: consolida o inventário declarado (H005+H010, ver
    load_declaracao_estoque()) numa linha por item x ano. Regra de
    continuidade: cada inventário declarado (identificado por DT_INV) vira,
    na MESMA linha física, o Estoque Final do ano de DT_INV e o Estoque
    Inicial do ano SEGUINTE a DT_INV — não são duas contagens diferentes, é
    a mesma foto vista dos dois lados da virada do ano (ex.: inventário com
    DT_INV=31/12/2020 é EF(2020) e, ao mesmo tempo, EI(2021)). O último ano
    coberto fica sem QUANTIDADE_FINAL até o inventário seguinte ser
    declarado (correto: ainda não fechou). DESCR_ITEM_DECLARACAO vem do
    cadastro de produto (Registro 0200), por COD_ITEM. Regra R07:
    ANO_REFERENCIA/COD_ITEM_DECLARACAO/DESCR_ITEM_DECLARACAO/UNIDADE sempre
    string; QUANTIDADE_INICIAL/QUANTIDADE_FINAL são medidas numéricas de
    verdade (não códigos), ficam float.

    Corrigido 2026-07-17: até então o código gravava EI(ano_inv)/
    EF(ano_inv-1) — o OPOSTO do que este próprio docstring sempre
    documentou no exemplo acima (EF(2020)/EI(2021) pra DT_INV=31/12/2020),
    um desvio sistemático de 1 ano. Achado pela nova Auditoria de
    Divergência de Estoque (ver interface.render_auditoria_divergencia_
    estoque()): comparando contra o Excel de referência (ESTOQUE(...).xlsx,
    fonte de outra aplicação do usuário), quase 100% dos pares (COD_ITEM,
    ANO) divergiam; deslocar ANO_REFERENCIA em +1 ano fazia 31.954/31.955
    baterem exatamente na base da geraldo — confirmação inequívoca do
    desvio, não ruído de arredondamento."""
    df_est, _ = load_declaracao_estoque()
    if df_est.empty or "DT_INV" not in df_est.columns:
        return pd.DataFrame(columns=_COLUNAS_ESTOQUE_ANUAL)

    df = df_est.copy()
    ano_valido = df["DT_INV"].str.fullmatch(r"\d{8}")
    df = df[ano_valido].copy()
    if df.empty:
        return pd.DataFrame(columns=_COLUNAS_ESTOQUE_ANUAL)

    ano_inv = df["DT_INV"].str[4:8].astype(int)  # DDMMAAAA -> AAAA
    qtd_num = _numero_decimal_br(df["QTD"])

    base_ei = pd.DataFrame({
        "ANO_REFERENCIA":      (ano_inv + 1).astype(str),
        "COD_ITEM_DECLARACAO": df["COD_ITEM"].to_numpy(),
        "UNIDADE_EI":          df["UNID"].to_numpy(),
        "QUANTIDADE_INICIAL":  qtd_num.to_numpy(),
    })
    base_ef = pd.DataFrame({
        "ANO_REFERENCIA":      ano_inv.astype(str),
        "COD_ITEM_DECLARACAO": df["COD_ITEM"].to_numpy(),
        "UNIDADE_EF":          df["UNID"].to_numpy(),
        "QUANTIDADE_FINAL":    qtd_num.to_numpy(),
    })

    consolidado = base_ei.merge(
        base_ef, on=["ANO_REFERENCIA", "COD_ITEM_DECLARACAO"], how="outer",
    )
    consolidado["UNIDADE"] = consolidado["UNIDADE_EI"].fillna(consolidado["UNIDADE_EF"])
    consolidado = consolidado.drop(columns=["UNIDADE_EI", "UNIDADE_EF"])

    df_produtos, _ = load_declaracao_produtos()
    if not df_produtos.empty and {"COD_ITEM", "DESCR_ITEM"} <= set(df_produtos.columns):
        cadastro = (
            df_produtos[["COD_ITEM", "DESCR_ITEM"]]
            .drop_duplicates("COD_ITEM")
            .rename(columns={"COD_ITEM": "COD_ITEM_DECLARACAO", "DESCR_ITEM": "DESCR_ITEM_DECLARACAO"})
        )
        consolidado = consolidado.merge(cadastro, on="COD_ITEM_DECLARACAO", how="left")
    else:
        consolidado["DESCR_ITEM_DECLARACAO"] = ""
    consolidado["DESCR_ITEM_DECLARACAO"] = consolidado["DESCR_ITEM_DECLARACAO"].fillna("")

    consolidado = (
        consolidado[_COLUNAS_ESTOQUE_ANUAL]
        .sort_values(["COD_ITEM_DECLARACAO", "ANO_REFERENCIA"])
        .reset_index(drop=True)
    )
    return _forcar_colunas_string(
        consolidado, ["ANO_REFERENCIA", "COD_ITEM_DECLARACAO", "DESCR_ITEM_DECLARACAO", "UNIDADE"]
    )


def persistir_estoque_anual_consolidado(callback=None) -> dict:
    """Estágio 5: persiste estoque_anual_consolidado no DuckDB — inventário
    declarado (H005+H010) consolidado por item x ano com a regra de
    continuidade cronológica (ver montar_estoque_anual_consolidado()). Sem
    cálculo de entradas/saídas/divergências nesta etapa. callback(etapa, n)
    chamado ao final."""
    _BANCO_PATH.parent.mkdir(parents=True, exist_ok=True)
    resultado = {}
    try:
        df = montar_estoque_anual_consolidado()
        with duckdb.connect(str(_BANCO_PATH)) as con:
            if not df.empty:
                con.register("_df_estoque_anual", df)
                con.execute("CREATE OR REPLACE TABLE estoque_anual_consolidado AS SELECT * FROM _df_estoque_anual")
                con.unregister("_df_estoque_anual")
        resultado["estoque_anual_consolidado"] = len(df)
        if callback:
            callback("estoque_anual_consolidado", resultado["estoque_anual_consolidado"])
    except Exception as exc:
        logger.exception("Erro ao persistir estoque_anual_consolidado: %s", exc)
        resultado["erro"] = str(exc)
    return resultado


def estoque_anual_ja_gerado() -> bool:
    """True se a tabela estoque_anual_consolidado (Estágio 5) já existe no
    DuckDB da operação (mesma lógica de bc3_ja_gerada()/analise_ja_gerada())."""
    if not _BANCO_PATH.exists():
        return False
    try:
        with duckdb.connect(str(_BANCO_PATH), read_only=True) as con:
            tabelas = {r[0] for r in con.execute("SHOW TABLES").fetchall()}
            return "estoque_anual_consolidado" in tabelas
    except Exception:
        logger.exception("Erro ao verificar estoque_anual_consolidado existente em %s", _BANCO_PATH)
        return False


def consultar_estoque_anual_consolidado(limite: "int | None" = 200) -> "tuple[pd.DataFrame, int]":
    """Lê estoque_anual_consolidado já persistida (sem reprocessar),
    devolvendo uma amostra (até 'limite' linhas) e o total real de linhas.
    limite=None devolve a tabela inteira (exportação completa)."""
    if not _BANCO_PATH.exists():
        return pd.DataFrame(), 0
    try:
        with duckdb.connect(str(_BANCO_PATH), read_only=True) as con:
            tabelas = {r[0] for r in con.execute("SHOW TABLES").fetchall()}
            if "estoque_anual_consolidado" not in tabelas:
                return pd.DataFrame(), 0
            total = con.execute("SELECT COUNT(*) FROM estoque_anual_consolidado").fetchone()[0]
            query = (
                "SELECT * FROM estoque_anual_consolidado" if limite is None
                else f"SELECT * FROM estoque_anual_consolidado LIMIT {limite}"
            )
            df = con.execute(query).df()
        return df, total
    except Exception:
        logger.exception("Erro ao consultar estoque_anual_consolidado em %s", _BANCO_PATH)
        return pd.DataFrame(), 0


# ── Estágio 7 — Escolha do Produto Alvo ──────────────────────────────────────
# Estágio 7.1 — Fixação da Descrição Relevante (produto_alvo)
# Solicitação Técnica (2026-07-18): unifica COD_ITEM_DECLARACAO/DESCR_ITEM_
# DECLARACAO das 3 tabelas enriquecidas que o usuário chama informalmente de
# "entradas, saidas e estoque" (nomes reais no DuckDB, sem mudança —
# estoque_entradas/estoque_saidas — Estágio 4, movimentação; estoque_anual_
# consolidado — Estágio 5, inventário declarado) e elege, por código, a
# descrição estatisticamente mais frequente (moda) — um mesmo produto pode
# aparecer com grafias levemente diferentes entre as 3 fontes (erro de
# digitação, abreviação, atualização de cadastro do fornecedor/auditada).
# Primeiro sub-passo do Estágio 7 (escolha do produto a auditar) — próximos
# sub-passos (7.2 em diante) ainda não especificados.
_COLUNAS_PRODUTO_ALVO = ["COD_ITEM", "DESCR_ALVO"]

_TABELAS_PRODUTO_ALVO_FONTE = ("estoque_entradas", "estoque_saidas", "estoque_anual_consolidado")
# = "entradas, saidas e estoque" na linguagem do usuário — nomes reais das
# tabelas no DuckDB mantidos como estão (Estágios 4/5 inteiros dependem
# deles); decisão explícita de não renomear as tabelas em si, só a
# terminologia usada nos comentários/docstrings deste módulo.

_CODIGOS_PLACEHOLDER_PRODUTO_ALVO = {"nd", "nm"}
# Códigos-sentinela de "não declarado"/"não mapeado" gravados quando o
# Matching (BC3, Estágio 2) não achou correspondência pro item — achado
# real: 1.502 linhas em estoque_entradas e 565 em estoque_saidas na
# geraldo. Comparação EXATA (case-insensitive), não substring — a cometa
# tem COD_ITEM_DECLARACAO alfanumérico legítimo (ex.: "125KGRAXA",
# "CQ4533T", "PO916UNF"), então filtrar por "contém nd/nm" arriscaria
# excluir um código real que só coincidentemente contivesse essas letras.


def montar_produto_alvo() -> pd.DataFrame:
    """Estágio 7.1 (Fixação da Descrição Relevante) — elege a DESCR_ITEM_
    DECLARACAO mais frequente (moda) por COD_ITEM_DECLARACAO, unificando
    "entradas, saidas e estoque" (nomes reais no DuckDB: estoque_entradas,
    estoque_saidas — Estágio 4; estoque_anual_consolidado — Estágio 5) —
    as 3 tabelas enriquecidas com esse par de colunas. Exclui linhas com
    COD_ITEM_DECLARACAO nulo ou igual (case-insensitive) a 'nd'/'nm' (ver
    _CODIGOS_PLACEHOLDER_PRODUTO_ALVO). Empate na contagem é desempatado
    pela descrição em ordem alfabética (A-Z) — determinístico, não
    depende da ordem de leitura das tabelas fonte.

    Normalização de código ANTES da moda (2026-07-19, achado real —
    usuário reportou `COD_ITEM=000003` elegendo "DIAFRAGMA 8" na cometa,
    com só 1 ocorrência, enquanto o mesmo código sem padding tinha
    "FEIJAO GRAO" com 8): sem normalizar, `"000003"`, `"003"`, `"03"` e
    `"3"` contavam como 4 códigos DIFERENTES (cada um com sua própria
    moda fraca, baseada em pouquíssimas ocorrências); a normalização
    (`_normalizar_cod_item_flexivel()`, remove zeros à esquerda só de
    código puramente numérico, preserva alfanumérico) agora roda ANTES
    do cálculo de moda, com reagrupamento de FREQUENCIA por (COD_ITEM
    normalizado, DESCR) — confirmado com o usuário: "são o mesmo código,
    a descrição relevante é pela maior frequência nas entradas, saídas e
    estoques" combinados. Isso também elimina a necessidade de normalizar
    de novo em `gerar_cruzamento_valor()` (Estágio 7.2) — `produto_alvo`
    já sai com `COD_ITEM` normalizado e único.

    Regra R07: `COD_ITEM` sempre string. Devolve colunas ['COD_ITEM',
    'DESCR_ALVO']. Vazia se nenhuma das 3 tabelas fonte existir ainda
    (nenhum erro — pré-requisitos ainda não gerados, ver 'TABELAS
    ENTRADAS / SAÍDAS / ESTOQUES')."""
    if not _BANCO_PATH.exists():
        return pd.DataFrame(columns=_COLUNAS_PRODUTO_ALVO)
    try:
        with duckdb.connect(str(_BANCO_PATH), read_only=True) as con:
            tabelas = {r[0] for r in con.execute("SHOW TABLES").fetchall()}
            fontes = [t for t in _TABELAS_PRODUTO_ALVO_FONTE if t in tabelas]
            if not fontes:
                return pd.DataFrame(columns=_COLUNAS_PRODUTO_ALVO)
            placeholders = ", ".join(f"'{c}'" for c in _CODIGOS_PLACEHOLDER_PRODUTO_ALVO)
            uniao = " UNION ALL ".join(
                f"SELECT COD_ITEM_DECLARACAO AS COD_ITEM, TRIM(DESCR_ITEM_DECLARACAO) AS DESCR "
                f"FROM {t} WHERE COD_ITEM_DECLARACAO IS NOT NULL "
                f"AND LOWER(COD_ITEM_DECLARACAO) NOT IN ({placeholders})"
                for t in fontes
            )
            contagem = con.execute(
                f"SELECT COD_ITEM, DESCR, COUNT(*) AS FREQUENCIA FROM ({uniao}) GROUP BY COD_ITEM, DESCR"
            ).df()
    except Exception:
        logger.exception("Erro ao montar produto_alvo em %s", _BANCO_PATH)
        return pd.DataFrame(columns=_COLUNAS_PRODUTO_ALVO)

    if contagem.empty:
        return pd.DataFrame(columns=_COLUNAS_PRODUTO_ALVO)

    # Normaliza ANTES de somar frequência — ver docstring acima (achado
    # real: "000003"/"003"/"03"/"3" são o mesmo item, mas só contavam
    # certo depois de unificados num único COD_ITEM).
    contagem["COD_ITEM"] = _normalizar_cod_item_flexivel(contagem["COD_ITEM"])
    contagem = contagem.groupby(["COD_ITEM", "DESCR"], as_index=False)["FREQUENCIA"].sum()

    # Moda por COD_ITEM: maior FREQUENCIA primeiro; empate pela DESCR em
    # ordem alfabética (A-Z) — sort_values + groupby(...).first() preserva
    # a ordem já ordenada dentro de cada grupo (mesmo idioma usado em
    # _ordenar_duplicatas_por_quantidade()).
    contagem = contagem.sort_values(
        ["COD_ITEM", "FREQUENCIA", "DESCR"], ascending=[True, False, True],
    )
    eleitos = (
        contagem.groupby("COD_ITEM", as_index=False)
        .first()
        .rename(columns={"DESCR": "DESCR_ALVO"})[_COLUNAS_PRODUTO_ALVO]
    )
    return _forcar_colunas_string(eleitos, _COLUNAS_PRODUTO_ALVO).sort_values("COD_ITEM").reset_index(drop=True)


def persistir_produto_alvo(callback=None) -> dict:
    """Estágio 7.1 (Fixação da Descrição Relevante): persiste produto_alvo
    no DuckDB — descrição mais frequente (moda) por COD_ITEM, ver
    montar_produto_alvo(). Usada como base pra padronizar relatórios e
    apoiar a seleção de produtos pra auditoria física (RN1, Estágio 15).
    callback(etapa, n) chamado ao final."""
    _BANCO_PATH.parent.mkdir(parents=True, exist_ok=True)
    resultado = {}
    try:
        df = montar_produto_alvo()
        with duckdb.connect(str(_BANCO_PATH)) as con:
            if not df.empty:
                con.register("_df_produto_alvo", df)
                con.execute("CREATE OR REPLACE TABLE produto_alvo AS SELECT * FROM _df_produto_alvo")
                con.unregister("_df_produto_alvo")
        resultado["produto_alvo"] = len(df)
        if callback:
            callback("produto_alvo", resultado["produto_alvo"])
    except Exception as exc:
        logger.exception("Erro ao persistir produto_alvo: %s", exc)
        resultado["erro"] = str(exc)
    return resultado


def produto_alvo_ja_gerado() -> bool:
    """True se a tabela produto_alvo (Estágio 7.1) já existe no DuckDB da
    operação (mesma lógica de estoque_anual_ja_gerado())."""
    if not _BANCO_PATH.exists():
        return False
    try:
        with duckdb.connect(str(_BANCO_PATH), read_only=True) as con:
            tabelas = {r[0] for r in con.execute("SHOW TABLES").fetchall()}
            return "produto_alvo" in tabelas
    except Exception:
        logger.exception("Erro ao verificar produto_alvo existente em %s", _BANCO_PATH)
        return False


def consultar_produto_alvo(limite: "int | None" = 200) -> "tuple[pd.DataFrame, int]":
    """Lê produto_alvo já persistida (sem reprocessar), devolvendo uma
    amostra (até 'limite' linhas) e o total real de linhas. limite=None
    devolve a tabela inteira (exportação completa)."""
    if not _BANCO_PATH.exists():
        return pd.DataFrame(), 0
    try:
        with duckdb.connect(str(_BANCO_PATH), read_only=True) as con:
            tabelas = {r[0] for r in con.execute("SHOW TABLES").fetchall()}
            if "produto_alvo" not in tabelas:
                return pd.DataFrame(), 0
            total = con.execute("SELECT COUNT(*) FROM produto_alvo").fetchone()[0]
            query = (
                "SELECT * FROM produto_alvo" if limite is None
                else f"SELECT * FROM produto_alvo LIMIT {limite}"
            )
            df = con.execute(query).df()
        return df, total
    except Exception:
        logger.exception("Erro ao consultar produto_alvo em %s", _BANCO_PATH)
        return pd.DataFrame(), 0


# ── Estágio 7.2 — Cruzamento por Valor ───────────────────────────────────────
# Solicitação Técnica (2026-07-18): aplica a identidade contábil EI+Compras=
# Vendas+EF por (COD_ITEM, ANO), em R$ — perspectiva híbrida definida pelo
# usuário: Compras (estoque_entradas) e Estoque (Bloco H) pela visão da
# própria auditada (dado já vinculado ao COD_ITEM_DECLARACAO dela via
# Matching/BC3, ou por ela mesma declarado no SPED), Vendas (estoque_saidas)
# pela visão física do XML (nota fiscal emitida) — mesmo raciocínio de
# "verdade física vs. declarada" da RN1 original (`regra de negócios
# unificadas/regra negocio_pu_rn1_ei+c=v+ef_1.txt`); aqui só a MONTAGEM da
# base em valor, sem a lógica de PU/omissão do texto original (isso continua
# reservado pro Estágio 15).
_COLUNAS_CRUZAMENTO_VALOR = [
    "ANO", "COD_ITEM", "DESCR_ALVO", "EI", "COMPRAS", "TOTAL_DEBITO",
    "VENDAS", "EF", "TOTAL_CREDITO", "DIVERGENCIA", "INFRACAO", "PCT_DIVERGENCIA",
]

# Rótulos de INFRACAO (2026-07-19, Solicitação Técnica de evolução do 7.2)
# — direção confirmada com o usuário contra a RN1 já documentada em `regra
# de negócios unificadas/regra negocio_pu_rn1_ei+c=v+ef_1.txt` (condição 1:
# EI+C < V+EF = "compras de mercadorias sem notas"; condição 2: EI+C > V+EF
# = "vendas de mercadorias sem notas"). A primeira redação da Solicitação
# Técnica pedia o mapeamento INVERTIDO (TD<TC='Saídas sem NF') — sinalizado
# ao usuário antes de implementar; confirmado seguir a RN1 já documentada.
# Raciocínio: TC (Vendas+EF) > TD (EI+Compras) significa que saiu/sobrou
# mais mercadoria do que jamais foi registrada como comprada — só possível
# se houve COMPRA sem nota de entrada. O inverso (TD > TC) significa que
# entrou mais do que foi contabilizado saindo — VENDA sem nota de saída.
_INFRACAO_ENTRADAS_SEM_NF = "Entradas sem NF"
_INFRACAO_SAIDAS_SEM_NF = "Saídas sem NF"


def _valores_estoque_hunter() -> pd.DataFrame:
    """Valor (VL_ITEM) do Bloco H, no formato "largo" ano×item — EI e EF
    na MESMA linha física (diferente de `_declaracoes_estoque_hunter()`,
    uma linha por declaração, usada pela Auditoria de Estoque): cada
    declaração contribui pro EF do ano de `DT_INV` e, ao mesmo tempo, pro
    EI do ano seguinte — mesma regra de continuidade de `montar_estoque_
    anual_consolidado()` (Estágio 5), aqui aplicada a VALOR em vez de
    QUANTIDADE. `VL_ITEM` não existe em `estoque_anual_consolidado` (só
    QUANTIDADE_INICIAL/FINAL) — lido direto do SPED cru (`load_
    declaracao_estoque()`). Função paralela, decisão explícita do usuário
    de não estender o schema do Estágio 5 pra isso. `COD_ITEM` não
    normalizado (mesma convenção de `montar_produto_alvo()` — igualdade
    exata com o `COD_ITEM_DECLARACAO` cru, sem stripping de zeros).
    Soma VL_ITEM por (ANO, COD_ITEM) — declarações duplicadas (achado
    real de 2026-07-17/18, ex.: geraldo `DT_INV=31/01/2020`) se somam
    entre si; caso raro, mitigado na prática pelo filtro de Período de
    Auditoria em `gerar_cruzamento_valor()`."""
    df_est, _ = load_declaracao_estoque()
    if df_est.empty or "DT_INV" not in df_est.columns:
        return pd.DataFrame(columns=["ANO", "COD_ITEM", "VALOR_INICIAL", "VALOR_FINAL"])
    df = df_est[df_est["DT_INV"].str.fullmatch(r"\d{8}")].copy()
    if df.empty:
        return pd.DataFrame(columns=["ANO", "COD_ITEM", "VALOR_INICIAL", "VALOR_FINAL"])

    ano_inv = df["DT_INV"].str[4:8].astype(int)
    valor = _numero_decimal_br(df["VL_ITEM"])
    cod_item = df["COD_ITEM"].astype(str)

    base_ei = (
        pd.DataFrame({"ANO": (ano_inv + 1).astype(str), "COD_ITEM": cod_item, "VALOR_INICIAL": valor})
        .groupby(["ANO", "COD_ITEM"], as_index=False)["VALOR_INICIAL"].sum()
    )
    base_ef = (
        pd.DataFrame({"ANO": ano_inv.astype(str), "COD_ITEM": cod_item, "VALOR_FINAL": valor})
        .groupby(["ANO", "COD_ITEM"], as_index=False)["VALOR_FINAL"].sum()
    )
    return base_ei.merge(base_ef, on=["ANO", "COD_ITEM"], how="outer")


def _valores_por_ano_item(tabela: str, coluna_ano: str, coluna_cod_item: str) -> pd.DataFrame:
    """Soma `fatoitemnfe_infnfe_det_prod_vprod` ("Valor bruto do produto",
    ver DICIONARIO DE CAMPOS.txt — não existe coluna literal `VL_ITEM`
    nas tabelas de XML) por (`coluna_cod_item`, `coluna_ano`) numa tabela
    do Estágio 4 (`estoque_entradas`/`estoque_saidas`) — usado por
    `gerar_cruzamento_valor()` pra Compras/Vendas. `coluna_ano`/`coluna_
    cod_item` só recebem literais fixos do chamador (nunca input do
    usuário). Coluna de valor gravada como VARCHAR (achado real: sempre
    decimal com ponto nas 3 operações reais, nunca vírgula — `TRY_CAST`
    direto, sem `REPLACE`; `TRY_CAST` em vez de `CAST` pra não quebrar a
    query inteira se algum valor futuro vier malformado, tratando como
    NULL/0 em vez de erro).

    `coluna_cod_item` varia por direção — achado real (2026-07-18, usuário
    apontou): `estoque_entradas.COD_ITEM_DECLARACAO` (vindo do Matching/
    BC3) tem cobertura quase total (~99,9%), mas `estoque_saidas.COD_
    ITEM_DECLARACAO` é nulo em 98,8% das linhas — BC3 só vincula no
    sentido fornecedor→auditada (compras); não existe elo equivalente pro
    sentido auditada→cliente. Pro lado saídas, o usuário esclareceu que
    "nas saídas do XML, o código do produto é o código da declaração" —
    "o próprio XML, emissão própria, já é a declaração" (não existe um
    SPED separado listando produto de saída pra casar): quando a auditada
    é EMITENTE da nota, `fatoitemnfe_infnfe_det_prod_cprod` (código do
    produto/serviço, no próprio XML dela) já É o código dela mesma, sem
    precisar de Matching — coluna 100% preenchida nas 3 operações reais
    (diferente de `COD_ITEM_DECLARACAO`). `COD_ITEM` resultante NÃO
    normalizado aqui — ver `_normalizar_cod_item_flexivel()`, aplicado
    pelo chamador antes de casar com `produto_alvo`/Compras/Estoque
    (paddings diferentes pro MESMO item entre `COD_ITEM_DECLARACAO` e
    `cprod`). Vazia se a tabela não existir ainda (Estágio 4 não gerado).

    Deduplicação ET/EP (2026-07-18, achado ao investigar resíduo do 7.2 a
    pedido do usuário): `estoque_entradas`/`estoque_saidas` têm 241 itens
    (mesma `CHV_NFE`+`NITEM`) duplicados entre `PASTA_ORIGEM='ET'` e
    `'EP'` — as 11 notas de autoemissão já documentadas no projeto
    (`_chaves_autoemissao_duplicada()`), que contam como entrada E saída
    ao mesmo tempo; R$74.773,52 inflados em dobro em CADA tabela. A
    correção de 2026-07-17 só excluiu o subcaso CFOP 5927/6927 de
    `mask_entrada_real` — não elimina esta duplicação mais geral, que
    ainda existe nas tabelas persistidas do Estágio 4. Usuário pediu
    correção "somente para o levantamento do 7.2" — não tocar nas
    tabelas do Estágio 4: aqui, `ROW_NUMBER() OVER (PARTITION BY
    CHV_NFE, NITEM ORDER BY PASTA_ORIGEM)` mantém só 1 linha por item
    físico antes de somar, restrito à consulta deste módulo.

    Exclusão de autoemissão em Vendas (2026-07-18, mesmo dia — achado ao
    investigar resíduo de "FRALDA NENE BABY 3"): uma nota autoemitida
    (`fatonfe_infnfe_emit_cnpj == fatonfe_infnfe_dest_cnpj`) satisfaz
    `mask_entrada_real` E `mask_saida_real` SIMULTANEAMENTE, sempre —
    não é dependente de CFOP nem de `TPNF` (a exclusão de 2026-07-17,
    `mask_baixa_estoque_autoemissao_ep`, só cobre o subcaso CFOP
    5927/6927; uma nota de "Devolução de Mercadorias" autoemitida, por
    exemplo, não é coberta e ainda conta em dobro). Confirmado: as 482
    linhas autoemitidas em `estoque_saidas` (241 itens × 2 pastas) são
    exatamente o mesmo conjunto da deduplicação ET/EP acima — mesmo
    R$74.773,52. Usuário confirmou excluir TODA nota de autoemissão de
    Vendas (mantendo em Compras, espelhando a decisão de 2026-07-17
    pro lado entradas) — aplicado só quando `tabela='estoque_saidas'`."""
    colunas = ["ANO", "COD_ITEM", "VALOR"]
    if not _BANCO_PATH.exists():
        return pd.DataFrame(columns=colunas)
    try:
        with duckdb.connect(str(_BANCO_PATH), read_only=True) as con:
            tabelas = {r[0] for r in con.execute("SHOW TABLES").fetchall()}
            if tabela not in tabelas:
                return pd.DataFrame(columns=colunas)
            filtro_autoemissao = (
                " AND fatonfe_infnfe_emit_cnpj != fatonfe_infnfe_dest_cnpj"
                if tabela == "estoque_saidas" else ""
            )
            df = con.execute(
                f"WITH dedup_et_ep AS ("
                f"  SELECT {coluna_ano} AS ANO, {coluna_cod_item} AS COD_ITEM, "
                f"         fatoitemnfe_infnfe_det_prod_vprod AS VPROD, "
                f"         ROW_NUMBER() OVER ("
                f"           PARTITION BY fatoitemnfe_infprot_chnfe, fatoitemnfe_infnfe_det_nitem "
                f"           ORDER BY PASTA_ORIGEM"
                f"         ) AS rn "
                f"  FROM {tabela} WHERE {coluna_cod_item} IS NOT NULL{filtro_autoemissao}"
                f") "
                f"SELECT ANO, COD_ITEM, SUM(TRY_CAST(VPROD AS DOUBLE)) AS VALOR "
                f"FROM dedup_et_ep WHERE rn = 1 GROUP BY ANO, COD_ITEM"
            ).df()
        return df
    except Exception:
        logger.exception("Erro ao somar valor por ano/item em %s (%s)", tabela, _BANCO_PATH)
        return pd.DataFrame(columns=colunas)


def _normalizar_agrupar_valor(df: pd.DataFrame, colunas_valor: list) -> pd.DataFrame:
    """Normaliza COD_ITEM (`_normalizar_cod_item_flexivel()`) e reagrupa
    (soma) por (ANO, COD_ITEM) — necessário porque normalizar PODE unir
    grupos que antes eram distintos por padding (ex.: `"00000000013990"`
    e `"013990"` viram o mesmo `"13990"`), então uma soma feita ANTES da
    normalização ficaria fragmentada. Usado por gerar_cruzamento_valor()
    nas 3 fontes (Compras, Vendas, Estoque)."""
    if df.empty:
        return df
    df = df.copy()
    df["COD_ITEM"] = _normalizar_cod_item_flexivel(df["COD_ITEM"])
    return df.groupby(["ANO", "COD_ITEM"], as_index=False)[colunas_valor].sum()


def gerar_cruzamento_valor() -> dict:
    """Estágio 7.2 — monta o Cruzamento por Valor: uma linha por (ANO,
    COD_ITEM) com EI, Compras, Total Débito (EI+Compras), Vendas, EF,
    Total Crédito (Vendas+EF), Divergência, Infração e % Diverg, em R$.

    Indicadores de risco (2026-07-19, Solicitação Técnica de evolução):
    - `DIVERGENCIA`: `|TD-TC|` — sempre positiva (antes era `TD-TC`,
      podia ser negativa).
    - `INFRACAO`: rótulo condicional — ver `_INFRACAO_ENTRADAS_SEM_NF`/
      `_INFRACAO_SAIDAS_SEM_NF` acima pro raciocínio completo e a
      confirmação com o usuário contra a RN1 já documentada (a primeira
      redação da Solicitação Técnica pedia o mapeamento invertido).
      `TD < TC` → "Entradas sem NF" (compras sem nota, RN1 condição 1);
      `TD ≥ TC` → "Saídas sem NF" (vendas sem nota, RN1 condição 2).
    - `PCT_DIVERGENCIA`: `|TD-TC| / min(TD,TC) × 100` — magnitude
      relativa ao menor dos dois lados. `min(TD,TC)=0` sem divergência
      (`TD=TC=0`) vira `0.0`; `min(TD,TC)=0` COM divergência (um lado
      zerado, outro não) usa `0.00001` no denominador em vez de `NaN`
      (2026-07-19, refinamento) — dá um percentual gigante em vez de
      "N/A", subindo a omissão total pro topo do ranking.
    - Ordenação: por `DIVERGENCIA` decrescente (antes era `ANO`+`COD_
      ITEM`) — prioriza os maiores "rombos" financeiros no topo.

    Fonte de Vendas corrigida (2026-07-18, achado real ao investigar
    divergência apontada pelo usuário pro produto "BOLACHA MANTEGA DO
    SERTAO JUCURUTU" contra o cruzamento da aplicação de produção dele):
    `estoque_saidas.COD_ITEM_DECLARACAO` (vindo do Matching/BC3) é nulo
    em 98,8% das linhas — BC3 só vincula no sentido fornecedor→auditada
    (compras). Usuário esclareceu: "nas saídas do XML, o código do
    produto é o código da declaração" — "o próprio XML, emissão própria,
    já é a declaração" (não existe SPED separado listando produto de
    saída pra casar contra). Vendas agora usa `fatoitemnfe_infnfe_det_
    prod_cprod` (código do produto no próprio XML da auditada, como
    emitente — 100% preenchido nas 3 operações reais) em vez de
    `COD_ITEM_DECLARACAO`.

    Identidade cross-fonte: `COD_ITEM_DECLARACAO` (Compras/Estoque) e
    `cprod` (Vendas) têm padding de zeros diferente pro MESMO item (ex.:
    `"00000000013990"` vs `"013990"`) — as 3 fontes (Compras, Vendas,
    Estoque) e `produto_alvo` (Estágio 7.1) são normalizadas por
    `_normalizar_cod_item_flexivel()` (remove zeros à esquerda só de
    código puramente numérico, preserva alfanumérico — diferente de
    `_normalizar_cod_item_numerico()`, que destruiria código alfanumérico
    legítimo da cometa) antes de casar. `produto_alvo` deduplicado por
    código normalizado (`keep="first"`) — colisão rara, mesmo tipo de
    caso já visto em `auditar_divergencia_estoque()` (cometa `COD_ITEM=4`).
    O `COD_ITEM` exibido no resultado final é o de `produto_alvo` (a
    identidade "oficial" do Estágio 7.1), não o normalizado internamente.

    Continuidade: EI(ano) = EF(ano-1) da mesma declaração de inventário
    (ver `_valores_estoque_hunter()`).

    Escopo do Período de Auditoria: quando configurado (`obter_periodo_
    auditoria()`), restringe `ANO` a `[ano_inicial, ano_final]` — mesmo
    filtro das 3 auditorias de AUDITORIA1 (2026-07-18). Sem período
    configurado, mostra todos os anos presentes nos dados.

    Ausência de uma métrica pra um (ANO, COD_ITEM) vira 0 (`fillna`) —
    não erro: um item comprado mas nunca vendido naquele ano aparece com
    VENDAS=0, por exemplo.

    Regra R07: `ANO`/`COD_ITEM` sempre string.

    Devolve `{'resumo': dict, 'cruzamento': DataFrame, 'erros': list}` —
    `erros` não-vazio quando `produto_alvo` (Estágio 7.1) ainda não foi
    gerada."""
    produto_alvo, _ = consultar_produto_alvo(limite=None)
    if produto_alvo.empty:
        return {
            "resumo": {}, "cruzamento": pd.DataFrame(),
            "erros": ["Tabela produto_alvo (Estágio 7.1) ainda não foi gerada."],
        }

    compras = _valores_por_ano_item("estoque_entradas", "ANO_ELEITO", "COD_ITEM_DECLARACAO")
    compras = compras.rename(columns={"VALOR": "COMPRAS"})
    vendas = _valores_por_ano_item("estoque_saidas", "ANO_ELEITO", "fatoitemnfe_infnfe_det_prod_cprod")
    vendas = vendas.rename(columns={"VALOR": "VENDAS"})
    estoque = _valores_estoque_hunter()

    periodo = obter_periodo_auditoria()
    if periodo:
        ano_ini, ano_fim = int(periodo["ano_inicial"]), int(periodo["ano_final"])
        compras = compras[compras["ANO"].astype(int).between(ano_ini, ano_fim)]
        vendas = vendas[vendas["ANO"].astype(int).between(ano_ini, ano_fim)]
        if not estoque.empty:
            estoque = estoque[estoque["ANO"].astype(int).between(ano_ini, ano_fim)]

    compras = _normalizar_agrupar_valor(compras, ["COMPRAS"])
    vendas = _normalizar_agrupar_valor(vendas, ["VENDAS"])
    estoque = _normalizar_agrupar_valor(estoque, ["VALOR_INICIAL", "VALOR_FINAL"])

    base = compras.merge(vendas, on=["ANO", "COD_ITEM"], how="outer")
    if estoque.empty:
        base["VALOR_INICIAL"] = 0.0
        base["VALOR_FINAL"] = 0.0
    else:
        base = base.merge(estoque, on=["ANO", "COD_ITEM"], how="outer")
    if base.empty:
        return {"resumo": {}, "cruzamento": pd.DataFrame(), "erros": []}

    for col in ("COMPRAS", "VENDAS", "VALOR_INICIAL", "VALOR_FINAL"):
        base[col] = base[col].fillna(0.0)
    base = base.rename(columns={"VALOR_INICIAL": "EI", "VALOR_FINAL": "EF"})

    # produto_alvo já sai de montar_produto_alvo() com COD_ITEM normalizado
    # e único (2026-07-19) — não precisa normalizar/deduplicar de novo aqui,
    # só casar direto (base["COD_ITEM"] também já normalizado, ver
    # _normalizar_agrupar_valor()).
    base = base.merge(produto_alvo, on="COD_ITEM", how="inner")
    if base.empty:
        return {"resumo": {}, "cruzamento": pd.DataFrame(), "erros": []}

    base["TOTAL_DEBITO"] = (base["EI"] + base["COMPRAS"]).round(2)
    base["TOTAL_CREDITO"] = (base["VENDAS"] + base["EF"]).round(2)
    diferenca = base["TOTAL_DEBITO"] - base["TOTAL_CREDITO"]
    base["DIVERGENCIA"] = diferenca.abs().round(2)
    base["INFRACAO"] = np.where(diferenca < 0, _INFRACAO_ENTRADAS_SEM_NF, _INFRACAO_SAIDAS_SEM_NF)

    # % Diverg = |TD-TC| / min(TD,TC) × 100 — magnitude relativa ao menor dos
    # dois lados (pedido do usuário: distinguir divergência irrelevante num
    # giro grande de divergência crítica num produto de baixo giro).
    # min(TD,TC)=0 é indefinido (divisão por zero) — antes virava NaN
    # ("N/A" na UI) quando um lado zerava e o outro não, escondendo do
    # ranking justamente os casos de omissão total (2026-07-19, Solicitação
    # Técnica de refinamento: "N/A prejudica o ranqueamento de infrações
    # graves por omissão total"). Denominador zero agora vira 0.00001 em vez
    # de NaN — TD=TC=0 (sem divergência) continua dando 0%, mas um lado
    # zerado com o outro não dá um % gigante, subindo a omissão total pro
    # topo do alerta em vez de sumir como "N/A".
    minimo = base[["TOTAL_DEBITO", "TOTAL_CREDITO"]].min(axis=1)
    minimo_seguro = minimo.where(minimo != 0, 0.00001)
    base["PCT_DIVERGENCIA"] = (base["DIVERGENCIA"] / minimo_seguro * 100).round(2)

    cruzamento = (
        _forcar_colunas_string(base, ["ANO", "COD_ITEM"])[_COLUNAS_CRUZAMENTO_VALOR]
        .sort_values("DIVERGENCIA", ascending=False)
        .reset_index(drop=True)
    )

    resumo = {
        "total_linhas": len(cruzamento),
        "total_produtos": int(cruzamento["COD_ITEM"].nunique()),
        "total_divergencia_absoluta": float(cruzamento["DIVERGENCIA"].sum()),
        "periodo": periodo,
    }
    return {"resumo": resumo, "cruzamento": cruzamento, "erros": []}


def persistir_cruzamento_valor(callback=None) -> dict:
    """Estágio 7.2: persiste cruzamento_valor no DuckDB, ver
    gerar_cruzamento_valor(). callback(etapa, n) chamado ao final."""
    _BANCO_PATH.parent.mkdir(parents=True, exist_ok=True)
    resultado = {}
    try:
        r = gerar_cruzamento_valor()
        if r["erros"]:
            resultado["erro"] = " | ".join(r["erros"])
            return resultado
        df = r["cruzamento"]
        with duckdb.connect(str(_BANCO_PATH)) as con:
            if not df.empty:
                con.register("_df_cruzamento_valor", df)
                con.execute("CREATE OR REPLACE TABLE cruzamento_valor AS SELECT * FROM _df_cruzamento_valor")
                con.unregister("_df_cruzamento_valor")
        resultado["cruzamento_valor"] = len(df)
        if callback:
            callback("cruzamento_valor", resultado["cruzamento_valor"])
    except Exception as exc:
        logger.exception("Erro ao persistir cruzamento_valor: %s", exc)
        resultado["erro"] = str(exc)
    return resultado


def cruzamento_valor_ja_gerado() -> bool:
    """True se a tabela cruzamento_valor (Estágio 7.2) já existe no
    DuckDB da operação."""
    if not _BANCO_PATH.exists():
        return False
    try:
        with duckdb.connect(str(_BANCO_PATH), read_only=True) as con:
            tabelas = {r[0] for r in con.execute("SHOW TABLES").fetchall()}
            return "cruzamento_valor" in tabelas
    except Exception:
        logger.exception("Erro ao verificar cruzamento_valor existente em %s", _BANCO_PATH)
        return False


def consultar_cruzamento_valor(limite: "int | None" = 200) -> "tuple[pd.DataFrame, int]":
    """Lê cruzamento_valor já persistida (sem reprocessar), devolvendo
    uma amostra (até 'limite' linhas) e o total real de linhas.
    limite=None devolve a tabela inteira."""
    if not _BANCO_PATH.exists():
        return pd.DataFrame(), 0
    try:
        with duckdb.connect(str(_BANCO_PATH), read_only=True) as con:
            tabelas = {r[0] for r in con.execute("SHOW TABLES").fetchall()}
            if "cruzamento_valor" not in tabelas:
                return pd.DataFrame(), 0
            total = con.execute("SELECT COUNT(*) FROM cruzamento_valor").fetchone()[0]
            query = (
                "SELECT * FROM cruzamento_valor" if limite is None
                else f"SELECT * FROM cruzamento_valor LIMIT {limite}"
            )
            df = con.execute(query).df()
        return df, total
    except Exception:
        logger.exception("Erro ao consultar cruzamento_valor em %s", _BANCO_PATH)
        return pd.DataFrame(), 0


# ── Estágio 7.2.1 — Cruzamento por Produto ─────────────────────────────────
# Condensação do Estágio 7.2 (2026-07-19, Solicitação Técnica): uma linha por
# ANO+COD_ITEM fragmenta o "rombo" total de um produto ao longo dos anos —
# aqui soma tudo numa linha por DESCR_ALVO (Descrição Relevante, Estágio
# 7.1), pra responder direto "qual produto causou o maior prejuízo
# financeiro no período todo".
_COLUNAS_CRUZAMENTO_PRODUTO = [
    "DESCR_ALVO", "EI", "COMPRAS", "TOTAL_DEBITO", "VENDAS", "EF",
    "TOTAL_CREDITO", "DIVERGENCIA", "INFRACAO", "PCT_DIVERGENCIA",
]
_COLUNAS_SOMA_CRUZAMENTO_PRODUTO = [
    "EI", "COMPRAS", "TOTAL_DEBITO", "VENDAS", "EF", "TOTAL_CREDITO", "DIVERGENCIA",
]


def gerar_cruzamento_produto() -> dict:
    """Estágio 7.2.1 — Cruzamento por Produto: condensa `cruzamento_valor`
    (Estágio 7.2, uma linha por ANO+COD_ITEM) numa linha por DESCR_ALVO,
    somando EI/Compras/Total Débito/Vendas/EF/Total Crédito/Divergência
    de todos os anos do produto. Lê de `cruzamento_valor` JÁ PERSISTIDA
    (não reprocessa entradas/saídas/estoque do zero) — exige essa tabela
    já gerada.

    `DIVERGENCIA` aqui é a SOMA das divergências anuais (magnitude total
    acumulada de irregularidade no período) — DELIBERADAMENTE não é
    `|∑TOTAL_DEBITO - ∑TOTAL_CREDITO|` (a "divergência do total líquido"),
    que poderia dar um valor MENOR ou até 0 se anos com direções opostas
    se cancelassem (ex.: 2021 com entrada sem NF e 2022 com saída sem NF
    do mesmo produto) — isso esconderia produtos com histórico recorrente
    de irregularidade atrás de um total líquido enganosamente baixo.

    `INFRACAO`/`PCT_DIVERGENCIA` SÃO recalculados sobre os totais
    acumulados (∑TOTAL_DEBITO, ∑TOTAL_CREDITO) — não é uma simples soma
    das colunas originais, senão o rótulo de Infração de um produto
    dependeria arbitrariamente de qual ano "pesa mais" na soma. Mesma
    direção de INFRACAO do Estágio 7.2 (confirmado com o usuário
    2026-07-19, pra manter consistência entre os dois painéis — o 7.2.1
    é a versão somada da MESMA equação, não uma regra nova): ∑TD < ∑TC →
    'Entradas sem NF' (compra sem nota); ∑TD ≥ ∑TC → 'Saídas sem NF'
    (venda sem nota). `PCT_DIVERGENCIA` usa a mesma fórmula/proteção
    contra zero do Estágio 7.2 (`DIVERGENCIA / min(∑TD,∑TC) × 100`,
    denominador 0 vira 0.00001 — ver gerar_cruzamento_valor()).

    Ordenação: por `DIVERGENCIA` (acumulada) decrescente — maiores
    "rombos" financeiros totais no topo.

    Regra R07: `DESCR_ALVO` sempre string.

    Devolve `{'resumo': dict, 'cruzamento': DataFrame, 'erros': list}` —
    `erros` não-vazio quando `cruzamento_valor` (Estágio 7.2) ainda não
    foi gerada."""
    base, _ = consultar_cruzamento_valor(limite=None)
    if base.empty:
        return {
            "resumo": {}, "cruzamento": pd.DataFrame(),
            "erros": ["Tabela cruzamento_valor (Estágio 7.2) ainda não foi gerada."],
        }

    for col in _COLUNAS_SOMA_CRUZAMENTO_PRODUTO:
        base[col] = pd.to_numeric(base[col], errors="coerce").fillna(0.0)

    agrupado = base.groupby("DESCR_ALVO", as_index=False)[_COLUNAS_SOMA_CRUZAMENTO_PRODUTO].sum()

    diferenca = agrupado["TOTAL_DEBITO"] - agrupado["TOTAL_CREDITO"]
    agrupado["INFRACAO"] = np.where(diferenca < 0, _INFRACAO_ENTRADAS_SEM_NF, _INFRACAO_SAIDAS_SEM_NF)

    minimo = agrupado[["TOTAL_DEBITO", "TOTAL_CREDITO"]].min(axis=1)
    minimo_seguro = minimo.where(minimo != 0, 0.00001)
    agrupado["PCT_DIVERGENCIA"] = (agrupado["DIVERGENCIA"] / minimo_seguro * 100).round(2)

    for col in _COLUNAS_SOMA_CRUZAMENTO_PRODUTO:
        agrupado[col] = agrupado[col].round(2)

    cruzamento = (
        _forcar_colunas_string(agrupado, ["DESCR_ALVO"])[_COLUNAS_CRUZAMENTO_PRODUTO]
        .sort_values("DIVERGENCIA", ascending=False)
        .reset_index(drop=True)
    )

    resumo = {
        "total_produtos": len(cruzamento),
        "total_divergencia_acumulada": float(cruzamento["DIVERGENCIA"].sum()),
    }
    return {"resumo": resumo, "cruzamento": cruzamento, "erros": []}


def persistir_cruzamento_produto(callback=None) -> dict:
    """Estágio 7.2.1: persiste cruzamento_produto no DuckDB, ver
    gerar_cruzamento_produto(). callback(etapa, n) chamado ao final."""
    _BANCO_PATH.parent.mkdir(parents=True, exist_ok=True)
    resultado = {}
    try:
        r = gerar_cruzamento_produto()
        if r["erros"]:
            resultado["erro"] = " | ".join(r["erros"])
            return resultado
        df = r["cruzamento"]
        with duckdb.connect(str(_BANCO_PATH)) as con:
            if not df.empty:
                con.register("_df_cruzamento_produto", df)
                con.execute("CREATE OR REPLACE TABLE cruzamento_produto AS SELECT * FROM _df_cruzamento_produto")
                con.unregister("_df_cruzamento_produto")
        resultado["cruzamento_produto"] = len(df)
        if callback:
            callback("cruzamento_produto", resultado["cruzamento_produto"])
    except Exception as exc:
        logger.exception("Erro ao persistir cruzamento_produto: %s", exc)
        resultado["erro"] = str(exc)
    return resultado


def cruzamento_produto_ja_gerado() -> bool:
    """True se a tabela cruzamento_produto (Estágio 7.2.1) já existe no
    DuckDB da operação."""
    if not _BANCO_PATH.exists():
        return False
    try:
        with duckdb.connect(str(_BANCO_PATH), read_only=True) as con:
            tabelas = {r[0] for r in con.execute("SHOW TABLES").fetchall()}
            return "cruzamento_produto" in tabelas
    except Exception:
        logger.exception("Erro ao verificar cruzamento_produto existente em %s", _BANCO_PATH)
        return False


def consultar_cruzamento_produto(limite: "int | None" = 200) -> "tuple[pd.DataFrame, int]":
    """Lê cruzamento_produto já persistida (sem reprocessar), devolvendo
    uma amostra (até 'limite' linhas) e o total real de linhas.
    limite=None devolve a tabela inteira."""
    if not _BANCO_PATH.exists():
        return pd.DataFrame(), 0
    try:
        with duckdb.connect(str(_BANCO_PATH), read_only=True) as con:
            tabelas = {r[0] for r in con.execute("SHOW TABLES").fetchall()}
            if "cruzamento_produto" not in tabelas:
                return pd.DataFrame(), 0
            total = con.execute("SELECT COUNT(*) FROM cruzamento_produto").fetchone()[0]
            query = (
                "SELECT * FROM cruzamento_produto" if limite is None
                else f"SELECT * FROM cruzamento_produto LIMIT {limite}"
            )
            df = con.execute(query).df()
        return df, total
    except Exception:
        logger.exception("Erro ao consultar cruzamento_produto em %s", _BANCO_PATH)
        return pd.DataFrame(), 0


# ── Estágio 7.3 — RN1 Movimentação Física ────────────────────────────────
# Solicitação Técnica (2026-07-20): mesma identidade contábil EI+Compras=
# Vendas+EF do Estágio 7.2 (ver gerar_cruzamento_valor()) — Compras/Vendas já
# vêm de estoque_entradas/estoque_saidas (Estágio 4, XML) e EI/EF já vêm de
# estoque/Bloco H (Estágio 5, declaração); a mudança pedida pro 7.3 é o grão
# da agregação: por (ANO, DESCR_ALVO) em vez de (ANO, COD_ITEM) — a
# Descrição Relevante (Estágio 7.1) vira o elo direto entre movimentação e
# inventário, somando todo COD_ITEM que compartilhe a mesma DESCR_ALVO numa
# única linha por ano (mesmo raciocínio de gerar_cruzamento_produto(),
# Estágio 7.2.1, mas mantendo ANO separado em vez de somar todos os anos
# numa linha só).
#
# Reaproveita cruzamento_valor (Estágio 7.2) já persistida em vez de
# reprocessar entradas/saídas/estoque do zero (mesma decisão de
# gerar_cruzamento_produto()) — evita duplicar a lógica de dedup ET/EP e
# exclusão de autoemissão já resolvida em _valores_por_ano_item().
#
# Limitação conhecida (herdada de produto_alvo/cruzamento_valor): itens de
# entrada SEM match no BC3 (COD_ITEM_DECLARACAO/DESCR_ITEM_DECLARACAO nulos
# — ver montar_estoque_entradas(), ambas as colunas vêm do MESMO LEFT JOIN
# com a bc3) não têm como ser vinculados a uma DESCR_ALVO — produto_alvo é
# construído a partir dessas mesmas colunas, então não existe descrição
# alguma pra casar. "Notas na gaveta" sem NENHUM match no BC3 não aparecem
# atribuídas a um produto específico neste painel; o que ele revela é a
# divergência acumulada nos itens QUE JÁ têm produto_alvo reconhecido.
_COLUNAS_RN1_FISICA = [
    "ANO", "DESCR_ALVO", "EI", "COMPRAS", "TOTAL_DEBITO", "VENDAS", "EF",
    "TOTAL_CREDITO", "DIVERGENCIA", "INFRACAO", "PCT_DIVERGENCIA",
]


def gerar_rn1_fisica() -> dict:
    """Estágio 7.3 — RN1 Movimentação Física: ver comentário da seção
    acima. Lê cruzamento_valor (Estágio 7.2) JÁ PERSISTIDA e reagrupa por
    (ANO, DESCR_ALVO) — soma EI/Compras/Total Débito/Vendas/EF/Total
    Crédito/Divergência. INFRACAO/PCT_DIVERGENCIA SÃO recalculados sobre
    os totais agrupados (mesmo motivo de gerar_cruzamento_produto(): o
    rótulo não pode depender de qual COD_ITEM "pesa mais" na soma).
    Ordenação: por DIVERGENCIA decrescente. Regra R07: ANO/DESCR_ALVO
    sempre string.

    Devolve {'resumo': dict, 'cruzamento': DataFrame, 'erros': list} —
    erros não-vazio quando cruzamento_valor (Estágio 7.2) ainda não foi
    gerada."""
    base, _ = consultar_cruzamento_valor(limite=None)
    if base.empty:
        return {
            "resumo": {}, "cruzamento": pd.DataFrame(),
            "erros": ["Tabela cruzamento_valor (Estágio 7.2) ainda não foi gerada."],
        }

    for col in _COLUNAS_SOMA_CRUZAMENTO_PRODUTO:
        base[col] = pd.to_numeric(base[col], errors="coerce").fillna(0.0)

    agrupado = base.groupby(["ANO", "DESCR_ALVO"], as_index=False)[_COLUNAS_SOMA_CRUZAMENTO_PRODUTO].sum()

    diferenca = agrupado["TOTAL_DEBITO"] - agrupado["TOTAL_CREDITO"]
    agrupado["INFRACAO"] = np.where(diferenca < 0, _INFRACAO_ENTRADAS_SEM_NF, _INFRACAO_SAIDAS_SEM_NF)

    minimo = agrupado[["TOTAL_DEBITO", "TOTAL_CREDITO"]].min(axis=1)
    minimo_seguro = minimo.where(minimo != 0, 0.00001)
    agrupado["PCT_DIVERGENCIA"] = (agrupado["DIVERGENCIA"] / minimo_seguro * 100).round(2)

    for col in _COLUNAS_SOMA_CRUZAMENTO_PRODUTO:
        agrupado[col] = agrupado[col].round(2)

    cruzamento = (
        _forcar_colunas_string(agrupado, ["ANO", "DESCR_ALVO"])[_COLUNAS_RN1_FISICA]
        .sort_values("DIVERGENCIA", ascending=False)
        .reset_index(drop=True)
    )

    resumo = {
        "total_linhas": len(cruzamento),
        "total_produtos": int(cruzamento["DESCR_ALVO"].nunique()),
        "total_divergencia_absoluta": float(cruzamento["DIVERGENCIA"].sum()),
    }
    return {"resumo": resumo, "cruzamento": cruzamento, "erros": []}


def persistir_rn1_fisica(callback=None) -> dict:
    """Estágio 7.3: persiste rn1_fisica no DuckDB, ver gerar_rn1_fisica().
    callback(etapa, n) chamado ao final."""
    _BANCO_PATH.parent.mkdir(parents=True, exist_ok=True)
    resultado = {}
    try:
        r = gerar_rn1_fisica()
        if r["erros"]:
            resultado["erro"] = " | ".join(r["erros"])
            return resultado
        df = r["cruzamento"]
        with duckdb.connect(str(_BANCO_PATH)) as con:
            if not df.empty:
                con.register("_df_rn1_fisica", df)
                con.execute("CREATE OR REPLACE TABLE rn1_fisica AS SELECT * FROM _df_rn1_fisica")
                con.unregister("_df_rn1_fisica")
        resultado["rn1_fisica"] = len(df)
        if callback:
            callback("rn1_fisica", resultado["rn1_fisica"])
    except Exception as exc:
        logger.exception("Erro ao persistir rn1_fisica: %s", exc)
        resultado["erro"] = str(exc)
    return resultado


def rn1_fisica_ja_gerado() -> bool:
    """True se a tabela rn1_fisica (Estágio 7.3) já existe no DuckDB da
    operação."""
    if not _BANCO_PATH.exists():
        return False
    try:
        with duckdb.connect(str(_BANCO_PATH), read_only=True) as con:
            tabelas = {r[0] for r in con.execute("SHOW TABLES").fetchall()}
            return "rn1_fisica" in tabelas
    except Exception:
        logger.exception("Erro ao verificar rn1_fisica existente em %s", _BANCO_PATH)
        return False


def consultar_rn1_fisica(limite: "int | None" = 200) -> "tuple[pd.DataFrame, int]":
    """Lê rn1_fisica já persistida (sem reprocessar), devolvendo uma
    amostra (até 'limite' linhas) e o total real de linhas. limite=None
    devolve a tabela inteira."""
    if not _BANCO_PATH.exists():
        return pd.DataFrame(), 0
    try:
        with duckdb.connect(str(_BANCO_PATH), read_only=True) as con:
            tabelas = {r[0] for r in con.execute("SHOW TABLES").fetchall()}
            if "rn1_fisica" not in tabelas:
                return pd.DataFrame(), 0
            total = con.execute("SELECT COUNT(*) FROM rn1_fisica").fetchone()[0]
            query = (
                "SELECT * FROM rn1_fisica" if limite is None
                else f"SELECT * FROM rn1_fisica LIMIT {limite}"
            )
            df = con.execute(query).df()
        return df, total
    except Exception:
        logger.exception("Erro ao consultar rn1_fisica em %s", _BANCO_PATH)
        return pd.DataFrame(), 0


# ── Auditoria — Divergência de Entradas (Hunter × Excel de referência) ─────
# Estudo pontual (2026-07-13), SEM cruzar código de item: compara um Excel
# de referência de outra aplicação do usuário com estoque_entradas (Estágio
# 4), só por CHV_NFE + contagem de itens por nota, pra explicar a origem de
# uma diferença de volume total (achado real: 19.177 itens no Excel x
# 16.420 em estoque_entradas, operação geraldo — resíduo de 2.757).

MSG_SEM_EXCEL_ENTRADAS_REFERENCIA = "Nenhum arquivo '*ENTRADAS*.xlsx' encontrado na pasta da operação."
# Sentinela exportada pra interface.render_auditoria_divergencia_entradas()
# distinguir "arquivo não existe" (normal, st.info) de qualquer outro erro
# em resultado['erros'] (dependência ausente, coluna faltando, arquivo
# corrompido — st.error com o motivo real). Achado real 2026-07-16: sem
# essa distinção, um ImportError de 'openpyxl' ausente no runtime
# portátil de PB/cometa aparecia como "sem Excel" — mascarando a causa.

_COLUNAS_EXCEL_VALOR_CANDIDATAS = ("Sum(Valor_total_prod)", "$VT")
# Nome da coluna de valor no Excel de referência varia por export: a
# TABELA ENTRADAS da geraldo/PB tem as duas colunas, mas a TABELA SAÍDAS
# só tem '$VT' — checa nessa ordem de prioridade em vez de um nome fixo.


def _coluna_valor_excel_referencia(df_excel: pd.DataFrame) -> "str | None":
    for c in _COLUNAS_EXCEL_VALOR_CANDIDATAS:
        if c in df_excel.columns:
            return c
    return None


def _localizar_excel_entradas_referencia() -> "Path | None":
    """Localiza o Excel de referência de entradas na raiz da operação — o
    nome varia por operação, não só o sufixo (uuid aleatório): geraldo/PB
    usam 'TABELA ENTRADAS A SE EXPORTADA AO HUNTER(<uuid>).xlsx', cometa
    usa 'COMETA ENTRADAS.xlsx' (sem prefixo 'TABELA', sem uuid). Por isso a
    busca é por qualquer '.xlsx' na raiz cujo nome contenha 'ENTRADAS'
    (case-insensitive), não por um prefixo fixo. Ignora arquivos
    temporários do Excel (~$...). None se a operação não tiver esse arquivo
    (normal — é um estudo pontual, não um dado obrigatório de todo estágio)."""
    candidatos = sorted(
        p for p in _OPERACAO_DIR.glob("*.xlsx")
        if not p.name.startswith("~$") and "ENTRADAS" in p.stem.upper()
    )
    return candidatos[0] if candidatos else None


@st.cache_data(ttl=1800, show_spinner=False)
def carregar_excel_entradas_referencia() -> "tuple[pd.DataFrame, dict]":
    """Carrega o Excel de referência de entradas (outra aplicação do
    usuário) — só a coluna `CHAVE` (renomeada `CHV_NFE`) importa pro estudo
    de divergência, que não cruza código de item. Regra R07: `CHV_NFE`
    sempre string."""
    caminho = _localizar_excel_entradas_referencia()
    meta: dict = {"arquivo": str(caminho) if caminho else None, "erros": []}
    if caminho is None:
        meta["erros"].append(MSG_SEM_EXCEL_ENTRADAS_REFERENCIA)
        return pd.DataFrame(), meta
    try:
        df = pd.read_excel(caminho, dtype=str)
    except Exception as exc:
        meta["erros"].append(str(exc))
        logger.exception("Erro ao ler Excel de referência de entradas em %s: %s", caminho, exc)
        return pd.DataFrame(), meta
    if "CHAVE" not in df.columns:
        meta["erros"].append(f"Coluna 'CHAVE' não encontrada em {caminho.name}.")
        return pd.DataFrame(), meta
    df = df.rename(columns={"CHAVE": "CHV_NFE"})
    df["CHV_NFE"] = df["CHV_NFE"].astype(str).str.strip()
    meta["total_linhas"] = len(df)
    meta["total_chaves"] = df["CHV_NFE"].nunique()
    return df, meta


MSG_SEM_EXCEL_SAIDAS_REFERENCIA = "Nenhum arquivo '*SAIDAS*.xlsx' encontrado na pasta da operação."
# Mesmo papel de MSG_SEM_EXCEL_ENTRADAS_REFERENCIA, pro lado saídas
# (auditar_divergencia_saidas(), 2026-07-17).


def _localizar_excel_saidas_referencia() -> "Path | None":
    """Localiza o Excel de referência de saídas na raiz da operação — mesmo
    critério de _localizar_excel_entradas_referencia() (nome varia por
    operação/distribuidora: 'TABELA SAÍDAS A SE EXPORTADA AO
    HUNTER(<uuid>).xlsx' na geraldo/PB, 'COMETA SAÍDAS.xlsx' na cometa).
    Busca por '.xlsx' na raiz cujo nome normalizado (sem acento,
    maiúsculo — _normalizar_str()) contenha 'SAIDA', não por prefixo fixo
    — 'SAÍDAS' com acento não bateria com um `.upper()` puro. Ignora
    arquivos temporários do Excel (~$...). None se a operação não tiver
    esse arquivo (normal — estudo pontual, não dado obrigatório)."""
    candidatos = sorted(
        p for p in _OPERACAO_DIR.glob("*.xlsx")
        if not p.name.startswith("~$") and "SAIDA" in _normalizar_str(p.stem)
    )
    return candidatos[0] if candidatos else None


@st.cache_data(ttl=1800, show_spinner=False)
def carregar_excel_saidas_referencia() -> "tuple[pd.DataFrame, dict]":
    """Carrega o Excel de referência de saídas — mesmo padrão de
    carregar_excel_entradas_referencia() (só a coluna `CHAVE`, renomeada
    `CHV_NFE`, importa pro estudo de divergência)."""
    caminho = _localizar_excel_saidas_referencia()
    meta: dict = {"arquivo": str(caminho) if caminho else None, "erros": []}
    if caminho is None:
        meta["erros"].append(MSG_SEM_EXCEL_SAIDAS_REFERENCIA)
        return pd.DataFrame(), meta
    try:
        df = pd.read_excel(caminho, dtype=str)
    except Exception as exc:
        meta["erros"].append(str(exc))
        logger.exception("Erro ao ler Excel de referência de saídas em %s: %s", caminho, exc)
        return pd.DataFrame(), meta
    if "CHAVE" not in df.columns:
        meta["erros"].append(f"Coluna 'CHAVE' não encontrada em {caminho.name}.")
        return pd.DataFrame(), meta
    df = df.rename(columns={"CHAVE": "CHV_NFE"})
    df["CHV_NFE"] = df["CHV_NFE"].astype(str).str.strip()
    meta["total_linhas"] = len(df)
    meta["total_chaves"] = df["CHV_NFE"].nunique()
    return df, meta


MSG_SEM_EXCEL_ESTOQUE_REFERENCIA = "Nenhum arquivo '*ESTOQUE*.xlsx' encontrado na pasta da operação."
# Mesmo papel de MSG_SEM_EXCEL_ENTRADAS_REFERENCIA/MSG_SEM_EXCEL_SAIDAS_
# REFERENCIA, pro lado estoque (auditar_divergencia_estoque(), 2026-07-17).


def _localizar_excel_estoque_referencia() -> "Path | None":
    """Localiza o Excel de referência de estoque na raiz da operação —
    mesmo critério de _localizar_excel_entradas_referencia()/_localizar_
    excel_saidas_referencia(): busca por '.xlsx' na raiz cujo nome
    normalizado (_normalizar_str()) contenha 'ESTOQUE'. As 3 operações
    reais usam 'ESTOQUE(<uuid>).xlsx' (sem acento — não precisaria de
    _normalizar_str aqui, usado só por consistência com as outras duas
    buscas). Ignora arquivos temporários (~$...). None se a operação não
    tiver esse arquivo (normal — estudo pontual, não dado obrigatório)."""
    candidatos = sorted(
        p for p in _OPERACAO_DIR.glob("*.xlsx")
        if not p.name.startswith("~$") and "ESTOQUE" in _normalizar_str(p.stem)
    )
    return candidatos[0] if candidatos else None


def _normalizar_cod_item_numerico(serie: pd.Series) -> pd.Series:
    """Normaliza código de item puramente numérico pra comparação entre
    fontes com padding de zeros à esquerda diferente — achado real: SPED
    grava COD_ITEM_DECLARACAO com zeros à esquerda (ex.: geraldo usa 14
    dígitos, cometa varia entre 7 e 13 dígitos dentro da MESMA operação),
    mas o Excel ESTOQUE(...).xlsx grava CodItem como inteiro puro (sem
    padding) — comparação direta por string sempre divergiria. Converte
    pra número e volta pra string, removendo o padding dos dois lados.
    Confirmado nas 3 operações reais: COD_ITEM_DECLARACAO é sempre
    puramente numérico nesta base."""
    return pd.to_numeric(serie, errors="coerce").astype("Int64").astype(str)


def _normalizar_cod_item_flexivel(serie: pd.Series) -> pd.Series:
    """Remove zeros à esquerda só de códigos PURAMENTE numéricos (unifica
    padding entre fontes — ex.: `estoque_entradas.COD_ITEM_DECLARACAO`
    grava `"00000000013990"`, `estoque_saidas.fatoitemnfe_infnfe_det_
    prod_cprod` grava `"013990"` pro MESMO item — ver gerar_cruzamento_
    valor()); preserva código alfanumérico como está (ex.: `"125KGRAXA"`,
    `"VEIC_008047"` da cometa), que `_normalizar_cod_item_numerico()`
    destruiria virando `NaN`/`"<NA>"` — diferente daquela função (usada
    só no contexto do Bloco H, confirmado 100% numérico), aqui o dado
    fonte é XML de venda, onde código alfanumérico é legítimo e comum."""
    s = serie.astype(str).str.strip()
    numerico = s.str.fullmatch(r"\d+").fillna(False)
    s = s.copy()
    s.loc[numerico] = pd.to_numeric(s.loc[numerico]).astype("int64").astype(str)
    return s


@st.cache_data(ttl=1800, show_spinner=False)
def carregar_excel_estoque_referencia() -> "tuple[pd.DataFrame, dict]":
    """Carrega o Excel de referência de estoque (outra aplicação do
    usuário) no MESMO modelo de linha do arquivo original — uma linha por
    declaração de inventário (H010), sem expandir pro formato 'largo'
    item×ano (ver docs/estagios/05_tabela_estoque.md). Corrigido
    2026-07-17 (mesmo dia): a primeira versão desta função split cada
    declaração em EI/EF e comparava contra estoque_anual_consolidado (já
    no formato largo) — tecnicamente correto, mas o usuário pediu pra
    comparar "no modelo do CSV": uma linha por declaração, direto contra
    load_declaracao_estoque() (H010 cru, mesma granularidade), sem passar
    pelo Estágio 5. `ANO_REFERENCIA` usa `EstFinal` (o ano de fechamento
    daquela contagem) — equivalente ao ano de `DT_INV` do lado Hunter
    (ver auditar_divergencia_estoque()); `EstInicial` não é usado aqui
    porque é sempre `EstFinal + 1` pra MESMA quantidade (redundante nesta
    granularidade). Confirmado nas 3 operações reais: total de linhas do
    Excel bate com o total de linhas H010 do Hunter (geraldo 25.590 x
    25.600; PB 127 x 127 exato; cometa 75 x 75 exato). Regra R07:
    ANO_REFERENCIA/COD_ITEM sempre string; EXCEL_QTDE fica float
    (_numero_decimal_br, tolera vírgula ou ponto decimal)."""
    caminho = _localizar_excel_estoque_referencia()
    meta: dict = {"arquivo": str(caminho) if caminho else None, "erros": []}
    if caminho is None:
        meta["erros"].append(MSG_SEM_EXCEL_ESTOQUE_REFERENCIA)
        return pd.DataFrame(), meta
    try:
        df = pd.read_excel(caminho)
    except Exception as exc:
        meta["erros"].append(str(exc))
        logger.exception("Erro ao ler Excel de referência de estoque em %s: %s", caminho, exc)
        return pd.DataFrame(), meta

    colunas_obrigatorias = {"CodItem", "Qtde", "EstFinal", "DescItem"}
    faltando = colunas_obrigatorias - set(df.columns)
    if faltando:
        meta["erros"].append(f"Coluna(s) {sorted(faltando)} não encontrada(s) em {caminho.name}.")
        return pd.DataFrame(), meta

    resultado = pd.DataFrame({
        "ANO_REFERENCIA":    df["EstFinal"].astype(str),
        "COD_ITEM":          _normalizar_cod_item_numerico(df["CodItem"]),
        "EXCEL_QTDE":        _numero_decimal_br(df["Qtde"]),
        "EXCEL_DESCR_ITEM":  df["DescItem"].astype(str),
    })

    meta["total_linhas"] = len(resultado)
    meta["total_itens"] = resultado["COD_ITEM"].nunique()
    return resultado, meta


def _contagem_por_chave_nfe(tabela: str) -> pd.Series:
    """Conta linhas por CHV_NFE (`fatonfe_infprot_chnfe`) numa tabela do
    DuckDB da operação — Series vazia se a tabela ou o banco não existirem
    (não quebra a auditoria, só fica sem essa fonte de reconciliação)."""
    if not _BANCO_PATH.exists():
        return pd.Series(dtype=int)
    try:
        with duckdb.connect(str(_BANCO_PATH), read_only=True) as con:
            tabelas = {r[0] for r in con.execute("SHOW TABLES").fetchall()}
            if tabela not in tabelas:
                return pd.Series(dtype=int)
            df = con.execute(
                f"SELECT fatonfe_infprot_chnfe AS CHV_NFE, COUNT(*) AS N "
                f"FROM {tabela} GROUP BY fatonfe_infprot_chnfe"
            ).df()
        return df.set_index("CHV_NFE")["N"]
    except Exception:
        logger.exception("Erro ao contar %s por CHV_NFE em %s", tabela, _BANCO_PATH)
        return pd.Series(dtype=int)


def _chaves_autoemissao_duplicada() -> set:
    """CHV_NFE de notas autoemitidas (`CNPJ_EMITENTE == CNPJ_DESTINATARIO
    == CNPJ da auditada`) que aparecem tanto em `PASTA_ORIGEM='ET'` quanto
    em `'EP'` — caso real conhecido desde 2026-07-05 (11 notas, 241 linhas
    duplicadas em `nfe_entradas`; não corrigido, decisão do usuário na
    época). Usado só pra anotar/cruzar contra a auditoria de divergência
    (ver `auditar_divergencia_entradas()`), não corrige o dado em si."""
    entidade = obter_entidade_auditada()
    cnpj_auditada = (entidade or {}).get("cnpj")
    if not cnpj_auditada:
        return set()
    r = _classificar_itens_nfe()
    combinado = pd.concat(
        [r["entradas"], r["saidas"], r["analise_et"], r["analise_ep"], r["situacao_et"], r["situacao_ep"]],
        ignore_index=True,
    )
    if combinado.empty or "fatonfe_infnfe_emit_cnpj" not in combinado.columns:
        return set()
    emit = combinado["fatonfe_infnfe_emit_cnpj"].apply(_normalizar_cnpj)
    dest = combinado["fatonfe_infnfe_dest_cnpj"].apply(_normalizar_cnpj)
    autoemissao = (emit == cnpj_auditada) & (dest == cnpj_auditada)
    if not autoemissao.any():
        return set()
    sub = combinado.loc[autoemissao, [_COL_CHAVE_NFE, "PASTA_ORIGEM"]]
    contagem_pastas = sub.groupby(_COL_CHAVE_NFE)["PASTA_ORIGEM"].nunique()
    return set(contagem_pastas[contagem_pastas > 1].index)


def _detalhar_chaves_hunter_ausentes_no_excel(chaves: set, tabela: str = "estoque_entradas") -> pd.DataFrame:
    """Detalha (CHV_NFE, DATA_ELEITA, VL_ITEM, EMITENTE) das linhas de
    `tabela` (`estoque_entradas` ou, desde 2026-07-17, `estoque_saidas`)
    cuja CHV_NFE está em 'chaves' — usado pro 'Resíduo Hunter' de
    auditar_divergencia_entradas()/auditar_divergencia_saidas() (chaves
    que o Hunter tem e o Excel de referência não cita em nenhuma linha).
    Uma linha por item (não por nota) — uma mesma CHV_NFE pode aparecer
    várias vezes se a nota tiver mais de um item; a contagem de chaves
    ÚNICAS é responsabilidade de quem consome o retorno (ex.: nunique() na
    UI). Regra R07: CHV_NFE sempre string. Vazio se não houver chaves ou o
    banco/tabela não existir (não é erro). `tabela` só recebe literais
    fixos das duas chamadoras (nunca input do usuário)."""
    colunas = ["CHV_NFE", "DATA_ELEITA", "VL_ITEM", "EMITENTE"]
    if not chaves or not _BANCO_PATH.exists():
        return pd.DataFrame(columns=colunas)
    try:
        with duckdb.connect(str(_BANCO_PATH), read_only=True) as con:
            tabelas = {r[0] for r in con.execute("SHOW TABLES").fetchall()}
            if tabela not in tabelas:
                return pd.DataFrame(columns=colunas)
            con.register("_chaves_so_hunter", pd.DataFrame({"CHV_NFE": list(chaves)}))
            df = con.execute(
                f"SELECT e.fatonfe_infprot_chnfe AS CHV_NFE, e.DATA_ELEITA, "
                f"e.fatoitemnfe_infnfe_det_prod_vprod AS VL_ITEM, "
                f"e.fatonfe_infnfe_emit_xnome AS EMITENTE "
                f"FROM {tabela} e "
                "INNER JOIN _chaves_so_hunter c ON e.fatonfe_infprot_chnfe = c.CHV_NFE"
            ).df()
            con.unregister("_chaves_so_hunter")
        df["CHV_NFE"] = df["CHV_NFE"].astype(str)
        return df
    except Exception:
        logger.exception("Erro ao detalhar chaves só no Hunter em %s", _BANCO_PATH)
        return pd.DataFrame(columns=colunas)


def _filtrar_serie_chv_por_periodo(serie: pd.Series, periodo: "dict | None") -> pd.Series:
    """Filtra uma Series indexada por CHV_NFE ao Período de Auditoria
    (`periodo`, já resolvido por `obter_periodo_auditoria()` — recebido
    como parâmetro em vez de consultado aqui de novo, pra não reabrir o
    banco a cada série filtrada) — ano embutido nos dígitos 3-4 da chave
    de acesso ('AA' -> '20AA'), mesmo critério já usado na quebra "por
    ano" de `interface.render_auditoria_divergencia_entradas()`. Sem
    período configurado (`periodo=None`), devolve a Series inalterada —
    mesmo comportamento de antes de 2026-07-18."""
    if not periodo or serie.empty:
        return serie
    ano_ini, ano_fim = int(periodo["ano_inicial"]), int(periodo["ano_final"])
    anos = ("20" + pd.Series(serie.index, index=serie.index).astype(str).str[2:4]).astype(int)
    return serie[(anos >= ano_ini) & (anos <= ano_fim)]


def _filtrar_df_chv_por_periodo(df: pd.DataFrame, periodo: "dict | None", coluna: str = "CHV_NFE") -> pd.DataFrame:
    """Mesmo filtro de `_filtrar_serie_chv_por_periodo()`, pra um
    DataFrame com uma coluna de CHV_NFE em vez de índice."""
    if not periodo or df.empty:
        return df
    ano_ini, ano_fim = int(periodo["ano_inicial"]), int(periodo["ano_final"])
    anos = ("20" + df[coluna].astype(str).str[2:4]).astype(int)
    return df[(anos >= ano_ini) & (anos <= ano_fim)]


def auditar_divergencia_entradas() -> dict:
    """Estudo de diferenças Hunter × Excel de referência, SEM cruzar código
    de item — só `CHV_NFE` + contagem de itens por nota. Pra cada chave do
    Excel, reconcilia o resíduo (itens do Excel não explicados por
    `estoque_entradas`) num waterfall, nesta ordem: `xml_saidas_real`
    (Estágio 3 — reclassificado como saída física pelo papel da auditada),
    `nfe_situacao_et`/`nfe_situacao_ep` (situação irregular) e
    `nfe_analise_et`/`nfe_analise_ep` (CFOP de watchlist — inclui EP porque
    uma chave pode ter sido lida originalmente da pasta EP e só
    reclassificada como entrada real pelo Estágio 3) — cada nível só
    reconcilia o que sobrou do anterior, evitando contar o mesmo item em
    mais de uma categoria. O que sobrar depois é 'divergência não
    identificada' — na prática, majoritariamente chaves cujo XML
    simplesmente não existe em `1-DOCFISCAIS/nf/` (nem ET nem EP), não uma
    diferença de classificação (ver `chaves_divergentes` pra investigar
    caso a caso).

    Análise bidirecional de chaves (2026-07-15, complementar a
    `chaves_divergentes` — que reconcilia por CONTAGEM dentro de cada
    chave presente no Excel; isto aqui é presença/ausência TOTAL da chave
    num lado ou no outro):
    - `residuo_hunter`: linhas de `estoque_entradas` cuja CHV_NFE não
      aparece em nenhuma linha do Excel — "compras que a empresa recebeu
      mas que não constam no relatório enviado pro Hunter conferir".
    - `residuo_csv`: linhas do Excel cuja CHV_NFE não aparece em NENHUMA
      das 4 fontes do Hunter (`estoque_entradas`, `xml_saidas_real`,
      `nfe_situacao_et/ep`, `nfe_analise_et/ep`) — candidatas a "XML nunca
      chegou em `1-DOCFISCAIS/nf/`", o subconjunto mais acionável de
      `ITENS_NAO_IDENTIFICADOS` (que também inclui chaves parcialmente
      presentes, só com contagem diferente).

    Escopo do Período de Auditoria (2026-07-18): quando `obter_periodo_
    auditoria()` está configurado, restringe a comparação às chaves cujo
    ano (dígitos 3-4 da CHV_NFE) cai entre `ano_inicial` e `ano_final` —
    mesmo filtro já aplicado em `auditar_divergencia_estoque()`. Sem
    período configurado, mantém o comportamento anterior (todas as
    chaves, de qualquer ano).

    Devolve `{'resumo': dict, 'chaves_divergentes': DataFrame,
    'residuo_hunter': DataFrame, 'residuo_csv': DataFrame, 'erros': list}`
    — `erros` não-vazio quando não há Excel de referência nesta operação
    (não é uma falha, só indica que o estudo não se aplica)."""
    df_excel, meta_excel = carregar_excel_entradas_referencia()
    if df_excel.empty:
        return {
            "resumo": {}, "chaves_divergentes": pd.DataFrame(),
            "residuo_hunter": pd.DataFrame(), "residuo_csv": pd.DataFrame(),
            "erros": meta_excel.get("erros", []),
        }

    periodo = obter_periodo_auditoria()
    df_excel = _filtrar_df_chv_por_periodo(df_excel, periodo)

    excel_por_chave = df_excel.groupby("CHV_NFE").size().rename("EXCEL_QTD_ITENS")
    hunter_entradas = _filtrar_serie_chv_por_periodo(
        _contagem_por_chave_nfe("estoque_entradas"), periodo
    ).rename("HUNTER_ENTRADAS_QTD")
    hunter_saidas = _filtrar_serie_chv_por_periodo(
        _contagem_por_chave_nfe("xml_saidas_real"), periodo
    ).rename("HUNTER_SAIDAS_QTD")
    hunter_situacao = _filtrar_serie_chv_por_periodo(
        _contagem_por_chave_nfe("nfe_situacao_et").add(_contagem_por_chave_nfe("nfe_situacao_ep"), fill_value=0),
        periodo,
    ).rename("HUNTER_SITUACAO_QTD")
    hunter_analise = _filtrar_serie_chv_por_periodo(
        _contagem_por_chave_nfe("nfe_analise_et").add(_contagem_por_chave_nfe("nfe_analise_ep"), fill_value=0),
        periodo,
    ).rename("HUNTER_ANALISE_QTD")

    base = pd.DataFrame(excel_por_chave)
    for serie in (hunter_entradas, hunter_saidas, hunter_situacao, hunter_analise):
        base = base.join(serie, how="left")
    base = base.fillna(0).astype(int)

    # Waterfall: entradas reais primeiro (o "lar" natural do item), depois
    # o resíduo é testado contra saídas/situação/análise nessa ordem. tpnf +
    # papel da auditada (que decide entrada x saída real) é atributo da
    # NOTA inteira, então raramente se sobrepõe com CFOP de watchlist (que é
    # por ITEM) dentro da mesma nota — daí a ordem evitar dupla contagem na
    # prática, não só na teoria.
    base["ITENS_ENTRADAS_REAIS"] = base[["EXCEL_QTD_ITENS", "HUNTER_ENTRADAS_QTD"]].min(axis=1)
    residual_1 = base["EXCEL_QTD_ITENS"] - base["ITENS_ENTRADAS_REAIS"]
    base["ITENS_SAIDAS_REAIS"] = pd.concat([residual_1, base["HUNTER_SAIDAS_QTD"]], axis=1).min(axis=1)
    residual_2 = residual_1 - base["ITENS_SAIDAS_REAIS"]
    base["ITENS_SITUACAO"] = pd.concat([residual_2, base["HUNTER_SITUACAO_QTD"]], axis=1).min(axis=1)
    residual_3 = residual_2 - base["ITENS_SITUACAO"]
    base["ITENS_ANALISE_CFOP"] = pd.concat([residual_3, base["HUNTER_ANALISE_QTD"]], axis=1).min(axis=1)
    base["ITENS_NAO_IDENTIFICADOS"] = residual_3 - base["ITENS_ANALISE_CFOP"]

    # total_hunter_entradas aqui é restrito às chaves que TAMBÉM estão no
    # Excel (índice de 'base' = chaves do Excel) — não é o total real de
    # `estoque_entradas`. hunter_so_entradas mede o inverso: itens que o
    # Hunter tem e o Excel não (chave nem aparece no Excel) — gap na
    # direção oposta, pequeno mas real.
    total_real_hunter_entradas = int(hunter_entradas.sum())
    hunter_so_entradas = total_real_hunter_entradas - int(base["HUNTER_ENTRADAS_QTD"].sum())

    resumo = {
        "total_excel": int(base["EXCEL_QTD_ITENS"].sum()),
        "total_hunter_entradas": total_real_hunter_entradas,
        "itens_hunter_ausentes_no_excel": hunter_so_entradas,
        "itens_entradas_reais": int(base["ITENS_ENTRADAS_REAIS"].sum()),
        "itens_saidas_reais": int(base["ITENS_SAIDAS_REAIS"].sum()),
        "itens_situacao": int(base["ITENS_SITUACAO"].sum()),
        "itens_analise_cfop": int(base["ITENS_ANALISE_CFOP"].sum()),
        "itens_nao_identificados": int(base["ITENS_NAO_IDENTIFICADOS"].sum()),
    }

    chaves_autoemissao = _chaves_autoemissao_duplicada()
    base["CASO_AUTOEMISSAO_DUPLICADA"] = base.index.isin(chaves_autoemissao)
    resumo["chaves_autoemissao_na_divergencia"] = int(
        (base.index.isin(chaves_autoemissao) & (base["ITENS_NAO_IDENTIFICADOS"] > 0)).sum()
    )
    resumo["periodo"] = periodo

    divergentes = base[base["EXCEL_QTD_ITENS"] != base["HUNTER_ENTRADAS_QTD"]].copy()
    divergentes.index.name = "CHV_NFE"
    divergentes = divergentes.reset_index().sort_values("ITENS_NAO_IDENTIFICADOS", ascending=False)
    divergentes["CHV_NFE"] = divergentes["CHV_NFE"].astype(str)

    # Análise bidirecional de chaves (2026-07-15) — ver docstring.
    chaves_excel = set(excel_por_chave.index)
    chaves_hunter_qualquer = (
        set(hunter_entradas.index) | set(hunter_saidas.index)
        | set(hunter_situacao.index) | set(hunter_analise.index)
    )
    chaves_so_hunter = set(hunter_entradas.index) - chaves_excel
    chaves_so_csv = chaves_excel - chaves_hunter_qualquer

    residuo_hunter = _detalhar_chaves_hunter_ausentes_no_excel(chaves_so_hunter)
    # 'DataFinal' e a coluna de valor (ver _coluna_valor_excel_referencia())
    # são específicas do layout do Excel de cada operação — checadas em vez
    # de assumidas, pra não quebrar se outra operação vier a usar este
    # estudo com um Excel de layout diferente.
    col_valor = _coluna_valor_excel_referencia(df_excel)
    colunas_excel_extra = [c for c in ("DataFinal", col_valor) if c and c in df_excel.columns]
    residuo_csv = df_excel[df_excel["CHV_NFE"].isin(chaves_so_csv)][["CHV_NFE", *colunas_excel_extra]].rename(
        columns={"DataFinal": "DATA", **({col_valor: "VALOR"} if col_valor else {})}
    ).copy()
    residuo_csv["CHV_NFE"] = residuo_csv["CHV_NFE"].astype(str)

    return {
        "resumo": resumo, "chaves_divergentes": divergentes,
        "residuo_hunter": residuo_hunter, "residuo_csv": residuo_csv,
        "erros": [],
    }


def auditar_divergencia_saidas() -> dict:
    """Espelho de auditar_divergencia_entradas() (2026-07-17) pro lado
    saídas: compara o Excel de referência de saídas ('*SAIDAS*.xlsx' na
    raiz da operação, ver carregar_excel_saidas_referencia()) com
    `estoque_saidas` (Estágio 4), SEM cruzar código de item — só `CHV_NFE`
    + contagem de itens por nota. Mesmo waterfall de reconciliação, com os
    papéis principal/reconciliação invertidos: `estoque_saidas` é a fonte
    principal (equivalente a `estoque_entradas` do lado entradas) e
    `xml_entradas_real` é o primeiro fallback de reconciliação
    (equivalente a `xml_saidas_real` do lado entradas) — mesmo `PASTA_
    ORIGEM` não bater 1:1 com a direção real (uma nota de EP pode virar
    entrada_real, uma de ET pode virar saida_real, ver Estágio 3).
    `nfe_situacao_et/ep` e `nfe_analise_et/ep` são os mesmos dois níveis
    seguintes, sem duplicar (não têm direção — servem os dois estudos).

    Devolve o mesmo formato de auditar_divergencia_entradas():
    `{'resumo': dict, 'chaves_divergentes': DataFrame, 'residuo_hunter':
    DataFrame, 'residuo_csv': DataFrame, 'erros': list}` — as colunas de
    `chaves_divergentes`/`resumo` usam os MESMOS nomes (`ITENS_ENTRADAS_
    REAIS`/`ITENS_SAIDAS_REAIS` etc.) que a versão entradas; só o que é
    "principal" vs. "reconciliação" se inverte.

    Escopo do Período de Auditoria (2026-07-18): mesmo filtro de
    `auditar_divergencia_entradas()` — ver docstring lá."""
    df_excel, meta_excel = carregar_excel_saidas_referencia()
    if df_excel.empty:
        return {
            "resumo": {}, "chaves_divergentes": pd.DataFrame(),
            "residuo_hunter": pd.DataFrame(), "residuo_csv": pd.DataFrame(),
            "erros": meta_excel.get("erros", []),
        }

    periodo = obter_periodo_auditoria()
    df_excel = _filtrar_df_chv_por_periodo(df_excel, periodo)

    excel_por_chave = df_excel.groupby("CHV_NFE").size().rename("EXCEL_QTD_ITENS")
    hunter_saidas = _filtrar_serie_chv_por_periodo(
        _contagem_por_chave_nfe("estoque_saidas"), periodo
    ).rename("HUNTER_SAIDAS_QTD")
    hunter_entradas = _filtrar_serie_chv_por_periodo(
        _contagem_por_chave_nfe("xml_entradas_real"), periodo
    ).rename("HUNTER_ENTRADAS_QTD")
    hunter_situacao = _filtrar_serie_chv_por_periodo(
        _contagem_por_chave_nfe("nfe_situacao_et").add(_contagem_por_chave_nfe("nfe_situacao_ep"), fill_value=0),
        periodo,
    ).rename("HUNTER_SITUACAO_QTD")
    hunter_analise = _filtrar_serie_chv_por_periodo(
        _contagem_por_chave_nfe("nfe_analise_et").add(_contagem_por_chave_nfe("nfe_analise_ep"), fill_value=0),
        periodo,
    ).rename("HUNTER_ANALISE_QTD")

    base = pd.DataFrame(excel_por_chave)
    for serie in (hunter_saidas, hunter_entradas, hunter_situacao, hunter_analise):
        base = base.join(serie, how="left")
    base = base.fillna(0).astype(int)

    # Waterfall: saídas reais primeiro (o "lar" natural do item aqui),
    # depois o resíduo é testado contra entradas/situação/análise nessa
    # ordem — mesmo raciocínio de auditar_divergencia_entradas(), invertido.
    base["ITENS_SAIDAS_REAIS"] = base[["EXCEL_QTD_ITENS", "HUNTER_SAIDAS_QTD"]].min(axis=1)
    residual_1 = base["EXCEL_QTD_ITENS"] - base["ITENS_SAIDAS_REAIS"]
    base["ITENS_ENTRADAS_REAIS"] = pd.concat([residual_1, base["HUNTER_ENTRADAS_QTD"]], axis=1).min(axis=1)
    residual_2 = residual_1 - base["ITENS_ENTRADAS_REAIS"]
    base["ITENS_SITUACAO"] = pd.concat([residual_2, base["HUNTER_SITUACAO_QTD"]], axis=1).min(axis=1)
    residual_3 = residual_2 - base["ITENS_SITUACAO"]
    base["ITENS_ANALISE_CFOP"] = pd.concat([residual_3, base["HUNTER_ANALISE_QTD"]], axis=1).min(axis=1)
    base["ITENS_NAO_IDENTIFICADOS"] = residual_3 - base["ITENS_ANALISE_CFOP"]

    total_real_hunter_saidas = int(hunter_saidas.sum())
    hunter_so_saidas = total_real_hunter_saidas - int(base["HUNTER_SAIDAS_QTD"].sum())

    resumo = {
        "total_excel": int(base["EXCEL_QTD_ITENS"].sum()),
        "total_hunter_saidas": total_real_hunter_saidas,
        "itens_hunter_ausentes_no_excel": hunter_so_saidas,
        "itens_saidas_reais": int(base["ITENS_SAIDAS_REAIS"].sum()),
        "itens_entradas_reais": int(base["ITENS_ENTRADAS_REAIS"].sum()),
        "itens_situacao": int(base["ITENS_SITUACAO"].sum()),
        "itens_analise_cfop": int(base["ITENS_ANALISE_CFOP"].sum()),
        "itens_nao_identificados": int(base["ITENS_NAO_IDENTIFICADOS"].sum()),
    }

    chaves_autoemissao = _chaves_autoemissao_duplicada()
    base["CASO_AUTOEMISSAO_DUPLICADA"] = base.index.isin(chaves_autoemissao)
    resumo["chaves_autoemissao_na_divergencia"] = int(
        (base.index.isin(chaves_autoemissao) & (base["ITENS_NAO_IDENTIFICADOS"] > 0)).sum()
    )
    resumo["periodo"] = periodo

    divergentes = base[base["EXCEL_QTD_ITENS"] != base["HUNTER_SAIDAS_QTD"]].copy()
    divergentes.index.name = "CHV_NFE"
    divergentes = divergentes.reset_index().sort_values("ITENS_NAO_IDENTIFICADOS", ascending=False)
    divergentes["CHV_NFE"] = divergentes["CHV_NFE"].astype(str)

    chaves_excel = set(excel_por_chave.index)
    chaves_hunter_qualquer = (
        set(hunter_saidas.index) | set(hunter_entradas.index)
        | set(hunter_situacao.index) | set(hunter_analise.index)
    )
    chaves_so_hunter = set(hunter_saidas.index) - chaves_excel
    chaves_so_csv = chaves_excel - chaves_hunter_qualquer

    residuo_hunter = _detalhar_chaves_hunter_ausentes_no_excel(chaves_so_hunter, tabela="estoque_saidas")
    col_valor = _coluna_valor_excel_referencia(df_excel)
    colunas_excel_extra = [c for c in ("DataFinal", col_valor) if c and c in df_excel.columns]
    residuo_csv = df_excel[df_excel["CHV_NFE"].isin(chaves_so_csv)][["CHV_NFE", *colunas_excel_extra]].rename(
        columns={"DataFinal": "DATA", **({col_valor: "VALOR"} if col_valor else {})}
    ).copy()
    residuo_csv["CHV_NFE"] = residuo_csv["CHV_NFE"].astype(str)

    return {
        "resumo": resumo, "chaves_divergentes": divergentes,
        "residuo_hunter": residuo_hunter, "residuo_csv": residuo_csv,
        "erros": [],
    }


_TOLERANCIA_DIVERGENCIA_ESTOQUE = 0.01
# Tolerância de arredondamento na comparação de quantidades — Qtde do Excel
# e QTD do Hunter passam por conversões BR (vírgula decimal) independentes;
# diferenças de centésimos são ruído de ponto flutuante, não divergência
# real.


def _declaracoes_estoque_hunter() -> pd.DataFrame:
    """H010 cru (uma linha por declaração de inventário), no MESMO modelo
    de linha do Excel de referência (ver carregar_excel_estoque_
    referencia()) — usado só por auditar_divergencia_estoque(). ANO_
    REFERENCIA = ano de DT_INV, que a correção de 2026-07-17 em
    montar_estoque_anual_consolidado() já estabeleceu como o ano de
    FECHAMENTO daquela contagem (equivalente a EstFinal do Excel).
    Ignora `DT_INV` malformado (mesmo filtro de montar_estoque_anual_
    consolidado()). Vazia se não houver SPED de Bloco H nesta operação."""
    df_est, _ = load_declaracao_estoque()
    if df_est.empty or "DT_INV" not in df_est.columns:
        return pd.DataFrame(columns=["ANO_REFERENCIA", "COD_ITEM", "QUANTIDADE"])
    df = df_est[df_est["DT_INV"].str.fullmatch(r"\d{8}")].copy()
    if df.empty:
        return pd.DataFrame(columns=["ANO_REFERENCIA", "COD_ITEM", "QUANTIDADE"])
    return pd.DataFrame({
        "ANO_REFERENCIA": df["DT_INV"].str[4:8],
        "COD_ITEM":       _normalizar_cod_item_numerico(df["COD_ITEM"]),
        "QUANTIDADE":     _numero_decimal_br(df["QTD"]),
    })


def _ordenar_duplicatas_por_quantidade(df: pd.DataFrame, col_qtd: str, chave: list) -> pd.DataFrame:
    """Numera duplicatas de `chave` (0, 1, 2...) em ordem CRESCENTE de
    `col_qtd` — usado por auditar_divergencia_estoque() pra parear
    declarações duplicadas do mesmo (COD_ITEM, ANO_REFERENCIA) entre
    Hunter e Excel pela quantidade mais próxima, em vez de manter a ordem
    original do arquivo (que pode casar a declaração errada quando há
    mais de uma linha pro mesmo par, gerando falso positivo de
    divergência). Ordenar os dois lados igual e casar por posição é ótimo
    pra minimizar a soma das diferenças absolutas entre dois conjuntos do
    mesmo tamanho — não é uma escolha arbitrária."""
    df = df.sort_values(chave + [col_qtd], kind="stable").copy()
    df["_ORDEM"] = df.groupby(chave).cumcount()
    return df


def auditar_divergencia_estoque() -> dict:
    """Estudo de diferenças Hunter × Excel de referência pro lado estoque
    (2026-07-17, revisado 2x no mesmo dia) — compara as declarações de
    inventário CRUAS do Bloco H (`_declaracoes_estoque_hunter()`, H010
    direto) com o Excel `ESTOQUE(...).xlsx` da raiz da operação, por
    `(COD_ITEM, ANO_REFERENCIA)`, no MESMO modelo de linha do arquivo de
    referência — uma linha por declaração física de inventário, não o
    formato "largo" item×ano do Estágio 5. Primeira versão comparava
    contra `estoque_anual_consolidado` (já expandido em EI/EF, 223 linhas
    na PB); usuário pediu pra usar "o modelo do CSV" — confirmado que a
    granularidade certa é a declaração crua: total de linhas do Excel bate
    quase exato com o total de H010 do Hunter nas 3 operações reais
    (geraldo 25.590×25.600; PB 127×127 exato; cometa 75×75 exato),
    dispensando inclusive a passagem pelo Estágio 5.

    Diferente de auditar_divergencia_entradas/saidas() (que cruzam por
    CHV_NFE + contagem de itens, sem valor), aqui a comparação é direta
    por QUANTIDADE — não há waterfall de reconciliação, é comparação
    1:1 de declaração.

    Ausência de um lado é tratada como quantidade 0 do lado ausente
    (fillna(0)) — não como erro: um item que só existe no Excel aparece
    como QUANTIDADE=0 do Hunter, e vice-versa, já capturando o resíduo
    bidirecional dentro da própria tabela de divergência.

    Achado real 1 (geraldo): 10 declarações H005 datadas `31/01/2020` são
    duplicidade pré-existente no SPED (mesma quantidade já coberta pela
    declaração normal de `31/12/2019`, ausentes do Excel de referência) —
    colidem em `ANO_REFERENCIA=2020` com a declaração real de
    `31/12/2020` do mesmo item.

    Achado real 2 (cometa, investigado a pedido do usuário): `COD_ITEM=4`
    é usado por DOIS produtos diferentes no SPED cru desta operação —
    `"0000000004"` (FEIJAO CARIOCA AG) e `"4"` sem padding (FEIJAO
    MACASSAR) — que colidem no mesmo `COD_ITEM` normalizado (ver
    `_normalizar_cod_item_numerico()`). O Excel de referência tem a MESMA
    colisão (2 linhas com `CodItem=4`, descrições diferentes) — os
    valores batem perfeitamente par a par (17.933,5 e 6.873,7 dos dois
    lados), mas a primeira versão desta função usava `groupby(...).first()`
    e comparava a declaração errada entre si (17.933,5 Hunter × 6.873,7
    Excel), reportando uma divergência de 11.059,8 que não existia.

    Ambos os achados são resolvidos pela mesma técnica —
    `_ordenar_duplicatas_por_quantidade()` em vez de `.first()`: quando um
    (COD_ITEM, ANO) tem mais de uma linha de um lado, casa pela
    quantidade mais próxima em vez de pela ordem de leitura do arquivo.
    Não corrige os dados de origem (SPED cru ou Excel) — só evita
    comparar a declaração errada dentro da auditoria.

    Escopo do Período de Auditoria (2026-07-18): quando `obter_periodo_
    auditoria()` está configurado (`config_auditoria`, definido em
    "EXTRAÇÃO"), a auditoria só considera `ANO_REFERENCIA` entre
    `ano_inicial` e `ano_final` — os Estoques Finais efetivamente exigidos
    pela fiscalização (ex.: período 2021-2024 processa EF(2021..2024),
    extraídos das declarações com `DT_INV` em 2021..2024 respectivamente —
    ver regra do usuário). Sem período configurado, mantém o comportamento
    anterior (mostra todos os anos presentes nos dados) — não filtra nada.

    Devolve `{'resumo': dict, 'divergentes': DataFrame, 'erros': list}`
    — `erros` não-vazio quando não há Excel de referência nesta operação
    ou nenhum SPED de Bloco H foi encontrado."""
    df_excel, meta_excel = carregar_excel_estoque_referencia()
    if df_excel.empty:
        return {"resumo": {}, "divergentes": pd.DataFrame(), "erros": meta_excel.get("erros", [])}

    hunter = _declaracoes_estoque_hunter()
    if hunter.empty:
        return {
            "resumo": {}, "divergentes": pd.DataFrame(),
            "erros": ["Nenhuma declaração de inventário (Bloco H) encontrada nesta operação."],
        }

    periodo = obter_periodo_auditoria()
    if periodo:
        ano_ini, ano_fim = int(periodo["ano_inicial"]), int(periodo["ano_final"])
        df_excel = df_excel[df_excel["ANO_REFERENCIA"].astype(int).between(ano_ini, ano_fim)]
        hunter = hunter[hunter["ANO_REFERENCIA"].astype(int).between(ano_ini, ano_fim)]

    chave = ["ANO_REFERENCIA", "COD_ITEM"]
    df_excel = _ordenar_duplicatas_por_quantidade(df_excel, "EXCEL_QTDE", chave)
    hunter = _ordenar_duplicatas_por_quantidade(hunter, "QUANTIDADE", chave)

    base = df_excel.merge(hunter, on=chave + ["_ORDEM"], how="outer").drop(columns="_ORDEM")
    base["EXCEL_QTDE"] = base["EXCEL_QTDE"].fillna(0.0)
    base["QUANTIDADE"] = base["QUANTIDADE"].fillna(0.0)
    base["EXCEL_DESCR_ITEM"] = base["EXCEL_DESCR_ITEM"].fillna("")

    base["DIF"] = (base["EXCEL_QTDE"] - base["QUANTIDADE"]).round(2)
    divergente = base["DIF"].abs() > _TOLERANCIA_DIVERGENCIA_ESTOQUE

    resumo = {
        "total_pares": len(base),
        "total_itens_unicos": int(base["COD_ITEM"].nunique()),
        "pares_divergentes": int(divergente.sum()),
        "itens_so_excel": int((base["QUANTIDADE"].eq(0) & base["EXCEL_QTDE"].ne(0)).sum()),
        "itens_so_hunter": int((base["EXCEL_QTDE"].eq(0) & base["QUANTIDADE"].ne(0)).sum()),
        "periodo": periodo,
    }

    divergentes = base.loc[divergente, [
        "COD_ITEM", "ANO_REFERENCIA", "EXCEL_DESCR_ITEM", "EXCEL_QTDE", "QUANTIDADE", "DIF",
    ]].copy().sort_values("DIF", key=lambda s: s.abs(), ascending=False)

    return {"resumo": resumo, "divergentes": divergentes, "erros": []}


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
