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


def main() -> None:
    st.title("Equalizador de Produtos")
    st.subheader(f"Operação ativa: {loader.nome_operacao()}")
    st.divider()
    if st.session_state.get("dados_carregados"):
        interface.render_entidade_auditada()
        st.divider()
    interface.render_carga_operacao()
    st.info("Demais módulos (carregamento completo, matching e equalização) ainda não implementados.")


if __name__ == "__main__":
    main()
