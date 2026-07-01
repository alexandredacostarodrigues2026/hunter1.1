@echo off
title Equalizador de Produtos - GECOF/OPERACOES

set "ROOT=%~dp0"
cd /d "%ROOT%"

:: Isola o runtime portatil do perfil do usuario do Windows
:: (%APPDATA%\Python\...) -- sem isso, o app pode rodar nesta maquina mas
:: falhar numa maquina diferente.
set "PYTHONNOUSERSITE=1"

echo.
echo  ======================================================
echo    EQUALIZADOR DE PRODUTOS - GECOF / OPERACOES
echo  ======================================================

:: ---- Prioridade 1: Runtime portatil (venv criado por setup_ambiente.bat) ----
if exist "runtime\Scripts\python.exe" (
    echo  Ambiente: runtime portatil
    echo.
    "runtime\Scripts\python.exe" launcher\launcher_exe.py
    goto FIM
)

:: ---- Prioridade 2: Python embarcado em runtime\ ----
if exist "runtime\python.exe" (
    echo  Ambiente: Python embarcado
    echo.
    "runtime\python.exe" launcher\launcher_exe.py
    goto FIM
)

:: ---- Prioridade 3: Python do sistema ----
python --version >nul 2>&1
if %errorlevel% equ 0 (
    echo  Ambiente: Python do sistema
    echo.
    python launcher\launcher_exe.py
    goto FIM
)

:: ---- Nenhum Python encontrado ----
echo.
echo  ======================================================
echo   [ERRO] Python nao encontrado.
echo.
echo   Execute setup_ambiente.bat para configurar o ambiente.
echo   Ou instale Python 3.12 em: https://python.org
echo  ======================================================
echo.
pause

:FIM
if %errorlevel% neq 0 (
    echo.
    echo  [ERRO] Falha ao iniciar. Verifique logs\launcher.log
    pause
)
