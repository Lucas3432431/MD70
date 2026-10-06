"""
Configuração e inicialização do banco de dados SQL.
"""

import os
from pathlib import Path
from sqlalchemy import create_engine, text, event
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.pool import StaticPool

from App.Core.Settings import load_config
from App.Core.Logs import debug, info, warning, critical

Base = declarative_base()


class DummySession:
    """Sessão dummy para REST API - simula SQLAlchemy Session sem fazer nada."""

    def __init__(self, engine=None):
        self.engine = engine

    def query(self, *args, **kwargs):
        """Retorna um objeto que sempre retorna vazio."""
        return DummyQuery()

    def execute(self, *args, **kwargs):
        """Retorna um objeto que sempre retorna vazio."""
        return DummyResult()

    def add(self, *args, **kwargs):
        """No-op para REST API."""
        pass

    def commit(self):
        """No-op para REST API."""
        pass

    def rollback(self):
        """No-op para REST API."""
        pass

    def refresh(self, *args, **kwargs):
        """No-op para REST API."""
        pass

    def close(self):
        """No-op para REST API."""
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


class DummyRow:
    """Row dummy que pode ser convertida para dict."""

    def __init__(self):
        self._mapping = {}

    def __iter__(self):
        return iter([])

    def keys(self):
        return []


class DummyQuery:
    """Query dummy que sempre retorna vazio."""

    def filter(self, *args, **kwargs):
        return self

    def first(self):
        return None

    def all(self):
        return []

    def scalar(self):
        return None

    def count(self):
        return 0


class DummyResult:
    """Result dummy que sempre retorna vazio."""

    def first(self):
        return None

    def fetchone(self):
        return None

    def fetchall(self):
        return []

    def close(self):
        pass


