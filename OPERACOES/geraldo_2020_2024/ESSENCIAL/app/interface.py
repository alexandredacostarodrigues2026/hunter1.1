"""Componentes de interface (painéis, tabs, cards) do Equalizador de Produtos."""
import sys
import time
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


def _barra_progresso(titulo: str, n_passos: int, fn_persistir) -> bool:
    """Exibe título + barra de progresso para uma fase de carga.
    fn_persistir(callback) deve chamar callback(etapa, n) a cada passo.
    Retorna True em sucesso, False em erro."""
    st.markdown(f"**{titulo}**")
    barra  = st.progress(0.0, text="Aguardando...")
    status = st.empty()
    idx    = [0]

    def _cb(etapa: str, n: int) -> None:
        idx[0] += 1
        frac = idx[0] / n_passos
        barra.progress(frac, text=f"{etapa}: {n:,} registros".replace(",", "."))
        status.caption(f"Passo {idx[0]}/{n_passos} — {etapa} ({n:,} registros)".replace(",", "."))
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


def render_carga_operacao() -> None:
    """Prévia + botão de carga: 3 barras de progresso independentes.
      1. XML pendentes  — classificação arquivo a arquivo
      2. NF-e           — nfe_entradas + nfe_saidas + nfe_analise_et/ep + nfe_situacao_et/ep
                           + xml_entradas_real/xml_saidas_real no DuckDB
      3. SPED           — sped_itens + sped_produtos + sped_unidades + sped_estoque no DuckDB
    Quando já carregado e sem pendentes, exibe "Carregar novamente" (KPIs de
    entradas/saídas reais ficam no painel dedicado, ver render_fluxos_fisicos())."""
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
    ok_nfe = _barra_progresso(fase_nfe, n_passos=9, fn_persistir=loader.persistir_nfe)

    # ── Barra 3: SPED ─────────────────────────────────────────────────────────
    ok_sped = _barra_progresso(fase_sped, n_passos=4, fn_persistir=loader.persistir_sped)

    if ok_nfe and ok_sped:
        st.session_state["dados_carregados"] = True
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
        colunas = [c for c in _COLUNAS_PREVIEW_ENTRADAS_TERCEIROS if c in df_preview.columns]
        st.markdown(f"Prévia limitada a 200 linhas de {total:,}".replace(",", "."))
        st.dataframe(df_preview[colunas], use_container_width=True)

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
    "PASTA_ORIGEM", "ARQUIVO_ORIGEM",
    "fatonfe_infprot_chnfe", "fatoitemnfe_infnfe_det_nitem",
    "fatoitemnfe_infnfe_det_prod_cfop", "fatoitemnfe_infnfe_det_prod_xprod",
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


def _render_categoria_segregacao(
    titulo: str, categoria: str, total_et: int, total_ep: int,
    colunas_preview: list, msg_vazio: str,
) -> None:
    """Bloco reutilizável: KPIs ET/EP + expander com prévia de uma das duas
    categorias de segregação (categoria='cfop' ou 'situacao')."""
    st.markdown(f"**{titulo}**")
    col1, col2 = st.columns(2)
    col1.metric(f"Qtd Itens ET ({titulo})", f"{total_et:,}".replace(",", "."))
    col2.metric(f"Qtd Itens EP ({titulo})", f"{total_ep:,}".replace(",", "."))

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
      1. CFOP de watchlist (nfe_analise_et/nfe_analise_ep) — situação válida
         mas operação simbólica/de ajuste (entrega futura, venda à ordem,
         baixa de estoque, lançamento ECF).
      2. Situação irregular (nfe_situacao_et/nfe_situacao_ep) — canceladas,
         denegadas, inutilizadas etc.
    Exibido só após a carga geral (dados_carregados)."""
    st.subheader("Painel de Monitoramento — Registros Segregados")
    st.caption(
        "Itens desviados do cruzamento principal (Etapa 1), preservados aqui para consulta: "
        "CFOP de watchlist (faturamento futuro, venda à ordem, baixa de estoque/ECF) e "
        "documentos com situação irregular (cancelados, denegados, inutilizados)."
    )

    if "analise_cfop_gerada" not in st.session_state:
        st.session_state["analise_cfop_gerada"] = loader.analise_ja_gerada()

    if st.session_state["analise_cfop_gerada"]:
        totais = loader.consultar_totais_analise()
        st.success("✅ Dados de análise prontos.")

        _render_categoria_segregacao(
            "CFOP de Watchlist", "cfop",
            totais["nfe_analise_et"], totais["nfe_analise_ep"],
            _COLUNAS_PREVIEW_ANALISE, "Nenhum registro para análise física/simbólica",
        )
        st.markdown("---")
        _render_categoria_segregacao(
            "Situação Irregular", "situacao",
            totais["nfe_situacao_et"], totais["nfe_situacao_ep"],
            _COLUNAS_PREVIEW_SITUACAO, "Nenhum documento com situação irregular",
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
    `bc3`."""
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

        (col1, col2, col3, col4, col5, col6, col7, col8,
         col9, col10, col11, col12, col13, col14) = st.columns(14)
        col1.metric("Matches D1", f"{totais['D1']:,}".replace(",", "."))
        col2.metric("Matches D2", f"{totais['D2']:,}".replace(",", "."))
        col3.metric("Matches A1", f"{totais['A1']:,}".replace(",", "."))
        col4.metric("Matches A2", f"{totais['A2']:,}".replace(",", "."))
        col5.metric("Matches A3", f"{totais['A3']:,}".replace(",", "."))
        col6.metric("Matches A4", f"{totais['A4']:,}".replace(",", "."))
        col7.metric("Matches A5", f"{totais['A5']:,}".replace(",", "."))
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
    "fatoitemnfe_infnfe_det_prod_vprod", "ID_UNICO",
]


def render_fluxos_fisicos() -> None:
    """Estágio 3 — Fluxos Físicos (Lado XML): KPIs + prévia sob demanda de
    xml_entradas_real/xml_saidas_real (loader._classificar_itens_nfe()) —
    movimentação física real da auditada, cruzando tpnf com o papel dela na
    nota (emitente ou destinatária), não só o tpnf isolado (ver
    "regra de negócios unificadas/CNPJ EMIT = CNPJ DEST.txt", raiz do
    projeto). Visualização exclusiva: só uma prévia (entradas OU saídas) fica
    visível por vez, controlada por st.session_state["fluxo_fisico_ativo"]."""
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
