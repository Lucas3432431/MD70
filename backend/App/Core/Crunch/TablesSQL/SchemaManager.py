"""
Gerenciador de schema do banco de dados SQL.
Responsável por criar tabelas, triggers, índices e dados iniciais.
"""

from sqlalchemy import text
from typing import List

from App.Core.Crunch.TablesSQL.Database import database
from App.Core.Settings import load_config
from App.Core.Logs import info, warning, error, debug


class SchemaManager:
    """
    Gerenciador de schema do banco de dados.
    Responsável por criar tabelas, triggers, índices e dados mock.
    Suporta sufixo de ambiente (dev_/prod_) para cloud.
    """

    def __init__(self):
        self.engine = database.engine
        self.errors: List[str] = []
        self.config = load_config()
        self.tables_created = 0
        self.indexes_created = 0

    def _get_db_type(self) -> str:
        """Detectar tipo de banco (cloud-rest, cloud-tcp, local, sqlite-fallback)."""
        return database.get_db_type()

    def _get_table_prefix(self) -> str:
        """Retornar prefixo de tabela baseado em ambiente (dev_ ou prod_)."""
        dev_env = self.config.get("dev_env", False)

        # Usar prefixo apenas se for cloud (REST ou TCP)
        if database.is_rest_api() or (
            database.is_cloud() and database.get_db_env().startswith("cloud-")
        ):
            return "dev_" if dev_env else "prod_"
        return ""

    def _table_name(self, name: str) -> str:
        """Adicionar prefixo de ambiente ao nome da tabela."""
        return f"{self._get_table_prefix()}{name}"

    def _get_environment_name(self) -> str:
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

    def _get_schema_info(self) -> str:
        """Retornar informações do schema (para cloud, mostra dev_schema ou prod_schema)."""
        db_env = database.get_db_env()
        schema = database.get_schema()

        # Para cloud, mostrar qual schema está usando
        if db_env.startswith("cloud-"):
            return f"{self._get_environment_name()} (schema: {schema})"
        else:
            return self._get_environment_name()

    def _column_exists(self, table: str, column: str) -> bool:
        """Verifica se uma coluna já existe na tabela (SQLite PRAGMA)."""
        try:
            with self.engine.connect() as conn:
                rows = conn.execute(text(f"PRAGMA table_info({table})")).fetchall()
                return any(row[1] == column for row in rows)
        except Exception:
            return False

    def _backfill_product_cpu(self) -> None:
        """Replay WAC from transaction history for any products_stock rows with cost_per_unit = 0."""
        try:
            with self.engine.connect() as conn:
                rows = conn.execute(text(
                    "SELECT client_id, product_id FROM products_stock WHERE cost_per_unit = 0 OR cost_per_unit IS NULL"
                )).fetchall()
                if not rows:
                    return
                for cid, pid in rows:
                    txns = conn.execute(text(
                        "SELECT type, quantity, total_cost FROM products_stock_transactions"
                        " WHERE client_id = :cid AND product_id = :pid AND type IN ('compra','venda','perda')"
                        " ORDER BY created_at ASC"
                    ), {"cid": cid, "pid": pid}).fetchall()
                    qty = 0.0
                    cpu = 0.0
                    for typ, q, cost in txns:
                        q = float(q or 0)
                        if typ == "compra" and cost and float(cost) > 0:
                            cost = float(cost)
                            new_qty = qty + q
                            cpu = (cpu * qty + cost) / new_qty if new_qty > 0 else cpu
                            qty = new_qty
                        elif typ == "venda":
                            qty = max(0.0, qty - q)
                        elif typ == "perda":
                            qty = max(0.0, qty - q)
                    if cpu > 0:
                        conn.execute(text(
                            "UPDATE products_stock SET cost_per_unit = :cpu"
                            " WHERE client_id = :cid AND product_id = :pid"
                        ), {"cpu": cpu, "cid": cid, "pid": pid})
                conn.commit()
        except Exception as e:
            warning(f"[SCHEMA] backfill product cpu: {e}")

    def _add_column_if_missing(
        self, table: str, column: str, definition: str, description: str = ""
    ) -> bool:
        """Executa ALTER TABLE ADD COLUMN somente se a coluna ainda não existir."""
        if self._column_exists(table, column):
            return True
        return self.run_sql(
            f"ALTER TABLE {table} ADD COLUMN {column} {definition};",
            description or f"Migration: add {column} to {table}",
            fail_silently=True,
        )

    def run_sql(
        self, sql: str, description: str = "", fail_silently: bool = False
    ) -> bool:
        """
        Executar SQL com tratamento de erro.
        Conta automaticamente CREATE TABLE e CREATE INDEX para logging.

        Args:
            sql: Comando SQL a executar
            description: Descrição da operação para logging
            fail_silently: Se True, não adiciona erro à lista (para migrations opcionais)

        Returns:
            True se sucesso, False se erro
        """
        try:
            with self.engine.connect() as connection:
                connection.execute(text(sql))
                connection.commit()

            # Contar tabelas e indexes criados
            sql_upper = sql.upper()
            if "CREATE TABLE" in sql_upper:
                self.tables_created += 1
            elif "CREATE INDEX" in sql_upper:
                self.indexes_created += 1

            return True
        except Exception as e:
            error_msg = f"{description}: {str(e)}" if description else str(e)

            # Se fail_silently=True, apenas log em debug, não adiciona à lista de erros
            if fail_silently:
                debug(f"SQL (non-critical): {error_msg}")
            else:
                self.errors.append(error_msg)
                warning(f"SQL Error: {error_msg}")

            return False

    def create_tables(self):
        """Criar todas as tabelas do banco de dados."""

        # Se usando Supabase REST, apenas retornar (schema já existe no cloud)
        if database.is_rest_api():
            return  # Schema já foi criado manualmente no Supabase

        # ============================================================================
        # CONFIGURAÇÃO - CARREGADOR DE CONFIG (apenas para local/postgresql)
        # ============================================================================

        config = load_config()
        reset_local_db = config.get("reset_local_db", False)

        if reset_local_db:
            info("[SCHEMA] reset_local_db is TRUE. Dropping all tables...")
            self.drop_tables()

        # ============================================================================
        # SCHEMA - CRIAR SCHEMA SE USANDO POSTGRESQL DIRETO
        # ============================================================================

        if database.get_db_env() == "cloud-tcp":
            # PostgreSQL direto
            if (
                hasattr(database.engine, "dialect")
                and database.engine.dialect.name == "postgresql"
            ):
                schema = database.get_schema()
                self.run_sql(
                    f"CREATE SCHEMA IF NOT EXISTS {schema};", f"Schema: Create {schema}"
                )
                self.run_sql(
                    f"SET search_path TO {schema};",
                    f"Schema: Set search_path to {schema}",
                )

        # ============================================================================
        # 👥 TABELAS DE CLIENTES E AUTENTICAÇÃO
        # ============================================================================

        # Tabela de planos disponíveis (referência)
        self.run_sql(
            """
            CREATE TABLE IF NOT EXISTS plans (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                plan_id TEXT UNIQUE NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                name TEXT NOT NULL,
                description TEXT,
                message TEXT,
                cumulative_credits REAL,
                non_cumulative_credits REAL,
                users_limit INTEGER,
                credits_reset_in INTEGER,
                cumulative_resets_in INTEGER,
                non_cumulative_resets_in INTEGER,
                active BOOLEAN DEFAULT 1,
                sell BOOLEAN DEFAULT 0,
                billing_type TEXT DEFAULT 'plan' CHECK(billing_type IN ('plan', 'extra')),
                plan_type TEXT NOT NULL,
                test_id TEXT
            );
        """,
            "Table: plans",
        )

        # Tabela do plano ativo do cliente
        self.run_sql(
            """
            CREATE TABLE IF NOT EXISTS clients (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                client_id TEXT UNIQUE NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                plan_id TEXT,
                started_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                finishes_at DATETIME,
                users_available INTEGER NOT NULL DEFAULT 1,
                FOREIGN KEY (plan_id) REFERENCES plans (plan_id) ON DELETE SET NULL
            );
        """,
            "Table: clients",
        )

        self.run_sql(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT UNIQUE NOT NULL,
                client_id TEXT NOT NULL,
                email TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL,
                full_name TEXT NOT NULL DEFAULT 'new_user',
                whatsapp TEXT,
                instagram TEXT,
                telegram TEXT,
                two_factor_enabled BOOLEAN DEFAULT 0,
                two_factor_secret TEXT,
                type TEXT CHECK(type IN ('trial', 'login')) DEFAULT 'login',
                ip_address TEXT,
                fingerprint_id TEXT,
                credits REAL DEFAULT 0,
                last_reset TEXT CHECK(last_reset IN ('cumulative', 'non_cumulative')),
                cumulative_resets_at DATETIME,
                non_cumulative_resets_at DATETIME,
                cookies_accepted BOOLEAN DEFAULT 0,
                cookies_accepted_at DATETIME,
                terms_accepted BOOLEAN DEFAULT 0,
                terms_accepted_at DATETIME,
                privacy_accepted BOOLEAN DEFAULT 0,
                privacy_accepted_at DATETIME,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                current_session_usage REAL DEFAULT 0,
                current_session_starts_at DATETIME,
                current_week_usage REAL DEFAULT 0,
                current_week_starts_at DATETIME,
                FOREIGN KEY (client_id) REFERENCES clients (client_id) ON DELETE CASCADE
            );
        """,
            "Table: users",
        )

        self.run_sql(
            """
            CREATE TABLE IF NOT EXISTS access_tokens (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                token_id TEXT UNIQUE NOT NULL,
                user_id INTEGER NOT NULL,
                token_hash TEXT NOT NULL,
                type TEXT CHECK(type IN ('trial', 'login')) DEFAULT 'login',
                expires_at DATETIME NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                revoked_at DATETIME DEFAULT NULL,
                FOREIGN KEY (user_id) REFERENCES users (user_id) ON DELETE CASCADE
            );
        """,
            "Table: access_tokens",
        )

        self.run_sql(
            """
            CREATE TABLE IF NOT EXISTS refresh_tokens (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                token_id TEXT UNIQUE NOT NULL,
                user_id INTEGER NOT NULL,
                token_hash TEXT NOT NULL,
                type TEXT CHECK(type IN ('trial', 'login')) DEFAULT 'login',
                expires_at DATETIME NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                revoked_at DATETIME DEFAULT NULL,
                FOREIGN KEY (user_id) REFERENCES users (user_id) ON DELETE CASCADE
            );
        """,
            "Table: refresh_tokens",
        )

        self.run_sql(
            """
            CREATE TABLE IF NOT EXISTS oauth_tokens (
                token_id INTEGER PRIMARY KEY AUTOINCREMENT,
                service_name TEXT NOT NULL UNIQUE,
                access_token TEXT,
                refresh_token TEXT NOT NULL,
                token_uri TEXT NOT NULL,
                client_id TEXT NOT NULL,
                client_secret TEXT NOT NULL,
                scopes TEXT NOT NULL,
                expires_at DATETIME,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );
        """,
            "Table: oauth_tokens",
        )

        # ============================================================================
        # 💬 TABELAS DE CHAT E MENSAGENS (SIMPLIFICADAS)
        # ============================================================================

        self.run_sql(
            """
            CREATE TABLE IF NOT EXISTS chats (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id TEXT UNIQUE NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                user_id TEXT,
                chat_name TEXT,
                status TEXT DEFAULT 'active',
                chat_cover TEXT,
                FOREIGN KEY (user_id) REFERENCES users (user_id) ON DELETE CASCADE
            );
        """,
            "Table: chats",
        )

        # ── Omni-channel & Agent Tables ───────────────────────────────────────

        self.run_sql(
            """
            CREATE TABLE IF NOT EXISTS agent_chat (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id TEXT UNIQUE NOT NULL,
                user_id TEXT NOT NULL,
                provider TEXT, -- 'whatsapp', 'telegram', 'instagram', 'gmail'
                external_id TEXT, -- ID no canal externo
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (user_id) ON DELETE CASCADE
            );
        """,
            "Table: agent_chat",
        )

        self.run_sql(
            """
            CREATE TABLE IF NOT EXISTS agent_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                message_id TEXT UNIQUE NOT NULL,
                chat_id TEXT NOT NULL,
                sender TEXT NOT NULL, -- 'user' or 'agent'
                content TEXT NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (chat_id) REFERENCES agent_chat (chat_id) ON DELETE CASCADE
            );
        """,
            "Table: agent_messages",
        )

        self.run_sql(
            """
            CREATE TABLE IF NOT EXISTS agent_isolated_chat (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id TEXT UNIQUE NOT NULL,
                user_id TEXT NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (user_id) ON DELETE CASCADE
            );
        """,
            "Table: agent_isolated_chat",
        )

        self.run_sql(
            """
            CREATE TABLE IF NOT EXISTS agent_isolated_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                message_id TEXT UNIQUE NOT NULL,
                chat_id TEXT NOT NULL,
                sender TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (chat_id) REFERENCES agent_isolated_chat (chat_id) ON DELETE CASCADE
            );
        """,
            "Table: agent_isolated_messages",
        )

        self.run_sql(
            """
            CREATE TABLE IF NOT EXISTS telegram_link_codes (
                code TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                expires_at DATETIME NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (user_id) ON DELETE CASCADE
            );
        """,
            "Table: telegram_link_codes",
        )

        self.run_sql(
            """
            CREATE TABLE IF NOT EXISTS webhook_secrets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                web_secret_id TEXT UNIQUE NOT NULL,
                client_id TEXT NOT NULL,
                provider TEXT NOT NULL,
                webhook_secret TEXT UNIQUE NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending', 'connected', 'lost')),
                prompt TEXT,
                autonomy_level INTEGER NOT NULL DEFAULT 4 CHECK(autonomy_level IN (1, 2, 3, 4)),
                tools TEXT NOT NULL DEFAULT '[]',
                last_received_at DATETIME,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (client_id) REFERENCES clients (client_id) ON DELETE CASCADE
            );
            -- status: 'pending' (gerado, não confirmado), 'connected' (recebeu chamada), 'lost' (falha ou inativo)
            -- autonomy_level: 1=full-auto, 2=auto c/ log, 3=aprova ações destrutivas, 4=aprova tudo
            -- tools: JSON array de integration IDs disponíveis para este webhook
        """,
            "Table: webhook_secrets",
        )

        self.run_sql(
            """
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                message_id TEXT UNIQUE NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                chat_id TEXT NOT NULL,
                message_type TEXT NOT NULL DEFAULT 'user',
                content TEXT NOT NULL,
                tool TEXT,
                fk_tool_id TEXT,
                feedback TEXT,
                model TEXT,
                attachment_type TEXT,
                attachment_id TEXT,
                FOREIGN KEY (chat_id) REFERENCES chats (chat_id) ON DELETE CASCADE
            );
        """,
            "Table: messages",
        )

        # ============================================================================
        # 🤖 TABELAS DE CHAT ISOLADO POR AGENTE
        # ============================================================================

        self.run_sql(
            """
            CREATE TABLE IF NOT EXISTS isolated_chat (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id TEXT NOT NULL UNIQUE,
                agent_id TEXT NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (chat_id) REFERENCES chats (chat_id) ON DELETE CASCADE
            );
        """,
            "Table: isolated_chat",
        )

        self.run_sql(
            """
            CREATE TABLE IF NOT EXISTS isolated_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                isolated_chat_id TEXT NOT NULL,
                isolated_message_id TEXT NOT NULL UNIQUE,
                tool_call_id TEXT,
                tool_called TEXT,
                tool_call_type TEXT CHECK(tool_call_type IN ('input', 'output')),
                fk_tool_id TEXT,
                agent_id TEXT NOT NULL,
                agent TEXT NOT NULL,
                role TEXT NOT NULL CHECK(role IN ('assistant', 'user', 'system')),
                content TEXT NOT NULL,
                input_tokens INTEGER DEFAULT 0,
                output_tokens INTEGER DEFAULT 0,
                type TEXT NOT NULL DEFAULT 'message' CHECK(type IN ('message', 'tool_call')),
                context_window BOOLEAN DEFAULT 1,
                provider_type TEXT CHECK(provider_type IN ('main', 'fallback')) DEFAULT 'main',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (isolated_chat_id) REFERENCES isolated_chat (chat_id) ON DELETE CASCADE
            );
        """,
            "Table: isolated_messages",
        )

        # ============================================================================
        # 📊 TABELAS DE USO E CRÉDITOS
        # ============================================================================

        # Tabela de logs de créditos (monitoramento de distribuição)
        self.run_sql(
            """
            CREATE TABLE IF NOT EXISTS credits_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                credits_logs_id TEXT UNIQUE NOT NULL,
                user_id TEXT NOT NULL,
                credits_added REAL NOT NULL DEFAULT 0,
                credit_type TEXT NOT NULL CHECK(credit_type IN ('cumulative', 'non_cumulative')),
                credits_charged REAL DEFAULT 0.0,
                is_signup_setup BOOLEAN DEFAULT 0,
                reason TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                operation_type TEXT,
                value REAL,
                isolated_message_id TEXT REFERENCES isolated_messages(isolated_message_id) ON DELETE SET NULL,
                isolated_chat_id TEXT REFERENCES isolated_chat(chat_id) ON DELETE SET NULL,
                session_usage_pct REAL,
                week_usage_pct REAL,
                FOREIGN KEY (user_id) REFERENCES users (user_id) ON DELETE CASCADE
            );
        """,
            "Table: credits_logs",
        )

        # Tabela para armazenar contextos comprimidos
        self.run_sql(
            """
            CREATE TABLE IF NOT EXISTS context_window (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                isolated_chat_id TEXT NOT NULL,
                cut_message_isolated_message_id TEXT NOT NULL,
                context_generated TEXT NOT NULL,
                agent_id TEXT NOT NULL,
                agent TEXT NOT NULL,
                tokens INTEGER DEFAULT 0,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (isolated_chat_id) REFERENCES isolated_chat (chat_id) ON DELETE CASCADE
            );
        """,
            "Table: context_window",
        )

        # ============================================================================
        # 📄 TABELAS DE ARQUIVOS
        # ============================================================================

        # REMOVIDO: Tabela 'files' - usando 'assets' em seu lugar para assets gerados

        # REMOVIDO: message_files - tabela intermediária para files
        # Depende de 'files' que foi removido em favor de 'assets'
        # Se necessário reconstruir, criar message_assets

        self.run_sql(
            """
            CREATE TABLE IF NOT EXISTS jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id TEXT UNIQUE NOT NULL,
                chat_id TEXT NOT NULL,
                user_id TEXT,
                status TEXT DEFAULT 'running' CHECK(status IN ('running', 'waiting', 'completed', 'error', 'cancelled')),
                response TEXT,
                error_message TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                finished_at DATETIME,
                agent_save_completed BOOLEAN DEFAULT 0,
                FOREIGN KEY (chat_id) REFERENCES chats (chat_id) ON DELETE CASCADE,
                FOREIGN KEY (user_id) REFERENCES users (user_id) ON DELETE SET NULL
            );
        """,
            "Table: jobs",
        )

        self.run_sql(
            """
            CREATE TABLE IF NOT EXISTS attachments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                attachment_id TEXT UNIQUE NOT NULL,
                user_id TEXT NOT NULL,
                chat_id TEXT,
                message_id TEXT,
                file_name TEXT,
                extension VARCHAR(50),
                attachment_type TEXT DEFAULT 'file',
                template_id TEXT,
                file_type TEXT,
                file_size INTEGER,
                storage_path TEXT,
                storage_env TEXT DEFAULT 'local',
                is_temp BOOLEAN DEFAULT 1,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                uploaded_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                deleted_at DATETIME,
                FOREIGN KEY (user_id) REFERENCES users (user_id) ON DELETE CASCADE,
                FOREIGN KEY (chat_id) REFERENCES chats (chat_id) ON DELETE CASCADE,
                FOREIGN KEY (message_id) REFERENCES messages (message_id) ON DELETE CASCADE
            );
        """,
            "Table: attachments",
        )

        self.run_sql(
            """
            CREATE TABLE IF NOT EXISTS table_files (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                table_file_id TEXT UNIQUE NOT NULL,
                attachment_id TEXT NOT NULL,
                content TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (attachment_id) REFERENCES attachments (attachment_id) ON DELETE CASCADE
            );
        """,
            "Table: table_files",
        )

        self.run_sql(
            """
            CREATE TABLE IF NOT EXISTS text_files (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                text_file_id TEXT UNIQUE NOT NULL,
                attachment_id TEXT NOT NULL,
                content TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (attachment_id) REFERENCES attachments (attachment_id) ON DELETE CASCADE
            );
        """,
            "Table: text_files",
        )

        self.run_sql(
            """
            CREATE TABLE IF NOT EXISTS assets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                asset_id TEXT UNIQUE NOT NULL,
                user_id TEXT NOT NULL,
                client_id TEXT,
                chat_id TEXT,
                type TEXT NOT NULL DEFAULT 'img',
                content_name TEXT,
                storage_path TEXT,
                storage_env TEXT DEFAULT 'local',
                provider TEXT,
                provider_type TEXT CHECK(provider_type IN ('main', 'fallback')) DEFAULT 'main',
                title TEXT,
                caption TEXT,
                ratio TEXT,
                version INTEGER DEFAULT 1,
                variation_id TEXT,
                approval_status TEXT DEFAULT 'waitingJudge' CHECK(approval_status IN ('waitingJudge','approved','discarded','improve')),
                feedback TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (user_id) ON DELETE CASCADE,
                FOREIGN KEY (client_id) REFERENCES clients (client_id) ON DELETE CASCADE,
                FOREIGN KEY (chat_id) REFERENCES chats (chat_id) ON DELETE CASCADE
            );
        """,
            "Table: assets",
        )

        self.run_sql(
            """
            CREATE TABLE IF NOT EXISTS message_feedbacks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                feedback_id TEXT UNIQUE NOT NULL,
                chat_id TEXT NOT NULL,
                message_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                feedback_type TEXT NOT NULL CHECK(feedback_type IN ('like', 'dislike')),
                content TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (chat_id) REFERENCES chats (chat_id) ON DELETE CASCADE,
                FOREIGN KEY (message_id) REFERENCES messages (message_id) ON DELETE CASCADE,
                FOREIGN KEY (user_id) REFERENCES users (user_id) ON DELETE CASCADE,
                UNIQUE(message_id, feedback_type)
            );
        """,
            "Table: message_feedbacks",
        )

        self.run_sql(
            """
            CREATE TABLE IF NOT EXISTS cellphone_validations_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                cellphone_validation_id TEXT UNIQUE NOT NULL,
                user_id INTEGER,
                phone TEXT NOT NULL,
                is_valid BOOLEAN NOT NULL,
                country TEXT,
                country_code TEXT,
                type TEXT,
                carrier TEXT,
                timezone TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (user_id) ON DELETE SET NULL
            );
        """,
            "Table: cellphone_validations_logs",
        )

        self.run_sql(
            """
            CREATE TABLE IF NOT EXISTS postal_code_validations_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                postal_code_validation_id TEXT UNIQUE NOT NULL,
                user_id INTEGER,
                postal_code TEXT NOT NULL,
                is_valid BOOLEAN NOT NULL,
                city TEXT,
                state TEXT,
                address TEXT,
                complemento TEXT,
                bairro TEXT,
                logradouro TEXT,
                estado TEXT,
                regiao TEXT,
                ibge TEXT,
                gia TEXT,
                ddd TEXT,
                siafi TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (user_id) ON DELETE SET NULL
            );
        """,
            "Table: postal_code_validations_logs",
        )

        # ============================================================================
        # 🔐 TABELAS DE AUTENTICAÇÃO E DISPOSITIVOS
        # ============================================================================

        self.run_sql(
            """
            CREATE TABLE IF NOT EXISTS devices (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                fingerprint_id TEXT UNIQUE NOT NULL,
                user_id TEXT NOT NULL,
                authorized BOOLEAN DEFAULT 0,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (user_id) ON DELETE CASCADE
            );
        """,
            "Table: devices",
        )

        self.run_sql(
            """
            CREATE TABLE IF NOT EXISTS auth_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                auth_id TEXT UNIQUE NOT NULL,
                user_id TEXT NOT NULL,
                fingerprint_id TEXT NOT NULL,
                fingerprint_components TEXT,
                login_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                logout_at DATETIME,
                is_successful BOOLEAN DEFAULT 1,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (user_id) ON DELETE CASCADE,
                FOREIGN KEY (fingerprint_id) REFERENCES devices (fingerprint_id) ON DELETE CASCADE
            );
        """,
            "Table: auth_logs",
        )

        # ============================================================================
        # 📄 TABELAS DE DOCUMENTOS E CONTEÚDO
        # ============================================================================

        self.run_sql(
            """
            CREATE TABLE IF NOT EXISTS documents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                document_id TEXT UNIQUE NOT NULL,
                chat_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                client_id TEXT,
                title VARCHAR(255) NOT NULL,
                content TEXT,
                extension VARCHAR(50),
                tool_type VARCHAR(100),
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (chat_id) REFERENCES chats (chat_id) ON DELETE CASCADE,
                FOREIGN KEY (user_id) REFERENCES users (user_id) ON DELETE CASCADE,
                FOREIGN KEY (client_id) REFERENCES clients (client_id) ON DELETE CASCADE
            );
        """,
            "Table: documents",
        )

        self.run_sql(
            """
            CREATE INDEX IF NOT EXISTS idx_documents_user_type ON documents(user_id, tool_type);
        """,
            "Index: documents(user_id, tool_type)",
        )

        self.run_sql(
            """
            CREATE INDEX IF NOT EXISTS idx_documents_client_type ON documents(client_id, tool_type);
        """,
            "Index: documents(client_id, tool_type)",
        )

        self.run_sql(
            """
            CREATE TABLE IF NOT EXISTS email_domains (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email_domain_id TEXT UNIQUE NOT NULL,
                email VARCHAR(255),
                domain VARCHAR(255),
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );
        """,
            "Table: email_domains",
        )

        self.run_sql(
            """
            CREATE TABLE IF NOT EXISTS emails (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email_id TEXT UNIQUE NOT NULL,
                event_type TEXT CHECK(event_type IN ('sent', 'received')),
                email_domain_id TEXT,
                email TEXT,
                content TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (email_domain_id) REFERENCES email_domains (email_domain_id) ON DELETE SET NULL
            );
        """,
            "Table: emails",
        )

        # 🔗 TABELA DE URLS TEMPORÁRIAS (screenshots, vision analysis e attachment tokens)
        self.run_sql(
            """
            CREATE TABLE IF NOT EXISTS temp_urls (
                token TEXT PRIMARY KEY,
                filepath TEXT,
                origin_url TEXT,
                expires_at REAL NOT NULL,
                attachment_id TEXT,
                user_id TEXT,
                used INTEGER DEFAULT 0,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );
        """,
            "Table: temp_urls",
        )

        # Índice para limpeza de tokens expirados
        self.run_sql(
            """
            CREATE INDEX IF NOT EXISTS idx_temp_urls_expires_at
            ON temp_urls(expires_at);
        """,
            "Index: temp_urls expires_at",
        )

        # ============================================================================
        # 🔗 TABELAS DE INTEGRAÇÕES MCP (Model Context Protocol)
        # ============================================================================

        self.run_sql(
            """
            CREATE TABLE IF NOT EXISTS integrations_mcp (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                integration_id TEXT UNIQUE NOT NULL,
                client_id TEXT NOT NULL,
                provider TEXT NOT NULL, -- ex: 'meta-ads'
                command TEXT NOT NULL,  -- ex: 'npx'
                args TEXT NOT NULL,     -- JSON string: ["-y", "meta-ads-mcp"]
                env_vars TEXT NOT NULL, -- JSON string: {"TOKEN": "..."}
                is_active BOOLEAN DEFAULT 1,
                token_valid BOOLEAN DEFAULT 1,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (client_id) REFERENCES clients (client_id) ON DELETE CASCADE,
                UNIQUE(client_id, provider)
            );
        """,
            "Table: integrations_mcp",
        )

        # ============================================================================
        # 🔗 TABELAS DE CAMPANHA E REFERRAL
        # ============================================================================

        self.run_sql(
            """
            CREATE TABLE IF NOT EXISTS campaigns (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                campaign_id TEXT UNIQUE NOT NULL,
                short_code TEXT UNIQUE NOT NULL,
                channel TEXT NOT NULL CHECK(channel IN ('shared_link', 'meta_ads', 'google_ads', 'email', 'organic', 'other')),
                name TEXT,
                owner_user_id TEXT REFERENCES users(user_id) ON DELETE SET NULL,
                is_active INTEGER DEFAULT 1,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                metadata TEXT
            );
        """,
            "Table: campaigns",
        )

        self.run_sql(
            """
            CREATE TABLE IF NOT EXISTS sharing_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sharing_log_id TEXT UNIQUE NOT NULL,
                user_id TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );
        """,
            "Table: sharing_logs",
        )

        self.run_sql(
            """
            CREATE TABLE IF NOT EXISTS referral_attributions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                attribution_id TEXT UNIQUE NOT NULL,
                referrer_user_id TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
                referred_user_id TEXT REFERENCES users(user_id) ON DELETE SET NULL,
                referred_fingerprint_id TEXT,
                campaign_short_code TEXT REFERENCES campaigns(short_code) ON DELETE SET NULL,
                status TEXT DEFAULT 'registered' CHECK(status IN ('registered', 'trialed', 'subscribed')),
                trial_credits_awarded_referrer INTEGER DEFAULT 0,
                subscription_credits_awarded_referrer INTEGER DEFAULT 0,
                trial_credits_awarded_referred INTEGER DEFAULT 0,
                subscription_bonus_awarded_referred INTEGER DEFAULT 0,
                ab_test_variant TEXT CHECK(ab_test_variant IN ('24h', '72h')),
                bonus_window_expires_at DATETIME,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                registered_at DATETIME,
                trialed_at DATETIME,
                subscribed_at DATETIME
            );
        """,
            "Table: referral_attributions",
        )

        self.run_sql(
            """
            CREATE TABLE IF NOT EXISTS invite_tokens (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                invite_id TEXT UNIQUE NOT NULL,
                short_code TEXT UNIQUE NOT NULL,
                referrer_user_id TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
                label TEXT,
                status TEXT DEFAULT 'pending' CHECK(status IN ('pending', 'registered', 'trialed', 'subscribed')),
                attribution_id TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                used_at DATETIME
            );
            """,
            "Table: invite_tokens",
        )

        # ============================================================================
        # ⏰ TABELAS DE TAREFAS AGENDADAS
        # ============================================================================

        self.run_sql(
            """
            CREATE TABLE IF NOT EXISTS scheduled_tasks (
                id TEXT PRIMARY KEY NOT NULL,
                user_id TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
                name TEXT NOT NULL,
                description TEXT,
                cron_expression TEXT NOT NULL,
                cron_label TEXT,
                prompt TEXT NOT NULL,
                integrations TEXT DEFAULT '[]',
                status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active', 'paused')),
                last_executed_at DATETIME,
                next_execution_at DATETIME,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );
            """,
            "Table: scheduled_tasks",
        )

        self.run_sql(
            "CREATE INDEX IF NOT EXISTS idx_scheduled_tasks_user ON scheduled_tasks (user_id);",
            "Index: idx_scheduled_tasks_user",
        )

        self.run_sql(
            """
            CREATE TABLE IF NOT EXISTS task_executions (
                id TEXT PRIMARY KEY NOT NULL,
                task_id TEXT NOT NULL REFERENCES scheduled_tasks(id) ON DELETE CASCADE,
                user_id TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
                chat_id TEXT,
                status TEXT NOT NULL DEFAULT 'running' CHECK(status IN ('running', 'completed', 'pending_review', 'approved', 'rejected', 'failed')),
                result_summary TEXT,
                started_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                finished_at DATETIME,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );
            """,
            "Table: task_executions",
        )

        self.run_sql(
            "CREATE INDEX IF NOT EXISTS idx_task_executions_task ON task_executions (task_id);",
            "Index: idx_task_executions_task",
        )

        self.run_sql(
            "CREATE INDEX IF NOT EXISTS idx_task_executions_user_status ON task_executions (user_id, status);",
            "Index: idx_task_executions_user_status",
        )

        self.run_sql(
            """
            CREATE TABLE IF NOT EXISTS trigger_executions (
                id TEXT PRIMARY KEY NOT NULL,
                web_secret_id TEXT NOT NULL REFERENCES webhook_secrets(web_secret_id) ON DELETE CASCADE,
                user_id TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
                chat_id TEXT,
                status TEXT NOT NULL DEFAULT 'running'
                    CHECK(status IN ('running', 'completed', 'pending_review', 'approved', 'rejected', 'failed')),
                result_summary TEXT,
                started_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                finished_at DATETIME,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );
            """,
            "Table: trigger_executions",
        )

        self.run_sql(
            "CREATE INDEX IF NOT EXISTS idx_trigger_exec_user ON trigger_executions (user_id);",
            "Index: idx_trigger_exec_user",
        )

        self.run_sql(
            """
            CREATE TABLE IF NOT EXISTS trigger_tool_approvals (
                id TEXT PRIMARY KEY NOT NULL,
                chat_id TEXT,
                job_id TEXT,
                tool_name TEXT NOT NULL,
                args_json TEXT,
                status TEXT NOT NULL DEFAULT 'pending'
                    CHECK(status IN ('pending', 'approved', 'rejected')),
                result_json TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );
            """,
            "Table: trigger_tool_approvals",
        )

        self.run_sql(
            "CREATE INDEX IF NOT EXISTS idx_tool_approvals_chat ON trigger_tool_approvals (chat_id);",
            "Index: idx_tool_approvals_chat",
        )
        self.run_sql(
            "CREATE INDEX IF NOT EXISTS idx_tool_approvals_job ON trigger_tool_approvals (job_id);",
            "Index: idx_tool_approvals_job",
        )

        self.run_sql(
            """
            CREATE TABLE IF NOT EXISTS custom_skills (
                id TEXT PRIMARY KEY NOT NULL,
                user_id TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
                name TEXT NOT NULL,
                description TEXT,
                content TEXT NOT NULL,
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );
            """,
            "Table: custom_skills",
        )

        self.run_sql(
            "CREATE INDEX IF NOT EXISTS idx_custom_skills_user ON custom_skills (user_id);",
            "Index: idx_custom_skills_user",
        )

        self.run_sql(
            """
            CREATE TABLE IF NOT EXISTS knowledge_sources (
                id TEXT PRIMARY KEY NOT NULL,
                user_id TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
                provider TEXT NOT NULL,
                name TEXT,
                config_json TEXT,
                last_synced_at DATETIME,
                status TEXT DEFAULT 'pending',
                error_message TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );
            """,
            "Table: knowledge_sources",
        )

        self.run_sql(
            "CREATE INDEX IF NOT EXISTS idx_ksources_user ON knowledge_sources (user_id);",
            "Index: idx_ksources_user",
        )

        self.run_sql(
            """
            CREATE TABLE IF NOT EXISTS knowledge_objects (
                id TEXT PRIMARY KEY NOT NULL,
                source_id TEXT NOT NULL REFERENCES knowledge_sources(id) ON DELETE CASCADE,
                user_id TEXT NOT NULL,
                external_id TEXT NOT NULL,
                file_name TEXT,
                file_path TEXT,
                file_type TEXT,
                source_url TEXT,
                last_modified_at DATETIME,
                last_indexed_at DATETIME,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );
            """,
            "Table: knowledge_objects",
        )

        self.run_sql(
            "CREATE INDEX IF NOT EXISTS idx_kobjects_source ON knowledge_objects (source_id);",
            "Index: idx_kobjects_source",
        )

        self.run_sql(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_kobjects_external ON knowledge_objects (source_id, external_id);",
            "Index: idx_kobjects_external",
        )

        self.run_sql(
            """
            CREATE TABLE IF NOT EXISTS knowledge_chunks (
                id TEXT PRIMARY KEY NOT NULL,
                object_id TEXT NOT NULL REFERENCES knowledge_objects(id) ON DELETE CASCADE,
                user_id TEXT NOT NULL,
                chunk_index INTEGER NOT NULL,
                content TEXT NOT NULL,
                embedding_json TEXT,
                vector_id TEXT,
                token_count INTEGER,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );
            """,
            "Table: knowledge_chunks",
        )

        self.run_sql(
            "CREATE INDEX IF NOT EXISTS idx_kchunks_object ON knowledge_chunks (object_id);",
            "Index: idx_kchunks_object",
        )

        self.run_sql(
            "CREATE INDEX IF NOT EXISTS idx_kchunks_user ON knowledge_chunks (user_id);",
            "Index: idx_kchunks_user",
        )

        # ============================================================================
        # 🏗️ MD70 — EMPREENDIMENTOS, PORTAL E CRM IMOBILIÁRIO
        # ============================================================================

        self.run_sql(
            """
            CREATE TABLE IF NOT EXISTS md70_developments (
                id TEXT PRIMARY KEY NOT NULL,
                name TEXT NOT NULL,
                city TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'Projeto'
                    CHECK(status IN (
                        'Oferecido / Interessado','Visita','Business Plan / Capital',
                        'Projeto','Proposta / Negociação','Construção / Reforma','Vendido'
                    )),
                progress INTEGER NOT NULL DEFAULT 0 CHECK(progress >= 0 AND progress <= 100),
                capital REAL NOT NULL DEFAULT 0,
                budget REAL NOT NULL DEFAULT 0,
                remaining REAL NOT NULL DEFAULT 0,
                forecast TEXT,
                image_url TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );
            """,
            "Table: md70_developments",
        )

        self.run_sql(
            """
            CREATE TABLE IF NOT EXISTS md70_budget_lines (
                id TEXT PRIMARY KEY NOT NULL,
                development_id TEXT NOT NULL REFERENCES md70_developments(id) ON DELETE CASCADE,
                category TEXT NOT NULL,
                item TEXT NOT NULL,
                planned REAL NOT NULL DEFAULT 0,
                realized REAL NOT NULL DEFAULT 0,
                committed REAL NOT NULL DEFAULT 0,
                remaining REAL NOT NULL DEFAULT 0,
                quantity REAL,
                unit TEXT,
                note TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );
            """,
            "Table: md70_budget_lines",
        )

        self.run_sql(
            "CREATE INDEX IF NOT EXISTS idx_md70_budget_lines_dev ON md70_budget_lines (development_id);",
            "Index: idx_md70_budget_lines_dev",
        )

        self.run_sql(
            """
            CREATE TABLE IF NOT EXISTS md70_suppliers (
                id TEXT PRIMARY KEY NOT NULL,
                name TEXT NOT NULL,
                cnpj TEXT,
                contact TEXT,
                phone TEXT,
                email TEXT,
                notes TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );
            """,
            "Table: md70_suppliers",
        )

        self.run_sql(
            """
            CREATE TABLE IF NOT EXISTS md70_purchases (
                id TEXT PRIMARY KEY NOT NULL,
                development_id TEXT NOT NULL REFERENCES md70_developments(id) ON DELETE CASCADE,
                budget_line_id TEXT REFERENCES md70_budget_lines(id) ON DELETE SET NULL,
                description TEXT NOT NULL,
                quantity REAL NOT NULL DEFAULT 1,
                unit TEXT NOT NULL DEFAULT 'un',
                estimate REAL NOT NULL DEFAULT 0,
                requester TEXT NOT NULL,
                date TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'Solicitado'
                    CHECK(status IN (
                        'Solicitado','Fornecedores Contatados','Orçamento 1','Orçamento 2',
                        'Orçamento 3','Aguardando entrega','Entregue','Cancelado'
                    )),
                selected_quote_id TEXT,
                approved_by TEXT,
                approved_at DATETIME,
                justification TEXT,
                paid_at DATETIME,
                note TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );
            """,
            "Table: md70_purchases",
        )

        self.run_sql(
            "CREATE INDEX IF NOT EXISTS idx_md70_purchases_dev ON md70_purchases (development_id);",
            "Index: idx_md70_purchases_dev",
        )

        self.run_sql(
            "CREATE INDEX IF NOT EXISTS idx_md70_purchases_status ON md70_purchases (status);",
            "Index: idx_md70_purchases_status",
        )

        self.run_sql(
            """
            CREATE TABLE IF NOT EXISTS md70_quotes (
                id TEXT PRIMARY KEY NOT NULL,
                purchase_id TEXT NOT NULL REFERENCES md70_purchases(id) ON DELETE CASCADE,
                supplier_id TEXT NOT NULL REFERENCES md70_suppliers(id) ON DELETE CASCADE,
                value REAL NOT NULL DEFAULT 0,
                shipping REAL NOT NULL DEFAULT 0,
                discount REAL NOT NULL DEFAULT 0,
                payment TEXT NOT NULL,
                delivery TEXT NOT NULL,
                validity TEXT NOT NULL,
                notes TEXT,
                attachment_url TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );
            """,
            "Table: md70_quotes",
        )

        self.run_sql(
            "CREATE INDEX IF NOT EXISTS idx_md70_quotes_purchase ON md70_quotes (purchase_id);",
            "Index: idx_md70_quotes_purchase",
        )

        self.run_sql(
            """
            CREATE TABLE IF NOT EXISTS md70_movements (
                id TEXT PRIMARY KEY NOT NULL,
                development_id TEXT NOT NULL REFERENCES md70_developments(id) ON DELETE CASCADE,
                purchase_id TEXT REFERENCES md70_purchases(id) ON DELETE SET NULL,
                date TEXT NOT NULL,
                description TEXT NOT NULL,
                category TEXT NOT NULL,
                direction TEXT NOT NULL CHECK(direction IN ('Entrada','Saída')),
                value REAL NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'Previsto'
                    CHECK(status IN ('Previsto','Comprometido','Realizado')),
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );
            """,
            "Table: md70_movements",
        )

        self.run_sql(
            "CREATE INDEX IF NOT EXISTS idx_md70_movements_dev ON md70_movements (development_id);",
            "Index: idx_md70_movements_dev",
        )

        self.run_sql(
            "CREATE INDEX IF NOT EXISTS idx_md70_movements_date ON md70_movements (date);",
            "Index: idx_md70_movements_date",
        )

        self.run_sql(
            """
            CREATE TABLE IF NOT EXISTS md70_documents (
                id TEXT PRIMARY KEY NOT NULL,
                movement_id TEXT NOT NULL REFERENCES md70_movements(id) ON DELETE CASCADE,
                url TEXT NOT NULL,
                label TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );
            """,
            "Table: md70_documents",
        )

        self.run_sql(
            "CREATE INDEX IF NOT EXISTS idx_md70_documents_movement ON md70_documents (movement_id);",
            "Index: idx_md70_documents_movement",
        )

        self.run_sql(
            """
            CREATE TABLE IF NOT EXISTS md70_leads (
                id TEXT PRIMARY KEY NOT NULL,
                name TEXT NOT NULL,
                email TEXT NOT NULL,
                phone TEXT,
                project_interest TEXT REFERENCES md70_developments(id) ON DELETE SET NULL,
                status TEXT NOT NULL DEFAULT 'Interesse'
                    CHECK(status IN (
                        'Interesse','Qualificado','Em negociação','Investidor ativo','Descartado'
                    )),
                source TEXT NOT NULL,
                value REAL,
                notes TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );
            """,
            "Table: md70_leads",
        )

        self.run_sql(
            "CREATE INDEX IF NOT EXISTS idx_md70_leads_status ON md70_leads (status);",
            "Index: idx_md70_leads_status",
        )

        self.run_sql(
            """
            CREATE TABLE IF NOT EXISTS md70_investors (
                id TEXT PRIMARY KEY NOT NULL,
                lead_id TEXT REFERENCES md70_leads(id) ON DELETE SET NULL,
                user_id TEXT REFERENCES users(user_id) ON DELETE SET NULL,
                name TEXT NOT NULL,
                email TEXT NOT NULL UNIQUE,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );
            """,
            "Table: md70_investors",
        )

        self.run_sql(
            """
            CREATE TABLE IF NOT EXISTS md70_investments (
                id TEXT PRIMARY KEY NOT NULL,
                investor_id TEXT NOT NULL REFERENCES md70_investors(id) ON DELETE CASCADE,
                development_id TEXT NOT NULL REFERENCES md70_developments(id) ON DELETE CASCADE,
                invested REAL NOT NULL DEFAULT 0,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(investor_id, development_id)
            );
            """,
            "Table: md70_investments",
        )

        self.run_sql(
            "CREATE INDEX IF NOT EXISTS idx_md70_investments_investor ON md70_investments (investor_id);",
            "Index: idx_md70_investments_investor",
        )

        self.run_sql(
            "CREATE INDEX IF NOT EXISTS idx_md70_investments_dev ON md70_investments (development_id);",
            "Index: idx_md70_investments_dev",
        )

        self.run_sql(
            """
            CREATE TABLE IF NOT EXISTS md70_investment_snapshots (
                id TEXT PRIMARY KEY NOT NULL,
                investment_id TEXT NOT NULL REFERENCES md70_investments(id) ON DELETE CASCADE,
                month TEXT NOT NULL,
                invested REAL NOT NULL DEFAULT 0,
                value REAL NOT NULL DEFAULT 0,
                cdi_value REAL NOT NULL DEFAULT 0,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(investment_id, month)
            );
            """,
            "Table: md70_investment_snapshots",
        )

        self.run_sql(
            "CREATE INDEX IF NOT EXISTS idx_md70_snapshots_inv_month ON md70_investment_snapshots (investment_id, month);",
            "Index: idx_md70_snapshots_inv_month",
        )

        self.run_sql(
            """
            CREATE TABLE IF NOT EXISTS md70_cdi_rates (
                id TEXT PRIMARY KEY NOT NULL,
                month TEXT NOT NULL UNIQUE,
                rate REAL NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );
            """,
            "Table: md70_cdi_rates",
        )

        self.run_sql(
            """
            CREATE TABLE IF NOT EXISTS md70_announcements (
                id TEXT PRIMARY KEY NOT NULL,
                development_id TEXT NOT NULL REFERENCES md70_developments(id) ON DELETE CASCADE,
                title TEXT NOT NULL,
                body TEXT NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );
            """,
            "Table: md70_announcements",
        )

        self.run_sql(
            "CREATE INDEX IF NOT EXISTS idx_md70_announcements_dev ON md70_announcements (development_id);",
            "Index: idx_md70_announcements_dev",
        )

        self.run_sql(
            """
            CREATE TABLE IF NOT EXISTS md70_investor_documents (
                id TEXT PRIMARY KEY NOT NULL,
                development_id TEXT REFERENCES md70_developments(id) ON DELETE SET NULL,
                name TEXT NOT NULL,
                category TEXT NOT NULL DEFAULT 'Outros',
                date TEXT NOT NULL,
                size TEXT NOT NULL DEFAULT '',
                file_url TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );
            """,
            "Table: md70_investor_documents",
        )

        self.run_sql(
            "CREATE INDEX IF NOT EXISTS idx_md70_inv_docs_dev ON md70_investor_documents (development_id);",
            "Index: idx_md70_inv_docs_dev",
        )

    def column_exists(self, table_name: str, column_name: str) -> bool:
        """Verificar se uma coluna existe em uma tabela usando PRAGMA."""
        try:
            with self.engine.connect() as conn:
                result = conn.execute(text(f"PRAGMA table_info({table_name})"))
                columns = [row[1] for row in result.fetchall()]
                return column_name in columns
        except Exception as e:
            debug(f"Error checking column {column_name} in {table_name}: {e}")
            return False

    def validate_schema(self):
        """
        Valida que o banco contém exatamente as tabelas e colunas definidas nos Models SQLAlchemy.
        Deriva o schema esperado dos próprios Models (sem hardcode) e compara via inspect().
        Derruba o servidor com sys.exit(1) se houver incoerência.
        """
        from sqlalchemy import inspect as _inspect
        from App.Core.Crunch.TablesSQL.Models import Base as _Base

        # Schema esperado: derivado dos Models ORM (fonte de verdade)
        expected: dict[str, set[str]] = {
            table_name: {col.name for col in table_obj.columns}
            for table_name, table_obj in _Base.metadata.tables.items()
        }

        # Schema real: inspecionar o banco
        inspector = _inspect(self.engine)
        actual_tables = set(inspector.get_table_names())

        missing_tables = sorted(set(expected) - actual_tables)
        missing_cols: list[str] = []

        for table_name, exp_cols in expected.items():
            if table_name in actual_tables:
                actual_cols = {col["name"] for col in inspector.get_columns(table_name)}
                for col in sorted(exp_cols - actual_cols):
                    missing_cols.append(f"{table_name}.{col}")

        if missing_tables or missing_cols:
            parts = []
            if missing_tables:
                parts.append(f"tabelas ausentes: {', '.join(missing_tables)}")
            if missing_cols:
                parts.append(f"colunas ausentes: {', '.join(missing_cols)}")
            msg = (
                "[SCHEMA] INCOERÊNCIA CRÍTICA — "
                + "; ".join(parts)
                + ". Reinicie o DB de dev para recriar as tabelas com o schema atual."
            )
            error(msg)
            import sys as _sys

            _sys.exit(1)

        info(
            f"[SCHEMA] Validação OK — {len(expected)} tabelas verificadas via Models, schema coerente."
        )

    def run_migrations(self):
        """Executar migrações para tabelas já existentes (ALTER TABLE)."""

        # MD70: role column distinguishes investors from admin users
        if not self.column_exists("users", "role"):
            try:
                self.run_sql(
                    "ALTER TABLE users ADD COLUMN role TEXT DEFAULT 'investor'",
                    "Migration: Add role to users",
                )
            except Exception as e:
                warning(f"Migration: Failed to add role to users: {e}")

        # 2FA columns
        if not self.column_exists("users", "two_factor_enabled"):
            try:
                self.run_sql(
                    "ALTER TABLE users ADD COLUMN two_factor_enabled BOOLEAN DEFAULT 0",
                    "Migration: Add two_factor_enabled to users",
                )
            except Exception as e:
                warning(f"Migration: Failed to add two_factor_enabled: {e}")

        if not self.column_exists("users", "two_factor_secret"):
            try:
                self.run_sql(
                    "ALTER TABLE users ADD COLUMN two_factor_secret TEXT",
                    "Migration: Add two_factor_secret to users",
                )
            except Exception as e:
                warning(f"Migration: Failed to add two_factor_secret: {e}")

        # Omni-channel identifiers
        for col in ["whatsapp", "instagram", "telegram"]:
            if not self.column_exists("users", col):
                try:
                    self.run_sql(
                        f"ALTER TABLE users ADD COLUMN {col} TEXT",
                        f"Migration: Add {col} to users",
                    )
                except Exception as e:
                    warning(f"Migration: Failed to add {col} to users: {e}")

        # Adicionar coluna ratio para armazenar aspect ratio dos assets gerados
        if not self.column_exists("assets", "ratio"):
            try:
                self.run_sql(
                    "ALTER TABLE assets ADD COLUMN ratio TEXT",
                    "Migration: Add ratio column to assets table",
                )
            except Exception as e:
                warning(f"Migration: Failed to add ratio column to assets: {e}")

        if not self.column_exists("integrations_mcp", "token_valid"):
            try:
                self.run_sql(
                    "ALTER TABLE integrations_mcp ADD COLUMN token_valid BOOLEAN DEFAULT 1",
                    "Migration: Add token_valid column to integrations_mcp",
                )
            except Exception as e:
                warning(
                    f"Migration: Failed to add token_valid column to integrations_mcp: {e}"
                )

        # Migrar assets: adicionar approval_status e feedback (substitui approving_logs)
        if not self.column_exists("assets", "approval_status"):
            try:
                self.run_sql(
                    "ALTER TABLE assets ADD COLUMN approval_status TEXT DEFAULT 'waitingJudge'",
                    "Migration: Add approval_status column to assets table",
                )
            except Exception as e:
                warning(f"Migration: Failed to add approval_status to assets: {e}")

        if not self.column_exists("assets", "feedback"):
            try:
                self.run_sql(
                    "ALTER TABLE assets ADD COLUMN feedback TEXT",
                    "Migration: Add feedback column to assets table",
                )
            except Exception as e:
                warning(f"Migration: Failed to add feedback to assets: {e}")

        # Migrar temp_urls: adicionar campos para attachment tokens
        for col, defn in [
            ("attachment_id", "TEXT"),
            ("user_id", "TEXT"),
            ("used", "INTEGER DEFAULT 0"),
        ]:
            if not self.column_exists("temp_urls", col):
                try:
                    self.run_sql(
                        f"ALTER TABLE temp_urls ADD COLUMN {col} {defn}",
                        f"Migration: Add {col} to temp_urls",
                    )
                except Exception as e:
                    warning(f"Migration: Failed to add {col} to temp_urls: {e}")

        # Migrar temp_urls: remover coluna screenshot_id (obsoleta)
        try:
            with self.engine.connect() as conn:
                row = conn.execute(
                    text(
                        "SELECT sql FROM sqlite_master WHERE type='table' AND name='temp_urls'"
                    )
                ).fetchone()
                schema_sql = (row[0] or "") if row else ""
                has_screenshot_id = "screenshot_id" in schema_sql.lower()

                if has_screenshot_id:
                    conn.execute(
                        text(
                            """
                        CREATE TABLE IF NOT EXISTS temp_urls_new (
                            token TEXT PRIMARY KEY,
                            filepath TEXT,
                            origin_url TEXT,
                            expires_at REAL NOT NULL,
                            attachment_id TEXT,
                            user_id TEXT,
                            used INTEGER DEFAULT 0,
                            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                        )
                    """
                        )
                    )
                    conn.execute(
                        text(
                            """
                        INSERT OR IGNORE INTO temp_urls_new
                            (token, filepath, origin_url, expires_at,
                             attachment_id, user_id, used, created_at)
                        SELECT token, filepath, origin_url, expires_at,
                               attachment_id, user_id, used, created_at
                        FROM temp_urls
                    """
                        )
                    )
                    conn.execute(text("DROP TABLE temp_urls"))
                    conn.execute(text("ALTER TABLE temp_urls_new RENAME TO temp_urls"))
                    conn.commit()
                    info("Migration: temp_urls recreated without screenshot_id")
        except Exception as e:
            warning(f"Migration: Failed to remove screenshot_id from temp_urls: {e}")

        # Migrar jobs: adicionar user_id
        if not self.column_exists("jobs", "user_id"):
            try:
                self.run_sql(
                    "ALTER TABLE jobs ADD COLUMN user_id TEXT REFERENCES users(user_id) ON DELETE SET NULL",
                    "Migration: Add user_id to jobs",
                )
            except Exception as e:
                warning(f"Migration: Failed to add user_id to jobs: {e}")

        # Tracking de uso por sessão e semana (rate limiting independente de créditos)
        for col, defn in [
            ("current_session_usage", "REAL DEFAULT 0"),
            ("current_session_starts_at", "DATETIME"),
            ("current_week_usage", "REAL DEFAULT 0"),
            ("current_week_starts_at", "DATETIME"),
        ]:
            if not self.column_exists("users", col):
                try:
                    self.run_sql(
                        f"ALTER TABLE users ADD COLUMN {col} {defn}",
                        f"Migration: Add {col} to users",
                    )
                except Exception as e:
                    warning(f"Migration: Failed to add {col} to users: {e}")

        # Percentuais de uso de sessão/semana nos logs de créditos
        for col, defn in [
            ("session_usage_pct", "REAL"),
            ("week_usage_pct", "REAL"),
        ]:
            if not self.column_exists("credits_logs", col):
                try:
                    self.run_sql(
                        f"ALTER TABLE credits_logs ADD COLUMN {col} {defn}",
                        f"Migration: Add {col} to credits_logs",
                    )
                except Exception as e:
                    warning(f"Migration: Failed to add {col} to credits_logs: {e}")

        # Pinar chats
        if not self.column_exists("chats", "is_pinned"):
            try:
                self.run_sql(
                    "ALTER TABLE chats ADD COLUMN is_pinned INTEGER DEFAULT 0",
                    "Migration: Add is_pinned to chats",
                )
            except Exception as e:
                warning(f"Migration: Failed to add {col} to credits_logs: {e}")

        # Snapshot do design renderizado (base64 PNG, sem prefixo data URI)
        for col, defn in [
            ("snapshot_b64", "TEXT"),
            ("snapshot_version", "INTEGER"),
        ]:
            if not self.column_exists("creative_compositions", col):
                try:
                    self.run_sql(
                        f"ALTER TABLE creative_compositions ADD COLUMN {col} {defn}",
                        f"Migration: Add {col} to creative_compositions",
                    )
                except Exception as e:
                    warning(
                        f"Migration: Failed to add {col} to creative_compositions: {e}"
                    )

        # Conexões por chat (whitelist de providers MCP)
        if not self.column_exists("chats", "connections"):
            try:
                self.run_sql(
                    "ALTER TABLE chats ADD COLUMN connections TEXT DEFAULT NULL",
                    "Migration: Add connections to chats",
                )
            except Exception as e:
                warning(f"Migration: Failed to add connections to chats: {e}")

        # Nível de autonomia em tarefas agendadas
        if not self.column_exists("scheduled_tasks", "autonomy_level"):
            try:
                self.run_sql(
                    "ALTER TABLE scheduled_tasks ADD COLUMN autonomy_level INTEGER NOT NULL DEFAULT 4",
                    "Migration: Add autonomy_level to scheduled_tasks",
                )
            except Exception as e:
                warning(
                    f"Migration: Failed to add autonomy_level to scheduled_tasks: {e}"
                )

        if not self.column_exists("scheduled_tasks", "utc_offset"):
            try:
                self.run_sql(
                    "ALTER TABLE scheduled_tasks ADD COLUMN utc_offset INTEGER NOT NULL DEFAULT 0",
                    "Migration: Add utc_offset to scheduled_tasks",
                )
            except Exception as e:
                warning(f"Migration: Failed to add utc_offset to scheduled_tasks: {e}")

        # triggers table was dropped — migrations removed

        # seen: 0 = novo/não lido, 1 = visto (default)
        if not self.column_exists("chats", "seen"):
            try:
                self.run_sql(
                    "ALTER TABLE chats ADD COLUMN seen INTEGER DEFAULT 1",
                    "Migration: Add seen to chats",
                )
            except Exception as e:
                warning(f"Migration: Failed to add seen to chats: {e}")

        # source: identifica chats criados por triggers ou agendamentos
        if not self.column_exists("chats", "source"):
            try:
                self.run_sql(
                    "ALTER TABLE chats ADD COLUMN source TEXT DEFAULT NULL",
                    "Migration: Add source to chats",
                )
            except Exception as e:
                warning(f"Migration: Failed to add source to chats: {e}")

        if not self.column_exists("chats", "external_sender_id"):
            try:
                self.run_sql(
                    "ALTER TABLE chats ADD COLUMN external_sender_id TEXT DEFAULT NULL",
                    "Migration: Add external_sender_id to chats",
                )
            except Exception as e:
                warning(f"Migration: Failed to add external_sender_id: {e}")

        if not self.column_exists("chats", "external_sender_name"):
            try:
                self.run_sql(
                    "ALTER TABLE chats ADD COLUMN external_sender_name TEXT DEFAULT NULL",
                    "Migration: Add external_sender_name to chats",
                )
            except Exception as e:
                warning(f"Migration: Failed to add external_sender_name: {e}")

        if not self.column_exists("chats", "trigger_id"):
            try:
                self.run_sql(
                    "ALTER TABLE chats ADD COLUMN trigger_id TEXT DEFAULT NULL",
                    "Migration: Add trigger_id to chats",
                )
            except Exception as e:
                warning(f"Migration: Failed to add trigger_id: {e}")

        if not self.column_exists("chats", "context_usage_pct"):
            try:
                self.run_sql(
                    "ALTER TABLE chats ADD COLUMN context_usage_pct REAL DEFAULT 0.0",
                    "Migration: Add context_usage_pct to chats",
                )
            except Exception as e:
                warning(f"Migration: Failed to add context_usage_pct: {e}")

        # Analytics: sdk_key e site_id para tracking de sites dos clientes
        if not self.column_exists("clients", "sdk_key"):
            try:
                self.run_sql(
                    "ALTER TABLE clients ADD COLUMN sdk_key TEXT",
                    "Migration: Add sdk_key to clients",
                )
            except Exception as e:
                warning(f"Migration: Failed to add sdk_key to clients: {e}")

        if not self.column_exists("clients", "site_id"):
            try:
                self.run_sql(
                    "ALTER TABLE clients ADD COLUMN site_id TEXT",
                    "Migration: Add site_id to clients",
                )
            except Exception as e:
                warning(f"Migration: Failed to add site_id to clients: {e}")

        if not self.column_exists("clients", "site_url"):
            try:
                self.run_sql(
                    "ALTER TABLE clients ADD COLUMN site_url TEXT",
                    "Migration: Add site_url to clients",
                )
            except Exception as e:
                warning(f"Migration: Failed to add site_url to clients: {e}")

        if not self.column_exists("agent_isolated_messages", "updated_at"):
            try:
                self.run_sql(
                    "ALTER TABLE agent_isolated_messages ADD COLUMN updated_at DATETIME DEFAULT CURRENT_TIMESTAMP",
                    "Migration: add updated_at to agent_isolated_messages",
                )
            except Exception as e:
                warning(
                    f"Migration: Failed to add updated_at to agent_isolated_messages: {e}"
                )

        # source: identifica se o attachment foi enviado pelo usuário ('user') ou gerado pelo agente no terminal ('agent')
        if not self.column_exists("attachments", "source"):
            try:
                self.run_sql(
                    "ALTER TABLE attachments ADD COLUMN source TEXT DEFAULT 'user'",
                    "Migration: Add source to attachments",
                )
            except Exception as e:
                warning(f"Migration: Failed to add source to attachments: {e}")

        # sandbox_path: caminho relativo dentro do sandbox onde o arquivo deve ser re-injetado (ex: 'relatorio.html', 'user/dados.csv')
        if not self.column_exists("attachments", "sandbox_path"):
            try:
                self.run_sql(
                    "ALTER TABLE attachments ADD COLUMN sandbox_path TEXT DEFAULT NULL",
                    "Migration: Add sandbox_path to attachments",
                )
            except Exception as e:
                warning(f"Migration: Failed to add sandbox_path to attachments: {e}")

        # MD70: shared admin chat support
        self._add_column_if_missing(
            "chats", "is_admin_shared", "BOOLEAN DEFAULT 0",
            "Migration: add is_admin_shared to chats"
        )

        # MD70: rich development fields
        self._add_column_if_missing("md70_developments", "category", "TEXT")
        self._add_column_if_missing("md70_developments", "summary", "TEXT")
        self._add_column_if_missing("md70_developments", "planned_progress", "INTEGER DEFAULT 0")
        self._add_column_if_missing("md70_developments", "current_stage", "TEXT")
        self._add_column_if_missing("md70_developments", "next_stage", "TEXT")
        self._add_column_if_missing("md70_developments", "gallery_json", "TEXT")
        self._add_column_if_missing("md70_developments", "plan_json", "TEXT")
        self._add_column_if_missing("md70_developments", "scenarios_json", "TEXT")
        self._add_column_if_missing("md70_developments", "milestones_json", "TEXT")
        self._add_column_if_missing("md70_developments", "gantt_months_json", "TEXT")
        self._add_column_if_missing("md70_developments", "diary_json", "TEXT")
        self._add_column_if_missing("md70_developments", "budget_series_json", "TEXT")
        self._add_column_if_missing("md70_developments", "budget_items_json", "TEXT")
        self._add_column_if_missing("md70_developments", "result_json", "TEXT")
        self._add_column_if_missing("md70_developments", "month_changes_json", "TEXT")
        self._add_column_if_missing("md70_developments", "month_impact", "TEXT")

        # MD70: updated_at on movements for PATCH support
        self._add_column_if_missing("md70_movements", "updated_at", "DATETIME")
        # MD70: separate accrual date (competência) vs cash date (caixa)
        self._add_column_if_missing("md70_movements", "date_competencia", "TEXT")
        # MD70: operational / obra fields on movements
        self._add_column_if_missing("md70_movements", "is_operational", "INTEGER DEFAULT 0")
        self._add_column_if_missing("md70_movements", "obra_type", "TEXT")
        self._add_column_if_missing("md70_movements", "obra_category", "TEXT")
        self._add_column_if_missing("md70_movements", "cnpj", "TEXT")
        self._add_column_if_missing("md70_movements", "recipient_name", "TEXT")
        # MD70: multiple project interests on leads
        self._add_column_if_missing("md70_leads", "project_interests_json", "TEXT")
        # MD70: financeiro-equivalent fields on purchases
        self._add_column_if_missing("md70_purchases", "cnpj", "TEXT")
        self._add_column_if_missing("md70_purchases", "recipient_name", "TEXT")
        self._add_column_if_missing("md70_purchases", "is_operational", "INTEGER DEFAULT 0")
        self._add_column_if_missing("md70_purchases", "obra_type", "TEXT")
        self._add_column_if_missing("md70_purchases", "obra_category", "TEXT")
        self._add_column_if_missing("md70_purchases", "attachment", "TEXT")

        # Ensure fundo operacional sentinel development exists
        try:
            with self.engine.connect() as conn:
                conn.execute(text(
                    "INSERT OR IGNORE INTO md70_developments (id, name, status, progress, capital, budget, remaining) "
                    "VALUES ('fundo-md70', 'Fundo MD70 (Operacional)', 'Projeto', 0, 0, 0, 0)"
                ))
                conn.commit()
        except Exception:
            pass

    def create_triggers_and_indexes(self):
        """Criar triggers e índices para otimização."""

        # ============================================================================
        # ÍNDICES PARA PERFORMANCE
        # ============================================================================

        self.run_sql(
            "CREATE INDEX IF NOT EXISTS idx_plans_id ON plans (plan_id);",
            "Index: idx_plans_id",
        )

        self.run_sql(
            "CREATE INDEX IF NOT EXISTS idx_plans_active_test ON plans (active, test_id);",
            "Index: idx_plans_active_test",
        )

        self.run_sql(
            "CREATE INDEX IF NOT EXISTS idx_users_email ON users (email);",
            "Index: idx_users_email",
        )

        self.run_sql(
            "CREATE INDEX IF NOT EXISTS idx_users_client ON users (client_id);",
            "Index: idx_users_client",
        )

        self.run_sql(
            "CREATE INDEX IF NOT EXISTS idx_users_fingerprint ON users (fingerprint_id);",
            "Index: idx_users_fingerprint",
        )

        self.run_sql(
            "CREATE INDEX IF NOT EXISTS idx_chats_user ON chats (user_id);",
            "Index: idx_chats_user",
        )

        self.run_sql(
            "CREATE INDEX IF NOT EXISTS idx_messages_chat ON messages (chat_id);",
            "Index: idx_messages_chat",
        )

        self.run_sql(
            "CREATE INDEX IF NOT EXISTS idx_messages_chat ON messages (chat_id);",
            "Index: idx_messages_chat",
        )

        self.run_sql(
            "CREATE INDEX IF NOT EXISTS idx_messages_type ON messages (message_type);",
            "Index: idx_messages_type",
        )

        self.run_sql(
            "CREATE INDEX IF NOT EXISTS idx_attachments_chat ON attachments (chat_id);",
            "Index: idx_attachments_chat",
        )

        self.run_sql(
            "CREATE INDEX IF NOT EXISTS idx_attachments_message ON attachments (message_id);",
            "Index: idx_attachments_message",
        )

        self.run_sql(
            "CREATE INDEX IF NOT EXISTS idx_assets_chat ON assets (chat_id);",
            "Index: idx_assets_chat",
        )

        self.run_sql(
            "CREATE INDEX IF NOT EXISTS idx_assets_user ON assets (user_id);",
            "Index: idx_assets_user",
        )

        self.run_sql(
            "CREATE INDEX IF NOT EXISTS idx_assets_type ON assets (type);",
            "Index: idx_assets_type",
        )

        self.run_sql(
            "CREATE INDEX IF NOT EXISTS idx_assets_id ON assets (asset_id);",
            "Index: idx_assets_id",
        )

        self.run_sql(
            "CREATE INDEX IF NOT EXISTS idx_access_tokens_user_id ON access_tokens (user_id);",
            "Index: idx_access_tokens_user_id",
        )

        self.run_sql(
            "CREATE INDEX IF NOT EXISTS idx_access_tokens_expires ON access_tokens (expires_at);",
            "Index: idx_access_tokens_expires",
        )

        self.run_sql(
            "CREATE INDEX IF NOT EXISTS idx_refresh_tokens_user_id ON refresh_tokens (user_id);",
            "Index: idx_refresh_tokens_user_id",
        )

        # REMOVIDO: Índices da tabela 'files' (tabela removida em favor de 'assets')
        # - idx_files_hash
        # - idx_files_user
        # - idx_files_client
        # - idx_files_chat
        # - idx_files_category
        # - idx_files_temp

        # ============================================================================
        # 🔍 ÍNDICES PARA TABELAS DE CHAT ISOLADO
        # ============================================================================

        self.run_sql(
            "CREATE INDEX IF NOT EXISTS idx_isolated_chat_chat_id ON isolated_chat (chat_id);",
            "Index: idx_isolated_chat_chat_id",
        )

        self.run_sql(
            "CREATE INDEX IF NOT EXISTS idx_isolated_chat_chat_id ON isolated_chat (chat_id);",
            "Index: idx_isolated_chat_chat_id",
        )

        self.run_sql(
            "CREATE INDEX IF NOT EXISTS idx_isolated_chat_agent_id ON isolated_chat (agent_id);",
            "Index: idx_isolated_chat_agent_id",
        )

        self.run_sql(
            "CREATE INDEX IF NOT EXISTS idx_isolated_messages_chat_id ON isolated_messages (isolated_chat_id);",
            "Index: idx_isolated_messages_chat_id",
        )

        self.run_sql(
            "CREATE INDEX IF NOT EXISTS idx_isolated_messages_uuid ON isolated_messages (isolated_message_id);",
            "Index: idx_isolated_messages_uuid",
        )

        self.run_sql(
            "CREATE INDEX IF NOT EXISTS idx_isolated_messages_role ON isolated_messages (role);",
            "Index: idx_isolated_messages_role",
        )

        self.run_sql(
            "CREATE INDEX IF NOT EXISTS idx_isolated_messages_agent_id ON isolated_messages (agent_id);",
            "Index: idx_isolated_messages_agent_id",
        )

        self.run_sql(
            "CREATE INDEX IF NOT EXISTS idx_isolated_messages_agent ON isolated_messages (agent);",
            "Index: idx_isolated_messages_agent",
        )

        # ============================================================================
        # 📤 ÍNDICES PARA UPLOADS E SESSIONS
        # ============================================================================

        self.run_sql(
            "CREATE INDEX IF NOT EXISTS idx_attachments_chat ON attachments (chat_id);",
            "Index: idx_attachments_chat",
        )

        self.run_sql(
            "CREATE INDEX IF NOT EXISTS idx_attachments_message ON attachments (message_id);",
            "Index: idx_attachments_message",
        )

        self.run_sql(
            "CREATE INDEX IF NOT EXISTS idx_attachments_temp ON attachments (is_temp);",
            "Index: idx_attachments_temp",
        )

        self.run_sql(
            "CREATE INDEX IF NOT EXISTS idx_message_feedbacks_chat ON message_feedbacks (chat_id);",
            "Index: idx_message_feedbacks_chat",
        )

        self.run_sql(
            "CREATE INDEX IF NOT EXISTS idx_message_feedbacks_message ON message_feedbacks (message_id);",
            "Index: idx_message_feedbacks_message",
        )

        self.run_sql(
            "CREATE INDEX IF NOT EXISTS idx_message_feedbacks_type ON message_feedbacks (feedback_type);",
            "Index: idx_message_feedbacks_type",
        )

        self.run_sql(
            """
            CREATE TABLE IF NOT EXISTS note_groups (
                id TEXT PRIMARY KEY NOT NULL,
                user_id TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
                name TEXT NOT NULL,
                description TEXT DEFAULT NULL,
                emoji TEXT DEFAULT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );
            """,
            "Table: note_groups",
        )

        self.run_sql(
            "CREATE INDEX IF NOT EXISTS idx_note_groups_user ON note_groups (user_id);",
            "Index: idx_note_groups_user",
        )

        self.run_sql(
            """
            CREATE TABLE IF NOT EXISTS notes (
                id TEXT PRIMARY KEY NOT NULL,
                user_id TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
                content TEXT NOT NULL,
                group_id TEXT REFERENCES note_groups(id) ON DELETE SET NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );
            """,
            "Table: notes",
        )

        self.run_sql(
            "CREATE INDEX IF NOT EXISTS idx_notes_user ON notes (user_id, created_at);",
            "Index: idx_notes_user",
        )

        # Migrations para bancos existentes (ignoradas se coluna já existe)
        self._add_column_if_missing("note_groups", "description", "TEXT DEFAULT NULL")
        self._add_column_if_missing("note_groups", "emoji", "TEXT DEFAULT NULL")
        self._add_column_if_missing(
            "notes", "group_id", "TEXT REFERENCES note_groups(id) ON DELETE SET NULL"
        )

        # Drop tabela `triggers` legada — substituída por webhook_secrets
        self.run_sql(
            "DROP INDEX IF EXISTS idx_triggers_user;",
            "Migration: drop idx_triggers_user",
            fail_silently=True,
        )
        self.run_sql(
            "DROP INDEX IF EXISTS idx_triggers_user_name;",
            "Migration: drop idx_triggers_user_name",
            fail_silently=True,
        )
        self.run_sql(
            "DROP TABLE IF EXISTS triggers;",
            "Migration: drop triggers table (substituída por webhook_secrets)",
            fail_silently=True,
        )
        # Recriar trigger_executions com FK para webhook_secrets em vez de triggers
        if self.column_exists("trigger_executions", "trigger_id"):
            try:
                with DatabaseManager.get_engine().connect() as conn:
                    conn.execute(text("DROP INDEX IF EXISTS idx_trigger_exec_trigger"))
                    conn.execute(text("DROP TABLE IF EXISTS trigger_executions"))
                    conn.execute(
                        text(
                            """
                        CREATE TABLE IF NOT EXISTS trigger_executions (
                            id TEXT PRIMARY KEY NOT NULL,
                            web_secret_id TEXT NOT NULL REFERENCES webhook_secrets(web_secret_id) ON DELETE CASCADE,
                            user_id TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
                            chat_id TEXT,
                            status TEXT NOT NULL DEFAULT 'running'
                                CHECK(status IN ('running','completed','pending_review','approved','rejected','failed')),
                            result_summary TEXT,
                            started_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                            finished_at DATETIME,
                            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                        )
                    """
                        )
                    )
                    conn.execute(
                        text(
                            "CREATE INDEX IF NOT EXISTS idx_trigger_exec_secret ON trigger_executions (web_secret_id)"
                        )
                    )
                    conn.execute(
                        text(
                            "CREATE INDEX IF NOT EXISTS idx_trigger_exec_user ON trigger_executions (user_id)"
                        )
                    )
                    conn.commit()
                info(
                    "Migration: trigger_executions recriada com FK para webhook_secrets"
                )
            except Exception as e:
                warning(f"Migration: Failed to recreate trigger_executions: {e}")

        # ── Dynamic links (NFC / QR stickers) ────────────────────────────────
        self.run_sql(
            """
            CREATE TABLE IF NOT EXISTS dynamic_links (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                dynamic_link_id TEXT UNIQUE NOT NULL,
                client_id TEXT,
                table_number TEXT,
                active INTEGER NOT NULL DEFAULT 1,
                destination TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );
            """,
            "Table: dynamic_links",
        )
        self.run_sql(
            "CREATE INDEX IF NOT EXISTS idx_dynamic_links_client ON dynamic_links (client_id);",
            "Index: idx_dynamic_links_client",
        )

        # ============================================================================
        # 📊 MD70 — TABELAS DE INVESTIDORES E ADMINISTRADORES
        # ============================================================================

        self.run_sql(
            """
            CREATE TABLE IF NOT EXISTS investors_users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT UNIQUE NOT NULL,
                investor_code TEXT UNIQUE,
                cpf_encrypted TEXT,
                phone TEXT,
                address TEXT,
                city TEXT,
                state TEXT,
                zip_code TEXT,
                birth_date DATE,
                total_invested REAL DEFAULT 0,
                portfolio_value REAL DEFAULT 0,
                referral_code TEXT,
                referred_by TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (user_id) ON DELETE CASCADE
            );
        """,
            "Table: investors_users",
        )

        self.run_sql(
            "CREATE INDEX IF NOT EXISTS idx_investors_users_user ON investors_users (user_id);",
            "Index: idx_investors_users_user",
        )

        self.run_sql(
            """
            CREATE TABLE IF NOT EXISTS admin_users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT UNIQUE NOT NULL,
                department TEXT,
                access_level TEXT CHECK(access_level IN ('super', 'manager', 'analyst')) DEFAULT 'analyst',
                two_factor_required BOOLEAN DEFAULT 1,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (user_id) ON DELETE CASCADE
            );
        """,
            "Table: admin_users",
        )

        self.run_sql(
            "CREATE INDEX IF NOT EXISTS idx_admin_users_user ON admin_users (user_id);",
            "Index: idx_admin_users_user",
        )

    def create_schema(self):
        """
        Criar schema completo do banco de dados.
        Executa em ordem:
        1. Tabelas
        2. Triggers e Índices (apenas para local/postgresql)
        3. Sincronizar planos (popular tabela plans)
        4. Dados Mock (apenas para local/postgresql e quando necessário)
        """
        try:
            # Log inicial mostrando qual schema está usando
            schema_info = self._get_schema_info()
            info(f"[SCHEMA] Initializing schema on {schema_info}...")

            # Se for Supabase REST, apenas conectar (schema já existe)
            if database.is_rest_api():
                self.create_tables()  # Retorna cedo, não precisa do resto
                self.run_migrations()
                info(
                    f"[SCHEMA] {self.tables_created} tables + {self.indexes_created} indexes ({schema_info})"
                )
                return

            # Para SQLite e PostgreSQL direto, fazer o fluxo completo
            self.create_all_tables()
            self.run_migrations()
            self.create_triggers_and_indexes()

            # PRIMEIRO: Sincronizar planos para popular a tabela plans
            from App.Core.Crunch.PlansSync import PlansSync

            PlansSync.sync(self.engine, self.config)

            # DEPOIS: Inserir dados mock (que depende dos planos)
            from App.Core.Crunch.MockData import MockData

            MockData.sync(self.engine)

            # HIDRATAÇÃO: Puxar dados ativos do Supabase se o banco local estiver vazio
            self.hydrate_from_cloud()

            # Validar coerência do schema com o banco — crash se incoerente
            self.validate_schema()

            # Log final com resumo (dinâmico baseado no que foi criado)
            info(
                f"[SCHEMA] {self.tables_created} tables + {self.indexes_created} indexes ({schema_info})"
            )
        except Exception as e:
            self.errors.append(str(e))
            error(f"[SCHEMA] Failed: {e}")
            raise

    def hydrate_from_cloud(self):
        """
        Sincroniza dados do Supabase para o SQLite local no boot.
        Executado apenas se DB_ENV for 'cloud-rest' ou 'cloud-tcp'.
        Evita duplicados inserindo apenas se a tabela local estiver vazia.
        """
        db_env = self.config.get("db_env", "local").lower()
        if db_env not in ["cloud-rest", "cloud-tcp"]:
            return

        info(f"[SCHEMA] Verificando necessidade de hidratação (Ambiente: {db_env})...")

        try:
            from supabase import create_client

            supabase_url = self.config.get("supabase_url")
            supabase_key = self.config.get("supabase_key") or self.config.get(
                "supabase_service_role_key"
            )

            if not supabase_url or not supabase_key:
                warning("[SCHEMA] Credenciais Supabase ausentes para hidratação.")
                return

            supabase = create_client(supabase_url, supabase_key)
            prefix = self._get_table_prefix()

            # Tabelas essenciais para o funcionamento do sistema
            # Ordem importa por causa de Foreign Keys
            tables_to_sync = [
                "plans",
                "clients",
                "users",
                "chats",
                "messages",
            ]

            with self.engine.connect() as conn:
                for table in tables_to_sync:
                    # Verificar se a tabela local está vazia
                    try:
                        result = conn.execute(text(f"SELECT COUNT(*) FROM {table}"))
                        local_count = result.scalar()
                    except Exception:
                        local_count = 0

                    if local_count == 0:
                        cloud_table = f"{prefix}{table}"
                        info(f"[SCHEMA] ⬇️ Hidratando '{table}' do Supabase...")

                        try:
                            # Pull data
                            res = supabase.table(cloud_table).select("*").execute()

                            if res.data:
                                for row in res.data:
                                    # Preparar insert dinâmico
                                    keys = row.keys()
                                    cols = ", ".join(keys)
                                    placeholders = ", ".join([f":{k}" for k in keys])
                                    sql = f"INSERT INTO {table} ({cols}) VALUES ({placeholders})"
                                    conn.execute(text(sql), row)

                                conn.commit()
                                info(
                                    f"[SCHEMA] ✓ {len(res.data)} registros sincronizados para '{table}'"
                                )
                            else:
                                debug(
                                    f"[SCHEMA] Tabela remota '{cloud_table}' está vazia."
                                )
                        except Exception as e:
                            warning(f"[SCHEMA] Falha ao hidratar '{table}': {e}")
                    else:
                        debug(
                            f"[SCHEMA] Tabela local '{table}' já possui dados ({local_count} registros)."
                        )

            info("[SCHEMA] Processo de hidratação de dados concluído.")

        except ImportError:
            warning(
                "[SCHEMA] Biblioteca 'supabase' não instalada. Use: pip install supabase"
            )
        except Exception as e:
            error(f"[SCHEMA] Erro fatal na hidratação: {e}")

    def _execute_supabase_schema(self):
        """Executar schema SQL do arquivo para Supabase via API REST."""
        try:
            from pathlib import Path

            # Localizar arquivo SQL (sobe até MD70 root)
            # Path hierarchy: SchemaManager.py -> TablesSQL -> Crunch -> Core -> App -> backend -> services -> mvp -> App -> MD70 -> CloudDB
            # __file__ = backend/App/Core/Crunch/TablesSQL/SchemaManager.py
            # Need 9 parents to reach MD70/
            current_dir = Path(__file__).parent  # TablesSQL/
            sql_file = (
                current_dir.parent.parent.parent.parent.parent.parent.parent.parent.parent
                / "CloudDB"
                / "MD70_SchemaManager.sql"
            )

            if not sql_file.exists():
                warning(f"Arquivo SQL não encontrado: {sql_file}")
                return

            # Ler arquivo
            with open(sql_file, "r", encoding="utf-8") as f:
                sql_content = f.read()

            # Determinar schema baseado em env
            schema_name = (
                "dev_schema" if self.config.get("dev_env", False) else "prod_schema"
            )
            info(f"Executando schema: {schema_name}")

            # Extrair queries do schema correto
            queries = self._extract_schema_queries(sql_content, schema_name)

            if not queries:
                warning(f"Nenhuma query encontrada para {schema_name}")
                return

            # Executar queries via Supabase
            # supabase_client = self.engine  # engine é o cliente Supabase quando db_env == 'cloud-rest'

            for i, query in enumerate(queries, 1):
                try:
                    # Executar via PostgREST RPC se possível, ou log
                    debug(f"[{i}/{len(queries)}] Executando query...")
                    # Para agora, apenas log (implementação completa vai usar RPC ou raw SQL)
                except Exception as e:
                    warning(f"Erro executando query {i}: {e}")

            info(
                f"Schema {schema_name} processado com sucesso ({len(queries)} queries)"
            )

        except Exception as e:
            error(f"Erro ao executar Supabase schema: {e}")

    def _extract_schema_queries(self, sql_content: str, schema_name: str) -> List[str]:
        """Extrair queries específicas de um schema do arquivo SQL."""
        queries = []
        lines = sql_content.split("\n")

        in_schema = False
        current_query = []
        target_schema_marker = f"SET search_path TO {schema_name}"

        for line in lines:
            # Detectar início do schema
            if target_schema_marker in line:
                in_schema = True
                continue

            # Detectar fim do schema (próximo SET search_path)
            if (
                in_schema
                and "SET search_path TO" in line
                and target_schema_marker not in line
            ):
                if current_query:
                    queries.append("\n".join(current_query).strip())
                    current_query = []
                break

            # Coletar queries dentro do schema
            if in_schema:
                # Ignorar comentários
                if line.strip().startswith("--"):
                    continue

                current_query.append(line)

                # Detectar fim de statement (;)
                if line.strip().endswith(";"):
                    query = "\n".join(current_query).strip()
                    if query:
                        queries.append(query)
                    current_query = []

        return queries

    def create_all_tables(self):
        """Garante que todas as tabelas existam.

        1. Executa create_tables() para tabelas definidas via raw SQL (billing, plans, etc.)
        2. Executa Base.metadata.create_all() para tabelas definidas via Models.py (ORM).
           Isso garante que novos modelos adicionados ao Models.py sejam criados automaticamente
           sem precisar adicionar SQL manual no SchemaManager.
        """
        from App.Core.Crunch.TablesSQL.Database import Base

        # Importar todos os models para registrar no metadata antes do create_all
        import App.Core.Crunch.TablesSQL.Models  # noqa: F401

        self.create_tables()
        try:
            Base.metadata.create_all(bind=self.engine, checkfirst=True)
            debug("[SCHEMA] Base.metadata.create_all() executado (Models.py → engine)")
        except Exception as e:
            warning(f"[SCHEMA] Erro em Base.metadata.create_all(): {e}")

    def report_results(self):
        """Reportar resultados da criação de schema."""
        if self.errors:
            warning(
                f"[SCHEMA] Schema creation completed with {len(self.errors)} warning(s):"
            )
            for err in self.errors:
                warning(f"  ⚠️  {err}")
        else:
            info("[SCHEMA] All schema operations completed successfully")
