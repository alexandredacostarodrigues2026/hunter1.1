======================================================
  HUNTER 1.1 — GECOF / OPERAÇÕES
  Manual do Usuário
======================================================


------------------------------------------------------
COMO FUNCIONA EM QUALQUER PC WINDOWS
------------------------------------------------------

  +---------------------------+--------------------------------------------+
  |  Situação                 |  O que fazer                               |
  +---------------------------+--------------------------------------------+
  |  Uso diário               |  Duplo clique em  iniciar_sistema.exe      |
  +---------------------------+--------------------------------------------+
  |  PC novo (primeira vez)   |  Executar  launcher\setup_ambiente.bat     |
  |                           |  uma vez — depois usa o .exe normalmente   |
  +---------------------------+--------------------------------------------+
  |  Atualizar o .exe         |  Executar  launcher\build_exe.bat          |
  +---------------------------+--------------------------------------------+
  |  CSVs em outro lugar      |  Editar  config\config.json                |
  |                           |  campo "csv_path" com o caminho da pasta   |
  +---------------------------+--------------------------------------------+

  O runtime\ tem Python 3.12 com todas as dependências
  instaladas — não precisa de Python no sistema.


------------------------------------------------------
COMO USAR (USO DIÁRIO)
------------------------------------------------------

1. Abra a pasta ESSENCIAL\
2. Clique duas vezes em:  iniciar_sistema.exe
3. Aguarde o navegador abrir automaticamente
4. Use normalmente em: http://localhost:8600

Pronto. Não é necessário nenhum outro passo.


------------------------------------------------------
PRIMEIRA VEZ EM UM COMPUTADOR NOVO
------------------------------------------------------

Se o iniciar_sistema.exe não abrir, execute UMA VEZ:

   launcher\setup_ambiente.bat

Esse arquivo configura o ambiente Python automaticamente.
Após a conclusão, use o iniciar_sistema.exe normalmente.

Observação (etapa atual — esqueleto): o .exe ainda não foi gerado.
Use iniciar_sistema.bat até que launcher\build_exe.bat seja executado.


------------------------------------------------------
ONDE FICAM OS ARQUIVOS CSV
------------------------------------------------------

Os arquivos de dados devem estar na pasta:

   ESSENCIAL\qlik\

Arquivos esperados:
   - ENTRADAS.csv
   - SAIDAS.csv
   - ESTOQUE.csv

Se os arquivos estiverem em outro lugar, edite:
   config\config.json
   Campo "csv_path" — coloque o caminho completo da pasta.


------------------------------------------------------
COMO LEVAR PARA OUTRO COMPUTADOR
------------------------------------------------------

1. Copie a pasta ESSENCIAL\ completa para o novo computador
2. Na primeira vez, execute: launcher\setup_ambiente.bat
3. Depois use normalmente o iniciar_sistema.exe

O histórico, banco de dados e configurações vão junto.


------------------------------------------------------
ONDE FICAM OS DADOS GERADOS
------------------------------------------------------

   banco\equalizador.duckdb  → histórico completo
   logs\                     → logs de execução
   history\                  → contexto e snapshots
   exports\                  → arquivos exportados


------------------------------------------------------
SE ALGO DER ERRADO
------------------------------------------------------

1. Verifique o arquivo:  logs\launcher.log
2. Verifique o arquivo:  logs\streamlit.log
3. Execute novamente:    launcher\setup_ambiente.bat


------------------------------------------------------
SUPORTE TÉCNICO
------------------------------------------------------

Contato: GECOF / OPERAÇÕES
Versão:  0.1.0
======================================================
