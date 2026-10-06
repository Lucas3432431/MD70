"""
App.Core.Types - Tipos e constantes centralizadas para o projeto.
"""

from .ToolTypes import (
    ToolName,
    AssetType,
    AssetContentType,
    DocumentType,
    TaskStatus,
    ToolCallType,
    OperationType,
    AgentType,
    StorageEnv,
    # Listas de validação
    VALID_TOOL_NAMES,
    VALID_ASSET_TYPES,
    VALID_DOCUMENT_TYPES,
    VALID_TASK_STATUSES,
    VALID_STORAGE_ENVS,
    # Mapeamentos
    ASSET_TYPE_TO_CONTENT_TYPE,
    ASSET_CONTENT_TYPE_TO_EXTENSION,
    # Sets de ferramentas
    ASYNC_TOOLS,
    INLINE_TOOLS,
    ORCHESTRATOR_ONLY_TOOLS,
    EDITABLE_FIELDS_BY_TOOL,
)

__all__ = [
    # Enums
    "ToolName",
    "AssetType",
    "AssetContentType",
    "DocumentType",
    "TaskStatus",
    "ToolCallType",
    "OperationType",
    "AgentType",
    "StorageEnv",
    # Listas
    "VALID_TOOL_NAMES",
    "VALID_ASSET_TYPES",
    "VALID_DOCUMENT_TYPES",
    "VALID_TASK_STATUSES",
    "VALID_STORAGE_ENVS",
    # Mapeamentos
    "ASSET_TYPE_TO_CONTENT_TYPE",
    "ASSET_CONTENT_TYPE_TO_EXTENSION",
    # Sets
    "ASYNC_TOOLS",
    "INLINE_TOOLS",
    "ORCHESTRATOR_ONLY_TOOLS",
    "EDITABLE_FIELDS_BY_TOOL",
]
