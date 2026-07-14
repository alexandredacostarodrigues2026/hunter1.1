"""Ponto de entrada Streamlit do Hunter 1.1.

Despacha pro Menu Principal (Estágio 6 — VAMOS ORGANIZAR, ver
docs/estagios/06_menu_navegacao.md) e os 3 grupos de painéis navegáveis
(Extração, Segregados, Painéis em Construção). Arquivo idêntico entre
operações — a operação ativa é resolvida em runtime por
loader.nome_operacao() (pasta-pai de ESSENCIAL/, ou HUNTER_OPERACAO_DIR).
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
    if "pagina_ativa" not in st.session_state:
        # None = Menu Principal (Estágio 6); "extracao"/"segregados"/
        # "construcao" = os 3 grupos de painéis navegáveis, ver
        # interface.render_menu_principal().
        st.session_state["pagina_ativa"] = None

    st.title("Hunter 1.1")
    st.subheader(f"Operação ativa: {loader.nome_operacao()}")

    pagina = st.session_state["pagina_ativa"]
    if pagina == "extracao":
        interface.render_pagina_extracao()
    elif pagina == "segregados":
        interface.render_pagina_segregados()
    elif pagina == "construcao":
        interface.render_pagina_construcao()
    else:
        interface.render_menu_principal()


if __name__ == "__main__":
    main()
