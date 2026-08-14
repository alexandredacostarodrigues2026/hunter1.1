"""Componentes de interface (painéis, tabs, cards) do Hunter 1.1."""
import base64
import re
import sys
import time
from datetime import datetime
from pathlib import Path

_APP_DIR = Path(__file__).parent
if str(_APP_DIR) not in sys.path:
    sys.path.insert(0, str(_APP_DIR))

import pandas as pd
import streamlit as st

import loader

_STATUS_RENDER = {
    "salvo":                 lambda r: st.success(f"✅ {r['arquivo']} → {r['pasta']}/ ({r['mensagem']})"),
    "duplicado":             lambda r: st.warning(f"⚠️ {r['arquivo']}: {r['mensagem']}"),
    "erro_esquema":          lambda r: st.error(f"❌ {r['arquivo']}: {r['mensagem']}"),
    "cnpj_nao_identificado": lambda r: st.error(f"❌ {r['arquivo']}: {r['mensagem']}"),
    "erro":                  lambda r: st.error(f"❌ {r['arquivo']}: {r['mensagem']}"),
}

_DELAY = 0.25   # segundos por passo — garante visibilidade da barra mesmo em cargas rápidas


def render_configuracao_periodo() -> None:
    """Estágio 1 — trava inicial de escopo temporal da auditoria: define
    Ano Inicial/Final, persistido em `config_auditoria`
    (`loader.salvar_periodo_auditoria()`/`obter_periodo_auditoria()`). Uma
    vez confirmado, mostra um resumo fixo ("Período Gravado") em vez dos
    seletores, com botão "Alterar" pra reabrir a edição. Calcula e exibe
    quais pastas de XML/Declaração precisam existir pra garantir os
    cruzamentos de "virada de ano" dos Estágios 4/5 (`DATA_ELEITA`,
    continuidade Estoque Final/Inicial): XML cobre um ano a mais pra trás
    (a virada anterior ao início do período já precisa da base de
    comparação); Declarações cobre um ano a mais pra frente (o inventário
    de fechamento do último ano do período)."""
    periodo = loader.obter_periodo_auditoria()

    if periodo and not st.session_state.get("editando_periodo_auditoria"):
        col1, col2 = st.columns([6, 1])
        col1.markdown(
            f"📅 **Período de Auditoria:** {periodo['ano_inicial']} a {periodo['ano_final']}"
        )
        if col2.button("Alterar", key="btn_alterar_periodo_auditoria"):
            st.session_state["editando_periodo_auditoria"] = True
            st.rerun()
        return

    ano_atual = datetime.now().year
    anos_disponiveis = [str(a) for a in range(ano_atual - 8, ano_atual + 1)]

    st.markdown("**Configuração do Período de Auditoria**")
    col1, col2 = st.columns(2)
    idx_inicial = (
        anos_disponiveis.index(periodo["ano_inicial"])
        if periodo and periodo["ano_inicial"] in anos_disponiveis else 0
    )
    idx_final = (
        anos_disponiveis.index(periodo["ano_final"])
        if periodo and periodo["ano_final"] in anos_disponiveis else len(anos_disponiveis) - 1
    )
    ano_inicial = col1.selectbox("Ano Inicial", anos_disponiveis, index=idx_inicial, key="sel_ano_inicial_auditoria")
    ano_final = col2.selectbox("Ano Final", anos_disponiveis, index=idx_final, key="sel_ano_final_auditoria")

    periodo_valido = int(ano_inicial) <= int(ano_final)
    if not periodo_valido:
        st.warning("Ano Inicial não pode ser maior que Ano Final.")
    else:
        st.info(
            f"Base XML: pastas de **{int(ano_inicial) - 1}** até **{ano_final}**.  \n"
            f"Base Declarações (SPED): pastas de **{ano_inicial}** até **{int(ano_final) + 1}**."
        )

    if st.button("Confirmar Período", key="btn_confirmar_periodo_auditoria"):
        if not periodo_valido:
            st.error("Corrija o período antes de confirmar: Ano Inicial não pode ser maior que Ano Final.")
        else:
            loader.salvar_periodo_auditoria(ano_inicial, ano_final)
            st.session_state["editando_periodo_auditoria"] = False
            st.rerun()


def render_equipe_auditoria() -> None:
    """Estágio 1 — Equipe de Fiscalização: cadastro de até 4 auditores
    (nome + matrícula), persistido em `equipe_auditoria`
    (`loader.salvar_equipe_auditoria()`/`obter_equipe_auditoria()`).
    Alimenta automaticamente o rodapé de assinatura do Relatório Final
    (Estágio 12.1), eliminando a edição manual do PDF depois de gerado."""
    st.markdown("**Equipe de Fiscalização**")
    equipe = loader.obter_equipe_auditoria()
    df_edicao = pd.DataFrame({
        "Nome do Auditor": equipe["NOME_AUDITOR"].tolist(),
        "Matrícula": equipe["MATRICULA"].tolist(),
    })
    df_editado = st.data_editor(
        df_edicao,
        num_rows="fixed",
        hide_index=True,
        use_container_width=True,
        key="data_editor_equipe_auditoria",
    )

    if st.button("👥 Confirmar Equipe de Auditoria", key="btn_confirmar_equipe_auditoria"):
        df_salvar = pd.DataFrame({
            "NOME_AUDITOR": df_editado["Nome do Auditor"].tolist(),
            "MATRICULA": df_editado["Matrícula"].tolist(),
        })
        loader.salvar_equipe_auditoria(df_salvar)
        st.success("✅ Equipe de Auditoria gravada.")
        st.rerun()


def render_entidade_auditada() -> None:
    """Mostra os dados da entidade auditada. Só é chamada por main.py quando
    st.session_state['dados_carregados'] é True."""
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


def _barra_progresso(titulo: str, n_passos: int, fn_persistir, categorias: "dict | None" = None) -> bool:
    """Exibe título + barra de progresso agregada para uma fase de carga.
    fn_persistir(callback) deve chamar callback(etapa, n) a cada passo.
    Retorna True em sucesso, False em erro.

    `categorias` (2026-08-11, Solicitação Técnica "MONITORAMENTO DE CARGA
    E EQUIPE DE AUDITORIA" — "barra st.progress dedicada para cada lote
    de processamento"): dict opcional `{rótulo: [nomes_de_etapa]}` — uma
    barra EXTRA por categoria, além da agregada de sempre, avançando
    conforme as etapas daquela categoria completam. Categoria POR
    CATEGORIA (ET/EP/Declaração/Estoque — granularidade que já existe via
    o nome de cada tabela persistida, ver `render_carga_operacao()`), não
    por ANO — `persistir_nfe()`/`persistir_sped()` processam cada tabela
    inteira de uma vez (não em lotes por ano); quebrar de verdade por ano
    exigiria reescrever o parser interno, decisão explícita do usuário de
    não fazer isso agora (risco alto numa área crítica já validada). O
    detalhamento por ANO fica no painel de cobertura pós-carga (ver
    `_render_alerta_cobertura_granular()`/`loader.verificar_cobertura_
    granular()`). Uma etapa pode aparecer em mais de 1 categoria (ex.:
    `nfe_entradas`/`nfe_saidas` misturam ET+EP — contam pras duas)."""
    st.markdown(f"**{titulo}**")
    barra  = st.progress(0.0, text="Aguardando...")
    status = st.empty()
    idx    = [0]

    barras_categoria = {}
    contadores_categoria = {}
    if categorias:
        for rotulo, etapas in categorias.items():
            barras_categoria[rotulo] = st.progress(0.0, text=f"{rotulo}: 0/{len(etapas)}")
            contadores_categoria[rotulo] = 0

    def _cb(etapa: str, n: int) -> None:
        idx[0] += 1
        frac = idx[0] / n_passos
        barra.progress(frac, text=f"{etapa}: {n:,} registros".replace(",", "."))
        status.caption(f"Passo {idx[0]}/{n_passos} — {etapa} ({n:,} registros)".replace(",", "."))
        if categorias:
            for rotulo, etapas in categorias.items():
                if etapa in etapas:
                    contadores_categoria[rotulo] += 1
                    frac_cat = contadores_categoria[rotulo] / len(etapas)
                    barras_categoria[rotulo].progress(
                        frac_cat, text=f"{rotulo}: {contadores_categoria[rotulo]}/{len(etapas)}",
                    )
        time.sleep(_DELAY)

    res = fn_persistir(_cb)

    if "erro" in res:
        barra.empty()
        status.error(f"Erro: {res['erro']}")
        return False

    total = sum(v for k, v in res.items() if k != "erro")
    barra.progress(1.0, text=f"Concluído — {total:,} registros".replace(",", "."))
    status.empty()
    return True


def _render_alerta_cobertura_periodo() -> None:
    """Alerta de Carga (Estágio 1): confere se os dados persistidos cobrem
    os anos exigidos pelo Período de Auditoria já configurado (ver
    render_configuracao_periodo()/loader.verificar_cobertura_periodo()).
    Não bloqueia a carga — só avisa. Silencioso se nenhum período estiver
    configurado ainda (nada a checar)."""
    cobertura = loader.verificar_cobertura_periodo()
    if not cobertura.get("aplicavel"):
        return

    faltando_xml = cobertura["anos_xml_faltando"]
    faltando_sped = cobertura["anos_sped_faltando"]
    if not faltando_xml and not faltando_sped:
        st.caption(
            f"✅ Cobertura completa para o Período de Auditoria "
            f"({cobertura['ano_inicial']} a {cobertura['ano_final']})."
        )
        return

    partes = []
    if faltando_xml:
        partes.append(f"**XML**: {', '.join(str(a) for a in faltando_xml)}")
    if faltando_sped:
        partes.append(f"**Declarações (SPED)**: {', '.join(str(a) for a in faltando_sped)}")
    st.warning(
        f"⚠️ Alerta de Carga — faltam arquivos para o Período de Auditoria "
        f"({cobertura['ano_inicial']} a {cobertura['ano_final']}): " + " · ".join(partes)
    )


_ROTULOS_COBERTURA_GRANULAR = {
    "et": "ET (Emissão de Terceiros)",
    "ep": "EP (Emissão Própria)",
    "declaracao": "Declaração (C100/C170)",
    "estoque": "Estoque (H010)",
}
_MENSAGENS_FALTANTE_COBERTURA_GRANULAR = {
    "et": "ET (Emissão de Terceiros) de {anos} não localizado(a/os) na pasta ET.",
    "ep": "EP (Emissão Própria) de {anos} não localizado(a/os) na pasta EP.",
    "declaracao": "Declaração (C100/C170) de {anos} não localizada nas declarações (SPED).",
    "estoque": "Estoque (H010) de {anos} não localizado nas declarações (SPED).",
}


def _render_alerta_cobertura_granular() -> None:
    """Alerta de Carga GRANULAR (Estágio 1, 2026-08-11, Solicitação
    Técnica "MONITORAMENTO DE CARGA E EQUIPE DE AUDITORIA") — confere
    separadamente ET/EP/Declaração(C100/C170)/Estoque(H010) contra o
    Período de Auditoria (`loader.verificar_cobertura_granular()`).
    SUBSTITUI `_render_alerta_cobertura_periodo()` (mantida no código,
    só não é mais chamada por `render_carga_operacao()`) — o alerta
    agregado anterior só via "XML"/"SPED" como 2 blocos e não pegava,
    por exemplo, uma Declaração com C100/C170 mas SEM nenhum H010
    (Estoque) daquele ano — achado real ao testar contra o banco da
    geraldo (Declaração 2025 presente, Estoque 2025 ausente — o alerta
    antigo não via essa lacuna).

    Uma barra `st.progress` de "completude" (anos presentes/anos
    necessários, não uma barra de carregamento) por categoria, mais
    `st.warning` específico por ano faltando naquela categoria — mesma
    redação do exemplo da Solicitação Técnica ("⚠️ Atenção: Estoque de
    2022 não localizado nas declarações."). Silencioso se nenhum período
    estiver configurado ainda (nada a checar)."""
    cobertura = loader.verificar_cobertura_granular()
    if not cobertura.get("aplicavel"):
        return

    st.markdown("**Cobertura por Categoria**")
    algo_faltando = False
    for categoria, rotulo in _ROTULOS_COBERTURA_GRANULAR.items():
        bloco = cobertura[categoria]
        necessarios, faltando = bloco["necessarios"], bloco["faltando"]
        total = len(necessarios)
        presentes = total - len(faltando)
        frac = presentes / total if total else 1.0
        st.progress(frac, text=f"{rotulo}: {presentes}/{total} ano(s)")
        if faltando:
            algo_faltando = True
            anos_str = ", ".join(str(a) for a in faltando)
            st.warning("⚠️ Atenção: " + _MENSAGENS_FALTANTE_COBERTURA_GRANULAR[categoria].format(anos=anos_str))

    if not algo_faltando:
        st.caption(
            f"✅ Cobertura completa para o Período de Auditoria "
            f"({cobertura['ano_inicial']} a {cobertura['ano_final']})."
        )


def _lista_anos_pt(anos: list) -> str:
    """'2020, 2021 e 2022' — junta anos (já como string) com vírgula e um
    'e' antes do último, conforme Regra R07 (anos sempre como string, nunca
    formatados como número, pra não virar '2,020')."""
    if len(anos) == 1:
        return anos[0]
    return ", ".join(anos[:-1]) + " e " + anos[-1]


def _render_alerta_ancoragem_estoque() -> None:
    """Verificação de Âncoras de Estoque (Bloco H) — Estágio 1: por regra
    fiscal, o estoque final de um exercício (saldo em 31/12) é declarado no
    SPED de competência do início do exercício seguinte (geralmente
    jan/fev). Para o Estágio 5 (Tabela de Estoque) fechar sem lacunas, cada
    ano do Período de Auditoria precisa da declaração do ano seguinte como
    âncora de saldo. Checa direto nos arquivos brutos de 2-DECLARACAO/SPED
    (`loader.anos_declaracao_disponiveis()`), sem depender de carga já
    persistida — silencioso se o período ainda não foi configurado."""
    periodo = loader.obter_periodo_auditoria()
    if not periodo:
        return

    ano_ini = int(periodo["ano_inicial"])
    ano_fim = int(periodo["ano_final"])
    anos_estoque = [str(a) for a in range(ano_ini, ano_fim + 1)]
    anos_declaracao = [str(a + 1) for a in range(ano_ini, ano_fim + 1)]

    st.markdown("**Verificação de Âncoras de Estoque (Bloco H)**")
    st.info(
        f"Para auditar o período de {periodo['ano_inicial']} a {periodo['ano_final']}, "
        f"o sistema processará os estoques finais de {_lista_anos_pt(anos_estoque)}, "
        f"que são extraídos respectivamente das declarações de {_lista_anos_pt(anos_declaracao)}.  \n"
        f"Nota: o estoque final refere-se ao saldo em 31 de dezembro de cada exercício."
    )

    ano_ancora_final = str(ano_fim + 1)
    if ano_ancora_final not in loader.anos_declaracao_disponiveis():
        st.error(
            f"⚠️ Atenção: a declaração de {ano_ancora_final} não foi detectada. "
            f"O estoque final de {periodo['ano_final']} não poderá ser validado."
        )


def render_carga_operacao() -> None:
    """Prévia + botão de carga: 3 barras de progresso independentes + o
    Matching (BC3) automático no final.
      1. XML pendentes  — classificação arquivo a arquivo
      2. NF-e           — nfe_entradas + nfe_saidas + nfe_analise_et/ep + nfe_situacao_et/ep
                           + xml_entradas_real/xml_saidas_real no DuckDB
      3. SPED           — sped_itens + sped_produtos + sped_unidades + sped_estoque no DuckDB
      4. Matching (BC3) — loader.persistir_bc3(), 2026-08-15, Solicitação
                           Técnica "PAINEL 1 — PROCEDIMENTOS INICIAIS":
                           dispara automaticamente sempre que a carga (1ª
                           vez ou "Carregar novamente") termina com sucesso,
                           sem exigir navegação manual até "🧩 MATCHING
                           (BC3)". Erro no Matching não invalida a carga —
                           `dados_carregados` já foi marcado True antes; o
                           auditor pode gerar manualmente depois se precisar.
    Quando já carregado e sem pendentes, exibe "Carregar novamente" (KPIs de
    entradas/saídas reais ficam no painel dedicado, ver render_fluxos_fisicos()).
    Resultado (KPIs de match) exibido por render_pagina_extracao(), não
    aqui — ver _render_resultado_matching_inicial()."""
    st.subheader("Carga de XML")

    erro_bc3_automatico = st.session_state.pop("erro_bc3_automatico", None)
    if erro_bc3_automatico:
        st.error(
            f"Erro ao gerar o Matching (BC3) automaticamente após a carga: {erro_bc3_automatico} — "
            'os dados de NF-e/SPED foram carregados normalmente; gere o Matching manualmente em '
            '"🧩 MATCHING (BC3)" se precisar.'
        )

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

    _render_alerta_ancoragem_estoque()

    if ja_carregado and sem_pendentes:
        st.success("✅ Dados carregados.")
        _render_alerta_cobertura_granular()
        clicou = st.button(
            "Carregar novamente",
            key="btn_recarregar",
            help="Reprocessa toda a base (NF-e + SPED) e atualiza o banco de dados.",
        )
    else:
        clicou = st.button("Carregar dados", key="btn_carregar_dados")

    if not clicou:
        return

    # ── Barra 1: XML pendentes ────────────────────────────────────────────────
    if pend["quantidade"] > 0:
        st.markdown("**1. Classificação de XML**")
        barra_xml    = st.progress(0.0, text="Iniciando...")
        area_xml     = st.container()

        def _prog_xml(indice: int, total: int, resultado: dict) -> None:
            barra_xml.progress(indice / total, text=f"{indice}/{total}: {resultado['arquivo']}")
            render = _STATUS_RENDER.get(resultado["status"])
            with area_xml:
                if render:
                    render(resultado)
                else:
                    st.error(f"❌ {resultado['arquivo']}: status desconhecido ({resultado['status']}).")

        loader.carregar_operacao(progresso=_prog_xml)
        barra_xml.progress(1.0, text="XML concluído.")
        fase_nfe  = "**2. NF-e (base)**"
        fase_sped = "**3. SPED (declaração)**"
    else:
        fase_nfe  = "**1. NF-e (base)**"
        fase_sped = "**2. SPED (declaração)**"

    # ── Barra 2: NF-e ─────────────────────────────────────────────────────────
    # Categorias (2026-08-11) — ET/EP específicas: nfe_analise_*/nfe_situacao_*
    # (só existem numa origem, ver _classificar_itens_nfe()) e nfe_bc2 (só ET,
    # "Base Comparativa 2 — itens de Emissão de Terceiros"). nfe_entradas/
    # nfe_saidas/xml_entradas_real/xml_saidas_real MISTURAM ET+EP — contam
    # pras duas barras (não dá pra separar sem reprocessar por PASTA_ORIGEM,
    # fora de escopo aqui).
    categorias_nfe = {
        "ET": [
            "nfe_analise_et", "nfe_situacao_et", "nfe_bc2",
            "nfe_entradas", "nfe_saidas", "xml_entradas_real", "xml_saidas_real",
        ],
        "EP": [
            "nfe_analise_ep", "nfe_situacao_ep",
            "nfe_entradas", "nfe_saidas", "xml_entradas_real", "xml_saidas_real",
        ],
    }
    ok_nfe = _barra_progresso(fase_nfe, n_passos=9, fn_persistir=loader.persistir_nfe, categorias=categorias_nfe)

    # ── Barra 3: SPED ─────────────────────────────────────────────────────────
    # sped_produtos (0200)/sped_unidades (0190) são cadastros AUXILIARES da
    # Declaração (enriquecem os itens de C170) — contam como "Declaração",
    # não "Estoque". sped_estoque (H010) é exclusivo de "Estoque".
    categorias_sped = {
        "Declaração": ["sped_itens", "sped_produtos", "sped_unidades"],
        "Estoque": ["sped_estoque"],
    }
    ok_sped = _barra_progresso(fase_sped, n_passos=4, fn_persistir=loader.persistir_sped, categorias=categorias_sped)

    if ok_nfe and ok_sped:
        st.session_state["dados_carregados"] = True
        # ── Fase final: Matching (BC3) automático (2026-08-15, Solicitação
        # Técnica "PAINEL 1 — PROCEDIMENTOS INICIAIS") — antes só rodava via
        # botão manual em "🧩 MATCHING (BC3)"; agora dispara aqui, na MESMA
        # carga, pro auditor já ver a taxa de match sem precisar navegar pra
        # outra página. Sem barra granular própria (persistir_bc3() não
        # expõe progresso interno, só 1 callback no fim — mesmo padrão que
        # render_bc3() já usa: st.spinner cobrindo a chamada síncrona).
        fase_bc3 = "**4. Matching (BC2 x BC1)**" if pend["quantidade"] > 0 else "**3. Matching (BC2 x BC1)**"
        st.markdown(fase_bc3)
        with st.spinner("Executando o Matching (BC2 x BC1) — pode levar cerca de 1 minuto..."):
            resultado_bc3 = loader.persistir_bc3()
        if "erro" in resultado_bc3:
            st.session_state["erro_bc3_automatico"] = resultado_bc3["erro"]
        else:
            st.session_state["bc3_gerada"] = True
            st.session_state.pop("erro_bc3_automatico", None)
        st.rerun()


_COLUNAS_PREVIEW_ENTRADAS_TERCEIROS = [
    "COMPETENCIA", "ARQUIVO_ORIGEM", "CHV_NFE", "NUM_DOC", "DT_DOC",
    "DT_E_S", "DT_FIN",
    "COD_PART", "CNPJ", "NUM_ITEM", "COD_ITEM", "DESCR_ITEM", "COD_NCM",
    "COD_BARRA", "UNID", "DESCR_UNID", "QTD", "VL_ITEM",
]


def render_entradas_terceiros() -> None:
    """Botão dedicado (exibido só após a carga): gera e persiste as chaves de
    entrada de emissão de terceiros — C100 com IND_OPER=0 (entrada) e
    IND_EMIT=1 (emitido por terceiros), enriquecido com o cadastro de produto
    (0200), de unidade de medida (0190) e o CNPJ do emitente via cadastro de
    participantes (0150, ligado por COD_PART). Se já foram geradas antes
    (mesma lógica de dados_ja_carregados), mostra direto o resultado
    persistido — não reprocessa a cada reabertura do front."""
    st.subheader("Chaves de entrada de emissão de terceiros da declaração (base comparativa1)")
    st.caption(
        "C100 (IND_OPER=0 + IND_EMIT=1) + C170, enriquecido com 0200 (produto), "
        "0190 (unidade) e 0150 (CNPJ do emitente). Inclui DT_E_S (data de entrada/saída "
        "efetiva, Campo 11 do C100) e DT_FIN (data final do período de apuração, "
        "Campo 05 do Registro 0000) — base para auditoria de escrituração extemporânea."
    )

    if "entradas_terceiros_geradas" not in st.session_state:
        st.session_state["entradas_terceiros_geradas"] = loader.entradas_terceiros_ja_geradas()

    if st.session_state["entradas_terceiros_geradas"]:
        df_preview, total = loader.consultar_entradas_terceiros(limite=200)
        st.success(f"✅ {total:,} registro(s) em `sped_entradas_terceiros`.".replace(",", "."))
        st.markdown(f"Prévia limitada a 200 linhas de {total:,}".replace(",", "."))
        st.dataframe(_preparar_preview(df_preview, _COLUNAS_PREVIEW_ENTRADAS_TERCEIROS), use_container_width=True)

        # Exportação sob demanda, à parte da prévia — só busca a tabela
        # inteira quando pedido, para não pesar em bases com milhões de
        # linhas a cada redesenho da tela.
        preparar = st.button("Preparar exportação completa (CSV)", key="btn_preparar_export_entradas_terceiros")
        if preparar:
            with st.spinner("Preparando exportação completa..."):
                df_completo, total_completo = loader.consultar_entradas_terceiros(limite=None)
                csv_completo = df_completo.rename(columns=loader.carregar_dicionario_campos())
                st.session_state["entradas_terceiros_csv_bytes"] = csv_completo.to_csv(index=False, sep=";").encode("utf-8-sig")
                st.session_state["entradas_terceiros_csv_total"] = total_completo

        if "entradas_terceiros_csv_bytes" in st.session_state:
            st.download_button(
                f"Baixar tabela completa ({st.session_state['entradas_terceiros_csv_total']:,} linha(s), CSV)".replace(",", "."),
                data=st.session_state["entradas_terceiros_csv_bytes"],
                file_name="sped_entradas_terceiros.csv",
                mime="text/csv",
                key="btn_download_entradas_terceiros",
            )

        clicou = st.button(
            "Gerar novamente",
            key="btn_regerar_entradas_terceiros",
            help="Reprocessa e substitui a tabela sped_entradas_terceiros.",
        )
    else:
        clicou = st.button(
            "Gerar chaves de entrada de emissão de terceiros",
            key="btn_gerar_entradas_terceiros",
        )

    if not clicou:
        return

    with st.spinner("Gerando chaves de entrada de emissão de terceiros..."):
        df, meta = loader.gerar_entradas_terceiros()

    if meta.get("erros"):
        st.error("Erros: " + "; ".join(meta["erros"]))
        return
    if df.empty:
        st.warning("Nenhum registro C100/C170 com IND_OPER=0 e IND_EMIT=1 encontrado.")
        return

    st.session_state["entradas_terceiros_geradas"] = True
    st.rerun()


_COLUNAS_PREVIEW_ANALISE = [
    "PASTA_ORIGEM", "ARQUIVO_ORIGEM", "MOTIVO_SEGREGACAO",
    "fatonfe_infprot_chnfe", "fatoitemnfe_infnfe_det_nitem",
    "fatonfe_infnfe_ide_mod", "fatoitemnfe_infnfe_det_prod_cfop",
    "fatoitemnfe_infnfe_det_prod_xprod",
    "fatoitemnfe_infnfe_det_prod_qcom", "fatoitemnfe_infnfe_det_prod_vuncom",
    "fatoitemnfe_infnfe_det_prod_vprod", "ID_UNICO",
]
_COLUNAS_PREVIEW_SITUACAO = [
    "PASTA_ORIGEM", "ARQUIVO_ORIGEM",
    "fatonfe_infprot_chnfe", "fatoitemnfe_infnfe_det_nitem",
    "fatonfe_informix_stnfeletronica", "fatoitemnfe_infnfe_det_prod_xprod",
    "fatoitemnfe_infnfe_det_prod_vprod", "ID_UNICO",
]


def _preparar_preview(df: pd.DataFrame, colunas: list) -> pd.DataFrame:
    """Seleciona as colunas relevantes e as renomeia para os nomes amigáveis
    do DICIONARIO DE CAMPOS.txt antes de exibir."""
    cols = [c for c in colunas if c in df.columns]
    return df[cols].rename(columns=loader.carregar_dicionario_campos())


def _render_botao_cfops_segregados(colunas_preview: list) -> None:
    """Botão dedicado 'CFOPS SEGREGADOS' — exclusivo da seção "CFOPs Não
    Autorizados" do Painel de Monitoramento (render_painel_analise()).
    Mostra, unidos num só st.dataframe, os itens de nfe_analise_et +
    nfe_analise_ep (CFOP fora do cruzamento principal: entrega futura,
    venda à ordem, baixa de estoque, lançamento ECF — física ou simbólica,
    não compõe o estoque real). Diferente do expander "Visualizar
    registros" logo abaixo (que separa ET/EP em duas tabelas), aqui é uma
    tabela só, para varredura rápida pelo auditor. Regra Operacional R07:
    CHV_NFE/CFOP já vêm como string desde a persistência
    (loader._classificar_itens_nfe()) — concatenar as duas amostras não
    altera o dtype. Toggle via session_state — clique liga/desliga."""
    if "cfops_segregados_aberto" not in st.session_state:
        st.session_state["cfops_segregados_aberto"] = False
    if st.button("CFOPS SEGREGADOS", key="btn_cfops_segregados"):
        st.session_state["cfops_segregados_aberto"] = not st.session_state["cfops_segregados_aberto"]

    if not st.session_state["cfops_segregados_aberto"]:
        return

    df_et, _ = loader.consultar_chaves_analise("ET", categoria="cfop")
    df_ep, _ = loader.consultar_chaves_analise("EP", categoria="cfop")
    uniao = pd.concat([df_et, df_ep], ignore_index=True)
    if uniao.empty:
        st.info("Nenhum registro de CFOP segregado para esta operação.")
    else:
        st.dataframe(_preparar_preview(uniao, colunas_preview), use_container_width=True)


def _render_categoria_segregacao(
    titulo: str, categoria: str, total_et: int, total_ep: int,
    colunas_preview: list, msg_vazio: str, mostrar_botao_uniao: bool = False,
) -> None:
    """Bloco reutilizável: KPIs ET/EP + expander com prévia de uma das duas
    categorias de segregação (categoria='cfop' ou 'situacao').
    mostrar_botao_uniao=True (só para "CFOPs Não Autorizados") insere o
    botão 'CFOPS SEGREGADOS' logo abaixo dos KPIs, ver
    _render_botao_cfops_segregados()."""
    st.markdown(f"**{titulo}**")
    col1, col2 = st.columns(2)
    col1.metric(f"Qtd Itens ET ({titulo})", f"{total_et:,}".replace(",", "."))
    col2.metric(f"Qtd Itens EP ({titulo})", f"{total_ep:,}".replace(",", "."))

    if mostrar_botao_uniao:
        _render_botao_cfops_segregados(colunas_preview)

    with st.expander(f"Visualizar registros — {titulo}"):
        for fluxo, rotulo in (("ET", "Emissão de Terceiros (ET)"), ("EP", "Emissão Própria (EP)")):
            df, total = loader.consultar_chaves_analise(fluxo, categoria=categoria)
            st.markdown(f"**{rotulo}** — {total:,} registro(s)".replace(",", "."))
            if df.empty:
                st.info(f"{msg_vazio} em {fluxo}.")
            else:
                st.dataframe(_preparar_preview(df, colunas_preview), use_container_width=True)


def render_painel_analise() -> None:
    """Painel de Monitoramento de Registros Segregados — KPIs + botão de
    geração sob demanda + expanders com prévia para as duas categorias que a
    carga de NF-e desvia do fluxo principal (nfe_entradas/nfe_saidas), sem
    descartar nada:
      1. "CFOPs Não Autorizados" (rótulo de exibição; categoria interna
         'cfop', tabelas nfe_analise_et/nfe_analise_ep) — situação válida
         mas operação simbólica/de ajuste (entrega futura, venda à ordem,
         baixa de estoque, lançamento ECF) OU, exclusivo de ET, modelo 65
         (NFC-e vedada em entrada — ver MOTIVO_SEGREGACAO na prévia). Nome
         de exibição escolhido pelo usuário em 2026-07-14; tecnicamente os
         CFOPs em si são válidos — o que fica de fora do cruzamento é a
         NATUREZA simbólica/não física da operação (ou o modelo vedado),
         não uma irregularidade do CFOP.
      2. "Notas Não Autorizadas" (rótulo de exibição; categoria interna
         'situacao', tabelas nfe_situacao_et/nfe_situacao_ep) — mistura
         canceladas, denegadas e inutilizadas (fatonfe_informix_stnfeletronica
         fora de {"A","O"}) num único grupo de exibição.
    Exibido só após a carga geral (dados_carregados)."""
    st.subheader("Painel de Monitoramento — Registros Segregados")
    st.caption(
        "Itens desviados do cruzamento principal (Etapa 1), preservados aqui para consulta: "
        "CFOPs Não Autorizados (faturamento futuro, venda à ordem, baixa de estoque/ECF; "
        "em ET também Modelo 65 Vedado em Entrada) e "
        "Notas Não Autorizadas (canceladas, denegadas, inutilizadas)."
    )

    if "analise_cfop_gerada" not in st.session_state:
        st.session_state["analise_cfop_gerada"] = loader.analise_ja_gerada()

    if st.session_state["analise_cfop_gerada"]:
        totais = loader.consultar_totais_analise()
        st.success("✅ Dados de análise prontos.")

        _render_categoria_segregacao(
            "CFOPs Não Autorizados", "cfop",
            totais["nfe_analise_et"], totais["nfe_analise_ep"],
            _COLUNAS_PREVIEW_ANALISE, "Nenhum registro de CFOP não autorizado",
            mostrar_botao_uniao=True,
        )
        st.markdown("---")
        _render_categoria_segregacao(
            "Notas Não Autorizadas", "situacao",
            totais["nfe_situacao_et"], totais["nfe_situacao_ep"],
            _COLUNAS_PREVIEW_SITUACAO, "Nenhuma nota não autorizada",
        )

        clicou = st.button(
            "Regerar Análise",
            key="btn_regerar_analise_cfop",
            help="Reprocessa e substitui nfe_analise_et/ep e nfe_situacao_et/ep.",
        )
    else:
        clicou = st.button("Gerar Dados para Análise de CFOPs", key="btn_gerar_analise_cfop")

    if not clicou:
        return

    with st.spinner("Gerando dados de análise de CFOPs e situação..."):
        resultado = loader.gerar_dados_analise()

    if "erro" in resultado:
        st.error(f"Erro: {resultado['erro']}")
        return

    st.session_state["analise_cfop_gerada"] = True
    st.rerun()


_COLUNAS_PREVIEW_BC3 = [
    "fatonfe_infprot_chnfe", "fatoitemnfe_infnfe_det_nitem",
    # produto do fornecedor (XML, BC2) e produto da auditada (declaração,
    # BC1 — via bc3) lado a lado, para conferência direta pelo auditor.
    "fatoitemnfe_infnfe_det_prod_cprod", "fatoitemnfe_infnfe_det_prod_xprod",
    "COD_ITEM_DECLARACAO", "DESCR_ITEM_DECLARACAO",
    "fatoitemnfe_infnfe_det_prod_vprod", "fatoitemnfe_infnfe_det_prod_cean",
    "MATCH_TIPO", "MATCH_SCORE", "FATOR_MULTIPLICADOR_SUGERIDO",
    "DT_E_S", "DT_FIN", "ID_UNICO",
]


def render_bc3() -> None:
    """Painel do Matching (Etapa 1): cruza a BC2 (XML) com a BC1 (SPED) e
    mostra o resultado (BC3) — KPIs por tipo de match + botão de geração sob
    demanda + expander com prévia. A geração pode levar cerca de 1 minuto
    (similaridade de texto item a item), por isso fica atrás de um botão
    explícito em vez de rodar automaticamente na carga geral.
    A prévia expande a BC3 de volta pro dataset bruto de ET (`nfe_entradas`,
    via loader.consultar_nfe_entradas_bc3(), join por ID_UNICO), mostrando
    produto do fornecedor (XML) e produto da auditada (declaração) lado a
    lado; a exportação completa (CSV) continua servindo direto a tabela
    `bc3`.

    Desde 2026-07-14, a BC1 (`render_entradas_terceiros()`) vive dentro de
    um `st.expander` no topo deste painel, em vez de ter seção própria em
    render_pagina_construcao() — BC1 é a base de comparação oficial que o
    Matching usa pra "completar" as notas de entrada, então passou a ser
    subcomponente do processo de Matching, não algo independente."""
    with st.expander(
        "Chaves de entrada de emissão de terceiros da declaração (base comparativa 1)",
        expanded=True,
    ):
        render_entradas_terceiros()

    st.subheader("Matching (Etapa 1) — BC2 × BC1 = BC3")
    st.caption(
        "Cruza os itens de Emissão de Terceiros (BC2, XML) com a declaração (BC1, SPED) em duas "
        "famílias: Direto (D1-D6, sempre dentro da mesma CHV_NFE) e Aprendizado (A1-A5, dicionário "
        "histórico, não exige mesma CHV_NFE). "
        "D1 = mesmo GTIN/EAN + similaridade > 90%; "
        "D2 (fallback) = mesmo Valor Total + similaridade > 60% — sem depender de NUM_ITEM. "
        "A1 (aprendizado) = itens 'nd'/'nm' recuperados por histórico de CNPJ do emitente + "
        "código do produto (XML) + ano de emissão já confirmado em D1/D2. "
        "A2 (aprendizado por descrição) = igual ao A1, trocando o código do produto pela "
        "descrição exata do produto (XML). "
        "A3/A4 (aprendizado sem exigir o mesmo ano) = mesmos critérios do A1/A2 "
        "(código e descrição, respectivamente), mas sem exigir âncora confirmada no mesmo ano da "
        "nota — cobre fornecedor/código estável entre anos. "
        "A5 (aprendizado só por descrição) = igual ao A4, relaxando também o CNPJ do "
        "emitente — cobre a mesma descrição exata vinda de fornecedores diferentes. "
        "D3 (consolidação N-para-1) = vários itens 'nd'/'nm' do XML agrupados numa única linha "
        "'sortido'/consolidada do SPED, quando a soma dos valores do grupo bate exatamente com "
        "o valor da linha do SPED e a descrição do SPED está coberta (por token, ponderado por "
        "raridade) nos itens do grupo. "
        "D4 (integridade de nota) = itens 'nd'/'nm' restantes, recuperados só em notas onde a "
        "contagem de itens e o valor total batem entre XML e SPED, por similaridade > 70%. "
        "D5 (último recurso) = itens 'nd'/'nm' restantes, casados só por similaridade > 70% "
        "dentro da mesma CHV_NFE, sem exigir GTIN, valor ou integridade de nota. "
        "D6 (valor + desempate por texto) = itens 'nd'/'nm' restantes, casados dentro da mesma "
        "CHV_NFE por valor idêntico, sem exigir nota íntegra nem similaridade de texto — cobre "
        "descrição do SPED genérica ou errada. Valor empatado entre 2+ itens desempata por "
        "similaridade de descrição (ou confirma direto se for a mesma duplicata dos dois lados); "
        "só fica sem match se a similaridade também empatar."
    )

    if "bc3_gerada" not in st.session_state:
        st.session_state["bc3_gerada"] = loader.bc3_ja_gerada()

    if st.session_state["bc3_gerada"]:
        totais = loader.consultar_totais_bc3()
        total_itens = sum(totais.values())
        total_casados = (
            totais["D1"] + totais["D2"] + totais["A1"] + totais["A2"]
            + totais["A3"] + totais["A4"] + totais["A5"] + totais["D3"]
            + totais["D4"] + totais["D5"] + totais["D6"]
        )
        taxa_match = (total_casados / total_itens * 100) if total_itens else 0.0

        # Fonte reduzida + 2 linhas de 7 (2026-08-12, pedido do usuário) —
        # 14 KPIs numa linha só estouravam o rótulo ("Matches D1..." virava
        # "Matches...") mesmo com fonte menor; dividido em 2 linhas (Direto
        # D1/D2 + Aprendizado A1-A5 | Direto D3-D6 + ND/NM/Taxa) dá mais
        # largura por coluna. CSS escopado só a este container via
        # st.container(key=...), mesmo padrão já usado nas tabelas de alta
        # densidade do resto do app.
        st.markdown(
            "<style>"
            ".st-key-bc3_kpis [data-testid='stMetricValue'] { font-size: 1.1rem; }"
            ".st-key-bc3_kpis [data-testid='stMetricLabel'] { font-size: 0.75rem; }"
            "</style>",
            unsafe_allow_html=True,
        )
        with st.container(key="bc3_kpis"):
            col1, col2, col3, col4, col5, col6, col7 = st.columns(7)
            col1.metric("Matches D1", f"{totais['D1']:,}".replace(",", "."))
            col2.metric("Matches D2", f"{totais['D2']:,}".replace(",", "."))
            col3.metric("Matches A1", f"{totais['A1']:,}".replace(",", "."))
            col4.metric("Matches A2", f"{totais['A2']:,}".replace(",", "."))
            col5.metric("Matches A3", f"{totais['A3']:,}".replace(",", "."))
            col6.metric("Matches A4", f"{totais['A4']:,}".replace(",", "."))
            col7.metric("Matches A5", f"{totais['A5']:,}".replace(",", "."))

            col8, col9, col10, col11, col12, col13, col14 = st.columns(7)
            col8.metric("Matches D3", f"{totais['D3']:,}".replace(",", "."))
            col9.metric("Matches D4", f"{totais['D4']:,}".replace(",", "."))
            col10.metric("Matches D5", f"{totais['D5']:,}".replace(",", "."))
            col11.metric("Matches D6", f"{totais['D6']:,}".replace(",", "."))
            col12.metric("Não Declarado (nd)", f"{totais['ND']:,}".replace(",", "."))
            col13.metric("Sem Match (nm)", f"{totais['NM']:,}".replace(",", "."))
            col14.metric("Taxa de Match", f"{taxa_match:.1f}%".replace(".", ","))
        st.success("✅ Matching (BC3) pronto.")

        with st.expander("Visualizar resultado do Matching (BC3)"):
            df_bc3, total = loader.consultar_nfe_entradas_bc3(limite=200)
            st.markdown(
                f"**Amostra** — {total:,} registro(s) de ET no total, expandidos com o resultado "
                "do Matching (prévia limitada a 200 linhas; use o botão abaixo para exportar tudo)"
                .replace(",", ".")
            )
            if df_bc3.empty:
                if total_itens > 0:
                    st.warning(
                        "A BC3 tem registros, mas a prévia enriquecida veio vazia — "
                        "provavelmente `nfe_entradas` foi persistida com uma versão antiga "
                        "do schema (sem ID_UNICO). Use \"Carregar novamente\" na Carga de XML "
                        "para regravar `nfe_entradas` com o schema atual."
                    )
                else:
                    st.info("Nenhum registro de ET encontrado.")
            else:
                st.dataframe(_preparar_preview(df_bc3, _COLUNAS_PREVIEW_BC3), use_container_width=True)

            # A prévia acima é sempre limitada a 200 linhas (leve, rápida de
            # desenhar). A exportação é uma ação à parte, sob demanda, porque
            # ler a BC3 inteira pode ser pesado em bases com milhões de linhas
            # — só acontece quando o usuário pede, não a cada redesenho da tela.
            preparar = st.button("Preparar exportação completa (CSV)", key="btn_preparar_export_bc3")
            if preparar:
                with st.spinner("Preparando exportação completa..."):
                    df_completo, total_completo = loader.consultar_bc3(limite=None)
                    # VL_ITEM vem do XML (BC2) sempre com ponto decimal (ver
                    # matching.py) — normaliza pra vírgula (padrão BR) só na
                    # exportação, sem alterar o valor armazenado no banco.
                    df_completo["VL_ITEM"] = df_completo["VL_ITEM"].astype(str).str.replace(".", ",", regex=False)
                    csv_completo = df_completo.rename(columns=loader.carregar_dicionario_campos())
                    st.session_state["bc3_csv_bytes"] = csv_completo.to_csv(index=False, sep=";").encode("utf-8-sig")
                    st.session_state["bc3_csv_total"] = total_completo

            if "bc3_csv_bytes" in st.session_state:
                st.download_button(
                    f"Baixar BC3 completa ({st.session_state['bc3_csv_total']:,} linha(s), CSV)".replace(",", "."),
                    data=st.session_state["bc3_csv_bytes"],
                    file_name="bc3_matching.csv",
                    mime="text/csv",
                    key="btn_download_bc3",
                )

        clicou = st.button(
            "Regerar Matching (BC3)",
            key="btn_regerar_bc3",
            help="Reprocessa o cruzamento BC2 x BC1 (pode levar cerca de 1 minuto).",
        )
    else:
        clicou = st.button(
            "Gerar Matching (BC3)",
            key="btn_gerar_bc3",
            help="Executa o cruzamento BC2 x BC1 (pode levar cerca de 1 minuto).",
        )

    if not clicou:
        return

    with st.spinner("Executando o Matching (BC2 x BC1) — pode levar cerca de 1 minuto..."):
        resultado = loader.persistir_bc3()

    if "erro" in resultado:
        st.error(f"Erro: {resultado['erro']}")
        return

    st.session_state["bc3_gerada"] = True
    st.rerun()


_COLUNAS_PREVIEW_FLUXOS_REAIS = [
    "PASTA_ORIGEM", "ARQUIVO_ORIGEM", "fatonfe_infprot_chnfe",
    "fatonfe_infnfe_ide_tpnf",
    "fatonfe_infnfe_emit_cnpj", "fatonfe_infnfe_emit_xnome",
    "fatonfe_infnfe_dest_cnpj", "fatonfe_infnfe_dest_xnome",
    "fatoitemnfe_infnfe_det_nitem", "fatoitemnfe_infnfe_det_prod_xprod",
    "fatoitemnfe_infnfe_det_prod_vprod",
    # produto da auditada (declaração, BC1 — via bc3, Estágio 2) lado a lado
    # com o produto do fornecedor (XML) acima — só populado para entradas;
    # em xml_saidas_real fica sempre NULL (bc3 só cobre entradas de
    # terceiros, ver docs/estagios/03_fluxos_fisicos.md).
    "COD_ITEM_DECLARACAO", "FATOR_MULTIPLICADOR_SUGERIDO",
    "ID_UNICO",
]


def render_fluxos_fisicos() -> None:
    """Estágio 3 — Fluxos Físicos (Lado XML): KPIs + prévia sob demanda de
    xml_entradas_real/xml_saidas_real (loader._classificar_itens_nfe()) —
    movimentação física real da auditada, cruzando tpnf com o papel dela na
    nota (emitente ou destinatária), não só o tpnf isolado (ver
    "regra de negócios unificadas/CNPJ EMIT = CNPJ DEST.txt", raiz do
    projeto). Prévia enriquecida com COD_ITEM_DECLARACAO/
    FATOR_MULTIPLICADOR_SUGERIDO da bc3 (Estágio 2 — Matching, ver
    loader.consultar_fluxo_real()) — produto da auditada (declaração) lado a
    lado com o produto do fornecedor (XML), só populado em "Entradas"
    (bc3 não cobre saídas). Visualização exclusiva: só uma prévia (entradas
    OU saídas) fica visível por vez, controlada por
    st.session_state["fluxo_fisico_ativo"]."""
    st.subheader("Estágio 3 — Fluxos Físicos (Lado XML)")
    st.caption(
        "Reclassificação da movimentação física real da auditada: cruza o tpnf da nota com "
        "o papel dela na operação (emitente ou destinatária) — não só o tpnf isolado, que "
        "reflete a perspectiva de quem emite a NF-e. Roda sobre o mesmo universo de "
        "nfe_entradas/nfe_saidas (situação válida + CFOP fora da watchlist)."
    )

    totais = loader.consultar_totais_entradas_saidas_real()
    col1, col2 = st.columns(2)
    col1.metric("Entradas Reais (XML)", f"{totais['xml_entradas_real']:,}".replace(",", "."))
    col2.metric("Saídas Reais (XML)", f"{totais['xml_saidas_real']:,}".replace(",", "."))

    if not sum(totais.values()) and not loader.obter_entidade_auditada():
        st.info(
            "⚠️ Entradas/saídas reais dependem da entidade auditada (CNPJ) já fixada — "
            "veja a seção \"Entidade Auditada\"."
        )

    if "fluxo_fisico_ativo" not in st.session_state:
        st.session_state["fluxo_fisico_ativo"] = None

    col_btn1, col_btn2 = st.columns(2)
    if col_btn1.button("Visualizar Entradas", key="btn_ver_entradas_real"):
        st.session_state["fluxo_fisico_ativo"] = "entradas"
    if col_btn2.button("Visualizar Saídas", key="btn_ver_saidas_real"):
        st.session_state["fluxo_fisico_ativo"] = "saidas"

    ativo = st.session_state["fluxo_fisico_ativo"]
    if ativo is None:
        return

    rotulo = "Entradas Reais" if ativo == "entradas" else "Saídas Reais"
    df_preview, total = loader.consultar_fluxo_real(ativo, limite=200)
    st.markdown(f"**Prévia — {rotulo}** — {total:,} registro(s) no total (limitada a 200 linhas)".replace(",", "."))
    if df_preview.empty:
        st.info(f"Nenhum registro em xml_{ativo}_real.")
    else:
        st.dataframe(_preparar_preview(df_preview, _COLUNAS_PREVIEW_FLUXOS_REAIS), use_container_width=True)


_COLUNAS_PREVIEW_ESTOQUE_ENTRADAS_SAIDAS = [
    "PASTA_ORIGEM", "ARQUIVO_ORIGEM", "fatonfe_infprot_chnfe",
    "fatonfe_infnfe_ide_tpnf",
    "fatonfe_infnfe_emit_cnpj", "fatonfe_infnfe_emit_xnome",
    "fatonfe_infnfe_dest_cnpj", "fatonfe_infnfe_dest_xnome",
    "fatoitemnfe_infnfe_det_nitem", "fatoitemnfe_infnfe_det_prod_xprod",
    "fatoitemnfe_infnfe_det_prod_vprod",
    "COD_ITEM_DECLARACAO", "DESCR_ITEM_DECLARACAO", "FATOR_MULTIPLICADOR_SUGERIDO",
    "DATA_ORIGINAL", "ANO_ORIGINAL", "DATA_ELEITA", "ANO_ELEITO", "DATA_ELEITA_ORIGEM",
    "ID_UNICO",
]


def render_estoque_entradas_saidas() -> None:
    """Estágio 4 — Entradas e Saídas Enriquecidas: primeiro painel deste
    estágio na UI (2026-07-14) — antes só existia o backend
    (loader.persistir_estoque_entradas_saidas() nunca era chamada de lugar
    nenhum da interface). Persiste `estoque_entradas`/`estoque_saidas`:
    xml_entradas_real/xml_saidas_real (Estágio 3) enriquecidos com
    COD_ITEM_DECLARACAO/DESCR_ITEM_DECLARACAO/FATOR_MULTIPLICADOR_SUGERIDO
    da bc3 (Estágio 2), DATA_ELEITA/ANO_ELEITO/DATA_ELEITA_ORIGEM
    (hierarquia de datas + rótulo simplificado 'declaração'/'xml' da fonte
    vencedora — 2026-07-15) e DATA_ORIGINAL/ANO_ORIGINAL (dhEmi cru do
    XML, campo de auditoria paralelo à hierarquia — 2026-07-15, ver
    docs/estagios/04_cronologia_ano_eleito.md). Botão Gerar/Regerar (mesmo
    padrão de render_estoque_anual()) + toggle Entradas/Saídas (mesmo
    padrão de render_fluxos_fisicos()) — mas aqui o resultado fica
    persistido, diferente da prévia sob demanda do Estágio 3.

    Expander "📋 Regras de eleição da Data" (2026-08-07, pedido do
    usuário: "no estágio 4, traga as regras das datas") — mostra a
    tabela de hierarquia (4 prioridades × Cenário A/ET, Cenário B/EP)
    direto na tela, pra não depender de ler docs/estagios/
    04_cronologia_ano_eleito.md pra entender por que uma DATA_ELEITA
    específica venceu. Conteúdo transcrito da mesma doc (regra
    confirmada com o usuário em 2026-07-15, não mudou desde então)."""
    st.subheader("Estágio 4 — Entradas e Saídas Enriquecidas (BC3 + Cronologia)")
    st.caption(
        "Persiste xml_entradas_real/xml_saidas_real (Estágio 3) enriquecidos com o código "
        "interno da auditada e o fator de multiplicação sugerido (bc3, Estágio 2), mais a "
        "data/ano oficial de cada item e a origem simplificada dela (DATA_ELEITA/ANO_ELEITO/"
        "DATA_ELEITA_ORIGEM: 'declaração' ou 'xml') e a data/ano de emissão original do XML "
        "(DATA_ORIGINAL/ANO_ORIGINAL), para medir a defasagem entre emissão e escrituração. "
        "Diferente da prévia do Estágio 3 (calculada a cada consulta), aqui o resultado é "
        "gravado em estoque_entradas/estoque_saidas."
    )
    with st.expander("📋 Regras de eleição da Data (hierarquia de prioridade)"):
        st.markdown(
            "Pra cada item, `DATA_ELEITA`/`ANO_ELEITO` usam a PRIMEIRA data válida "
            "(nesta ordem de prioridade), conforme o papel da auditada na nota "
            "(`AUDITADA_PAPEL`, Estágio 3):\n\n"
            "| Prioridade | Cenário A — Destinatária (ET) | Cenário B — Emitente (EP) |\n"
            "|---|---|---|\n"
            "| 1ª | `DT_E_S` (declaração — C100, via BC3) | `dhSaiEnt` (XML) |\n"
            "| 2ª | `DT_FIN` (declaração — Registro 0000, via BC3) | `DT_E_S` (declaração — C100, via BC3) |\n"
            "| 3ª | `dhSaiEnt` (XML) | `DT_FIN` (declaração — Registro 0000, via BC3) |\n"
            "| 4ª | `dhEmi` (XML) | `dhEmi` (XML) |\n\n"
            "`DATA_ELEITA_ORIGEM` guarda um rótulo simplificado de qual fonte venceu: "
            "**'declaração'** (`DT_E_S`/`DT_FIN`, veio do SPED) ou **'xml'** "
            "(`dhSaiEnt`/`dhEmi`, veio do documento fiscal).\n\n"
            "`DATA_ORIGINAL`/`ANO_ORIGINAL` é um campo PARALELO, sempre `dhEmi` (emissão do "
            "XML) em qualquer cenário, sem passar pela hierarquia — não substitui "
            "`DATA_ELEITA`, serve pra medir a defasagem entre emissão e escrituração real.\n\n"
            "*Limitação real conhecida*: a extração de XML deste projeto não inclui o campo "
            "`dhSaiEnt` — na prática, a 3ª prioridade do Cenário A e a 1ª do Cenário B nunca "
            "contribuem; no Cenário B, como também não existe declaração de emissão própria "
            "(BC3 só cobre entradas de terceiros), `DATA_ELEITA` cai sempre na 4ª prioridade "
            "(`dhEmi`, XML) — confirmado na base real: praticamente 100% de "
            "`estoque_saidas` usa a data do XML."
        )

    if "estoque_entradas_saidas_gerado" not in st.session_state:
        st.session_state["estoque_entradas_saidas_gerado"] = loader.estoque_entradas_saidas_ja_gerado()

    if st.session_state["estoque_entradas_saidas_gerado"]:
        totais = loader.consultar_totais_estoque_entradas_saidas()
        col1, col2 = st.columns(2)
        col1.metric("Entradas Enriquecidas", f"{totais['estoque_entradas']:,}".replace(",", "."))
        col2.metric("Saídas Enriquecidas", f"{totais['estoque_saidas']:,}".replace(",", "."))
        st.success("✅ Entradas/Saídas enriquecidas prontas.")

        if "estoque_entradas_saidas_ativo" not in st.session_state:
            st.session_state["estoque_entradas_saidas_ativo"] = None

        col_btn1, col_btn2 = st.columns(2)
        if col_btn1.button("Visualizar Entradas", key="btn_ver_estoque_entradas"):
            st.session_state["estoque_entradas_saidas_ativo"] = "entradas"
        if col_btn2.button("Visualizar Saídas", key="btn_ver_estoque_saidas"):
            st.session_state["estoque_entradas_saidas_ativo"] = "saidas"

        ativo = st.session_state["estoque_entradas_saidas_ativo"]
        if ativo is not None:
            rotulo = "Entradas Enriquecidas" if ativo == "entradas" else "Saídas Enriquecidas"
            df_preview, total = loader.consultar_estoque_entradas_saidas(ativo, limite=200)
            st.markdown(
                f"**Prévia — {rotulo}** — {total:,} registro(s) no total (limitada a 200 linhas)"
                .replace(",", ".")
            )
            if df_preview.empty:
                st.info(f"Nenhum registro em estoque_{ativo}.")
            else:
                st.dataframe(
                    _preparar_preview(df_preview, _COLUNAS_PREVIEW_ESTOQUE_ENTRADAS_SAIDAS),
                    use_container_width=True,
                )

        clicou = st.button(
            "Regerar Entradas/Saídas Enriquecidas",
            key="btn_regerar_estoque_entradas_saidas",
            help="Reprocessa xml_entradas_real/xml_saidas_real + bc3 e atualiza "
                 "estoque_entradas/estoque_saidas.",
        )
    else:
        clicou = st.button(
            "Gerar Entradas/Saídas Enriquecidas", key="btn_gerar_estoque_entradas_saidas"
        )

    if not clicou:
        return

    with st.spinner("Enriquecendo entradas e saídas com dados da bc3..."):
        resultado = loader.persistir_estoque_entradas_saidas()

    if "erro" in resultado:
        st.error(f"Erro: {resultado['erro']}")
        return

    st.session_state["estoque_entradas_saidas_gerado"] = True
    st.rerun()


_COLUNAS_PREVIEW_ESTOQUE_ANUAL = [
    "ANO_REFERENCIA", "COD_ITEM_DECLARACAO", "DESCR_ITEM_DECLARACAO",
    "UNIDADE", "QUANTIDADE_INICIAL", "QUANTIDADE_FINAL",
]


def render_estoque_anual() -> None:
    """Estágio 5 — Tabela de Estoque: consolida o inventário já declarado no
    SPED (Bloco H — H005+H010, ver loader.montar_estoque_anual_consolidado())
    por item x ano, aplicando a regra de continuidade cronológica (Estoque
    Final de 31/12 do ano N-1 vira Estoque Inicial de 01/01 do ano N — mesma
    linha física). Sem cálculo de entradas/saídas nem divergências nesta
    etapa (foco exclusivo em consolidação)."""
    st.subheader("Estágio 5 — Tabela de Estoque")
    st.caption(
        "Consolida o inventário já declarado no SPED (Bloco H — H005+H010) por item e por ano, "
        "aplicando a regra de continuidade: o Estoque Final de 31/12 do ano anterior vira o "
        "Estoque Inicial de 01/01 do ano seguinte — o mesmo inventário físico, visto dos dois "
        "lados da virada do ano. Não calcula entradas, saídas nem divergências — só consolida "
        "o que já foi declarado."
    )

    if "estoque_anual_gerado" not in st.session_state:
        st.session_state["estoque_anual_gerado"] = loader.estoque_anual_ja_gerado()

    if st.session_state["estoque_anual_gerado"]:
        df_preview, total = loader.consultar_estoque_anual_consolidado(limite=200)
        st.success(f"✅ {total:,} registro(s) em `estoque_anual_consolidado`.".replace(",", "."))
        st.markdown(f"Prévia limitada a 200 linhas de {total:,}".replace(",", "."))
        if df_preview.empty:
            st.info("Nenhum registro na tabela de estoque.")
        else:
            st.dataframe(_preparar_preview(df_preview, _COLUNAS_PREVIEW_ESTOQUE_ANUAL), use_container_width=True)

        clicou = st.button(
            "Regerar Tabela de Estoque",
            key="btn_regerar_estoque_anual",
            help="Reprocessa o Bloco H (H005+H010) e atualiza a tabela.",
        )
    else:
        clicou = st.button("Gerar Tabela de Estoque", key="btn_gerar_estoque_anual")

    if not clicou:
        return

    with st.spinner("Consolidando a tabela de estoque..."):
        resultado = loader.persistir_estoque_anual_consolidado()

    if "erro" in resultado:
        st.error(f"Erro: {resultado['erro']}")
        return

    st.session_state["estoque_anual_gerado"] = True
    st.rerun()


_COLUNAS_PREVIEW_PRODUTO_ALVO = ["COD_ITEM", "DESCR_ALVO", "UNID_ALVO"]


def render_descricao_relevante() -> None:
    """Estágio 7.1 — Fixação da Descrição Relevante (2026-07-18,
    Solicitação Técnica; primeiro sub-passo do Estágio 7 — Escolha do
    Produto Alvo): unifica COD_ITEM_DECLARACAO/DESCR_ITEM_DECLARACAO de
    "entradas, saidas e estoque" (nomes reais no DuckDB, sem mudança:
    estoque_entradas, estoque_saidas — Estágio 4; estoque_anual_
    consolidado — Estágio 5) e elege, por código, a descrição mais
    frequente (moda) — ver loader.montar_produto_alvo(). Serve de nome
    "oficial" pra padronizar relatórios e apoiar a seleção de produtos
    pra auditoria física. Mesmo padrão de botão "Gerar/Regerar" + prévia
    de render_estoque_anual().

    Unidade Relevante (`UNID_ALVO`, 2026-08-03, Solicitação Técnica —
    "Enriquecimento da Identidade do Produto"): moda da unidade de
    medida, calculada de forma INDEPENDENTE da moda de descrição (mesmo
    rigor, contagem própria — não altera em nada a DESCR_ALVO já
    validada). Serve de "unidade de destino" pro Fator Multiplicador
    (Estágios 9/10) e evita somar quantidades em unidades diferentes
    sem alerta na RN1."""
    st.subheader("Estágio 7.1 — Fixação da Descrição Relevante")
    st.caption(
        "Elege, por COD_ITEM, a descrição E a unidade de medida estatisticamente mais frequentes "
        "(moda, calculadas de forma independente uma da outra) entre entradas, saídas e estoque — "
        "um mesmo produto pode aparecer com grafias/unidades levemente diferentes entre essas 3 "
        "fontes. Ignora códigos nulos ou sentinela ('nd'/'nm', gravados quando o Matching não achou "
        "correspondência); empate na contagem é desempatado em ordem alfabética (A-Z)."
    )

    if "produto_alvo_gerado" not in st.session_state:
        st.session_state["produto_alvo_gerado"] = loader.produto_alvo_ja_gerado()

    if st.session_state["produto_alvo_gerado"]:
        df_preview, total = loader.consultar_produto_alvo(limite=200)
        st.success(f"✅ {total:,} produto(s) único(s) em `produto_alvo`.".replace(",", "."))
        st.markdown(f"Prévia limitada a 200 linhas de {total:,}".replace(",", "."))
        if df_preview.empty:
            st.info("Nenhum produto elegível encontrado — gere entradas/saídas/estoque primeiro, "
                    "em \"TABELAS ENTRADAS / SAÍDAS / ESTOQUES\".")
        else:
            st.dataframe(_preparar_preview(df_preview, _COLUNAS_PREVIEW_PRODUTO_ALVO), use_container_width=True)

        clicou = st.button(
            "Regerar Descrições Relevantes",
            key="btn_regerar_produto_alvo",
            help="Reprocessa entradas/saídas/estoque e recalcula a descrição mais frequente por "
                 "código.",
        )
    else:
        clicou = st.button("Gerar/Regerar Descrições Relevantes", key="btn_gerar_produto_alvo")

    if not clicou:
        return

    with st.spinner("Elegendo a descrição mais frequente por produto..."):
        resultado = loader.persistir_produto_alvo()

    if "erro" in resultado:
        st.error(f"Erro: {resultado['erro']}")
        return

    st.session_state["produto_alvo_gerado"] = True
    st.rerun()


_COLUNAS_PREVIEW_CRUZAMENTO_VALOR = [
    "ANO", "DESCR_ALVO", "EI", "COMPRAS", "TOTAL_DEBITO", "VENDAS", "EF", "TOTAL_CREDITO",
    "DIVERGENCIA", "INFRACAO", "PCT_DIVERGENCIA",
]
_COLUNAS_MONETARIAS_CRUZAMENTO_VALOR = (
    "EI", "COMPRAS", "TOTAL_DEBITO", "VENDAS", "EF", "TOTAL_CREDITO", "DIVERGENCIA",
)
_TRANS_MILHAR_BR = str.maketrans({",": ".", ".": ","})


def _formatar_moeda_br(v: float) -> str:
    """Formata valor monetário como "1.234,56" (padrão BR: milhar '.',
    decimal ',') — column_config.NumberColumn só formata no padrão
    sprintf-js/en-US (milhar ',', decimal '.'), sem opção de trocar pro
    padrão BR, por isso as colunas monetárias do painel 7.2 viram texto
    pré-formatado antes do st.dataframe (2026-07-19, refinamento de UX)."""
    return f"{v:,.2f}".translate(_TRANS_MILHAR_BR)


def _padrao_busca_curinga(texto: str) -> str:
    """Converte um termo de "Buscar por Descrição" em regex segura pro
    `.str.contains()` do pandas. Origem (2026-08-12, achado real):
    usuário digitou "*bol*jutucut*" esperando curinga estilo Qlik/SQL
    LIKE — o texto ia direto pro `.str.contains(regex=True)` por padrão,
    e "*" sozinho não é regex válida, estourava `pyarrow.lib.
    ArrowInvalid: no argument for repetition operator`.

    Refinado 2026-08-14 (Solicitação Técnica — âncoras + interseção),
    confirmado com o usuário via AskUserQuestion. Regras, em ordem:

    1. **Sem nenhum "*"**: mantém o comportamento original — substring
       simples ("contém"), sem âncora nenhuma. Decisão explícita do
       usuário: aplicar ^/$ sempre (mesmo sem "*") quebraria toda busca
       de uma palavra solta já em uso nas 7 telas que chamam esta função
       — "mac" continua achando qualquer descrição que CONTENHA "mac".
    2. **Âncora de início**: se o texto NÃO começa com "*", prefixa "^"
       — só casa quem COMEÇA com o 1º fragmento (ex.: "mac*" → "^mac.*",
       exclui "ENGRAXATE PARA CERVEJA" de uma busca por "CERVEJA*"... — 1º
       fragmento "*" à direita ainda deixa livre o que vem depois).
    3. **Âncora de fim**: se o texto NÃO termina com "*", sufixa "$" — só
       casa quem TERMINA com o último fragmento (ex.: "*mac" → ".*mac$").
    4. **Contém global**: lado que TEM "*" na borda vira ".*" solto (sem
       âncora) naquele lado (ex.: "*mac*" → ".*mac.*", igual à busca
       antiga).
    5. **Interseção (qualquer ordem)**: só quando o texto COMEÇA com "*"
       E tem mais de um fragmento não-vazio — em vez de exigir a ordem
       linear dos fragmentos (ex.: "mor.*mac" exige "mor" antes de
       "mac"), monta um Positive Lookahead por fragmento, validando a
       presença de todos em qualquer posição/ordem (ex.: "*mor*mac*" →
       "^(?=.*mor)(?=.*mac).*$" — acha "PICOLE DE MORANGO" e "MORANGO
       PICOLE" com o mesmo termo de busca). Fragmentos vazios (bordas ou
       "**" consecutivo) são ignorados, nunca geram lookahead vazio.
       Texto começando com "*" mas com só 1 fragmento cai na regra 4
       (contém global simples), não na interseção — não há "ordem" pra
       ignorar com um termo só.

    Todo fragmento é escapado com `re.escape()` antes de entrar na
    regex — parênteses/colchetes/pontos em descrições de produto
    buscados não quebram a regex nem casam sem querer."""
    if "*" not in texto:
        return re.escape(texto)

    comeca_asterisco = texto.startswith("*")
    termina_asterisco = texto.endswith("*")
    fragmentos = [parte for parte in texto.split("*") if parte]

    if not fragmentos:
        return ".*"

    if comeca_asterisco and len(fragmentos) > 1:
        lookaheads = "".join(f"(?=.*{re.escape(fragmento)})" for fragmento in fragmentos)
        return f"^{lookaheads}.*$"

    meio = ".*".join(re.escape(fragmento) for fragmento in fragmentos)
    prefixo = ".*" if comeca_asterisco else "^"
    sufixo = ".*" if termina_asterisco else "$"
    return f"{prefixo}{meio}{sufixo}"


def _badge_st(escolhido: dict) -> str:
    """Rótulo curto "ST" (Substituição Tributária) pra anexar onde o
    produto alvo é identificado no Estágio 10 — Solicitação Técnica
    (2026-07-29): "ESSA INFORMAÇÃO 'ST' DEVERÁ ACOMPANHAR O PRODUTO
    ALVO NO DECORRER DE TODOS OS PROCEDIMENTOS DA APLICAÇÃO. SEMPRE QUE
    REQUISITADO" — lê `escolhido["IS_ST"]` (já enriquecido ao vivo por
    loader.consultar_produto_cruzamento_escolhido(), a partir de
    produto_alvo_fiscalizacao). String vazia se não for ST, pra usar
    direto em f-string/concatenação sem `if` repetido em cada tela."""
    return " 🏷️ **ST**" if escolhido.get("IS_ST") else ""


def _formatar_pct_br(v: float) -> str:
    """% Diverg do painel 7.2: acima de 1000% vira '>1000%' — evita número
    gigante na tela quando o denominador é ~0 (ver gerar_cruzamento_
    valor(), caso de omissão total onde um lado da equação é zero); a
    ordenação por Divergência (não por % Diverg) preserva esses casos no
    topo mesmo com o valor "achatado" na exibição. Abaixo de 1000%,
    formata com vírgula decimal (padrão BR, 2026-07-19). `NaN` também
    vira '>1000%' (2026-07-19, correção): tabelas `cruzamento_valor`
    persistidas ANTES da correção do denominador em gerar_cruzamento_
    valor() ainda guardam `NaN` de verdade — sem este caso, `f"{nan:.2f}
    %"` vira literalmente a string "nan%" na tela (Python formata NaN
    como "nan", não dá erro). Regerar a tabela ("Regerar Cruzamento por
    Valor" na UI) elimina o NaN armazenado; este tratamento cobre a
    exibição enquanto isso não acontece."""
    if pd.isna(v) or abs(v) > 1000:
        return ">1000%"
    return f"{v:.2f}%".replace(".", ",")


def render_cruzamento_valor() -> None:
    """Estágio 7.2 — Cruzamento por Valor (2026-07-18, Solicitação
    Técnica; indicadores de risco adicionados em 2026-07-19): aplica
    EI+Compras=Vendas+EF por (ANO, COD_ITEM), em R$ — ver loader.
    gerar_cruzamento_valor(). Identidade pela DESCR_ALVO do Estágio 7.1
    (produto_alvo); exige essa tabela já gerada. Mesmo padrão
    "Gerar/Regerar" + prévia de render_descricao_relevante(), com filtros
    de Ano (multiselect) e busca textual por Descrição — aplicados só na
    exibição (client-side sobre a prévia carregada), não refazem o
    cálculo. Prévia já vem ordenada por Divergência decrescente (feito no
    loader) — os filtros preservam essa ordem. Tabela em formato "alta
    densidade" (2026-07-19, refinamento de UX): sem coluna de índice,
    fonte reduzida (CSS escopado só a esta tabela via st.container(key=
    ...)), colunas monetárias formatadas em padrão BR ("1.234,56" — ver
    _formatar_moeda_br()) e % Diverg capado em ">1000%" com vírgula
    decimal (ver _formatar_pct_br())."""
    st.subheader("Estágio 7.2 — Cruzamento por Valor")
    st.caption(
        "Aplica EI + Compras = Vendas + EF por (Ano, Produto), em R$ — Compras (entradas) e "
        "Estoque pela visão declarada/vinculada da auditada, Vendas (saídas) pela visão física "
        "do XML. Identidade pela Descrição Relevante (Estágio 7.1); itens sem descrição eleita "
        "ficam de fora. Ordenado por Divergência decrescente — maiores 'rombos' financeiros no "
        "topo. Infração: 'Entradas sem NF' quando Total Débito < Total Crédito (compra sem nota); "
        "'Saídas sem NF' quando Total Débito ≥ Total Crédito (venda sem nota)."
    )

    if "cruzamento_valor_gerado" not in st.session_state:
        st.session_state["cruzamento_valor_gerado"] = loader.cruzamento_valor_ja_gerado()

    if st.session_state["cruzamento_valor_gerado"]:
        df_preview, total = loader.consultar_cruzamento_valor(limite=None)
        periodo_txt = ""
        if not df_preview.empty:
            periodo = loader.obter_periodo_auditoria()
            periodo_txt = _texto_periodo_auditoria(periodo)
        st.success(f"✅ {total:,} linha(s) em `cruzamento_valor`.{periodo_txt}".replace(",", "."))

        if df_preview.empty:
            st.info('Nenhuma linha gerada — gere "Descrições Relevantes" (Estágio 7.1) e as '
                    'tabelas de entradas/saídas/estoque primeiro.')
        else:
            col_ano, col_busca = st.columns(2)
            anos_disponiveis = sorted(df_preview["ANO"].unique())
            anos_selecionados = col_ano.multiselect(
                "Filtrar por Ano", anos_disponiveis, default=anos_disponiveis, key="filtro_ano_cruzamento_valor",
            )
            busca_descricao = col_busca.text_input(
                "Buscar por Descrição", key="filtro_descricao_cruzamento_valor",
            )

            filtrado = df_preview[df_preview["ANO"].isin(anos_selecionados)]
            if busca_descricao.strip():
                filtrado = filtrado[
                    filtrado["DESCR_ALVO"].str.contains(
                        _padrao_busca_curinga(busca_descricao.strip()), case=False, na=False,
                    )
                ]

            st.markdown(f"**{len(filtrado):,} linha(s)** após filtro.".replace(",", "."))
            amostra = filtrado.head(200).copy()
            amostra["PCT_DIVERGENCIA"] = amostra["PCT_DIVERGENCIA"].apply(_formatar_pct_br)
            for _col in _COLUNAS_MONETARIAS_CRUZAMENTO_VALOR:
                amostra[_col] = amostra[_col].apply(_formatar_moeda_br)
            with st.container(key="cruzamento_valor_tabela"):
                st.markdown(
                    "<style>.st-key-cruzamento_valor_tabela [data-testid='stDataFrame'] "
                    "* { font-size: 12px; }</style>",
                    unsafe_allow_html=True,
                )
                st.dataframe(
                    _preparar_preview(amostra, _COLUNAS_PREVIEW_CRUZAMENTO_VALOR),
                    use_container_width=True,
                    hide_index=True,
                )

        clicou = st.button(
            "Regerar Cruzamento por Valor",
            key="btn_regerar_cruzamento_valor",
            help="Reprocessa entradas/saídas/estoque + produto_alvo e recalcula EI/Compras/"
                 "Vendas/EF por ano e produto.",
        )
    else:
        clicou = st.button("Gerar Cruzamento por Valor", key="btn_gerar_cruzamento_valor")

    if not clicou:
        return

    with st.spinner("Calculando EI/Compras/Vendas/EF por ano e produto..."):
        resultado = loader.persistir_cruzamento_valor()

    if "erro" in resultado:
        st.error(f"Erro: {resultado['erro']}")
        return

    st.session_state["cruzamento_valor_gerado"] = True
    st.rerun()


_COLUNAS_PREVIEW_CRUZAMENTO_PRODUTO = [
    "DESCR_ALVO", "EI", "COMPRAS", "TOTAL_DEBITO", "VENDAS", "EF", "TOTAL_CREDITO",
    "DIVERGENCIA", "INFRACAO", "PCT_DIVERGENCIA",
]


def render_cruzamento_produto() -> None:
    """Estágio 7.2.1 — Cruzamento por Produto (2026-07-19, Solicitação
    Técnica): condensa `cruzamento_valor` (Estágio 7.2, uma linha por
    ANO+COD_ITEM) numa linha por Descrição Relevante, somando os valores
    financeiros e recalculando Infração/% Diverg/Divergência (|∑TD-∑TC|,
    líquida — mudança de 2026-07-20, ver loader.gerar_cruzamento_
    produto() pro raciocínio completo) sobre os totais acumulados. Exige
    `cruzamento_valor` (Estágio 7.2) já gerada.
    Mesmo padrão "Gerar/Regerar" + prévia de alta densidade das outras
    páginas (hide_index, fonte 12px, formatação BR — reaproveita
    _formatar_moeda_br()/_formatar_pct_br() do Estágio 7.2). Drill-down:
    um st.selectbox com as Descrições Relevantes já geradas — ao
    escolher uma, filtra `cruzamento_valor` por essa descrição e mostra
    o detalhamento ano a ano abaixo, na mesma formatação."""
    st.subheader("Estágio 7.2.1 — Cruzamento por Produto")
    st.caption(
        "Condensa o Cruzamento por Valor (Estágio 7.2) por Descrição Relevante — soma EI, "
        "Compras, Total Débito, Vendas, EF e Total Crédito de todos os anos do produto. "
        "Divergência é o total LÍQUIDO acumulado (|Total Débito − Total Crédito|), sempre "
        "coerente com as duas colunas ao lado — veja o detalhamento ano a ano no drill-down "
        "abaixo. Infração e % Diverg recalculados sobre os totais acumulados (mesma regra do "
        "Estágio 7.2: Total Débito < Total Crédito acumulado → 'Entradas sem NF'; caso "
        "contrário → 'Saídas sem NF'). Ordenado por Divergência líquida decrescente — "
        "produtos com maior 'rombo' líquido no período no topo."
    )

    if "cruzamento_produto_gerado" not in st.session_state:
        st.session_state["cruzamento_produto_gerado"] = loader.cruzamento_produto_ja_gerado()

    if st.session_state["cruzamento_produto_gerado"]:
        df_preview, total = loader.consultar_cruzamento_produto(limite=None)
        st.success(f"✅ {total:,} produto(s) em `cruzamento_produto`.".replace(",", "."))

        if df_preview.empty:
            st.info('Nenhum produto gerado — gere "Cruzamento por Valor" (Estágio 7.2) primeiro.')
        else:
            busca_descricao = st.text_input(
                "Buscar por Descrição", key="filtro_descricao_cruzamento_produto",
            )
            filtrado = df_preview
            if busca_descricao.strip():
                filtrado = filtrado[
                    filtrado["DESCR_ALVO"].str.contains(
                        _padrao_busca_curinga(busca_descricao.strip()), case=False, na=False,
                    )
                ]

            st.markdown(f"**{len(filtrado):,} produto(s)** após filtro.".replace(",", "."))
            amostra = filtrado.head(200).copy()
            amostra["PCT_DIVERGENCIA"] = amostra["PCT_DIVERGENCIA"].apply(_formatar_pct_br)
            for _col in _COLUNAS_MONETARIAS_CRUZAMENTO_VALOR:
                amostra[_col] = amostra[_col].apply(_formatar_moeda_br)
            with st.container(key="cruzamento_produto_tabela"):
                st.markdown(
                    "<style>.st-key-cruzamento_produto_tabela [data-testid='stDataFrame'] "
                    "* { font-size: 12px; }</style>",
                    unsafe_allow_html=True,
                )
                st.dataframe(
                    _preparar_preview(amostra, _COLUNAS_PREVIEW_CRUZAMENTO_PRODUTO),
                    use_container_width=True,
                    hide_index=True,
                )

            st.divider()
            st.markdown("**Detalhamento por Ano (drill-down do Estágio 7.2)**")
            produtos_disponiveis = sorted(df_preview["DESCR_ALVO"].unique())
            produto_selecionado = st.selectbox(
                "Selecione um produto para ver o detalhamento anual",
                options=["Selecione..."] + produtos_disponiveis,
                key="drilldown_cruzamento_produto",
            )
            if produto_selecionado != "Selecione...":
                df_valor, _ = loader.consultar_cruzamento_valor(limite=None)
                detalhe = df_valor[df_valor["DESCR_ALVO"] == produto_selecionado].sort_values("ANO").copy()
                if detalhe.empty:
                    st.info("Nenhum detalhamento anual encontrado pra este produto.")
                else:
                    detalhe["PCT_DIVERGENCIA"] = detalhe["PCT_DIVERGENCIA"].apply(_formatar_pct_br)
                    for _col in _COLUNAS_MONETARIAS_CRUZAMENTO_VALOR:
                        detalhe[_col] = detalhe[_col].apply(_formatar_moeda_br)
                    with st.container(key="cruzamento_produto_drilldown_tabela"):
                        st.markdown(
                            "<style>.st-key-cruzamento_produto_drilldown_tabela "
                            "[data-testid='stDataFrame'] * { font-size: 12px; }</style>",
                            unsafe_allow_html=True,
                        )
                        st.dataframe(
                            _preparar_preview(detalhe, _COLUNAS_PREVIEW_CRUZAMENTO_VALOR),
                            use_container_width=True,
                            hide_index=True,
                        )

        clicou = st.button(
            "Regerar Cruzamento por Produto",
            key="btn_regerar_cruzamento_produto",
            help="Reprocessa a partir de cruzamento_valor (Estágio 7.2) e recalcula os totais por produto.",
        )
    else:
        clicou = st.button("Gerar Cruzamento por Produto", key="btn_gerar_cruzamento_produto")

    if not clicou:
        return

    with st.spinner("Consolidando por produto..."):
        resultado = loader.persistir_cruzamento_produto()

    if "erro" in resultado:
        st.error(f"Erro: {resultado['erro']}")
        return

    st.session_state["cruzamento_produto_gerado"] = True
    st.rerun()


_COLUNAS_PREVIEW_RN1_FISICA = [
    "ANO", "DESCR_ALVO", "EI", "COMPRAS", "TOTAL_DEBITO", "VENDAS", "EF", "TOTAL_CREDITO",
    "DIVERGENCIA", "INFRACAO", "PCT_DIVERGENCIA",
]


def _preparar_preview_rn1_fisica(df: pd.DataFrame) -> pd.DataFrame:
    """Mesma preparação de _preparar_preview(), mas com "Compras (XML)"/
    "Vendas (XML)" no lugar de "Compras (R$)"/"Vendas (R$)" (Dicionário de
    Campos é genérico, compartilhado por todos os painéis — ver `feedback_
    dicionario_campos_convencao` — por isso o rótulo específico deste
    painel é aplicado aqui, não no dicionário)."""
    preview = _preparar_preview(df, _COLUNAS_PREVIEW_RN1_FISICA)
    return preview.rename(columns={"Compras (R$)": "Compras (XML)", "Vendas (R$)": "Vendas (XML)"})


def render_rn1_fisica() -> None:
    """Estágio 7.3 — RN1 Movimentação Física (2026-07-20, Solicitação
    Técnica): aplica EI+Compras=Vendas+EF por (ANO, Descrição Relevante),
    em R$ — ver loader.gerar_rn1_fisica(). Diferente do Estágio 7.2:
    Compras soma TODO o valor de `estoque_entradas` (XML puro), inclusive
    itens sem match no BC3 (esclarecido pelo usuário 2026-07-20: "dados de
    entradas do xml podem ser diferentes dos dados de entradas de
    declaração" — o 7.2 só soma itens COM match); itens sem vínculo nenhum
    viram uma linha POR descrição bruta do XML (prefixo `loader.PREFIXO_
    RN1_SEM_VINCULO`, "(SEM VÍNCULO) " — usuário alertou que podem ser
    "vários produtos", não um caso residual, ver achado real de 52
    descrições distintas na cometa), em vez de somem do relatório ou
    virarem um total cego. Vendas/EI/EF continuam vindo de `cruzamento_
    valor` (Estágio 7.2) já persistida — não têm o mesmo problema de
    cobertura. Agregado por Descrição Relevante (Estágio 7.1) — várias
    COD_ITEM que compartilham a mesma DESCR_ALVO somam juntas numa única
    linha por ano. Exige `produto_alvo` (7.1) e `cruzamento_valor` (7.2)
    já gerados. Mesmo padrão "Gerar/Regerar" + prévia de alta densidade
    das outras páginas (hide_index, fonte 12px, formatação BR), com
    filtro de Ano (multiselect) e busca textual por Descrição, igual ao
    Estágio 7.2."""
    st.subheader("Estágio 7.3 — RN1: Movimentação Física (XML)")
    st.caption(
        "Aplica EI + Compras = Vendas + EF por (Ano, Descrição Relevante), em R$ — Compras soma "
        "TODO o valor do XML de entradas (Estágio 4), inclusive itens sem match no Matching/BC3 "
        "('notas na gaveta' — cada descrição bruta do XML sem vínculo vira sua própria linha, "
        "prefixada com \"(SEM VÍNCULO) \"); Vendas pela visão física do XML, Estoque (EI/EF) pela "
        "declaração (Estágio 5). Identidade pela Descrição Relevante (Estágio 7.1) — soma todo "
        "código que compartilhe a mesma descrição. Ordenado por Divergência decrescente. Infração: "
        "'Entradas sem NF' quando Total Débito < Total Crédito (compra sem nota); 'Saídas sem NF' "
        "quando Total Débito ≥ Total Crédito (venda sem nota)."
    )

    if "rn1_fisica_gerado" not in st.session_state:
        st.session_state["rn1_fisica_gerado"] = loader.rn1_fisica_ja_gerado()

    if st.session_state["rn1_fisica_gerado"]:
        df_preview, total = loader.consultar_rn1_fisica(limite=None)
        st.success(f"✅ {total:,} linha(s) em `rn1_fisica`.".replace(",", "."))

        if df_preview.empty:
            st.info('Nenhuma linha gerada — gere "Descrições Relevantes" (Estágio 7.1) e '
                    '"Cruzamento por Valor" (Estágio 7.2) primeiro.')
        else:
            mask_sem_vinculo = df_preview["DESCR_ALVO"].str.startswith(loader.PREFIXO_RN1_SEM_VINCULO)
            sem_vinculo = df_preview.loc[mask_sem_vinculo, "COMPRAS"].sum()
            if sem_vinculo > 0:
                n_produtos_sem_vinculo = df_preview.loc[mask_sem_vinculo, "DESCR_ALVO"].nunique()
                st.warning(
                    f"⚠️ R$ {_formatar_moeda_br(sem_vinculo)} em Compras sem vínculo nenhum no "
                    f"Matching (BC3), em {n_produtos_sem_vinculo} descrição(ões) distinta(s) do XML "
                    "— itens que entraram fisicamente mas nunca foram vinculados/lançados. Linhas "
                    "prefixadas com \"(SEM VÍNCULO) \" na tabela abaixo."
                )

            col_ano, col_busca = st.columns(2)
            anos_disponiveis = sorted(df_preview["ANO"].unique())
            anos_selecionados = col_ano.multiselect(
                "Filtrar por Ano", anos_disponiveis, default=anos_disponiveis, key="filtro_ano_rn1_fisica",
            )
            busca_descricao = col_busca.text_input(
                "Buscar por Descrição", key="filtro_descricao_rn1_fisica",
            )

            filtrado = df_preview[df_preview["ANO"].isin(anos_selecionados)]
            if busca_descricao.strip():
                filtrado = filtrado[
                    filtrado["DESCR_ALVO"].str.contains(
                        _padrao_busca_curinga(busca_descricao.strip()), case=False, na=False,
                    )
                ]

            st.markdown(f"**{len(filtrado):,} linha(s)** após filtro.".replace(",", "."))
            amostra = filtrado.head(200).copy()
            amostra["PCT_DIVERGENCIA"] = amostra["PCT_DIVERGENCIA"].apply(_formatar_pct_br)
            for _col in _COLUNAS_MONETARIAS_CRUZAMENTO_VALOR:
                amostra[_col] = amostra[_col].apply(_formatar_moeda_br)
            with st.container(key="rn1_fisica_tabela"):
                st.markdown(
                    "<style>.st-key-rn1_fisica_tabela [data-testid='stDataFrame'] "
                    "* { font-size: 12px; }</style>",
                    unsafe_allow_html=True,
                )
                st.dataframe(
                    _preparar_preview_rn1_fisica(amostra),
                    use_container_width=True,
                    hide_index=True,
                )

        clicou = st.button(
            "Regerar RN1 — Movimentação Física",
            key="btn_regerar_rn1_fisica",
            help="Reprocessa Compras a partir do XML de entradas (Estágio 4) e Vendas/EI/EF a "
                 "partir de cruzamento_valor (Estágio 7.2), recalculando os totais por (Ano, "
                 "Descrição Relevante).",
        )
    else:
        clicou = st.button("Gerar RN1 — Movimentação Física", key="btn_gerar_rn1_fisica")

    if not clicou:
        return

    with st.spinner("Consolidando Compras (XML completo) e Vendas/EI/EF por ano e Descrição Relevante..."):
        resultado = loader.persistir_rn1_fisica()

    if "erro" in resultado:
        st.error(f"Erro: {resultado['erro']}")
        return

    st.session_state["rn1_fisica_gerado"] = True
    st.rerun()


_COLUNAS_PREVIEW_RN1_PRODUTO = [
    "DESCR_ALVO", "EI", "COMPRAS", "TOTAL_DEBITO", "VENDAS", "EF", "TOTAL_CREDITO",
    "DIVERGENCIA", "INFRACAO", "PCT_DIVERGENCIA",
]


def _preparar_preview_rn1_produto(df: pd.DataFrame) -> pd.DataFrame:
    """Mesma preparação de _preparar_preview_rn1_fisica() (rename "Compras
    (XML)"/"Vendas (XML)"), aplicada às colunas do Estágio 7.3.1."""
    preview = _preparar_preview(df, _COLUNAS_PREVIEW_RN1_PRODUTO)
    return preview.rename(columns={"Compras (R$)": "Compras (XML)", "Vendas (R$)": "Vendas (XML)"})


def render_rn1_produto() -> None:
    """Estágio 7.3.1 — RN1 por Produto (2026-07-20, Solicitação Técnica:
    "o 7.2.1 unifica por produto. consegue fazer o mesmo para o 7.3?"):
    condensa `rn1_fisica` (Estágio 7.3, uma linha por Ano+Descrição
    Relevante) numa linha por Descrição Relevante, somando os valores
    financeiros de todos os anos e recalculando Infração/% Diverg sobre
    os totais acumulados — ver loader.gerar_rn1_produto() pro raciocínio
    completo (mesma técnica de render_cruzamento_produto(), Estágio
    7.2.1, mas sobre rn1_fisica em vez de cruzamento_valor — os números
    DIVERGEM do 7.2.1 sempre que houver Compras sem vínculo no Matching).
    Exige `rn1_fisica` (Estágio 7.3) já gerada. Mesmo padrão "Gerar/
    Regerar" + prévia de alta densidade + drill-down do 7.2.1."""
    st.subheader("Estágio 7.3.1 — RN1 por Produto")
    st.caption(
        "Condensa a RN1 — Movimentação Física (Estágio 7.3) por Descrição Relevante — soma EI, "
        "Compras (XML completo, inclusive sem vínculo no Matching), Total Débito, Vendas, EF e "
        "Total Crédito de todos os anos do produto. Divergência é o total LÍQUIDO acumulado "
        "(|Total Débito − Total Crédito|), sempre coerente com as duas colunas ao lado — veja o "
        "detalhamento ano a ano no drill-down abaixo. Infração e % Diverg recalculados sobre os "
        "totais acumulados (mesma regra do Estágio 7.3). Ordenado por Divergência líquida "
        "decrescente — produtos com maior 'rombo' líquido no período no topo."
    )

    if "rn1_produto_gerado" not in st.session_state:
        st.session_state["rn1_produto_gerado"] = loader.rn1_produto_ja_gerado()

    if st.session_state["rn1_produto_gerado"]:
        df_preview, total = loader.consultar_rn1_produto(limite=None)
        st.success(f"✅ {total:,} produto(s) em `rn1_produto`.".replace(",", "."))

        if df_preview.empty:
            st.info('Nenhum produto gerado — gere "RN1 — Movimentação Física" (Estágio 7.3) primeiro.')
        else:
            mask_sem_vinculo = df_preview["DESCR_ALVO"].str.startswith(loader.PREFIXO_RN1_SEM_VINCULO)
            sem_vinculo = df_preview.loc[mask_sem_vinculo, "COMPRAS"].sum()
            if sem_vinculo > 0:
                n_produtos_sem_vinculo = df_preview.loc[mask_sem_vinculo, "DESCR_ALVO"].nunique()
                st.warning(
                    f"⚠️ R$ {_formatar_moeda_br(sem_vinculo)} em Compras sem vínculo nenhum no "
                    f"Matching (BC3), em {n_produtos_sem_vinculo} descrição(ões) distinta(s) do "
                    "XML, acumulado no período todo."
                )

            busca_descricao = st.text_input(
                "Buscar por Descrição", key="filtro_descricao_rn1_produto",
            )
            filtrado = df_preview
            if busca_descricao.strip():
                filtrado = filtrado[
                    filtrado["DESCR_ALVO"].str.contains(
                        _padrao_busca_curinga(busca_descricao.strip()), case=False, na=False,
                    )
                ]

            st.markdown(f"**{len(filtrado):,} produto(s)** após filtro.".replace(",", "."))
            amostra = filtrado.head(200).copy()
            amostra["PCT_DIVERGENCIA"] = amostra["PCT_DIVERGENCIA"].apply(_formatar_pct_br)
            for _col in _COLUNAS_MONETARIAS_CRUZAMENTO_VALOR:
                amostra[_col] = amostra[_col].apply(_formatar_moeda_br)
            with st.container(key="rn1_produto_tabela"):
                st.markdown(
                    "<style>.st-key-rn1_produto_tabela [data-testid='stDataFrame'] "
                    "* { font-size: 12px; }</style>",
                    unsafe_allow_html=True,
                )
                st.dataframe(
                    _preparar_preview_rn1_produto(amostra),
                    use_container_width=True,
                    hide_index=True,
                )

            st.divider()
            st.markdown("**Detalhamento por Ano (drill-down do Estágio 7.3)**")
            produtos_disponiveis = sorted(df_preview["DESCR_ALVO"].unique())
            produto_selecionado = st.selectbox(
                "Selecione um produto para ver o detalhamento anual",
                options=["Selecione..."] + produtos_disponiveis,
                key="drilldown_rn1_produto",
            )
            if produto_selecionado != "Selecione...":
                df_fisica, _ = loader.consultar_rn1_fisica(limite=None)
                detalhe = df_fisica[df_fisica["DESCR_ALVO"] == produto_selecionado].sort_values("ANO").copy()
                if detalhe.empty:
                    st.info("Nenhum detalhamento anual encontrado pra este produto.")
                else:
                    detalhe["PCT_DIVERGENCIA"] = detalhe["PCT_DIVERGENCIA"].apply(_formatar_pct_br)
                    for _col in _COLUNAS_MONETARIAS_CRUZAMENTO_VALOR:
                        detalhe[_col] = detalhe[_col].apply(_formatar_moeda_br)
                    with st.container(key="rn1_produto_drilldown_tabela"):
                        st.markdown(
                            "<style>.st-key-rn1_produto_drilldown_tabela "
                            "[data-testid='stDataFrame'] * { font-size: 12px; }</style>",
                            unsafe_allow_html=True,
                        )
                        st.dataframe(
                            _preparar_preview_rn1_fisica(detalhe),
                            use_container_width=True,
                            hide_index=True,
                        )

        clicou = st.button(
            "Regerar RN1 por Produto",
            key="btn_regerar_rn1_produto",
            help="Reprocessa a partir de rn1_fisica (Estágio 7.3) e recalcula os totais por produto.",
        )
    else:
        clicou = st.button("Gerar RN1 por Produto", key="btn_gerar_rn1_produto")

    if not clicou:
        return

    with st.spinner("Consolidando por produto..."):
        resultado = loader.persistir_rn1_produto()

    if "erro" in resultado:
        st.error(f"Erro: {resultado['erro']}")
        return

    st.session_state["rn1_produto_gerado"] = True
    st.rerun()


_COLUNAS_PREVIEW_RN1_FISICA_SIMULADA_30 = [
    "ANO", "COD_ITEM", "UNID_ALVO", "EI", "COMPRAS", "TOTAL_DEBITO", "VENDAS", "EF", "TOTAL_CREDITO",
    "DIVERGENCIA", "INFRACAO", "PCT_DIVERGENCIA",
]


def _preparar_preview_rn1_fisica_simulada_30(df: pd.DataFrame) -> pd.DataFrame:
    """Identifica as colunas majoradas (EI/Compras/EF) com o sufixo
    "(+30%)" no cabeçalho, pra evitar confusão com os valores reais do
    Estágio 7.3.1. Vendas permanece "Vendas (XML)" — âncora real, sem
    acréscimo. Usada no drill-down por ano dentro de
    _render_grupo_produto_alvo_fiscalizacao() — sem DESCR_ALVO
    (2026-07-22, pedido do usuário: "retire o campo descrição relevante,
    pois já traz no título" — o produto já aparece no `st.markdown` do
    cabeçalho da seção, repetir em toda linha da tabela é redundante)."""
    preview = _preparar_preview(df, _COLUNAS_PREVIEW_RN1_FISICA_SIMULADA_30)
    return preview.rename(columns={
        "EI (R$)": "EI (+30%)",
        "Compras (R$)": "Compras (+30%)",
        "EF (R$)": "EF (+30%)",
        "Vendas (R$)": "Vendas (XML)",
    })


_COLUNAS_BASE_GRUPO_PRODUTO_ALVO = [
    "DESCR_ALVO", "UNID_ALVO", "COD_ITEM", "DIVERGENCIA", "INFRACAO", "PCT_DIVERGENCIA",
    "TOTAL_DEBITO", "TOTAL_CREDITO",
]
_COLUNA_CHECKBOX_GRUPO_PRODUTO_ALVO = "Selecionar p/ Fiscalização"
_COLUNA_CHECKBOX_VER_ANOS = "📅 Ver Anos"
_COLUNAS_DESTAQUE_VERMELHO_GRUPO_ALVO = ("TOTAL_DEBITO", "TOTAL_CREDITO", "DIVERGENCIA")
_COLUNAS_DESTAQUE_VERMELHO_GRUPO_ALVO_LABEL = (
    "Total Debito (R$)", "Total Credito (R$)", "Divergencia (R$)", "% Diverg",
)
_COLUNAS_OCULTAS_EDITOR_GRUPO_ALVO = ("Total Debito (R$)", "Total Credito (R$)", "Observacao")
_MARCADOR_CABECALHO_VERMELHO_EDITOR_GRUPO_ALVO = {
    "Divergencia (R$)": "🔴 Divergencia (R$)",
    "% Diverg": "🔴 % Diverg",
    "Infracao": "🔴 Infracao",
}


_LIMIAR_DESTAQUE_VERMELHO_PCT_DIVERG = 30


def _destacar_vermelho_grupo_alvo(df: pd.DataFrame, acima_do_limiar: pd.Series) -> "pd.io.formats.style.Styler":
    """Pinta de vermelho (cor de texto de verdade, via pandas.Styler) as
    colunas de Total Débito/Total Crédito/Divergência/% Diverg — só nas
    LINHAS em que % Diverg > 30% (2026-07-22, pedido do usuário: "só
    pinte de vermelho se > 30%" — antes pintava a coluna inteira, sem
    condição). `acima_do_limiar` é uma Series booleana (índice igual ao
    de `df`) calculada ANTES de % Diverg virar string formatada
    ("313,36%") — precisa ser o valor numérico cru pra comparar com 30,
    por isso é passada separada em vez de recalculada aqui. Usada nas
    tabelas SOMENTE LEITURA do Grupo de Produto Alvo (drill-down por ano
    e "Ver grupo completo já salvo"), que são st.dataframe comum e por
    isso aceitam Styler. A tabela principal (st.data_editor, com os
    checkboxes) NÃO tem esse destaque — confirmado com o usuário
    2026-07-22 que `st.data_editor` não aceita `pandas.Styler`."""
    colunas = [c for c in _COLUNAS_DESTAQUE_VERMELHO_GRUPO_ALVO_LABEL if c in df.columns]

    def _estilo_linha(linha: pd.Series) -> list:
        vermelho = "color: red" if acima_do_limiar.get(linha.name, False) else ""
        return [vermelho if col in colunas else "" for col in df.columns]

    return df.style.apply(_estilo_linha, axis=1)


def _render_grupo_produto_alvo_fiscalizacao(amostra_raw: pd.DataFrame) -> None:
    """Solicitação Técnica (2026-07-22): "o 7.3.2 produto será o painel
    para escolha do produto alvo" — mesma mecânica do `ranking.py` do app
    antigo (ANTIGO_geraldo_2020_2024_5: checkbox "Escolher" + botão
    "Salvar Produto Alvo" + `registrar_produto_eleito()`), agora sobre os
    produtos já filtrados/exibidos no 7.3.2 (Divergência, Infração, %
    Diverg) em vez da tabela de ranking bruta (Origem/Produto/QT/Valor)
    do app antigo. `amostra_raw` é a mesma fatia (até 200 linhas, já
    filtrada por Descrição), ANTES da formatação de moeda/percentual —
    os valores crus são o que efetivamente vai pra loader.salvar_grupo_
    produto_alvo_fiscalizacao(); a formatação aqui é só cosmética (mesmo
    padrão do resto do painel). Marcar/desmarcar e salvar sob um filtro
    de busca não apaga seleções feitas sob outro filtro (merge por
    DESCR_ALVO em loader.py).

    Unidade Relevante (`UNID_ALVO`, 2026-08-04, Solicitação Técnica —
    "Integração da Unidade Relevante no Estágio 7.3.2"): transportada do
    Estágio 7.1 (produto_alvo) via loader._mapa_cod_item_por_descr_alvo(),
    posicionada logo após Descrição Relevante, SÓ LEITURA (mesmo padrão
    de IS_ST/COD_ITEM, puramente informativa nesta tela). Chegou a virar
    editável aqui por uma rodada (mesmo dia), junto com um campo novo
    "Descrição Editada" — o usuário pediu pra reverter e mover a edição
    de ambas pro Estágio 10 (`render_produtos_alvo_salvos()`/
    `loader.salvar_edicoes_produto_alvo_salvos()`), mesmo lugar/padrão
    já usado pro IS_ST; `DESCR_EDITADA` nem aparece mais nesta tela.

    Chave de identidade da tabela `produto_alvo_fiscalizacao` trocou de
    `DESCR_ALVO` pra `COD_ITEM` (com fallback pra DESCR_ALVO só quando
    COD_ITEM vem vazio) — ver `loader._chave_produto_alvo_fiscalizacao()`/
    `salvar_grupo_produto_alvo_fiscalizacao()` pro raciocínio completo
    (essa parte NÃO foi revertida — só a edição de UNID_ALVO/
    DESCR_EDITADA em si).

    Segunda coluna de checkbox, "📅 Ver Anos" (2026-07-22, mesma sessão —
    usuário pediu pra esta tabela virar também a base do drill-down por
    ano, "ignorando" a antiga tabela read-only com clique-de-linha):
    marcar essa coluna abre, logo abaixo da tabela, o detalhamento anual
    (loader.simular_rn1_fisica_30()) do(s) produto(s) marcado(s) — não
    precisa de on_select (que st.data_editor nem suporta nesta versão do
    Streamlit) porque o próprio retorno do data_editor já dá o estado do
    checkbox editado. Extração de valores marcados sempre por índice
    (`.reindex`), nunca por posição (`.to_numpy()` direto) — mais seguro
    contra qualquer reordenação interna do widget."""
    st.markdown("**🎯 Grupo de Produto Alvo (Fiscalização)**")
    st.caption(
        "Marque \"Selecionar p/ Fiscalização\" pros produtos que entram no grupo efetivamente "
        "fiscalizado (fica salvo mesmo trocando o filtro de busca depois), e \"Ver Anos\" pra "
        "abrir o detalhamento anual (simulação +30%) do produto logo abaixo da tabela. Total "
        "Débito, Total Crédito e Observação ficam só nas tabelas de leitura abaixo. Unidade "
        "Relevante e Descrição Editada podem ser corrigidas no Estágio 10 (Produtos Alvos "
        "Salvos), depois de marcar o produto aqui."
    )

    ja_selecionados, _ = loader.consultar_grupo_produto_alvo_fiscalizacao(limite=None, apenas_ativos=True)
    # Chave de identidade: COD_ITEM quando preenchido, senão DESCR_ALVO
    # (mesmo raciocínio de loader._chave_produto_alvo_fiscalizacao() —
    # DESCR_ALVO pode mudar numa regeração futura de produto_alvo, ver
    # memoria/2026-08-04.md, "BUG REAL corrigido").
    if not ja_selecionados.empty:
        chave_salva = ja_selecionados["COD_ITEM"].where(
            ja_selecionados["COD_ITEM"] != "", ja_selecionados["DESCR_ALVO"],
        )
        chaves_ja_selecionadas = set(chave_salva)
        # pd.Series(dados, index=chave) em vez de .set_index(lista) -- uma
        # lista Python comum (ou .values/ArrowStringArray, vindo de
        # duckdb.df()) é ambígua pro pandas (tenta interpretar cada
        # elemento como NOME DE COLUNA — achado real, 2026-08-04, ver
        # loader.salvar_grupo_produto_alvo_fiscalizacao()).
        obs_por_produto = pd.Series(ja_selecionados["OBSERVACAO"].to_numpy(), index=chave_salva.tolist())
    else:
        chaves_ja_selecionadas = set()
        obs_por_produto = pd.Series(dtype=str)

    editor_base = amostra_raw[_COLUNAS_BASE_GRUPO_PRODUTO_ALVO].copy()
    chave_tela = editor_base["COD_ITEM"].where(editor_base["COD_ITEM"] != "", editor_base["DESCR_ALVO"])
    editor_base.insert(
        3, _COLUNA_CHECKBOX_GRUPO_PRODUTO_ALVO, chave_tela.isin(chaves_ja_selecionadas),
    )
    editor_base.insert(4, _COLUNA_CHECKBOX_VER_ANOS, False)
    editor_base["OBSERVACAO"] = chave_tela.map(obs_por_produto).fillna("")

    editor_exibicao = editor_base.copy()
    editor_exibicao["PCT_DIVERGENCIA"] = editor_exibicao["PCT_DIVERGENCIA"].apply(_formatar_pct_br)
    for _col in _COLUNAS_DESTAQUE_VERMELHO_GRUPO_ALVO:
        editor_exibicao[_col] = editor_exibicao[_col].apply(_formatar_moeda_br)
    editor_exibicao = editor_exibicao.rename(columns=loader.carregar_dicionario_campos())
    editor_exibicao = editor_exibicao.rename(columns={"OBSERVACAO": "Observacao"})
    # Total Débito/Total Crédito/Observação saem da tabela editável (pedido
    # do usuário 2026-07-22) — continuam disponíveis no drill-down e no
    # "Ver grupo completo já salvo" abaixo. Divergência/%Diverg/Infração
    # ganham marcador 🔴 só no CABEÇALHO (não no valor de cada linha) —
    # mesma sessão, depois de descartar bolinha por linha e crachá/etiqueta
    # (ver memoria/2026-07-22.md pro raciocínio completo dessa escolha).
    editor_exibicao = editor_exibicao.drop(columns=list(_COLUNAS_OCULTAS_EDITOR_GRUPO_ALVO))
    editor_exibicao = editor_exibicao.rename(columns=_MARCADOR_CABECALHO_VERMELHO_EDITOR_GRUPO_ALVO)

    colunas_travadas = [
        c for c in editor_exibicao.columns
        if c not in (_COLUNA_CHECKBOX_GRUPO_PRODUTO_ALVO, _COLUNA_CHECKBOX_VER_ANOS)
    ]
    with st.container(key="rn1_simulada_30_editor_grupo_alvo"):
        st.markdown(
            "<style>.st-key-rn1_simulada_30_editor_grupo_alvo [data-testid='stDataFrame'] "
            "* { font-size: 12px; }</style>",
            unsafe_allow_html=True,
        )
        editado = st.data_editor(
            editor_exibicao,
            use_container_width=True,
            hide_index=True,
            disabled=colunas_travadas,
            key="editor_grupo_produto_alvo_fiscalizacao",
        )

    if st.button("💾 Salvar Grupo de Produto Alvo", key="btn_salvar_grupo_produto_alvo"):
        selecoes = editor_base[_COLUNAS_BASE_GRUPO_PRODUTO_ALVO].copy()
        selecoes["SELECIONADO"] = (
            editado[_COLUNA_CHECKBOX_GRUPO_PRODUTO_ALVO].reindex(editor_base.index).to_numpy()
        )
        # "Observacao" não está mais na tabela exibida (removida a pedido do
        # usuário) — mantém o que já estava salvo, sem edição possível aqui.
        selecoes["OBSERVACAO"] = editor_base["OBSERVACAO"].to_numpy()
        resultado = loader.salvar_grupo_produto_alvo_fiscalizacao(selecoes)
        if "erro" in resultado:
            st.error(f"Erro: {resultado['erro']}")
        else:
            st.success(f"✅ Grupo salvo — {resultado['total_ativos']} produto(s) ativo(s) no total.")
            st.rerun()

    marcados_ver_anos = editado[_COLUNA_CHECKBOX_VER_ANOS].reindex(editor_base.index)
    produtos_ver_anos = editor_base.loc[marcados_ver_anos.fillna(False), "DESCR_ALVO"].tolist()
    for descr_produto in produtos_ver_anos:
        st.divider()
        st.markdown(f"**Detalhamento por Ano — simulação +30% — {descr_produto}**")
        detalhe = loader.simular_rn1_fisica_30(descr_produto)
        if detalhe.empty:
            st.info("Nenhum detalhamento anual encontrado pra este produto.")
        else:
            acima_30 = detalhe["PCT_DIVERGENCIA"] > _LIMIAR_DESTAQUE_VERMELHO_PCT_DIVERG
            detalhe["PCT_DIVERGENCIA"] = detalhe["PCT_DIVERGENCIA"].apply(_formatar_pct_br)
            for _col in _COLUNAS_MONETARIAS_CRUZAMENTO_VALOR:
                detalhe[_col] = detalhe[_col].apply(_formatar_moeda_br)
            st.dataframe(
                _destacar_vermelho_grupo_alvo(_preparar_preview_rn1_fisica_simulada_30(detalhe), acima_30),
                use_container_width=True,
                hide_index=True,
            )

    grupo_atual, total_grupo = loader.consultar_grupo_produto_alvo_fiscalizacao(limite=None, apenas_ativos=True)
    if not grupo_atual.empty:
        with st.expander(f"Ver grupo completo já salvo ({total_grupo} produto(s))"):
            grupo_preview = grupo_atual.copy()
            acima_30 = grupo_preview["PCT_DIVERGENCIA"] > _LIMIAR_DESTAQUE_VERMELHO_PCT_DIVERG
            grupo_preview["PCT_DIVERGENCIA"] = grupo_preview["PCT_DIVERGENCIA"].apply(_formatar_pct_br)
            for _col in _COLUNAS_DESTAQUE_VERMELHO_GRUPO_ALVO:
                grupo_preview[_col] = grupo_preview[_col].apply(_formatar_moeda_br)
            st.dataframe(
                _destacar_vermelho_grupo_alvo(_preparar_preview(
                    grupo_preview,
                    _COLUNAS_BASE_GRUPO_PRODUTO_ALVO + ["TS", "OBSERVACAO"],
                ), acima_30),
                use_container_width=True,
                hide_index=True,
            )


def render_rn1_simulada_30() -> None:
    """Estágio 7.3.2 — Simulação RN1 (+30%) (2026-07-22, Solicitação
    Técnica): parte de rn1_produto (Estágio 7.3.1, já condensado por
    Descrição Relevante) e majora EI/Compras/EF em 30% — testa se uma
    eventual subvaloração de 30% nessas contas de "custo"/"estoque"
    explicaria as divergências, ou se o risco fiscal permanece estrutural
    mesmo com os valores majorados. Vendas permanece o valor físico real
    do XML, sem acréscimo, servindo de âncora de confronto — ver
    loader.gerar_rn1_simulada_30() pro raciocínio completo. Exige
    `rn1_produto` (Estágio 7.3.1) já gerada. Painel único, direto pra
    seção "Grupo de Produto Alvo (Fiscalização)"
    (_render_grupo_produto_alvo_fiscalizacao()) — 2026-07-22, usuário
    pediu pra unificar: a tabela editável (checkbox de seleção +
    checkbox "Ver Anos" pro drill-down) virou a ÚNICA tabela do painel,
    substituindo a antiga tabela read-only com clique-de-linha (removida
    a pedido: "essa tabela ficou ótima como base para drill down de
    anos... pode ignorar a primeira tabela")."""
    st.subheader("Estágio 7.3.2 — Simulação RN1 (+30%)")
    st.caption(
        "Simula uma subvaloração de 30% em Estoque Inicial, Compras e Estoque Final (colunas "
        "marcadas com \"(+30%)\") sobre o total acumulado por produto do Estágio 7.3.1, mantendo "
        "Vendas como âncora real do XML, sem acréscimo. Total Débito, Total Crédito, Divergência, "
        "Infração e % Diverg recalculados sobre os novos totais — ajuda a identificar se uma margem "
        "de erro de escrituração explicaria as divergências ou se os indícios de omissão são "
        "estruturais. Ordenado por Divergência decrescente. Compras e Vendas vêm da movimentação "
        "física do XML (todo o volume do Estágio 4, com ou sem vínculo no Matching/BC3); Estoque "
        "Inicial e Final vêm da declaração (SPED, Bloco H)."
    )

    if "rn1_simulada_30_gerado" not in st.session_state:
        st.session_state["rn1_simulada_30_gerado"] = loader.rn1_simulada_30_ja_gerado()

    if st.session_state["rn1_simulada_30_gerado"]:
        df_preview, total = loader.consultar_rn1_simulada_30(limite=None)
        st.success(f"✅ {total:,} produto(s) em `rn1_simulada_30`.".replace(",", "."))

        if df_preview.empty:
            st.info('Nenhum produto gerado — gere "RN1 por Produto" (Estágio 7.3.1) primeiro.')
        else:
            busca_descricao = st.text_input(
                "Buscar por Descrição", key="filtro_descricao_rn1_simulada_30",
            )
            filtrado = df_preview
            if busca_descricao.strip():
                filtrado = filtrado[
                    filtrado["DESCR_ALVO"].str.contains(
                        _padrao_busca_curinga(busca_descricao.strip()), case=False, na=False,
                    )
                ]

            st.markdown(f"**{len(filtrado):,} produto(s)** após filtro.".replace(",", "."))
            amostra_raw = filtrado.head(200).copy()
            _render_grupo_produto_alvo_fiscalizacao(amostra_raw)

        clicou = st.button(
            "Regerar Simulação RN1 (+30%)",
            key="btn_regerar_rn1_simulada_30",
            help="Reprocessa a partir de rn1_produto (Estágio 7.3.1) e recalcula os totais majorados.",
        )
    else:
        clicou = st.button("Gerar Simulação RN1 (+30%)", key="btn_gerar_rn1_simulada_30")

    if not clicou:
        return

    with st.spinner("Majorando EI/Compras/EF em 30% e recalculando os totais por produto..."):
        resultado = loader.persistir_rn1_simulada_30()

    if "erro" in resultado:
        st.error(f"Erro: {resultado['erro']}")
        return

    st.session_state["rn1_simulada_30_gerado"] = True
    st.rerun()


_COLUNAS_CONSOLIDADO_733 = ["ANO", "DESCR_PROD", "COD_ITEM", "UNID_PROD", "QTDE", "VALOR_TOTAL", "ORIGEM"]
_COLUNA_CHECKBOX_CONSOLIDADO_733 = "Selecionar p/ Fiscalização"


def render_consolidado_origens_733() -> None:
    """Estágio 7.3.3 — Seleção Consolidada de Alvos (2026-08-03,
    Solicitação Técnica): une Entradas/Saídas/Estoque (Estágio 4/5) numa
    única tabela de consulta, pro auditor "cravar" alvos que não têm
    divergência financeira aparente no 7.2/7.3, mas têm volume físico
    (XML) ou estoque estagnado (Bloco H) suspeito. Ver
    loader.gerar_consolidado_origens_733() pro raciocínio de agregação/
    fontes. Chamada por render_pagina_consolidado_733() — botão PRÓPRIO
    no Menu Principal desde 2026-08-03 (pedido do usuário: "separe 7.3.3
    do 7.3.2 criando botão próprio pra ele"); a Solicitação Técnica
    original pedia essa seção logo abaixo do 7.3.2, na mesma página —
    revertido nesta sessão.

    Upsert ADITIVO (loader.salvar_alvos_selecionados_733(), confirmado com
    o usuário via AskUserQuestion): cravar aqui nunca cancela nada que já
    estava ativo em produto_alvo_fiscalizacao (nem do 7.2, nem de uma
    rodada anterior do 7.3.3) — diferente do "💾 Salvar Grupo de Produto
    Alvo" do 7.3.2, que reconcilia a tela inteira (desmarcar cancela).
    Alvo cravado aqui não tem RN1 calculado (DIVERGENCIA/TOTAL_DEBITO/
    TOTAL_CREDITO=0, INFRACAO vazio, OBSERVACAO registra a origem) —
    também confirmado com o usuário, em vez de calcular RN1 na hora.

    Sem limite de linhas carregadas no editor (2026-08-03, pedido do
    usuário — "quando ordenar pelo título, não ficar restrito às 200
    primeiras e sim buscar no todo"): a versão original capava em 200
    linhas após filtro (mesmo padrão do 7.3.2), o que fazia a ordenação
    por clique no cabeçalho da coluna (recurso nativo do
    st.data_editor/glide-data-grid) ordenar só as 200 já carregadas, não
    o total filtrado. Removido o cap — todo `filtrado` vai pro editor,
    já que o grid é virtualizado (só renderiza as linhas visíveis).

    Refinamento 2026-08-13, 1ª rodada (Solicitação Técnica — auditoria
    integrada): fonte unificada em 10px na tabela principal e nas 3
    tabelas de Detalhamento por Origem; Detalhamento só aparece com termo
    de busca preenchido (senão repetiria a tabela principal sem agregar
    valor); Detalhamento ignora o selectbox de Origem de propósito —
    mostra sempre Entradas/Saídas/Estoque juntos pro termo buscado, pra
    achar omissão (comprou mas não vendeu, ou vice-versa) sem trocar o
    filtro repetidamente; ganhou 2 st.metric (Soma Quantidade/Soma Valor
    Total) por origem, calculados com `.sum()` puro (nulo vira 0.0).

    Refinamento 2026-08-13, 2ª rodada (Solicitação Técnica — "painel de
    instrumentos"): Detalhamento por Origem trocou de 3 colunas lado a
    lado pra `st.tabs(["📥 Entradas", "📤 Saídas", "📦 Estoque"])`; fonte
    das grades reduzida de 10px pra 9px (principal e detalhes); KPIs
    miniaturizados via CSS (rótulo 10px, valor 14px, mesmo padrão já usado
    no painel de Matching/BC3 — `.st-key-bc3_kpis`); colunas Qtde/Valor
    Total das tabelas de detalhe deixaram de ser texto BR pré-formatado e
    passaram a usar `column_config.NumberColumn(format="%.2f")`, mesmo
    motivo já documentado no editor principal (ordenação por clique no
    cabeçalho é por STRING quando a coluna é texto).

    Refinamento 2026-08-13, 3ª rodada (usuário questionou a alegação
    repetida de que "o Bloco H não tem valor"): CONFIRMADO como falso pra
    granularidade bruta do H010 (`VL_ITEM`/`VL_UNIT` 100% preenchidos) —
    o que não tinha valor era só a tabela consolidada do Estágio 5
    (`estoque_anual_consolidado`), que passou a carregar VALOR_INICIAL/
    VALOR_FINAL (ver loader.montar_estoque_anual_consolidado()). Valor
    Total do Estoque, aqui e no Detalhamento por Origem, deixou de ser
    NULL/branco e passou a mostrar o valor declarado real (VL_ITEM do
    inventário de fechamento do ano)."""
    st.markdown("**🔍 7.3.3: Seleção Consolidada (Estoque/XML)**")
    st.caption(
        "Une Entradas, Saídas (excluindo autoemissão) e Estoque (Bloco H, só anos já fechados) "
        "numa única tabela — Qtde/Valor Total agregados por Ano+Descrição+Unidade+Origem. Ajuda a "
        "encontrar itens com volume físico ou estoque suspeito que não aparecem no 7.2/7.3 por "
        "falta de divergência financeira. Valor Total do Estoque é o valor declarado (VL_ITEM) do "
        "inventário de fechamento do ano (Bloco H). Cód. Produto mostra "
        "'nc' quando nenhuma origem tinha código vinculado. Alvo cravado aqui não passa pela "
        "régua de divergência do 7.2/7.3 (fica marcado na Observação)."
    )

    if "estagio733_gerado" not in st.session_state:
        st.session_state["estagio733_gerado"] = loader.estagio733_consolidado_ja_gerado()

    if st.session_state["estagio733_gerado"]:
        df_preview, total = loader.consultar_consolidado_origens_733(limite=None)
        st.success(f"✅ {total:,} linha(s) em `estagio733_consolidado`.".replace(",", "."))
        clicou = st.button(
            "Regerar Consolidado (7.3.3)", key="btn_regerar_consolidado_733",
            help="Reprocessa Entradas/Saídas/Estoque do zero.",
        )
    else:
        df_preview = pd.DataFrame(columns=_COLUNAS_CONSOLIDADO_733)
        clicou = st.button("Gerar Consolidado (7.3.3)", key="btn_gerar_consolidado_733")

    if clicou:
        with st.spinner("Unindo Entradas/Saídas/Estoque..."):
            resultado = loader.persistir_consolidado_origens_733()
        if "erro" in resultado:
            st.error(f"Erro: {resultado['erro']}")
            return
        for erro in resultado.get("erros", []):
            st.warning(erro)
        st.session_state["estagio733_gerado"] = True
        st.rerun()

    if df_preview.empty:
        if st.session_state["estagio733_gerado"]:
            st.info("Nenhuma linha encontrada — confira se Entradas/Saídas/Estoque já foram gerados.")
        return

    col_busca, col_ano, col_origem = st.columns(3)
    busca_descricao = col_busca.text_input("Buscar por Descrição", key="filtro_descricao_733")
    col_busca.caption(
        r"Dica: use '\*' como curinga. Ex.: 'mac\*' (inicia com mac), '\*mac' (termina com mac), "
        r"'\*mac\*' (contém mac), '\*mor\*mac\*' (contém mor e mac, em qualquer ordem)."
    )
    anos_disponiveis = sorted(df_preview["ANO"].dropna().unique().tolist())
    ano_selecionado = col_ano.selectbox("Ano", ["Todos"] + anos_disponiveis, key="filtro_ano_733")
    origens_disponiveis = sorted(df_preview["ORIGEM"].dropna().unique().tolist())
    origem_selecionada = col_origem.selectbox(
        "Origem", ["Todas"] + origens_disponiveis, key="filtro_origem_733",
    )

    # `filtrado_base` (busca+ano, sem Origem) alimenta o Detalhamento por
    # Origem abaixo — 2026-08-13, pedido do usuário: o selectbox de Origem
    # não deve limitar as 3 tabelas de detalhe (senão pesquisar um item com
    # Origem="entrada" selecionada esconderia Saídas/Estoque desse mesmo
    # item, o oposto do objetivo de ver as 3 frentes simultaneamente).
    # `filtrado` (busca+ano+origem) continua alimentando só a tabela
    # principal de seleção, que respeita os 3 filtros normalmente.
    filtrado_base = df_preview
    if busca_descricao.strip():
        filtrado_base = filtrado_base[
            filtrado_base["DESCR_PROD"].str.contains(
                _padrao_busca_curinga(busca_descricao.strip()), case=False, na=False,
            )
        ]
    if ano_selecionado != "Todos":
        filtrado_base = filtrado_base[filtrado_base["ANO"] == ano_selecionado]

    filtrado = filtrado_base
    if origem_selecionada != "Todas":
        filtrado = filtrado[filtrado["ORIGEM"] == origem_selecionada]

    st.markdown(f"**{len(filtrado):,} linha(s)** após filtro.".replace(",", "."))
    amostra_raw = filtrado.copy()

    editor_base = amostra_raw[_COLUNAS_CONSOLIDADO_733].copy()
    editor_base.insert(0, _COLUNA_CHECKBOX_CONSOLIDADO_733, False)

    editor_exibicao = editor_base.copy()
    editor_exibicao = editor_exibicao.rename(columns=loader.carregar_dicionario_campos())
    editor_exibicao = editor_exibicao.rename(columns={"ORIGEM": "Origem"})

    colunas_travadas = [c for c in editor_exibicao.columns if c != _COLUNA_CHECKBOX_CONSOLIDADO_733]
    with st.container(key="estagio733_editor_consolidado"):
        st.markdown(
            "<style>.st-key-estagio733_editor_consolidado [data-testid='stDataFrame'] "
            "* { font-size: 9px; }</style>",
            unsafe_allow_html=True,
        )
        editado = st.data_editor(
            editor_exibicao,
            use_container_width=True,
            hide_index=True,
            disabled=colunas_travadas,
            key="editor_consolidado_733",
            column_config={
                # Mantidos NUMÉRICOS de propósito (2026-08-03, achado real:
                # a versão anterior pré-formatava como texto BR — "3.740,88"
                # — pra exibição, e a ordenação por clique no cabeçalho do
                # grid (glide-data-grid) ordenava como STRING, não número:
                # "999,60" ficava acima de "3.740,88" porque "9" > "3"
                # lexicograficamente. NumberColumn não tem opção de milhar
                # "." + decimal "," (mesma limitação já documentada em
                # _formatar_moeda_br), então perde a formatação BR aqui —
                # troca aceita pra ordenação numérica funcionar de verdade.
                "Qtde": st.column_config.NumberColumn(format="%.2f"),
                "Valor Total": st.column_config.NumberColumn(format="%.2f"),
            },
        )

    # Detalhamento por Origem (2026-08-12, tabelas lado a lado; refinado
    # 2026-08-13 — Solicitação Técnica: gate por busca + desvínculo do
    # filtro de Origem + KPIs; refinado de novo 2026-08-13, 2ª rodada —
    # Solicitação Técnica "painel de instrumentos": abas em vez de colunas
    # lado a lado, fonte 9px, KPIs miniaturizados): só renderiza quando há
    # termo de busca por descrição (senão a seção fica igual à tabela
    # principal e não agrega valor pra quem só está navegando/filtrando
    # por Ano). Usa `filtrado_base` (busca+ano, SEM o filtro de Origem) de
    # propósito — o objetivo declarado é o auditor ver as 3 frentes
    # (Entradas/Saídas/Estoque) do item buscado simultaneamente, mesmo com
    # um valor específico selecionado no selectbox de Origem (que só vale
    # pra tabela principal de seleção). Cada aba é sempre a origem fixa do
    # loop (`origem_valor`), não a do selectbox. `st.tabs` de topo, não
    # aninhado em outro `st.tabs` desta página — as 3 abas rodam no mesmo
    # script run do Streamlit (conteúdo das 3 é sempre computado, só a
    # exibição é client-side), por isso não há custo de re-fetch ao trocar
    # de aba. NumberColumn (não mais texto BR pré-formatado) nas colunas
    # Qtde/Valor Total, mesmo motivo já documentado na tabela principal:
    # ordenação por clique no cabeçalho do grid é por STRING quando a
    # coluna é texto, quebrando a ordenação numérica.
    if busca_descricao.strip():
        st.markdown("**Detalhamento por Origem (Entradas / Saídas / Estoque)**")
        st.caption(
            "Ignora o filtro de Origem acima — mostra sempre as 3 origens pro termo "
            "buscado, pra comparar se o item comprado também foi vendido ou consta em estoque."
        )
        aba_entrada, aba_saida, aba_estoque = st.tabs(["📥 Entradas", "📤 Saídas", "📦 Estoque"])
        for aba, origem_valor in (
            (aba_entrada, "entrada"),
            (aba_saida, "saida"),
            (aba_estoque, "estoque"),
        ):
            sub = filtrado_base[filtrado_base["ORIGEM"] == origem_valor]
            with aba:
                chave_kpi = f"estagio733_kpi_{origem_valor}"
                with st.container(key=chave_kpi):
                    st.markdown(
                        f"<style>.st-key-{chave_kpi} [data-testid='stMetricLabel'] "
                        "{ font-size: 10px; } "
                        f".st-key-{chave_kpi} [data-testid='stMetricValue'] "
                        "{ font-size: 14px; }</style>",
                        unsafe_allow_html=True,
                    )
                    col_kpi1, col_kpi2 = st.columns(2)
                    col_kpi1.metric("Soma Quantidade", _formatar_moeda_br(sub["QTDE"].sum()))
                    col_kpi2.metric("Soma Valor Total", _formatar_moeda_br(sub["VALOR_TOTAL"].sum()))
                if sub.empty:
                    st.caption("Nenhum item.")
                    continue
                agrupado = (
                    sub.groupby("DESCR_PROD", as_index=False)[["QTDE", "VALOR_TOTAL"]]
                    .sum(min_count=1)
                    .sort_values("DESCR_PROD")
                )
                linha_total = pd.DataFrame([{
                    "DESCR_PROD": "TOTAL",
                    "QTDE": agrupado["QTDE"].sum(min_count=1),
                    "VALOR_TOTAL": agrupado["VALOR_TOTAL"].sum(min_count=1),
                }])
                exibicao = pd.concat([agrupado, linha_total], ignore_index=True)
                exibicao = exibicao.rename(
                    columns={"DESCR_PROD": "Descrição", "QTDE": "Qtde", "VALOR_TOTAL": "Valor Total"}
                )
                chave = f"estagio733_tabela_{origem_valor}"
                with st.container(key=chave):
                    st.markdown(
                        f"<style>.st-key-{chave} [data-testid='stDataFrame'] "
                        "* { font-size: 9px; }</style>",
                        unsafe_allow_html=True,
                    )
                    st.dataframe(
                        exibicao, use_container_width=True, hide_index=True,
                        column_config={
                            "Qtde": st.column_config.NumberColumn(format="%.2f"),
                            "Valor Total": st.column_config.NumberColumn(format="%.2f"),
                        },
                    )

    if st.button("🎯 Cravar Alvos Selecionados (7.3.3)", key="btn_cravar_alvos_733"):
        marcados = editado[_COLUNA_CHECKBOX_CONSOLIDADO_733].reindex(editor_base.index).fillna(False)
        selecionados = editor_base.loc[marcados.to_numpy()]
        if selecionados.empty:
            st.warning("Nenhuma linha marcada.")
        else:
            resultado = loader.salvar_alvos_selecionados_733(selecionados)
            if "erro" in resultado:
                st.error(f"Erro: {resultado['erro']}")
            else:
                st.success(
                    f"✅ {resultado['total_adicionado']} alvo(s) novo(s) cravado(s), "
                    f"{resultado['total_reativado']} reativado(s)."
                )
                st.rerun()


_COLUNAS_PREVIEW_DIVERGENCIA = [
    "CHV_NFE", "EXCEL_QTD_ITENS", "HUNTER_ENTRADAS_QTD", "ITENS_ENTRADAS_REAIS",
    "ITENS_SAIDAS_REAIS", "ITENS_SITUACAO", "ITENS_ANALISE_CFOP",
    "ITENS_NAO_IDENTIFICADOS", "CASO_AUTOEMISSAO_DUPLICADA",
]


def _texto_periodo_auditoria(periodo: "dict | None") -> str:
    """Trecho de legenda comum às 3 auditorias da AUDITORIA1 (entradas,
    saídas, estoque, 2026-07-18) — informa se a comparação está restrita
    ao Período de Auditoria configurado (`config_auditoria`, EXTRAÇÃO) ou
    mostrando todos os anos presentes nos dados (sem período)."""
    if periodo:
        return f" Restrita ao Período de Auditoria configurado ({periodo['ano_inicial']}-{periodo['ano_final']})."
    return " Nenhum Período de Auditoria configurado — mostrando todos os anos presentes nos dados."


def render_auditoria_divergencia_entradas() -> None:
    """Estudo de diferenças Hunter × Excel de referência (2026-07-13), SEM
    cruzar código de item — ver loader.auditar_divergencia_entradas().
    Diagnóstico pontual pra explicar a origem de uma diferença de volume
    total entre um Excel de outra aplicação do usuário e `estoque_entradas`
    (Estágio 4). Mostra um aviso (não um erro) se a operação não tiver o
    Excel de referência (qualquer `*ENTRADAS*.xlsx` na raiz da operação —
    nome varia por operação, ver loader._localizar_excel_entradas_
    referencia()) — normal pra quem ainda não recebeu esse arquivo. Se o
    arquivo EXISTE mas não pôde ser carregado (dependência ausente —
    achado real 2026-07-16: `openpyxl` faltando no runtime portátil de
    PB/cometa fazia `pd.read_excel()` lançar ImportError —, coluna
    'CHAVE' ausente, arquivo corrompido etc.), mostra st.error() com o
    motivo real em vez do mesmo aviso genérico — não misturar as duas
    situações de novo. Único chamador: render_pagina_
    auditoria1() (Estágio 6, botão "AUDITORIA1" — antes de 2026-07-15
    ficava embutida, sem botão próprio, no fim de
    render_pagina_construcao(), daí o retorno silencioso fazer sentido
    ali; numa página dedicada, silêncio total pareceria página quebrada).
    Seção "Detalhamento de Chaves Ausentes" (2026-07-15): dois botões que
    revelam `resultado['residuo_hunter']`/`['residuo_csv']` — análise
    bidirecional por PRESENÇA/AUSÊNCIA total da chave (complementar ao
    "Investigar Chaves Divergentes" acima, que é por CONTAGEM).

    Escopo do Período de Auditoria (2026-07-18): quando configurado em
    "EXTRAÇÃO", restringe às chaves cujo ano (dígitos 3-4 da CHV_NFE) cai
    dentro do período — ver `loader.auditar_divergencia_entradas()`."""
    resultado = loader.auditar_divergencia_entradas()
    if resultado["erros"]:
        if resultado["erros"] == [loader.MSG_SEM_EXCEL_ENTRADAS_REFERENCIA]:
            st.info(
                "Sem Excel de referência (`*ENTRADAS*.xlsx`) na pasta desta operação — "
                "este estudo só se aplica a quem tiver esse arquivo."
            )
        else:
            st.error(
                "Excel de referência encontrado, mas não foi possível carregá-lo: "
                + " | ".join(resultado["erros"])
            )
        return

    st.divider()
    st.subheader("Auditoria — Divergência de Entradas (Hunter × Excel)")
    resumo = resultado["resumo"]
    st.caption(
        "Compara o Excel de referência (`*ENTRADAS*.xlsx` na pasta da operação) com "
        "estoque_entradas por CHV_NFE + contagem de itens por nota — sem cruzar código de "
        "item. Reconcilia o resíduo checando xml_saidas_real (Estágio 3), nfe_situacao_et/ep "
        "(Notas Não Autorizadas) e nfe_analise_et/ep (CFOPs Não Autorizados), nessa ordem."
        + _texto_periodo_auditoria(resumo.get("periodo"))
    )

    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric("Itens em Entradas Reais", f"{resumo['itens_entradas_reais']:,}".replace(",", "."))
    col2.metric("Itens em Saídas Reais", f"{resumo['itens_saidas_reais']:,}".replace(",", "."))
    col3.metric("Itens Cancelados/Situação", f"{resumo['itens_situacao']:,}".replace(",", "."))
    col4.metric("Itens em Análise CFOP", f"{resumo['itens_analise_cfop']:,}".replace(",", "."))
    col5.metric("Divergência não identificada", f"{resumo['itens_nao_identificados']:,}".replace(",", "."))

    st.caption(
        f"Total Excel: {resumo['total_excel']:,} · Total estoque_entradas: "
        f"{resumo['total_hunter_entradas']:,} ({resumo['itens_hunter_ausentes_no_excel']:,} "
        "item(ns) do Hunter sem chave correspondente no Excel — direção oposta). Da "
        f"divergência não identificada, {resumo['chaves_autoemissao_na_divergencia']} chave(s) "
        "fazem parte do caso conhecido de autoemissão duplicada entre ET/EP (2026-07-05)."
        .replace(",", ".")
    )

    if "mostrar_chaves_divergentes" not in st.session_state:
        st.session_state["mostrar_chaves_divergentes"] = False
    if st.button("Investigar Chaves Divergentes", key="btn_investigar_chaves_divergentes"):
        st.session_state["mostrar_chaves_divergentes"] = True

    if st.session_state["mostrar_chaves_divergentes"]:
        df_div = resultado["chaves_divergentes"]
        st.markdown(
            f"**{len(df_div):,} chave(s) com contagem diferente entre Excel e Hunter**"
            .replace(",", ".")
        )
        if df_div.empty:
            st.info("Nenhuma chave divergente encontrada.")
        else:
            nao_identificado = df_div[df_div["ITENS_NAO_IDENTIFICADOS"] > 0].copy()
            if not nao_identificado.empty:
                # Quebra por ano da CHV_NFE (dígitos 3-4, "AA" da chave de
                # acesso) — achado real na base do geraldo: 100% do resíduo
                # não identificado concentrado em CHV_NFE de 2019, sinal de
                # ausência de XML na origem (1-DOCFISCAIS/nf/), não erro de
                # classificação.
                nao_identificado["ANO_NFE"] = "20" + nao_identificado["CHV_NFE"].str[2:4]
                por_ano = (
                    nao_identificado.groupby("ANO_NFE")["ITENS_NAO_IDENTIFICADOS"]
                    .sum().sort_index()
                )
                st.markdown("**Divergência não identificada, por ano da CHV_NFE:**")
                st.dataframe(por_ano.rename("Itens").to_frame(), use_container_width=True)
            st.dataframe(df_div[_COLUNAS_PREVIEW_DIVERGENCIA], use_container_width=True)

    st.divider()
    st.markdown("**Detalhamento de Chaves Ausentes**")
    st.caption(
        "Visão bidirecional por chave (diferente de 'Investigar Chaves Divergentes' acima, "
        "que reconcilia por CONTAGEM dentro de cada chave presente no Excel): aqui é presença/ "
        "ausência TOTAL da chave num lado ou no outro."
    )

    residuo_hunter = resultado["residuo_hunter"]
    residuo_csv = resultado["residuo_csv"]
    n_chaves_hunter = residuo_hunter["CHV_NFE"].nunique() if not residuo_hunter.empty else 0
    n_chaves_csv = residuo_csv["CHV_NFE"].nunique() if not residuo_csv.empty else 0

    if "mostrar_residuo_hunter" not in st.session_state:
        st.session_state["mostrar_residuo_hunter"] = False
    if "mostrar_residuo_csv" not in st.session_state:
        st.session_state["mostrar_residuo_csv"] = False

    col_res1, col_res2 = st.columns(2)
    if col_res1.button(
        f"🔍 Chaves do Hunter ausentes no CSV ({n_chaves_hunter:,} chave(s) única(s))".replace(",", "."),
        key="btn_residuo_hunter",
    ):
        st.session_state["mostrar_residuo_hunter"] = True
    if col_res2.button(
        f"📂 Chaves do CSV ausentes no Hunter ({n_chaves_csv:,} chave(s) única(s))".replace(",", "."),
        key="btn_residuo_csv",
    ):
        st.session_state["mostrar_residuo_csv"] = True

    if st.session_state["mostrar_residuo_hunter"]:
        st.markdown("**Resíduo Hunter** — no XML, mas ausente de todas as linhas do Excel:")
        if residuo_hunter.empty:
            st.info("Nenhuma chave do Hunter ausente no Excel.")
        else:
            st.dataframe(residuo_hunter, use_container_width=True)

    if st.session_state["mostrar_residuo_csv"]:
        st.markdown(
            "**Resíduo CSV** — no Excel, mas ausente de Entradas/Saídas/Situação/Análise do Hunter "
            "(candidatas a XML nunca extraído de `1-DOCFISCAIS/nf/`):"
        )
        if residuo_csv.empty:
            st.info("Nenhuma chave do Excel totalmente ausente do Hunter.")
        else:
            st.dataframe(residuo_csv, use_container_width=True)


_COLUNAS_PREVIEW_DIVERGENCIA_SAIDAS = [
    "CHV_NFE", "EXCEL_QTD_ITENS", "HUNTER_SAIDAS_QTD", "ITENS_SAIDAS_REAIS",
    "ITENS_ENTRADAS_REAIS", "ITENS_SITUACAO", "ITENS_ANALISE_CFOP",
    "ITENS_NAO_IDENTIFICADOS", "CASO_AUTOEMISSAO_DUPLICADA",
]


def render_auditoria_divergencia_saidas() -> None:
    """Espelho de render_auditoria_divergencia_entradas() (2026-07-17) pro
    lado saídas — ver loader.auditar_divergencia_saidas(). Mesma estrutura
    (KPIs, "Investigar Chaves Divergentes", "Detalhamento de Chaves
    Ausentes"), com HUNTER_SAIDAS_QTD como métrica principal em vez de
    HUNTER_ENTRADAS_QTD e chaves de session_state/widget próprias
    (sufixo `_saidas`) — sem isso, os botões desta seção e os de
    render_auditoria_divergencia_entradas() colidiriam (mesmo
    `key=` do Streamlit) e compartilhariam estado indevidamente.

    Escopo do Período de Auditoria (2026-07-18): mesmo filtro de
    render_auditoria_divergencia_entradas() — ver
    loader.auditar_divergencia_saidas()."""
    resultado = loader.auditar_divergencia_saidas()
    if resultado["erros"]:
        if resultado["erros"] == [loader.MSG_SEM_EXCEL_SAIDAS_REFERENCIA]:
            st.info(
                "Sem Excel de referência (`*SAIDAS*.xlsx`) na pasta desta operação — "
                "este estudo só se aplica a quem tiver esse arquivo."
            )
        else:
            st.error(
                "Excel de referência encontrado, mas não foi possível carregá-lo: "
                + " | ".join(resultado["erros"])
            )
        return

    st.divider()
    st.subheader("Auditoria — Divergência de Saídas (Hunter × Excel)")
    resumo = resultado["resumo"]
    st.caption(
        "Compara o Excel de referência (`*SAIDAS*.xlsx` na pasta da operação) com "
        "estoque_saidas por CHV_NFE + contagem de itens por nota — sem cruzar código de "
        "item. Reconcilia o resíduo checando xml_entradas_real (Estágio 3), nfe_situacao_et/ep "
        "(Notas Não Autorizadas) e nfe_analise_et/ep (CFOPs Não Autorizados), nessa ordem."
        + _texto_periodo_auditoria(resumo.get("periodo"))
    )
    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric("Itens em Saídas Reais", f"{resumo['itens_saidas_reais']:,}".replace(",", "."))
    col2.metric("Itens em Entradas Reais", f"{resumo['itens_entradas_reais']:,}".replace(",", "."))
    col3.metric("Itens Cancelados/Situação", f"{resumo['itens_situacao']:,}".replace(",", "."))
    col4.metric("Itens em Análise CFOP", f"{resumo['itens_analise_cfop']:,}".replace(",", "."))
    col5.metric("Divergência não identificada", f"{resumo['itens_nao_identificados']:,}".replace(",", "."))

    st.caption(
        f"Total Excel: {resumo['total_excel']:,} · Total estoque_saidas: "
        f"{resumo['total_hunter_saidas']:,} ({resumo['itens_hunter_ausentes_no_excel']:,} "
        "item(ns) do Hunter sem chave correspondente no Excel — direção oposta). Da "
        f"divergência não identificada, {resumo['chaves_autoemissao_na_divergencia']} chave(s) "
        "fazem parte do caso conhecido de autoemissão duplicada entre ET/EP (2026-07-05)."
        .replace(",", ".")
    )

    if "mostrar_chaves_divergentes_saidas" not in st.session_state:
        st.session_state["mostrar_chaves_divergentes_saidas"] = False
    if st.button("Investigar Chaves Divergentes", key="btn_investigar_chaves_divergentes_saidas"):
        st.session_state["mostrar_chaves_divergentes_saidas"] = True

    if st.session_state["mostrar_chaves_divergentes_saidas"]:
        df_div = resultado["chaves_divergentes"]
        st.markdown(
            f"**{len(df_div):,} chave(s) com contagem diferente entre Excel e Hunter**"
            .replace(",", ".")
        )
        if df_div.empty:
            st.info("Nenhuma chave divergente encontrada.")
        else:
            nao_identificado = df_div[df_div["ITENS_NAO_IDENTIFICADOS"] > 0].copy()
            if not nao_identificado.empty:
                nao_identificado["ANO_NFE"] = "20" + nao_identificado["CHV_NFE"].str[2:4]
                por_ano = (
                    nao_identificado.groupby("ANO_NFE")["ITENS_NAO_IDENTIFICADOS"]
                    .sum().sort_index()
                )
                st.markdown("**Divergência não identificada, por ano da CHV_NFE:**")
                st.dataframe(por_ano.rename("Itens").to_frame(), use_container_width=True)
            st.dataframe(df_div[_COLUNAS_PREVIEW_DIVERGENCIA_SAIDAS], use_container_width=True)

    st.divider()
    st.markdown("**Detalhamento de Chaves Ausentes**")
    st.caption(
        "Visão bidirecional por chave (diferente de 'Investigar Chaves Divergentes' acima, "
        "que reconcilia por CONTAGEM dentro de cada chave presente no Excel): aqui é presença/ "
        "ausência TOTAL da chave num lado ou no outro."
    )

    residuo_hunter = resultado["residuo_hunter"]
    residuo_csv = resultado["residuo_csv"]
    n_chaves_hunter = residuo_hunter["CHV_NFE"].nunique() if not residuo_hunter.empty else 0
    n_chaves_csv = residuo_csv["CHV_NFE"].nunique() if not residuo_csv.empty else 0

    if "mostrar_residuo_hunter_saidas" not in st.session_state:
        st.session_state["mostrar_residuo_hunter_saidas"] = False
    if "mostrar_residuo_csv_saidas" not in st.session_state:
        st.session_state["mostrar_residuo_csv_saidas"] = False

    col_res1, col_res2 = st.columns(2)
    if col_res1.button(
        f"🔍 Chaves do Hunter ausentes no CSV ({n_chaves_hunter:,} chave(s) única(s))".replace(",", "."),
        key="btn_residuo_hunter_saidas",
    ):
        st.session_state["mostrar_residuo_hunter_saidas"] = True
    if col_res2.button(
        f"📂 Chaves do CSV ausentes no Hunter ({n_chaves_csv:,} chave(s) única(s))".replace(",", "."),
        key="btn_residuo_csv_saidas",
    ):
        st.session_state["mostrar_residuo_csv_saidas"] = True

    if st.session_state["mostrar_residuo_hunter_saidas"]:
        st.markdown("**Resíduo Hunter** — no XML, mas ausente de todas as linhas do Excel:")
        if residuo_hunter.empty:
            st.info("Nenhuma chave do Hunter ausente no Excel.")
        else:
            st.dataframe(residuo_hunter, use_container_width=True)

    if st.session_state["mostrar_residuo_csv_saidas"]:
        st.markdown(
            "**Resíduo CSV** — no Excel, mas ausente de Entradas/Saídas/Situação/Análise do Hunter "
            "(candidatas a XML nunca extraído de `1-DOCFISCAIS/nf/`):"
        )
        if residuo_csv.empty:
            st.info("Nenhuma chave do Excel totalmente ausente do Hunter.")
        else:
            st.dataframe(residuo_csv, use_container_width=True)


_COLUNAS_PREVIEW_DIVERGENCIA_ESTOQUE = [
    "COD_ITEM", "ANO_REFERENCIA", "EXCEL_DESCR_ITEM", "EXCEL_QTDE", "QUANTIDADE", "DIF",
]


def render_auditoria_divergencia_estoque() -> None:
    """Auditoria de estoque (2026-07-17, revisada no mesmo dia) — ver
    loader.auditar_divergencia_estoque(). Diferente de render_auditoria_
    divergencia_entradas/saidas() (que cruzam por CHV_NFE + contagem de
    itens, sem valor e com waterfall de reconciliação em várias tabelas),
    aqui a comparação é direta por QUANTIDADE, uma linha por declaração
    de inventário — MESMO modelo de linha do Excel de referência (usuário
    pediu explicitamente pra comparar "no modelo do CSV" em vez do
    formato item×ano expandido do Estágio 5) — só uma tabela de
    divergência, sem seção separada de "Resíduo" (a ausência de um lado
    já aparece como quantidade 0 dentro da própria tabela). Mostra um
    aviso (não erro) se a operação não tiver o Excel de referência nem
    nenhum SPED de Bloco H — normal em ambos os casos.

    Escopo do Período de Auditoria (2026-07-18): quando configurado em
    "EXTRAÇÃO" (`config_auditoria`), a comparação é restrita a
    `ANO_REFERENCIA` entre `ano_inicial` e `ano_final` — evita contar como
    divergência anos fora do período fiscalizado (achado real: geraldo
    tinha declarações de 2019/2020 fora do período 2021-2024 configurado,
    que antes entravam na comparação sem necessidade)."""
    resultado = loader.auditar_divergencia_estoque()
    if resultado["erros"]:
        if resultado["erros"] == [loader.MSG_SEM_EXCEL_ESTOQUE_REFERENCIA]:
            st.info(
                "Sem Excel de referência (`*ESTOQUE*.xlsx`) na pasta desta operação — "
                "este estudo só se aplica a quem tiver esse arquivo."
            )
        elif "Bloco H" in " ".join(resultado["erros"]):
            st.info(
                "Nenhuma declaração de inventário (Bloco H — H005/H010) encontrada nos SPED "
                "desta operação."
            )
        else:
            st.error(
                "Excel de referência encontrado, mas não foi possível carregá-lo: "
                + " | ".join(resultado["erros"])
            )
        return

    st.divider()
    st.subheader("Auditoria — Divergência de Estoque (Hunter × Excel)")
    resumo = resultado["resumo"]
    st.caption(
        "Compara o Excel de referência (`*ESTOQUE*.xlsx` na pasta da operação) com as "
        "declarações de inventário cruas do Bloco H (H010), por (COD_ITEM, ANO_REFERENCIA) — "
        "uma linha por declaração física, mesmo modelo do Excel, sem passar pelo formato "
        "item×ano expandido do Estágio 5." + _texto_periodo_auditoria(resumo.get("periodo"))
    )

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Pares Item×Ano", f"{resumo['total_pares']:,}".replace(",", "."))
    col2.metric("Divergentes", f"{resumo['pares_divergentes']:,}".replace(",", "."))
    col3.metric("Só no Excel", f"{resumo['itens_so_excel']:,}".replace(",", "."))
    col4.metric("Só no Hunter", f"{resumo['itens_so_hunter']:,}".replace(",", "."))

    if "mostrar_divergentes_estoque" not in st.session_state:
        st.session_state["mostrar_divergentes_estoque"] = False
    if st.button("Investigar Itens Divergentes", key="btn_investigar_divergentes_estoque"):
        st.session_state["mostrar_divergentes_estoque"] = True

    if st.session_state["mostrar_divergentes_estoque"]:
        df_div = resultado["divergentes"]
        st.markdown(
            f"**{len(df_div):,} par(es) COD_ITEM×ANO com quantidade divergente**"
            .replace(",", ".")
        )
        if df_div.empty:
            st.info("Nenhum item divergente encontrado.")
        else:
            st.dataframe(df_div[_COLUNAS_PREVIEW_DIVERGENCIA_ESTOQUE], use_container_width=True)


# ── Estágio 6 — VAMOS ORGANIZAR (Menu de Navegação) ─────────────────────────
# Reorganiza a tela única (todos os painéis empilhados) em 4 grupos
# navegáveis, controlados por st.session_state["pagina_ativa"]
# (None -> menu; "extracao"; "matching"; "segregados"; "construcao"). Não
# cria nem apaga nenhuma tabela do DuckDB — é só uma reorganização de UI
# sobre os painéis que já existiam; os dados carregados sobrevivem à troca
# de página porque vivem no DuckDB, não em session_state.
# "Segregados" (2026-07-14) foi promovido a botão próprio, separado de
# "Construção": são dados que a Etapa 1 desviou do cruzamento principal de
# propósito (CFOPs Não Autorizados, Notas Não Autorizadas — nomes de
# exibição escolhidos pelo usuário; ver render_painel_analise()) — nunca
# entram no cômputo do Matching/cruzamento, então misturá-los com os
# painéis que mostram RESULTADO de cruzamento (BC3, Fluxos Físicos, Estoque
# Anual) confundia o que é o quê.
# "Matching (BC3)" (2026-07-14, mesmo dia) também ganhou botão próprio,
# posicionado logo após "Extração" — é o motor central que viabiliza os
# estágios seguintes (Fluxos Físicos, Cronologia), então o usuário pediu
# destaque equivalente ao de "Extração", à frente de "Segregados" e do
# 4º botão (rotulado "TABELAS ENTRADAS / SAÍDAS / ESTOQUES" desde
# 2026-07-14 — mesmo `pagina_ativa="construcao"`/`render_pagina_construcao()`
# de antes, só o texto do botão mudou, pra descrever o conteúdo real do
# painel — Fluxos Físicos = Entradas/Saídas, Estoque Anual = Estoques —
# em vez do rótulo genérico "Painéis em Construção").
# "AUDITORIA1: COMPARAÇÃO ENTRADAS-SAÍDAS-ESTOQUES" (2026-07-15) ganhou
# botão de 5º nível, posicionado logo após "TABELAS ENTRADAS / SAÍDAS /
# ESTOQUES" — ponto de acesso formal e nomeado pro que antes era
# render_auditoria_divergencia_entradas() rodando sem botão próprio, no
# fim de render_pagina_construcao(). A lógica em si (loader.auditar_
# divergencia_entradas(): estoque_entradas × Excel de referência, por
# CHV_NFE + contagem de itens, sem cruzar código de produto) já existia
# desde 2026-07-13 e não mudou — só a navegação.

def render_menu_principal() -> None:
    """Menu principal (Estágio 6): 8 botões despacham para
    render_pagina_extracao()/render_pagina_matching()/
    render_pagina_segregados()/render_pagina_construcao()/
    render_pagina_auditoria1()/render_pagina_descricao_relevante()
    (Estágio 7.1)/render_pagina_cruzamento_valor() (Estágio 7.2,
    2026-07-18)/render_pagina_cruzamento_produto() (Estágio 7.2.1,
    2026-07-19 — condensação do 7.2 por Descrição Relevante)/
    render_pagina_rn1_fisica() (Estágio 7.3, 2026-07-20 — mesma fórmula
    do 7.2 agregada por Descrição Relevante, mantendo o Ano)/
    render_pagina_rn1_produto() (Estágio 7.3.1, 2026-07-20 — condensação
    do 7.3 por Descrição Relevante, somando todos os anos)/
    render_pagina_rn1_simulada_30() (Estágio 7.3.2, 2026-07-22 — majora
    EI/Compras/EF do 7.3.1 em 30%, Vendas como âncora real)/
    render_pagina_estagio_8() (Estágio 8, 2026-07-23 — Resumo de
    Entradas/Saídas/Estoques: visão detalhada + agrupada de estoque_
    entradas/estoque_saidas/estoque_anual_consolidado pra conferir
    qualidade do Matching)/render_pagina_estagio_9() (Estágio 9,
    2026-07-24 — Curadoria de Fator Multiplicador: saneamento em massa
    de casos onde a unidade de comercialização do fornecedor diverge da
    unidade de estoque da auditada). 2ª linha própria de botões a
    partir do Estágio 8 (2026-07-23) — a 1ª linha (11 botões) já estava
    cheia."""
    st.subheader("Menu Principal")
    # Destaque cinza nos botões 7.2/7.2.1/7.3/7.3.1 (2026-07-23, pedido do
    # usuário) — mesmo padrão de CSS via key (".st-key-<key>") já usado em
    # containers/tabelas de alta densidade no resto do app; aqui aplicado
    # ao próprio <button>, com !important pra sobrepor o tema padrão do
    # Streamlit. Cor semitransparente (não sólida) pra continuar legível
    # tanto no tema claro quanto no escuro.
    st.markdown(
        "<style>"
        + "".join(
            f".st-key-{chave} button {{ background-color: rgba(128, 128, 128, 0.35) !important; }}"
            for chave in (
                "btn_menu_cruzamento_valor", "btn_menu_cruzamento_produto",
                "btn_menu_rn1_fisica", "btn_menu_rn1_produto",
            )
        )
        + "</style>",
        unsafe_allow_html=True,
    )
    col1, col2, col3, col4, col5, col6, col7, col8, col9, col10, col11 = st.columns(11)
    if col1.button("🛠️ 1: PROCEDIMENTOS INICIAIS", key="btn_menu_extracao", use_container_width=True):
        st.session_state["pagina_ativa"] = "extracao"
        st.rerun()
    if col2.button("🧩 MATCHING (BC3)", key="btn_menu_matching", use_container_width=True):
        st.session_state["pagina_ativa"] = "matching"
        st.rerun()
    if col3.button("🔀 SEGREGADOS", key="btn_menu_segregados", use_container_width=True):
        st.session_state["pagina_ativa"] = "segregados"
        st.rerun()
    if col4.button("📊 TABELAS ENTRADAS / SAÍDAS / ESTOQUES", key="btn_menu_construcao", use_container_width=True):
        st.session_state["pagina_ativa"] = "construcao"
        st.rerun()
    if col5.button(
        "📑 AUDITORIA1: COMPARAÇÃO ENTRADAS-SAÍDAS-ESTOQUES",
        key="btn_menu_auditoria1", use_container_width=True,
    ):
        st.session_state["pagina_ativa"] = "auditoria1"
        st.rerun()
    if col6.button("🏷️ DESCRIÇÃO RELEVANTE", key="btn_menu_descricao_relevante", use_container_width=True):
        st.session_state["pagina_ativa"] = "descricao_relevante"
        st.rerun()
    if col7.button("📉 7.2: CRUZAMENTO POR VALOR", key="btn_menu_cruzamento_valor", use_container_width=True):
        st.session_state["pagina_ativa"] = "cruzamento_valor"
        st.rerun()
    if col8.button("📊 7.2.1: CRUZAMENTO POR PRODUTO", key="btn_menu_cruzamento_produto", use_container_width=True):
        st.session_state["pagina_ativa"] = "cruzamento_produto"
        st.rerun()
    if col9.button("🔥 7.3: RN1 — MOVIMENTAÇÃO FÍSICA (XML)", key="btn_menu_rn1_fisica", use_container_width=True):
        st.session_state["pagina_ativa"] = "rn1_fisica"
        st.rerun()
    if col10.button("📊 7.3.1: RN1 POR PRODUTO", key="btn_menu_rn1_produto", use_container_width=True):
        st.session_state["pagina_ativa"] = "rn1_produto"
        st.rerun()
    if col11.button("📈 7.3.2: SIMULAÇÃO RN1 (+30%)", key="btn_menu_rn1_simulada_30", use_container_width=True):
        st.session_state["pagina_ativa"] = "rn1_simulada_30"
        st.rerun()

    # 2ª linha do menu — começa no Estágio 8 (2026-07-23, pedido do usuário:
    # "inicie com o 8 uma nova linha de botões"). 12 colunas ficavam
    # espremidas numa linha só; a 2ª linha também dá espaço pros próximos
    # estágios sem precisar espremer mais a 1ª. "7.3.3: Seleção Consolidada"
    # entrou aqui em 2026-08-03 (ganhou botão próprio, separado do 7.3.2 —
    # pedido do usuário) em vez da 1ª linha (já tinha 11 colunas).
    # "11: CONSOLIDADO GERAL (RN1)" entrou em 2026-08-06 (Solicitação
    # Técnica "CONSOLIDADO DO CRUZAMENTO FINAL"). "12: RELATÓRIOS" entrou
    # em 2026-08-07 (Solicitação Técnica "MÓDULO DE RELATÓRIOS FINAIS").
    (
        col_consolidado_733, col_estagio8, col_estagio9, col_produtos_alvo_salvos,
        col_consolidado_11, col_relatorios,
    ) = st.columns(6)
    if col_consolidado_733.button(
        "🔍 7.3.3: SELEÇÃO CONSOLIDADA (ESTOQUE/XML)",
        key="btn_menu_consolidado_733", use_container_width=True,
    ):
        st.session_state["pagina_ativa"] = "consolidado_733"
        st.rerun()
    if col_estagio8.button(
        "📋 ESTÁGIO 8: RESUMO DE ENTRADAS / SAÍDAS / ESTOQUES",
        key="btn_menu_estagio_8", use_container_width=True,
    ):
        st.session_state["pagina_ativa"] = "estagio_8"
        st.rerun()
    if col_estagio9.button(
        "⚖️ ESTÁGIO 9: FATOR MULTIPLICADOR (ENTRADAS)",
        key="btn_menu_estagio_9", use_container_width=True,
    ):
        st.session_state["pagina_ativa"] = "estagio_9"
        st.rerun()
    if col_produtos_alvo_salvos.button(
        "🎯 ESTÁGIO 10 - PRODUTOS ALVOS SALVOS", key="btn_menu_produtos_alvo_salvos", use_container_width=True,
    ):
        st.session_state["pagina_ativa"] = "produtos_alvo_salvos"
        st.rerun()
    if col_consolidado_11.button(
        "📊 11: CONSOLIDADO GERAL (RN1)", key="btn_menu_consolidado_11", use_container_width=True,
    ):
        st.session_state["pagina_ativa"] = "consolidado_11"
        st.rerun()
    if col_relatorios.button(
        "📄 12: RELATÓRIOS", key="btn_menu_relatorios", use_container_width=True,
    ):
        st.session_state["pagina_ativa"] = "relatorios"
        st.rerun()


def _botao_voltar_menu() -> None:
    """Botão fixo no topo dos painéis Extração/Construção — volta pro Menu
    Principal. Só mexe em st.session_state["pagina_ativa"], nunca em
    dados_carregados nem em tabela nenhuma do DuckDB."""
    if st.button("⬅️ Voltar ao Menu Principal", key="btn_voltar_menu"):
        st.session_state["pagina_ativa"] = None
        st.rerun()
    st.divider()


def _render_resultado_matching_inicial() -> None:
    """Painel de KPIs do Matching (BC3) dentro de "🛠️ 1: PROCEDIMENTOS
    INICIAIS" (Solicitação Técnica 2026-08-15) — mesmo formato visual de
    render_bc3() (Estágio 2: 2 linhas de 7 st.metric, CSS escopado pra
    fonte reduzida), mas com PORCENTAGEM sobre o total real da BC2
    (loader.consultar_total_bc2()) embutida em cada métrica via
    `delta_color="off"` (mostra o valor cinza, sem seta verde/vermelha —
    aqui é só um percentual, não uma variação). loader.consultar_totais_
    bc3() continua devolvendo só contagens brutas, sem alteração — não
    quebra render_bc3(), que já consome essa função hoje; o cálculo de %
    fica só aqui, local à nova tela.

    Só renderiza se bc3_ja_gerada() — cobre tanto o fluxo automático
    (render_carga_operacao() já gerou a BC3 na mesma carga) quanto o caso
    de o auditor ter gerado manualmente antes em "🧩 MATCHING (BC3)" e só
    depois ter voltado pra esta tela."""
    if "bc3_gerada" not in st.session_state:
        st.session_state["bc3_gerada"] = loader.bc3_ja_gerada()
    if not st.session_state["bc3_gerada"]:
        return

    st.markdown("### 🧩 Resultado do Matching Inicial (BC3)")
    totais = loader.consultar_totais_bc3()
    total_bc2 = loader.consultar_total_bc2()
    total_casados = (
        totais["D1"] + totais["D2"] + totais["A1"] + totais["A2"]
        + totais["A3"] + totais["A4"] + totais["A5"] + totais["D3"]
        + totais["D4"] + totais["D5"] + totais["D6"]
    )
    taxa_match = (total_casados / total_bc2 * 100) if total_bc2 else 0.0

    def _valor(tipo: str) -> str:
        return f"{totais[tipo]:,}".replace(",", ".")

    def _pct(tipo: str) -> str:
        if not total_bc2:
            return "0,0% da BC2"
        return f"{(totais[tipo] / total_bc2 * 100):.1f}% da BC2".replace(".", ",")

    st.markdown(
        "<style>"
        ".st-key-procedimentos_iniciais_kpis [data-testid='stMetricValue'] { font-size: 1.1rem; }"
        ".st-key-procedimentos_iniciais_kpis [data-testid='stMetricLabel'] { font-size: 0.75rem; }"
        ".st-key-procedimentos_iniciais_kpis [data-testid='stMetricDelta'] { font-size: 0.7rem; }"
        "</style>",
        unsafe_allow_html=True,
    )
    with st.container(key="procedimentos_iniciais_kpis"):
        col1, col2, col3, col4, col5, col6, col7 = st.columns(7)
        col1.metric("Matches D1", _valor("D1"), _pct("D1"), delta_color="off")
        col2.metric("Matches D2", _valor("D2"), _pct("D2"), delta_color="off")
        col3.metric("Matches A1", _valor("A1"), _pct("A1"), delta_color="off")
        col4.metric("Matches A2", _valor("A2"), _pct("A2"), delta_color="off")
        col5.metric("Matches A3", _valor("A3"), _pct("A3"), delta_color="off")
        col6.metric("Matches A4", _valor("A4"), _pct("A4"), delta_color="off")
        col7.metric("Matches A5", _valor("A5"), _pct("A5"), delta_color="off")

        col8, col9, col10, col11, col12, col13, col14 = st.columns(7)
        col8.metric("Matches D3", _valor("D3"), _pct("D3"), delta_color="off")
        col9.metric("Matches D4", _valor("D4"), _pct("D4"), delta_color="off")
        col10.metric("Matches D5", _valor("D5"), _pct("D5"), delta_color="off")
        col11.metric("Matches D6", _valor("D6"), _pct("D6"), delta_color="off")
        col12.metric("Não Declarado (ND)", _valor("ND"), _pct("ND"), delta_color="off")
        col13.metric("Sem Match (NM)", _valor("NM"), _pct("NM"), delta_color="off")
        col14.metric("Taxa de Match", f"{taxa_match:.1f}%".replace(".", ","))

    st.caption(
        f"{total_bc2:,} item(ns) na BC2 (base do Matching) — percentuais calculados sobre esse "
        "total. Uma taxa alta de \"Não Declarado (ND)\" é sinal imediato de risco de omissão de "
        'compras. Regerar manualmente em "🧩 MATCHING (BC3)" se precisar.'.replace(",", ".")
    )


def render_pagina_extracao() -> None:
    """Painel '🛠️ 1: PROCEDIMENTOS INICIAIS' (Solicitação Técnica
    2026-08-15 "PAINEL 1"; antes chamado só de "Extração", Estágio 6) —
    ponto de entrada oficial de qualquer nova auditoria: Configuração de
    Período de Auditoria, Equipe de Fiscalização, Carga de XML/SPED (com
    os alertas de cobertura e de Ancoragem de Estoque já embutidos em
    render_carga_operacao()), Entidade Auditada e, por fim, o Resultado
    do Matching Inicial (BC3) — que agora roda AUTOMATICAMENTE ao final
    de toda carga bem-sucedida (ver render_carga_operacao()), sem
    precisar navegar até "🧩 MATCHING (BC3)" e clicar em "Gerar" à parte.
    O painel de Matching (Estágio 2) continua existindo separado, pro
    auditor regerar manualmente se precisar (ex.: depois de corrigir
    algo na BC1/BC2) — esta tela só ganhou a exibição automática, não
    substituiu a manual."""
    _botao_voltar_menu()
    render_configuracao_periodo()
    st.divider()
    render_equipe_auditoria()
    st.divider()
    render_carga_operacao()
    if st.session_state.get("dados_carregados"):
        st.divider()
        render_entidade_auditada()
        if "bc3_gerada" not in st.session_state:
            st.session_state["bc3_gerada"] = loader.bc3_ja_gerada()
        if st.session_state["bc3_gerada"]:
            st.divider()
            _render_resultado_matching_inicial()


def render_pagina_matching() -> None:
    """Painel 'Matching (BC3)' (Estágio 6), próprio desde 2026-07-14: mostra
    só render_bc3() (Estágio 2) — motor de 11 níveis (D1-D6/A1-A5) que casa
    o produto do fornecedor (XML) com o código interno da auditada (SPED).
    render_bc3() traz consigo, num st.expander no topo, a BC1 (Entradas de
    Terceiros) — subcomponente do Matching desde 2026-07-14, não painel
    independente. Promovido a botão de primeiro nível (logo após
    "Extração") porque é o que "completa" as notas de entrada e viabiliza
    os estágios seguintes (Fluxos Físicos, Cronologia) — tratamento
    equivalente ao que "Segregados" já tinha ganhado no mesmo dia. Exige
    dados_carregados."""
    _botao_voltar_menu()
    if not st.session_state.get("dados_carregados"):
        st.info('Carregue os dados primeiro em "🛠️ 1: PROCEDIMENTOS INICIAIS".')
        return
    render_bc3()


def render_pagina_segregados() -> None:
    """Painel 'Segregados' (Estágio 6), próprio desde 2026-07-14: mostra só
    render_painel_analise() — CFOPs Não Autorizados (com o botão "CFOPS
    SEGREGADOS") e Notas Não Autorizadas. Isolado de "Construção" porque
    esses dados, por definição, NÃO entram no cômputo do cruzamento/Matching
    (Estágio 1 os desvia de propósito de nfe_entradas/nfe_saidas) — não são
    resultado de cruzamento, então não pertencem ao mesmo grupo de BC3/
    Fluxos Físicos/Estoque Anual. Exige dados_carregados."""
    _botao_voltar_menu()
    if not st.session_state.get("dados_carregados"):
        st.info('Carregue os dados primeiro em "🛠️ 1: PROCEDIMENTOS INICIAIS".')
        return
    render_painel_analise()


def render_pagina_construcao() -> None:
    """Painel 'TABELAS ENTRADAS / SAÍDAS / ESTOQUES' (Estágio 6; nome de
    exibição desde 2026-07-14 — antes "Painéis em Construção", mesma
    `pagina_ativa="construcao"`/função por baixo): agrupa as visualizações
    dos Estágios 3/4/5 — Fluxos Físicos (Estágio 3, prévia sob demanda de
    xml_entradas_real/xml_saidas_real, sem persistir), Entradas e Saídas
    Enriquecidas (Estágio 4, primeiro painel deste estágio na UI desde
    2026-07-14 — persiste estoque_entradas/estoque_saidas com os dados da
    bc3 + DATA_ELEITA/ANO_ELEITO) e Tabela de Estoque (Estágio 5,
    Estoques). Matching (BC3, Estágio 2) saiu daqui em 2026-07-14 (mesmo
    dia da promoção de "Segregados") — ver render_pagina_matching(),
    ganhou botão de primeiro nível próprio. BC1 (Entradas de Terceiros)
    também saiu daqui no mesmo dia — passou a viver dentro de um
    `st.expander` em render_bc3() (subcomponente do Matching, não painel
    independente), ver render_pagina_matching(). Registros Segregados
    (CFOPs Não Autorizados/Notas Não Autorizadas) saíram daqui em
    2026-07-14 — ver render_pagina_segregados(), são dados que não entram
    no cômputo do cruzamento. Auditoria de Divergência de Entradas saiu
    daqui em 2026-07-15 — ver render_pagina_auditoria1(), ganhou botão de
    5º nível próprio ("AUDITORIA1"). Exige dados_carregados — sem carga
    feita, não há nada pra mostrar (orienta o usuário a ir em "EXTRAÇÃO"
    primeiro)."""
    _botao_voltar_menu()
    if not st.session_state.get("dados_carregados"):
        st.info('Carregue os dados primeiro em "🛠️ 1: PROCEDIMENTOS INICIAIS".')
        return
    render_fluxos_fisicos()
    st.divider()
    render_estoque_entradas_saidas()
    st.divider()
    render_estoque_anual()


def render_pagina_auditoria1() -> None:
    """Painel 'AUDITORIA1: COMPARAÇÃO ENTRADAS-SAÍDAS-ESTOQUES' (Estágio 6,
    próprio desde 2026-07-15): ponto de acesso formal e nomeado pra
    render_auditoria_divergencia_entradas() — antes rodava sem botão
    próprio, no fim de render_pagina_construcao(). Não muda nenhuma lógica
    de negócio: continua o mesmo estudo Hunter (estoque_entradas, Estágio
    4) × Excel de referência ('*ENTRADAS*.xlsx' na pasta da
    operação), cruzando só por CHV_NFE + contagem de itens (nunca por
    código de produto) — ver loader.auditar_divergencia_entradas(). Fica
    invisível (só a mensagem de "carregue os dados") se a operação não
    tiver o Excel de referência (normal pra quem não é a geraldo). Exige
    dados_carregados.

    2026-07-17: ganhou o espelho render_auditoria_divergencia_saidas()
    logo abaixo — "estenda a auditoria para as saídas", pedido do usuário
    depois de fechar a auditoria de entradas nas 3 operações reais. Cada
    painel aparece (ou não) de forma independente, conforme a operação
    tiver o respectivo Excel de referência (`*ENTRADAS*`/`*SAIDAS*.xlsx`).

    2026-07-17 (mesmo dia): ganhou o botão "Regenerar Entradas e Saídas"
    — achado real na geraldo: um arquivo XML de 2019 foi removido de
    `1-DOCFISCAIS/nf/ET/`, mas ninguém rodou persistir_nfe()/persistir_
    estoque_entradas_saidas() depois, então o banco (e a auditoria) ficou
    desatualizado sem nenhum aviso — o usuário só descobriu a
    inconsistência comparando contra o Excel de referência. O botão fica
    logo no topo desta página, antes das duas auditorias, pra reduzir
    esse tipo de investigação: refaz Estágio 1 (persistir_nfe — relê os
    .txt já classificados em ET/EP) + Estágio 4 (persistir_estoque_
    entradas_saidas) em sequência, sem precisar abrir "EXTRAÇÃO" e depois
    "TABELAS ENTRADAS/SAÍDAS/ESTOQUES" separadamente. Não reclassifica
    XML novo ainda pendente na raiz de `1-DOCFISCAIS/nf/` (isso continua
    sendo `loader.carregar_operacao()`, botão "Carregar novamente" da
    página EXTRAÇÃO) — só relê o que já está em ET/EP.

    2026-07-17 (mesmo dia): ganhou o terceiro espelho render_auditoria_
    divergencia_estoque() — "falta agora para os estoques", pedido do
    usuário logo após fechar entradas/saídas. Estrutura diferente das
    outras duas (comparação direta de quantidade por COD_ITEM×ANO, sem
    waterfall) porque a fonte Hunter (estoque_anual_consolidado, Estágio
    5) não tem os múltiplos afluentes que estoque_entradas/saidas têm —
    ver loader.auditar_divergencia_estoque()."""
    _botao_voltar_menu()
    if not st.session_state.get("dados_carregados"):
        st.info('Carregue os dados primeiro em "🛠️ 1: PROCEDIMENTOS INICIAIS".')
        return

    if st.button(
        "🔄 Regenerar Entradas e Saídas (Estágio 1 + 4)",
        key="btn_regenerar_entradas_saidas_auditoria1",
        help="Relê os XML já classificados em 1-DOCFISCAIS/nf/ET e /EP "
             "(persistir_nfe) e recalcula estoque_entradas/estoque_saidas "
             "(persistir_estoque_entradas_saidas). Use antes de conferir a "
             "auditoria se algum arquivo fonte mudou (ex.: removeu/adicionou "
             "um XML em ET/EP) — não reclassifica XML novo ainda pendente na "
             "raiz de 1-DOCFISCAIS/nf/ (isso é a página EXTRAÇÃO).",
    ):
        with st.spinner("Regenerando NF-e (Estágio 1)..."):
            resultado_nfe = loader.persistir_nfe()
        if "erro" in resultado_nfe:
            st.error(f"Erro ao regenerar NF-e: {resultado_nfe['erro']}")
            return
        with st.spinner("Regenerando Entradas/Saídas Enriquecidas (Estágio 4)..."):
            resultado_estoque = loader.persistir_estoque_entradas_saidas()
        if "erro" in resultado_estoque:
            st.error(f"Erro ao regenerar Entradas/Saídas: {resultado_estoque['erro']}")
            return
        st.success(
            f"✅ Regenerado: {resultado_nfe.get('xml_entradas_real', 0):,} entradas reais, "
            f"{resultado_nfe.get('xml_saidas_real', 0):,} saídas reais → "
            f"{resultado_estoque.get('estoque_entradas', 0):,} entradas / "
            f"{resultado_estoque.get('estoque_saidas', 0):,} saídas enriquecidas."
            .replace(",", ".")
        )
        st.session_state["estoque_entradas_saidas_gerado"] = True
        # Sem st.rerun() aqui de propósito: as duas auditorias são chamadas
        # logo abaixo, no mesmo ciclo de execução do script — já leem o
        # banco recém-atualizado. Um rerun faria a mensagem de sucesso
        # sumir antes do usuário conseguir ler os números.

    render_auditoria_divergencia_entradas()
    render_auditoria_divergencia_saidas()
    render_auditoria_divergencia_estoque()


def render_pagina_descricao_relevante() -> None:
    """Painel 'DESCRIÇÃO RELEVANTE' (Estágio 7.1 — Fixação da Descrição
    Relevante, primeiro sub-passo do Estágio 7 — Escolha do Produto Alvo;
    2026-07-18, Solicitação Técnica), botão de 6º nível no Menu Principal:
    elege a descrição mais frequente (moda) por COD_ITEM entre entradas,
    saídas (Estágio 4) e estoque (Estágio 5) — ver loader.
    montar_produto_alvo()/render_descricao_relevante(). Serve de nome
    "oficial" pra padronizar relatórios e apoiar a seleção de produtos
    pra auditoria física. Exige dados_carregados (mesmo padrão das outras
    páginas — sem carga, as 3 tabelas fonte não existem)."""
    _botao_voltar_menu()
    if not st.session_state.get("dados_carregados"):
        st.info('Carregue os dados primeiro em "🛠️ 1: PROCEDIMENTOS INICIAIS".')
        return
    render_descricao_relevante()


def render_pagina_cruzamento_valor() -> None:
    """Painel '7.2: CRUZAMENTO POR VALOR' (Estágio 7.2 — segundo sub-passo
    do Estágio 7 — Escolha do Produto Alvo; 2026-07-18, Solicitação
    Técnica), botão de 7º nível no Menu Principal: aplica EI+Compras=
    Vendas+EF por (ANO, COD_ITEM) em R$ — ver loader.
    gerar_cruzamento_valor()/render_cruzamento_valor(). Exige
    dados_carregados (mesmo padrão das outras páginas — sem carga, as
    tabelas fonte não existem); depende também de produto_alvo (Estágio
    7.1) já gerada, checado dentro de render_cruzamento_valor()."""
    _botao_voltar_menu()
    if not st.session_state.get("dados_carregados"):
        st.info('Carregue os dados primeiro em "🛠️ 1: PROCEDIMENTOS INICIAIS".')
        return
    render_cruzamento_valor()


def render_pagina_cruzamento_produto() -> None:
    """Painel '7.2.1: CRUZAMENTO POR PRODUTO' (Estágio 7.2.1 —
    condensação do Estágio 7.2 por Descrição Relevante, 2026-07-19,
    Solicitação Técnica), botão de 8º nível no Menu Principal: ver
    loader.gerar_cruzamento_produto()/render_cruzamento_produto(). Exige
    dados_carregados (mesmo padrão das outras páginas); depende também
    de cruzamento_valor (Estágio 7.2) já gerada, checado dentro de
    render_cruzamento_produto()."""
    _botao_voltar_menu()
    if not st.session_state.get("dados_carregados"):
        st.info('Carregue os dados primeiro em "🛠️ 1: PROCEDIMENTOS INICIAIS".')
        return
    render_cruzamento_produto()


def render_pagina_rn1_fisica() -> None:
    """Painel '7.3: RN1 — MOVIMENTAÇÃO FÍSICA (XML)' (Estágio 7.3,
    2026-07-20, Solicitação Técnica), botão de 9º nível no Menu Principal:
    ver loader.gerar_rn1_fisica()/render_rn1_fisica(). Exige
    dados_carregados (mesmo padrão das outras páginas); depende também de
    cruzamento_valor (Estágio 7.2) já gerada, checado dentro de
    render_rn1_fisica()."""
    _botao_voltar_menu()
    if not st.session_state.get("dados_carregados"):
        st.info('Carregue os dados primeiro em "🛠️ 1: PROCEDIMENTOS INICIAIS".')
        return
    render_rn1_fisica()


def render_pagina_rn1_produto() -> None:
    """Painel '7.3.1: RN1 POR PRODUTO' (Estágio 7.3.1, 2026-07-20,
    Solicitação Técnica), botão de 10º nível no Menu Principal: ver
    loader.gerar_rn1_produto()/render_rn1_produto(). Exige
    dados_carregados (mesmo padrão das outras páginas); depende também de
    rn1_fisica (Estágio 7.3) já gerada, checado dentro de
    render_rn1_produto()."""
    _botao_voltar_menu()
    if not st.session_state.get("dados_carregados"):
        st.info('Carregue os dados primeiro em "🛠️ 1: PROCEDIMENTOS INICIAIS".')
        return
    render_rn1_produto()


def render_pagina_rn1_simulada_30() -> None:
    """Painel '7.3.2: SIMULAÇÃO RN1 (+30%)' (Estágio 7.3.2, 2026-07-22,
    Solicitação Técnica), botão de 11º nível no Menu Principal: ver
    loader.gerar_rn1_simulada_30()/render_rn1_simulada_30(). Exige
    dados_carregados (mesmo padrão das outras páginas); depende também de
    rn1_produto (Estágio 7.3.1) já gerada, checado dentro de
    render_rn1_simulada_30(). Estágio 7.3.3 (Seleção Consolidada de
    Alvos) teve seu próprio botão/página separados em 2026-08-03 (pedido
    do usuário) — ver render_pagina_consolidado_733()."""
    _botao_voltar_menu()
    if not st.session_state.get("dados_carregados"):
        st.info('Carregue os dados primeiro em "🛠️ 1: PROCEDIMENTOS INICIAIS".')
        return
    render_rn1_simulada_30()


def render_pagina_consolidado_733() -> None:
    """Painel '7.3.3: Seleção Consolidada (Estoque/XML)' (Estágio 7.3.3),
    botão próprio no Menu Principal desde 2026-08-03 — Solicitação
    Técnica original (2026-08-03) pedia esta seção logo abaixo do 7.3.2,
    na mesma página; o usuário pediu depois pra separar em botão próprio
    ("separe 7.3.3 do 7.3.2 criando botão próprio pra ele"). Ver
    loader.gerar_consolidado_origens_733()/render_consolidado_origens_733().
    Exige dados_carregados (mesmo padrão das outras páginas) — mas NÃO
    depende de nenhum outro estágio 7.x já gerado (lê estoque_entradas/
    estoque_saidas/estoque_anual_consolidado direto, Estágios 4/5)."""
    _botao_voltar_menu()
    if not st.session_state.get("dados_carregados"):
        st.info('Carregue os dados primeiro em "🛠️ 1: PROCEDIMENTOS INICIAIS".')
        return
    render_consolidado_origens_733()


_COLUNAS_PREVIEW_ESTAGIO8_DETALHADO = ["codproddecl", "desc_xml", "descrição_decl", "idunico"]
_COLUNAS_PREVIEW_ESTAGIO8_AGRUPADO = ["codproddecl", "desc_xml", "descrição_decl", "qtde_ocorrencias"]

# Critério 1 do Cruzamento (Estágio 10, Entradas) inclui SIMILARIDADE_DESCRICAO
# além das colunas do Estágio 8 — ver loader.cruzar_produto_escolhido_entradas().
# "descrição_decl" continua na base (loader.salvar_cruzamento_confirmado()
# exige a coluna), mas sai só da EXIBIÇÃO do editor (2026-07-23, pedido do
# usuário: "retire descrição da declaração" — já aparece só uma vez, no
# cabeçalho/caption da seção, repetir em toda linha é redundante aqui; a
# tabela detalhada de baixo mantém a coluna) — ver _render_cruzamento_
# entradas().
_COLUNAS_PREVIEW_CRUZAMENTO_ENTRADAS_AGRUPADO = _COLUNAS_PREVIEW_ESTAGIO8_AGRUPADO + ["SIMILARIDADE_DESCRICAO"]

# Tabela "Itens individuais (com ID Único)" persistida (cruzamento_confirmado_detalhado,
# 2026-07-23) — ver loader.consultar_cruzamento_confirmado_detalhado(). CHV_NFE +
# atributos físicos/fiscais (Ano Eleito, NCM 4 dígitos, unidade/valor/quantidade do
# produto) enriquecidos ao vivo via loader.consultar_atributos_estoque_por_idunico()
# (2026-07-23: "traga tb a chave de acesso"; 2026-07-25, Solicitação Técnica
# "ENRIQUECIMENTO DA TABELA DE ITENS INDIVIDUAIS": os 6 campos fiscais), nada
# persistido — enriquecimento só na exibição.
# Ordem 2026-07-25 (pedido do usuário: "coloque chave após valor total
# do item e id único na ultima coluna"): CHV_NFE logo após vl_prod;
# idunico vira a ÚLTIMA coluna (depois até de CRITERIO/TS).
_COLUNAS_PREVIEW_CRUZAMENTO_CONFIRMADO_DETALHADO = [
    "codproddecl", "desc_xml", "ANO_ELEITO", "ncm4",
    "unid_prod", "vl_unit_prod", "qtde_prod", "vl_prod",
    "unid_prod_utiliz", "vu_utilizado", "quant_utiliz",
    "fm_utilizado", "TRATAMENTO",
    "CHV_NFE", "CRITERIO", "TS", "idunico", "IS_ST",
]


_COLUNAS_PREVIEW_ESTAGIO8_SAIDAS_DETALHADO = ["codproddecl", "desc_xml", "idunico"]
_COLUNAS_PREVIEW_ESTAGIO8_SAIDAS_AGRUPADO = ["codproddecl", "desc_xml", "qtde_ocorrencias"]

# Saídas (2026-07-25, Solicitação Técnica "BUSCA DE CORRESPONDENTES NAS
# SAÍDAS") — mesma ideia do cruzamento de Entradas, mas sobre
# estagio8_saidas_agrupado, que não tem "descrição_decl" (achado real:
# na saída a auditada é emitente, `desc_xml` JÁ é a "declaração" dela —
# não existe campo separado pra comparar, por isso Saídas só tem
# Critério 1 e Critério 3, sem Critério 2).
_COLUNAS_PREVIEW_CRUZAMENTO_SAIDAS_AGRUPADO = _COLUNAS_PREVIEW_ESTAGIO8_SAIDAS_AGRUPADO + ["SIMILARIDADE_DESCRICAO"]


_COLUNAS_PREVIEW_ESTAGIO8_ESTOQUE_DETALHADO = ["codproddecl", "descrição_decl", "idunico"]
_COLUNAS_PREVIEW_ESTAGIO8_ESTOQUE_AGRUPADO = ["codproddecl", "descrição_decl", "qtde_ocorrencias"]

# Estoque (2026-07-25, Solicitação Técnica "BUSCA DE CORRESPONDENTES NO
# ESTOQUE") — mesma ideia do cruzamento de Entradas/Saídas, mas sobre
# estagio8_estoque_agrupado (Estágio 8.2, Bloco H). Só Critério 1 (mesmo
# código) e Critério 2 (nome de declaração igual), sem Critério 3 (não
# pedido na Solicitação Técnica). `desc_xml` não aparece na EXIBIÇÃO —
# Estoque só tem "descrição_decl" (ver loader._COLUNAS_CRUZAMENTO_
# ESTOQUE_AGRUPADO); `desc_xml` existe só internamente, como alias de
# descrição_decl, pra caber no mesmo esquema de persistência de
# cruzamento_confirmado usado por Entradas/Saídas, sem exigir mudança
# nenhuma em salvar_cruzamento_confirmado()/_detalhado().
_COLUNAS_BASE_CRUZAMENTO_ESTOQUE_AGRUPADO = ["codproddecl", "desc_xml", "descrição_decl", "qtde_ocorrencias"]
_COLUNAS_PREVIEW_CRUZAMENTO_ESTOQUE_AGRUPADO = _COLUNAS_PREVIEW_ESTAGIO8_ESTOQUE_AGRUPADO + ["SIMILARIDADE_DESCRICAO"]


def _render_bloco_estagio8(
    *,
    chave_estado: str,
    chave_widget: str,
    nome_tabela_detalhado: str,
    nome_tabela_agrupado: str,
    colunas_preview_detalhado: list,
    colunas_preview_agrupado: list,
    fn_ja_gerado,
    fn_verificar,
    fn_consultar_detalhado,
    fn_consultar_agrupado,
    fn_persistir,
    nome_tabela_origem: str,
    label_gerar: str,
) -> None:
    """Bloco genérico Detalhada+Agrupada+verificação+exportação CSV do
    Estágio 8 — reusado por Entradas (2026-07-23) e Saídas (2026-07-23,
    Estágio 8.1), mesma estrutura sobre fontes diferentes
    (estoque_entradas/estoque_saidas). Já é chamado de DENTRO de uma aba
    de nível superior (render_estagio_8(): "📥 Entradas"/"📤 Saídas") —
    por isso Detalhada/Agrupada aqui são SEÇÕES (cabeçalho + divisor),
    não abas aninhadas, evitando `st.tabs` dentro de `st.tabs`.
    `chave_widget` prefixa toda key de widget/container pra não colidir
    entre as duas seções na mesma tela. Mostra a verificação de
    qualidade (fn_verificar — soma de qtde_ocorrencias no agrupado DEVE
    bater com o total do detalhado, Solicitação Técnica 2026-07-23) a
    cada exibição, não só logo após gerar."""
    if chave_estado not in st.session_state:
        st.session_state[chave_estado] = fn_ja_gerado()

    if st.session_state[chave_estado]:
        verificacao = fn_verificar()
        if verificacao["bate"] is True:
            st.success(
                f"✅ Verificação de qualidade: {verificacao['total_detalhado']:,} linha(s) em "
                f"`{nome_tabela_detalhado}` = {verificacao['soma_ocorrencias']:,} em soma de "
                "qtde_ocorrencias — bate.".replace(",", ".")
            )
        elif verificacao["bate"] is False:
            st.error(
                f"❌ Verificação de qualidade falhou: {verificacao['total_detalhado']:,} linha(s) em "
                f"`{nome_tabela_detalhado}`, mas soma de qtde_ocorrencias é "
                f"{verificacao['soma_ocorrencias']:,} — regere.".replace(",", ".")
            )

        # Seções (não abas aninhadas — st.tabs dentro de st.tabs tem
        # histórico de comportamento visual inconsistente no Streamlit;
        # "abas ou seções" era explicitamente aceito na Solicitação
        # Técnica, então o nível interno usa cabeçalho + divisor).
        st.markdown("#### Detalhada")
        df_preview, total = fn_consultar_detalhado(limite=200)
        st.success(f"✅ {total:,} registro(s) em `{nome_tabela_detalhado}`.".replace(",", "."))
        if df_preview.empty:
            st.info("Nenhum registro encontrado.")
        else:
            st.markdown(f"Prévia limitada a 200 linhas de {total:,}".replace(",", "."))
            chave_container = f"{chave_widget}_detalhado_tabela"
            with st.container(key=chave_container):
                st.markdown(
                    f"<style>.st-key-{chave_container} [data-testid='stDataFrame'] "
                    "* { font-size: 12px; }</style>",
                    unsafe_allow_html=True,
                )
                st.dataframe(
                    _preparar_preview(df_preview, colunas_preview_detalhado),
                    use_container_width=True,
                    hide_index=True,
                )

            chave_csv = f"{chave_widget}_detalhado_csv_bytes"
            chave_csv_total = f"{chave_widget}_detalhado_csv_total"
            preparar = st.button(
                "Preparar exportação completa (CSV)", key=f"btn_preparar_export_{chave_widget}_detalhado",
            )
            if preparar:
                with st.spinner("Preparando exportação completa..."):
                    df_completo, total_completo = fn_consultar_detalhado(limite=None)
                    csv_completo = df_completo.rename(columns=loader.carregar_dicionario_campos())
                    st.session_state[chave_csv] = csv_completo.to_csv(index=False, sep=";").encode("utf-8-sig")
                    st.session_state[chave_csv_total] = total_completo

            if chave_csv in st.session_state:
                st.download_button(
                    f"Baixar tabela completa ({st.session_state[chave_csv_total]:,} "
                    "linha(s), CSV)".replace(",", "."),
                    data=st.session_state[chave_csv],
                    file_name=f"{nome_tabela_detalhado}.csv",
                    mime="text/csv",
                    key=f"btn_download_{chave_widget}_detalhado",
                )

        st.divider()
        st.markdown("#### Agrupada")
        df_preview, total = fn_consultar_agrupado(limite=200)
        st.success(f"✅ {total:,} combinação(ões) em `{nome_tabela_agrupado}`.".replace(",", "."))
        if df_preview.empty:
            st.info("Nenhum registro encontrado.")
        else:
            st.markdown(f"Prévia limitada a 200 linhas de {total:,}".replace(",", "."))
            chave_container = f"{chave_widget}_agrupado_tabela"
            with st.container(key=chave_container):
                st.markdown(
                    f"<style>.st-key-{chave_container} [data-testid='stDataFrame'] "
                    "* { font-size: 12px; }</style>",
                    unsafe_allow_html=True,
                )
                st.dataframe(
                    _preparar_preview(df_preview, colunas_preview_agrupado),
                    use_container_width=True,
                    hide_index=True,
                )

            chave_csv = f"{chave_widget}_agrupado_csv_bytes"
            chave_csv_total = f"{chave_widget}_agrupado_csv_total"
            preparar = st.button(
                "Preparar exportação completa (CSV)", key=f"btn_preparar_export_{chave_widget}_agrupado",
            )
            if preparar:
                with st.spinner("Preparando exportação completa..."):
                    df_completo, total_completo = fn_consultar_agrupado(limite=None)
                    csv_completo = df_completo.rename(columns=loader.carregar_dicionario_campos())
                    st.session_state[chave_csv] = csv_completo.to_csv(index=False, sep=";").encode("utf-8-sig")
                    st.session_state[chave_csv_total] = total_completo

            if chave_csv in st.session_state:
                st.download_button(
                    f"Baixar tabela completa ({st.session_state[chave_csv_total]:,} "
                    "linha(s), CSV)".replace(",", "."),
                    data=st.session_state[chave_csv],
                    file_name=f"{nome_tabela_agrupado}.csv",
                    mime="text/csv",
                    key=f"btn_download_{chave_widget}_agrupado",
                )

        st.divider()
        clicou = st.button(
            f"Regerar {label_gerar}",
            key=f"btn_regerar_{chave_widget}",
            help=f"Reprocessa a partir de {nome_tabela_origem} e substitui as 2 tabelas.",
        )
    else:
        clicou = st.button(f"Gerar {label_gerar}", key=f"btn_gerar_{chave_widget}")

    if not clicou:
        return

    with st.spinner(f"Processando {nome_tabela_origem} (Detalhada + Agrupada)..."):
        resultado = fn_persistir()

    if "erro" in resultado:
        st.error(f"Erro: {resultado['erro']}")
        return

    st.session_state[chave_estado] = True
    st.rerun()


def render_estagio_8() -> None:
    """Estágio 8 — Resumo de Entradas/Saídas/Estoques (2026-07-23,
    Solicitação Técnica, expandido no mesmo dia com os Estágios 8.1 e
    8.2): visões de referência sobre estoque_entradas/estoque_saidas
    (Estágio 4) e estoque_anual_consolidado (Estágio 5) pra conferir a
    qualidade do Matching e identificar padrões de escrituração da
    auditada — ver loader.gerar_estagio_8()/gerar_estagio_8_saidas()/
    gerar_estagio_8_estoque() pro raciocínio completo. Três abas de
    nível superior, "Entradas"/"Saídas"/"Estoques", cada uma com
    sub-seções "Detalhada"/"Agrupada" (_render_bloco_estagio8(), função
    genérica reusada pelas três). Em Saídas, codproddecl vem de
    fatoitemnfe_infnfe_det_prod_cprod (código do próprio XML) — não de
    COD_ITEM_DECLARACAO/Matching, que não se aplica a saídas (auditada
    é emitente da nota, cProd já é o código dela mesma; achado
    confirmado com o usuário 2026-07-23, mesma correção já aplicada em
    Vendas do Estágio 7.2). Em Estoques, idunico é SINTÉTICO (hash de
    Ano+Código+Descrição+EstoqueInicial+EstoqueFinal, instrução
    explícita do usuário) — estoque_anual_consolidado não tem chave de
    item individual (é consolidada por Ano+Código)."""
    st.subheader("Estágio 8 — Resumo de Entradas / Saídas / Estoques")

    aba_entradas, aba_saidas, aba_estoques = st.tabs(["📥 Entradas", "📤 Saídas", "📦 Estoques"])

    with aba_entradas:
        st.caption(
            "Duas visões de referência sobre estoque_entradas (Estágio 4): a aba Detalhada mostra "
            "cada item do XML com o código/descrição declarados e o ID Único (rastreia a nota "
            "exata); a aba Agrupada condensa por código + descrição declarados + descrição do XML, "
            "contando ocorrências — revela se o mesmo item do XML está associado a mais de um "
            "código declarado, ou o inverso. Ordenada por quantidade de ocorrências decrescente."
        )
        _render_bloco_estagio8(
            chave_estado="estagio8_gerado",
            chave_widget="estagio8",
            nome_tabela_detalhado="estagio8_detalhado",
            nome_tabela_agrupado="estagio8_agrupado",
            colunas_preview_detalhado=_COLUNAS_PREVIEW_ESTAGIO8_DETALHADO,
            colunas_preview_agrupado=_COLUNAS_PREVIEW_ESTAGIO8_AGRUPADO,
            fn_ja_gerado=loader.estagio8_ja_gerado,
            fn_verificar=loader.verificar_estagio_8,
            fn_consultar_detalhado=loader.consultar_estagio8_detalhado,
            fn_consultar_agrupado=loader.consultar_estagio8_agrupado,
            fn_persistir=loader.persistir_estagio_8,
            nome_tabela_origem="estoque_entradas (Estágio 4)",
            label_gerar="Estágio 8 — Resumo de Entradas",
        )

    with aba_saidas:
        st.caption(
            "Mesma lógica sobre estoque_saidas (Estágio 4): Detalhada (código do produto do próprio "
            "XML + descrição do XML + ID Único) e Agrupada (código + descrição do XML, contando "
            "ocorrências). Na saída a auditada é emitente da nota, então o código do produto do "
            "XML dela já é o código próprio, sem precisar de Matching/BC3 (diferente de Entradas, "
            "onde o código vem de terceiros e precisa ser traduzido pelo Matching)."
        )
        _render_bloco_estagio8(
            chave_estado="estagio8_saidas_gerado",
            chave_widget="estagio8_saidas",
            nome_tabela_detalhado="estagio8_saidas_detalhado",
            nome_tabela_agrupado="estagio8_saidas_agrupado",
            colunas_preview_detalhado=_COLUNAS_PREVIEW_ESTAGIO8_SAIDAS_DETALHADO,
            colunas_preview_agrupado=_COLUNAS_PREVIEW_ESTAGIO8_SAIDAS_AGRUPADO,
            fn_ja_gerado=loader.estagio8_saidas_ja_gerado,
            fn_verificar=loader.verificar_estagio_8_saidas,
            fn_consultar_detalhado=loader.consultar_estagio8_saidas_detalhado,
            fn_consultar_agrupado=loader.consultar_estagio8_saidas_agrupado,
            fn_persistir=loader.persistir_estagio_8_saidas,
            nome_tabela_origem="estoque_saidas (Estágio 4)",
            label_gerar="Estágio 8.1 — Resumo de Saídas",
        )

    with aba_estoques:
        st.caption(
            "Mesma lógica sobre estoque_anual_consolidado (Estágio 5): Detalhada (código/descrição "
            "declarados + ID Único) e Agrupada (código + descrição, contando ocorrências). Essa "
            "tabela não tem chave de item individual (é consolidada por Ano+Código) — o ID Único "
            "aqui é sintético, um hash de Ano + Código + Descrição + Estoque Inicial + Estoque "
            "Final, só pra esta visão (não altera a tabela real do Estágio 5). Duas linhas 100% "
            "idênticas nesses 5 campos (achado real de qualidade de dado, raro) recebem o mesmo ID."
        )
        _render_bloco_estagio8(
            chave_estado="estagio8_estoque_gerado",
            chave_widget="estagio8_estoque",
            nome_tabela_detalhado="estagio8_estoque_detalhado",
            nome_tabela_agrupado="estagio8_estoque_agrupado",
            colunas_preview_detalhado=_COLUNAS_PREVIEW_ESTAGIO8_ESTOQUE_DETALHADO,
            colunas_preview_agrupado=_COLUNAS_PREVIEW_ESTAGIO8_ESTOQUE_AGRUPADO,
            fn_ja_gerado=loader.estagio8_estoque_ja_gerado,
            fn_verificar=loader.verificar_estagio_8_estoque,
            fn_consultar_detalhado=loader.consultar_estagio8_estoque_detalhado,
            fn_consultar_agrupado=loader.consultar_estagio8_estoque_agrupado,
            fn_persistir=loader.persistir_estagio_8_estoque,
            nome_tabela_origem="estoque_anual_consolidado (Estágio 5)",
            label_gerar="Estágio 8.2 — Resumo de Estoques",
        )


def render_pagina_estagio_8() -> None:
    """Painel 'ESTÁGIO 8: RESUMO DE ENTRADAS' (2026-07-23, Solicitação
    Técnica; expandido no mesmo dia com as abas Saídas/Estoques,
    Estágios 8.1/8.2), botão de 12º nível no Menu Principal: ver
    loader.gerar_estagio_8()/render_estagio_8(). Exige dados_carregados
    (mesmo padrão das outras páginas); depende também de estoque_
    entradas/estoque_saidas (Estágio 4) e estoque_anual_consolidado
    (Estágio 5) já gerados, checado dentro de render_estagio_8()."""
    _botao_voltar_menu()
    if not st.session_state.get("dados_carregados"):
        st.info('Carregue os dados primeiro em "🛠️ 1: PROCEDIMENTOS INICIAIS".')
        return
    render_estagio_8()


_CHAVE_EDITOR_FM_ENTRADAS = "editor_curadoria_fm_entradas"
_COLUNAS_PREVIEW_FM_ENTRADAS_AGRUPADO = [
    "desc_xml", "up_xml", "particula", "fm_sugerido", "nova_up", "qtde_ocorrencias",
]
_COLUNAS_PREVIEW_FM_ENTRADAS_DETALHADO = ["desc_xml", "idunico", "FM_ELEITO", "NOVA_UP"]


def render_curadoria_fm_entradas() -> None:
    """Estágio 9 — Curadoria de Fator Multiplicador (Entradas),
    Solicitação Técnica 2026-07-24: ferramenta de saneamento pra
    identificar itens onde a unidade de comercialização do fornecedor
    (XML) é um múltiplo da unidade de estoque da auditada (SPED) — ver
    loader.gerar_curadoria_fm_entradas() pro raciocínio completo do
    agrupamento (Descrição XML + Valor Unitário XML arredondado ao
    inteiro mais próximo — chave interna, NÃO exibida — ajuste feito
    após investigação real com o usuário: agrupar pelo valor exato
    gerava 76,5% dos grupos com só 1 ocorrência, não atingindo "edição
    em massa").

    "UP XML" (2026-07-24, correção do usuário: "up é unidade de
    produto: cx, uind, fd" — NÃO é valor unitário, como uma primeira
    versão deste painel assumiu por engano) é a MODA do campo UCOM do
    XML dentro do grupo ("UN", "CX", "FD", "cx12" etc.). "Nova UP"
    (mesma correção: "deixe como default 'unid'") é só um valor PADRÃO
    editável ("UNID"), sem fórmula — o auditor corrige manualmente
    quando o padrão não for o caso; não há sincronização com "FM
    Sugerido" (são campos independentes).

    Editor único (`st.data_editor`, mesmo padrão de alta densidade do
    Estágio 8 — fonte 10px, hide_index), SEM checkbox de seleção nem
    coluna "Observação" (2026-07-24, pedido do usuário: "retire a
    coluna 'gravar' e observação'" — diferente da Rubrica do Produto
    Alvo, Estágio 10, que exige marcar linha a linha, aqui TODA a tabela
    fica editável e "Salvar" grava o estado atual de TODOS os grupos de
    uma vez, edição em massa de verdade). FM Sugerido exibido sem zeros
    à direita (2026-07-24: "transforme fm sugerido 12.000 em 12" —
    `format="%g"`). Termina com "Itens individuais (com ID Único)"
    (2026-07-24: "tabela deve estar vinckada à tabela com id único") —
    junta fm_entradas_curadoria com estoque_entradas pela mesma chave
    de agrupamento, trazendo o ID_UNICO de cada item coberto por um
    grupo já salvo (loader.consultar_curadoria_fm_entradas_detalhado()),
    mesmo espírito da tabela homônima do Estágio 10."""
    st.subheader("Estágio 9 — Curadoria de Fator Multiplicador (Entradas)")
    st.caption(
        "Agrupa itens de Entradas (Estágio 4) por Descrição XML + Valor Unitário XML "
        "(arredondado, só como chave interna) pra identificar em massa casos onde a unidade de "
        "comercialização do fornecedor é um múltiplo da unidade de estoque da auditada. \"UP XML\" "
        "é a Unidade de Produto do XML (CX, UN, FD...); \"FM Sugerido\" vem do Fator Multiplicador "
        "já calculado no Matching (Estágio 2); \"Partícula\" é uma pista de embalagem extraída da "
        "própria descrição (ex.: \"C/12\"); \"Nova UP\" começa como \"UNID\" (ajustável). Ajuste os "
        "grupos que precisar e clique em \"Salvar\" — a decisão alimenta o Estágio 15 (RN1)."
    )

    if "estagio9_fm_gerado" not in st.session_state:
        st.session_state["estagio9_fm_gerado"] = loader.curadoria_fm_entradas_ja_gerado()

    if st.session_state["estagio9_fm_gerado"]:
        clicou = st.button(
            "Regerar Estágio 9 — Curadoria de Fator Multiplicador",
            key="btn_regerar_estagio9_fm",
            help="Reprocessa a partir de estoque_entradas (Estágio 4) e substitui a tabela agrupada.",
        )
    else:
        clicou = st.button("Gerar Estágio 9 — Curadoria de Fator Multiplicador", key="btn_gerar_estagio9_fm")

    if clicou:
        with st.spinner("Processando estoque_entradas (agrupando por Descrição XML + Valor Unitário)..."):
            resultado = loader.persistir_curadoria_fm_entradas()
        if resultado.get("erros"):
            st.error(resultado["erros"][0])
            return
        st.session_state["estagio9_fm_gerado"] = True
        # Widget da rodada anterior não faz mais sentido pro novo
        # conjunto de linhas — descarta pra não misturar índice antigo
        # com dado novo.
        st.session_state.pop(_CHAVE_EDITOR_FM_ENTRADAS, None)
        st.rerun()

    if not st.session_state["estagio9_fm_gerado"]:
        return

    agrupado, total = loader.consultar_curadoria_fm_entradas_agrupado(limite=None)
    if agrupado.empty:
        st.info("Nenhum grupo encontrado.")
        return
    st.markdown(f"**{total:,} grupo(s)** de Descrição XML + Valor Unitário.".replace(",", "."))

    # Grupos já confirmados antes (fm_entradas_curadoria) — pré-popula
    # FM Sugerido/Nova UP com o valor SALVO (não o recém-sugerido, que
    # pode ter mudado numa regeração). Sem checkbox "Gravar" nem coluna
    # "Observação" (2026-07-24, pedido do usuário: "retire a coluna
    # 'gravar' e observação'") — toda a tabela fica sempre editável, e
    # "Salvar" grava o estado ATUAL de todas as linhas de uma vez (edição
    # em massa de verdade, sem passo de marcação linha a linha).
    curadoria_salva, _ = loader.consultar_curadoria_fm(limite=None)
    salvos_por_chave = {}
    if not curadoria_salva.empty:
        for _, linha in curadoria_salva.iterrows():
            if pd.notna(linha["VALOR_UNIT_GRUPO"]):
                salvos_por_chave[(linha["DESC_XML"], int(linha["VALOR_UNIT_GRUPO"]))] = linha

    editor_base = agrupado[_COLUNAS_PREVIEW_FM_ENTRADAS_AGRUPADO].copy()
    editor_base.insert(0, "_valor_unit_grupo", agrupado["_valor_unit_grupo"])
    for idx, linha in editor_base.iterrows():
        chave = (
            linha["desc_xml"],
            int(linha["_valor_unit_grupo"]) if pd.notna(linha["_valor_unit_grupo"]) else None,
        )
        salvo = salvos_por_chave.get(chave)
        if salvo is not None:
            editor_base.at[idx, "fm_sugerido"] = salvo["FM_ELEITO"]
            editor_base.at[idx, "nova_up"] = salvo["NOVA_UP"]

    editor_exibicao = (
        editor_base.drop(columns=["_valor_unit_grupo"]).rename(columns=loader.carregar_dicionario_campos())
    )
    colunas_travadas = [c for c in editor_exibicao.columns if c not in ("FM Sugerido", "Nova UP")]
    with st.container(key="curadoria_fm_entradas_tabela"):
        st.markdown(
            "<style>.st-key-curadoria_fm_entradas_tabela [data-testid='stDataFrame'] "
            "* { font-size: 10px; }</style>",
            unsafe_allow_html=True,
        )
        editado = st.data_editor(
            editor_exibicao,
            use_container_width=True,
            hide_index=True,
            disabled=colunas_travadas,
            key=_CHAVE_EDITOR_FM_ENTRADAS,
            # "%g" (formato geral) em vez de "%.4f" — 2026-07-24, pedido
            # do usuário: "transforme fm sugerido 12.000 em 12" — remove
            # zeros à direita sem esconder casas decimais quando existem
            # de verdade (12.0 -> "12", 0.499107 -> "0.499107").
            column_config={"FM Sugerido": st.column_config.NumberColumn(format="%g")},
        )

    if st.button("💾 Salvar Curadoria de Fator Multiplicador", key="btn_salvar_curadoria_fm"):
        selecionadas = pd.DataFrame({
            "DESC_XML": editor_base["desc_xml"],
            "VALOR_UNIT_GRUPO": editor_base["_valor_unit_grupo"],
            "FM_ELEITO": editado["FM Sugerido"],
            "NOVA_UP": editado["Nova UP"],
        })
        universo_chaves = set(zip(
            editor_base["desc_xml"],
            editor_base["_valor_unit_grupo"].apply(lambda v: int(v) if pd.notna(v) else None),
        ))
        resultado = loader.salvar_curadoria_fm(selecionadas, universo_chaves=universo_chaves)
        if "erro" in resultado:
            st.error(f"Erro: {resultado['erro']}")
        else:
            st.success(f"✅ Curadoria salva — {resultado['total_salvo']} grupo(s) atualizado(s).")
            st.rerun()

    # Itens individuais (com ID Único) — 2026-07-24, pedido do usuário:
    # "tabela deve estar vinckada à tabela com id único". Junta a
    # curadoria salva (fm_entradas_curadoria) com estoque_entradas pela
    # mesma chave de agrupamento (Descrição XML + Valor Unitário
    # arredondado), trazendo o ID_UNICO de cada item individual coberto
    # por um grupo já salvo — mesmo espírito da tabela "Itens individuais
    # (com ID Único)" do Estágio 10 (Rubrica do Produto Alvo).
    st.divider()
    st.markdown("**Itens individuais (com ID Único)**")
    detalhado, total_detalhado = loader.consultar_curadoria_fm_entradas_detalhado(limite=200)
    if detalhado.empty:
        st.info("Nenhum grupo salvo ainda — clique em \"Salvar Curadoria de Fator Multiplicador\" acima.")
        return
    st.markdown(f"Prévia limitada a 200 linhas de {total_detalhado:,}".replace(",", "."))
    with st.container(key="curadoria_fm_entradas_detalhado_tabela"):
        st.markdown(
            "<style>.st-key-curadoria_fm_entradas_detalhado_tabela [data-testid='stDataFrame'] "
            "* { font-size: 12px; }</style>",
            unsafe_allow_html=True,
        )
        st.dataframe(
            _preparar_preview(detalhado, _COLUNAS_PREVIEW_FM_ENTRADAS_DETALHADO),
            use_container_width=True,
            hide_index=True,
        )


_CHAVE_EDITOR_FM_SAIDAS = "editor_curadoria_fm_saidas"
_COLUNAS_PREVIEW_FM_SAIDAS_AGRUPADO = [
    "desc_xml", "up_xml", "particula", "fm_sugerido", "nova_up", "qtde_ocorrencias",
]
_COLUNAS_PREVIEW_FM_SAIDAS_DETALHADO = ["desc_xml", "idunico", "FM_ELEITO", "NOVA_UP"]


def render_curadoria_fm_saidas() -> None:
    """Estágio 9 — Curadoria de Fator Multiplicador (Saídas), 2026-07-25,
    Solicitação Técnica "crie tb fator para descrição de saídas e
    estoques nos moldes das entradas" — mirror de
    render_curadoria_fm_entradas(), mesmo agrupamento (Descrição XML +
    Valor Unitário XML arredondado) sobre estoque_saidas (Estágio 4).
    `fm_sugerido` fica NULL na quase totalidade dos grupos (achado
    real: só 0,3% de estoque_saidas tem FATOR_MULTIPLICADOR_SUGERIDO —
    Matching/BC3 só cobre Entradas), mantida mesmo assim por decisão
    explícita do usuário — o auditor digita o FM_ELEITO manualmente."""
    st.subheader("Estágio 9 — Curadoria de Fator Multiplicador (Saídas)")
    st.caption(
        "Agrupa itens de Saídas (Estágio 4) por Descrição XML + Valor Unitário XML "
        "(arredondado, só como chave interna). \"UP XML\" é a Unidade de Produto do XML "
        "(CX, UN, FD...); \"FM Sugerido\" vem do Fator Multiplicador do Matching (Estágio 2), mas "
        "cobre só ~0,3% dos itens de Saídas (o Matching só liga Entradas de terceiros) — na maioria "
        "das linhas o auditor digita o FM_ELEITO do zero; \"Partícula\" é uma pista de embalagem "
        "extraída da própria descrição; \"Nova UP\" começa como \"UNID\" (ajustável)."
    )

    if "estagio9_fm_saidas_gerado" not in st.session_state:
        st.session_state["estagio9_fm_saidas_gerado"] = loader.curadoria_fm_saidas_ja_gerado()

    if st.session_state["estagio9_fm_saidas_gerado"]:
        clicou = st.button(
            "Regerar Estágio 9 — Curadoria de Fator Multiplicador (Saídas)",
            key="btn_regerar_estagio9_fm_saidas",
            help="Reprocessa a partir de estoque_saidas (Estágio 4) e substitui a tabela agrupada.",
        )
    else:
        clicou = st.button(
            "Gerar Estágio 9 — Curadoria de Fator Multiplicador (Saídas)", key="btn_gerar_estagio9_fm_saidas",
        )

    if clicou:
        with st.spinner("Processando estoque_saidas (agrupando por Descrição XML + Valor Unitário)..."):
            resultado = loader.persistir_curadoria_fm_saidas()
        if resultado.get("erros"):
            st.error(resultado["erros"][0])
            return
        st.session_state["estagio9_fm_saidas_gerado"] = True
        st.session_state.pop(_CHAVE_EDITOR_FM_SAIDAS, None)
        st.rerun()

    if not st.session_state["estagio9_fm_saidas_gerado"]:
        return

    agrupado, total = loader.consultar_curadoria_fm_saidas_agrupado(limite=None)
    if agrupado.empty:
        st.info("Nenhum grupo encontrado.")
        return
    st.markdown(f"**{total:,} grupo(s)** de Descrição XML + Valor Unitário.".replace(",", "."))

    curadoria_salva, _ = loader.consultar_curadoria_fm_saidas(limite=None)
    salvos_por_chave = {}
    if not curadoria_salva.empty:
        for _, linha in curadoria_salva.iterrows():
            if pd.notna(linha["VALOR_UNIT_GRUPO"]):
                salvos_por_chave[(linha["DESC_XML"], int(linha["VALOR_UNIT_GRUPO"]))] = linha

    editor_base = agrupado[_COLUNAS_PREVIEW_FM_SAIDAS_AGRUPADO].copy()
    editor_base.insert(0, "_valor_unit_grupo", agrupado["_valor_unit_grupo"])
    for idx, linha in editor_base.iterrows():
        chave = (
            linha["desc_xml"],
            int(linha["_valor_unit_grupo"]) if pd.notna(linha["_valor_unit_grupo"]) else None,
        )
        salvo = salvos_por_chave.get(chave)
        if salvo is not None:
            editor_base.at[idx, "fm_sugerido"] = salvo["FM_ELEITO"]
            editor_base.at[idx, "nova_up"] = salvo["NOVA_UP"]

    editor_exibicao = (
        editor_base.drop(columns=["_valor_unit_grupo"]).rename(columns=loader.carregar_dicionario_campos())
    )
    colunas_travadas = [c for c in editor_exibicao.columns if c not in ("FM Sugerido", "Nova UP")]
    with st.container(key="curadoria_fm_saidas_tabela"):
        st.markdown(
            "<style>.st-key-curadoria_fm_saidas_tabela [data-testid='stDataFrame'] "
            "* { font-size: 10px; }</style>",
            unsafe_allow_html=True,
        )
        editado = st.data_editor(
            editor_exibicao,
            use_container_width=True,
            hide_index=True,
            disabled=colunas_travadas,
            key=_CHAVE_EDITOR_FM_SAIDAS,
            column_config={"FM Sugerido": st.column_config.NumberColumn(format="%g")},
        )

    if st.button("💾 Salvar Curadoria de Fator Multiplicador", key="btn_salvar_curadoria_fm_saidas"):
        selecionadas = pd.DataFrame({
            "DESC_XML": editor_base["desc_xml"],
            "VALOR_UNIT_GRUPO": editor_base["_valor_unit_grupo"],
            "FM_ELEITO": editado["FM Sugerido"],
            "NOVA_UP": editado["Nova UP"],
        })
        universo_chaves = set(zip(
            editor_base["desc_xml"],
            editor_base["_valor_unit_grupo"].apply(lambda v: int(v) if pd.notna(v) else None),
        ))
        resultado = loader.salvar_curadoria_fm_saidas(selecionadas, universo_chaves=universo_chaves)
        if "erro" in resultado:
            st.error(f"Erro: {resultado['erro']}")
        else:
            st.success(f"✅ Curadoria salva — {resultado['total_salvo']} grupo(s) atualizado(s).")
            st.rerun()

    st.divider()
    st.markdown("**Itens individuais (com ID Único)**")
    detalhado, total_detalhado = loader.consultar_curadoria_fm_saidas_detalhado(limite=200)
    if detalhado.empty:
        st.info("Nenhum grupo salvo ainda — clique em \"Salvar Curadoria de Fator Multiplicador\" acima.")
        return
    st.markdown(f"Prévia limitada a 200 linhas de {total_detalhado:,}".replace(",", "."))
    with st.container(key="curadoria_fm_saidas_detalhado_tabela"):
        st.markdown(
            "<style>.st-key-curadoria_fm_saidas_detalhado_tabela [data-testid='stDataFrame'] "
            "* { font-size: 12px; }</style>",
            unsafe_allow_html=True,
        )
        st.dataframe(
            _preparar_preview(detalhado, _COLUNAS_PREVIEW_FM_SAIDAS_DETALHADO),
            use_container_width=True,
            hide_index=True,
        )


_CHAVE_EDITOR_FM_ESTOQUE = "editor_curadoria_fm_estoque"
_COLUNAS_PREVIEW_FM_ESTOQUE_AGRUPADO = [
    "descrição_decl", "up_estoque", "particula", "fm_sugerido", "nova_up", "qtde_ocorrencias",
]
_COLUNAS_PREVIEW_FM_ESTOQUE_DETALHADO = ["descrição_decl", "idunico", "FM_ELEITO", "NOVA_UP"]


def render_curadoria_fm_estoque() -> None:
    """Estágio 9 — Curadoria de Fator Multiplicador (Estoque), 2026-07-25,
    Solicitação Técnica — mirror de render_curadoria_fm_entradas(), mas
    sobre estoque_anual_consolidado (Bloco H, Estágio 5). Diferença
    estrutural real confirmada com o usuário ANTES de implementar: essa
    tabela não tem valor unitário nem UCOM — agrupa só por Descrição
    Declarada (sem "_valor_unit_grupo"); "UP Estoque" vem da MODA do
    campo UNIDADE (único campo de unidade do Bloco H). "FM Sugerido"
    (2026-07-28, pedido do usuário: "nos moldes de entradas e saídas,
    replique em estoque o fm sugerido em vez de fm eleito, assim como
    partículas") passou a ser calculado igual a Entradas/Saídas —
    _extrair_fator_multiplicador_xml() sobre a própria Descrição
    Declarada — e é a própria coluna editável (igual às outras duas
    telas: o auditor ajusta o valor sugerido em vez de digitar do zero
    num campo "FM Eleito" separado)."""
    st.subheader("Estágio 9 — Curadoria de Fator Multiplicador (Estoque)")
    st.caption(
        "Agrupa itens de Estoque (Estágio 5, Bloco H) por Descrição Declarada — sem valor "
        "unitário (o Bloco H não declara valor por item, só quantidade por ano). \"UP Estoque\" "
        "é a Unidade declarada no Bloco H (moda do grupo); \"FM Sugerido\" vem do número "
        "embutido na própria Descrição Declarada (ex.: \"C/12\" — mesma técnica de Entradas/"
        "Saídas, fator=1 se nenhum padrão de embalagem for reconhecido); \"Partícula\" é a "
        "pista de embalagem que originou o FM Sugerido; \"Nova UP\" começa como \"UNID\" "
        "(ajustável)."
    )

    if "estagio9_fm_estoque_gerado" not in st.session_state:
        st.session_state["estagio9_fm_estoque_gerado"] = loader.curadoria_fm_estoque_ja_gerado()

    if st.session_state["estagio9_fm_estoque_gerado"]:
        clicou = st.button(
            "Regerar Estágio 9 — Curadoria de Fator Multiplicador (Estoque)",
            key="btn_regerar_estagio9_fm_estoque",
            help="Reprocessa a partir de estoque_anual_consolidado (Estágio 5) e substitui a tabela agrupada.",
        )
    else:
        clicou = st.button(
            "Gerar Estágio 9 — Curadoria de Fator Multiplicador (Estoque)", key="btn_gerar_estagio9_fm_estoque",
        )

    if clicou:
        with st.spinner("Processando estoque_anual_consolidado (agrupando por Descrição Declarada)..."):
            resultado = loader.persistir_curadoria_fm_estoque()
        if resultado.get("erros"):
            st.error(resultado["erros"][0])
            return
        st.session_state["estagio9_fm_estoque_gerado"] = True
        st.session_state.pop(_CHAVE_EDITOR_FM_ESTOQUE, None)
        st.rerun()

    if not st.session_state["estagio9_fm_estoque_gerado"]:
        return

    agrupado, total = loader.consultar_curadoria_fm_estoque_agrupado(limite=None)
    if agrupado.empty:
        st.info("Nenhum grupo encontrado.")
        return
    st.markdown(f"**{total:,} grupo(s)** de Descrição Declarada.".replace(",", "."))

    curadoria_salva, _ = loader.consultar_curadoria_fm_estoque(limite=None)
    salvos_por_chave = {}
    if not curadoria_salva.empty:
        for _, linha in curadoria_salva.iterrows():
            salvos_por_chave[linha["DESCR_ITEM_DECL"]] = linha

    editor_base = agrupado[_COLUNAS_PREVIEW_FM_ESTOQUE_AGRUPADO].copy()
    for idx, linha in editor_base.iterrows():
        salvo = salvos_por_chave.get(linha["descrição_decl"])
        if salvo is not None:
            editor_base.at[idx, "fm_sugerido"] = salvo["FM_ELEITO"]
            editor_base.at[idx, "nova_up"] = salvo["NOVA_UP"]

    editor_exibicao = editor_base.rename(columns=loader.carregar_dicionario_campos())
    colunas_travadas = [c for c in editor_exibicao.columns if c not in ("FM Sugerido", "Nova UP")]
    with st.container(key="curadoria_fm_estoque_tabela"):
        st.markdown(
            "<style>.st-key-curadoria_fm_estoque_tabela [data-testid='stDataFrame'] "
            "* { font-size: 10px; }</style>",
            unsafe_allow_html=True,
        )
        editado = st.data_editor(
            editor_exibicao,
            use_container_width=True,
            hide_index=True,
            disabled=colunas_travadas,
            key=_CHAVE_EDITOR_FM_ESTOQUE,
            column_config={"FM Sugerido": st.column_config.NumberColumn(format="%g")},
        )

    if st.button("💾 Salvar Curadoria de Fator Multiplicador", key="btn_salvar_curadoria_fm_estoque"):
        selecionadas = pd.DataFrame({
            "DESCR_ITEM_DECL": editor_base["descrição_decl"],
            "FM_ELEITO": editado["FM Sugerido"],
            "NOVA_UP": editado["Nova UP"],
        })
        universo_chaves = set(editor_base["descrição_decl"])
        resultado = loader.salvar_curadoria_fm_estoque(selecionadas, universo_chaves=universo_chaves)
        if "erro" in resultado:
            st.error(f"Erro: {resultado['erro']}")
        else:
            st.success(f"✅ Curadoria salva — {resultado['total_salvo']} grupo(s) atualizado(s).")
            st.rerun()

    st.divider()
    st.markdown("**Itens individuais (com ID Único)**")
    detalhado, total_detalhado = loader.consultar_curadoria_fm_estoque_detalhado(limite=200)
    if detalhado.empty:
        st.info("Nenhum grupo salvo ainda — clique em \"Salvar Curadoria de Fator Multiplicador\" acima.")
        return
    st.markdown(f"Prévia limitada a 200 linhas de {total_detalhado:,}".replace(",", "."))
    with st.container(key="curadoria_fm_estoque_detalhado_tabela"):
        st.markdown(
            "<style>.st-key-curadoria_fm_estoque_detalhado_tabela [data-testid='stDataFrame'] "
            "* { font-size: 12px; }</style>",
            unsafe_allow_html=True,
        )
        st.dataframe(
            _preparar_preview(detalhado, _COLUNAS_PREVIEW_FM_ESTOQUE_DETALHADO),
            use_container_width=True,
            hide_index=True,
        )


def render_pagina_estagio_9() -> None:
    """Painel 'ESTÁGIO 9: FATOR MULTIPLICADOR' (2026-07-24, Solicitação
    Técnica original — só Entradas; expandido 2026-07-25 pra Saídas e
    Estoque, "nos moldes das entradas"), botão da 2ª linha do Menu
    Principal: 3 abas, mesmo padrão de nível superior do Estágio 8
    ("📥 Entradas"/"📤 Saídas"/"📦 Estoque"). Exige dados_carregados
    (mesmo padrão das outras páginas); cada aba checa sua própria
    tabela de origem (estoque_entradas/estoque_saidas/estoque_anual_
    consolidado) dentro da respectiva render_curadoria_fm_*()."""
    _botao_voltar_menu()
    if not st.session_state.get("dados_carregados"):
        st.info('Carregue os dados primeiro em "🛠️ 1: PROCEDIMENTOS INICIAIS".')
        return
    aba_entradas, aba_saidas, aba_estoque = st.tabs(["📥 Entradas", "📤 Saídas", "📦 Estoque"])
    with aba_entradas:
        render_curadoria_fm_entradas()
    with aba_saidas:
        render_curadoria_fm_saidas()
    with aba_estoque:
        render_curadoria_fm_estoque()


def _ampliar_universo_idunicos_com_persistido(
    escolhido: dict, origem: str, universo_chaves: set, universo_idunicos: set,
) -> set:
    """Amplia `universo_idunicos` (calculado a partir da busca AO VIVO,
    `fn_detalhado()`) com qualquer idunico JÁ PERSISTIDO em
    cruzamento_confirmado_detalhado pras mesmas `universo_chaves`
    (codproddecl, desc_xml), mesmo que esse idunico não apareça mais na
    busca atual — achado real 2026-07-25: um item confirmado na Rubrica
    do Estoque (idunico de um ano "ainda não fechado") ficou ÓRFÃO depois
    que o filtro de QUANTIDADE_FINAL do Estágio 8.2 passou a excluir
    aquele ano da busca — o usuário marcou "Desfazer" na combinação
    inteira, mas o idunico órfão nunca aparecia mais em `fn_detalhado()`,
    então nunca entrava no `universo_idunicos` calculado só a partir da
    busca ao vivo, e a linha ficava PRA SEMPRE travada em
    cruzamento_confirmado_detalhado, inalcançável pelo Desfazer normal.
    Sem essa ampliação, qualquer mudança futura na fonte (Estágio 4/5/8,
    regeneração de dados) que remova um idunico anteriormente confirmado
    pode orfanizar aquela confirmação da mesma forma — a ampliação evita
    isso em qualquer origem (entradas/saídas/estoque)."""
    ja_persistido, _ = loader.consultar_cruzamento_confirmado_detalhado(
        descr_alvo=escolhido["DESCR_ALVO"], origem=origem, limite=None,
    )
    if ja_persistido.empty:
        return universo_idunicos
    mask_persistido = [
        (c, d) in universo_chaves
        for c, d in zip(ja_persistido["codproddecl"], ja_persistido["desc_xml"])
    ]
    return universo_idunicos | set(ja_persistido.loc[mask_persistido, "idunico"])


def _obter_criterios_cruzamento_entradas() -> dict:
    """Mapa criterio -> (fn_agrupado, fn_detalhado) usado pelo selectbox
    de _render_cruzamento_entradas(). Construído em função (não no
    escopo do módulo) pra usar `loader.*` sem depender da ordem de
    definição no arquivo. Critério 2 original (código divergente,
    2026-07-23) foi RENUMERADO pra Critério 3 no mesmo dia ("transforme
    o critério 2 em critério3") quando o Critério 2 "de verdade" (nome
    de declaração igual ao alvo) foi definido — motivo pelo qual esta
    função existe: com 3 critérios, a tela precisa DESPACHAR pra função
    certa conforme o que está selecionado. Rótulo do Critério 3
    (2026-07-28, pedido do usuário: "mudar o nome do critério3 para:
    'nome_prod_decl do alvo = nome_prod_xml' em entradas") usa
    `CRITERIO_BUSCA3_NOME_XML` — mesma constante usada no Critério 3 de
    Saídas (ver _obter_criterios_cruzamento_saidas(); chegou a ser
    renumerada "Busca2" lá no mesmo dia, revertida logo em seguida —
    "vamos fixar. volte para o nr 3." — daí as duas abas convergirem
    pra uma constante SÓ, em vez de uma por aba)."""
    return {
        loader.CRITERIO_BUSCA1_MESMO_CODIGO: (
            loader.cruzar_produto_escolhido_entradas,
            loader.cruzar_produto_escolhido_entradas_detalhado,
        ),
        loader.CRITERIO_BUSCA2_NOME_DECLARACAO_IGUAL: (
            loader.cruzar_produto_escolhido_entradas_criterio2,
            loader.cruzar_produto_escolhido_entradas_criterio2_detalhado,
        ),
        loader.CRITERIO_BUSCA3_NOME_XML: (
            loader.cruzar_produto_escolhido_entradas_criterio3,
            loader.cruzar_produto_escolhido_entradas_criterio3_detalhado,
        ),
        loader.CRITERIO_BUSCA4_PESQUISA_LIVRE: (
            loader.cruzar_produto_escolhido_entradas_criterio4,
            loader.cruzar_produto_escolhido_entradas_criterio4_detalhado,
        ),
    }


def _obter_valor_unitario_editado(
    valor_min_editado, valor_max_editado, valor_min_original, valor_max_original,
) -> "float | None":
    """Devolve o valor unitário ÚNICO editado pelo auditor no Sumário —
    2026-07-26, "SEPARE EM DIAS COLUNAS MIN E MAX" (antes era um texto
    combinado "min - max", "TRANSFORME O VALOR UNIT MIN-MAX EM
    EDITÁVEL"; virou 2 colunas numéricas, `Valor Minimo`/`Valor
    Maximo`).

    CORRIGIDO em 2026-07-26 (achado real reportado pelo usuário: "CRAVEI
    30 NO VALOR MÍNIMO E QUANDO APLIQUEI VOLTOU PARA DEFAULT") — a
    versão anterior só aceitava override quando `valor_min == valor_max`
    (exigia editar os 2 campos pro MESMO número); na prática o auditor
    edita só UM dos 2 campos (ex.: só "Valor Minimo"), esperando que
    isso já baste. Agora compara cada valor editado contra o ORIGINAL
    calculado (`valor_min_original`/`valor_max_original`, vindos de
    `sumario_unidades["vl_min"]`/`["vl_max"]` antes da renomeação) pra
    descobrir qual campo o auditor de fato mexeu:
    - só um dos 2 mudou → esse valor é o override.
    - os 2 mudaram pro MESMO valor → esse valor é o override.
    - os 2 mudaram pra valores DIFERENTES → ambíguo, sem override
      (preserva o comportamento padrão; o auditor precisa deixar os 2
      iguais se quiser um valor único pros dois lados).
    - nenhum mudou (faixa intocada) → sem override, comportamento
      padrão (÷FM sobre o bruto de cada item)."""
    min_valido = pd.notna(valor_min_editado)
    max_valido = pd.notna(valor_max_editado)
    min_mudou = min_valido and float(valor_min_editado) != float(valor_min_original)
    max_mudou = max_valido and float(valor_max_editado) != float(valor_max_original)
    if min_mudou and max_mudou:
        return float(valor_min_editado) if float(valor_min_editado) == float(valor_max_editado) else None
    if min_mudou:
        return float(valor_min_editado)
    if max_mudou:
        return float(valor_max_editado)
    return None


def _render_sumario_unidades_com_aplicar(
    sumario_unidades: pd.DataFrame, idunicos_tratados: set,
    escolhido: dict, origem: str, sufixo_key: str,
) -> None:
    """Renderiza o "📊 Diagnóstico de Unidades (Visão XML)" — Sumário de
    Unidades (2026-07-25) com "Valor Minimo"/"Valor Maximo"/"FM Sug"/
    "Nova Unid" editáveis, coluna "Observação" (2026-07-26, "CRIE UMA
    OBSERVAÇÃO COMO NA FIG", mesmo padrão da coluna homônima da Rubrica:
    "✅ Já salvo na Rubrica" — aqui "✅ Já aplicado" pras linhas com pelo
    menos 1 item já tratado, sem depender do estado dos checkboxes, que
    é só a AÇÃO da próxima gravação/remoção) e checkboxes "Aplicar"/
    "Desfazer" + botão "🔧 Aplicar / Desfazer Tratamento" (2026-07-26).
    Mirror entre Entradas/Saídas/Estoque — `sufixo_key` evita colisão de
    widget key entre as 3 abas (rodam no mesmo script run do
    `st.tabs()`). Checkboxes sempre começam DESMARCADOS, mesmo padrão
    do "Salvar"/"Desfazer" da Rubrica.

    "Valor Minimo"/"Valor Maximo" editáveis (2026-07-26, "1-TRANSFORME O
    VALOR UNIT MIN-MAX EM EDITÁVEL", depois "SEPARE EM DIAS COLUNAS MIN
    E MAX" — o campo combinado "faixa" virou 2 colunas numéricas): se o
    auditor igualar os 2 valores (via `_obter_valor_unitario_editado()`,
    um valor único, não mais uma faixa de verdade), esse valor vira o
    preço-base usado no ÷FM pra TODOS os itens da UP, no lugar do valor
    bruto individual de cada item — corrige a variação interna de preço
    entre notas (achado real: "cx12" variando de R$24,90 a R$38,76).
    "2-ATUALIZE A OCORRÊNCIA": a "Qtd. Ocorrências" já reflete
    corretamente os itens tratados sem precisar de código extra — o
    Sumário sempre recalcula do zero (bruto) a cada `st.rerun()`, e
    "Aplicar" sempre trata TODOS os idunicos daquela linha de uma vez
    (nunca parcialmente), então a contagem bruta da linha JÁ É a
    contagem de itens tratados. "3-VOLTE AO DEFAULT AO DESFAZER":
    também automático — "Desfazer" apaga o registro de tratamento
    inteiro (FM/Nova Unidade/Valor Unitário editados juntos), então o
    item volta a mostrar o valor CALCULADO a partir do XML bruto, sem
    rastro da edição anterior.

    IMPORTANTE (2026-07-26, achado real via bug reportado pelo usuário:
    "MARQUE SOMENTE O 17,67 E A APLICAÇÃO CONSIDEROU TUDO
    ERRONEAMENTE") — localiza os idunicos de cada linha marcada pela
    coluna INTERNA `sumario_unidades["_idunicos"]` (indexada pela mesma
    posição da linha), NUNCA por texto de `unid_prod`: depois da
    separação por destaque, 2+ linhas podem ter o MESMO texto (ex.:
    "LA" normal e "LA" destoante) — comparar por texto aplicava/
    desfazia em TODOS os itens daquele texto, não só os da linha
    marcada. Chama loader.aplicar_tratamento_fm()/loader.desfazer_
    tratamento_fm() (origem=origem). "Desfazer" tem precedência sobre
    "Aplicar" se as duas vierem marcadas na mesma linha (por ÍNDICE,
    mesmo raciocínio da Rubrica, 2026-07-24 — mas nunca por texto, pelo
    mesmo motivo acima). "Aplicar" grava `escolhido["DESCR_ALVO"]`/
    `escolhido["COD_ITEM"]` junto (2026-07-26, "ISSO DEVE FICAR SALVO
    NO PRODUTO ALVO")."""
    if sumario_unidades.empty:
        return
    st.markdown("### 📊 Diagnóstico de Unidades (Visão XML)")
    idunicos_por_linha = sumario_unidades["_idunicos"]
    # Valores ORIGINAIS calculados (antes de qualquer edição) — usados
    # por _obter_valor_unitario_editado() pra descobrir qual dos 2
    # campos o auditor de fato mexeu (2026-07-26, ver docstring dessa
    # função: "CRAVEI 30 NO VALOR MÍNIMO ... VOLTOU PARA DEFAULT").
    vl_min_original_por_linha = sumario_unidades["vl_min"]
    vl_max_original_por_linha = sumario_unidades["vl_max"]
    sumario_exibicao = sumario_unidades.drop(columns=["_idunicos"]).rename(
        columns=loader.carregar_dicionario_campos(),
    )
    sumario_exibicao["Aplicar"] = False
    sumario_exibicao["Desfazer"] = False
    sumario_exibicao["Observação"] = [
        "✅ Já aplicado" if (conjunto & idunicos_tratados) else ""
        for conjunto in idunicos_por_linha
    ]
    colunas_travadas_sumario = [
        c for c in sumario_exibicao.columns
        if c not in ("Valor Minimo", "Valor Maximo", "FM Sug", "Nova Unid", "Aplicar", "Desfazer")
    ]
    chave_container = f"sumario_unidades_alvo_tabela_{sufixo_key}"
    with st.container(key=chave_container):
        st.markdown(
            f"<style>.st-key-{chave_container} [data-testid='stDataFrame'] "
            "* { font-size: 10px; }</style>",
            unsafe_allow_html=True,
        )
        sumario_editado = st.data_editor(
            sumario_exibicao,
            use_container_width=True,
            hide_index=True,
            disabled=colunas_travadas_sumario,
            key=f"editor_sumario_unidades_alvo_{sufixo_key}",
            column_config={
                # "%g" (mesmo truque do Estágio 9, 2026-07-24: "transforme
                # fm sugerido 12.000 em 12") — remove zeros à direita sem
                # esconder casas decimais quando existem de verdade.
                "FM Sug": st.column_config.NumberColumn(format="%g"),
                "Valor Minimo": st.column_config.NumberColumn(format="%.2f"),
                "Valor Maximo": st.column_config.NumberColumn(format="%.2f"),
            },
        )
    st.caption(
        "Marque \"Aplicar\" nas UPs cujo FM Sug/Nova Unid devem ser lançados nos itens "
        "individuais dessa UP (preço unitário ÷ FM, quantidade × FM, TRATAMENTO='T'); iguale "
        "\"Valor Minimo\"/\"Valor Maximo\" pra corrigir o preço-base usado nesse cálculo; marque "
        "\"Desfazer\" pra reverter um tratamento já aplicado (volta ao valor bruto do XML)."
    )
    if st.button("🔧 Aplicar / Desfazer Tratamento", key=f"btn_aplicar_fm_sumario_{sufixo_key}"):
        marcadas_desfazer = sumario_editado[sumario_editado["Desfazer"] == True]  # noqa: E712
        marcadas_aplicar = sumario_editado[sumario_editado["Aplicar"] == True]  # noqa: E712
        # "Desfazer" tem precedência sobre "Aplicar" se as duas vierem
        # marcadas na mesma linha (caso contraditório raro) — por
        # ÍNDICE da linha, não por texto de UP (2026-07-26, ver
        # docstring: 2 linhas podem ter o mesmo texto).
        indices_desfazer = set(marcadas_desfazer.index)
        marcadas_aplicar = marcadas_aplicar[~marcadas_aplicar.index.isin(indices_desfazer)]
        if marcadas_aplicar.empty and marcadas_desfazer.empty:
            st.warning("Nenhuma UP marcada em \"Aplicar\" ou \"Desfazer\".")
        else:
            total_aplicado = 0
            total_desfeito = 0
            erros = []
            for idx, linha in marcadas_aplicar.iterrows():
                up = linha["Unidade do Produto"]
                fm = linha["FM Sug"]
                nova_unid = linha["Nova Unid"]
                if pd.isna(fm) or float(fm) == 0:
                    erros.append(f"UP \"{up}\": FM Sug inválido (vazio ou zero), não aplicado.")
                    continue
                valor_unitario_editado = _obter_valor_unitario_editado(
                    linha["Valor Minimo"], linha["Valor Maximo"],
                    vl_min_original_por_linha.loc[idx], vl_max_original_por_linha.loc[idx],
                )
                idunicos_up = set(idunicos_por_linha.loc[idx])
                resultado = loader.aplicar_tratamento_fm(
                    idunicos_up, float(fm), str(nova_unid),
                    descr_alvo=escolhido["DESCR_ALVO"], cod_item=escolhido["COD_ITEM"], origem=origem,
                    valor_unitario_aplicado=valor_unitario_editado,
                )
                if "erro" in resultado:
                    erros.append(f"UP \"{up}\": {resultado['erro']}")
                else:
                    total_aplicado += resultado["total_aplicado"]
            for idx, linha in marcadas_desfazer.iterrows():
                up = linha["Unidade do Produto"]
                idunicos_up = set(idunicos_por_linha.loc[idx])
                resultado = loader.desfazer_tratamento_fm(idunicos_up, origem=origem)
                if "erro" in resultado:
                    erros.append(f"UP \"{up}\": {resultado['erro']}")
                else:
                    total_desfeito += resultado["total_removido"]
            for erro in erros:
                st.error(erro)
            partes = []
            if total_aplicado:
                partes.append(f"{total_aplicado} item(ns) tratado(s)")
            if total_desfeito:
                partes.append(f"{total_desfeito} item(ns) revertido(s)")
            if partes:
                st.success(f"✅ {', '.join(partes)}.")
                st.rerun()


def _render_kpis_itens_individuais(detalhado: pd.DataFrame) -> None:
    """KPIs da tabela "Itens individuais" (Estágio 10): soma de `quant_utiliz`
    (quantidade utilizada, após tratamento de FM) e média de `vu_utilizado`
    (valor unitário utilizado) — chamar com `detalhado` ainda NUMÉRICO,
    antes do loop que converte essas colunas em string BR (ver chamadas em
    _render_cruzamento_entradas/saidas/estoque)."""
    soma_quant = detalhado["quant_utiliz"].sum(skipna=True)
    media_vu = detalhado["vu_utilizado"].mean(skipna=True)
    col1, col2 = st.columns(2)
    col1.metric("Soma Quantidade Utilizada", _formatar_moeda_br(soma_quant) if pd.notna(soma_quant) else "-")
    col2.metric("Média Valor Unitário Utilizado", _formatar_moeda_br(media_vu) if pd.notna(media_vu) else "-")


def _render_itens_individuais(detalhado: pd.DataFrame, colunas_preview: list, sufixo_key: str) -> None:
    """Tabela "Itens individuais" (Estágio 10) — somente leitura. Voltou a
    ser assim em 2026-07-26 (revertendo a edição direta de "Unidade do
    Produto"/"FM Sugerido" criada mais cedo no mesmo dia): "Campo de
    unidade de produto deixa de ser editável" + "FM Utilizado" (que
    substituiu "FM Sugerido" no mesmo pedido) também "não editável" —
    toda decisão de tratamento de FM passa a ser feita exclusivamente
    pelo Sumário de Unidades (`_render_sumario_unidades_com_aplicar()`,
    Aplicar/Desfazer). Esta tabela agora é só relatório: mostra os
    campos ORIGINAIS (brutos do XML, nunca sobrescritos) lado a lado
    com os campos "utilizados" (efetivos após tratamento, ou iguais aos
    originais quando não há tratamento — ver _aplicar_tratamento_fm_
    detalhado())."""
    preview = _preparar_preview(detalhado, colunas_preview)
    chave_container = f"cruzamento_{sufixo_key}_detalhado_tabela"
    with st.container(key=chave_container):
        st.markdown(
            f"<style>.st-key-{chave_container} [data-testid='stDataFrame'] "
            "* { font-size: 12px; }</style>",
            unsafe_allow_html=True,
        )
        st.dataframe(preview, use_container_width=True, hide_index=True)


def _render_cruzamento_entradas(escolhido: dict) -> None:
    """Aba 'Entradas' do cruzamento (Estágio 10): compara o produto
    escolhido com estagio8_agrupado (Entradas) usando o critério
    selecionado no selectbox — DESPACHA pra função diferente conforme o
    critério (2026-07-23, renomeada de `_render_cruzamento_entradas_
    criterio1` quando o 2º critério foi adicionado).

    **Critério 1** (loader.cruzar_produto_escolhido_entradas()) combina
    DUAS condições (redefinido 2026-07-23: "critério1: mesmo codigo do
    produto e similaridade entre descricao do produto xml buscado e e
    descrição do alvo"):
    1. MESMO código de produto (normalizado — zero à esquerda não conta
       como diferença): achado real confirmado com o usuário 2026-07-23
       — sem normalizar, "CERV SKOL LATA 350ML" dava zero
       correspondências por causa só do padding (`7891149200504` vs
       `07891149200504`), mesmo sendo o mesmo produto/código.
    2. SIMILARIDADE_DESCRICAO (overlap de tokens) — não filtra nenhuma
       linha, só ordena (desc) e ajuda a decidir qual descrição de XML
       é de fato o mesmo produto quando o código aparece associado a
       mais de uma descrição.

    **Critério 2** (loader.cruzar_produto_escolhido_entradas_
    criterio2()), pedido 2026-07-23 ("o novo critério 2 vai ser o
    seguinte: nome do alvo igual ao nome de declaração do candidato.
    mantenha as similaridade entre nome do alvo e descrição xml do
    candidato."): filtra por IGUALDADE (normalizada) entre `DESCR_ALVO`
    e `descrição_decl` (nome que a própria auditada usa na declaração)
    — sem exigir nenhuma relação de código. `SIMILARIDADE_DESCRICAO`
    continua calculada (entre `desc_xml` e `DESCR_ALVO`), mas aqui só
    ordena, não filtra.

    **Critério 3** (loader.cruzar_produto_escolhido_entradas_
    criterio3()) — era o "Critério 2" original até ser renumerado no
    mesmo dia ("transforme o critério 2 em critério3") — cobre o caso
    OPOSTO do Critério 1: código DIVERGENTE (diferente) do alvo — aqui
    a similaridade de descrição vira FILTRO (≥
    LIMIAR_SIMILARIDADE_CRITERIO3=20), já que não há mais o código como
    evidência. Motivado pelo caso real investigado nesta mesma sessão
    (FARINHA DE TRIGO ADORITA, código 20847, nunca aparece em Entradas
    com esse código).

    Os três alimentam a MESMA tabela de correspondências, com checkbox
    "Salvar" (2026-07-23: "CRIE CAIXA PARA GRAVAR O PRODUTO QUE FARÁ
    PARTE DA RUBRICA DO PRODUTO ALVO" — rótulo encurtado de "Selecionar
    p/ Rubrica" pra "Salvar" na mesma sessão, sempre começa DESMARCADO
    — "deixe como defaut 'Salvar' desmarcado") + checkbox "Desfazer"
    (2026-07-24: "aqui abrir a oportunidade de desfazer" — ação
    dedicada e EXPLÍCITA pra remover uma combinação já salva, separada
    de "Salvar"; antes, remover dependia de deixar "Salvar" desmarcado
    numa linha já confirmada — funcionava via sincronização, mas não
    era uma ação visível/deliberada na tela) + coluna "Observação"
    (2026-07-23: "cravar uma observação" pro que já foi salvo) + botão
    "Salvar na Rubrica", persistindo em loader.salvar_cruzamento_
    confirmado() (agregado) e loader.salvar_cruzamento_confirmado_
    detalhado() (item-a-item, idunico — 2026-07-23: "é importante que
    os produtos com ids fiquem gravado no produto alvo") — universo de
    sincronização restrito às combinações efetivamente marcadas
    (Salvar OU Desfazer), não mais TODAS as linhas da busca, evitando
    remover por engano uma combinação já salva mas simplesmente não
    tocada nesta rodada. Termina com a tabela "Itens individuais (com
    ID Único)" — lê direto de cruzamento_confirmado_detalhado
    (persistido, cumulativo entre critérios — cresce conforme o
    auditor confirma mais combinações, de qualquer critério), não
    recalculada ao vivo.

    Selectbox "Critério de busca" (2026-07-23: "escolha do critério
    dever ser antes do cruzamento") vem ANTES de rodar a comparação, já
    que a escolha do critério é o que DEFINE qual comparação roda — ver
    _obter_criterios_cruzamento_entradas() pro despacho.

    Descrição/Unidade EFETIVAS (2026-08-04): todos os textos desta tela
    (captions/avisos) usam `descr_efetiva`/`unid_efetiva` —
    loader.descricao_efetiva_escolhido()/unidade_efetiva_escolhido() —
    em vez de `escolhido['DESCR_ALVO']`/`escolhido['UNID_ALVO']` puros:
    usam DESCR_EDITADA/UNID_EDITADA (Estágio 10) quando preenchidos,
    senão caem pro original. Achado real do usuário: editou a descrição
    no Estágio 10 e viu que o texto/comparação daqui continuava usando
    a original ("mas o produto alvo ainda é o descrição origina").
    Identidade/chave (loader.cruzar_produto_escolhido_*(),
    consultar_cruzamento_confirmado(), salvar_cruzamento_confirmado())
    continua SEMPRE por `escolhido['DESCR_ALVO']` puro — só o TEXTO/
    COMPARAÇÃO DE SIMILARIDADE usa a versão efetiva (ver
    loader.descricao_efetiva_escolhido() pro raciocínio completo)."""
    criterios = _obter_criterios_cruzamento_entradas()
    criterio_busca = st.selectbox(
        "Critério de busca",
        options=list(criterios.keys()),
        key="select_criterio_busca_entradas",
    )
    fn_agrupado, fn_detalhado = criterios[criterio_busca]
    sufixo_criterio = criterio_busca.split(":", 1)[0].replace("Critério de Busca", "").strip()
    descr_efetiva = loader.descricao_efetiva_escolhido(escolhido)
    unid_efetiva = loader.unidade_efetiva_escolhido(escolhido)
    if escolhido.get("IS_ST"):
        st.caption(f"🏷️ **{descr_efetiva}** é **ST** (Substituição Tributária).")

    if criterio_busca == loader.CRITERIO_BUSCA1_MESMO_CODIGO:
        st.caption(
            f"Combinações em `estagio8_agrupado` (Entradas, Estágio 8) com o MESMO código de produto "
            f"de **{descr_efetiva}** ({escolhido['COD_ITEM']}) — Unidade: **{unid_efetiva or '—'}** — "
            "comparação normalizada (zero à esquerda em código numérico não conta como diferença) — "
            "ordenadas por similaridade de descrição (overlap de tokens) entre o produto do XML e a "
            "descrição do alvo."
        )
    elif criterio_busca == loader.CRITERIO_BUSCA2_NOME_DECLARACAO_IGUAL:
        st.caption(
            f"Combinações em `estagio8_agrupado` (Entradas, Estágio 8) cujo nome de declaração "
            f"(`descrição_decl` — como a própria auditada chama o item) é IGUAL (normalizado — "
            f"maiúsculas/espaços) ao de **{descr_efetiva}** ({escolhido['COD_ITEM']}), "
            "sem exigir nenhuma relação de código. Ordenadas por similaridade de descrição (overlap "
            "de tokens) entre o produto do XML e a descrição do alvo — aqui informativa, não filtra."
        )
    elif criterio_busca == loader.CRITERIO_BUSCA4_PESQUISA_LIVRE:
        st.caption(
            f"Pesquisa livre em `estagio8_agrupado` (Entradas, Estágio 8) pra comparar com "
            f"**{descr_efetiva}** ({escolhido['COD_ITEM']}) — SEM filtro de código "
            "(nem igual, nem divergente) e SEM piso de similaridade. Útil quando o candidato certo "
            "tem pouca ou nenhuma semelhança de texto com o alvo (nomenclatura muito diferente), "
            "caso em que o Critério 3 nunca o encontraria. Digite um termo na busca abaixo (ex.: "
            "parte do nome do alvo) pra ver candidatos, incluindo o próprio produto alvo se ele "
            "aparecer em `estagio8_agrupado` — sem termo, a tabela fica oculta (evita carregar "
            "milhares de grupos de uma vez)."
        )
    else:
        st.caption(
            f"Combinações em `estagio8_agrupado` (Entradas, Estágio 8) com código DIVERGENTE (diferente) "
            f"do de **{descr_efetiva}** ({escolhido['COD_ITEM']}) — cobre o caso em que o "
            "produto é o mesmo fisicamente, mas o código na declaração/XML diverge do código oficial do "
            f"alvo. Só entram candidatos com similaridade de descrição ≥ "
            f"{loader.LIMIAR_SIMILARIDADE_CRITERIO3:.0f}% (aqui a similaridade FILTRA, não é só ordenação, "
            "já que o código não serve de evidência), ordenados por similaridade (desc)."
        )

    correspondentes, _ = fn_agrupado()
    if correspondentes.empty:
        if criterio_busca == loader.CRITERIO_BUSCA1_MESMO_CODIGO:
            st.warning(
                f"⚠️ Nenhuma combinação encontrada com o mesmo código de **{escolhido['COD_ITEM']}** "
                "em `estagio8_agrupado`, mesmo após normalizar zero à esquerda — o produto "
                "provavelmente não aparece nas entradas com esse código."
            )
        elif criterio_busca == loader.CRITERIO_BUSCA2_NOME_DECLARACAO_IGUAL:
            st.warning(
                f"⚠️ Nenhum item declarado com o mesmo nome de **{descr_efetiva}** encontrado "
                "em `estagio8_agrupado`."
            )
        elif criterio_busca == loader.CRITERIO_BUSCA4_PESQUISA_LIVRE:
            st.warning(
                "⚠️ `estagio8_agrupado` está vazio, ou todos os grupos já pertencem a outro alvo — "
                "nada disponível pra pesquisa livre."
            )
        else:
            st.warning(
                f"⚠️ Nenhum candidato de código divergente com similaridade ≥ "
                f"{loader.LIMIAR_SIMILARIDADE_CRITERIO3:.0f}% encontrado pra **{descr_efetiva}** "
                "em `estagio8_agrupado`."
            )
        return
    if criterio_busca == loader.CRITERIO_BUSCA4_PESQUISA_LIVRE:
        st.info(
            f"📚 {len(correspondentes):,} grupo(s) na base (sem filtro de código nem similaridade) "
            "— use a busca abaixo pra encontrar candidatos.".replace(",", ".")
        )
    else:
        st.success(
            f"✅ {len(correspondentes):,} combinação(ões) encontrada(s).".replace(",", ".")
        )

    # Checkbox "Salvar" (2026-07-23, pedido do usuário: "CRIE CAIXA PARA
    # GRAVAR O PRODUTO QUE FARÁ PARTE DA RUBRICA DO PRODUTO ALVO. GERE 1
    # OPÇÃO DE 'CRITÉRIO DE BUSCA1_MESMO CÓDIGO DE PRODUTO'." — rótulo da
    # coluna encurtado de "Selecionar p/ Rubrica" pra "Salvar" em
    # 2026-07-23, mesma sessão: "primeiro campo passa a ser chamado
    # 'Salvar'") — o auditor confirma quais correspondências pertencem de
    # fato à rubrica do produto escolhido, etiquetadas com o critério de
    # busca usado. st.data_editor (não st.dataframe) por causa do
    # checkbox — mesmo padrão/limitações já usados no Grupo de Produto
    # Alvo (7.3.2): sem Styler nesta tabela, cor de destaque só nas
    # tabelas somente-leitura.
    # "Salvar" sempre começa DESMARCADO (2026-07-23, pedido do usuário:
    # "deixe como defaut 'Salvar' desmarcado") — antes vinha pré-marcado
    # pras combinações já confirmadas em cruzamento_confirmado; removido
    # a pedido do usuário, sem pré-marcação nenhuma. Em vez disso, uma
    # coluna "Observação" (2026-07-23, mesma sessão: "as 46 ocorrencias
    # de skol ja foram gravadas. tem que cravar uma observação para
    # isso na linha") informa quais linhas já estão confirmadas — sem
    # depender do estado do checkbox, que agora é só a AÇÃO da próxima
    # gravação/remoção, não um espelho do que já foi salvo.
    ja_confirmadas, _ = loader.consultar_cruzamento_confirmado(descr_alvo=escolhido["DESCR_ALVO"], limite=None)
    ja_confirmadas_entradas = (
        ja_confirmadas[ja_confirmadas["ORIGEM"] == "entradas"] if not ja_confirmadas.empty
        else ja_confirmadas
    )
    chaves_confirmadas = set(
        zip(ja_confirmadas_entradas["codproddecl"], ja_confirmadas_entradas["desc_xml"])
    ) if not ja_confirmadas_entradas.empty else set()

    editor_base = correspondentes[_COLUNAS_PREVIEW_CRUZAMENTO_ENTRADAS_AGRUPADO].copy()
    editor_base.insert(0, "Salvar", False)
    # "Desfazer" (2026-07-24, pedido do usuário: "aqui abrir a
    # oportunidade de desfazer") — checkbox dedicado pra REMOVER uma
    # combinação já confirmada, separado de "Salvar" (que só adiciona).
    # Antes, remover dependia de deixar "Salvar" desmarcado numa
    # combinação já salva e clicar salvar — funcionava (sincronização já
    # implementada), mas não era uma ação EXPLÍCITA/visível na tela; só
    # fazia sentido descobrir isso lendo o código. Com "Desfazer"
    # dedicado, o universo de sincronização passa a ser só as
    # combinações efetivamente marcadas (Salvar OU Desfazer) em vez de
    # TODAS as linhas da busca — uma combinação já salva que não for
    # tocada (nem Salvar nem Desfazer marcados) fica intocada, sem risco
    # de remoção acidental só por estar desmarcada.
    editor_base.insert(1, "Desfazer", False)
    editor_exibicao = editor_base.rename(columns=loader.carregar_dicionario_campos())
    # "Descricao Declaracao" sai só da EXIBIÇÃO (2026-07-23: "retire
    # descrição da declaração") — editor_base mantém a coluna crua
    # (descrição_decl), exigida por loader.salvar_cruzamento_confirmado().
    editor_exibicao = editor_exibicao.drop(columns=["Descricao Declaracao"], errors="ignore")
    editor_exibicao.insert(2, "Observação", [
        "✅ Já salvo na Rubrica" if (c, d) in chaves_confirmadas else ""
        for c, d in zip(editor_base["codproddecl"], editor_base["desc_xml"])
    ])

    # Busca por descrição do XML (pedido do usuário: campo no topo da
    # tabela pra facilitar a comparação visual com o alvo) — filtro
    # client-side (substring, case-insensitive) sobre `desc_xml`, não
    # refaz a busca de candidatos nem muda a contagem de "combinação(ões)
    # encontrada(s)" acima (essa reflete o total do critério, não o
    # filtrado). Aplicado em editor_base E editor_exibicao com a MESMA
    # máscara pra manter os índices alinhados — o botão "Salvar na
    # Rubrica" usa editor_base.index como referência pro que veio do
    # st.data_editor.
    termo_busca_xml = st.text_input(
        "🔎 Buscar por descrição do XML",
        key=f"busca_xml_entradas_{sufixo_criterio}",
        placeholder="Filtrar as combinações abaixo pela descrição do XML...",
    )
    if termo_busca_xml:
        mask_busca = editor_base["desc_xml"].str.contains(termo_busca_xml, case=False, na=False, regex=False)
        editor_base = editor_base[mask_busca]
        editor_exibicao = editor_exibicao.loc[editor_base.index]
        st.caption(f"{len(editor_base)} de {len(correspondentes)} combinação(ões) exibida(s).")
    elif criterio_busca == loader.CRITERIO_BUSCA4_PESQUISA_LIVRE:
        # Pesquisa livre (Solicitação Técnica 2026-07-29) não tem filtro
        # de código nem piso de similaridade — sem um termo de busca, a
        # tabela renderizaria a base inteira de uma vez (5.091 grupos em
        # Entradas na geraldo), pesado pro st.data_editor. EXIGE busca
        # antes de mostrar qualquer linha (reaproveita o MESMO campo de
        # busca acima, em vez de um segundo widget).
        st.info(
            "🔎 Digite um termo de busca acima pra ver candidatos — a pesquisa livre não tem "
            "filtro de código nem de similaridade, então a tabela só aparece depois de buscar."
        )
        return

    colunas_travadas = [c for c in editor_exibicao.columns if c not in ("Salvar", "Desfazer")]
    with st.container(key="cruzamento_entradas_tabela"):
        st.markdown(
            "<style>.st-key-cruzamento_entradas_tabela [data-testid='stDataFrame'] "
            "* { font-size: 10px; }</style>",
            unsafe_allow_html=True,
        )
        editado = st.data_editor(
            editor_exibicao,
            use_container_width=True,
            hide_index=True,
            disabled=colunas_travadas,
            key=f"editor_cruzamento_entradas_{sufixo_criterio}",
        )

    st.caption(
        "Marque \"Salvar\" pra confirmar uma combinação na Rubrica; marque \"Desfazer\" pra "
        "remover uma combinação já salva (coluna \"Observação\")."
    )
    if st.button("💾 Salvar na Rubrica do Produto Alvo", key=f"btn_salvar_rubrica_entradas_{sufixo_criterio}"):
        marcadas_salvar = editado["Salvar"].reindex(editor_base.index).fillna(False)
        marcadas_desfazer = editado["Desfazer"].reindex(editor_base.index).fillna(False)
        # "Desfazer" tem precedência sobre "Salvar" se os dois vierem
        # marcados na mesma linha (caso contraditório raro) — a
        # combinação é tratada como remoção.
        selecionadas = editor_base.loc[
            marcadas_salvar & ~marcadas_desfazer, _COLUNAS_PREVIEW_ESTAGIO8_AGRUPADO
        ]
        # Universo restrito às combinações efetivamente TOCADAS (Salvar
        # OU Desfazer) — 2026-07-24, pedido do usuário: "aqui abrir a
        # oportunidade de desfazer". Antes o universo era TODAS as
        # linhas da busca (2026-07-23, achado real: desmarcar o
        # checkbox nunca removia nada, só deixava de adicionar — a
        # correção de então usava o universo inteiro da busca pra
        # sincronizar). Restringir o universo só ao que foi marcado
        # evita que uma combinação já salva, mas simplesmente não
        # tocada nesta rodada (nem Salvar nem Desfazer), seja removida
        # por engano — e explicita a ação de remoção como algo
        # deliberado ("Desfazer"), não um efeito colateral de deixar
        # "Salvar" desmarcado.
        chaves_desfazer = set(zip(
            editor_base.loc[marcadas_desfazer, "codproddecl"],
            editor_base.loc[marcadas_desfazer, "desc_xml"],
        ))
        chaves_salvar = set(zip(selecionadas["codproddecl"], selecionadas["desc_xml"]))
        universo_chaves = chaves_salvar | chaves_desfazer
        resultado = loader.salvar_cruzamento_confirmado(
            escolhido, "entradas", criterio_busca, selecionadas, universo_chaves=universo_chaves,
        )
        # Grava também o detalhe item-a-item (idunico) — 2026-07-23,
        # pedido do usuário: "é importante que os produtos com ids
        # fiquem gravado no produto alvo e que depois de gravado a
        # situação possa ser revista pelo auditor". Mesmo raciocínio de
        # universo restrito às combinações tocadas.
        # fn_detalhado (não sempre cruzar_produto_escolhido_entradas_
        # detalhado()) — bug em potencial corrigido ao adicionar o
        # Critério 2: usar sempre a função do Critério 1 aqui teria
        # calculado o universo de idunicos errado pra buscas do Critério 2.
        detalhado_completo, _ = fn_detalhado()
        mask_universo = [
            (c, d) in universo_chaves
            for c, d in zip(detalhado_completo["codproddecl"], detalhado_completo["desc_xml"])
        ]
        universo_idunicos = set(detalhado_completo.loc[mask_universo, "idunico"])
        universo_idunicos = _ampliar_universo_idunicos_com_persistido(
            escolhido, "entradas", universo_chaves, universo_idunicos,
        )
        mask_salvar = [
            (c, d) in chaves_salvar
            for c, d in zip(detalhado_completo["codproddecl"], detalhado_completo["desc_xml"])
        ]
        itens_marcados = detalhado_completo.loc[mask_salvar, ["codproddecl", "desc_xml", "idunico"]]
        resultado_detalhado = loader.salvar_cruzamento_confirmado_detalhado(
            escolhido, "entradas", criterio_busca, itens_marcados, universo_idunicos=universo_idunicos,
        )
        if "erro" in resultado:
            st.error(f"Erro: {resultado['erro']}")
        elif "erro" in resultado_detalhado:
            st.error(f"Erro ao gravar itens individuais: {resultado_detalhado['erro']}")
        else:
            partes = [f"{resultado['total_salvo']} confirmada(s)"]
            if resultado["total_removido"]:
                partes.append(f"{resultado['total_removido']} removida(s)")
            st.success(
                f"✅ Rubrica atualizada — {', '.join(partes)} "
                f"({resultado_detalhado['total_salvo']} item(ns) individual(is) gravado(s))."
            )
            st.rerun()

    # Tabela inferior (2026-07-23, pedido do usuário: "CRIE UMA TABELA
    # INFERIOR COM OS PRODUTOS E RESPECTIVOS IDS ÚNICOS") — GRAVADA em
    # cruzamento_confirmado_detalhado (2026-07-23, mesma sessão: "é
    # importante que os produtos com ids fiquem gravado no produto alvo
    # e que depois de gravado a situação possa ser revista pelo
    # auditor") — deixou de ser recalculada ao vivo (cruzando estagio8_
    # detalhado com as chaves confirmadas a cada carregamento da
    # página) e passou a ler direto o que foi persistido, revisável a
    # qualquer momento independente do Estágio 8 ser regerado depois.
    st.divider()
    detalhado, total_detalhado = loader.consultar_cruzamento_confirmado_detalhado(
        descr_alvo=escolhido["DESCR_ALVO"], origem="entradas", limite=None,
    )
    if detalhado.empty:
        st.info(
            "Nenhuma combinação confirmada na Rubrica ainda — marque \"Salvar\" na tabela acima e "
            "clique em \"Salvar na Rubrica do Produto Alvo\" pra ver os itens individuais aqui."
        )
        return
    # Chave de acesso (CHV_NFE) + atributos físicos/fiscais (Ano Eleito,
    # NCM 4 dígitos, unidade/valor/quantidade do produto) — 2026-07-23:
    # "traga tb a chave de acesso"; 2026-07-25, Solicitação Técnica
    # "ENRIQUECIMENTO DA TABELA DE ITENS INDIVIDUAIS" — buscados ao vivo
    # por idunico (não persistidos junto com a Rubrica, ver loader.
    # consultar_atributos_estoque_por_idunico()), já que o idunico já é
    # determinístico e não muda.
    atributos_por_idunico = loader.consultar_atributos_estoque_por_idunico(set(detalhado["idunico"]), origem="entradas")
    detalhado = detalhado.merge(atributos_por_idunico, left_on="idunico", right_on="ID_UNICO", how="left")
    detalhado, sumario_unidades, idunicos_tratados = loader.aplicar_tratamento_fm_detalhado(
        detalhado, origem="entradas",
    )
    # IS_ST (2026-07-29) acompanha o produto alvo até a tabela de Itens
    # Individuais — mesmo valor pra todas as linhas (propriedade do
    # PRODUTO, não do item), ver _badge_st()/consultar_produto_
    # cruzamento_escolhido().
    detalhado["IS_ST"] = escolhido.get("IS_ST", False)

    # Diagnóstico de Unidades + aplicação de FM/Nova Unidade — ANTES da
    # tabela de Itens Individuais (2026-07-30, pedido do usuário: "quero
    # que diagnósticos de unidades venham antes da tabela de id
    # únicos") — ver _render_sumario_unidades_com_aplicar() (2026-07-25/26).
    _render_sumario_unidades_com_aplicar(
        sumario_unidades, idunicos_tratados, escolhido,
        origem="entradas", sufixo_key="entradas",
    )

    st.divider()
    st.markdown("**Itens individuais (com ID Único) — já atribuídos ao alvo**")
    # Formatação BR (milhar '.', decimal ',') pras colunas de valor/quantidade
    # — pedido explícito da Solicitação Técnica ("separadores de milhar e 2
    # casas decimais"), mesmo padrão já usado no painel 7.2. Inclui os
    # campos "utilizados" (2026-07-26) — voltou a ser tabela só leitura,
    # sem precisar ficar numérico pra edição.
    _render_kpis_itens_individuais(detalhado)
    for _col in ("vl_unit_prod", "qtde_prod", "vl_prod", "vu_utilizado", "quant_utiliz", "fm_utilizado"):
        detalhado[_col] = detalhado[_col].apply(lambda v: _formatar_moeda_br(v) if pd.notna(v) else "")
    st.markdown(f"**{total_detalhado:,} item(ns)** individuais gravado(s).".replace(",", "."))
    _render_itens_individuais(
        detalhado, _COLUNAS_PREVIEW_CRUZAMENTO_CONFIRMADO_DETALHADO, sufixo_key="entradas",
    )


def _obter_criterios_cruzamento_saidas() -> dict:
    """Mapa criterio -> (fn_agrupado, fn_detalhado) usado pelo selectbox de
    _render_cruzamento_saidas() — mirror de _obter_criterios_cruzamento_
    entradas() (2026-07-25, Solicitação Técnica "BUSCA DE CORRESPONDENTES
    NAS SAÍDAS"), mas só com 2 critérios: "Busca1" (mesmo código) e
    "Busca3" (código divergente, mesma comparação e MESMA constante
    `CRITERIO_BUSCA3_NOME_XML` do Critério 3 de Entradas —
    SIMILARIDADE_DESCRICAO entre desc_xml do candidato e DESCR_ALVO;
    2026-07-28, chegou a ser renumerado "Busca2" no mesmo dia da troca
    de texto — "nas saídas transforme busca3 em 2 e mude o texto
    conforme entradas" — revertido horas depois, "vamos fixar. volte
    para o nr 3." Saídas nunca teve um Critério 2 próprio: não há
    "nome de declaração" do candidato separado de `desc_xml` pra
    comparar (a auditada é a EMITENTE, `desc_xml` já é a descrição
    dela) — só o "buraco" na numeração ficou aceito pra manter a MESMA
    constante/texto que Entradas)."""
    return {
        loader.CRITERIO_BUSCA1_MESMO_CODIGO: (
            loader.cruzar_produto_escolhido_saidas,
            loader.cruzar_produto_escolhido_saidas_detalhado,
        ),
        loader.CRITERIO_BUSCA3_NOME_XML: (
            loader.cruzar_produto_escolhido_saidas_criterio3,
            loader.cruzar_produto_escolhido_saidas_criterio3_detalhado,
        ),
        loader.CRITERIO_BUSCA4_PESQUISA_LIVRE: (
            loader.cruzar_produto_escolhido_saidas_criterio4,
            loader.cruzar_produto_escolhido_saidas_criterio4_detalhado,
        ),
    }


def _render_cruzamento_saidas(escolhido: dict) -> None:
    """Aba 'Saídas' do cruzamento (Estágio 10) — mirror de
    _render_cruzamento_entradas(), 2026-07-25, Solicitação Técnica "BUSCA
    DE CORRESPONDENTES NAS SAÍDAS": compara o produto escolhido com
    estagio8_saidas_agrupado usando o critério selecionado no selectbox.

    Só dois critérios (ver _obter_criterios_cruzamento_saidas()):

    **Busca1** (loader.cruzar_produto_escolhido_saidas()) — MESMO
    código de produto (normalizado) + SIMILARIDADE_DESCRICAO só pra
    ordenar, mesmo raciocínio do Critério 1 de Entradas.

    **Busca3** (loader.cruzar_produto_escolhido_saidas_criterio3()) —
    código DIVERGENTE do alvo, similaridade de descrição vira FILTRO
    (≥ LIMIAR_SIMILARIDADE_CRITERIO3), mesmo raciocínio e MESMO rótulo
    do Critério 3 de Entradas.

    Mesma UI de Entradas: checkbox "Salvar"/"Desfazer", botão "Salvar na
    Rubrica" (persiste com origem="saidas" em loader.salvar_cruzamento_
    confirmado()/salvar_cruzamento_confirmado_detalhado()) e tabela
    "Itens individuais" ao final. Todas as keys de widget/container
    levam sufixo "_saidas" pra não colidir com a aba de Entradas — as
    duas abas de st.tabs() rodam no MESMO script run do Streamlit.

    Descrição/Unidade EFETIVAS (2026-08-04): ver docstring de
    _render_cruzamento_entradas() pro raciocínio completo — mesmo
    `descr_efetiva`/`unid_efetiva` usados nos textos aqui."""
    criterios = _obter_criterios_cruzamento_saidas()
    criterio_busca = st.selectbox(
        "Critério de busca",
        options=list(criterios.keys()),
        key="select_criterio_busca_saidas",
    )
    fn_agrupado, fn_detalhado = criterios[criterio_busca]
    sufixo_criterio = criterio_busca.split(":", 1)[0].replace("Critério de Busca", "").strip()
    descr_efetiva = loader.descricao_efetiva_escolhido(escolhido)
    unid_efetiva = loader.unidade_efetiva_escolhido(escolhido)
    if escolhido.get("IS_ST"):
        st.caption(f"🏷️ **{descr_efetiva}** é **ST** (Substituição Tributária).")

    if criterio_busca == loader.CRITERIO_BUSCA1_MESMO_CODIGO:
        st.caption(
            f"Combinações em `estagio8_saidas_agrupado` (Saídas, Estágio 8) com o MESMO código de produto "
            f"de **{descr_efetiva}** ({escolhido['COD_ITEM']}) — Unidade: **{unid_efetiva or '—'}** — "
            "comparação normalizada (zero à esquerda em código numérico não conta como diferença) — "
            "ordenadas por "
            "similaridade de descrição (overlap de tokens) entre o produto vendido e a descrição do alvo."
        )
    elif criterio_busca == loader.CRITERIO_BUSCA4_PESQUISA_LIVRE:
        st.caption(
            f"Pesquisa livre em `estagio8_saidas_agrupado` (Saídas, Estágio 8) pra comparar com "
            f"**{descr_efetiva}** ({escolhido['COD_ITEM']}) — SEM filtro de código e SEM "
            "piso de similaridade. Útil quando o candidato certo tem pouca ou nenhuma semelhança "
            "de texto com o alvo, caso em que o Critério 3 nunca o encontraria. Digite um termo na "
            "busca abaixo (ex.: parte do nome do alvo) pra ver candidatos, incluindo o próprio "
            "produto alvo se ele aparecer em `estagio8_saidas_agrupado` — sem termo, a tabela fica "
            "oculta (evita carregar milhares de grupos de uma vez)."
        )
    else:
        st.caption(
            f"Combinações em `estagio8_saidas_agrupado` (Saídas, Estágio 8) com código DIVERGENTE (diferente) "
            f"do de **{descr_efetiva}** ({escolhido['COD_ITEM']}) — cobre o caso em que o "
            "produto é o mesmo fisicamente, mas o código na saída diverge do código oficial do "
            f"alvo. Só entram candidatos com similaridade de descrição ≥ "
            f"{loader.LIMIAR_SIMILARIDADE_CRITERIO3:.0f}% (aqui a similaridade FILTRA, não é só ordenação, "
            "já que o código não serve de evidência), ordenados por similaridade (desc)."
        )

    correspondentes, _ = fn_agrupado()
    if correspondentes.empty:
        if criterio_busca == loader.CRITERIO_BUSCA1_MESMO_CODIGO:
            st.warning(
                f"⚠️ Nenhuma combinação encontrada com o mesmo código de **{escolhido['COD_ITEM']}** "
                "em `estagio8_saidas_agrupado`, mesmo após normalizar zero à esquerda — o produto "
                "provavelmente não aparece nas saídas com esse código."
            )
        elif criterio_busca == loader.CRITERIO_BUSCA4_PESQUISA_LIVRE:
            st.warning(
                "⚠️ `estagio8_saidas_agrupado` está vazio, ou todos os grupos já pertencem a "
                "outro alvo — nada disponível pra pesquisa livre."
            )
        else:
            st.warning(
                f"⚠️ Nenhum candidato de código divergente com similaridade ≥ "
                f"{loader.LIMIAR_SIMILARIDADE_CRITERIO3:.0f}% encontrado pra **{descr_efetiva}** "
                "em `estagio8_saidas_agrupado`."
            )
        return
    if criterio_busca == loader.CRITERIO_BUSCA4_PESQUISA_LIVRE:
        st.info(
            f"📚 {len(correspondentes):,} grupo(s) na base (sem filtro de código nem similaridade) "
            "— use a busca abaixo pra encontrar candidatos.".replace(",", ".")
        )
    else:
        st.success(
            f"✅ {len(correspondentes):,} combinação(ões) encontrada(s).".replace(",", ".")
        )

    ja_confirmadas, _ = loader.consultar_cruzamento_confirmado(descr_alvo=escolhido["DESCR_ALVO"], limite=None)
    ja_confirmadas_saidas = (
        ja_confirmadas[ja_confirmadas["ORIGEM"] == "saidas"] if not ja_confirmadas.empty
        else ja_confirmadas
    )
    chaves_confirmadas = set(
        zip(ja_confirmadas_saidas["codproddecl"], ja_confirmadas_saidas["desc_xml"])
    ) if not ja_confirmadas_saidas.empty else set()

    editor_base = correspondentes[_COLUNAS_PREVIEW_CRUZAMENTO_SAIDAS_AGRUPADO].copy()
    editor_base.insert(0, "Salvar", False)
    editor_base.insert(1, "Desfazer", False)
    editor_exibicao = editor_base.rename(columns=loader.carregar_dicionario_campos())
    # estagio8_saidas_agrupado não tem "descrição_decl" — nada a remover
    # da exibição aqui (diferente de Entradas).
    editor_exibicao.insert(2, "Observação", [
        "✅ Já salvo na Rubrica" if (c, d) in chaves_confirmadas else ""
        for c, d in zip(editor_base["codproddecl"], editor_base["desc_xml"])
    ])

    # Busca por descrição do XML — ver comentário equivalente em
    # _render_cruzamento_entradas().
    termo_busca_xml = st.text_input(
        "🔎 Buscar por descrição do XML",
        key=f"busca_xml_saidas_{sufixo_criterio}",
        placeholder="Filtrar as combinações abaixo pela descrição do XML...",
    )
    if termo_busca_xml:
        mask_busca = editor_base["desc_xml"].str.contains(termo_busca_xml, case=False, na=False, regex=False)
        editor_base = editor_base[mask_busca]
        editor_exibicao = editor_exibicao.loc[editor_base.index]
        st.caption(f"{len(editor_base)} de {len(correspondentes)} combinação(ões) exibida(s).")
    elif criterio_busca == loader.CRITERIO_BUSCA4_PESQUISA_LIVRE:
        # Pesquisa livre — ver comentário equivalente em
        # _render_cruzamento_entradas().
        st.info(
            "🔎 Digite um termo de busca acima pra ver candidatos — a pesquisa livre não tem "
            "filtro de código nem de similaridade, então a tabela só aparece depois de buscar."
        )
        return

    colunas_travadas = [c for c in editor_exibicao.columns if c not in ("Salvar", "Desfazer")]
    with st.container(key="cruzamento_saidas_tabela"):
        st.markdown(
            "<style>.st-key-cruzamento_saidas_tabela [data-testid='stDataFrame'] "
            "* { font-size: 10px; }</style>",
            unsafe_allow_html=True,
        )
        editado = st.data_editor(
            editor_exibicao,
            use_container_width=True,
            hide_index=True,
            disabled=colunas_travadas,
            key=f"editor_cruzamento_saidas_{sufixo_criterio}",
        )

    st.caption(
        "Marque \"Salvar\" pra confirmar uma combinação na Rubrica; marque \"Desfazer\" pra "
        "remover uma combinação já salva (coluna \"Observação\")."
    )
    if st.button("💾 Salvar na Rubrica do Produto Alvo", key=f"btn_salvar_rubrica_saidas_{sufixo_criterio}"):
        marcadas_salvar = editado["Salvar"].reindex(editor_base.index).fillna(False)
        marcadas_desfazer = editado["Desfazer"].reindex(editor_base.index).fillna(False)
        selecionadas = editor_base.loc[
            marcadas_salvar & ~marcadas_desfazer, _COLUNAS_PREVIEW_ESTAGIO8_SAIDAS_AGRUPADO
        ]
        chaves_desfazer = set(zip(
            editor_base.loc[marcadas_desfazer, "codproddecl"],
            editor_base.loc[marcadas_desfazer, "desc_xml"],
        ))
        chaves_salvar = set(zip(selecionadas["codproddecl"], selecionadas["desc_xml"]))
        universo_chaves = chaves_salvar | chaves_desfazer
        resultado = loader.salvar_cruzamento_confirmado(
            escolhido, "saidas", criterio_busca, selecionadas, universo_chaves=universo_chaves,
        )
        detalhado_completo, _ = fn_detalhado()
        mask_universo = [
            (c, d) in universo_chaves
            for c, d in zip(detalhado_completo["codproddecl"], detalhado_completo["desc_xml"])
        ]
        universo_idunicos = set(detalhado_completo.loc[mask_universo, "idunico"])
        universo_idunicos = _ampliar_universo_idunicos_com_persistido(
            escolhido, "saidas", universo_chaves, universo_idunicos,
        )
        mask_salvar = [
            (c, d) in chaves_salvar
            for c, d in zip(detalhado_completo["codproddecl"], detalhado_completo["desc_xml"])
        ]
        itens_marcados = detalhado_completo.loc[mask_salvar, ["codproddecl", "desc_xml", "idunico"]]
        resultado_detalhado = loader.salvar_cruzamento_confirmado_detalhado(
            escolhido, "saidas", criterio_busca, itens_marcados, universo_idunicos=universo_idunicos,
        )
        if "erro" in resultado:
            st.error(f"Erro: {resultado['erro']}")
        elif "erro" in resultado_detalhado:
            st.error(f"Erro ao gravar itens individuais: {resultado_detalhado['erro']}")
        else:
            partes = [f"{resultado['total_salvo']} confirmada(s)"]
            if resultado["total_removido"]:
                partes.append(f"{resultado['total_removido']} removida(s)")
            st.success(
                f"✅ Rubrica atualizada — {', '.join(partes)} "
                f"({resultado_detalhado['total_salvo']} item(ns) individual(is) gravado(s))."
            )
            st.rerun()

    st.divider()
    detalhado, total_detalhado = loader.consultar_cruzamento_confirmado_detalhado(
        descr_alvo=escolhido["DESCR_ALVO"], origem="saidas", limite=None,
    )
    if detalhado.empty:
        st.info(
            "Nenhuma combinação confirmada na Rubrica ainda — marque \"Salvar\" na tabela acima e "
            "clique em \"Salvar na Rubrica do Produto Alvo\" pra ver os itens individuais aqui."
        )
        return
    # A suposição original (2026-07-25, mesma sessão que criou este
    # enriquecimento) de que estoque_saidas não teria ANO_ELEITO/NCM/
    # UCOM/VUNCOM/QCOM — e que este merge sempre devolveria vazio —
    # nunca foi checada com dado real; confirmado depois (mesmo achado
    # já documentado em consultar_atributos_estoque_por_idunico(), ver
    # loader.py) que TODAS as colunas esperadas existem de fato em
    # estoque_saidas: testado com a Rubrica real da geraldo (170 itens
    # de CERV SKOL LATA 350ML em Saídas), o merge veio 100% preenchido.
    atributos_por_idunico = loader.consultar_atributos_estoque_por_idunico(set(detalhado["idunico"]), origem="saidas")
    detalhado = detalhado.merge(atributos_por_idunico, left_on="idunico", right_on="ID_UNICO", how="left")
    detalhado, sumario_unidades, idunicos_tratados = loader.aplicar_tratamento_fm_detalhado(
        detalhado, origem="saidas",
    )
    # IS_ST — ver comentário equivalente em _render_cruzamento_entradas().
    detalhado["IS_ST"] = escolhido.get("IS_ST", False)

    # Diagnóstico de Unidades + aplicação de FM/Nova Unidade — ANTES da
    # tabela de Itens Individuais (2026-07-30, "quero que diagnósticos
    # de unidades venham antes da tabela de id únicos"; extensão pra
    # Saídas em 2026-07-26, "ESTENDA PARA SAIDAS E ESTOQUES") — ver
    # _render_sumario_unidades_com_aplicar().
    _render_sumario_unidades_com_aplicar(
        sumario_unidades, idunicos_tratados, escolhido,
        origem="saidas", sufixo_key="saidas",
    )

    st.divider()
    st.markdown("**Itens individuais (com ID Único) — já atribuídos ao alvo**")
    _render_kpis_itens_individuais(detalhado)
    for _col in ("vl_unit_prod", "qtde_prod", "vl_prod", "vu_utilizado", "quant_utiliz", "fm_utilizado"):
        if _col in detalhado.columns:
            detalhado[_col] = detalhado[_col].apply(lambda v: _formatar_moeda_br(v) if pd.notna(v) else "")
    st.markdown(f"**{total_detalhado:,} item(ns)** individuais gravado(s).".replace(",", "."))
    _render_itens_individuais(
        detalhado, _COLUNAS_PREVIEW_CRUZAMENTO_CONFIRMADO_DETALHADO, sufixo_key="saidas",
    )


def _obter_criterios_cruzamento_estoque() -> dict:
    """Mapa criterio -> (fn_agrupado, fn_detalhado) usado pelo selectbox de
    _render_cruzamento_estoque() — mirror de _obter_criterios_cruzamento_
    entradas() (2026-07-25, Solicitação Técnica "BUSCA DE CORRESPONDENTES
    NO ESTOQUE"), com Critério 1 (mesmo código) e Critério 2 (nome de
    declaração igual) — mesmos dois critérios de Entradas. SEM Critério 3
    (código divergente): não pedido na Solicitação Técnica."""
    return {
        loader.CRITERIO_BUSCA1_MESMO_CODIGO: (
            loader.cruzar_produto_escolhido_estoque,
            loader.cruzar_produto_escolhido_estoque_detalhado,
        ),
        loader.CRITERIO_BUSCA2_NOME_DECLARACAO_IGUAL: (
            loader.cruzar_produto_escolhido_estoque_criterio2,
            loader.cruzar_produto_escolhido_estoque_criterio2_detalhado,
        ),
        loader.CRITERIO_BUSCA4_PESQUISA_LIVRE: (
            loader.cruzar_produto_escolhido_estoque_criterio4,
            loader.cruzar_produto_escolhido_estoque_criterio4_detalhado,
        ),
    }


# "Itens individuais" do Estoque não passa pelo enriquecimento fiscal
# (loader.consultar_atributos_estoque_por_idunico()) — esse enriquecimento
# busca em estoque_entradas/estoque_saidas por ID_UNICO real de item de
# XML; o idunico do Estoque é SINTÉTICO (hash de ANO_REFERENCIA+COD_ITEM_
# DECLARACAO+DESCR_ITEM_DECLARACAO+QUANTIDADE_INICIAL+QUANTIDADE_FINAL,
# ver gerar_estagio_8_estoque()) e não existe em nenhuma das duas tabelas
# — não faz sentido tentar enriquecer com CHV_NFE/ANO_ELEITO/NCM/etc.,
# que só existem pra itens de movimentação física (XML).
# Ordem 2026-07-25 (pedido do usuário: "inclua aqui os campos: ncm4|
# unid_prod|vl_unit_prod|qte_prod|vl_total_prod|ano_ef|ano_ei|dt_decl" —
# nomes normalizados pros já usados em Entradas/Saídas, qtde_prod/vl_prod)
# — enriquecimento ao vivo por idunico sintético, ver loader.consultar_
# atributos_estoque_estoque_por_idunico().
_COLUNAS_PREVIEW_CRUZAMENTO_CONFIRMADO_DETALHADO_ESTOQUE = [
    "codproddecl", "desc_xml", "ncm4",
    "unid_prod", "vl_unit_prod", "qtde_prod", "vl_prod",
    "unid_prod_utiliz", "vu_utilizado", "quant_utiliz",
    "fm_utilizado", "TRATAMENTO",
    "ano_ef", "ano_ei", "dt_decl", "CRITERIO", "TS", "idunico", "IS_ST",
]


def _render_cruzamento_estoque(escolhido: dict) -> None:
    """Aba 'Estoque' do cruzamento (Estágio 10) — mirror de
    _render_cruzamento_entradas(), 2026-07-25, Solicitação Técnica "BUSCA
    DE CORRESPONDENTES NO ESTOQUE": compara o produto escolhido com
    estagio8_estoque_agrupado (Estágio 8.2, Bloco H) usando o critério
    selecionado no selectbox.

    Dois critérios (sem Critério 3 — ver
    _obter_criterios_cruzamento_estoque()):

    **Critério 1** (loader.cruzar_produto_escolhido_estoque()) — MESMO
    código de produto (normalizado) + SIMILARIDADE_DESCRICAO (entre
    `descrição_decl` — única descrição disponível no Bloco H — e
    `DESCR_ALVO`) só pra ordenar.

    **Critério 2** (loader.cruzar_produto_escolhido_estoque_criterio2())
    — `descrição_decl` IGUAL (normalizado) ao `DESCR_ALVO`, sem exigir
    relação de código — captura itens que a empresa declara com o nome
    correto mas com código interno que não bate com as notas fiscais
    (comum em cadastros legados, conforme a Solicitação Técnica).

    Mesma UI de Entradas/Saídas: checkbox "Salvar"/"Desfazer", botão
    "Salvar na Rubrica" (persiste com origem="estoque" em
    loader.salvar_cruzamento_confirmado()/salvar_cruzamento_confirmado_
    detalhado(), preservando o idunico SINTÉTICO do Estágio 8.2 pra
    auditoria física futura) e tabela "Itens individuais" ao final —
    aqui SEM o enriquecimento fiscal (não se aplica ao idunico
    sintético, ver _COLUNAS_PREVIEW_CRUZAMENTO_CONFIRMADO_DETALHADO_
    ESTOQUE). Todas as keys de widget/container levam sufixo "_estoque"
    pra não colidir com as abas de Entradas/Saídas — as três abas de
    st.tabs() rodam no MESMO script run do Streamlit.

    Descrição/Unidade EFETIVAS (2026-08-04): ver docstring de
    _render_cruzamento_entradas() pro raciocínio completo — mesmo
    `descr_efetiva`/`unid_efetiva` usados nos textos aqui."""
    criterios = _obter_criterios_cruzamento_estoque()
    criterio_busca = st.selectbox(
        "Critério de busca",
        options=list(criterios.keys()),
        key="select_criterio_busca_estoque",
    )
    fn_agrupado, fn_detalhado = criterios[criterio_busca]
    sufixo_criterio = criterio_busca.split(":", 1)[0].replace("Critério de Busca", "").strip()
    descr_efetiva = loader.descricao_efetiva_escolhido(escolhido)
    unid_efetiva = loader.unidade_efetiva_escolhido(escolhido)
    if escolhido.get("IS_ST"):
        st.caption(f"🏷️ **{descr_efetiva}** é **ST** (Substituição Tributária).")

    if criterio_busca == loader.CRITERIO_BUSCA1_MESMO_CODIGO:
        st.caption(
            f"Combinações em `estagio8_estoque_agrupado` (Estoque, Estágio 8.2) com o MESMO código de produto "
            f"de **{descr_efetiva}** ({escolhido['COD_ITEM']}) — Unidade: **{unid_efetiva or '—'}** — "
            "comparação normalizada (zero à esquerda em código numérico não conta como diferença) — "
            "ordenadas por similaridade de descrição (overlap de tokens) entre a descrição declarada e "
            "a do alvo."
        )
    elif criterio_busca == loader.CRITERIO_BUSCA4_PESQUISA_LIVRE:
        st.caption(
            f"Pesquisa livre em `estagio8_estoque_agrupado` (Estoque, Estágio 8.2) pra comparar "
            f"com **{descr_efetiva}** ({escolhido['COD_ITEM']}) — SEM filtro de código e "
            "SEM piso de similaridade. Útil quando o candidato certo tem pouca ou nenhuma "
            "semelhança de texto com o alvo. Digite um termo na busca abaixo (ex.: parte do nome "
            "do alvo) pra ver candidatos, incluindo o próprio produto alvo se ele aparecer em "
            "`estagio8_estoque_agrupado` — sem termo, a tabela fica oculta (evita carregar "
            "milhares de grupos de uma vez)."
        )
    else:
        st.caption(
            f"Combinações em `estagio8_estoque_agrupado` (Estoque, Estágio 8.2) cujo nome de declaração "
            f"(`descrição_decl`) é IGUAL (normalizado — maiúsculas/espaços) ao de **{descr_efetiva}** "
            f"({escolhido['COD_ITEM']}), sem exigir nenhuma relação de código — captura itens com nome "
            "correto mas código interno divergente (comum em cadastros legados)."
        )

    correspondentes, _ = fn_agrupado()
    if correspondentes.empty:
        if criterio_busca == loader.CRITERIO_BUSCA1_MESMO_CODIGO:
            st.warning(
                f"⚠️ Nenhuma combinação encontrada com o mesmo código de **{escolhido['COD_ITEM']}** "
                "em `estagio8_estoque_agrupado`, mesmo após normalizar zero à esquerda."
            )
        elif criterio_busca == loader.CRITERIO_BUSCA4_PESQUISA_LIVRE:
            st.warning(
                "⚠️ `estagio8_estoque_agrupado` está vazio, ou todos os grupos já pertencem a "
                "outro alvo — nada disponível pra pesquisa livre."
            )
        else:
            st.warning(
                f"⚠️ Nenhum item declarado com o mesmo nome de **{descr_efetiva}** encontrado "
                "em `estagio8_estoque_agrupado`."
            )
        return
    if criterio_busca == loader.CRITERIO_BUSCA4_PESQUISA_LIVRE:
        st.info(
            f"📚 {len(correspondentes):,} grupo(s) na base (sem filtro de código nem similaridade) "
            "— use a busca abaixo pra encontrar candidatos.".replace(",", ".")
        )
    else:
        st.success(
            f"✅ {len(correspondentes):,} combinação(ões) encontrada(s).".replace(",", ".")
        )

    ja_confirmadas, _ = loader.consultar_cruzamento_confirmado(descr_alvo=escolhido["DESCR_ALVO"], limite=None)
    ja_confirmadas_estoque = (
        ja_confirmadas[ja_confirmadas["ORIGEM"] == "estoque"] if not ja_confirmadas.empty
        else ja_confirmadas
    )
    chaves_confirmadas = set(
        zip(ja_confirmadas_estoque["codproddecl"], ja_confirmadas_estoque["desc_xml"])
    ) if not ja_confirmadas_estoque.empty else set()

    editor_base = correspondentes[_COLUNAS_BASE_CRUZAMENTO_ESTOQUE_AGRUPADO + ["SIMILARIDADE_DESCRICAO"]].copy()
    editor_base.insert(0, "Salvar", False)
    editor_base.insert(1, "Desfazer", False)
    editor_exibicao = editor_base.rename(columns=loader.carregar_dicionario_campos())
    # "desc_xml" não aparece na EXIBIÇÃO (Estoque só tem "descrição_decl",
    # desc_xml é só um alias interno pro esquema de persistência — ver
    # loader._COLUNAS_CRUZAMENTO_ESTOQUE_AGRUPADO).
    editor_exibicao = editor_exibicao.drop(columns=["Descricao XML"], errors="ignore")
    editor_exibicao.insert(2, "Observação", [
        "✅ Já salvo na Rubrica" if (c, d) in chaves_confirmadas else ""
        for c, d in zip(editor_base["codproddecl"], editor_base["desc_xml"])
    ])

    # Busca por descrição do XML — ver comentário equivalente em
    # _render_cruzamento_entradas(). No Estoque, "desc_xml" é um alias
    # interno de "descrição_decl" (não existe XML separado no Bloco H,
    # ver cruzar_produto_escolhido_estoque() em loader.py) — o filtro
    # funciona igual, mesmo com a coluna "Descricao XML" oculta na
    # exibição.
    termo_busca_xml = st.text_input(
        "🔎 Buscar por descrição do XML",
        key=f"busca_xml_estoque_{sufixo_criterio}",
        placeholder="Filtrar as combinações abaixo pela descrição do XML...",
    )
    if termo_busca_xml:
        mask_busca = editor_base["desc_xml"].str.contains(termo_busca_xml, case=False, na=False, regex=False)
        editor_base = editor_base[mask_busca]
        editor_exibicao = editor_exibicao.loc[editor_base.index]
        st.caption(f"{len(editor_base)} de {len(correspondentes)} combinação(ões) exibida(s).")
    elif criterio_busca == loader.CRITERIO_BUSCA4_PESQUISA_LIVRE:
        # Pesquisa livre — ver comentário equivalente em
        # _render_cruzamento_entradas().
        st.info(
            "🔎 Digite um termo de busca acima pra ver candidatos — a pesquisa livre não tem "
            "filtro de código nem de similaridade, então a tabela só aparece depois de buscar."
        )
        return

    colunas_travadas = [c for c in editor_exibicao.columns if c not in ("Salvar", "Desfazer")]
    with st.container(key="cruzamento_estoque_tabela"):
        st.markdown(
            "<style>.st-key-cruzamento_estoque_tabela [data-testid='stDataFrame'] "
            "* { font-size: 10px; }</style>",
            unsafe_allow_html=True,
        )
        editado = st.data_editor(
            editor_exibicao,
            use_container_width=True,
            hide_index=True,
            disabled=colunas_travadas,
            key=f"editor_cruzamento_estoque_{sufixo_criterio}",
        )

    st.caption(
        "Marque \"Salvar\" pra confirmar uma combinação na Rubrica; marque \"Desfazer\" pra "
        "remover uma combinação já salva (coluna \"Observação\")."
    )
    if st.button("💾 Salvar na Rubrica do Produto Alvo", key=f"btn_salvar_rubrica_estoque_{sufixo_criterio}"):
        marcadas_salvar = editado["Salvar"].reindex(editor_base.index).fillna(False)
        marcadas_desfazer = editado["Desfazer"].reindex(editor_base.index).fillna(False)
        selecionadas = editor_base.loc[
            marcadas_salvar & ~marcadas_desfazer, _COLUNAS_BASE_CRUZAMENTO_ESTOQUE_AGRUPADO
        ]
        chaves_desfazer = set(zip(
            editor_base.loc[marcadas_desfazer, "codproddecl"],
            editor_base.loc[marcadas_desfazer, "desc_xml"],
        ))
        chaves_salvar = set(zip(selecionadas["codproddecl"], selecionadas["desc_xml"]))
        universo_chaves = chaves_salvar | chaves_desfazer
        resultado = loader.salvar_cruzamento_confirmado(
            escolhido, "estoque", criterio_busca, selecionadas, universo_chaves=universo_chaves,
        )
        detalhado_completo, _ = fn_detalhado()
        mask_universo = [
            (c, d) in universo_chaves
            for c, d in zip(detalhado_completo["codproddecl"], detalhado_completo["desc_xml"])
        ]
        universo_idunicos = set(detalhado_completo.loc[mask_universo, "idunico"])
        universo_idunicos = _ampliar_universo_idunicos_com_persistido(
            escolhido, "estoque", universo_chaves, universo_idunicos,
        )
        mask_salvar = [
            (c, d) in chaves_salvar
            for c, d in zip(detalhado_completo["codproddecl"], detalhado_completo["desc_xml"])
        ]
        itens_marcados = detalhado_completo.loc[mask_salvar, ["codproddecl", "desc_xml", "idunico"]]
        resultado_detalhado = loader.salvar_cruzamento_confirmado_detalhado(
            escolhido, "estoque", criterio_busca, itens_marcados, universo_idunicos=universo_idunicos,
        )
        if "erro" in resultado:
            st.error(f"Erro: {resultado['erro']}")
        elif "erro" in resultado_detalhado:
            st.error(f"Erro ao gravar itens individuais: {resultado_detalhado['erro']}")
        else:
            partes = [f"{resultado['total_salvo']} confirmada(s)"]
            if resultado["total_removido"]:
                partes.append(f"{resultado['total_removido']} removida(s)")
            st.success(
                f"✅ Rubrica atualizada — {', '.join(partes)} "
                f"({resultado_detalhado['total_salvo']} item(ns) individual(is) gravado(s))."
            )
            st.rerun()

    st.divider()
    detalhado, total_detalhado = loader.consultar_cruzamento_confirmado_detalhado(
        descr_alvo=escolhido["DESCR_ALVO"], origem="estoque", limite=None,
    )
    if detalhado.empty:
        st.info(
            "Nenhuma combinação confirmada na Rubrica ainda — marque \"Salvar\" na tabela acima e "
            "clique em \"Salvar na Rubrica do Produto Alvo\" pra ver os itens individuais aqui."
        )
        return
    # Enriquecimento fiscal (2026-07-25, pedido do usuário: "inclua aqui
    # os campos: ncm4|unid_prod|vl_unit_prod|qte_prod|vl_total_prod|
    # ano_ef|ano_ei|dt_decl") — busca ao vivo por idunico SINTÉTICO
    # (recompõe o hash a partir de estoque_anual_consolidado e cruza com
    # H010/cadastro de produtos, ver loader.consultar_atributos_estoque_
    # estoque_por_idunico()); validado contra ESTOQUE(...).xlsx (Excel
    # de referência do usuário) — os 6 anos do CERV SKOL LATA 350ML
    # batem exato, inclusive dt_decl (último dia de fevereiro do ano_ei,
    # não um campo bruto do SPED).
    atributos_por_idunico = loader.consultar_atributos_estoque_estoque_por_idunico(set(detalhado["idunico"]))
    detalhado = detalhado.merge(atributos_por_idunico, left_on="idunico", right_on="ID_UNICO", how="left")
    detalhado, sumario_unidades, idunicos_tratados = loader.aplicar_tratamento_fm_detalhado(
        detalhado, origem="estoque",
    )
    # IS_ST — ver comentário equivalente em _render_cruzamento_entradas().
    detalhado["IS_ST"] = escolhido.get("IS_ST", False)

    # Diagnóstico de Unidades + aplicação de FM/Nova Unidade — ANTES da
    # tabela de Itens Individuais (2026-07-30, "quero que diagnósticos
    # de unidades venham antes da tabela de id únicos"; extensão pro
    # Estoque em 2026-07-26, "ESTENDA PARA SAIDAS E ESTOQUES") — ver
    # _render_sumario_unidades_com_aplicar(). idunico do Estoque é
    # SINTÉTICO (hash), mas a persistência de tratamento não depende de
    # como o idunico foi gerado, só que seja determinístico — funciona
    # igual às outras 2 origens.
    _render_sumario_unidades_com_aplicar(
        sumario_unidades, idunicos_tratados, escolhido,
        origem="estoque", sufixo_key="estoque",
    )

    st.divider()
    st.markdown("**Itens individuais (com ID Único) — já atribuídos ao alvo**")
    _render_kpis_itens_individuais(detalhado)
    for _col in ("vl_unit_prod", "qtde_prod", "vl_prod", "vu_utilizado", "quant_utiliz", "fm_utilizado"):
        if _col in detalhado.columns:
            detalhado[_col] = detalhado[_col].apply(lambda v: _formatar_moeda_br(v) if pd.notna(v) else "")
    st.markdown(f"**{total_detalhado:,} item(ns)** individuais gravado(s).".replace(",", "."))
    _render_itens_individuais(
        detalhado, _COLUNAS_PREVIEW_CRUZAMENTO_CONFIRMADO_DETALHADO_ESTOQUE, sufixo_key="estoque",
    )


_COLUNAS_PRODUTOS_ALVO_SALVOS = [
    "DESCR_ALVO", "COD_ITEM", "UNID_ALVO", "UNID_EDITADA", "DESCR_EDITADA", "IS_ST",
]
_COLUNA_CHECKBOX_PRODUTOS_ALVO_SALVOS = "🎯 Escolher p/ Cruzamento"
# Rótulos de exibição (ver DICIONARIO DE CAMPOS.txt) — usados pra achar
# as colunas DEPOIS do rename via loader.carregar_dicionario_campos().
# DESCR_EDITADA (2026-08-04): chegou a ser editável no Estágio 7.3.2
# (_render_grupo_produto_alvo_fiscalizacao()) — o usuário pediu pra
# reverter aquilo e mover a edição pra cá, mesmo padrão já usado pro
# IS_ST (campo informativo, editado só nesta tela). UNID_ALVO é SEMPRE
# só leitura (valor original transportado do Estágio 7.1, nunca
# editado em lugar nenhum) — `UNID_EDITADA` é o campo editável
# separado (mesma ideia de DESCR_ALVO/DESCR_EDITADA), pra não perder o
# valor original quando o auditor corrige a unidade.
_COLUNA_LABEL_UNID_EDITADA = "Unidade Editada"
_COLUNA_LABEL_DESCR_EDITADA = "Descricao Editada"
_COLUNA_IS_ST_PRODUTOS_ALVO_SALVOS = "E ST (Substituicao Tributaria)"

# Cruzamento Final do Produto (Estágio 10.2, 2026-08-05) — colunas de
# exibição da grade (ordem da Solicitação Técnica original: "Ano |
# DescrProd | Aliq | ST | QtdeEI | QtdeC | QtdeV | QtdeEF | MediaPuC |
# MediaPuV | MediaPuE", com "UP" [Unidade de Produto] inserida logo após
# DescrProd — ajuste pedido pelo usuário no mesmo dia: "faltou o campo
# 'UP'"; TD/QtdeC.../QtdeEF/TC/Infração inseridos em 2026-08-06,
# Solicitação Técnica "ENRIQUECIMENTO DO CRUZAMENTO FINAL": "Ano |
# DescrProd | Aliq | ST | QtdeEI | QtdeC | TD | QtdeV | QtdeEF | TC |
# Infração | MediaPuC | MediaPuV | MediaPuE"; DIF_QTDE (=abs(TD-TC))
# inserida logo após Infração no mesmo dia, pedido separado: "crie campo
# 'DifQtde' (TD-TC com valor absoluto)"; PU_SUGERIDO/CONDICAO_PU/
# AGREGACAO inseridos logo em seguida, mesmo dia, Solicitação Técnica
# "LÓGICA DE PREÇO UNITÁRIO E DIVERGÊNCIA": "... TC | Infração |
# DifQtde | PU Sugerido | Condição PU | Agregação | MediaPuC | MediaPuV
# | MediaPuE"; BASE_CALCULO (=PU_SUGERIDO×DIF_QTDE) inserida logo após
# PU_SUGERIDO em 2026-08-06, Solicitação Técnica "PERSISTÊNCIA
# AUTOMÁTICA E VALORAÇÃO DO RISCO", pedido explícito "preferencialmente
# após 'PU Sugerido'"; ICMS/MULTA/CREDITO_TRIBUTARIO inseridos logo após
# BASE_CALCULO, mesmo dia, Solicitação Técnica "LIQUIDAÇÃO TRIBUTÁRIA DO
# CRUZAMENTO": "... BaseCalculo | Icms | Multa | Crédito Tributário |
# ..."). DESCR_ALVO/COD_ITEM/TS (identidade/upsert) não aparecem na
# grade — recompostos a partir de `escolhido_atual` na hora de salvar
# (ver loader.salvar_cruzamento_final_produto()).
_COLUNAS_EXIBICAO_CRUZAMENTO_FINAL_PRODUTO = [
    "ANO", "DESCR_PROD", "UP", "ALIQ", "ST", "QTDE_EI", "QTDE_C", "TD", "QTDE_V", "QTDE_EF",
    "TC", "INFRACAO_FINAL", "DIF_QTDE", "PU_SUGERIDO", "BASE_CALCULO",
    "ICMS", "MULTA", "CREDITO_TRIBUTARIO", "CONDICAO_PU", "AGREGACAO",
    "MEDIA_PU_C", "MEDIA_PU_V", "MEDIA_PU_E",
]


def render_produtos_alvo_salvos() -> None:
    """Painel 'PRODUTOS ALVOS SALVOS' (2026-07-23, Solicitação Técnica:
    "SERÁ UM PAINEL EM QUE ESCOLHEREU UM PRODUTO A SER CRUZADO"): lista
    os produtos já salvos e ativos no Grupo de Produto Alvo (Estágio
    7.3.2, produto_alvo_fiscalizacao) e deixa o auditor ESCOLHER um
    deles como o produto que será objeto do cruzamento — escolha
    persistida (loader.escolher_produto_cruzamento()), substituindo
    qualquer escolha anterior (só existe um produto escolhido por vez,
    diferente do GRUPO salvo, que pode ter vários).

    Tabela reduzida a Cód. Produto + Descrição Relevante (2026-07-23,
    pedido do usuário: "mantenha cod e descrição" — antes trazia
    Divergência/Infração/%Diverg também, depois disso foi enxugado pra
    só as 2 colunas de identificação) e a ESCOLHA passou a ser feita
    dentro da própria tabela via checkbox (antes era um st.selectbox
    separado abaixo — "a escolha deve ser nessa tabela para economizar
    espaço"), mesmo padrão de st.data_editor com coluna de checkbox já
    usado em _render_grupo_produto_alvo_fiscalizacao() (7.3.2): sem
    on_select, extração do estado marcado sempre por índice (.reindex).
    Só um produto pode estar marcado por vez (mesma regra de
    escolher_produto_cruzamento(), que só guarda 1 linha) — o botão
    valida isso e avisa se 0 ou mais de 1 estiverem marcados.

    Descrição Editada/Unidade Editada (2026-08-04): editáveis nesta
    tabela junto com "É ST" — botão "💾 Salvar Edições" salva os 3 campos
    de uma vez (loader.salvar_edicoes_produto_alvo_salvos(), UPDATE
    parcial por chave). Chegaram a ser editáveis no Estágio 7.3.2
    (Solicitação Técnica original), usuário pediu pra reverter aquilo e
    mover a edição pra cá, mesmo padrão já usado pro IS_ST. Unidade
    Editada (`UNID_EDITADA`) é um campo SEPARADO de Unidade Relevante
    (`UNID_ALVO`, sempre só leitura, valor original transportado do
    Estágio 7.1) — 1ª tentativa deixava UNID_ALVO editável direto e
    perdia o original a cada correção de unidade; usuário pediu campo
    novo, mesmo padrão de Descrição Relevante/Descrição Editada. Valor
    EFETIVO pra qualquer consumidor futuro (Estágio 15): UNID_EDITADA
    quando preenchido, senão UNID_ALVO.

    Termina com a seção "🔀 Busca de Produtos Correspondentes" (rótulo
    ajustado 2026-07-23, era "Cruzamento") — aba "📥 Entradas" com o
    Critério 1 (mesmo código de produto + similaridade de descrição
    contra estagio8_agrupado, ver _render_cruzamento_entradas_
    criterio1()/loader.cruzar_produto_escolhido_entradas()); mais
    critérios/abas (Saídas, Estoques) ficam pra próximas rodadas.

    Depois das 3 abas, "⚖️ Cruzamento Final do Produto" (Estágio 10.2,
    2026-08-05) — ver _render_cruzamento_final_produto()."""
    st.subheader("Estágio 10 - Produtos Alvos Salvos")
    st.caption(
        "Produtos já marcados como ativos no Grupo de Produto Alvo (Estágio 7.3.2). Marque "
        "\"Escolher p/ Cruzamento\" pra um deles e confirme abaixo. Descrição Editada, Unidade "
        "Editada e É ST são editáveis (Unidade Relevante continua travada — é o valor original) "
        "— use \"💾 Salvar Edições\" pra gravar."
    )

    grupo, total = loader.consultar_grupo_produto_alvo_fiscalizacao(limite=None, apenas_ativos=True)
    if grupo.empty:
        st.info(
            'Nenhum produto salvo ainda — marque produtos em "📈 7.3.2: SIMULAÇÃO RN1 (+30%)" '
            'primeiro (checkbox "Selecionar p/ Fiscalização" + botão "Salvar Grupo de Produto Alvo").'
        )
        return

    escolhido_atual = loader.consultar_produto_cruzamento_escolhido()
    if escolhido_atual:
        st.success(
            f"🎯 Produto atualmente escolhido pra cruzamento: "
            f"**{loader.descricao_efetiva_escolhido(escolhido_atual)}** "
            f"(Cód. {escolhido_atual['COD_ITEM']}) — escolhido em {escolhido_atual['TS']}."
            + _badge_st(escolhido_atual)
        )

    st.markdown(f"**{total:,} produto(s)** no grupo salvo.".replace(",", "."))

    editor_base = grupo[_COLUNAS_PRODUTOS_ALVO_SALVOS].drop_duplicates().reset_index(drop=True)
    editor_base.insert(
        0, _COLUNA_CHECKBOX_PRODUTOS_ALVO_SALVOS,
        editor_base["DESCR_ALVO"].eq(escolhido_atual["DESCR_ALVO"]) if escolhido_atual else False,
    )
    editor_exibicao = editor_base.rename(columns=loader.carregar_dicionario_campos())
    colunas_editaveis = (
        _COLUNA_CHECKBOX_PRODUTOS_ALVO_SALVOS, _COLUNA_LABEL_UNID_EDITADA,
        _COLUNA_LABEL_DESCR_EDITADA, _COLUNA_IS_ST_PRODUTOS_ALVO_SALVOS,
    )
    colunas_travadas = [c for c in editor_exibicao.columns if c not in colunas_editaveis]
    with st.container(key="produtos_alvo_salvos_tabela"):
        st.markdown(
            "<style>.st-key-produtos_alvo_salvos_tabela [data-testid='stDataFrame'] "
            "* { font-size: 12px; }</style>",
            unsafe_allow_html=True,
        )
        editado = st.data_editor(
            editor_exibicao,
            use_container_width=True,
            hide_index=True,
            disabled=colunas_travadas,
            key="editor_produtos_alvo_salvos",
        )

    # "É ST" (Substituição Tributária, 2026-07-29, pedido do usuário:
    # "crie uma campo para selecionar e o produto é ST") — botão PRÓPRIO,
    # independente de "Confirmar produto pra cruzamento" (que só afeta 1
    # produto por vez): salva o estado de TODOS os produtos exibidos de
    # uma vez, via loader.salvar_edicoes_produto_alvo_salvos() (UPDATE
    # parcial só das colunas editáveis, preserva o resto do grupo
    # intocado). Descrição Editada/Unidade Editada (2026-08-04) se
    # juntaram ao mesmo botão/UPDATE — chegaram a ser editáveis no
    # Estágio 7.3.2, usuário pediu pra mover pra cá, mesmo padrão de
    # campo puramente informativo (confirmado via AskUserQuestion) que
    # não influencia nenhum cálculo ainda. UNID_ALVO (Unidade Relevante)
    # NÃO entra em `atualizacoes` — é sempre só leitura, o campo
    # editável correspondente é UNID_EDITADA (separado, pra não perder
    # o valor original transportado do Estágio 7.1).
    if st.button("💾 Salvar Edições", key="btn_salvar_st_produtos_alvo"):
        atualizacoes = editor_base[["DESCR_ALVO", "COD_ITEM"]].copy()
        atualizacoes["IS_ST"] = (
            editado[_COLUNA_IS_ST_PRODUTOS_ALVO_SALVOS].reindex(editor_base.index).fillna(False)
        )
        atualizacoes["UNID_EDITADA"] = (
            editado[_COLUNA_LABEL_UNID_EDITADA].reindex(editor_base.index).fillna("")
        )
        atualizacoes["DESCR_EDITADA"] = (
            editado[_COLUNA_LABEL_DESCR_EDITADA].reindex(editor_base.index).fillna("")
        )
        resultado_st = loader.salvar_edicoes_produto_alvo_salvos(atualizacoes)
        if "erro" in resultado_st:
            st.error(f"Erro: {resultado_st['erro']}")
        else:
            st.success(f"✅ {resultado_st['total_atualizado']} produto(s) atualizado(s).")
            st.rerun()

    if st.button("🎯 Confirmar produto pra cruzamento", key="btn_confirmar_produto_cruzamento"):
        marcados = editado[_COLUNA_CHECKBOX_PRODUTOS_ALVO_SALVOS].reindex(editor_base.index).fillna(False)
        marcadas = editor_base.loc[marcados]
        if marcadas.empty:
            st.warning("Nenhum produto marcado — marque \"Escolher p/ Cruzamento\" antes de confirmar.")
        elif len(marcadas) > 1:
            st.warning("Marque só UM produto por vez — desmarque os outros antes de confirmar.")
        else:
            linha = marcadas.iloc[0]
            resultado = loader.escolher_produto_cruzamento(linha["DESCR_ALVO"], linha["COD_ITEM"])
            if "erro" in resultado:
                st.error(f"Erro: {resultado['erro']}")
            else:
                st.success(f"✅ Produto '{linha['DESCR_ALVO']}' escolhido pra cruzamento.")
                st.rerun()

    st.divider()
    st.markdown("### 🔀 Busca de Produtos Correspondentes")
    if not escolhido_atual:
        st.info("Escolha um produto acima pra ver o cruzamento com o Estágio 8.")
    else:
        # Execução Automática da Rubrica (Estágio 10.1, Solicitação Técnica
        # 2026-07-30) — botão posicionado à DIREITA da linha de abas.
        # PRIMEIRA versão usava st.columns([4, 1.4]) com as abas dentro da
        # coluna larga — funcionava visualmente, mas encolhia TODO o
        # conteúdo de dentro das abas (tabelas de correspondências, Itens
        # Individuais, Sumário de Unidades) pra 4/5.4 da largura da tela,
        # já que o container das abas fica travado na largura de onde foi
        # criado (2026-07-30, achado do usuário: "as tabelas inferiores
        # estão mais estreitas"). Corrigido com CSS (posicionamento
        # absoluto) em vez de coluna: as abas continuam sendo criadas em
        # LARGURA TOTAL (sem nenhuma coluna estreitando), e só o botão
        # fica flutuando por cima, no canto superior direito do container
        # — mesmo truque de CSS-por-key já usado noutras telas deste
        # arquivo (`.st-key-...`), aqui pra LAYOUT em vez de font-size.
        chave_header = "cruzamento_estagio10_header"
        chave_botao = "cruzamento_estagio10_botao_automatico"
        with st.container(key=chave_header):
            st.markdown(
                f"""
                <style>
                .st-key-{chave_header} {{ position: relative !important; }}
                .st-key-{chave_botao} {{
                    position: absolute !important;
                    top: 0.3rem !important;
                    right: 0 !important;
                    z-index: 10 !important;
                    width: auto !important;
                }}
                </style>
                """,
                unsafe_allow_html=True,
            )
            with st.container(key=chave_botao):
                clicou_automatico = st.button(
                    "⚡ Execução Automática (Crit. 1-3 | Confiança > 60% | + FM)",
                    key="btn_execucao_automatica_rubrica",
                )
            # Barras de progresso (2026-07-30, pedido do usuário: "ao
            # pressionar equalização automática, criar barra de progresso
            # para acompanhar") — renderizadas FORA do container estreito
            # do botão (que fica flutuando/posicionado em cima das abas,
            # sem espaço pra uma barra legível), em largura total, logo
            # abaixo da linha de abas. loader.executar_confirmacao_
            # automatica_rubrica()/executar_aplicacao_automatica_fm()
            # chamam `callback(origem, [criterio,] indice, total)` ao
            # final de cada passo (7 critérios + 3 origens de FM) — usado
            # aqui pra avançar a barra em tempo real, mesmo padrão de
            # `_barra_progresso()` já usado na tela de Extração.
            if clicou_automatico:
                barra_rubrica = st.progress(0.0, text="Confirmando correspondências...")

                def _cb_rubrica(origem: str, criterio: str, indice: int, total: int) -> None:
                    rotulo_criterio = criterio.split(":", 1)[0]
                    barra_rubrica.progress(
                        indice / total, text=f"{indice}/{total}: {origem} — {rotulo_criterio}",
                    )

                resultado_auto = loader.executar_confirmacao_automatica_rubrica(
                    escolhido_atual, callback=_cb_rubrica,
                )
                if "erro" in resultado_auto:
                    barra_rubrica.empty()
                    st.error(f"Erro: {resultado_auto['erro']}")
                else:
                    barra_rubrica.progress(1.0, text="Correspondências confirmadas.")
                    # "Próximo passo" (2026-07-30, Solicitação Técnica:
                    # "aplique nos mesmos moldes fm caso seja > 1") —
                    # depois de confirmar as correspondências, aplica
                    # automaticamente o FM sugerido em toda UP com "FM
                    # Sug" > 1, mesmo botão/clique — ver loader.
                    # executar_aplicacao_automatica_fm().
                    barra_fm = st.progress(0.0, text="Aplicando FM sugerido...")

                    def _cb_fm(origem: str, indice: int, total: int) -> None:
                        barra_fm.progress(indice / total, text=f"{indice}/{total}: {origem}")

                    resultado_fm = loader.executar_aplicacao_automatica_fm(
                        escolhido_atual, callback=_cb_fm,
                    )
                    barra_fm.progress(1.0, text="FM aplicado.")
                    for erro in resultado_auto["erros"]:
                        st.warning(f"⚠️ Rubrica — {erro}")
                    if "erro" in resultado_fm:
                        st.warning(f"⚠️ FM: {resultado_fm['erro']}")
                    else:
                        for erro in resultado_fm["erros"]:
                            st.warning(f"⚠️ FM — {erro}")
                    partes_origem = ", ".join(
                        f"{n} em {o}" for o, n in resultado_auto["por_origem"].items()
                    )
                    detalhe = f" ({partes_origem})" if partes_origem else ""
                    total_fm = resultado_fm.get("total_aplicado", 0) if "erro" not in resultado_fm else 0
                    partes_fm = ", ".join(
                        f"{n} em {o}" for o, n in resultado_fm.get("por_origem", {}).items()
                    )
                    detalhe_fm = f" ({partes_fm})" if partes_fm else ""
                    st.success(
                        f"✅ +{resultado_auto['total_adicionado']} item(ns) adicionados à Rubrica"
                        f"{detalhe}; {total_fm} item(ns) com FM aplicado{detalhe_fm}."
                    )
                    st.rerun()
            aba_cruzamento_entradas, aba_cruzamento_saidas, aba_cruzamento_estoque = st.tabs(
                ["📥 Entradas", "📤 Saídas", "📦 Estoque"]
            )
        with aba_cruzamento_entradas:
            _render_cruzamento_entradas(escolhido_atual)
        with aba_cruzamento_estoque:
            _render_cruzamento_estoque(escolhido_atual)
        with aba_cruzamento_saidas:
            _render_cruzamento_saidas(escolhido_atual)

        st.divider()
        _render_cruzamento_final_produto(escolhido_atual)


def _render_cruzamento_final_produto(escolhido: dict) -> None:
    """Estágio 10.2 — "⚖️ 10.2 Cruzamento Final do Produto" (Solicitação
    Técnica 2026-08-05): posicionado no final da página do Estágio 10,
    depois das 3 abas de busca/Rubrica. Consolida os itens já
    confirmados na Rubrica (Entradas/Saídas/Estoque) do produto
    `escolhido`, com o tratamento de Fator Multiplicador já aplicado
    (loader.gerar_cruzamento_final_produto()), num resumo editável por
    ano — preparação pro Estágio 15 (ainda não implementado).

    Recuperação Automática (2026-08-06, Solicitação Técnica
    "PERSISTÊNCIA AUTOMÁTICA E VALORAÇÃO DO RISCO"): na 1ª vez que a
    tela é aberta pra um produto (nada ainda em st.session_state pra
    ele), busca automaticamente o que já foi salvo em cruzamento_final_
    produto (loader.consultar_cruzamento_final_produto(descr_alvo=...))
    — o auditor não precisa clicar em nada pra continuar de onde parou
    (ex.: uma Alíquota corrigida à mão numa sessão anterior). Mostra
    "📂 Carregados dados salvos anteriormente." só na 1ª renderização
    depois do auto-load (flag consumida com `.pop()`, não reaparece nos
    reruns seguintes — inclusive os disparados pelo próprio
    st.data_editor a cada edição de célula). Trocar de produto escolhido
    dispara um NOVO auto-load, independente (chave por produto).

    2 botões, mesmo padrão de "editar depois salvar" já usado no Sumário
    de Unidades/Produtos Alvos Salvos (Estágio 10):
    - "⚖️ Efetuar Cruzamento do Produto": função de "Recalcular/Resetar
      a partir da Rubrica" (2026-08-06) — (re)calcula a grade do ZERO a
      partir da verdade física atual (Rubrica) e SOBRESCREVE o que
      estiver em st.session_state (carregado do banco ou editado na
      tela), guardando por produto (trocar de produto escolhido não
      mistura a grade de um com o de outro). Respeita o Período de
      Auditoria configurado no Estágio 1/EXTRAÇÃO (loader.gerar_
      cruzamento_final_produto() já filtra por ele) — 2026-08-05,
      pedido do usuário: "observe o período a ser fiscalizado definido
      em EXTRAÇÃO".
    - "💾 Salvar Cruzamento Final do Produto": grava o estado ATUAL da
      grade (já com os ajustes finos do auditor — Alíquota/ST/TD/TC/
      Infração/Base de Cálculo/quantidades/preços médios) em
      cruzamento_final_produto, upsert por produto (loader.salvar_
      cruzamento_final_produto()).

    TD/TC/INFRACAO_FINAL (2026-08-06, Solicitação Técnica
    "ENRIQUECIMENTO DO CRUZAMENTO FINAL"): calculados por loader.
    gerar_cruzamento_final_produto() (TD=QTDE_EI+QTDE_C, TC=QTDE_V+
    QTDE_EF, INFRACAO_FINAL="E sem NF"/"V sem NF"/"" conforme
    TD<TC/TD>TC/TD==TC), mas EDITÁVEIS na grade como qualquer outro
    campo — o auditor pode sobrescrever se a divergência física for
    justificada por outro meio (ex.: perda, quebra, bonificação).
    DIF_QTDE (mesmo dia, pedido separado: "crie campo 'DifQtde' [TD-TC
    com valor absoluto]") = abs(TD-TC), logo após Infração — magnitude
    da divergência, sem depender do sinal (a direção já está em
    INFRACAO_FINAL).

    PU_SUGERIDO/CONDICAO_PU/AGREGACAO (mesmo dia, Solicitação Técnica
    "LÓGICA DE PREÇO UNITÁRIO E DIVERGÊNCIA"): loader.gerar_cruzamento_
    final_produto() elege o preço unitário oficial da infração (4
    sub-cenários da regra RN1 original — ver docstring de lá), também
    editáveis aqui — o auditor pode forçar um PU/condição diferente.

    BASE_CALCULO (mesmo dia, Solicitação Técnica "PERSISTÊNCIA
    AUTOMÁTICA E VALORAÇÃO DO RISCO") = PU_SUGERIDO×DIF_QTDE, logo após
    "PU Sugerido" — valor em R$ da omissão daquele ano/produto.

    ICMS/MULTA/CREDITO_TRIBUTARIO (mesmo dia, Solicitação Técnica
    "LIQUIDAÇÃO TRIBUTÁRIA DO CRUZAMENTO"), logo após "Base de Cálculo":
    ICMS=BASE_CALCULO×(ALIQ/100), MULTA=ICMS×0,75 (penalidade de 75%),
    CREDITO_TRIBUTARIO=ICMS+MULTA (risco financeiro total da linha) —
    fecha a camada financeira do Estágio 10.2. Todos editáveis, como o
    resto da grade — o auditor pode ajustar ICMS/multa manualmente em
    casos de redução de base ou multa isolada."""
    st.markdown("### ⚖️ 10.2 Cruzamento Final do Produto")
    st.caption(
        "Consolida os itens confirmados na Rubrica (Entradas/Saídas/Estoque) — já com o "
        "tratamento de Fator Multiplicador aplicado — num resumo por ano, restrito ao Período de "
        "Auditoria configurado em \"🛠️ 1: PROCEDIMENTOS INICIAIS\". Ajuste o que precisar na grade antes de "
        "\"💾 Salvar Cruzamento Final do Produto\"."
    )
    # Chave de cache por PRODUTO (COD_ITEM, fallback DESCR_ALVO — mesmo
    # raciocínio de loader._chave_produto_alvo_fiscalizacao(), sem
    # chamar a função privada daqui: interface.py só chama funções
    # públicas do loader) — trocar de produto escolhido não mistura a
    # grade de um com o de outro.
    chave_grade = f"cruzamento_final_produto_grade_{escolhido.get('COD_ITEM') or escolhido['DESCR_ALVO']}"

    # Recuperação Automática (2026-08-06) — só na 1ª vez que a tela é
    # aberta pra este produto (chave_grade ainda não em session_state);
    # NUNCA roda de novo a cada rerun (o próprio st.data_editor dispara
    # rerun a cada edição de célula) — senão apagaria edições em
    # andamento ainda não salvas. Flag "_recem_carregado" consumida via
    # `.pop()` — mostra a nota só nesta renderização, some sozinha nos
    # reruns seguintes.
    if chave_grade not in st.session_state:
        persistido, _ = loader.consultar_cruzamento_final_produto(
            descr_alvo=escolhido["DESCR_ALVO"], limite=None,
        )
        if not persistido.empty:
            st.session_state[chave_grade] = persistido
            st.session_state[f"{chave_grade}_recem_carregado"] = True

    if st.session_state.pop(f"{chave_grade}_recem_carregado", False):
        st.info("📂 Carregados dados salvos anteriormente.")

    if st.button(
        "⚖️ Efetuar Cruzamento do Produto", key="btn_efetuar_cruzamento_final_produto",
        help=(
            "Recalcula a grade DO ZERO a partir da Rubrica (Entradas/Saídas/Estoque) — "
            "sobrescreve o que estiver salvo/editado na tela agora."
        ),
    ):
        grade = loader.gerar_cruzamento_final_produto(escolhido)
        if grade.empty:
            st.session_state.pop(chave_grade, None)
            st.warning(
                "Nenhum item confirmado na Rubrica (Entradas/Saídas/Estoque) pra este produto "
                "dentro do Período de Auditoria configurado — confirme correspondências nas abas "
                "acima ou revise o período em \"🛠️ 1: PROCEDIMENTOS INICIAIS\"."
            )
        else:
            st.session_state[chave_grade] = grade

    grade_atual = st.session_state.get(chave_grade)
    if grade_atual is None:
        return

    rotulos = {c: loader.carregar_dicionario_campos().get(c, c) for c in _COLUNAS_EXIBICAO_CRUZAMENTO_FINAL_PRODUTO}
    grade_exibicao = grade_atual[_COLUNAS_EXIBICAO_CRUZAMENTO_FINAL_PRODUTO].rename(columns=rotulos)
    with st.container(key="cruzamento_final_produto_tabela"):
        st.markdown(
            "<style>.st-key-cruzamento_final_produto_tabela [data-testid='stDataFrame'] "
            "* { font-size: 10px; }</style>",
            unsafe_allow_html=True,
        )
        grade_editada = st.data_editor(
            grade_exibicao,
            use_container_width=True,
            hide_index=True,
            column_config={
                rotulos["ALIQ"]: st.column_config.NumberColumn(format="%.0f"),
                rotulos["QTDE_EI"]: st.column_config.NumberColumn(format="%,.2f"),
                rotulos["QTDE_C"]: st.column_config.NumberColumn(format="%,.2f"),
                rotulos["TD"]: st.column_config.NumberColumn(format="%,.2f"),
                rotulos["QTDE_V"]: st.column_config.NumberColumn(format="%,.2f"),
                rotulos["QTDE_EF"]: st.column_config.NumberColumn(format="%,.2f"),
                rotulos["TC"]: st.column_config.NumberColumn(format="%,.2f"),
                rotulos["DIF_QTDE"]: st.column_config.NumberColumn(format="%,.2f"),
                rotulos["PU_SUGERIDO"]: st.column_config.NumberColumn(format="%,.2f"),
                rotulos["BASE_CALCULO"]: st.column_config.NumberColumn(format="%,.2f"),
                rotulos["ICMS"]: st.column_config.NumberColumn(format="%,.2f"),
                rotulos["MULTA"]: st.column_config.NumberColumn(format="%,.2f"),
                rotulos["CREDITO_TRIBUTARIO"]: st.column_config.NumberColumn(format="%,.2f"),
                rotulos["MEDIA_PU_C"]: st.column_config.NumberColumn(format="%,.2f"),
                rotulos["MEDIA_PU_V"]: st.column_config.NumberColumn(format="%,.2f"),
                rotulos["MEDIA_PU_E"]: st.column_config.NumberColumn(format="%,.2f"),
            },
            key="editor_cruzamento_final_produto",
        )

    if st.button("💾 Salvar Cruzamento Final do Produto", key="btn_salvar_cruzamento_final_produto"):
        gravar = grade_editada.rename(columns={v: k for k, v in rotulos.items()})
        resultado_final = loader.salvar_cruzamento_final_produto(escolhido, gravar)
        if "erro" in resultado_final:
            st.error(f"Erro: {resultado_final['erro']}")
        else:
            st.session_state[chave_grade] = gravar[_COLUNAS_EXIBICAO_CRUZAMENTO_FINAL_PRODUTO]
            st.success(f"✅ {resultado_final['total_anos']} ano(s) gravado(s) no Cruzamento Final do Produto.")


def render_pagina_produtos_alvo_salvos() -> None:
    """Painel 'ESTÁGIO 10 - PRODUTOS ALVOS SALVOS' (batizado assim
    2026-07-28 — antes chamado só de "Botão 9" nos comentários daqui
    até essa data, criado 2026-07-23), botão da 2ª linha do Menu
    Principal: ver loader.consultar_grupo_produto_alvo_fiscalizacao()/
    render_produtos_alvo_salvos(). Exige dados_carregados (mesmo
    padrão das outras páginas)."""
    _botao_voltar_menu()
    if not st.session_state.get("dados_carregados"):
        st.info('Carregue os dados primeiro em "🛠️ 1: PROCEDIMENTOS INICIAIS".')
        return
    render_produtos_alvo_salvos()


# Consolidado Geral do Cruzamento Final (Estágio 11, 2026-08-06) —
# colunas de exibição, ordem EXATA pedida na Solicitação Técnica: "Ano |
# DescrProd | UP | ST | Aliq | QtdeEI | QtdeC | TD | QtdeV | QtdeEF | TC
# | Infração | DifQtde | PU Sugerido | MediaPuC | MediaPuV" — recorte da
# grade completa do Estágio 10.2 (sem DESCR_ALVO/COD_ITEM/TS/CONDICAO_PU/
# AGREGACAO/MEDIA_PU_E, que ficam só na exportação CSV completa).
_COLUNAS_CONSOLIDADO_11 = [
    "ANO", "DESCR_PROD", "UP", "ST", "ALIQ", "QTDE_EI", "QTDE_C", "TD", "QTDE_V", "QTDE_EF",
    "TC", "INFRACAO_FINAL", "DIF_QTDE", "PU_SUGERIDO", "MEDIA_PU_C", "MEDIA_PU_V",
]
# Colunas numéricas de quantidade/valor exibidas em padrão BR (milhar '.',
# decimal ',') — mesmo padrão de _formatar_moeda_br() já usado nas
# tabelas somente-leitura de alta densidade deste projeto (Itens
# Individuais, Estágio 10). ALIQ vira percentual à parte (ver abaixo).
_COLUNAS_NUMERICAS_CONSOLIDADO_11 = (
    "QTDE_EI", "QTDE_C", "TD", "QTDE_V", "QTDE_EF", "TC", "DIF_QTDE", "PU_SUGERIDO", "MEDIA_PU_C", "MEDIA_PU_V",
)


def render_consolidado_cruzamento_11() -> None:
    """Estágio 11 — "📊 11: CONSOLIDADO GERAL (RN1)" (Solicitação
    Técnica 2026-08-06: "CONSOLIDADO DO CRUZAMENTO FINAL"): visão MACRO
    — lê `cruzamento_final_produto` INTEIRA (loader.consultar_
    consolidado_cruzamento_11(), todos os produtos já cruzados no
    Estágio 10.2), diferente do Estágio 10.2 (curadoria de 1 produto
    por vez). Somente leitura (`st.dataframe`, não `st.data_editor` —
    "garantir a integridade dos dados finais", pedido explícito) —
    correções continuam sendo feitas voltando ao Estágio 10.2.

    3 filtros de topo (Ano/Tipo de Infração — `st.multiselect`, começam
    com tudo marcado; busca por Descrição — `st.text_input`, substring
    case-insensitive) aplicados sobre o resultado JÁ carregado (não
    reconsultam o banco a cada mudança de filtro). Alta densidade (10px,
    mesmo padrão CSS-por-key do resto do Estágio 10) + formatação BR
    (milhar/decimal) nas colunas de quantidade/valor e percentual em
    Alíquota — como é `st.dataframe` (não editável), pré-formata como
    string ANTES de exibir (mesma solução já usada nas tabelas de Itens
    Individuais — `column_config.NumberColumn` não tem padrão BR).

    Exportação CSV (mesmo padrão de segurança já usado no resto do
    projeto pra tabelas grandes — Entradas de Terceiros, BC3, Estágio 8:
    só monta o CSV quando o auditor clica "Preparar exportação completa
    (CSV)", não a cada redesenho da tela): exporta o recorte FILTRADO
    (Ano/Infração/Descrição aplicados) mas com TODAS as colunas do
    schema (não só as 16 exibidas na tela — inclui DESCR_ALVO/COD_ITEM/
    TS/CONDICAO_PU/AGREGACAO/MEDIA_PU_E, úteis fora da tela mas raros
    demais pra ocupar espaço na grade principal)."""
    st.subheader("Estágio 11 - Consolidado Geral do Cruzamento Final (RN1)")
    st.caption(
        "Leitura total de `cruzamento_final_produto` — todos os produtos já cruzados no "
        "Estágio 10.2 (\"⚖️ 10.2 Cruzamento Final do Produto\"), ordenados por Ano (decrescente) "
        "e Diferença de Quantidade (decrescente). Somente leitura — correções são feitas "
        "voltando ao Estágio 10.2."
    )
    consolidado = loader.consultar_consolidado_cruzamento_11()
    if consolidado.empty:
        st.info(
            "Nenhum produto com Cruzamento Final salvo ainda — use \"⚖️ 10.2 Cruzamento Final "
            "do Produto\" (Estágio 10, depois de confirmar a Rubrica) pra gerar e salvar pelo "
            "menos 1 produto."
        )
        return

    col_ano, col_infracao, col_busca = st.columns(3)
    anos_disponiveis = sorted(consolidado["ANO"].unique(), key=int, reverse=True)
    anos_filtro = col_ano.multiselect(
        "Ano", anos_disponiveis, default=anos_disponiveis, key="consolidado_11_filtro_ano",
    )
    infracoes_disponiveis = sorted(consolidado["INFRACAO_FINAL"].unique())
    rotulos_infracao = {v: (v if v else "Sem infração") for v in infracoes_disponiveis}
    infracao_filtro = col_infracao.multiselect(
        "Tipo de Infração", infracoes_disponiveis, default=infracoes_disponiveis,
        format_func=lambda v: rotulos_infracao[v], key="consolidado_11_filtro_infracao",
    )
    busca = col_busca.text_input("Buscar na Descrição", key="consolidado_11_busca_descricao")

    filtrado = consolidado[consolidado["ANO"].isin(anos_filtro) & consolidado["INFRACAO_FINAL"].isin(infracao_filtro)]
    if busca.strip():
        filtrado = filtrado[
            filtrado["DESCR_PROD"].str.contains(_padrao_busca_curinga(busca.strip()), case=False, na=False)
        ]

    st.markdown(
        f"**{len(filtrado):,} linha(s)** de {len(consolidado):,} no total.".replace(",", "."),
    )
    if filtrado.empty:
        st.warning("Nenhuma linha bate com os filtros atuais.")
        return

    formatado = filtrado.copy()
    for col in _COLUNAS_NUMERICAS_CONSOLIDADO_11:
        formatado[col] = formatado[col].apply(_formatar_moeda_br)
    formatado["ALIQ"] = formatado["ALIQ"].apply(lambda v: f"{v:.0f}%")

    exibicao = _preparar_preview(formatado, _COLUNAS_CONSOLIDADO_11)
    with st.container(key="consolidado_11_tabela"):
        st.markdown(
            "<style>.st-key-consolidado_11_tabela [data-testid='stDataFrame'] "
            "* { font-size: 10px; }</style>",
            unsafe_allow_html=True,
        )
        st.dataframe(exibicao, use_container_width=True, hide_index=True)

    preparar = st.button("Preparar exportação completa (CSV)", key="btn_preparar_export_consolidado_11")
    if preparar:
        with st.spinner("Preparando exportação completa..."):
            csv_completo = filtrado.rename(columns=loader.carregar_dicionario_campos())
            st.session_state["consolidado_11_csv_bytes"] = csv_completo.to_csv(index=False, sep=";").encode("utf-8-sig")
            st.session_state["consolidado_11_csv_total"] = len(filtrado)
    if "consolidado_11_csv_bytes" in st.session_state:
        st.download_button(
            f"Baixar tabela completa ({st.session_state['consolidado_11_csv_total']:,} "
            "linha(s), CSV)".replace(",", "."),
            data=st.session_state["consolidado_11_csv_bytes"],
            file_name="cruzamento_final_produto_consolidado.csv",
            mime="text/csv",
            key="btn_download_consolidado_11",
        )


def render_pagina_consolidado_11() -> None:
    """Painel 'ESTÁGIO 11 - CONSOLIDADO GERAL (RN1)', botão da 2ª linha
    do Menu Principal: ver render_consolidado_cruzamento_11(). Exige
    dados_carregados (mesmo padrão das outras páginas)."""
    _botao_voltar_menu()
    if not st.session_state.get("dados_carregados"):
        st.info('Carregue os dados primeiro em "🛠️ 1: PROCEDIMENTOS INICIAIS".')
        return
    render_consolidado_cruzamento_11()


# Relatório Final (Estágio 12, 2026-08-07) — colunas de exibição em
# tela, ordem EXATA pedida na Solicitação Técnica: "Descrição, UP, Ano,
# VU $, EI (Qtde), Compras (Qtde), Total Débito, Vendas (Qtde), EF
# (Qtde), Total Crédito, Compras Sem NF, Vendas Sem NF, BC Total, Obs,
# ST, Aliq". ICMS/MULTA/CREDITO_TRIBUTARIO (também presentes em
# loader.gerar_dados_relatorio_final()) NÃO aparecem aqui — só usados
# no resumo do PDF (loader.exportar_relatorio_pdf()).
_COLUNAS_EXIBICAO_RELATORIO_FINAL = [
    "DESCR_PROD", "UP", "ANO", "PU_SUGERIDO",
    "QTDE_EI", "QTDE_C", "TD", "QTDE_V", "QTDE_EF", "TC",
    "COMPRAS_SEM_NF", "VENDAS_SEM_NF",
    "BASE_CALCULO", "INFRACAO_FINAL", "ST", "ALIQ",
]
_COLUNAS_NUMERICAS_RELATORIO_FINAL = (
    "PU_SUGERIDO", "QTDE_EI", "QTDE_C", "TD", "QTDE_V", "QTDE_EF", "TC",
    "COMPRAS_SEM_NF", "VENDAS_SEM_NF", "BASE_CALCULO", "ALIQ",
)


def _render_relatorio_final() -> None:
    """"RELATÓRIO FINAL" (Estágio 12, Solicitação Técnica 2026-08-07:
    "MÓDULO DE RELATÓRIOS FINAIS") — "Levantamento Quantitativo de
    Mercadorias", layout espelhando o relatório de referência do
    usuário (Hunter 1.0, SEFAZ-PB). Lê loader.gerar_dados_relatorio_
    final() (já ordenado por Descrição/Ano) e exibe em st.dataframe
    (somente leitura — "garantir a integridade dos dados finais", mesmo
    raciocínio do Estágio 11) de alta densidade (10px). Formatação BR
    (milhar '.', decimal ',') em TODAS as colunas numéricas — inclusive
    ALIQ como número puro ("18,00", não "18%"), igual ao PDF de
    referência.

    "👁️ Visualização do Relatório" (2026-08-07, pedido do usuário:
    "gostaria que o relatório ficasse disponível para visualização,
    antes do pdf") — o PDF é gerado AUTOMATICAMENTE (não atrás de
    botão — dados deste relatório são de baixa cardinalidade,
    produto×ano, nunca a base bruta inteira, então gerar a cada
    abertura da página é rápido; diferente do padrão "preparar depois
    baixar" usado noutras telas pra tabelas com potencialmente milhões
    de linhas) e embutido na própria página via `<iframe>` com o PDF
    em base64 (`unsafe_allow_html=True`) — o auditor vê o documento
    FINAL, formatado (cabeçalho, TOTAL ANO/TOTAL, Resumo das
    Irregularidades), sem precisar baixar às cegas antes de conferir.
    Tentativa de usar o componente nativo `st.pdf()` (Streamlit 1.58+)
    foi abandonada — o pacote extra que ele exige (`streamlit-pdf`)
    quebrou na importação neste ambiente (`StreamlitAPIException`
    ligada ao sistema de componentes v2, fora do controle deste
    projeto) — `<iframe>` com base64 é a alternativa sem dependência
    extra, robusta o bastante pro uso local/portátil deste app.
    `loader.exportar_relatorio_pdf()` usa `reportlab` (dependência
    nova, ver requirements.txt) — qualquer erro (ex.: ambiente sem
    `reportlab` instalado) vira st.error() em vez de derrubar a página
    inteira. Botão de download continua disponível LOGO ABAIXO da
    visualização, pra quem quiser salvar o arquivo."""
    dados = loader.gerar_dados_relatorio_final()
    if dados.empty:
        st.info(
            "Nenhum ano com repercussão tributária (TD ≠ TC) encontrado — nenhum produto com "
            "Cruzamento Final salvo ainda (use \"⚖️ 10.2 Cruzamento Final do Produto\", Estágio "
            "10, depois de confirmar a Rubrica), ou os anos já salvos estão todos com a equação "
            "de balanço fechada (sem infração a relatar). Confira o "
            "\"📊 11: CONSOLIDADO GERAL (RN1)\" pra ver TODOS os anos, incluindo os equilibrados."
        )
        return

    st.markdown(f"**{len(dados):,} linha(s)** (produto × ano).".replace(",", "."))

    formatado = dados.copy()
    for col in _COLUNAS_NUMERICAS_RELATORIO_FINAL:
        formatado[col] = formatado[col].apply(_formatar_moeda_br)
    exibicao = _preparar_preview(formatado, _COLUNAS_EXIBICAO_RELATORIO_FINAL)
    with st.container(key="relatorio_final_tabela"):
        st.markdown(
            "<style>.st-key-relatorio_final_tabela [data-testid='stDataFrame'] "
            "* { font-size: 10px; }</style>",
            unsafe_allow_html=True,
        )
        st.dataframe(exibicao, use_container_width=True, hide_index=True)

    st.divider()
    st.markdown("### 👁️ Visualização do Relatório")
    try:
        pdf_bytes = loader.exportar_relatorio_pdf(dados)
    except Exception as exc:
        st.error(f"Erro ao gerar PDF: {exc}")
        return

    pdf_base64 = base64.b64encode(pdf_bytes).decode("utf-8")
    st.markdown(
        f'<iframe src="data:application/pdf;base64,{pdf_base64}" '
        'width="100%" height="900" style="border: 1px solid #ccc;"></iframe>',
        unsafe_allow_html=True,
    )

    st.download_button(
        "📥 Baixar Relatório Final (PDF)",
        data=pdf_bytes,
        file_name="relatorio_final.pdf",
        mime="application/pdf",
        key="btn_download_relatorio_final_pdf",
    )


_COLUNAS_EXIBICAO_RELATORIO_ITENS_CRUZADOS = [
    "ANO", "DATA", "DC", "LOC", "DOCUMENTO_ORIGEM", "NUMERO", "CFOP", "QTDE_ITENS", "TIPO", "OBS",
]
_ROTULOS_COLUNAS_RELATORIO_ITENS_CRUZADOS = {
    "ANO": "Ano", "DATA": "Data", "DC": "DC", "LOC": "LOC",
    "DOCUMENTO_ORIGEM": "Documento de Origem", "NUMERO": "Número", "CFOP": "CFOP",
    "QTDE_ITENS": "Qtde de Itens", "TIPO": "Tipo", "OBS": "Obs",
}


def _render_relatorio_itens_cruzados(escolhido: dict) -> None:
    """"RELATÓRIO ITENS CRUZADOS" (Estágio 12.2, Solicitação Técnica
    2026-08-10) — "memória de cálculo" analítica por trás do Relatório
    Final (12.1): 1 linha por item físico (nota a nota/declaração a
    declaração) do produto recebido em `escolhido` — diferente do 12.1,
    que é consolidado geral de todos os produtos. `escolhido` vem de
    `_selecionar_produto_relatorio_12()` (Solicitação Técnica
    2026-08-14: "SELEÇÃO DE ITEM PARA RELATÓRIOS ANALÍTICOS") — não é
    mais obrigatoriamente o produto escolhido globalmente no Estágio 10,
    o auditor pode escolher qualquer produto com item confirmado na
    Rubrica direto nesta tela. Mesmo padrão de `_render_relatorio_
    final()`: tabela em tela (10px, somente leitura) + PDF gerado
    automaticamente e embutido via `<iframe>` base64, com botão de
    download logo abaixo."""
    st.markdown(
        f"**Item Cruzado:** {loader.descricao_efetiva_escolhido(escolhido)} — "
        f"**Unidade do Produto:** {loader.unidade_efetiva_escolhido(escolhido)}"
    )

    dados = loader.gerar_dados_relatorio_itens_cruzados(escolhido)
    if dados.empty:
        st.info(
            "Nenhum item confirmado na Rubrica pra este produto ainda (Entradas/Saídas/Estoque) — "
            'confirme itens em "⚖️ 10: PRODUTOS ALVOS SALVOS" primeiro, ou os anos confirmados '
            "estão fora do Período de Auditoria configurado."
        )
        return

    st.markdown(f"**{len(dados):,} item(ns)**.".replace(",", "."))

    exibicao = dados[_COLUNAS_EXIBICAO_RELATORIO_ITENS_CRUZADOS].rename(
        columns=_ROTULOS_COLUNAS_RELATORIO_ITENS_CRUZADOS,
    )
    exibicao[_ROTULOS_COLUNAS_RELATORIO_ITENS_CRUZADOS["QTDE_ITENS"]] = exibicao[
        _ROTULOS_COLUNAS_RELATORIO_ITENS_CRUZADOS["QTDE_ITENS"]
    ].apply(_formatar_moeda_br)
    with st.container(key="relatorio_itens_cruzados_tabela"):
        st.markdown(
            "<style>.st-key-relatorio_itens_cruzados_tabela [data-testid='stDataFrame'] "
            "* { font-size: 10px; }</style>",
            unsafe_allow_html=True,
        )
        st.dataframe(exibicao, use_container_width=True, hide_index=True)

    st.divider()
    st.markdown("### 👁️ Visualização do Relatório")
    try:
        pdf_bytes = loader.exportar_relatorio_itens_cruzados_pdf(dados, escolhido)
    except Exception as exc:
        st.error(f"Erro ao gerar PDF: {exc}")
        return

    pdf_base64 = base64.b64encode(pdf_bytes).decode("utf-8")
    st.markdown(
        f'<iframe src="data:application/pdf;base64,{pdf_base64}" '
        'width="100%" height="900" style="border: 1px solid #ccc;"></iframe>',
        unsafe_allow_html=True,
    )

    st.download_button(
        "📥 Baixar Relatório Itens Cruzados (PDF)",
        data=pdf_bytes,
        file_name="relatorio_itens_cruzados.pdf",
        mime="application/pdf",
        key="btn_download_relatorio_itens_cruzados_pdf",
    )


_COLUNAS_EXIBICAO_RELATORIO_MC_QUANTIDADES = [
    "CATEGORIA", "LOC", "DOCUMENTO_ORIGEM", "ANO", "TIPO", "DESCR_ORIGINAL", "UP_ORIGINAL",
    "QTDE_ORIGINAL", "OBS", "FATOR", "UP_UTILIZ", "QTDE_UTILIZ",
]
_ROTULOS_COLUNAS_RELATORIO_MC_QUANTIDADES = {
    "CATEGORIA": "Categoria", "LOC": "LOC", "DOCUMENTO_ORIGEM": "Documento de Origem",
    "ANO": "Ano", "TIPO": "Tipo",
    "DESCR_ORIGINAL": "Descrição Original", "UP_ORIGINAL": "Unidade Original",
    "QTDE_ORIGINAL": "Qtde Original", "OBS": "Obs", "FATOR": "Fator",
    "UP_UTILIZ": "Unidade Utilizada", "QTDE_UTILIZ": "Qtde Utilizada",
}
_COLUNAS_NUMERICAS_RELATORIO_MC_QUANTIDADES = ("QTDE_ORIGINAL", "FATOR", "QTDE_UTILIZ")


def _render_relatorio_mc_quantidades(escolhido: dict) -> None:
    """"RELATÓRIO MC QUANTIDADES" (Estágio 12.3, Solicitação Técnica
    2026-08-10: "MEMÓRIA DE CÁLCULO DAS QUANTIDADES") — prova, item a
    item, do cálculo `QTDE ORIGINAL × FATOR = QTDE UTILIZADA`, vinculado
    ao 12.2 pelo MESMO LOC (`loader.gerar_dados_relatorio_mc_
    quantidades()` reaproveita a base compartilhada de `gerar_dados_
    relatorio_itens_cruzados()` — LOC idêntico por construção, ver
    docstring de `loader._montar_base_relatorios_produto_12()`). Mesmo
    `escolhido` recebido por parâmetro do 12.2 (ambos vêm da MESMA
    chamada a `_selecionar_produto_relatorio_12()`, key de session_state
    compartilhada entre os 3 relatórios analíticos — trocar de 12.2 pra
    12.3 não perde a escolha, ver `render_pagina_relatorios()`).

    Grade em `st.data_editor` (pedido explícito da Solicitação Técnica,
    diferente do `st.dataframe` do 12.1/12.2) — TODAS as colunas
    desabilitadas (`disabled=True`): é uma prova formal de cálculo, não
    uma tela de edição; o widget "editor" é só o pedido de aparência,
    sem risco de alteração acidental do dado. Coluna "Categoria" (2026-
    08-10, pedido do usuário: "separar os tipos: entradas, saídas,
    estoque inicial e estoque final") logo no início da grade — a linha
    já vem ordenada por categoria (mesma base do 12.2), a coluna só torna
    o agrupamento visível em tela; no PDF o agrupamento aparece como
    banner "CATEGORIA X" (ver `loader.exportar_relatorio_mc_quantidades_
    pdf()`). PDF gerado automaticamente e embutido via `<iframe>` base64,
    mesmo padrão do 12.1/12.2."""
    st.markdown(
        f"**Item Cruzado:** {loader.descricao_efetiva_escolhido(escolhido)} — "
        f"**Unidade do Produto:** {loader.unidade_efetiva_escolhido(escolhido)}"
    )

    dados = loader.gerar_dados_relatorio_mc_quantidades(escolhido)
    if dados.empty:
        st.info(
            "Nenhum item confirmado na Rubrica pra este produto ainda (Entradas/Saídas/Estoque) — "
            'confirme itens em "⚖️ 10: PRODUTOS ALVOS SALVOS" primeiro, ou os anos confirmados '
            "estão fora do Período de Auditoria configurado."
        )
        return

    st.markdown(f"**{len(dados):,} item(ns)**.".replace(",", "."))

    exibicao = dados[_COLUNAS_EXIBICAO_RELATORIO_MC_QUANTIDADES].rename(
        columns=_ROTULOS_COLUNAS_RELATORIO_MC_QUANTIDADES,
    )
    for col in _COLUNAS_NUMERICAS_RELATORIO_MC_QUANTIDADES:
        rotulo = _ROTULOS_COLUNAS_RELATORIO_MC_QUANTIDADES[col]
        exibicao[rotulo] = exibicao[rotulo].apply(_formatar_moeda_br)
    with st.container(key="relatorio_mc_quantidades_tabela"):
        st.markdown(
            "<style>.st-key-relatorio_mc_quantidades_tabela [data-testid='stDataFrame'] "
            "* { font-size: 10px; }</style>",
            unsafe_allow_html=True,
        )
        st.data_editor(exibicao, use_container_width=True, hide_index=True, disabled=True)

    st.divider()
    st.markdown("### 👁️ Visualização do Relatório")
    try:
        pdf_bytes = loader.exportar_relatorio_mc_quantidades_pdf(dados, escolhido)
    except Exception as exc:
        st.error(f"Erro ao gerar PDF: {exc}")
        return

    pdf_base64 = base64.b64encode(pdf_bytes).decode("utf-8")
    st.markdown(
        f'<iframe src="data:application/pdf;base64,{pdf_base64}" '
        'width="100%" height="900" style="border: 1px solid #ccc;"></iframe>',
        unsafe_allow_html=True,
    )

    st.download_button(
        "📥 Baixar Relatório MC Quantidades (PDF)",
        data=pdf_bytes,
        file_name="relatorio_mc_quantidades.pdf",
        mime="application/pdf",
        key="btn_download_relatorio_mc_quantidades_pdf",
    )


_COLUNAS_EXIBICAO_RELATORIO_MC_PU = [
    "CATEGORIA", "ANO", "DOCUMENTO_ORIGEM", "TIPO", "DESCR_ORIGINAL", "UP_ORIGINAL",
    "QTDE_ORIGINAL", "VU_ORIGINAL", "OBS", "FATOR", "QTDE_UTILIZ", "VU_UTILIZADO",
]
_ROTULOS_COLUNAS_RELATORIO_MC_PU = {
    "CATEGORIA": "Categoria", "ANO": "Ano", "DOCUMENTO_ORIGEM": "Documento de Origem", "TIPO": "Tipo",
    "DESCR_ORIGINAL": "Descrição Original", "UP_ORIGINAL": "Unidade Original",
    "QTDE_ORIGINAL": "Qtde Original", "VU_ORIGINAL": "VU Original", "OBS": "Obs", "FATOR": "Fator",
    "QTDE_UTILIZ": "Qtde Utilizada", "VU_UTILIZADO": "VU Utilizado",
}
_COLUNAS_NUMERICAS_RELATORIO_MC_PU = ("QTDE_ORIGINAL", "VU_ORIGINAL", "FATOR", "QTDE_UTILIZ", "VU_UTILIZADO")


def _render_relatorio_mc_pu(escolhido: dict) -> None:
    """"RELATÓRIO MC PREÇOS UNITÁRIOS" (Estágio 12.4, Solicitação
    Técnica 2026-08-10: "MEMÓRIA DE CÁLCULO DE PREÇOS UNITÁRIOS") —
    prova aritmética, item a item, do preço unitário usado na valoração
    da infração (`VU ORIGINAL ÷ FATOR = VU UTILIZADO`). DIFERENTE do
    12.2/12.3 — só mostra os itens do ANO×CATEGORIA que efetivamente
    alimentou o `PU_SUGERIDO` daquele ano no Estágio 10.2/RN1 (ver
    docstring de `loader.gerar_dados_relatorio_mc_pu()`); nunca mostra
    Estoque, e cada ano só tem 1 categoria. Mesmo `escolhido` recebido
    por parâmetro do 12.2/12.3 (key de session_state compartilhada em
    `_selecionar_produto_relatorio_12()`).

    Grade em `st.data_editor` (pedido explícito da Solicitação Técnica),
    todas as colunas desabilitadas (`disabled=True`) — prova de cálculo,
    não tela de edição. PDF gerado automaticamente e embutido via
    `<iframe>` base64, mesmo padrão do 12.1/12.2/12.3 — no PDF (não na
    grade em tela) aparecem também as caixas "PU MÉDIO"/"MEMÓRIA DE
    CÁLCULO"/"PU MÉDIO + AGREGAÇÃO" por (ANO, CATEGORIA), ver `loader.
    exportar_relatorio_mc_pu_pdf()`."""
    st.markdown(
        f"**Item Cruzado:** {loader.descricao_efetiva_escolhido(escolhido)} — "
        f"**Unidade do Produto:** {loader.unidade_efetiva_escolhido(escolhido)}"
    )

    dados = loader.gerar_dados_relatorio_mc_pu(escolhido)
    if dados.empty:
        st.info(
            "Nenhum ano com repercussão tributária (TD ≠ TC) encontrado pra este produto — use "
            '"⚖️ 10.2 Cruzamento Final do Produto" primeiro, ou os anos com infração estão fora '
            "do Período de Auditoria configurado."
        )
        return

    st.markdown(f"**{len(dados):,} item(ns)**.".replace(",", "."))

    exibicao = dados[_COLUNAS_EXIBICAO_RELATORIO_MC_PU].rename(columns=_ROTULOS_COLUNAS_RELATORIO_MC_PU)
    for col in _COLUNAS_NUMERICAS_RELATORIO_MC_PU:
        rotulo = _ROTULOS_COLUNAS_RELATORIO_MC_PU[col]
        exibicao[rotulo] = exibicao[rotulo].apply(_formatar_moeda_br)
    with st.container(key="relatorio_mc_pu_tabela"):
        st.markdown(
            "<style>.st-key-relatorio_mc_pu_tabela [data-testid='stDataFrame'] "
            "* { font-size: 10px; }</style>",
            unsafe_allow_html=True,
        )
        st.data_editor(exibicao, use_container_width=True, hide_index=True, disabled=True)

    st.divider()
    st.markdown("### 👁️ Visualização do Relatório")
    try:
        pdf_bytes = loader.exportar_relatorio_mc_pu_pdf(dados, escolhido)
    except Exception as exc:
        st.error(f"Erro ao gerar PDF: {exc}")
        return

    pdf_base64 = base64.b64encode(pdf_bytes).decode("utf-8")
    st.markdown(
        f'<iframe src="data:application/pdf;base64,{pdf_base64}" '
        'width="100%" height="900" style="border: 1px solid #ccc;"></iframe>',
        unsafe_allow_html=True,
    )

    st.download_button(
        "📥 Baixar Relatório MC Preços Unitários (PDF)",
        data=pdf_bytes,
        file_name="relatorio_mc_precos_unitarios.pdf",
        mime="application/pdf",
        key="btn_download_relatorio_mc_pu_pdf",
    )


def _selecionar_produto_relatorio_12() -> "dict | None":
    """Seletor de produto dos 3 Relatórios Analíticos (12.2 Itens
    Cruzados/12.3 MC Quantidades/12.4 MC Preços Unitários), Solicitação
    Técnica 2026-08-14 "SELEÇÃO DE ITEM PARA RELATÓRIOS ANALÍTICOS":
    antes, os 3 usavam obrigatoriamente o produto escolhido GLOBALMENTE
    pra cruzamento no Estágio 10 (`loader.consultar_produto_cruzamento_
    escolhido()`); agora o auditor pode escolher qualquer produto que já
    tenha item confirmado na Rubrica, direto na aba de Relatórios, sem
    precisar voltar no Estágio 10 pra trocar o produto em cruzamento.

    Lista vem de `loader.consultar_produtos_disponiveis_relatorios_12()`
    (`DISTINCT DESCR_ALVO, COD_ITEM` de `cruzamento_confirmado_
    detalhado`) — não da tabela `produto_cruzamento_escolhido`, que
    continua intocada (escolher aqui não afeta o Estágio 10, e
    vice-versa). Pré-seleciona o produto escolhido GLOBALMENTE quando
    ele estiver na lista, preservando o comportamento de hoje como
    padrão — o auditor só precisa trocar se quiser ver outro produto.

    Key de session_state ÚNICA (`relatorios12_produto_selectbox`)
    compartilhada pelos 3 relatórios — trocar entre 12.2/12.3/12.4 no
    selectbox de cima não reseta a escolha de produto (12.2 e 12.3
    comparam pelo MESMO LOC entre si, ver docstring de `loader._montar_
    base_relatorios_produto_12()`; trocar de produto no meio da
    conferência quebraria essa comparação).

    Devolve o dict `escolhido` (via `loader.montar_escolhido_local()`,
    mesmo formato de `consultar_produto_cruzamento_escolhido()`) ou
    `None` se não há nenhum produto com item confirmado na Rubrica ainda
    (mostra `st.info` orientando — mesma mensagem de antes)."""
    produtos = loader.consultar_produtos_disponiveis_relatorios_12()
    if produtos.empty:
        st.info(
            'Nenhum produto com item confirmado na Rubrica ainda — em "⚖️ 10: PRODUTOS ALVOS '
            'SALVOS", confirme itens de Entradas/Saídas/Estoque pra pelo menos um produto primeiro.'
        )
        return None

    opcoes = list(zip(produtos["DESCR_ALVO"], produtos["COD_ITEM"]))
    rotulos = [f"{descr} ({cod})" if cod else descr for descr, cod in opcoes]

    indice_padrao = 0
    global_escolhido = loader.consultar_produto_cruzamento_escolhido()
    if global_escolhido:
        chave_global = (global_escolhido.get("DESCR_ALVO", ""), global_escolhido.get("COD_ITEM", ""))
        if chave_global in opcoes:
            indice_padrao = opcoes.index(chave_global)

    indice_selecionado = st.selectbox(
        "🔎 Selecione o produto para o relatório analítico",
        options=range(len(opcoes)),
        format_func=lambda i: rotulos[i],
        index=indice_padrao,
        key="relatorios12_produto_selectbox",
    )
    descr_alvo, cod_item = opcoes[indice_selecionado]
    return loader.montar_escolhido_local(descr_alvo, cod_item)


def render_pagina_relatorios() -> None:
    """Painel 'ESTÁGIO 12 - RELATÓRIOS' (Solicitação Técnica 2026-08-07:
    "MÓDULO DE RELATÓRIOS FINAIS"), botão da 2ª linha do Menu Principal.
    `st.selectbox` pra escolher qual relatório ver — "RELATÓRIO FINAL"
    (12.1, consolidado geral), "RELATÓRIO ITENS CRUZADOS" (12.2, memória
    de cálculo analítica de um produto), "RELATÓRIO MC QUANTIDADES"
    (12.3, prova do cálculo Qtde Original × Fator = Qtde Utilizada,
    vinculado ao 12.2 via LOC) e "RELATÓRIO MC PREÇOS UNITÁRIOS" (12.4,
    prova do cálculo VU Original ÷ Fator = VU Utilizado, agrupado por
    ANO/CATEGORIA conforme a origem do PU_SUGERIDO no RN1, 2026-08-10)
    — a tela já nasce pronta pra crescer (outros relatórios futuros
    entram como opção nova no mesmo selectbox, sem precisar de botão de
    menu extra). Exige dados_carregados (mesmo padrão das outras
    páginas).

    Seletor de produto (2026-08-14, Solicitação Técnica "SELEÇÃO DE ITEM
    PARA RELATÓRIOS ANALÍTICOS"): só aparece pros 3 relatórios
    analíticos (12.2/12.3/12.4), NÃO no 12.1 (Relatório Final continua
    consolidado geral de todos os produtos, sem seletor individual —
    pedido explícito da Solicitação Técnica). Ver `_selecionar_produto_
    relatorio_12()`."""
    _botao_voltar_menu()
    if not st.session_state.get("dados_carregados"):
        st.info('Carregue os dados primeiro em "🛠️ 1: PROCEDIMENTOS INICIAIS".')
        return
    st.subheader("Estágio 12 - Relatórios")
    relatorio = st.selectbox(
        "Relatório",
        [
            "RELATÓRIO FINAL", "RELATÓRIO ITENS CRUZADOS",
            "RELATÓRIO MC QUANTIDADES", "RELATÓRIO MC PREÇOS UNITÁRIOS",
        ],
        key="relatorios_selectbox",
    )
    if relatorio == "RELATÓRIO FINAL":
        _render_relatorio_final()
        return

    escolhido = _selecionar_produto_relatorio_12()
    if escolhido is None:
        return

    if relatorio == "RELATÓRIO ITENS CRUZADOS":
        _render_relatorio_itens_cruzados(escolhido)
    elif relatorio == "RELATÓRIO MC QUANTIDADES":
        _render_relatorio_mc_quantidades(escolhido)
    elif relatorio == "RELATÓRIO MC PREÇOS UNITÁRIOS":
        _render_relatorio_mc_pu(escolhido)
