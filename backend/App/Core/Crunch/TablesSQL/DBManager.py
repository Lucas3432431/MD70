"""
Gerenciador centralizado de banco de dados.
Suporta SQL (SQLite/PostgreSQL) e detecta automaticamente o ambiente.

COMPATIBILIDADE COM DIFERENTES DB_ENVs:
- local: SQLite local - suporta todas as operações
- cloud-tcp: PostgreSQL direto - suporta todas as operações
- cloud-rest: Supabase REST API - limitado (sem queries diretas, apenas JWT)
- sqlite-fallback: SQLite como fallback - suporta todas as operações

Para REST API (cloud-rest):
- Autenticação: apenas JWT (sem verificação de token no DB)
- Chats: retorna lista vazia (dados em JSON files)
- Mensagens: salvas em JSON files, não em SQL
- Transações: não suportadas
"""

from datetime import datetime
from typing import Optional, List, Callable, Any, Dict
from sqlalchemy.orm import Session
from sqlalchemy import text
import json
import re

from App.Core.Crunch.TablesSQL.Database import database
from .DBCryptographyManager import DBCryptographyManager
from App.Core.Crunch.TablesSQL.Models import (
    Chat,
    Message,
    Client,
    User,
    IsolatedChat,
    IsolatedMessage,
    IntegrationMCP,
)
from App.Core.Crunch.SyncManager import SyncManager
from App.Core.Logs import info, debug, error
from App.Core.Settings import load_config
import uuid as uuid_lib


