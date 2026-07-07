"""
Launcher do Equalizador de Produtos.

Este script é compilado com PyInstaller para gerar iniciar_sistema.exe.
Funciona também como .py puro (para desenvolvimento e testes).

Lógica:
  1. Determina ROOT (pasta ESSENCIAL/) com base em como está sendo executado
  2. Localiza Python: runtime/ (portátil) > sistema
  3. Encontra porta disponível a partir de config.json
  4. Inicia Streamlit em subprocesso
  5. Abre navegador automaticamente
  6. Exibe caixa de diálogo em caso de erro (sem console)
"""
import ctypes
import json
import os
import shutil
import socket
import subprocess
import sys
import time
import webbrowser
from pathlib import Path


APP_TITULO = "Equalizador de Produtos"


# ---------------------------------------------------------------------------
# Utilitários
# ---------------------------------------------------------------------------

def _msgbox(msg: str, erro: bool = False) -> None:
    """Exibe caixa de diálogo nativa do Windows (sem depender de tkinter)."""
    icone = 0x10 if erro else 0x40   # MB_ICONERROR | MB_ICONINFORMATION
    ctypes.windll.user32.MessageBoxW(0, msg, APP_TITULO, icone | 0x1000)


def _porta_livre(porta: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind(("127.0.0.1", porta))
            return True
        except OSError:
            return False


def _encontrar_porta(inicial: int, tentativas: int = 15) -> int:
    for p in range(inicial, inicial + tentativas):
        if _porta_livre(p):
            return p
    return inicial   # fallback — deixa o Streamlit reclamar


def _encontrar_python(root: Path) -> Path | None:
    """
    Ordem de preferência:
      1. runtime\\Scripts\\python.exe  → venv criado por setup_ambiente.bat
      2. runtime\\python.exe           → Python embutido (embedded distribution)
      3. python.exe do PATH do sistema
    """
    candidatos = [
        root / "runtime" / "Scripts" / "python.exe",
        root / "runtime" / "python.exe",
    ]
    for c in candidatos:
        if c.exists():
            return c
    sistema = shutil.which("python") or shutil.which("python3")
    return Path(sistema) if sistema else None


def _determinar_root() -> Path:
    """
    - Quando compilado como .exe: ROOT = pasta que contém o .exe
    - Quando executado como .py:  ROOT = pasta pai de launcher/ (= ESSENCIAL/)
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    ROOT   = _determinar_root()
    CONFIG = ROOT / "config" / "config.json"
    MAIN   = ROOT / "app" / "main.py"
    LOG    = ROOT / "logs" / "launcher.log"
    LOG.parent.mkdir(parents=True, exist_ok=True)

    def log(msg: str) -> None:
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        try:
            with open(LOG, "a", encoding="utf-8") as f:
                f.write(f"{ts} | {msg}\n")
        except Exception:
            pass

    log(f"Iniciando — ROOT={ROOT}")

    # ---- Ler configurações ----
    if not CONFIG.exists():
        _msgbox(f"Arquivo config.json não encontrado em:\n{CONFIG}", erro=True)
        return
    try:
        with open(CONFIG, encoding="utf-8") as f:
            cfg = json.load(f)
    except Exception as exc:
        _msgbox(f"Erro ao ler config.json:\n{exc}", erro=True)
        return

    # ---- Verificar app ----
    if not MAIN.exists():
        _msgbox(f"Arquivo principal não encontrado:\n{MAIN}", erro=True)
        return

    # ---- Localizar Python ----
    python = _encontrar_python(ROOT)
    if python is None:
        _msgbox(
            "Ambiente Python não encontrado.\n\n"
            "Execute setup_ambiente.bat para configurar o ambiente portátil.\n\n"
            f"Pasta esperada: {ROOT / 'runtime'}",
            erro=True,
        )
        return
    log(f"Python: {python}")

    # ---- Porta ----
    porta_cfg = int(cfg.get("port", 8600))
    porta     = _encontrar_porta(porta_cfg)
    if porta != porta_cfg:
        log(f"Porta {porta_cfg} ocupada. Usando {porta}.")
    url = f"http://localhost:{porta}"
    log(f"URL: {url}")

    # ---- Iniciar Streamlit ----
    cmd = [
        str(python), "-m", "streamlit", "run",
        str(MAIN),
        "--server.port",              str(porta),
        "--server.headless",          "true",
        "--browser.gatherUsageStats", "false",
        "--server.enableCORS",        "false",
    ]
    log(f"CMD: {' '.join(cmd)}")

    # PYTHONNOUSERSITE evita que o runtime portátil "escape" para pacotes
    # instalados no perfil do usuário do Windows (%APPDATA%\Python\...) —
    # sem isso, o app pode rodar aqui mas falhar numa máquina diferente.
    env = os.environ.copy()
    env["PYTHONNOUSERSITE"] = "1"

    try:
        proc = subprocess.Popen(
            cmd,
            cwd=str(ROOT),
            env=env,
            stdout=open(ROOT / "logs" / "streamlit.log", "a", encoding="utf-8"),
            stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    except Exception as exc:
        _msgbox(f"Falha ao iniciar o servidor:\n{exc}", erro=True)
        log(f"ERRO ao iniciar: {exc}")
        return

    log(f"Servidor PID={proc.pid} iniciado")

    # ---- Abrir navegador ----
    if cfg.get("auto_open_browser", True):
        time.sleep(3)
        try:
            webbrowser.open(url)
            log(f"Navegador aberto: {url}")
        except Exception as exc:
            log(f"Erro ao abrir navegador: {exc}")

    proc.wait()
    log("Servidor encerrado.")


if __name__ == "__main__":
    main()
