"""
Funções utilitárias para o sistema Crunch.
"""

import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from .Config import config
from App.Core.Logs import debug, error


def generate_id() -> str:
    """Gerar ID único."""
    return str(uuid.uuid4())


def format_datetime(dt: Optional[datetime] = None) -> str:
    """Formatar datetime para string ISO."""
    if dt is None:
        dt = datetime.utcnow()
    return dt.isoformat()


def parse_datetime(dt_str: str) -> datetime:
    """Parse datetime string do ISO format."""
    try:
        if isinstance(dt_str, str):
            return datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
        return dt_str
    except (ValueError, AttributeError):
        return datetime.utcnow()


def dict_to_model(data: Dict[str, Any], model_class):
    """
    Converter dicionário para modelo SQLAlchemy.

    Args:
        data: Dicionário com dados
        model_class: Classe do modelo SQLAlchemy

    Returns:
        Instância do modelo
    """
    try:
        # Remover campos que não existem no modelo
        model_fields = [col.name for col in model_class.__table__.columns]
        filtered_data = {k: v for k, v in data.items() if k in model_fields}

        # Criar instância do modelo
        return model_class(**filtered_data)
    except Exception as e:
        error(f"Error converting dict to {model_class.__name__}: {e}")
        raise


def model_to_dict(model) -> Dict[str, Any]:
    """
    Converter modelo SQLAlchemy para dicionário.

    Args:
        model: Instância do modelo SQLAlchemy

    Returns:
        Dicionário com os dados
    """
    if isinstance(model, dict):
        return model

    result = {}
    for key, value in model.__dict__.items():
        if not key.startswith("_"):
            # Converter datetime para string
            if isinstance(value, datetime):
                result[key] = value.isoformat()
            else:
                result[key] = value

    return result


def validate_client_data(data: Dict[str, Any]) -> bool:
    """Validar dados de cliente."""
    required_fields = ["legal_company_name", "company_code"]

    for field in required_fields:
        if field not in data or not data[field]:
            error(f"Missing required field: {field}")
            return False

    return True


def validate_user_data(data: Dict[str, Any]) -> bool:
    """Validar dados de usuário."""
    required_fields = ["email", "password", "client_id"]

    for field in required_fields:
        if field not in data or not data[field]:
            error(f"Missing required field: {field}")
            return False

    # Validar email
    if "@" not in data["email"]:
        error("Invalid email format")
        return False

    return True


def backup_database():
    """Criar backup do banco de dados."""
    try:
        if config.DB_PATH.exists():
            backup_path = config.DB_PATH.with_suffix(
                f'.backup.{datetime.now().strftime("%Y%m%d_%H%M%S")}.db'
            )
            import shutil

            shutil.copy2(config.DB_PATH, backup_path)
            debug(f"Database backup created: {backup_path}")
            return str(backup_path)
    except Exception as e:
        error(f"Error creating database backup: {e}")
    return None


def cleanup_old_backups(max_backups: int = 5):
    """Limpar backups antigos."""
    try:
        backup_dir = config.DB_PATH.parent
        backups = sorted(
            backup_dir.glob("*.backup.*.db"), key=lambda x: x.stat().st_mtime
        )

        if len(backups) > max_backups:
            for backup in backups[:-max_backups]:
                backup.unlink()
                debug(f"Removed old backup: {backup.name}")
    except Exception as e:
        error(f"Error cleaning up old backups: {e}")


def check_disk_space(min_gb: float = 1.0) -> bool:
    """Verificar espaço em disco disponível."""
    try:
        import shutil

        total, used, free = shutil.disk_usage(config.DB_PATH.parent)

        free_gb = free / (1024**3)  # Converter para GB
        debug(f"Disk space: {free_gb:.2f} GB free")

        return free_gb >= min_gb
    except Exception as e:
        error(f"Error checking disk space: {e}")
        return True  # Assume ok se não conseguir verificar
