"""Ponto de entrada Streamlit do Hunter 1.1.

Despacha pro Menu Principal (Estágio 6 — VAMOS ORGANIZAR, ver
docs/estagios/06_menu_navegacao.md) e os 14 grupos de painéis navegáveis
(Extração, Matching (BC3), Segregados, Tabelas Entradas/Saídas/Estoques,
Auditoria1, Descrição Relevante, Cruzamento por Valor, Cruzamento por
Produto, RN1 — Movimentação Física, RN1 por Produto, Simulação RN1
(+30%), Seleção Consolidada (Estoque/XML — 7.3.3), Estágio 8 — Resumo de
Entradas/Saídas/Estoques, Produtos Alvos Salvos). Arquivo idêntico entre
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
        # None = Menu Principal (Estágio 6); "extracao"/"matching"/
        # "segregados"/"construcao"/"auditoria1"/"descricao_relevante"/
        # "cruzamento_valor"/"cruzamento_produto"/"rn1_fisica"/
        # "rn1_produto"/"rn1_simulada_30"/"consolidado_733"/"estagio_8"/
        # "produtos_alvo_salvos"/"estagio_9"/"consolidado_11"/
        # "relatorios" = os 17 grupos de painéis navegáveis, ver
        # interface.render_menu_principal(). "cruzamento_produtos"
        # (plural, 2026-08-19) NÃO é um 18º botão do menu — é uma
        # 2ª tela do Estágio 10, alcançada só pelo botão "🎯 Cruzar
        # Produto" de "produtos_alvo_salvos" (interface.render_pagina_
        # cruzamento_produtos()).
        st.session_state["pagina_ativa"] = None

    pagina = st.session_state["pagina_ativa"]
    if pagina is None:
        # Título/subtítulo só no Menu Principal (2026-08-16, pedido do
        # usuário — "deixar isso somente e procedimento inicial. ocupa
        # muito espaço"): antes apareciam ACIMA de toda página, inclusive
        # nas 17 sub-páginas navegáveis, empurrando o conteúdo real pra
        # baixo sem necessidade — o operador já sabe em qual operação
        # está depois da primeira tela.
        st.title("Hunter 1.1")
        st.subheader(f"Operação ativa: {loader.nome_operacao()}")

    # Botão "⬅️ Voltar ao Menu Principal" (`interface._botao_voltar_menu()`)
    # chamado UMA VEZ AQUI, depois de TODO o conteúdo da sub-página (2026-08-17,
    # pedido do usuário — "colocar sempre no final da página"): antes cada uma
    # das 17 render_pagina_X() chamava _botao_voltar_menu() como sua PRIMEIRA
    # linha (botão no TOPO) — mover a chamada pra dentro de cada função e
    # deixá-la como ÚLTIMA linha quebraria a navegação de volta em qualquer
    # `return` antecipado (ex.: "dados ainda não carregados, volte pra
    # Extração primeiro") — centralizar a chamada AQUI, fora do if/elif de
    # despacho, garante que o botão sempre aparece no final de QUALQUER
    # sub-página, com QUALQUER caminho de execução interno, sem precisar
    # tocar em cada uma das 17 funções nem duplicar a chamada em cada
    # `return` antecipado delas.
    if pagina == "extracao":
        interface.render_pagina_extracao()
    elif pagina == "matching":
        interface.render_pagina_matching()
    elif pagina == "segregados":
        interface.render_pagina_segregados()
    elif pagina == "construcao":
        interface.render_pagina_construcao()
    elif pagina == "auditoria1":
        interface.render_pagina_auditoria1()
    elif pagina == "descricao_relevante":
        interface.render_pagina_descricao_relevante()
    elif pagina == "cruzamento_valor":
        interface.render_pagina_cruzamento_valor()
    elif pagina == "cruzamento_produto":
        interface.render_pagina_cruzamento_produto()
    elif pagina == "rn1_fisica":
        interface.render_pagina_rn1_fisica()
    elif pagina == "rn1_produto":
        interface.render_pagina_rn1_produto()
    elif pagina == "rn1_simulada_30":
        interface.render_pagina_rn1_simulada_30()
    elif pagina == "consolidado_733":
        interface.render_pagina_consolidado_733()
    elif pagina == "estagio_8":
        interface.render_pagina_estagio_8()
    elif pagina == "produtos_alvo_salvos":
        interface.render_pagina_produtos_alvo_salvos()
    elif pagina == "cruzamento_produtos":
        interface.render_pagina_cruzamento_produtos()
    elif pagina == "estagio_9":
        interface.render_pagina_estagio_9()
    elif pagina == "consolidado_11":
        interface.render_pagina_consolidado_11()
    elif pagina == "relatorios":
        interface.render_pagina_relatorios()
    else:
        interface.render_menu_principal()

    if pagina is not None:
        interface._botao_voltar_menu()


if __name__ == "__main__":
    main()
