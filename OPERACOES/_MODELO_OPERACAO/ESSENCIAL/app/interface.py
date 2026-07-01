"""Componentes de interface (painéis, tabs, cards) do Equalizador de Produtos."""
import sys
import time
from pathlib import Path

_APP_DIR = Path(__file__).parent
if str(_APP_DIR) not in sys.path:
    sys.path.insert(0, str(_APP_DIR))

import streamlit as st

import loader

_STATUS_RENDER = {
    "salvo": lambda r: st.success(f"✅ {r['arquivo']} → {r['pasta']}/ ({r['mensagem']})"),
    "duplicado": lambda r: st.warning(f"⚠️ {r['arquivo']}: {r['mensagem']}"),
    "erro_esquema": lambda r: st.error(f"❌ {r['arquivo']}: {r['mensagem']}"),
    "cnpj_nao_identificado": lambda r: st.error(f"❌ {r['arquivo']}: {r['mensagem']}"),
    "erro": lambda r: st.error(f"❌ {r['arquivo']}: {r['mensagem']}"),
}

_TABELAS_BANCO = ["nfe_entradas", "nfe_saidas", "sped_itens", "sped_produtos", "sped_estoque"]
_DELAY_BANCO = 0.25  # segundos por tabela — garante visibilidade da barra mesmo em cargas rápidas


def render_entidade_auditada() -> None:
    """Mostra os dados da entidade auditada. Só é chamada por main.py quando
    st.session_state['dados_carregados'] é True (liberado pelo botão
    "Carregar dados" em render_carga_operacao) — sem botão próprio aqui."""
    st.subheader("Entidade auditada")
    with st.spinner("Identificando entidade auditada (CNPJ/Razão Social)..."):
        info = loader.garantir_entidade_auditada()

    if not info.get("cnpj"):
        st.warning("Entidade auditada não pôde ser identificada: " + "; ".join(info.get("erros", [])))
        return

    col1, col2 = st.columns(2)
    col1.metric("CNPJ", info["cnpj"])
    col2.metric("Ocorrências", f"{info['ocorrencias']:,}".replace(",", "."))
    st.markdown(f"**Razão Social:** {info['razao_social']}")

    fonte = info.get("por_fonte") or {}
    total = info.get("total_linhas_analisadas")
    if total:
        st.caption(
            f"Base: {total:,}".replace(",", ".")
            + f" itens de NF-e analisados (ET={fonte.get('ET', 0):,} | EP={fonte.get('EP', 0):,})".replace(",", ".")
        )
    if info.get("erros"):
        st.caption("Avisos: " + "; ".join(info["erros"]))


def _render_banco(barra, legenda) -> bool:
    """Persiste dados em DuckDB exibindo barra de progresso por tabela.
    Retorna True em sucesso, False em erro."""
    n_tabelas = len(_TABELAS_BANCO)
    idx = [0]

    def _cb(etapa: str, n: int) -> None:
        idx[0] += 1
        frac = idx[0] / n_tabelas
        barra.progress(frac, text=f"{etapa}: {n:,} registros".replace(",", "."))
        legenda.caption(
            f"Tabela {idx[0]}/{n_tabelas} — {etapa} ({n:,} registros)".replace(",", ".")
        )
        time.sleep(_DELAY_BANCO)

    res = loader.persistir_banco(callback=_cb)

    if "erro" in res:
        barra.empty()
        legenda.error(f"Erro ao atualizar banco: {res['erro']}")
        return False

    total = sum(v for k, v in res.items() if k != "erro")
    barra.progress(1.0, text=f"Banco atualizado — {total:,} registros no total".replace(",", "."))
    legenda.empty()
    return True


def render_carga_operacao() -> None:
    """Prévia + botão de carga: mostra quantos arquivos existem em ET/EP/SPED
    e quantos XML estão pendentes. O clique processa pendentes (progresso por
    arquivo) e persiste tudo em DuckDB (barra por tabela). Quando já carregado
    e sem pendentes, exibe "Carregar novamente" para atualização da base."""
    st.subheader("Carga de XML")

    with st.spinner("Verificando pastas..."):
        resumo = loader.pre_visualizar_carga()

    st.markdown(f"- **{resumo['et']['quantidade']}** arquivo(s) em `ET`: `{resumo['et']['caminho']}`")
    st.markdown(f"- **{resumo['ep']['quantidade']}** arquivo(s) em `EP`: `{resumo['ep']['caminho']}`")
    st.markdown(
        f"- **{resumo['declaracoes']['quantidade']}** arquivo(s) de declaração (SPED): "
        f"`{resumo['declaracoes']['caminho']}`"
    )

    pend = resumo["pendentes"]
    if pend["quantidade"] == 0:
        st.info("Nenhum XML pendente em 1-DOCFISCAIS/nf/ (fora de ET/EP).")
    else:
        st.markdown(
            f"- **{pend['quantidade']}** XML pendente(s) em `{pend['caminho']}` — previsão: "
            f"{pend['previsao_et']} para ET, {pend['previsao_ep']} para EP, "
            f"{pend['previsao_rejeitado']} não identificado(s)"
        )

    ja_carregado = st.session_state.get("dados_carregados", False)
    sem_pendentes = pend["quantidade"] == 0

    if ja_carregado and sem_pendentes:
        st.success("✅ Dados carregados.")
        clicou = st.button("Carregar novamente", key="btn_recarregar",
                           help="Reprocessa toda a base (ET/EP/.txt + SPED) e atualiza o banco de dados.")
    else:
        clicou = st.button("Carregar dados", key="btn_carregar_dados")

    if not clicou:
        return

    # ── Fase 1: classificação de XML pendentes ────────────────────────────────
    if pend["quantidade"] > 0:
        barra_xml = st.progress(0.0, text="Iniciando carga...")
        resultados_area = st.container()

        def _progresso(indice: int, total: int, resultado: dict) -> None:
            barra_xml.progress(indice / total, text=f"Processando {indice}/{total}: {resultado['arquivo']}")
            render = _STATUS_RENDER.get(resultado["status"])
            with resultados_area:
                if render:
                    render(resultado)
                else:
                    st.error(f"❌ {resultado['arquivo']}: status desconhecido ({resultado['status']}).")

        loader.carregar_operacao(progresso=_progresso)
        barra_xml.progress(1.0, text="XML concluído.")

    # ── Fase 2: persistência em DuckDB ────────────────────────────────────────
    st.markdown("**Atualizando banco de dados...**")
    barra_banco = st.progress(0.0, text="Preparando...")
    legenda_banco = st.empty()

    _render_banco(barra_banco, legenda_banco)

    st.session_state["dados_carregados"] = True
    st.rerun()
