# StdLib
import io
import sys
import argparse
import os
from pathlib import Path

# Parse argumentos ANTES de qualquer import do App
parser = argparse.ArgumentParser(description="MD70 Backend Server")
parser.add_argument(
    "--env",
    "-e",
    required=False,
    help="Environment file to load (.env.windows, .env.wsl, etc)",
)
args = parser.parse_args()

# Define a variável de ambiente para o arquivo .env se fornecida
if args.env:
    os.environ["ENV_FILE"] = args.env

# Garante a codificação UTF-8
if sys.stdout.encoding != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

# Adiciona a raiz do projeto (Core) ao sys.path para permitir imports de 'Modules'
project_root = Path(__file__).resolve().parent
sys.path.insert(0, str(project_root))

from App.Core.Logs import get_logger, info, error
from App.Core.Settings.Settings import load_config
from App.Core.HotReload.HotReload import start_server


def main():
    """Função principal que carrega a configuração e executa o servidor FastAPI."""

    logger = get_logger()
    info("Aplicacao iniciada")

    try:
        config = load_config()
        info("Configuracoes carregadas com sucesso")
    except (FileNotFoundError, KeyError) as e:
        error(f"Falha ao carregar configuracao do {args.env}: {e}")
        sys.exit(1)

    host = config.get("host")
    port = config.get("port")
    start_server(host=host, port=port)


if __name__ == "__main__":
    main()