class DatabaseManager:
    """
    Gerenciador centralizado de banco de dados.
    Suporta SQL (SQLite/PostgreSQL) e JSON (chats/mensagens/anexos).

    Em produção (ENVIRONMENT=production) ou quando DB_ENV=cloud-rest:
    - TODAS operações de leitura usam DB LOCAL (SQLite)
    - POST/PATCH/DELETE são enfileiradas para sync com cloud
    """

    # ==================== SESSION MANAGEMENT ====================

    @staticmethod
    def _is_production() -> bool:
        """Verificar se está em produção (lê de Settings/config)"""
        try:
            config = load_config()
            env = config.get(
                "ENVIRONMENT", config.get("environment", "development")
            ).lower()
            return env == "production"
        except Exception:
            return False

    @staticmethod
    def _get_db_env_config() -> str:
        """Obter DB_ENV da configuração (cloud-rest, cloud-tcp, local, sqlite-fallback)"""
        try:
            config = load_config()
            return config.get("DB_ENV", "local").lower()
        except Exception:
            return "local"

    @staticmethod
    def _get_read_source() -> str:
        """Obter descrição da fonte de leitura do banco de dados.

        Returns:
            String descrevendo de onde está lendo (ex: "Local SQLite", "Cloud PostgreSQL", etc)
        """
        is_prod = DatabaseManager._is_production()
        db_env = DatabaseManager._get_db_env_config()

        # Em produção, sempre lê do local
        if is_prod:
            return "Local SQLite (Production)"

        # Em dev, usa o DB_ENV configurado
        if db_env == "cloud-rest":
            return "Cloud REST API"
        elif db_env == "cloud-tcp":
            return "Cloud PostgreSQL (TCP)"
        elif db_env == "sqlite-fallback":
            return "SQLite Fallback"
        else:
            return "Local SQLite"

    @staticmethod
    def _get_local_session() -> Session:
        """Obter sessão do DB local (SQLite)"""
        # Forçar usar local
        original_env = database.db_env
        database.db_env = "local"
        session = database.get_session()
        database.db_env = original_env
        debug("[DB Read] Forcing local SQLite session")
        return session

    @staticmethod
    def get_session() -> Session:
        """Obter nova sessão de banco de dados.

        Em produção: retorna local DB (SQLite)
        Em dev: usa a configuração padrão
        """
        read_source = DatabaseManager._get_read_source()
        # debug(f"[DB Read] Creating session from: {read_source}")

        if DatabaseManager._is_production():
            return DatabaseManager._get_local_session()
        return database.get_session()

    @staticmethod
    def get_db_env() -> str:
        """Obter ambiente do banco de dados (local ou cloud)."""
        return database.get_db_env()

    @staticmethod
    def get_db_env_config() -> str:
        """Obter DB_ENV da configuração (cloud-rest, cloud-tcp, local, sqlite-fallback)."""
        return DatabaseManager._get_db_env_config()

    @staticmethod
    def is_cloud() -> bool:
        """Verificar se está usando banco de dados cloud."""
        return database.is_cloud()

    @staticmethod
    def is_local() -> bool:
        """Verificar se está usando banco de dados local."""
        return database.is_local()

    @staticmethod
    def get_environment_name() -> str:
        """Retornar nome do ambiente para logging."""
        db_env = database.get_db_env()

        if db_env == "cloud-rest":
            return "Cloud REST API"
        elif db_env == "cloud-tcp":
            return "Cloud PostgreSQL (TCP)"
        elif db_env == "local":
            return "Local SQLite"
        elif db_env == "sqlite-fallback":
            return "SQLite Fallback"
        else:
            return "Unknown"

    # ==================== TRANSACTION & RAW SQL ====================

    @staticmethod
    def execute_transaction(callback: Callable[[Session], Any]) -> Any:
        """
        Executar operações em uma transação.

        Args:
            callback: Função que recebe a sessão e executa as operações

        Returns:
            O retorno da callback
        """
        read_source = DatabaseManager._get_read_source()
        # debug(f"[DB Read] Executing transaction from: {read_source}")
        session = database.get_session()
        try:
            result = callback(session)
            session.commit()
            # debug(f"[DB Transaction] Executada com sucesso (read_from: {read_source})")
            return result
        except Exception as e:
            session.rollback()
            error(f"[DB] Erro na transação ({read_source}): {e}")
            raise
        finally:
            session.close()

    @staticmethod
    def fetch_one(
        query: str, params: Dict[str, Any], table_name: Optional[str] = None
    ) -> Optional[Dict]:
        """
        Executar query e retornar primeira linha como dicionário.
        Descriptografa automaticamente campos sensíveis se table_name for especificado.

        Args:
            query: SQL query string
            params: Parâmetros da query
            table_name: Nome da tabela para descriptografar campos sensíveis (ex: 'users', 'billing')

        Returns:
            Dict com a primeira linha ou None (com campos descriptografados)
        """
        read_source = DatabaseManager._get_read_source()
        # debug(f"[DB Read] Fetching one row from: {read_source}")

        session = database.get_session()
        try:
            result = session.execute(text(query), params)
            row = result.first()
            if row:
                # Converter Row para dict
                row_dict = dict(row._mapping) if hasattr(row, "_mapping") else dict(row)

                # Descriptografar campos sensíveis se table_name foi especificado
                if table_name:
                    row_dict = DBCryptographyManager.decrypt_row(table_name, row_dict)

                return row_dict
            return None
        except Exception as e:
            error(f"[DB] Erro ao buscar linha ({read_source}): {e}")
            return None
        finally:
            session.close()

    @staticmethod
    def fetch_all(
        query: str, params: Dict[str, Any], table_name: Optional[str] = None
    ) -> List[Dict]:
        """
        Executar query e retornar todas as linhas como dicionários.
        Descriptografa automaticamente campos sensíveis se table_name for especificado.

        Args:
            query: SQL query string
            params: Parâmetros da query
            table_name: Nome da tabela para descriptografar campos sensíveis (ex: 'users', 'billing')

        Returns:
            Lista de dicts (com campos descriptografados)
        """
        read_source = DatabaseManager._get_read_source()
        # debug(f"[DB Read] Fetching all rows from: {read_source}")

        session = database.get_session()
        try:
            result = session.execute(text(query), params)
            rows = result.fetchall()
            rows_dict = [
                dict(row._mapping) if hasattr(row, "_mapping") else dict(row)
                for row in rows
            ]

            # Descriptografar campos sensíveis se table_name foi especificado
            if table_name:
                rows_dict = DBCryptographyManager.decrypt_rows(table_name, rows_dict)

            return rows_dict
        except Exception as e:
            error(f"[DB] Erro ao buscar linhas ({read_source}): {e}")
            return []
        finally:
            session.close()

    @staticmethod
    def execute_query(query: str, params: Dict[str, Any]) -> None:
        """
        Executar query sem retorno (INSERT/UPDATE/DELETE).

        Args:
            query: SQL query string
            params: Parâmetros da query
        """
        write_source = (
            DatabaseManager._get_read_source()
        )  # Write sempre no local em produção
        # debug(f"[DB Write] Executing query on: {write_source}")

        # Use DatabaseManager.get_session() to respect production routing (local SQLite in prod)
        if DatabaseManager._is_production():
            session = DatabaseManager._get_local_session()
        else:
            session = database.get_session()

        try:
            session.execute(text(query), params)
            session.commit()
            # debug(f"[DB Query] Executada com sucesso (write_to: {write_source})")
        except Exception as e:
            session.rollback()
            error(f"[DB] Erro ao executar query ({write_source}): {e}")
            raise
        finally:
            session.close()

    def execute(self, query: str, params: Dict[str, Any]) -> None:
        """Alias de instância para execute_query — permite uso via db = DatabaseManager()."""
        DatabaseManager.execute_query(query, params)

    @staticmethod
    def encrypt_params_for_insert(table: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Criptografa campos sensíveis dos parâmetros antes de inserir no banco.
        Útil para INSERT e UPDATE que precisa salvar dados sensíveis criptografados.

        Args:
            table: Nome da tabela (ex: 'users', 'billing', 'cards')
            params: Dicionário de parâmetros da query

        Returns:
            Dict: Cópia de params com campos sensíveis criptografados
        """
        return DBCryptographyManager.encrypt_row_for_insert(table, params)

    @staticmethod
    def decrypt_row(table: str, row: Dict[str, Any]) -> Dict[str, Any]:
        """
        Descriptografa campos sensíveis de uma linha.

        Args:
            table: Nome da tabela
            row: Dicionário com dados da linha

        Returns:
            Dict: Cópia de row com campos descriptografados
        """
        return DBCryptographyManager.decrypt_row(table, row)

    # ==================== CLIENT OPERATIONS ====================

    @staticmethod
    def create_client(session: Session, client_data: dict) -> Client:
        """Criar novo cliente.

        Em produção: cria local + enfileira para cloud
        """
        client = Client(**client_data)
        session.add(client)
        session.commit()
        session.refresh(client)
        info(f"Client created ({database.get_db_env()}): {client.client_id}")

        return client

    @staticmethod
    def get_client(session: Session, client_id: int) -> Optional[Client]:
        """Obter cliente por ID."""
        read_source = DatabaseManager._get_read_source()
        debug(f"[DB Read] Fetching client {client_id} from: {read_source}")
        return session.query(Client).filter(Client.client_id == client_id).first()

    # ==================== USER OPERATIONS ====================

    @staticmethod
    def create_user(session: Session, user_data: dict) -> User:
        """Criar novo usuário.

        Em produção: cria local + enfileira para cloud
        """
        user = User(**user_data)
        session.add(user)
        session.commit()
        session.refresh(user)
        info(f"User created ({database.get_db_env()}): {user.email}")

        return user

    @staticmethod
    def get_user_by_email(session: Session, email: str) -> Optional[User]:
        """Obter usuário por email."""
        read_source = DatabaseManager._get_read_source()
        debug(f"[DB Read] Fetching user by email from: {read_source}")
        return session.query(User).filter(User.email == email).first()

    @staticmethod
    def get_client_id_by_user_id(session: Session, user_id: str) -> Optional[str]:
        """Obter client_id associado a um user_id."""
        user = session.query(User).filter(User.user_id == str(user_id)).first()
        return user.client_id if user else None

    # ==================== MCP OPERATIONS ====================

    @staticmethod
    def get_mcp_configs(session: Session, client_id: str) -> List[Dict[str, Any]]:
        """Busca as configurações MCP ativas de um cliente."""
        configs = (
            session.query(IntegrationMCP)
            .filter(
                IntegrationMCP.client_id == client_id, IntegrationMCP.is_active == True
            )
            .all()
        )

        result = []
        for c in configs:
            raw = c.env_vars or {}
            if isinstance(raw, dict) and "_enc" in raw:
                # Dado criptografado: {"_enc": "<ciphertext>"}
                decrypted = DBCryptographyManager.decrypt_field(raw["_enc"])
                try:
                    env_dict = json.loads(decrypted) if decrypted else {}
                except Exception:
                    env_dict = {}
            elif isinstance(raw, dict):
                # Dado legado em plain dict (não criptografado)
                env_dict = raw
            else:
                env_dict = {}
            result.append(
                {
                    "provider": c.provider,
                    "command": c.command,
                    "args": c.args,
                    "env": env_dict,
                }
            )
        return result

    @staticmethod
    def list_mcp_integrations(session: Session, client_id: str) -> List[Dict[str, Any]]:
        """Lista integrações MCP ativas de um cliente (info para o frontend)."""
        records = (
            session.query(IntegrationMCP)
            .filter(
                IntegrationMCP.client_id == client_id, IntegrationMCP.is_active == True
            )
            .order_by(IntegrationMCP.created_at.asc())
            .all()
        )
        return [
            {
                "integration_id": r.integration_id,
                "provider": r.provider,
                "is_active": r.is_active,
                "token_valid": r.token_valid if r.token_valid is not None else True,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in records
        ]

    @staticmethod
    def create_mcp_integration(
        session: Session,
        client_id: str,
        provider: str,
        command: str,
        args: list,
        env_vars: dict,
    ) -> str:
        """Cria ou atualiza (upsert) uma integração MCP para um cliente."""
        import uuid as _uuid

        existing = (
            session.query(IntegrationMCP)
            .filter(
                IntegrationMCP.client_id == client_id,
                IntegrationMCP.provider == provider,
            )
            .first()
        )
        if existing:
            existing.command = command
            existing.args = args
            existing.env_vars = {
                "_enc": DBCryptographyManager.encrypt_field(json.dumps(env_vars))
            }
            existing.is_active = True
            existing.token_valid = True
            session.commit()
            return existing.integration_id

        integration_id = str(_uuid.uuid4())
        record = IntegrationMCP(
            integration_id=integration_id,
            client_id=client_id,
            provider=provider,
            command=command,
            args=args,
            env_vars={
                "_enc": DBCryptographyManager.encrypt_field(json.dumps(env_vars))
            },
            is_active=True,
        )
        session.add(record)
        session.commit()
        return integration_id

    @staticmethod
    def get_mcp_integration_env_vars(
        session: Session, client_id: str, provider: str
    ) -> dict:
        """Retorna env_vars descriptografadas de uma integração ativa."""
        record = (
            session.query(IntegrationMCP)
            .filter(
                IntegrationMCP.client_id == client_id,
                IntegrationMCP.provider == provider,
                IntegrationMCP.is_active == True,
            )
            .first()
        )
        if not record:
            return {}
        raw = record.env_vars or {}
        if isinstance(raw, dict) and "_enc" in raw:
            decrypted = DBCryptographyManager.decrypt_field(raw["_enc"])
            try:
                return json.loads(decrypted) if decrypted else {}
            except Exception:
                return {}
        return raw if isinstance(raw, dict) else {}

    @staticmethod
    def patch_mcp_integration_env_vars(
        session: Session, client_id: str, provider: str, patch: dict
    ) -> bool:
        """Merges new key-value pairs into an existing integration's env_vars."""
        record = (
            session.query(IntegrationMCP)
            .filter(
                IntegrationMCP.client_id == client_id,
                IntegrationMCP.provider == provider,
                IntegrationMCP.is_active == True,
            )
            .first()
        )
        if not record:
            return False

        raw = record.env_vars or {}
        if isinstance(raw, dict) and "_enc" in raw:
            decrypted = DBCryptographyManager.decrypt_field(raw["_enc"])
            try:
                env_dict = json.loads(decrypted) if decrypted else {}
            except Exception:
                env_dict = {}
        elif isinstance(raw, dict):
            env_dict = raw
        else:
            env_dict = {}

        env_dict.update(patch)
        record.env_vars = {
            "_enc": DBCryptographyManager.encrypt_field(json.dumps(env_dict))
        }
        session.commit()
        return True

    @staticmethod
    def delete_mcp_integration(
        session: Session, integration_id: str, client_id: str
    ) -> bool:
        """Desativa uma integração MCP (soft delete)."""
        record = (
            session.query(IntegrationMCP)
            .filter(
                IntegrationMCP.integration_id == integration_id,
                IntegrationMCP.client_id == client_id,
            )
            .first()
        )
        if not record:
            return False
        record.is_active = False
        session.commit()
        return True

    @staticmethod
    def mark_integration_token_invalid(
        session: Session, client_id: str, provider: str
    ) -> bool:
        """Marca o token de uma integração como inválido (requer reconexão)."""
        record = (
            session.query(IntegrationMCP)
            .filter(
                IntegrationMCP.client_id == client_id,
                IntegrationMCP.provider == provider,
                IntegrationMCP.is_active == True,
            )
            .first()
        )
        if not record:
            return False
        record.token_valid = False
        session.commit()
        return True

    @staticmethod
    def mark_integration_token_valid(
        session: Session, client_id: str, provider: str
    ) -> bool:
        """Marca o token de uma integração como válido."""
        record = (
            session.query(IntegrationMCP)
            .filter(
                IntegrationMCP.client_id == client_id,
                IntegrationMCP.provider == provider,
                IntegrationMCP.is_active == True,
            )
            .first()
        )
        if not record:
            return False
        record.token_valid = True
        session.commit()
        return True

    # ==================== ACCESS TOKEN OPERATIONS ====================

    @staticmethod
    def save_access_token(
        session: Session,
        token_id: str,
        user_id: int,
        client_id: int,
        token_hash: str,
        expires_at,
    ) -> bool:
        """
        Salvar access token no banco de dados.

        Em produção: salva local + enfileira para cloud

        Args:
            session: Sessão SQL
            token_id: ID único do token
            user_id: ID do usuário
            client_id: ID do cliente
            token_hash: Hash do token
            expires_at: Data de expiração

        Returns:
            True se salvo com sucesso
        """
        write_source = DatabaseManager._get_read_source()
        debug(f"[DB Write] Saving access token to: {write_source}")

        try:
            query = text(
                """
                INSERT INTO access_tokens (token_id, user_id, token_hash, expires_at)
                VALUES (:token_id, :user_id, :token_hash, :expires_at)
            """
            )
            params = {
                "token_id": token_id,
                "user_id": user_id,
                "token_hash": token_hash,
                "expires_at": expires_at,
            }
            session.execute(query, params)
            session.commit()
            debug(f"Access token saved: {token_id} (write_to: {write_source})")

            return True
        except Exception as e:
            session.rollback()
            error(f"[DB] Erro ao salvar access token ({write_source}): {e}")
            return False

    @staticmethod
    def get_access_token(session: Session, token_id: str) -> Optional[Dict]:
        """
        Buscar access token pelo ID.

        Args:
            session: Sessão SQL
            token_id: ID do token

        Returns:
            Dict com dados do token ou None
        """
        read_source = DatabaseManager._get_read_source()
        debug(f"[DB Read] Fetching access token from: {read_source}")
        try:
            query = text(
                "SELECT * FROM access_tokens WHERE token_id = :token_id AND revoked_at IS NULL"
            )
            result = session.execute(query, {"token_id": token_id}).fetchone()
            if result:
                return (
                    dict(result._mapping)
                    if hasattr(result, "_mapping")
                    else dict(result)
                )
            return None
        except Exception as e:
            error(f"[DB] Erro ao buscar access token ({read_source}): {e}")
            return None

    @staticmethod
    def revoke_access_token(session: Session, token_id: str) -> bool:
        """
        Revogar access token.

        Em produção: revoga local + enfileira para cloud

        Args:
            session: Sessão SQL
            token_id: ID do token

        Returns:
            True se revogado com sucesso
        """
        write_source = DatabaseManager._get_read_source()
        debug(f"[DB Write] Revoking access token on: {write_source}")

        try:
            query = text(
                "UPDATE access_tokens SET revoked_at = CURRENT_TIMESTAMP WHERE token_id = :token_id"
            )
            session.execute(query, {"token_id": token_id})
            session.commit()
            debug(f"Access token revoked: {token_id} (write_to: {write_source})")

            return True
        except Exception as e:
            session.rollback()
            error(f"[DB] Erro ao revogar access token ({write_source}): {e}")
            return False

    # ==================== REFRESH TOKEN OPERATIONS ====================

    @staticmethod
    def save_refresh_token(
        session: Session,
        token_id: str,
        user_id: int,
        client_id: int,
        token_hash: str,
        expires_at,
    ) -> bool:
        """
        Salvar refresh token no banco de dados.

        Em produção: salva local + enfileira para cloud

        Args:
            session: Sessão SQL
            token_id: ID único do token
            user_id: ID do usuário
            client_id: ID do cliente
            token_hash: Hash do token
            expires_at: Data de expiração

        Returns:
            True se salvo com sucesso
        """
        write_source = DatabaseManager._get_read_source()
        debug(f"[DB Write] Saving refresh token to: {write_source}")

        try:
            query = text(
                """
                INSERT INTO refresh_tokens (token_id, user_id, token_hash, expires_at)
                VALUES (:token_id, :user_id, :token_hash, :expires_at)
            """
            )
            params = {
                "token_id": token_id,
                "user_id": user_id,
                "token_hash": token_hash,
                "expires_at": expires_at,
            }
            session.execute(query, params)
            session.commit()
            debug(f"Refresh token saved: {token_id} (write_to: {write_source})")

            return True
        except Exception as e:
            session.rollback()
            error(f"[DB] Erro ao salvar refresh token ({write_source}): {e}")
            return False

    @staticmethod
    def get_refresh_token(session: Session, token_id: str) -> Optional[Dict]:
        """
        Buscar refresh token pelo ID.

        Args:
            session: Sessão SQL
            token_id: ID do token

        Returns:
            Dict com dados do token ou None
        """
        read_source = DatabaseManager._get_read_source()
        debug(f"[DB Read] Fetching refresh token from: {read_source}")

        try:
            query = text(
                "SELECT * FROM refresh_tokens WHERE token_id = :token_id AND revoked_at IS NULL"
            )
            result = session.execute(query, {"token_id": token_id}).fetchone()
            if result:
                return (
                    dict(result._mapping)
                    if hasattr(result, "_mapping")
                    else dict(result)
                )
            return None
        except Exception as e:
            error(f"[DB] Erro ao buscar refresh token ({read_source}): {e}")
            return None

    @staticmethod
    def revoke_refresh_token(session: Session, token_id: str) -> bool:
        """
        Revogar refresh token.

        Em produção: revoga local + enfileira para cloud

        Args:
            session: Sessão SQL
            token_id: ID do token

        Returns:
            True se revogado com sucesso
        """
        write_source = DatabaseManager._get_read_source()
        debug(f"[DB Write] Revoking refresh token on: {write_source}")

        try:
            query = text(
                "UPDATE refresh_tokens SET revoked_at = CURRENT_TIMESTAMP WHERE token_id = :token_id"
            )
            session.execute(query, {"token_id": token_id})
            session.commit()
            debug(f"Refresh token revoked: {token_id} (write_to: {write_source})")

            return True
        except Exception as e:
            session.rollback()
            error(f"[DB] Erro ao revogar refresh token ({write_source}): {e}")
            return False

    # ==================== USER SESSIONS OPERATIONS (FASE 2) ====================

    @staticmethod
    def save_user_session(
        session: Session,
        session_id: str,
        user_id: str,
        client_id: str,
        access_token_hash: str,
        refresh_token_hash: str,
        fingerprint_hash: str = None,
        last_ip: str = None,
        last_user_agent: str = None,
        access_expires_at=None,
        refresh_expires_at=None,
    ) -> bool:
        """
        Salvar nova user session com contexto de segurança.

        Args:
            session_id: ID único da session
            user_id: ID do usuário
            client_id: ID do cliente
            access_token_hash: SHA-256 do access token
            refresh_token_hash: SHA-256 do refresh token
            fingerprint_hash: SHA-256 do fingerprint_id
            last_ip: Último IP da session
            last_user_agent: Último User-Agent da session
            access_expires_at: Data de expiração do access token
            refresh_expires_at: Data de expiração do refresh token

        Returns:
            True se salvo com sucesso
        """
        write_source = DatabaseManager._get_read_source()
        debug(f"[DB Write] Saving user session to: {write_source}")

        try:
            query = text(
                """
                INSERT INTO user_sessions
                (session_id, user_id, client_id, access_token_hash, refresh_token_hash,
                 fingerprint_hash, last_ip, last_user_agent, access_expires_at, refresh_expires_at)
                VALUES (:session_id, :user_id, :client_id, :access_token_hash, :refresh_token_hash,
                        :fingerprint_hash, :last_ip, :last_user_agent, :access_expires_at, :refresh_expires_at)
            """
            )
            session.execute(
                query,
                {
                    "session_id": session_id,
                    "user_id": user_id,
                    "client_id": client_id,
                    "access_token_hash": access_token_hash,
                    "refresh_token_hash": refresh_token_hash,
                    "fingerprint_hash": fingerprint_hash,
                    "last_ip": last_ip,
                    "last_user_agent": last_user_agent,
                    "access_expires_at": access_expires_at,
                    "refresh_expires_at": refresh_expires_at,
                },
            )
            session.commit()
            debug(f"User session saved: {session_id}")

            return True
        except Exception as e:
            session.rollback()
            error(f"[DB] Erro ao salvar user session ({write_source}): {e}")
            return False

    @staticmethod
    def get_user_session(session: Session, session_id: str) -> Optional[Dict]:
        """
        Buscar user session pelo session_id.

        Args:
            session_id: ID da session

        Returns:
            Dict com dados da session ou None
        """
        read_source = DatabaseManager._get_read_source()
        debug(f"[DB Read] Fetching user session from: {read_source}")

        try:
            query = text(
                "SELECT * FROM user_sessions WHERE session_id = :session_id AND is_revoked = 0"
            )
            result = session.execute(query, {"session_id": session_id}).fetchone()
            if result:
                return (
                    dict(result._mapping)
                    if hasattr(result, "_mapping")
                    else dict(result)
                )
            return None
        except Exception as e:
            error(f"[DB] Erro ao buscar user session ({read_source}): {e}")
            return None

    @staticmethod
    def update_session_risk_score(
        session: Session, session_id: str, risk_score: float
    ) -> bool:
        """
        Atualizar risk_score de uma session.

        Args:
            session_id: ID da session
            risk_score: Novo risk_score (0.0 = seguro, 1.0 = suspeito)

        Returns:
            True se atualizado com sucesso
        """
        write_source = DatabaseManager._get_read_source()
        debug(f"[DB Write] Updating session risk_score on: {write_source}")

        try:
            query = text(
                "UPDATE user_sessions SET risk_score = :risk_score, last_used_at = CURRENT_TIMESTAMP WHERE session_id = :session_id"
            )
            session.execute(query, {"session_id": session_id, "risk_score": risk_score})
            session.commit()
            debug(f"Session risk_score updated: {session_id} = {risk_score}")

            return True
        except Exception as e:
            session.rollback()
            error(f"[DB] Erro ao atualizar risk_score ({write_source}): {e}")
            return False

    @staticmethod
    def revoke_user_session(
        session: Session, session_id: str, reason: str = None
    ) -> bool:
        """
        Revogar uma user session.

        Args:
            session_id: ID da session
            reason: Motivo da revogação

        Returns:
            True se revogado com sucesso
        """
        write_source = DatabaseManager._get_read_source()
        debug(f"[DB Write] Revoking user session on: {write_source}")

        try:
            query = text(
                "UPDATE user_sessions SET is_revoked = 1, revocation_reason = :reason WHERE session_id = :session_id"
            )
            session.execute(query, {"session_id": session_id, "reason": reason})
            session.commit()
            debug(f"User session revoked: {session_id} — reason={reason}")

            return True
        except Exception as e:
            session.rollback()
            error(f"[DB] Erro ao revogar user session ({write_source}): {e}")
            return False

    # ==================== CHAT OPERATIONS (SQL) ====================

    @staticmethod
    def create_chat(session: Session, chat_data: dict) -> Chat:
        """Criar novo chat no banco SQL.

        Em produção: cria local + enfileira para cloud
        """
        write_source = DatabaseManager._get_read_source()
        debug(f"[DB Write] Creating chat on: {write_source}")

        chat = Chat(**chat_data)
        session.add(chat)
        session.commit()
        session.refresh(chat)
        info(f"Chat created in SQL ({write_source}): {chat.chat_id}")

        return chat

    @staticmethod
    def get_chat_sql(session: Session, chat_id: str) -> Optional[Chat]:
        """Obter chat do banco SQL."""
        read_source = DatabaseManager._get_read_source()
        debug(f"[DB Read] Fetching chat from: {read_source}")
        return session.query(Chat).filter(Chat.chat_id == chat_id).first()

    @staticmethod
    def get_user_chats(session: Session, user_id: str) -> List[Chat]:
        """Obter todos os chats de um usuário."""
        read_source = DatabaseManager._get_read_source()
        debug(f"[DB Read] Fetching user chats from: {read_source}")
        return session.query(Chat).filter(Chat.user_id == user_id).all()

    # ==================== MESSAGE OPERATIONS (SQL) ====================

    @staticmethod
    def create_message(session: Session, message_data: dict) -> Message:
        """Criar nova mensagem no banco SQL.

        Em produção: cria local + enfileira para cloud
        """
        write_source = DatabaseManager._get_read_source()
        debug(f"[DB Write] Creating message on: {write_source}")

        message = Message(**message_data)
        session.add(message)
        session.commit()
        session.refresh(message)

        # Atualizar contador de mensagens no chat
        chat = session.query(Chat).filter(Chat.chat_id == message.chat_id).first()
        if chat:
            chat.updated_at = datetime.utcnow()
            session.commit()

        debug(
            f"Message created in SQL ({write_source}): {message.message_id} (type: {message.message_type})"
        )

        return message

    @staticmethod
    def get_chat_messages_sql(session: Session, chat_id: str) -> List[Message]:
        """Obter mensagens de um chat do banco SQL."""
        read_source = DatabaseManager._get_read_source()
        debug(f"[DB Read] Fetching chat messages from: {read_source}")
        return (
            session.query(Message)
            .filter(Message.chat_id == chat_id)
            .order_by(Message.created_at)
            .all()
        )

    @staticmethod
    def save_ai_message(
        session: Session, chat_id: str, content: str, model: str = "gpt-4o-mini"
    ) -> Message:
        """Salvar mensagem da IA no banco SQL.

        Em produção: salva local + enfileira para cloud
        """
        # Gerar ID único para a mensagem
        import uuid

        message_id = f"ai_{uuid.uuid4().hex[:8]}"

        message_data = {
            "message_id": message_id,
            "chat_id": chat_id,
            "message_type": "ai",
            "content": content,
            "model": model,
        }

        return DatabaseManager.create_message(session, message_data)

    # ==================== FILE OPERATIONS ====================
    # Files agora são gerenciados via tabela 'files' (expandida)
    # Suporta: documents, assets, uploads, attachments

    @staticmethod
    def save_file_record(session: Session, file_data: dict) -> bool:
        """
        Registrar arquivo na tabela files.

        Em produção: salva local + enfileira para cloud

        Args:
            session: Sessão SQL
            file_data: Dict com:
                - file_id: ID único
                - file_hash: Hash do arquivo
                - file_name: Nome do arquivo
                - file_type: Tipo MIME
                - file_size: Tamanho em bytes
                - user_id: ID do usuário
                - client_id: ID do cliente
                - chat_id: ID do chat (opcional)
                - message_id: ID da mensagem (opcional)
                - file_category: 'document', 'asset', 'upload', 'attachment'
                - storage_path: Caminho do armazenamento
                - storage_env: 'local' ou 'cloud'
                - is_temp: True/False

        Returns:
            True se salvo com sucesso
        """
        write_source = DatabaseManager._get_read_source()
        debug(f"[DB Write] Saving file record to: {write_source}")

        try:
            query = text(
                """
                INSERT INTO files (
                    file_id, file_hash, file_name, file_type, file_size,
                    user_id, client_id, chat_id, message_id, file_category,
                    storage_path, storage_env, is_temp
                ) VALUES (
                    :file_id, :file_hash, :file_name, :file_type, :file_size,
                    :user_id, :client_id, :chat_id, :message_id, :file_category,
                    :storage_path, :storage_env, :is_temp
                )
            """
            )
            session.execute(query, file_data)
            session.commit()
            debug(
                f"File record saved: {file_data.get('file_id')} ({file_data.get('file_category')}) (write_to: {write_source})"
            )

            return True
        except Exception as e:
            session.rollback()
            error(f"[DB] Erro ao salvar file record ({write_source}): {e}")
            return False

    @staticmethod
    def get_file_by_hash(session: Session, file_hash: str) -> Optional[Dict]:
        """
        Buscar arquivo por hash.

        Args:
            session: Sessão SQL
            file_hash: Hash do arquivo

        Returns:
            Dict com dados do arquivo ou None
        """
        # DEPRECATED: Use get_generated_content_by_id() para assets
        # A tabela 'files' foi removida em favor de 'generated_content'
        debug(
            "[DB] get_file_by_hash() is deprecated - use get_generated_content_by_id()"
        )
        return None

    @staticmethod
    def get_file_by_id(session: Session, file_id: str) -> Optional[Dict]:
        """
        Buscar arquivo por ID.

        Args:
            session: Sessão SQL
            file_id: ID do arquivo (ou generated_content_id)

        Returns:
            Dict com dados do arquivo ou None
        """
        # DEPRECATED: Use get_generated_content_by_id() para assets
        # A tabela 'files' foi removida em favor de 'generated_content'
        # Para backward compatibility, tentar buscar em generated_content
        try:
            from App.Core.Crunch.TablesSQL.Models import GeneratedContent
            from uuid import UUID

            # Tentar converter para UUID
            try:
                content_uuid = UUID(file_id)
            except:
                content_uuid = file_id

            asset = (
                session.query(GeneratedContent)
                .filter(GeneratedContent.asset_id == content_uuid)
                .first()
            )

            if asset:
                return {
                    "file_id": str(asset.asset_id),
                    "file_name": asset.content_name,
                    "chat_id": asset.chat_id,
                    "client_id": asset.client_id,
                    "user_id": asset.user_id,
                    "storage_path": asset.storage_path,
                    "storage_env": asset.storage_env,
                    "file_category": "asset",
                    "type": asset.type,
                }
            return None
        except Exception as e:
            debug(f"[DB] get_file_by_id() - Tentando buscar em generated_content: {e}")
            return None

    @staticmethod
    def get_generated_content_by_id(
        session: Session, generated_content_id: str
    ) -> Optional[Dict]:
        """
        Buscar conteúdo gerado (asset) por ID.

        Args:
            session: Sessão SQL
            generated_content_id: ID do conteúdo gerado (UUID string)

        Returns:
            Dict com dados do asset ou None
        """
        try:
            from App.Core.Crunch.TablesSQL.Models import GeneratedContent

            # asset_id é armazenado como STRING no banco, não como UUID
            asset_id_str = str(generated_content_id).strip()

            asset = (
                session.query(GeneratedContent)
                .filter(GeneratedContent.asset_id == asset_id_str)
                .first()
            )

            if asset:
                return {
                    "file_id": str(asset.asset_id),
                    "file_name": asset.content_name,
                    "chat_id": asset.chat_id,
                    "client_id": asset.client_id,
                    "user_id": asset.user_id,
                    "storage_path": asset.storage_path,
                    "storage_env": asset.storage_env,
                    "file_category": "asset",
                    "type": asset.type,
                    "variation_id": asset.variation_id,
                    "approval_status": asset.approval_status,
                    "feedback": asset.feedback,
                }
            return None
        except Exception as e:
            error(f"[DB] Erro ao buscar asset por ID: {e}")
            return None

    @staticmethod
    def get_chat_files(
        session: Session, chat_id: str, file_category: str = None
    ) -> List[Dict]:
        """
        Listar arquivos de um chat.

        Args:
            session: Sessão SQL
            chat_id: ID do chat
            file_category: Filtrar por categoria (opcional)

        Returns:
            Lista de arquivos
        """
        read_source = DatabaseManager._get_read_source()
        debug(f"[DB Read] Fetching chat files from: {read_source}")

        try:
            # Se file_category == 'asset', buscar em generated_content
            if file_category and file_category.lower() == "asset":
                query = text(
                    """
                    SELECT a.id, a.asset_id AS file_id, a.content_name AS file_name, a.type AS file_type,
                           a.storage_path, a.created_at,
                           a.variation_id, a.ratio,
                           a.approval_status,
                           a.feedback AS approval_feedback,
                           NULL AS file_hash, NULL AS file_size, NULL AS deleted_at
                    FROM assets a
                    WHERE a.chat_id = :chat_id
                    ORDER BY a.created_at DESC
                """
                )
                results = session.execute(query, {"chat_id": chat_id}).fetchall()
            else:
                # Para outras categorias, retornar vazio (files table foi removida)
                results = []

            return [
                dict(row._mapping) if hasattr(row, "_mapping") else dict(row)
                for row in results
            ]
        except Exception as e:
            error(f"[DB] Erro ao listar arquivos do chat: {e}")
            return []

    @staticmethod
    def get_client_files(
        session: Session, client_id: int, file_category: str = None, chat_id: str = None
    ) -> List[Dict]:
        """
        Listar arquivos de um cliente.

        Args:
            session: Sessão SQL
            client_id: ID do cliente
            file_category: Filtrar por categoria (opcional)
            chat_id: Filtrar por chat específico (opcional)

        Returns:
            Lista de arquivos
        """
        try:
            if file_category and file_category.lower() == "asset":
                if chat_id:
                    query = text(
                        """
                        SELECT a.id, a.asset_id AS file_id, a.content_name AS file_name,
                               a.type AS file_type, a.storage_path, a.chat_id, a.created_at,
                               a.variation_id, a.ratio,
                               a.approval_status,
                               a.feedback AS approval_feedback
                        FROM assets a
                        WHERE a.client_id = :client_id AND a.chat_id = :chat_id
                        ORDER BY a.created_at DESC
                    """
                    )
                    results = session.execute(
                        query, {"client_id": client_id, "chat_id": chat_id}
                    ).fetchall()
                else:
                    query = text(
                        """
                        SELECT a.id, a.asset_id AS file_id, a.content_name AS file_name,
                               a.type AS file_type, a.storage_path, a.chat_id, a.created_at,
                               a.variation_id, a.ratio,
                               a.approval_status,
                               a.feedback AS approval_feedback
                        FROM assets a
                        WHERE a.client_id = :client_id
                        ORDER BY a.created_at DESC
                    """
                    )
                    results = session.execute(
                        query, {"client_id": client_id}
                    ).fetchall()
            else:
                results = []

            return [
                dict(row._mapping) if hasattr(row, "_mapping") else dict(row)
                for row in results
            ]
        except Exception as e:
            error(f"[DB] Erro ao listar arquivos do cliente: {e}")
            return []

    @staticmethod
    def get_client_documents(session: Session, client_id: str) -> List[Dict]:
        """Lista todos os documentos de um cliente, de todos os chats."""
        try:
            query = text(
                """
                SELECT document_id, tool_type, title, chat_id, created_at, updated_at
                FROM documents
                WHERE client_id = :client_id
                ORDER BY created_at DESC
            """
            )
            results = session.execute(query, {"client_id": client_id}).fetchall()
            return [dict(row._mapping) for row in results]
        except Exception as e:
            error(f"[DB] Erro ao listar documentos do cliente: {e}")
            return []

    @staticmethod
    def mark_file_deleted(session: Session, file_id: str) -> bool:
        """
        Marcar arquivo como deletado (soft delete).

        Em produção: deleta local + enfileira para cloud

        Args:
            session: Sessão SQL
            file_id: ID do arquivo

        Returns:
            True se deletado com sucesso
        """
        try:
            query = text(
                "UPDATE files SET deleted_at = CURRENT_TIMESTAMP WHERE file_id = :file_id"
            )
            session.execute(query, {"file_id": file_id})
            session.commit()
            debug(f"File marked as deleted: {file_id}")

            return True
        except Exception as e:
            session.rollback()
            error(f"[DB] Erro ao deletar arquivo: {e}")
            return False

    # ==================== TASK OPERATIONS ====================

    @staticmethod
    def save_task(
        session: Session,
        task_id: str,
        step_id: str,
        chat_id: str,
        user_id: str,
        task_name: str,
        step_name: str,
        step_context: str,
        status: str,
    ) -> bool:
        """
        Salvar task no banco de dados.

        Em produção: salva local + enfileira para cloud

        Args:
            session: Sessão SQL
            task_id: ID do grupo de tasks (pode repetir)
            step_id: ID único do step
            chat_id: ID do chat
            user_id: ID do usuário (proprietário da task)
            task_name: Nome da task/grupo
            step_name: Nome do step
            step_context: Identificador do step (texto ou número)
            status: 'pending', 'success', 'failed', 'finished'

        Returns:
            True se salva com sucesso
        """
        try:
            query = text(
                """
                INSERT INTO tasks (task_id, step_id, chat_id, user_id, task_name, step_name, step_context, status)
                VALUES (:task_id, :step_id, :chat_id, :user_id, :task_name, :step_name, :step_context, :status)
                ON CONFLICT(step_id) DO UPDATE SET
                    status = :status,
                    updated_at = CURRENT_TIMESTAMP,
                    completed_at = CASE WHEN :status IN ('success', 'failed', 'finished') THEN CURRENT_TIMESTAMP ELSE NULL END
            """
            )
            params = {
                "task_id": task_id,
                "step_id": step_id,
                "chat_id": chat_id,
                "user_id": user_id,
                "task_name": task_name,
                "step_name": step_name,
                "step_context": step_context,
                "status": status,
            }
            session.execute(query, params)
            session.commit()
            debug(f"Task saved: {task_name}/{step_name} = {status}")

            return True
        except Exception as e:
            session.rollback()
            error(f"[DB] Erro ao salvar task: {e}")
            return False

    @staticmethod
    def get_chat_tasks(
        session: Session, chat_id: str, status: str = None
    ) -> List[Dict]:
        """
        Listar tasks de um chat.

        Args:
            session: Sessão SQL
            chat_id: ID do chat
            status: Filtrar por status (opcional)

        Returns:
            Lista de tasks
        """
        try:
            if status:
                query = text(
                    """
                    SELECT * FROM tasks
                    WHERE chat_id = :chat_id AND status = :status
                    ORDER BY created_at ASC, id ASC
                """
                )
                results = session.execute(
                    query, {"chat_id": chat_id, "status": status}
                ).fetchall()
            else:
                query = text(
                    """
                    SELECT * FROM tasks
                    WHERE chat_id = :chat_id
                    ORDER BY created_at ASC, id ASC
                """
                )
                results = session.execute(query, {"chat_id": chat_id}).fetchall()

            return [
                dict(row._mapping) if hasattr(row, "_mapping") else dict(row)
                for row in results
            ]
        except Exception as e:
            error(f"[DB] Erro ao listar tasks do chat: {e}")
            return []

    @staticmethod
    def get_task_by_name_step(
        session: Session, chat_id: str, task_name: str, step_name: str
    ) -> Optional[Dict]:
        """
        Buscar task específica por nome e step.

        Args:
            session: Sessão SQL
            chat_id: ID do chat
            task_name: Nome da task
            step_name: Nome do step

        Returns:
            Dict com dados da task ou None
        """
        try:
            query = text(
                """
                SELECT * FROM tasks
                WHERE chat_id = :chat_id AND task_name = :task_name AND step_name = :step_name
            """
            )
            result = session.execute(
                query,
                {"chat_id": chat_id, "task_name": task_name, "step_name": step_name},
            ).fetchone()

            if result:
                return (
                    dict(result._mapping)
                    if hasattr(result, "_mapping")
                    else dict(result)
                )
            return None
        except Exception as e:
            error(f"[DB] Erro ao buscar task: {e}")
            return None

    # ==================== ISOLATED CHAT OPERATIONS ====================

    @staticmethod
    def get_or_create_isolated_chat(
        session: Session, chat_id: str, user_id: str, agent_id: str
    ) -> IsolatedChat:
        """
        Obter ou criar chat isolado para um agente.

        Em produção: cria local + enfileira para cloud

        Args:
            session: Sessão SQL
            chat_id: ID do chat principal (identificador único)
            user_id: ID do usuário (para auditoria/créditos, não armazenado)
            agent_id: ID do agent

        Returns:
            IsolatedChat encontrado ou criado
        """
        isolated_chat = (
            session.query(IsolatedChat)
            .filter(IsolatedChat.chat_id == chat_id, IsolatedChat.agent_id == agent_id)
            .first()
        )

        if not isolated_chat:
            # The DB schema may have UNIQUE on chat_id alone (legacy). Check before inserting.
            isolated_chat = (
                session.query(IsolatedChat)
                .filter(IsolatedChat.chat_id == chat_id)
                .first()
            )
            if isolated_chat:
                debug(
                    f"Isolated chat found by chat_id (agent_id mismatch: stored={isolated_chat.agent_id}, requested={agent_id}) — reusing"
                )
                return isolated_chat

            # Verificar se o chat existe em chats (constraint de chave estrangeira)
            from App.Core.Crunch.TablesSQL.Models import Chat

            chat_exists = session.query(Chat).filter(Chat.chat_id == chat_id).first()

            if not chat_exists:
                # Criar chat padrão se não existir (para satisfazer a FK constraint)
                new_chat = Chat(
                    chat_id=chat_id,
                    user_id=user_id,
                    chat_name=f"Chat {chat_id[:8]}",
                    status="active",
                )
                session.add(new_chat)
                session.flush()  # Flush para garantir que o chat foi inserido antes de criar isolated_chat
                debug(f"Chat criado automaticamente: {chat_id}")

            isolated_chat = IsolatedChat(chat_id=chat_id, agent_id=agent_id)
            session.add(isolated_chat)
            session.commit()
            session.refresh(isolated_chat)
            debug(
                f"Isolated chat created ({database.get_db_env()}) for agent {agent_id} in chat {chat_id}"
            )

        return isolated_chat

    @staticmethod
    def save_isolated_message(
        session: Session,
        isolated_chat_id: str,
        agent_id: str,
        agent: str,
        role: str,
        content: str,
        message_type: str = "message",
        isolated_message_id: Optional[str] = None,
        tool_call_id: Optional[str] = None,
        tool_called: Optional[str] = None,
        tool_call_type: Optional[str] = None,
        fk_tool_id: Optional[str] = None,
        input_tokens: int = 0,
        output_tokens: int = 0,
    ) -> IsolatedMessage:
        """
        Salvar mensagem isolada para um agent.

        Em produção: salva local + enfileira para cloud

        Args:
            session: Sessão SQL
            isolated_chat_id: Chat ID (text) do chat isolado
            agent_id: ID do agente que enviou a mensagem
            agent: Nome/tipo do agente
            role: 'user', 'assistant', 'system'
            content: Conteúdo da mensagem
            message_type: 'message', 'tool_call'
            isolated_message_id: ID único da mensagem (se None, gera novo)
            tool_call_id: ID do tool call (mesmo para INPUT e OUTPUT)
            tool_called: Nome da tool (context, client, task, etc)
            input_tokens: Tokens de entrada retornados pela LLM
            output_tokens: Tokens de saída retornados pela LLM

        Returns:
            IsolatedMessage criada
        """
        if not isolated_message_id:
            isolated_message_id = str(uuid_lib.uuid4())

        debug(
            f"[SAVE-DEBUG] Before creating IsolatedMessage: content length = {len(content)}, first 50 chars = '{content[:50]}...', last 50 chars = '...{content[-50:]}'"
        )
        debug(
            f"[SAVE-DEBUG] isolated_chat_id type: {type(isolated_chat_id)}, value: {isolated_chat_id}"
        )

        try:
            isolated_message = IsolatedMessage(
                isolated_chat_id=isolated_chat_id,
                isolated_message_id=isolated_message_id,
                tool_call_id=tool_call_id,
                tool_called=tool_called,
                tool_call_type=tool_call_type,
                fk_tool_id=fk_tool_id,
                agent_id=agent_id,
                agent=agent,
                role=role,
                content=content,
                type=message_type,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
            )
            debug("[SAVE-DEBUG] IsolatedMessage object created successfully")
        except Exception as e:
            error(f"[SAVE-DEBUG] Error creating IsolatedMessage: {e}")
            raise
        debug(
            f"[SAVE-DEBUG] After creating IsolatedMessage object: content attr length = {len(isolated_message.content)}"
        )

        try:
            session.add(isolated_message)
            debug("[SAVE-DEBUG] Object added to session")
            session.commit()
            debug("[SAVE-DEBUG] Commit successful")
        except Exception as e:
            error(f"[SAVE-DEBUG] Error during add/commit: {e}")
            session.rollback()
            raise

        debug(
            f"[SAVE-DEBUG] After commit: content attr length = {len(isolated_message.content)}"
        )

        session.refresh(isolated_message)

        debug(
            f"[SAVE-DEBUG] After refresh: content attr length = {len(isolated_message.content)}, last 50 chars = '...{isolated_message.content[-50:]}'"
        )

        debug(
            f"Isolated message saved ({database.get_db_env()}): {isolated_message_id} (agent: {agent_id}/{agent}, role: {role}, type: {message_type})"
        )

        return isolated_message

    @staticmethod
    def get_isolated_messages(
        session: Session, isolated_chat_id: str
    ) -> List[IsolatedMessage]:
        """
        Obter todas as mensagens de um chat isolado.

        Args:
            session: Sessão SQL
            isolated_chat_id: Chat ID (text) do chat isolado

        Returns:
            Lista de IsolatedMessage
        """
        return (
            session.query(IsolatedMessage)
            .filter(IsolatedMessage.isolated_chat_id == isolated_chat_id)
            .order_by(IsolatedMessage.created_at)
            .all()
        )

    @staticmethod
    def _extract_image_routes(content: str) -> List[str]:
        """
        Extrai rotas de imagem do conteúdo de uma mensagem.
        Detecta rotas com extensões: jpg, jpeg, png, gif, webp, svg, bmp, ico

        Args:
            content: Conteúdo da mensagem

        Returns:
            Lista de rotas de imagem encontradas
        """
        if not content or not isinstance(content, str):
            return []

        # Padrão para detectar rotas com extensão de imagem
        # Aceita: /path/to/image.jpg, \path\to\image.jpg, ./relative/path.png, etc
        pattern = r"(?:[/\\][\w\-\.]+)*[/\\][\w\-\.]+\.(?:jpg|jpeg|png|gif|webp|svg|bmp|ico)(?:\?[^\s]*)?"
        matches = re.findall(pattern, content, re.IGNORECASE)
        return matches

    @staticmethod
    def sync_isolated_to_main(session: Session, chat_id: str, agent_id: str):
        """
        Sincronizar mensagens de chat isolado para o chat principal.
        Delega lógica de sincronização para SyncManager.

        APENAS mensagens do agent 'orchestrator-global' SÃO sincronizadas.
        Outras mensagens de agents especializados vão para tasks.

        Args:
            session: Sessão SQL
            chat_id: ID do chat principal
            agent_id: ID do agent
        """
        try:
            # 1. Buscar chat isolado
            isolated_chat = (
                session.query(IsolatedChat)
                .filter(
                    IsolatedChat.chat_id == chat_id, IsolatedChat.agent_id == agent_id
                )
                .first()
            )

            if not isolated_chat:
                # Fallback: DB may have UNIQUE on chat_id only — find any row for this chat
                isolated_chat = (
                    session.query(IsolatedChat)
                    .filter(IsolatedChat.chat_id == chat_id)
                    .first()
                )
                if not isolated_chat:
                    debug(
                        f"Isolated chat not found for sync ({database.get_db_env()}): {chat_id}/{agent_id}"
                    )
                    return
                debug(
                    f"Isolated chat found by chat_id for sync (agent_id mismatch: stored={isolated_chat.agent_id}, requested={agent_id})"
                )

            # 2. Buscar mensagens isoladas (estratégia baseada em agent_id)
            if agent_id == "orchestrator-global":
                from sqlalchemy import or_ as _or

                isolated_messages = (
                    session.query(IsolatedMessage)
                    .filter(
                        IsolatedMessage.isolated_chat_id == isolated_chat.chat_id,
                        _or(
                            IsolatedMessage.agent_id == "orchestrator-global",
                            IsolatedMessage.agent_id == "user",
                        ),
                        IsolatedMessage.role != "system",
                    )
                    .order_by(IsolatedMessage.created_at)
                    .all()
                )
                debug(
                    f"[Sync] Orchestrator mode: sincronizando todas as mensagens de {agent_id}"
                )
            else:
                from sqlalchemy import or_ as _or, and_ as _and

                isolated_messages = (
                    session.query(IsolatedMessage)
                    .filter(
                        IsolatedMessage.isolated_chat_id == isolated_chat.chat_id,
                        IsolatedMessage.agent_id == agent_id,
                        _or(
                            IsolatedMessage.type == "tool_call",
                            _and(
                                IsolatedMessage.role == "assistant",
                                IsolatedMessage.type == "message",
                            ),
                        ),
                    )
                    .order_by(IsolatedMessage.created_at)
                    .all()
                )
                debug(
                    f"[Sync] Non-orchestrator mode: sincronizando tool_calls e resposta final de {agent_id}"
                )

            # 3. Delegar toda sincronização para SyncManager
            # DBManager é apenas persistência, SyncManager cuida da lógica
            synced_count = SyncManager.sync_isolated_messages(
                session=session, isolated_messages=isolated_messages, chat_id=chat_id
            )

            # 4. Atualizar updated_at dos isolated chats sincronizados
            session.commit()

            # ============================================================================
            # Detectar e definir chat_cover a partir de rotas de imagem em isolated_messages
            # ============================================================================
            try:
                # Buscar todas as IsolatedMessage da conversa ordenadas por data
                all_isolated_msgs = (
                    session.query(IsolatedMessage)
                    .filter(IsolatedMessage.isolated_chat_id == chat_id)
                    .order_by(IsolatedMessage.created_at)
                    .all()
                )

                # Extrair todas as rotas de imagem das mensagens
                last_image_route = None
                for iso_msg in all_isolated_msgs:
                    image_routes = DatabaseManager._extract_image_routes(
                        iso_msg.content
                    )
                    if image_routes:
                        # Pegar a última rota encontrada (será sobrescrita se houver mais imagens depois)
                        last_image_route = image_routes[-1]
                        debug(
                            f"[Sync] Imagem detectada em mensagem {iso_msg.isolated_message_id}: {last_image_route}"
                        )

                # Se encontrou uma rota de imagem, atualizar chat_cover
                if last_image_route:
                    chat = session.query(Chat).filter(Chat.chat_id == chat_id).first()
                    if chat:
                        chat.chat_cover = last_image_route
                        session.commit()
                        debug(f"[Sync] Chat cover definido para: {last_image_route}")
            except Exception as e:
                debug(f"[Sync] Erro ao detectar e definir chat_cover: {e}")
                # Não falhar o sync se houver erro na detecção de imagem

            # ============================================================================
            # Atualizar updated_at do main_chat e isolated_chat após sincronização
            # ============================================================================
            try:
                # Atualizar updated_at do Chat (main_chat)
                chat = session.query(Chat).filter(Chat.chat_id == chat_id).first()
                if chat:
                    chat.updated_at = datetime.utcnow()
                    debug(f"[Sync] Chat {chat_id} updated_at atualizado")

                # Atualizar updated_at do IsolatedChat
                isolated_chat_updated = (
                    session.query(IsolatedChat)
                    .filter(
                        IsolatedChat.chat_id == chat_id,
                        IsolatedChat.agent_id == agent_id,
                    )
                    .first()
                )
                if isolated_chat_updated:
                    isolated_chat_updated.updated_at = datetime.utcnow()
                    debug(
                        f"[Sync] IsolatedChat {chat_id}/{agent_id} updated_at atualizado"
                    )

                session.commit()
                debug(f"[Sync] Updated_at dos chats sincronizados com sucesso")
            except Exception as e:
                debug(f"[Sync] Erro ao atualizar updated_at dos chats: {e}")
                # Não falhar o sync se houver erro na atualização de timestamp

            if agent_id == "orchestrator-global":
                debug(
                    f"[Sync] Synced {synced_count} orchestrator messages to main chat {chat_id} ({database.get_db_env()})"
                )
            else:
                debug(
                    f"[Sync] Synced {synced_count} tool_calls from {agent_id} to main chat (message_type=tool) ({database.get_db_env()})"
                )

        except Exception as e:
            error(f"Error syncing isolated chat to main ({database.get_db_env()}): {e}")
            session.rollback()
            raise

    @staticmethod
    def sync_mediaai_tool_to_main(
        session: Session,
        chat_id: str,
        client_id: int = None,
        user_id: str = None,
        media_type: str = None,
        model: str = None,
        filename: str = None,
    ) -> bool:
        """
        Sincronizar mediaai tool call para chat principal de forma padronizada.

        Em produção: insere local + enfileira para cloud

        Args:
            session: Sessão SQL
            chat_id: ID do chat principal
            client_id: ID do cliente
            media_type: 'image' ou 'video'
            model: Modelo usado (ex: 'flux-pro')
            filename: Nome do arquivo gerado

        Returns:
            True se sincronizado com sucesso
        """
        try:
            import uuid as uuid_lib

            message_id = str(uuid_lib.uuid4())

            content = {
                "tool": "mediaai",
                "type": media_type,
                "model": model,
                "filename": filename,
                "success": True,
                "timestamp": datetime.utcnow().isoformat(),
            }

            message_data = {
                "message_id": message_id,
                "chat_id": chat_id,
                "message_type": "tool",
                "content": json.dumps(content, ensure_ascii=False),
                "model": "mediaai",
            }

            msg = Message(**message_data)
            session.add(msg)
            session.commit()

            debug(
                f"[Sync] MediaAI tool synced to main chat: {filename} ({media_type}/{model})"
            )

            return True

        except Exception as e:
            session.rollback()
            error(f"[Sync] Erro ao sincronizar mediaai tool: {e}")
            return False

    @staticmethod
    def update_external_tool_result(
        session: Session,
        chat_id: str,
        client_id: int,
        tool_call_id: str,
        result_content: str,
    ) -> bool:
        """
        Atualizar mensagem de external tool no chat principal.
        Para external tools (scraping, asset, vision):
        - Busca a mensagem ORIGINAL com UUID = tool_call_id
        - SUBSTITUI seu content pelo resultado (ao invés de criar nova mensagem)

        Em produção: atualiza local + enfileira para cloud

        IMPORTANTE: NÃO faz commit - o caller deve fazer commit

        Args:
            session: Sessão SQL
            chat_id: ID do chat principal
            client_id: ID do cliente
            tool_call_id: UUID da mensagem original (para encontrar e atualizar)
            result_content: Conteúdo do resultado (JSON string)

        Returns:
            True se atualizado com sucesso, False caso contrário
        """
        try:
            # Buscar a mensagem original com o UUID da tool call
            existing_msg = (
                session.query(Message)
                .filter(Message.message_id == tool_call_id, Message.chat_id == chat_id)
                .first()
            )

            if existing_msg:
                # Atualizar o conteúdo da mensagem existente
                existing_msg.content = result_content
                existing_msg.updated_at = datetime.utcnow()
                debug(
                    f"[Sync] External tool result updated in main chat: {tool_call_id}"
                )

                return True
            else:
                # Se mensagem original não encontrada, criar nova como fallback
                debug(
                    f"[Sync] Original external tool message not found ({tool_call_id}), creating new message"
                )
                message_data = {
                    "message_id": tool_call_id,
                    "chat_id": chat_id,
                    "message_type": "tool",
                    "content": result_content,
                    "model": "external-tool",
                }
                msg = Message(**message_data)
                session.add(msg)

                return True

        except Exception as e:
            error(f"[Sync] Erro ao atualizar external tool result: {e}")
            return False

    # ==================== FEEDBACK OPERATIONS (SQL) ====================

    @staticmethod
    def create_feedback(feedback_id: str, user_id: str, content: str) -> bool:
        """
        Criar novo feedback no banco de dados.

        Args:
            feedback_id: ID único do feedback
            user_id: ID do usuário que enviou o feedback
            content: Conteúdo do feedback

        Returns:
            True se sucesso, False se erro
        """
        try:
            from App.Core.Crunch.TablesSQL.Database import database
            from sqlalchemy import text
            from datetime import datetime

            query = """
            INSERT INTO feedbacks (feedback_id, user_id, content, created_at, updated_at)
            VALUES (:feedback_id, :user_id, :content, :created_at, :updated_at)
            """

            params = {
                "feedback_id": feedback_id,
                "user_id": user_id,
                "content": content,
                "created_at": datetime.utcnow().isoformat(),
                "updated_at": datetime.utcnow().isoformat(),
            }

            with database.engine.connect() as connection:
                connection.execute(text(query), params)
                connection.commit()

            info(
                f"[FEEDBACK] Feedback criado com sucesso - feedback_id: {feedback_id}, user_id: {user_id}"
            )
            return True

        except Exception as e:
            error(f"[FEEDBACK] Erro ao criar feedback: {e}")
            return False

    @staticmethod
    def create_research_answer(
        answer_id: str,
        user_id: str,
        question: str,
        options: Optional[str],
        answer: str,
        answer_type: str,
    ) -> bool:
        """
        Registrar resposta de pesquisa de satisfação/solução no banco de dados.
        """
        try:
            from App.Core.Crunch.TablesSQL.Database import database
            from sqlalchemy import text
            from datetime import datetime

            query = """
            INSERT INTO solution_research_answers (answer_id, user_id, question, options, answer, answer_type, created_at)
            VALUES (:answer_id, :user_id, :question, :options, :answer, :answer_type, :created_at)
            """

            params = {
                "answer_id": answer_id,
                "user_id": user_id,
                "question": question,
                "options": options,
                "answer": answer,
                "answer_type": answer_type,
                "created_at": datetime.utcnow().isoformat(),
            }

            with database.engine.connect() as connection:
                connection.execute(text(query), params)
                connection.commit()

            info(
                f"[RESEARCH] Resposta registrada com sucesso - answer_id: {answer_id}, user_id: {user_id}"
            )
            return True

        except Exception as e:
            error(f"[RESEARCH] Erro ao registrar resposta: {e}")
            return False

    # ==================== JOB OPERATIONS (SQL) ====================

    @staticmethod
    def create_job(
        session: Session, job_id: str, chat_id: str, user_id: Optional[str] = None
    ) -> bool:
        """Criar um novo job de processamento no banco de dados usando SQL puro."""
        try:
            query = text(
                """
                INSERT INTO jobs (job_id, chat_id, user_id, status, created_at)
                VALUES (:job_id, :chat_id, :user_id, 'running', :created_at)
            """
            )
            session.execute(
                query,
                {
                    "job_id": job_id,
                    "chat_id": chat_id,
                    "user_id": user_id,
                    "created_at": datetime.utcnow(),
                },
            )
            session.commit()
            debug(f"[DB] Job {job_id} criado para o chat {chat_id}")
            return True
        except Exception as e:
            session.rollback()
            error(f"[DB] Erro ao criar job {job_id}: {e}")
            return False

    @staticmethod
    def get_job(session: Session, job_id: str) -> Optional[Dict]:
        """Obter um job pelo seu ID usando SQL puro."""
        try:
            query = text("SELECT * FROM jobs WHERE job_id = :job_id")
            result = session.execute(query, {"job_id": job_id}).first()
            if result:
                # Converter Row para dict
                return dict(result._mapping)
            return None
        except Exception as e:
            error(f"[DB] Erro ao buscar job {job_id}: {e}")
            return None

    @staticmethod
    def update_job_status(
        session: Session,
        job_id: str,
        status: str,
        response: str = None,
        error_message: str = None,
    ) -> bool:
        """Atualiza o status de um job usando SQL puro."""
        try:
            params = {"job_id": job_id, "status": status}
            update_fields = ["status = :status"]

            if response is not None:
                update_fields.append("response = :response")
                params["response"] = response

            if error_message is not None:
                update_fields.append("error_message = :error_message")
                params["error_message"] = error_message

            if status in ["completed", "error", "cancelled"]:
                update_fields.append("finished_at = :finished_at")
                params["finished_at"] = datetime.utcnow()

            query = text(
                f"UPDATE jobs SET {', '.join(update_fields)} WHERE job_id = :job_id"
            )
            session.execute(query, params)
            session.commit()
            debug(f"[DB] Job {job_id} atualizado para status {status}")
            return True
        except Exception as e:
            session.rollback()
            error(f"[DB] Erro ao atualizar job {job_id}: {e}")
            return False

    @staticmethod
    def find_latest_active_job(session: Session, chat_id: str) -> Optional[Dict]:
        """Busca o job mais recente que não esteja finalizado para um chat usando SQL puro."""
        try:
            query = text(
                """
                SELECT * FROM jobs
                WHERE chat_id = :chat_id AND finished_at IS NULL
                ORDER BY created_at DESC LIMIT 1
            """
            )
            result = session.execute(query, {"chat_id": chat_id}).first()
            if result:
                return dict(result._mapping)
            return None
        except Exception as e:
            error(f"[DB] Erro ao buscar latest active job para {chat_id}: {e}")
            return None

    # ==================== BILLING & SUBSCRIPTION OPERATIONS ====================

    @staticmethod
    def get_subscription_by_id(subscription_id: str) -> Optional[Dict]:
        """Busca uma subscrição pelo seu ID (UUID ou Stripe ID)."""
        return DatabaseManager.fetch_one(
            "SELECT * FROM billing_subscriptions WHERE subscription_id = :sid OR stripe_subscription_id = :sid",
            {"sid": subscription_id},
        )

    @staticmethod
    def get_or_create_card_from_stripe(
        user_id: str, payment_method_id: str, card_details: Dict = None
    ) -> str:
        """
        Busca ou cria um cartão a partir de um PaymentMethod do Stripe.
        Criptografa o payment_method_id no campo pagarme_card_id_encrypted.
        """
        pm_hash = DBCryptographyManager.hash_deterministic(payment_method_id)

        # 1. Tentar encontrar pelo hash
        row = DatabaseManager.fetch_one(
            "SELECT card_id FROM cards WHERE user_id = :uid AND payment_method_hash = :hash",
            {"uid": user_id, "hash": pm_hash},
        )

        if row:
            return row["card_id"]

        # 2. Se não existir, criar
        card_id = str(uuid_lib.uuid4())
        card_data = {
            "card_id": card_id,
            "user_id": user_id,
            "pagarme_card_id": payment_method_id,  # Será criptografado pelo encrypt_row_for_insert
            "payment_method_hash": pm_hash,
            "last_4": card_details.get("last_4", "0000") if card_details else "0000",
            "brand": (
                card_details.get("brand", "unknown") if card_details else "unknown"
            ),
            "holder_name": (
                card_details.get("holder_name", "Cardholder")
                if card_details
                else "Cardholder"
            ),
            "exp_month": card_details.get("exp_month", 1) if card_details else 1,
            "exp_year": card_details.get("exp_year", 2030) if card_details else 2030,
            "status": "valid",
        }

        # Criptografar
        encrypted_data = DatabaseManager.encrypt_params_for_insert("cards", card_data)

        DatabaseManager.execute_query(
            """
            INSERT INTO cards (
                card_id, user_id, pagarme_card_id_encrypted, payment_method_hash,
                last_4, brand, holder_name, exp_month, exp_year, status
            ) VALUES (
                :card_id, :user_id, :pagarme_card_id, :payment_method_hash,
                :last_4, :brand, :holder_name, :exp_month, :exp_year, :status
            )
            """,
            encrypted_data,
        )

        return card_id

    @staticmethod
    def create_subscription_record(sub_data: Dict) -> bool:
        """Cria um registro inicial de subscrição (geralmente via Webhook)."""
        required = [
            "subscription_id",
            "client_id",
            "plan_id",
            "card_id",
            "status",
            "billing_cycle",
        ]
        for field in required:
            if field not in sub_data:
                error(f"[DB] Falha ao criar subscrição: campo '{field}' ausente")
                return False

        from datetime import timedelta

        now_dt = datetime.utcnow()

        # Calcular próxima cobrança baseada no ciclo
        if sub_data["billing_cycle"] == "annual":
            next_charge = now_dt + timedelta(days=365)
        else:
            next_charge = now_dt + timedelta(days=30)

        params = {
            "sid": sub_data["subscription_id"],
            "cid": sub_data["client_id"],
            "pid": sub_data["plan_id"],
            "card_id": sub_data["card_id"],
            "status": sub_data["status"],
            "cycle": sub_data["billing_cycle"],
            "price_type": sub_data.get("price_type", "early_adopter"),
            "auto_renew": sub_data.get("auto_renew", 1),
            "stripe_sub_id": sub_data.get("stripe_subscription_id"),
            "stripe_cus_id": sub_data.get("stripe_customer_id"),
            "scheduled": next_charge.isoformat(),
            "renewal": next_charge.isoformat(),
            "now": now_dt.isoformat(),
        }

        try:
            DatabaseManager.execute_query(
                """
                INSERT INTO billing_subscriptions (
                    subscription_id, client_id, plan_id, card_id, status,
                    billing_cycle, price_type, auto_renew,
                    stripe_subscription_id, stripe_customer_id,
                    charge_scheduled_at, renewal_date, updated_at
                ) VALUES (
                    :sid, :cid, :pid, :card_id, :status,
                    :cycle, :price_type, :auto_renew,
                    :stripe_sub_id, :stripe_cus_id,
                    :scheduled, :renewal, :now
                )
                """,
                params,
            )
            return True
        except Exception as e:
            error(f"[DB] Erro ao criar subscrição via DBManager: {e}")
            return False
