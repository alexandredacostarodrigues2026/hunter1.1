@echo off
title Setup - Hunter 1.1

echo.
echo  ======================================================
echo    EQUALIZADOR DE PRODUTOS - Configuracao do Ambiente
echo  ======================================================
echo.

:: ROOT = pasta ESSENCIAL/ (pai de launcher/)
set "ROOT=%~dp0.."
cd /d "%ROOT%"

:: Versao do Python embeddable a baixar (mesma usada/validada no projeto)
set "PYVER=3.12.3"
set "PYZIP_URL=https://www.python.org/ftp/python/%PYVER%/python-%PYVER%-embed-amd64.zip"
set "GETPIP_URL=https://bootstrap.pypa.io/get-pip.py"

:: Isola o runtime do perfil do usuario do Windows (%APPDATA%\Python\...)
set "PYTHONNOUSERSITE=1"

:: ---- Verificar se ja esta configurado ----
if exist "runtime\Scripts\python.exe" (
    echo  [OK] Ambiente ja configurado em runtime\ (venv)
    echo.
    goto VERIFICAR_DEPS
)
if exist "runtime\python.exe" (
    echo  [OK] Ambiente ja configurado em runtime\ (embeddable)
    echo.
    goto VERIFICAR_DEPS
)

:: ---- Baixar e montar o Python embeddable (autocontido, sem depender de ----
:: ---- nenhuma instalacao de Python/Anaconda na maquina) -------------------
echo  Baixando Python %PYVER% embeddable...
if not exist "%ROOT%\temp" mkdir "%ROOT%\temp"
powershell -NoProfile -Command "Invoke-WebRequest -Uri '%PYZIP_URL%' -OutFile '%ROOT%\temp\python-embed.zip'"
if %errorlevel% neq 0 (
    echo.
    echo  [ERRO] Falha ao baixar o Python embeddable. Verifique a conexao com a internet.
    pause
    exit /b 1
)

echo  Extraindo para runtime\ ...
powershell -NoProfile -Command "Expand-Archive -Path '%ROOT%\temp\python-embed.zip' -DestinationPath '%ROOT%\runtime' -Force"
if %errorlevel% neq 0 (
    echo.
    echo  [ERRO] Falha ao extrair o Python embeddable.
    pause
    exit /b 1
)

echo  Habilitando site-packages no runtime...
powershell -NoProfile -Command "(Get-Content '%ROOT%\runtime\python312._pth') -replace '#import site','import site' | Set-Content '%ROOT%\runtime\python312._pth'"

echo  Instalando pip...
powershell -NoProfile -Command "Invoke-WebRequest -Uri '%GETPIP_URL%' -OutFile '%ROOT%\temp\get-pip.py'"
"%ROOT%\runtime\python.exe" "%ROOT%\temp\get-pip.py" --no-warn-script-location
if %errorlevel% neq 0 (
    echo.
    echo  [ERRO] Falha ao instalar o pip no runtime.
    pause
    exit /b 1
)

echo  [OK] Runtime embeddable criado.
del /q "%ROOT%\temp\python-embed.zip" "%ROOT%\temp\get-pip.py" >nul 2>&1
echo.

:VERIFICAR_DEPS
:: ---- Detectar executavel Python do runtime ----
if exist "runtime\Scripts\python.exe" (
    set "RTPYTHON=runtime\Scripts\python.exe"
) else (
    set "RTPYTHON=runtime\python.exe"
)

:: ---- Verificar/Instalar dependencias ----
echo  Verificando dependencias...
"%RTPYTHON%" -c "import streamlit, pandas, duckdb, rapidfuzz" >nul 2>&1
if %errorlevel% equ 0 (
    echo  [OK] Dependencias ja instaladas.
    goto FIM
)

echo  Instalando dependencias (pode levar alguns minutos)...
echo.
"%RTPYTHON%" -m pip install --upgrade pip --quiet --no-warn-script-location
"%RTPYTHON%" -m pip install -r "%ROOT%\requirements.txt" --quiet --no-warn-script-location

if %errorlevel% neq 0 (
    echo.
    echo  [ERRO] Falha ao instalar dependencias.
    echo  Verifique a conexao com a internet e tente novamente.
    pause
    exit /b 1
)

:FIM
echo.
echo  ======================================================
echo   Ambiente configurado com sucesso!
echo.
echo   Agora utilize: iniciar_sistema.bat
echo   ou clique em:  iniciar_sistema.exe
echo  ======================================================
echo.
pause
