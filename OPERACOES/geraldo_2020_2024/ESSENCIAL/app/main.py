"""Ponto de entrada Streamlit do Hunter 1.1 (geraldo_2020_2024).

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
    page_title="Hunter 1.1",
    page_icon="⚖️",
    layout="wide",
    initial_sidebar_state="collapsed",
    menu_items={"About": "Hunter 1.1 — GECOF/OPERAÇÕES"},
)


def main() -> None:
    if "dados_carregados" not in st.session_state:
        # Reabertura do front (nova sessão/navegador ou reinício do servidor):
        # verifica no DuckDB se já existe carga persistida, em vez de assumir
        # False e obrigar uma nova carga toda vez.
        st.session_state["dados_carregados"] = loader.dados_ja_carregados()

    st.title("Hunter 1.1")
    st.subheader(f"Operação ativa: {loader.nome_operacao()}")
    st.divider()
    interface.render_carga_operacao()
    st.info("Demais módulos (carregamento completo, equalização) ainda não implementados.")
    if st.session_state.get("dados_carregados"):
        st.divider()
        interface.render_entidade_auditada()
        st.divider()
        interface.render_entradas_terceiros()
        st.divider()
        interface.render_painel_analise()
        st.divider()
        interface.render_bc3()
        st.divider()
        interface.render_fluxos_fisicos()
        st.divider()
        interface.render_estoque_anual()


if __name__ == "__main__":
    main()
