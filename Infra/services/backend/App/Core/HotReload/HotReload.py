import uvicorn
import string
import random
from pathlib import Path
from App.Core.Settings.Settings import HOST, PORT, HOT_RELOAD

BASE_DIR = Path(__file__).parent.parent.parent.parent
from App.Core.Logs import info, error

# Arquivo sentinel para triggar reload (dentro da pasta HotReload)
RELOAD_TRIGGER_FILE = Path(__file__).parent / "reload_trigger.py"


def start_server(host=None, port=None):
    """Starts the Uvicorn server with hot-reload."""
    try:
        host = host or HOST
        port = port or PORT

        # LOG DE DEPURAÇÃO PARA VALIDAR EXECUÇÃO
        info(
            f"🛡️ SEGURANÇA: Iniciando Uvicorn com server_header=False em {host}:{port}"
        )

        # Usar o dicionário de configuração para garantir que o Uvicorn não ignore os parâmetros
        uvicorn_config = {
            "app": "App.Core.Services.Services:app",
            "host": host,
            "port": port,
            "reload": HOT_RELOAD,
            "reload_dirs": [str(BASE_DIR / "App")],
            "reload_includes": ["*.py"],
            "reload_delay": 0.5,  # debounce: aguarda 0.5s antes de recarregar (evita restarts em cascata)
            "log_config": None,
            "server_header": False,  # DESATIVAR DEFINITIVAMENTE
            "date_header": False,  # DESATIVAR DEFINITIVAMENTE
        }

        uvicorn.run(**uvicorn_config)

    except Exception as e:
        error(f"Erro ao executar servidor: {str(e)}")
        raise


def trigger_reload():
    try:
        random_text = "".join(
            random.choices(string.ascii_letters + string.digits, k=10)
        )
        content = f'"""{random_text}"""'
        RELOAD_TRIGGER_FILE.write_text(content)
        info(f"[HOTRELOAD] Reload triggered: {random_text}")
        return True
    except Exception as e:
        error(f"[HOTRELOAD] Erro ao triggar reload: {e}")
        return False
