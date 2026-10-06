"""
Crunch - Sistema de gerenciamento de banco de dados.
SQL (SQLite/PostgreSQL) para chats, mensagens, files e tokens.
"""

from .Config import config
from App.Core.Crunch.TablesSQL.Database import database
from App.Core.Crunch.TablesSQL.SchemaManager import SchemaManager
from App.Core.Crunch.TablesSQL.DBManager import DatabaseManager
from .Utils import (
    generate_id,
    format_datetime,
    parse_datetime,
    dict_to_model,
    model_to_dict,
    backup_database,
)
from App.Core.Crunch.TablesSQL.Models import (
    Client,
    User,
    Chat,
    Message,
    RefreshToken,
    OAuthToken,
)

# Versão do pacote
__version__ = "1.0.0"
__author__ = "MD70 Team"


def init_db(create_schema: bool = True) -> bool:
    """
    Inicializar sistema de banco de dados.

    Args:
        create_schema: Se True, cria o schema do banco

    Returns:
        True se inicializado com sucesso
    """
    try:
        # Inicializar conexão com banco
        if not database.initialize():
            return False

        # Criar schema se necessário
        if create_schema:
            schema_manager = SchemaManager()
            schema_manager.create_schema()
            schema_manager.report_results()

        return True

    except Exception as e:
        from App.Core.Logs import critical

        critical(f"Failed to initialize database: {e}")
        return False


# Atalhos para funções comuns
def get_session():
    """Obter sessão do banco de dados."""
    return database.get_session()


def get_db_manager() -> DatabaseManager:
    """Obter instância do DatabaseManager."""
    return DatabaseManager()


# Exportar componentes principais
__all__ = [
    # Configuração
    "config",
    # Instâncias principais
    "database",
    "DatabaseManager",
    # Funções
    "init_db",
    "get_session",
    "get_db_manager",
    # Utilitários
    "generate_id",
    "format_datetime",
    "parse_datetime",
    "dict_to_model",
    "model_to_dict",
    "backup_database",
    # Modelos
    "Client",
    "User",
    "Chat",
    "Message",
    "RefreshToken",
    "OAuthToken",
    # Gerenciadores
    "SchemaManager",
]
