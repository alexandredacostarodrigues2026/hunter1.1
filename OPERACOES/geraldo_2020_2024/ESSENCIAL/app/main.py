"""Ponto de entrada Streamlit do Equalizador de Produtos (geraldo_2020_2024).

Esqueleto inicial — sem lógica de negócio ainda. Serve para validar que
iniciar_sistema.bat/.exe consegue subir o servidor e abrir o navegador.
"""
import sys
from pathlib import Path

_APP_DIR = Path(__file__).parent
if str(_APP_DIR) not in sys.path:
    sys.path.insert(0, str(_APP_DIR))

import streamlit as st

import interface
import loader

st.set_page_config(
    page_title="Equalizador de Produtos",
    page_icon="⚖️",
    layout="wide",
    initial_sidebar_state="collapsed",
    menu_items={"About": "Equalizador de Produtos v0.1.0 — GECOF/OPERAÇÕES"},
)


def _render_entidade_auditada() -> None:
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


def main() -> None:
    st.title("Equalizador de Produtos")
    _render_entidade_auditada()
    st.divider()
    interface.render_carga_operacao()
    st.info("Demais módulos (carregamento completo, matching e equalização) ainda não implementados.")


if __name__ == "__main__":
    main()
