# ARQUITETURA — Equalizador de Produtos (geraldo_2020_2024)

## Estado atual: PS0 — esqueleto (2026-06-27)

Stack: Streamlit + pandas + DuckDB + rapidfuzz (mesma do app de referência em `ANTIGO_geraldo_2020_2024_5/`).

Entry point: `ESSENCIAL/app/main.py`, porta 8600 (config em `ESSENCIAL/config/config.json`).

### Estrutura
```
ESSENCIAL/
  app/            — main.py (placeholder executável) + stubs: interface, loader, matching,
                    persistencia, scoring, filtros, logs, contexto, utils
  banco/          — vazia (bancos criados em runtime)
  config/         — config.json
  runtime/        — vazia (populada por launcher/setup_ambiente.bat)
  launcher/       — launcher_exe.py, build_exe.bat, setup_ambiente.bat (reaproveitados de ANTIGO)
  logs/, history/, exports/, qlik/, temp/, executavel/, assets/ — vazias
  iniciar_sistema.bat
```

### Decisões
- Local: dentro de `geraldo_2020_2024/` (pasta da operação atual), não na raiz do projeto.
- Infraestrutura de portabilidade copiada de `ANTIGO_geraldo_2020_2024_5/ESSENCIAL/launcher/` sem alterações — já é portátil (usa `Path(__file__)`/`sys.frozen`, sem usuário/caminho fixo).
- Lógica de negócio (ingestão NF-e/SPED, matching, equalização) propositalmente **não** portada nesta etapa — ver `ANTIGO_geraldo_2020_2024_5/CLAUDE.md` e `docs/` para a referência completa quando essa etapa começar.

Próxima etapa: a definir.
