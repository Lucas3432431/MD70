"""
StorageManager.py - Gerencia storage de arquivos local ou cloud (Supabase)
Cria estrutura de pastas por client_id e chat_uuid
"""

from pathlib import Path
from typing import Optional
from App.Core.Logs import debug, error
from App.Core.Settings import load_config


class StorageManager:
    """Gerencia storage de arquivos para uploads, criação de documentos e tasks"""

    # Storage paths - Data/Database
    LOCAL_STORAGE_BASE = (
        Path(__file__).parent.parent.parent.parent / "Data" / "Database"
    )
    # Project root (services/backend)
    PROJECT_ROOT = Path(__file__).parent.parent.parent.parent

    @staticmethod
    def get_relative_path(abs_path) -> str:
        """
        Converte caminho absoluto para relativo a partir da raiz do projeto

        Args:
            abs_path: Caminho absoluto (str ou Path)

        Returns:
            Caminho relativo a partir da raiz do projeto (services/backend)
        """
        try:
            abs_path = Path(abs_path)
            rel_path = abs_path.relative_to(StorageManager.PROJECT_ROOT)
            return str(rel_path)
        except ValueError:
            # Se não for relativo ao projeto, retorna como string
            return str(abs_path)

    @staticmethod
    def get_storage_type() -> str:
        """Retorna o tipo de storage: 'local' ou 'cloud' (Supabase)"""
        config = load_config()
        db_env = config.get("db_env", "local").lower()
        return "cloud" if db_env.startswith("cloud-") else "local"

    @staticmethod
    def get_schema() -> str:
        """Retorna o schema do banco de dados baseado no environment"""
        config = load_config()
        dev_env = config.get("dev_env", False)
        return "dev_schema" if dev_env else "prod_schema"

    @staticmethod
    def get_client_chat_path(client_id: int, chat_uuid: str) -> Path:
        """
        Retorna o caminho base para um cliente + chat

        Estrutura:
        - Local: Data/Database/client_{client_id}/chat_{chat_uuid}/
        - Cloud: Usa Supabase (retorna Path virtual para referência)

        Args:
            client_id: ID do cliente
            chat_uuid: UUID do chat

        Returns:
            Path com a localização base
        """
        storage_type = StorageManager.get_storage_type()

        if storage_type == "local":
            base_path = (
                StorageManager.LOCAL_STORAGE_BASE
                / f"client_{client_id}"
                / f"chat_{chat_uuid}"
            )
            return base_path
        else:
            # Cloud: retorna path virtual para referência (Supabase faz o armazenamento)
            return Path(f"cloud://client_{client_id}/chat_{chat_uuid}")

    @staticmethod
    def ensure_path_exists(path: Path) -> bool:
        """
        Cria pasta se não existir (apenas para local storage)

        Args:
            path: Caminho a criar

        Returns:
            True se sucesso, False se falhar
        """
        storage_type = StorageManager.get_storage_type()

        if storage_type == "local":
            try:
                path.mkdir(parents=True, exist_ok=True)
                rel_path = StorageManager.get_relative_path(path)
                debug(f"[Storage] Pasta criada/verificada: {rel_path}")
                return True
            except Exception as e:
                rel_path = StorageManager.get_relative_path(path)
                error(f"[Storage] Erro ao criar pasta {rel_path}: {e}")
                return False
        else:
            # Cloud storage não precisa criar pastas localmente
            debug(f"[Storage] Cloud path virtual: {path}")
            return True

    @staticmethod
    def get_tasks_file_path(client_id: int, chat_uuid: str) -> Path:
        """Retorna caminho para arquivo JSON de tasks"""
        base_path = StorageManager.get_client_chat_path(client_id, chat_uuid)
        StorageManager.ensure_path_exists(base_path)
        return base_path / "tasks.json"

    @staticmethod
    def get_documents_folder(client_id: int, chat_uuid: str) -> Path:
        """Retorna caminho para pasta de documentos markdown"""
        base_path = StorageManager.get_client_chat_path(client_id, chat_uuid)
        docs_path = base_path / "documents"
        StorageManager.ensure_path_exists(docs_path)
        return docs_path

    @staticmethod
    def get_uploads_folder(client_id: int, chat_uuid: str) -> Path:
        """Retorna caminho para pasta de uploads"""
        base_path = StorageManager.get_client_chat_path(client_id, chat_uuid)
        uploads_path = base_path / "uploads"
        StorageManager.ensure_path_exists(uploads_path)
        return uploads_path

    @staticmethod
    def get_assets_folder(client_id: int, chat_uuid: str) -> Path:
        """Retorna caminho para pasta de assets gerados (imagens, vídeos)"""
        base_path = StorageManager.get_client_chat_path(client_id, chat_uuid)
        assets_path = base_path / "assets"
        StorageManager.ensure_path_exists(assets_path)
        return assets_path

    @staticmethod
    def save_file(
        client_id: int,
        chat_uuid: str,
        folder_type: str,
        filename: str,
        content,
        is_binary: bool = False,
    ) -> Optional[str]:
        """
        Salva arquivo no storage (texto ou binário)

        Args:
            client_id: ID do cliente
            chat_uuid: UUID do chat
            folder_type: 'documents', 'uploads', 'assets' ou 'tasks'
            filename: Nome do arquivo
            content: Conteúdo a salvar (str para texto, bytes para binário)
            is_binary: Se True, salva como arquivo binário

        Returns:
            Caminho do arquivo salvo ou None se falhar
        """
        storage_type = StorageManager.get_storage_type()

        try:
            if folder_type == "tasks":
                file_path = StorageManager.get_tasks_file_path(client_id, chat_uuid)
            elif folder_type == "documents":
                file_path = (
                    StorageManager.get_documents_folder(client_id, chat_uuid) / filename
                )
            elif folder_type == "uploads":
                file_path = (
                    StorageManager.get_uploads_folder(client_id, chat_uuid) / filename
                )
            elif folder_type == "assets":
                file_path = (
                    StorageManager.get_assets_folder(client_id, chat_uuid) / filename
                )
            else:
                error(f"[Storage] Tipo de pasta desconhecido: {folder_type}")
                return None

            if storage_type == "local":
                file_path.parent.mkdir(parents=True, exist_ok=True)

                if is_binary:
                    with open(file_path, "wb") as f:
                        f.write(content)
                else:
                    with open(file_path, "w", encoding="utf-8") as f:
                        f.write(content)

                rel_path = StorageManager.get_relative_path(file_path)
                debug(
                    f"[Storage] Arquivo {'binário ' if is_binary else ''}salvo: {rel_path}"
                )
                return str(file_path)
            else:
                # Cloud: aqui seria integração com Supabase
                # Por enquanto, retorna apenas o caminho virtual
                debug(f"[Storage] Cloud file path: {file_path}")
                return str(file_path)

        except Exception as e:
            error(f"[Storage] Erro ao salvar arquivo {filename}: {e}")
            return None

    @staticmethod
    def read_file(
        client_id: int, chat_uuid: str, folder_type: str, filename: str
    ) -> Optional[str]:
        """
        Lê arquivo do storage

        Args:
            client_id: ID do cliente
            chat_uuid: UUID do chat
            folder_type: 'documents', 'uploads', 'assets' ou 'tasks'
            filename: Nome do arquivo

        Returns:
            Conteúdo do arquivo ou None se falhar
        """
        storage_type = StorageManager.get_storage_type()

        try:
            if folder_type == "tasks":
                file_path = StorageManager.get_tasks_file_path(client_id, chat_uuid)
            elif folder_type == "documents":
                file_path = (
                    StorageManager.get_documents_folder(client_id, chat_uuid) / filename
                )
            elif folder_type == "uploads":
                file_path = (
                    StorageManager.get_uploads_folder(client_id, chat_uuid) / filename
                )
            elif folder_type == "assets":
                file_path = (
                    StorageManager.get_assets_folder(client_id, chat_uuid) / filename
                )
            else:
                error(f"[Storage] Tipo de pasta desconhecido: {folder_type}")
                return None

            if storage_type == "local":
                if file_path.exists():
                    with open(file_path, "r", encoding="utf-8") as f:
                        content = f.read()
                    rel_path = StorageManager.get_relative_path(file_path)
                    debug(f"[Storage] Arquivo lido: {rel_path}")
                    return content
                else:
                    rel_path = StorageManager.get_relative_path(file_path)
                    debug(f"[Storage] Arquivo não encontrado: {rel_path}")
                    return None
            else:
                # Cloud: aqui seria integração com Supabase
                debug(f"[Storage] Cloud file path: {file_path}")
                return None

        except Exception as e:
            error(f"[Storage] Erro ao ler arquivo {filename}: {e}")
            return None
