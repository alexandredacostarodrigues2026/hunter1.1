@echo off
title Hunter 1.1 - Carregar XML desta operacao
setlocal enabledelayedexpansion

set "OP_DIR=%~dp0"

:: Motor compartilhado: usa a ESSENCIAL/ propria se existir nesta pasta,
:: senao reaproveita a ESSENCIAL/ de geraldo_2020_2024 (motor padrao).
:: Isso permite copiar este mesmo .bat para qualquer pasta de operacao.
:: Cada candidato testa as duas formas de runtime (mesma ordem do launcher_exe.py):
::   1. runtime\Scripts\python.exe  -> venv
::   2. runtime\python.exe          -> Python embutido (embeddable, o caso normal)
set "ESSENCIAL_LOCAL=%OP_DIR%ESSENCIAL"
set "ESSENCIAL_COMPARTILHADA=%OP_DIR%..\geraldo_2020_2024\ESSENCIAL"

set "MOTOR_PY="
if exist "%ESSENCIAL_LOCAL%\runtime\Scripts\python.exe" set "MOTOR_PY=%ESSENCIAL_LOCAL%\runtime\Scripts\python.exe"
if not defined MOTOR_PY if exist "%ESSENCIAL_LOCAL%\runtime\python.exe" set "MOTOR_PY=%ESSENCIAL_LOCAL%\runtime\python.exe"
if defined MOTOR_PY set "MOTOR_LOADER=%ESSENCIAL_LOCAL%\app\loader.py"

if not defined MOTOR_PY if exist "%ESSENCIAL_COMPARTILHADA%\runtime\Scripts\python.exe" (
    set "MOTOR_PY=%ESSENCIAL_COMPARTILHADA%\runtime\Scripts\python.exe"
    set "MOTOR_LOADER=%ESSENCIAL_COMPARTILHADA%\app\loader.py"
)
if not defined MOTOR_PY if exist "%ESSENCIAL_COMPARTILHADA%\runtime\python.exe" (
    set "MOTOR_PY=%ESSENCIAL_COMPARTILHADA%\runtime\python.exe"
    set "MOTOR_LOADER=%ESSENCIAL_COMPARTILHADA%\app\loader.py"
)

if not defined MOTOR_PY (
    echo [ERRO] Motor Python nao encontrado nem em "%ESSENCIAL_LOCAL%" nem em "%ESSENCIAL_COMPARTILHADA%".
    echo Execute geraldo_2020_2024\ESSENCIAL\launcher\setup_ambiente.bat primeiro.
    pause
    exit /b 1
)

:: Isola o runtime do perfil do usuario do Windows (%APPDATA%\Python\...) -
:: sem isso, o app pode rodar nesta maquina mas falhar numa maquina diferente.
set "PYTHONNOUSERSITE=1"
set "HUNTER_OPERACAO_DIR=%OP_DIR%"

echo.
echo  ======================================================
echo   CARREGAR XML DESTA OPERACAO
echo   Pasta: %OP_DIR%
echo  ======================================================
echo.

:: Sem redirecionar a saida: a previa, a pergunta de confirmacao e o
:: progresso de cada arquivo aparecem direto na tela (o motor mesmo cuida
:: do log, em logs\). Cargas podem ser grandes -- o usuario acompanha.
"%MOTOR_PY%" "%MOTOR_LOADER%"

set "HUNTER_OPERACAO_DIR="
echo.
pause
endlocal