class Database:
    """Gerenciador de conexão com banco de dados."""

    def __init__(self):
        self.engine = None
        self.SessionLocal = None
        self.initialized = False
        self.db_env = "local"  # local, cloud-tcp, cloud-rest (configurado durante init)
        self.db_type = "local"  # Tipo efetivo de conexão: local, cloud-tcp, cloud-rest, sqlite-fallback
        self.config = None
        self.schema = "public"  # Schema padrão

    def initialize(self) -> bool:
        """Inicializar conexão com banco de dados.

        Em modo HYBRID (DB_ENV=cloud-rest ou cloud-tcp):
        - SEMPRE usa SQLite local para leitura/escrita
        - DB_ENV é apenas um FLAG para sincronização com cloud

        Em modo LOCAL:
        - Usa apenas SQLite local
        """
        try:
            # Carregar configuração
            self.config = load_config()
            db_env_config = self.config.get("db_env", "local").lower()

            # VALIDAÇÃO: DB_ENV must be one of: local, cloud-rest, cloud-tcp
            valid_db_envs = ["local", "cloud-rest", "cloud-tcp", "sqlite-fallback"]
            if db_env_config not in valid_db_envs:
                critical(
                    f"[FATAL] Invalid DB_ENV='{db_env_config}'. Must be one of: {', '.join(valid_db_envs)}"
                )
                raise ValueError(f"Invalid DB_ENV: {db_env_config}")

            # EM MODO HYBRID: SEMPRE usar banco LOCAL
            # DB_ENV é apenas um flag para sincronização, não para roteamento de operações
            result = self._initialize_local()

            # Atualizar config global com DB_ENV efetivo após inicialização
            if result:
                self.update_config_db_env()

            return result

        except Exception as e:
            critical(f"Database initialization failed: {e}")
            return False

    def _initialize_local(self) -> bool:
        """Inicializar conexão com SQLite local com WAL e BusyTimeout."""
        try:
            # Configurar diretório do banco de dados
            # __file__ = App/Core/Crunch/TablesSQL/Database.py
            # parent(5) = backend raiz
            base_dir = Path(__file__).parent.parent.parent.parent.parent.absolute()
            db_dir = base_dir / "Data" / "Database"
            db_dir.mkdir(parents=True, exist_ok=True)

            db_path = db_dir / "MD70.db"
            database_url = f"sqlite:///{db_path}"

            # Criar engine SQLite com timeouts e pool maior
            self.engine = create_engine(
                database_url,
                connect_args={
                    "check_same_thread": False,
                    "timeout": 30,  # BusyTimeout: 30 segundos
                },
                pool_size=20,
                max_overflow=40,
                pool_pre_ping=True,
                echo=False,
            )

            # Configurar WAL (Write-Ahead Logging) e outras otimizações
            @event.listens_for(self.engine, "connect")
            def set_sqlite_pragmas(dbapi_conn, connection_record):
                cursor = dbapi_conn.cursor()
                # WAL: Melhora concorrência
                cursor.execute("PRAGMA journal_mode=WAL")
                # Sincronização: NORMAL é mais rápido que FULL mas mais seguro que OFF
                cursor.execute("PRAGMA synchronous=NORMAL")
                # Cache: 10000 páginas (~160MB)
                cursor.execute("PRAGMA cache_size=10000")
                # Busy timeout: 30000ms (30 segundos)
                cursor.execute("PRAGMA busy_timeout=30000")
                # Foreign keys: ativados
                cursor.execute("PRAGMA foreign_keys=ON")
                cursor.close()
                # debug("[SQLite] WAL, NORMAL sync, and BusyTimeout(30s) configured")

            # Criar session factory
            self.SessionLocal = sessionmaker(
                autocommit=False, autoflush=False, bind=self.engine
            )

            # Testar conexão
            self._test_connection()

            self.initialized = True
            self.db_type = "local"
            self.db_env = "local"
            info(
                f"Database connection initialized (SQLite local with WAL: {db_path.relative_to(base_dir)})"
            )
            return True

        except Exception as e:
            critical(f"SQLite initialization failed: {e}")
            return False

    def _initialize_cloud(self) -> bool:
        """Inicializar conexão com Supabase: PostgreSQL → API REST → SQLite."""
        try:
            supabase_url = self.config.get("supabase_url", "")
            supabase_key = self.config.get("supabase_key", "")

            if not supabase_url or not supabase_key:
                warning("[CLOUD] Supabase credentials not configured. Using SQLite.")
                return self._initialize_local()

            # Determinar schema baseado em ENVIRONMENT
            environment = self.config.get("dev_env", False)
            self.schema = "dev_schema" if environment else "prod_schema"

            # Extrair project_id da URL do Supabase
            if "supabase.co" not in supabase_url:
                warning("[CLOUD] Invalid Supabase URL. Using SQLite.")
                return self._initialize_local()

            project_id = supabase_url.split("//")[1].split(".")[0]

            # Verificar preferência de conexão especificada no .env
            db_env_config = self.config.get("db_env", "local").lower()
            force_rest = db_env_config == "cloud-rest"
            force_tcp = db_env_config == "cloud-tcp"

            # ===================================================================
            # TENTATIVA 1: PostgreSQL direto (a menos que force_rest esteja ativo)
            # ===================================================================
            database_url = self.config.get("supabase_database_url", "")

            if not database_url and not force_rest:
                db_password = self.config.get(
                    "supabase_db_password", ""
                ) or os.environ.get("SUPABASE_DB_PASSWORD", "")
                if db_password:
                    database_url = f"postgresql://postgres:{db_password}@db.{project_id}.supabase.co:5432/postgres?options=-c%20search_path%3D{self.schema}"

            if database_url and not force_rest:
                try:
                    self.engine = create_engine(
                        database_url,
                        pool_size=20,
                        max_overflow=40,
                        pool_recycle=300,
                        pool_pre_ping=True,
                        echo=False,
                    )

                    @event.listens_for(self.engine, "connect")
                    def set_search_path(dbapi_conn, connection_record):
                        cursor = dbapi_conn.cursor()
                        cursor.execute(f"SET search_path TO {self.schema}")
                        cursor.close()

                    self.SessionLocal = sessionmaker(
                        autocommit=False, autoflush=False, bind=self.engine
                    )
                    self._test_connection()

                    self.initialized = True
                    self.db_type = "cloud-tcp"
                    self.db_env = "cloud-tcp"
                    info(f"[CLOUD] Connected to PostgreSQL (schema: {self.schema})")
                    return True
                except Exception:
                    pass  # Continua para API REST

            # ===================================================================
            # TENTATIVA 2: API REST do Supabase (a menos que force_tcp esteja ativo)
            # ===================================================================
            if not force_tcp:
                try:
                    result = self._initialize_supabase_rest(
                        supabase_url, supabase_key, project_id
                    )
                    if result:
                        return True
                except Exception:
                    pass  # Continua para SQLite

            # ===================================================================
            # TENTATIVA 3: SQLite (fallback final)
            # ===================================================================
            warning("[CLOUD] Cloud connection failed. Falling back to SQLite.")
            result = self._initialize_local()
            if result:
                self.db_env = "sqlite-fallback"
                self.db_type = "sqlite-fallback"
            return result

        except Exception as e:
            warning(f"[CLOUD] Initialization failed: {e}")
            return self._initialize_local()

    def _initialize_supabase_rest(
        self, supabase_url: str, supabase_key: str, project_id: str
    ) -> bool:
        """Inicializar conexão com API REST do Supabase usando supabase-py."""
        try:
            from supabase import create_client

            # Criar cliente Supabase
            supabase = create_client(supabase_url, supabase_key)

            # Armazenar cliente Supabase no engine
            self.engine = supabase
            self.db_type = "cloud-rest"
            self.db_env = "cloud-rest"

            # Criar uma factory de DummySession para REST API
            self.SessionLocal = lambda: DummySession(self.engine)

            self.initialized = True

            info(f"[CLOUD] Connected to REST API (schema: {self.schema})")
            return True

        except ImportError:
            warning("[CLOUD] Supabase library not installed. Use: pip install supabase")
            return False
        except Exception as e:
            return False

    def _test_connection(self):
        """Testar conexão com o banco de dados."""
        with self.engine.connect() as connection:
            connection.execute(text("SELECT 1"))

    def get_session(self) -> Session:
        """Obter nova sessão de banco de dados."""
        if not self.initialized:
            self.initialize()
        return self.SessionLocal()

    def get_db_env(self) -> str:
        """Obter ambiente do banco de dados (local, cloud-tcp, cloud-rest, sqlite-fallback)."""
        if not self.initialized:
            self.initialize()
        return self.db_env

    def get_db_type(self) -> str:
        """Obter tipo efetivo de conexão do banco de dados."""
        if not self.initialized:
            self.initialize()
        return self.db_type

    def get_schema(self) -> str:
        """Obter schema atual do banco de dados."""
        if not self.initialized:
            self.initialize()
        return self.schema

    def is_cloud(self) -> bool:
        """Verificar se está usando banco de dados cloud (TCP ou REST)."""
        db_env = self.get_db_env()
        return db_env in ["cloud-tcp", "cloud-rest"]

    def is_local(self) -> bool:
        """Verificar se está usando banco de dados local (SQLite)."""
        db_env = self.get_db_env()
        return db_env in ["local", "sqlite-fallback"]

    def is_rest_api(self) -> bool:
        """Verificar se está usando REST API do Supabase."""
        return self.get_db_env() == "cloud-rest"

    def update_config_db_env(self) -> None:
        """Atualizar a configuração global com o DB_ENV efetivo após inicialização."""
        if self.initialized and self.config:
            self.config["db_env"] = self.db_env

    def create_tables(self):
        """Criar todas as tabelas definidas nos modelos."""
        if not self.initialized:
            self.initialize()

        # Importar modelos para garantir que são registrados
        from App.Core.Crunch.TablesSQL.Models import Base as ModelsBase

        ModelsBase.metadata.create_all(bind=self.engine)
        info("Database tables created/verified")

    def drop_tables(self):
        """Remover todas as tabelas (apenas para desenvolvimento)."""
        if not self.initialized:
            self.initialize()

        from App.Core.Crunch.TablesSQL.Models import Base as ModelsBase

        ModelsBase.metadata.drop_all(bind=self.engine)
        warning("All database tables dropped")


# Instância global do banco de dados
database = Database()
