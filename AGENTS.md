# Política de Desenvolvimento, Documentação, Memória e Versionamento

## Objetivo

Garantir rastreabilidade completa da evolução do sistema, facilitando manutenção, auditoria técnica, transferência de conhecimento, continuidade de desenvolvimento e recuperação do histórico de decisões.

Esta política é obrigatória para qualquer desenvolvedor ou agente de IA que realize alterações no projeto.

---

# Diretório de Trabalho

Todas as operações deverão considerar como raiz do projeto o diretório atualmente aberto no VS Code (`AI_HUNTER1.1/`).

Nenhum arquivo de documentação, histórico ou memória deverá ser criado fora da estrutura do projeto atualmente aberta.

---

# Pasta de Memória do Projeto

O projeto deverá possuir obrigatoriamente a seguinte pasta:

```text
./memoria/
```

Caso a pasta não exista, ela deverá ser criada automaticamente.

A pasta `memoria` será o repositório oficial de conhecimento do projeto.

Nela deverão ser armazenados:

* Histórico diário de desenvolvimento.
* Decisões arquiteturais.
* Registros de correções relevantes.
* Alterações de infraestrutura.
* Mudanças de comportamento do sistema.
* Informações necessárias para continuidade futura do projeto.
* Resumos de sessões de trabalho.
* Lições aprendidas.
* Pendências técnicas.

---

# Estrutura Esperada

```text
AI_HUNTER1.1/
│
├── OPERACOES/
│   └── geraldo_2020_2024/
│       ├── ESSENCIAL/
│       ├── 1-DOCFISCAIS/
│       └── 2-DECLARACAO/
├── memoria/
│   ├── 2026-06-27.md
│   ├── 2026-06-30.md
│   └── ...
│
├── README.md
├── AGENTS.md
└── ...
```

---

# Registro Obrigatório de Atividades

Ao término de qualquer atividade relevante deverá ser gerado ou atualizado um arquivo Markdown correspondente à data atual.

Exemplo:

```text
./memoria/2026-06-23.md
```

Se já existir um arquivo para a data corrente, ele deverá ser atualizado.

Se não existir, deverá ser criado.

---

# Informações Obrigatórias em Cada Registro

Todo registro deverá conter:

* Funcionalidades implementadas.
* Correções realizadas.
* Refatorações executadas.
* Alterações arquiteturais.
* Alterações de infraestrutura.
* Dependências adicionadas.
* Dependências removidas.
* Dependências atualizadas.
* Scripts criados.
* Scripts alterados.
* Scripts removidos.
* Problemas encontrados.
* Soluções adotadas.
* Decisões técnicas tomadas.
* Pendências identificadas.
* Próximos passos recomendados.

---

# Modelo Obrigatório do Arquivo Diário

```md
# Atualização YYYY-MM-DD

## Resumo Executivo

Breve resumo do que foi realizado.

---

## Funcionalidades Implementadas

- Item

---

## Correções Realizadas

- Item

---

## Melhorias Técnicas

- Item

---

## Refatorações

- Item

---

## Alterações de Arquitetura

- Item

---

## Alterações de Banco de Dados

- Item

---

## Alterações de Infraestrutura

- Item

---

## Dependências Atualizadas

### Adicionadas

- Dependência

### Atualizadas

- Dependência

### Removidas

- Dependência

---

## Arquivos Criados

- caminho/arquivo.ext

---

## Arquivos Modificados

- caminho/arquivo.ext

---

## Arquivos Removidos

- caminho/arquivo.ext

---

## Problemas Encontrados

- Problema

---

## Soluções Aplicadas

- Solução

---

## Pendências

- Pendência

---

## Próximos Passos

- Próximo passo
```

---

# Atualização da Memória do Projeto

Sempre que houver alterações relevantes de negócio ou arquitetura, o agente deverá registrar:

* Motivo da alteração.
* Benefícios esperados.
* Impactos conhecidos.
* Riscos identificados.
* Decisão adotada.

O objetivo é permitir que futuros desenvolvedores ou agentes compreendam rapidamente a evolução do sistema.

---

# Controle de Versão

Todas as alterações aprovadas deverão ser registradas em repositório Git.

Ao final de cada ciclo de desenvolvimento:

1. Validar a integridade da aplicação.
2. Executar testes disponíveis.
3. Corrigir falhas encontradas.
4. Atualizar documentação técnica.
5. Atualizar documentação operacional.
6. Atualizar arquivos da pasta `memoria`.
7. Revisar alterações realizadas.
8. Realizar commit.
9. Realizar push para o repositório remoto.

---

# Política de Commit

Os commits deverão seguir o padrão Conventional Commits.

Exemplos:

```text
feat: implementa importação automática de csv

feat: adiciona processamento de rif

fix: corrige erro de autenticação

fix: corrige falha de leitura de arquivos

refactor: reorganiza camada de serviços

refactor: simplifica processamento de documentos

docs: atualiza documentação operacional

docs: adiciona histórico de evolução

perf: otimiza consulta de processamento

perf: reduz consumo de memória

infra: adiciona monitoramento

infra: configura ambiente de produção

test: adiciona testes automatizados

build: atualiza pipeline de deploy

chore: limpeza de arquivos temporários
```

---

# Regras de Commit

Cada commit deverá conter apenas alterações relacionadas ao mesmo contexto funcional.

Evitar commits genéricos como:

```text
update
ajustes
correções
alterações
melhorias
```

Toda mensagem deve descrever claramente o objetivo da alteração.

---

# Política de Conclusão de Tarefas

Nenhuma funcionalidade será considerada concluída sem:

* Código atualizado.
* Testes executados.
* Documentação atualizada.
* Registro na pasta `memoria`.
* Commit realizado.
* Push realizado.

---

# Obrigatoriedade para Agentes de IA

Todo agente de IA deverá obrigatoriamente:

1. Trabalhar dentro do diretório atualmente aberto no VS Code.
2. Criar automaticamente a pasta `./memoria` quando necessário.
3. Registrar a evolução do projeto na pasta `./memoria`.
4. Atualizar a documentação impactada.
5. Informar arquivos criados.
6. Informar arquivos modificados.
7. Informar arquivos removidos.
8. Informar riscos identificados.
9. Informar pendências existentes.
10. Sugerir próximos passos.
11. Manter consistência entre código, documentação e histórico.
12. Nunca considerar uma tarefa concluída sem atualizar a pasta `./memoria`.

---

# Regra de Ouro

Toda alteração realizada no projeto deve deixar evidências suficientes para que outro desenvolvedor ou agente consiga compreender:

* O que foi alterado.
* Por que foi alterado.
* Como foi alterado.
* Quais impactos a alteração produz.
* Quais são os próximos passos.

Se essas informações não estiverem registradas na pasta `./memoria`, a tarefa não deverá ser considerada concluída.

A documentação é parte integrante da entrega e deverá evoluir continuamente junto com o código-fonte durante todo o ciclo de vida da aplicação.
