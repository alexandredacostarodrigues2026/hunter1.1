@echo off
setlocal enabledelayedexpansion
title Equalizador de Produtos - GECOF/OPERACOES

set "ROOT=%~dp0"
cd /d "%ROOT%"

set "PYTHONNOUSERSITE=1"
set "HUNTER_OPERACAO_DIR="

echo.
echo  ======================================================
echo    EQUALIZADOR DE PRODUTOS - GECOF / OPERACOES
echo  ======================================================

:: Verifica se ha operacao ativa na porta 8600
netstat -ano 2>nul | findstr ":8600 " | findstr "LISTENING" >nul 2>&1
if %errorlevel% equ 0 (
    echo.
    echo  [AVISO] Ha uma operacao ativa na porta 8600.
    echo.
    set /p RESP="  Deseja encerrar a operacao atual e abrir esta? (S/N): "
    if /i "!RESP!"=="S" (
        for /f "tokens=5" %%a in ('netstat -ano 2^>nul ^| findstr ":8600"') do (
            taskkill /F /PID %%a >nul 2>&1
        )
        timeout /t 2 /nobreak >nul
        echo  Operacao anterior encerrada.
    ) else (
        echo.
        echo  Operacao atual mantida. Nenhuma alteracao foi feita.
        echo.
        pause
        exit /b 0
    )
)

echo.

if exist "runtime\Scripts\python.exe" (
    echo  Ambiente: runtime portatil
    echo.
    "runtime\Scripts\python.exe" launcher\launcher_exe.py
    goto FIM
)

if exist "runtime\python.exe" (
    echo  Ambiente: Python embarcado
    echo.
    "runtime\python.exe" launcher\launcher_exe.py
    goto FIM
)

python --version >nul 2>&1
if %errorlevel% equ 0 (
    echo  Ambiente: Python do sistema
    echo.
    python launcher\launcher_exe.py
    goto FIM
)

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
