"""Componentes de interface (painéis, tabs, cards) do Hunter 1.1."""
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

    _render_alerta_ancoragem_estoque()

    if ja_carregado and sem_pendentes:
        st.success("✅ Dados carregados.")
        _render_alerta_cobertura_periodo()
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
    persistido, diferente da prévia sob demanda do Estágio 3."""
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


_COLUNAS_PREVIEW_DIVERGENCIA = [
    "CHV_NFE", "EXCEL_QTD_ITENS", "HUNTER_ENTRADAS_QTD", "ITENS_ENTRADAS_REAIS",
    "ITENS_SAIDAS_REAIS", "ITENS_SITUACAO", "ITENS_ANALISE_CFOP",
    "ITENS_NAO_IDENTIFICADOS", "CASO_AUTOEMISSAO_DUPLICADA",
]


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
    "Investigar Chaves Divergentes" acima, que é por CONTAGEM)."""
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
    st.caption(
        "Compara o Excel de referência (`*ENTRADAS*.xlsx` na pasta da operação) com "
        "estoque_entradas por CHV_NFE + contagem de itens por nota — sem cruzar código de "
        "item. Reconcilia o resíduo checando xml_saidas_real (Estágio 3), nfe_situacao_et/ep "
        "(Notas Não Autorizadas) e nfe_analise_et/ep (CFOPs Não Autorizados), nessa ordem."
    )

    resumo = resultado["resumo"]
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
    `key=` do Streamlit) e compartilhariam estado indevidamente."""
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
    st.caption(
        "Compara o Excel de referência (`*SAIDAS*.xlsx` na pasta da operação) com "
        "estoque_saidas por CHV_NFE + contagem de itens por nota — sem cruzar código de "
        "item. Reconcilia o resíduo checando xml_entradas_real (Estágio 3), nfe_situacao_et/ep "
        "(Notas Não Autorizadas) e nfe_analise_et/ep (CFOPs Não Autorizados), nessa ordem."
    )

    resumo = resultado["resumo"]
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
    periodo = resumo.get("periodo")
    texto_periodo = (
        f" Restrita ao Período de Auditoria configurado ({periodo['ano_inicial']}-"
        f"{periodo['ano_final']})."
        if periodo else
        " Nenhum Período de Auditoria configurado — mostrando todos os anos presentes nos dados."
    )
    st.caption(
        "Compara o Excel de referência (`*ESTOQUE*.xlsx` na pasta da operação) com as "
        "declarações de inventário cruas do Bloco H (H010), por (COD_ITEM, ANO_REFERENCIA) — "
        "uma linha por declaração física, mesmo modelo do Excel, sem passar pelo formato "
        "item×ano expandido do Estágio 5." + texto_periodo
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
    """Menu principal (Estágio 6): 5 botões despacham para
    render_pagina_extracao()/render_pagina_matching()/
    render_pagina_segregados()/render_pagina_construcao()/
    render_pagina_auditoria1()."""
    st.subheader("Menu Principal")
    col1, col2, col3, col4, col5 = st.columns(5)
    if col1.button("📥 EXTRAÇÃO", key="btn_menu_extracao", use_container_width=True):
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


def _botao_voltar_menu() -> None:
    """Botão fixo no topo dos painéis Extração/Construção — volta pro Menu
    Principal. Só mexe em st.session_state["pagina_ativa"], nunca em
    dados_carregados nem em tabela nenhuma do DuckDB."""
    if st.button("⬅️ Voltar ao Menu Principal", key="btn_voltar_menu"):
        st.session_state["pagina_ativa"] = None
        st.rerun()
    st.divider()


def render_pagina_extracao() -> None:
    """Painel 'Extração' (Estágio 6): configuração de Período de Auditoria,
    Carga de XML/SPED (com os alertas de cobertura e de Ancoragem de
    Estoque já embutidos em render_carga_operacao()) e Entidade Auditada —
    mesmo conteúdo que antes ficava direto em main.py, só agrupado atrás do
    botão "EXTRAÇÃO" do menu principal."""
    _botao_voltar_menu()
    render_configuracao_periodo()
    st.divider()
    render_carga_operacao()
    if st.session_state.get("dados_carregados"):
        st.divider()
        render_entidade_auditada()


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
        st.info('Carregue os dados primeiro em "📥 EXTRAÇÃO".')
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
        st.info('Carregue os dados primeiro em "📥 EXTRAÇÃO".')
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
        st.info('Carregue os dados primeiro em "📥 EXTRAÇÃO".')
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
        st.info('Carregue os dados primeiro em "📥 EXTRAÇÃO".')
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
