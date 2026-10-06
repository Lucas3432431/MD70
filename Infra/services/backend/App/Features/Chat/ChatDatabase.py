"""Gerenciador de banco de dados para chats"""

from sqlalchemy import text, exc
from typing import Dict, Any, List, Optional
from App.Core.Logs import debug, error


class ChatDatabase:
    """Gerencia todas as operações de banco de dados relacionadas a chats"""

    def __init__(self, db_manager=None):
        """Inicializa o gerenciador de banco de dados"""
        from App.Core.Crunch.TablesSQL.Database import database

        if db_manager and hasattr(db_manager, "engine"):
            self.engine = db_manager.engine
        else:
            if not database.initialized:
                database.initialize()
            self.engine = database.engine

        debug(f"[CHAT-DB] Engine configurado")

    def execute_query(self, query: str, params: Dict = None) -> Any:
        """Executa uma query SQL"""
        debug(f"[CHAT-DB] Executando query: {query[:100]}...")
        debug(f"[CHAT-DB] Params: {params}")
        with self.engine.connect() as conn:
            result = conn.execute(text(query), params or {})
            conn.commit()
            debug(f"[CHAT-DB] Query executada, rows affected: {result.rowcount}")
            return result

    def fetch_one(self, query: str, params: Dict = None) -> Optional[Dict]:
        """Busca um único registro"""
        with self.engine.connect() as conn:
            result = conn.execute(text(query), params or {})
            row = result.first()
            return dict(row._asdict()) if row else None

    def fetch_all(self, query: str, params: Dict = None) -> List[Dict]:
        """Busca todos os registros"""
        with self.engine.connect() as conn:
            result = conn.execute(text(query), params or {})
            return [dict(row._asdict()) for row in result]

    def table_exists(self, table_name: str) -> bool:
        """Verifica se uma tabela existe"""
        try:
            with self.engine.connect() as conn:
                result = conn.execute(
                    text(
                        """
                    SELECT name FROM sqlite_master
                    WHERE type='table' AND name=:table_name
                """
                    ),
                    {"table_name": table_name},
                )
                return result.fetchone() is not None
        except exc.SQLAlchemyError:
            return False

    def get_table_columns(self, table_name: str) -> List[str]:
        """Obtém as colunas de uma tabela"""
        try:
            with self.engine.connect() as conn:
                result = conn.execute(text(f"PRAGMA table_info({table_name})"))
                return [row[1] for row in result]
        except exc.SQLAlchemyError as e:
            error(f"[CHAT-DB] Erro ao obter colunas: {e}")
            return []

    def execute_with_connection(self, func):
        """Executa uma função com conexão do banco"""
        with self.engine.connect() as conn:
            try:
                result = func(conn)
                conn.commit()  # Garantir commit explícito
                return result
            except Exception as e:
                conn.rollback()  # Rollback em caso de erro
                error(f"[CHAT-DB] Erro na transação: {e}")
                raise
