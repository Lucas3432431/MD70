"""
Ponto de entrada para inicialização do Crunch.
"""

import sys
from pathlib import Path

# Adicionar diretório pai ao path para importar módulos
sys.path.insert(0, str(Path(__file__).parent.parent))

from App.Core.Logs import info, error
from Crunch import init_db


def main():
    """Função principal para inicialização."""
    info("Initializing Crunch Database System...")

    if init_db():
        info("Crunch initialized successfully")
        return 0
    else:
        error("Failed to initialize Crunch")
        return 1


if __name__ == "__main__":
    sys.exit(main())
