"""Componentes de interface (painéis, tabs, cards) do Equalizador de Produtos."""
import sys
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


def render_entidade_auditada() -> None:
    """Painel de entidade auditada — nada é calculado/exibido até o usuário
    pedir explicitamente (consistente com a carga: sem dado "pronto" na tela
    sem uma ação do usuário confirmando)."""
    st.subheader("Entidade auditada")
    if not st.button("Consultar entidade auditada", key="btn_consultar_entidade"):
        return

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


def render_carga_operacao() -> None:
    """Prévia + confirmação manual: mostra quantos arquivos existem em cada
    pasta (ET/EP/declarações) e quantos XML estão pendentes (com previsão de
    classificação), e só processa depois que o usuário confirmar. Cargas podem
    ser grandes — o progresso é exibido arquivo a arquivo, não escondido."""
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
        return

    st.markdown(
        f"- **{pend['quantidade']}** XML pendente(s) em `{pend['caminho']}` — previsão: "
        f"{pend['previsao_et']} para ET, {pend['previsao_ep']} para EP, "
        f"{pend['previsao_rejeitado']} não identificado(s)"
    )

    if not st.button("Efetuar carga", key="btn_efetuar_carga"):
        return

    barra = st.progress(0.0, text="Iniciando carga...")
    resultados_area = st.container()

    def _progresso(indice: int, total: int, resultado: dict) -> None:
        barra.progress(indice / total, text=f"Processando {indice}/{total}: {resultado['arquivo']}")
        render = _STATUS_RENDER.get(resultado["status"])
        with resultados_area:
            if render:
                render(resultado)
            else:
                st.error(f"❌ {resultado['arquivo']}: status desconhecido ({resultado['status']}).")

    loader.carregar_operacao(progresso=_progresso)
    barra.progress(1.0, text="Concluído.")
