"""
Configurações centrais do sistema Crunch.
"""

import os
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent.parent.parent


class Config:
    """Configuration class for Database Management"""

    # Diretórios
    DATA_PATH = str(BASE_DIR / "Data")
    DB_NAME = "MD70.db"
    JSON_PATH = str(BASE_DIR / "data" / "chats")

    # Caminhos completos
    DB_DIR = BASE_DIR / "Data"
    DB_PATH = DB_DIR / DB_NAME

    # URL do banco de dados
    DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{DB_PATH}")

    # Configurações de logging
    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

    # Configurações de segurança
    TOKEN_EXPIRATION_HOURS = 24
    PASSWORD_HASH_ROUNDS = 12

    # Configurações de armazenamento JSON
    JSON_INDENT = 2
    JSON_ENSURE_ASCII = False


config = Config()
