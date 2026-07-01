@echo off
title Build - iniciar_sistema.exe

echo.
echo  ======================================================
echo    BUILD - Equalizador de Produtos
echo    Gerando iniciar_sistema.exe com PyInstaller
echo  ======================================================
echo.

set "ROOT=%~dp0.."
cd /d "%ROOT%"

:: ---- Verificar Python ----
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERRO] Python nao encontrado. Execute setup_ambiente.bat primeiro.
    pause & exit /b 1
)

:: ---- Instalar/verificar PyInstaller ----
python -m PyInstaller --version >nul 2>&1
if %errorlevel% neq 0 (
    echo Instalando PyInstaller...
    python -m pip install pyinstaller --quiet
)

:: ---- Gerar icone placeholder se nao existir ----
if not exist "assets\icon.ico" (
    echo [AVISO] assets\icon.ico nao encontrado. O .exe sera gerado sem icone.
    set ICON_OPT=
) else (
    set ICON_OPT=--icon=assets\icon.ico
)

:: ---- Build ----
echo Compilando...
python -m PyInstaller ^
    --onefile ^
    --noconsole ^
    --name iniciar_sistema ^
    --distpath "%ROOT%" ^
    --workpath "%ROOT%\temp\_pyinstaller_work" ^
    --specpath "%ROOT%\temp\_pyinstaller_spec" ^
    %ICON_OPT% ^
    "%ROOT%\launcher\launcher_exe.py"

if %errorlevel% equ 0 (
    echo.
    echo  ======================================================
    echo   BUILD CONCLUIDO COM SUCESSO
    echo   Arquivo gerado: iniciar_sistema.exe
    echo  ======================================================
) else (
    echo.
    echo  [ERRO] Falha no build. Verifique o log acima.
)
echo.
pause
