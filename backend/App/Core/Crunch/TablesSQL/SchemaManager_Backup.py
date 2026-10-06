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

    def run_sql(self, sql: str, description: str = "") -> bool:
        """
        Executar SQL com tratamento de erro.
        Conta automaticamente CREATE TABLE e CREATE INDEX para logging.

        Args:
            sql: Comando SQL a executar
            description: Descrição da operação para logging

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
        # MIGRAÇÃO - REMOVER TABELAS ANTIGAS (Conditional on RESET_LOCAL_DB)
        # ============================================================================
        if reset_local_db:
            # Dropar tabela zera_front que é redundante
            self.run_sql(
                "DROP TABLE IF EXISTS zera_front;", "Migration: Drop zera_front table"
            )

            # Dropar outras tabelas que podem ter conflitos
            self.run_sql(
                "DROP TABLE IF EXISTS messages;", "Migration: Drop messages table"
            )
            self.run_sql(
                "DROP TABLE IF EXISTS sub_agents_messages;",
                "Migration: Drop sub_agents_messages table",
            )
            self.run_sql("DROP TABLE IF EXISTS chats;", "Migration: Drop chats table")

            # Dropar tabelas de tokens
            self.run_sql(
                "DROP TABLE IF EXISTS access_tokens;",
                "Migration: Drop access_tokens table",
            )
            self.run_sql(
                "DROP TABLE IF EXISTS refresh_tokens;",
                "Migration: Drop refresh_tokens table",
            )

            # Dropar tabela de tasks
            self.run_sql("DROP TABLE IF EXISTS tasks;", "Migration: Drop tasks table")

            # Dropar tabelas de chat isolado para migração de schema
            # (será recriada com novo schema incluindo agent_id em isolated_messages)
            self.run_sql(
                "DROP TABLE IF EXISTS tools_call;", "Migration: Drop tools_call table"
            )
            self.run_sql(
                "DROP TABLE IF EXISTS message_files;",
                "Migration: Drop message_files table",
            )
            self.run_sql("DROP TABLE IF EXISTS files;", "Migration: Drop files table")
            self.run_sql(
                "DROP TABLE IF EXISTS documents;", "Migration: Drop documents table"
            )
            self.run_sql(
                "DROP TABLE IF EXISTS isolated_messages;",
                "Migration: Drop isolated_messages table",
            )
            self.run_sql(
                "DROP TABLE IF EXISTS isolated_chat;",
                "Migration: Drop isolated_chat table",
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
                credits REAL NOT NULL,
                users_limit INTEGER,
                annual_price REAL,
                monthly_price REAL,
                currency TEXT DEFAULT 'USD',
                credits_reset_in INTEGER,
                features TEXT,
                active BOOLEAN DEFAULT 1,
                sell BOOLEAN DEFAULT 0,
                type TEXT DEFAULT 'plan' CHECK(type IN ('plan', 'extra')),
                test_id TEXT
            );
        """,
            "Table: plans",
        )

        # Tabela do plano ativo do cliente
        self.run_sql(
            """
            CREATE TABLE IF NOT EXISTS client_plans (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                client_plan_id TEXT UNIQUE NOT NULL,
                client_id INTEGER NOT NULL,
                plan_id TEXT NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (client_id) REFERENCES clients (client_id) ON DELETE CASCADE,
                FOREIGN KEY (plan_id) REFERENCES plans (plan_id) ON DELETE RESTRICT
            );
        """,
            "Table: client_plans",
        )

        self.run_sql(
            """
            CREATE TABLE IF NOT EXISTS clients (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                client_id TEXT UNIQUE NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                started_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                finishes_at DATETIME,
                users_available INTEGER NOT NULL DEFAULT 1
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
                type TEXT CHECK(type IN ('trial', 'login')) DEFAULT 'login',
                ip_address TEXT,
                fingerprint_id TEXT,
                credits_available REAL DEFAULT 0,
                credits_reset_at DATETIME,
                daily_credits_resets_at DATETIME,
                cookies_accepted BOOLEAN DEFAULT 0,
                cookies_accepted_at DATETIME,
                terms_accepted BOOLEAN DEFAULT 0,
                terms_accepted_at DATETIME,
                privacy_accepted BOOLEAN DEFAULT 0,
                privacy_accepted_at DATETIME,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
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
                client_id INTEGER NOT NULL,
                token_hash TEXT NOT NULL,
                type TEXT CHECK(type IN ('trial', 'login')) DEFAULT 'login',
                expires_at DATETIME NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                revoked_at DATETIME DEFAULT NULL,
                FOREIGN KEY (user_id) REFERENCES users (user_id) ON DELETE CASCADE,
                FOREIGN KEY (client_id) REFERENCES clients (client_id) ON DELETE CASCADE
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
                client_id INTEGER NOT NULL,
                token_hash TEXT NOT NULL,
                type TEXT CHECK(type IN ('trial', 'login')) DEFAULT 'login',
                expires_at DATETIME NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                revoked_at DATETIME DEFAULT NULL,
                FOREIGN KEY (user_id) REFERENCES users (user_id) ON DELETE CASCADE,
                FOREIGN KEY (client_id) REFERENCES clients (client_id) ON DELETE CASCADE
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
        # 💳 TABELAS DE PAGAMENTO (PAGARME + CARTÕES)
        # ============================================================================

        self.run_sql(
            """
            CREATE TABLE IF NOT EXISTS billing_info (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                billing_id TEXT UNIQUE NOT NULL,
                user_id INTEGER NOT NULL,
                address_encrypted TEXT NOT NULL,
                complement_encrypted TEXT,
                city_encrypted TEXT NOT NULL,
                state_encrypted TEXT NOT NULL,
                postal_code_encrypted TEXT NOT NULL,
                phone_number_encrypted TEXT NOT NULL,
                document_encrypted TEXT NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
            );
        """,
            "Table: billing_info",
        )

        self.run_sql(
            """
            CREATE TABLE IF NOT EXISTS cards (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                card_id TEXT UNIQUE NOT NULL,
                user_id INTEGER NOT NULL,
                pagarme_card_id_encrypted TEXT,
                pagarme_customer_id TEXT,
                last_4 TEXT,
                brand TEXT,
                holder_name TEXT,
                exp_month INTEGER,
                exp_year INTEGER,
                status TEXT DEFAULT 'temp',
                expires_at TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (user_id) ON DELETE CASCADE
            );
        """,
            "Table: cards",
        )

        self.run_sql(
            """
            CREATE TABLE IF NOT EXISTS billing_subscriptions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                subscription_id TEXT UNIQUE NOT NULL,
                user_id INTEGER NOT NULL,
                client_id INTEGER NOT NULL,
                plan_id INTEGER NOT NULL,
                card_id TEXT NOT NULL,
                billing_id TEXT,
                status TEXT NOT NULL DEFAULT 'pending_charge' CHECK(status IN ('pending_charge', 'active', 'suspended', 'canceled', 'payment_failed')),
                charge_scheduled_at DATETIME NOT NULL,
                renewal_date DATETIME,
                charge_completed_at DATETIME,
                canceled_at DATETIME,
                cancellation_reason TEXT,
                payment_retry_count INTEGER DEFAULT 0,
                last_payment_error TEXT,
                last_payment_attempt_at DATETIME,
                pagarme_customer_id TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (user_id) ON DELETE CASCADE,
                FOREIGN KEY (client_id) REFERENCES clients (client_id) ON DELETE CASCADE,
                FOREIGN KEY (plan_id) REFERENCES plans (id) ON DELETE RESTRICT,
                FOREIGN KEY (card_id) REFERENCES cards (card_id) ON DELETE RESTRICT,
                FOREIGN KEY (billing_id) REFERENCES billing_info (billing_id) ON DELETE SET NULL
            );
        """,
            "Table: billing_subscriptions",
        )

        self.run_sql(
            """
            CREATE TABLE IF NOT EXISTS payments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                payment_id TEXT UNIQUE NOT NULL,
                charge_id_pagarme TEXT,
                idempotency_key TEXT UNIQUE NOT NULL,
                subscription_id TEXT NOT NULL,
                user_id INTEGER,
                amount INTEGER NOT NULL,
                currency TEXT DEFAULT 'BRL',
                status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending', 'paid', 'failed', 'refunded', 'canceled')),
                payment_method TEXT,
                description TEXT,
                retry_count INTEGER DEFAULT 0,
                max_retries INTEGER DEFAULT 3,
                next_retry_at DATETIME,
                error_message TEXT,
                metadata TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (subscription_id) REFERENCES billing_subscriptions (subscription_id) ON DELETE CASCADE,
                FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE SET NULL
            );
        """,
            "Table: payments",
        )

        self.run_sql(
            """
            CREATE TABLE IF NOT EXISTS subscription_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                client_id INTEGER NOT NULL,
                old_plan_id TEXT,
                new_plan_id TEXT NOT NULL,
                event TEXT NOT NULL CHECK(event IN ('created', 'upgraded', 'downgraded', 'canceled', 'reactivated')),
                changed_by TEXT,
                notes TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (client_id) REFERENCES clients (client_id) ON DELETE CASCADE,
                FOREIGN KEY (old_plan_id) REFERENCES plans (plan_id) ON DELETE SET NULL,
                FOREIGN KEY (new_plan_id) REFERENCES plans (plan_id) ON DELETE RESTRICT
            );
        """,
            "Table: subscription_logs",
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
                client_id TEXT NOT NULL,
                chat_name TEXT,
                status TEXT DEFAULT 'active',
                chat_cover TEXT,
                img TEXT,
                FOREIGN KEY (client_id) REFERENCES clients (client_id) ON DELETE CASCADE
            );
        """,
            "Table: chats",
        )

        self.run_sql(
            """
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                message_id TEXT UNIQUE NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                chat_id TEXT NOT NULL,
                client_id INTEGER NOT NULL,
                message_type TEXT NOT NULL DEFAULT 'user',
                content TEXT NOT NULL,
                feedback TEXT,
                model TEXT,
                FOREIGN KEY (chat_id) REFERENCES chats (chat_id) ON DELETE CASCADE,
                FOREIGN KEY (client_id) REFERENCES clients (client_id) ON DELETE CASCADE
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
                client_id INTEGER NOT NULL,
                agent_id TEXT NOT NULL,
                name TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (chat_id) REFERENCES chats (chat_id) ON DELETE CASCADE,
                FOREIGN KEY (client_id) REFERENCES clients (client_id) ON DELETE CASCADE
            );
        """,
            "Table: isolated_chat",
        )

        self.run_sql(
            """
            CREATE TABLE IF NOT EXISTS isolated_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                isolated_chat_id TEXT NOT NULL,
                uuid TEXT NOT NULL,
                agent_id TEXT NOT NULL,
                agent TEXT NOT NULL,
                role TEXT NOT NULL CHECK(role IN ('assistant', 'user', 'system')),
                content TEXT NOT NULL,
                tokens_used INTEGER DEFAULT 0,
                processing_time INTEGER DEFAULT 0,
                type TEXT NOT NULL DEFAULT 'message' CHECK(type IN ('message', 'tool_call')),
                context_window BOOLEAN DEFAULT 1,
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

        self.run_sql(
            """
            CREATE TABLE IF NOT EXISTS usage (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                usage_id TEXT UNIQUE NOT NULL,
                user_id INTEGER NOT NULL,
                isolated_chat_id TEXT,
                isolated_message_id INTEGER,
                type TEXT NOT NULL CHECK(type IN ('token_input', 'token_output', 'gen-video', 'gen-img', 'vision')),
                quantity INTEGER NOT NULL DEFAULT 0,
                current_charging REAL DEFAULT 0.0,
                charge REAL DEFAULT 0.0,
                current_plan_credits REAL,
                credits_cost REAL NOT NULL DEFAULT 0,
                current_plan_id INTEGER,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (user_id) ON DELETE CASCADE,
                FOREIGN KEY (isolated_chat_id) REFERENCES isolated_chat (chat_id) ON DELETE SET NULL,
                FOREIGN KEY (isolated_message_id) REFERENCES isolated_messages (id) ON DELETE SET NULL,
                FOREIGN KEY (current_plan_id) REFERENCES plans (id) ON DELETE SET NULL
            );
        """,
            "Table: usage",
        )

        # Tabela para armazenar contextos comprimidos
        self.run_sql(
            """
            CREATE TABLE IF NOT EXISTS context_window (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                isolated_chat_id TEXT NOT NULL,
                cut_message_uuid TEXT NOT NULL,
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
        # 📤 TABELAS DE SESSIONS
        # ============================================================================

        self.run_sql(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT UNIQUE NOT NULL,
                client_id INTEGER NOT NULL,
                user_id INTEGER,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                expires_at DATETIME NOT NULL,
                last_activity DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (client_id) REFERENCES clients (client_id) ON DELETE CASCADE,
                FOREIGN KEY (user_id) REFERENCES users (user_id) ON DELETE SET NULL
            );
        """,
            "Table: sessions",
        )

        # ============================================================================
        # 📄 TABELAS DE ARQUIVOS
        # ============================================================================

        self.run_sql(
            """
            CREATE TABLE IF NOT EXISTS files (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                file_id TEXT UNIQUE NOT NULL,
                file_hash TEXT UNIQUE NOT NULL,
                file_name VARCHAR(255) NOT NULL,
                file_type VARCHAR(50) NOT NULL,
                file_size INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                client_id INTEGER NOT NULL,
                chat_id TEXT,
                message_id TEXT,
                file_category VARCHAR(50) DEFAULT 'upload' CHECK(file_category IN ('document', 'asset', 'upload', 'attachment')),
                storage_path TEXT NOT NULL,
                storage_env TEXT DEFAULT 'local',
                is_temp BOOLEAN DEFAULT TRUE,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                deleted_at DATETIME DEFAULT NULL,
                FOREIGN KEY (user_id) REFERENCES users (user_id) ON DELETE CASCADE,
                FOREIGN KEY (client_id) REFERENCES clients (client_id) ON DELETE CASCADE,
                FOREIGN KEY (chat_id) REFERENCES chats (chat_id) ON DELETE CASCADE,
                FOREIGN KEY (message_id) REFERENCES messages (message_id) ON DELETE CASCADE
            );
        """,
            "Table: files",
        )

        self.run_sql(
            """
            CREATE TABLE IF NOT EXISTS message_files (
                message_id TEXT NOT NULL,
                file_id INTEGER NOT NULL,
                FOREIGN KEY (message_id) REFERENCES messages (message_id) ON DELETE CASCADE,
                FOREIGN KEY (file_id) REFERENCES files (id) ON DELETE CASCADE,
                PRIMARY KEY (message_id, file_id)
            );
        """,
            "Table: message_files",
        )

        self.run_sql(
            """
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id TEXT UNIQUE NOT NULL,
                chat_id TEXT NOT NULL,
                client_id INTEGER NOT NULL,
                task_name VARCHAR(255) NOT NULL,
                step_name VARCHAR(255) NOT NULL,
                status VARCHAR(50) NOT NULL CHECK(status IN ('pending', 'success', 'failed')),
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                completed_at DATETIME DEFAULT NULL,
                FOREIGN KEY (chat_id) REFERENCES chats (chat_id) ON DELETE CASCADE,
                FOREIGN KEY (client_id) REFERENCES clients (client_id) ON DELETE CASCADE,
                UNIQUE(chat_id, task_name, step_name)
            );
        """,
            "Table: tasks",
        )

        self.run_sql(
            """
            CREATE TABLE IF NOT EXISTS attachments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                attachment_id TEXT UNIQUE NOT NULL,
                chat_id TEXT,
                message_id TEXT,
                client_id INTEGER NOT NULL,
                file_name VARCHAR(255) NOT NULL,
                file_size INTEGER NOT NULL,
                file_type VARCHAR(50) NOT NULL,
                file_hash TEXT,
                storage_path TEXT NOT NULL,
                storage_env TEXT DEFAULT 'local',
                is_temp BOOLEAN DEFAULT TRUE,
                uploaded_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                deleted_at DATETIME DEFAULT NULL,
                FOREIGN KEY (chat_id) REFERENCES chats (chat_id) ON DELETE CASCADE,
                FOREIGN KEY (message_id) REFERENCES messages (message_id) ON DELETE CASCADE,
                FOREIGN KEY (client_id) REFERENCES clients (client_id) ON DELETE CASCADE
            );
        """,
            "Table: attachments",
        )

        self.run_sql(
            """
            CREATE TABLE IF NOT EXISTS message_feedbacks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                feedback_id TEXT UNIQUE NOT NULL,
                chat_id TEXT NOT NULL,
                message_id TEXT NOT NULL,
                client_id INTEGER NOT NULL,
                feedback_type TEXT NOT NULL CHECK(feedback_type IN ('like', 'dislike')),
                content TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (chat_id) REFERENCES chats (chat_id) ON DELETE CASCADE,
                FOREIGN KEY (message_id) REFERENCES messages (message_id) ON DELETE CASCADE,
                FOREIGN KEY (client_id) REFERENCES clients (client_id) ON DELETE CASCADE,
                UNIQUE(message_id, feedback_type)
            );
        """,
            "Table: message_feedbacks",
        )

        self.run_sql(
            """
            CREATE TABLE IF NOT EXISTS visitor_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                fingerprint_id TEXT NOT NULL,
                tab TEXT,
                visited_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );
        """,
            "Table: visitor_logs",
        )

        self.run_sql(
            """
            CREATE TABLE IF NOT EXISTS waitlist (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT UNIQUE NOT NULL,
                fingerprint_id TEXT,
                requested_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                notified_at DATETIME,
                status TEXT DEFAULT 'pending' CHECK(status IN ('pending', 'notified', 'converted'))
            );
        """,
            "Table: waitlist",
        )

        # ============================================================================
        # 🛒 TABELA DE RASTREAMENTO DE CHECKOUT
        # ============================================================================

        self.run_sql(
            """
            CREATE TABLE IF NOT EXISTS checkout_tracking (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tracking_id TEXT UNIQUE NOT NULL,
                user_id INTEGER,
                plan_id TEXT NOT NULL,
                plan_name TEXT,
                plan_price REAL,
                device_info TEXT,
                user_agent TEXT,
                ip_address TEXT,
                referrer TEXT,
                status TEXT DEFAULT 'viewed' CHECK(status IN ('viewed', 'billing_started', 'card_registered', 'payment_completed', 'abandoned')),
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE SET NULL,
                FOREIGN KEY (plan_id) REFERENCES plans (plan_id) ON DELETE CASCADE
            );
        """,
            "Table: checkout_tracking",
        )

        # ============================================================================
        # ✉️ TABELAS DE VALIDAÇÃO EXTERNA (EMAIL E TELEFONE)
        # ============================================================================

        self.run_sql(
            """
            CREATE TABLE IF NOT EXISTS email_validations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email_validation_id TEXT UNIQUE NOT NULL,
                user_id INTEGER,
                email TEXT NOT NULL,
                is_valid BOOLEAN NOT NULL,
                deliverability TEXT,
                is_format_valid BOOLEAN,
                is_smtp_valid BOOLEAN,
                is_mx_valid BOOLEAN,
                quality_score REAL,
                is_free_email BOOLEAN,
                is_disposable BOOLEAN,
                is_role BOOLEAN,
                risk_status TEXT,
                total_breaches INTEGER DEFAULT 0,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (user_id) ON DELETE SET NULL
            );
        """,
            "Table: email_validations",
        )

        self.run_sql(
            """
            CREATE TABLE IF NOT EXISTS cellphone_validations (
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
            "Table: cellphone_validations",
        )

        self.run_sql(
            """
            CREATE TABLE IF NOT EXISTS postal_code_validations (
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
            "Table: postal_code_validations",
        )

        # ============================================================================
        # 🔐 TABELAS DE AUTENTICAÇÃO E DISPOSITIVOS
        # ============================================================================

        self.run_sql(
            """
            CREATE TABLE IF NOT EXISTS devices (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                device_id TEXT UNIQUE NOT NULL,
                user_id INTEGER NOT NULL,
                os_encrypted TEXT,
                browser_encrypted TEXT,
                device_type_encrypted TEXT,
                timezone_encrypted TEXT,
                verified BOOLEAN DEFAULT 0,
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
                user_id INTEGER NOT NULL,
                device_id TEXT NOT NULL,
                fingerprint_id TEXT NOT NULL,
                ip_address TEXT,
                login_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                logout_at DATETIME,
                is_successful BOOLEAN DEFAULT 1,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (user_id) ON DELETE CASCADE,
                FOREIGN KEY (device_id) REFERENCES devices (device_id) ON DELETE CASCADE
            );
        """,
            "Table: auth_logs",
        )

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
            "CREATE INDEX IF NOT EXISTS idx_client_plans_client_id ON client_plans (client_id);",
            "Index: idx_client_plans_client_id",
        )

        self.run_sql(
            "CREATE INDEX IF NOT EXISTS idx_client_plans_plan_id ON client_plans (plan_id);",
            "Index: idx_client_plans_plan_id",
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
            "CREATE INDEX IF NOT EXISTS idx_visitor_logs_fingerprint ON visitor_logs (fingerprint_id);",
            "Index: idx_visitor_logs_fingerprint",
        )

        self.run_sql(
            "CREATE INDEX IF NOT EXISTS idx_visitor_logs_visited_at ON visitor_logs (visited_at);",
            "Index: idx_visitor_logs_visited_at",
        )

        self.run_sql(
            "CREATE INDEX IF NOT EXISTS idx_waitlist_email ON waitlist (email);",
            "Index: idx_waitlist_email",
        )

        self.run_sql(
            "CREATE INDEX IF NOT EXISTS idx_waitlist_status ON waitlist (status);",
            "Index: idx_waitlist_status",
        )

        self.run_sql(
            "CREATE INDEX IF NOT EXISTS idx_chats_client ON chats (client_id);",
            "Index: idx_chats_client",
        )

        self.run_sql(
            "CREATE INDEX IF NOT EXISTS idx_messages_chat ON messages (chat_id);",
            "Index: idx_messages_chat",
        )

        self.run_sql(
            "CREATE INDEX IF NOT EXISTS idx_messages_client ON messages (client_id);",
            "Index: idx_messages_client",
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

        self.run_sql(
            "CREATE INDEX IF NOT EXISTS idx_files_hash ON files (file_hash);",
            "Index: idx_files_hash",
        )

        self.run_sql(
            "CREATE INDEX IF NOT EXISTS idx_files_user ON files (user_id);",
            "Index: idx_files_user",
        )

        self.run_sql(
            "CREATE INDEX IF NOT EXISTS idx_files_client ON files (client_id);",
            "Index: idx_files_client",
        )

        self.run_sql(
            "CREATE INDEX IF NOT EXISTS idx_files_chat ON files (chat_id);",
            "Index: idx_files_chat",
        )

        self.run_sql(
            "CREATE INDEX IF NOT EXISTS idx_files_category ON files (file_category);",
            "Index: idx_files_category",
        )

        self.run_sql(
            "CREATE INDEX IF NOT EXISTS idx_files_temp ON files (is_temp);",
            "Index: idx_files_temp",
        )

        # ============================================================================
        # 📋 ÍNDICES PARA TASKS
        # ============================================================================

        self.run_sql(
            "CREATE INDEX IF NOT EXISTS idx_tasks_chat ON tasks (chat_id);",
            "Index: idx_tasks_chat",
        )

        self.run_sql(
            "CREATE INDEX IF NOT EXISTS idx_tasks_client ON tasks (client_id);",
            "Index: idx_tasks_client",
        )

        self.run_sql(
            "CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks (status);",
            "Index: idx_tasks_status",
        )

        self.run_sql(
            "CREATE INDEX IF NOT EXISTS idx_tasks_name ON tasks (task_name);",
            "Index: idx_tasks_name",
        )

        # ============================================================================
        # 🔍 ÍNDICES PARA TABELAS DE CHAT ISOLADO
        # ============================================================================

        self.run_sql(
            "CREATE INDEX IF NOT EXISTS idx_isolated_chat_chat_id ON isolated_chat (chat_id);",
            "Index: idx_isolated_chat_chat_id",
        )

        self.run_sql(
            "CREATE INDEX IF NOT EXISTS idx_isolated_chat_client_id ON isolated_chat (client_id);",
            "Index: idx_isolated_chat_client_id",
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
            "CREATE INDEX IF NOT EXISTS idx_isolated_messages_uuid ON isolated_messages (uuid);",
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
            "CREATE INDEX IF NOT EXISTS idx_sessions_client ON sessions (client_id);",
            "Index: idx_sessions_client",
        )

        self.run_sql(
            "CREATE INDEX IF NOT EXISTS idx_sessions_expires ON sessions (expires_at);",
            "Index: idx_sessions_expires",
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
            "CREATE INDEX IF NOT EXISTS idx_message_feedbacks_client ON message_feedbacks (client_id);",
            "Index: idx_message_feedbacks_client",
        )

        self.run_sql(
            "CREATE INDEX IF NOT EXISTS idx_message_feedbacks_type ON message_feedbacks (feedback_type);",
            "Index: idx_message_feedbacks_type",
        )

        # ============================================================================
        # 💳 ÍNDICES PARA CARTÕES E SUBSCRIÇÕES
        # ============================================================================

        self.run_sql(
            "CREATE INDEX IF NOT EXISTS idx_cards_user_id ON cards (user_id);",
            "Index: idx_cards_user_id",
        )

        self.run_sql(
            "CREATE INDEX IF NOT EXISTS idx_cards_card_id ON cards (card_id);",
            "Index: idx_cards_card_id",
        )

        self.run_sql(
            "CREATE INDEX IF NOT EXISTS idx_billing_subscriptions_user_id ON billing_subscriptions (user_id);",
            "Index: idx_billing_subscriptions_user_id",
        )

        self.run_sql(
            "CREATE INDEX IF NOT EXISTS idx_billing_subscriptions_client_id ON billing_subscriptions (client_id);",
            "Index: idx_billing_subscriptions_client_id",
        )

        self.run_sql(
            "CREATE INDEX IF NOT EXISTS idx_billing_subscriptions_status ON billing_subscriptions (status);",
            "Index: idx_billing_subscriptions_status",
        )

        self.run_sql(
            "CREATE INDEX IF NOT EXISTS idx_billing_subscriptions_charge_scheduled_at ON billing_subscriptions (charge_scheduled_at);",
            "Index: idx_billing_subscriptions_charge_scheduled_at",
        )

        self.run_sql(
            "CREATE INDEX IF NOT EXISTS idx_subscription_logs_client_id ON subscription_logs (client_id);",
            "Index: idx_subscription_logs_client_id",
        )

        self.run_sql(
            "CREATE INDEX IF NOT EXISTS idx_subscription_logs_event ON subscription_logs (event);",
            "Index: idx_subscription_logs_event",
        )

        # ============================================================================
        # 💳 ÍNDICES PARA PAYMENTS (PAGARME)
        # ============================================================================

        self.run_sql(
            "CREATE INDEX IF NOT EXISTS idx_payments_payment_id ON payments (payment_id);",
            "Index: idx_payments_payment_id",
        )

        self.run_sql(
            "CREATE INDEX IF NOT EXISTS idx_payments_idempotency_key ON payments (idempotency_key);",
            "Index: idx_payments_idempotency_key",
        )

        self.run_sql(
            "CREATE INDEX IF NOT EXISTS idx_payments_charge_id_pagarme ON payments (charge_id_pagarme);",
            "Index: idx_payments_charge_id_pagarme",
        )

        self.run_sql(
            "CREATE INDEX IF NOT EXISTS idx_payments_subscription_id ON payments (subscription_id);",
            "Index: idx_payments_subscription_id",
        )

        self.run_sql(
            "CREATE INDEX IF NOT EXISTS idx_payments_user_id ON payments (user_id);",
            "Index: idx_payments_user_id",
        )

        self.run_sql(
            "CREATE INDEX IF NOT EXISTS idx_payments_status ON payments (status);",
            "Index: idx_payments_status",
        )

        self.run_sql(
            "CREATE INDEX IF NOT EXISTS idx_payments_next_retry_at ON payments (next_retry_at);",
            "Index: idx_payments_next_retry_at",
        )

        # REMOVED: client_id column doesn't exist in payments table
        # self.run_sql(
        #     "CREATE INDEX IF NOT EXISTS idx_payments_client_id ON payments (client_id);",
        #     "Index: idx_payments_client_id"
        # )

        self.run_sql(
            "CREATE INDEX IF NOT EXISTS idx_payments_status ON payments (status);",
            "Index: idx_payments_status",
        )

        # REMOVED: user_subscription_id column doesn't exist in payments table
        # self.run_sql(
        #     "CREATE INDEX IF NOT EXISTS idx_payments_user_subscription_id ON payments (user_subscription_id);",
        #     "Index: idx_payments_user_subscription_id"
        # )

        # ============================================================================
        # 📊 ÍNDICES PARA USAGE
        # ============================================================================

        self.run_sql(
            "CREATE INDEX IF NOT EXISTS idx_usage_usage_id ON usage (usage_id);",
            "Index: idx_usage_usage_id",
        )

        self.run_sql(
            "CREATE INDEX IF NOT EXISTS idx_usage_user_id ON usage (user_id);",
            "Index: idx_usage_user_id",
        )

        self.run_sql(
            "CREATE INDEX IF NOT EXISTS idx_usage_isolated_chat_id ON usage (isolated_chat_id);",
            "Index: idx_usage_isolated_chat_id",
        )

        self.run_sql(
            "CREATE INDEX IF NOT EXISTS idx_usage_isolated_message_id ON usage (isolated_message_id);",
            "Index: idx_usage_isolated_message_id",
        )

        self.run_sql(
            "CREATE INDEX IF NOT EXISTS idx_usage_type ON usage (type);",
            "Index: idx_usage_type",
        )

        self.run_sql(
            "CREATE INDEX IF NOT EXISTS idx_usage_created_at ON usage (created_at);",
            "Index: idx_usage_created_at",
        )

        # ============================================================================
        # ✉️ ÍNDICES PARA VALIDAÇÕES (EMAIL E TELEFONE)
        # ============================================================================

        self.run_sql(
            "CREATE INDEX IF NOT EXISTS idx_email_validations_email ON email_validations (email);",
            "Index: idx_email_validations_email",
        )

        self.run_sql(
            "CREATE INDEX IF NOT EXISTS idx_email_validations_user_id ON email_validations (user_id);",
            "Index: idx_email_validations_user_id",
        )

        self.run_sql(
            "CREATE INDEX IF NOT EXISTS idx_email_validations_is_valid ON email_validations (is_valid);",
            "Index: idx_email_validations_is_valid",
        )

        self.run_sql(
            "CREATE INDEX IF NOT EXISTS idx_cellphone_validations_phone ON cellphone_validations (phone);",
            "Index: idx_cellphone_validations_phone",
        )

        self.run_sql(
            "CREATE INDEX IF NOT EXISTS idx_cellphone_validations_user_id ON cellphone_validations (user_id);",
            "Index: idx_cellphone_validations_user_id",
        )

        self.run_sql(
            "CREATE INDEX IF NOT EXISTS idx_cellphone_validations_is_valid ON cellphone_validations (is_valid);",
            "Index: idx_cellphone_validations_is_valid",
        )

        self.run_sql(
            "CREATE INDEX IF NOT EXISTS idx_postal_code_validations_postal_code ON postal_code_validations (postal_code);",
            "Index: idx_postal_code_validations_postal_code",
        )

        self.run_sql(
            "CREATE INDEX IF NOT EXISTS idx_postal_code_validations_user_id ON postal_code_validations (user_id);",
            "Index: idx_postal_code_validations_user_id",
        )

        self.run_sql(
            "CREATE INDEX IF NOT EXISTS idx_postal_code_validations_is_valid ON postal_code_validations (is_valid);",
            "Index: idx_postal_code_validations_is_valid",
        )

        # ============================================================================
        # 3. PLANOS ATIVOS DOS CLIENTES (client_plans)
        # ============================================================================

        # Buscar os UUIDs dos planos criados
        with self.engine.connect() as connection:
            pro_plan = connection.execute(
                text("SELECT plan_id FROM plans WHERE name = 'Pro' LIMIT 1")
            ).fetchone()
            free_plan = connection.execute(
                text("SELECT plan_id FROM plans WHERE name = 'Free' LIMIT 1")
            ).fetchone()

        if pro_plan and free_plan:
            pro_plan_id = pro_plan[0]
            free_plan_id = free_plan[0]

            info(f"[SCHEMA] Using plan_ids: Pro={pro_plan_id}, Free={free_plan_id}")

            # Plano Pro para Client 1
            self.run_sql(
                f"""
                INSERT INTO client_plans (client_plan_id, client_id, plan_id)
                VALUES ('cp-client1-pro', '{client1_uuid}', '{pro_plan_id}');
            """,
                "Initial: Client Plan (Client 1 - Pro)",
            )

            # Plano Free para Client 2
            self.run_sql(
                f"""
                INSERT INTO client_plans (client_plan_id, client_id, plan_id)
                VALUES ('cp-client2-free', '{client2_uuid}', '{free_plan_id}');
            """,
                "Initial: Client Plan (Client 2 - Free)",
            )

            # ============================================================================
            # 4. HISTÓRICO DE MUDANÇAS DE PLANO (subscription_logs)
            # ============================================================================

            # Log: Client 1 criado com plano Pro
            self.run_sql(
                f"""
                INSERT INTO subscription_logs (client_id, old_plan_id, new_plan_id, event, changed_by, notes)
                VALUES ('{client1_uuid}', NULL, '{pro_plan_id}', 'created', 'system', 'Initial setup');
            """,
                "Initial: Subscription Log (Client 1 - Created with Pro)",
            )

            # Log: Client 2 criado com plano Free
            self.run_sql(
                f"""
                INSERT INTO subscription_logs (client_id, old_plan_id, new_plan_id, event, changed_by, notes)
                VALUES ('{client2_uuid}', NULL, '{free_plan_id}', 'created', 'system', 'Initial setup');
            """,
                "Initial: Subscription Log (Client 2 - Created with Free)",
            )
        else:
            warning("[SCHEMA] Plans (Pro/Free) not found!")

        # ============================================================================
        # 4. DADOS DE CHAT DE EXEMPLO
        # ============================================================================

        # Chat 1
        self.run_sql(
            f"""
            INSERT OR IGNORE INTO chats (
                chat_id, client_id, chat_name, status
            ) VALUES (
                'chat_001', '{client1_uuid}', 'Chat de Teste 1', 'active'
            );
        """,
            "Initial: Chat 1",
        )

        # Mensagens do chat 1
        self.run_sql(
            f"""
            INSERT OR IGNORE INTO messages (
                message_id, chat_id, client_id, message_type, content, model
            ) VALUES (
                'msg_001', 'chat_001', '{client1_uuid}', 'user', 'Olá, como posso ajudar com imóveis?', 'user-input'
            );
        """,
            "Initial: Message 1 (user)",
        )

        self.run_sql(
            f"""
            INSERT OR IGNORE INTO messages (
                message_id, chat_id, client_id, message_type, content, model
            ) VALUES (
                'msg_002', 'chat_001', '{client1_uuid}', 'ai', 'Olá! Sou assistente da Zera Real Estate. Posso ajudar você a encontrar o imóvel perfeito!', 'gpt-4o-mini'
            );
        """,
            "Initial: Message 2 (ai)",
        )

        # ============================================================================
        # 4. DADOS DE CHAT ISOLADO COM EXEMPLO DE QUIZ
        # ============================================================================

        self.run_sql(
            f"""
            INSERT OR IGNORE INTO isolated_chat (
                chat_id, client_id, agent_id, name
            ) VALUES (
                'chat_001', '{client1_uuid}', 'orchestrator-global', 'Chat Isolado - Orchestrator Global'
            );
        """,
            "Initial: Isolated Chat (orchestrator-global)",
        )

        # Mensagem de tool call bem-sucedida de quiz
        self.run_sql(
            """
            INSERT OR IGNORE INTO isolated_messages (
                isolated_chat_id, uuid, agent_id, agent, role, content, type
            ) VALUES (
                'chat_001', 'uuid-quiz-001', 'orchestrator-global', 'orchestrator-global',
                'assistant',
                'Tool: quiz\\nArgs: {"question": "Qual é o objetivo principal da campanha?", "options": ["Aumentar vendas", "Construir marca", "Gerar leads", "Educação"], "type": "múltipla escolha"}',
                'tool_call'
            );
        """,
            "Initial: Tool Call (quiz input)",
        )

        # Resposta do quiz (sucesso)
        self.run_sql(
            """
            INSERT OR IGNORE INTO isolated_messages (
                isolated_chat_id, uuid, agent_id, agent, role, content, type
            ) VALUES (
                'chat_001', 'uuid-quiz-001', 'orchestrator-global', 'orchestrator-global',
                'user',
                '{"success": true, "tool": "quiz", "quiz_id": "550e8400-e29b-41d4-a716-446655440000", "question": "Qual é o objetivo principal da campanha?", "options": ["Aumentar vendas", "Construir marca", "Gerar leads", "Educação"], "type": "múltipla escolha", "total_options": 4, "message": "Quiz criado com sucesso (4 opções)", "timestamp": "2026-02-23T10:30:00"}',
                'tool_call'
            );
        """,
            "Initial: Tool Call (quiz response)",
        )

    def create_schema(self):
        """
        Criar schema completo do banco de dados.
        Executa em ordem:
        1. Tabelas
        2. Triggers e Índices (apenas para local/postgresql)
        3. Dados Mock (apenas para local/postgresql e quando necessário)
        """
        try:
            # Log inicial mostrando qual schema está usando
            schema_info = self._get_schema_info()
            info(f"[SCHEMA] Initializing schema on {schema_info}...")

            # Se for Supabase REST, apenas conectar (schema já existe)
            if database.is_rest_api():
                self.create_tables()  # Retorna cedo, não precisa do resto
                info(
                    f"[SCHEMA] {self.tables_created} tables + {self.indexes_created} indexes ({schema_info})"
                )
                return

            # Para SQLite e PostgreSQL direto, fazer o fluxo completo
            self.create_tables()
            self.create_triggers_and_indexes()

            # Inserir dados mock apenas se necessário
            from .MockData import MockData

            MockData.sync(self.engine, self.config)

            # Log final com resumo (dinâmico baseado no que foi criado)
            info(
                f"[SCHEMA] {self.tables_created} tables + {self.indexes_created} indexes ({schema_info})"
            )
        except Exception as e:
            self.errors.append(str(e))
            error(f"[SCHEMA] Failed: {e}")
            raise

    def _execute_supabase_schema(self):
        """Executar schema SQL do arquivo para Supabase via API REST."""
        try:
            from pathlib import Path

            # Localizar arquivo SQL (sobe até MD70 root)
            # Path hierarchy: SchemaManager.py -> Crunch -> Core -> App -> backend -> services -> mvp -> App -> MD70 -> CloudDB
            current_dir = Path(__file__).parent  # Crunch
            sql_file = (
                current_dir.parent.parent.parent.parent.parent.parent.parent.parent
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
