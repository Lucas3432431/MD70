"""
Definições centralizadas de tipos para Tools e Assets.
Single Source of Truth para tipos de ferramentas, assets e status.
"""

from enum import Enum
from typing import List


class ToolName(Enum):
    """Nomes de ferramentas disponíveis"""

    # Ferramentas de mídia
    ASSET = "asset"
    VISION = "vision"

    # Ferramentas de informação
    WEB_SEARCH = "web-search"
    CONTEXT = "context"

    # Ferramentas de documentação
    DOCUMENT = "document"
    ATTACHMENT = "attachment"

    # Ferramentas de agendamento
    SCHEDULE = "schedule"
    CALENDAR = "calendar"

    # Ferramentas de gerenciamento
    TASK = "task"
    UPDATE = "update"

    # Ferramentas de interação
    QUIZ = "quiz"
    PRINT = "print"
    MESSAGE = "message"

    # Ferramentas de raciocínio
    CHAIN_OF_THOUGHT = "chain-of-thought"

    # Ferramentas de cliente
    CLIENT = "client"


class AssetType(Enum):
    """Tipos de assets geráveis"""

    IMAGE = "image"
    VIDEO = "video"
    VISION = "vision"  # Análise, não geração


class AssetContentType(Enum):
    """Tipos de conteúdo armazenado em assets"""

    IMAGE = "img"  # Armazenado como 'img'
    VIDEO = "film"  # Armazenado como 'film'


class DocumentType(Enum):
    """Tipos de documentos estruturados"""

    BUSINESS_CANVAS = "business_canvas"
    BRAND_COMMUNICATION = "brand_communication"
    GOAL = "goal"
    COPY = "copy"
    VISUAL_COMMUNICATION = "visual_communication"


class TaskStatus(Enum):
    """Status de tasks em workflows"""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    SUCCESS = "success"
    FAILED = "failed"
    FINISHED = "finished"


class ToolCallType(Enum):
    """Tipo de chamada de ferramenta"""

    INPUT = "input"
    OUTPUT = "output"


class OperationType(Enum):
    """Tipos de operação para fila de processamento"""

    SCRAPING = "scraping"
    IMAGE_GEN = "image_gen"
    VIDEO_GEN = "video_gen"
    VISION = "vision"
    COMPACTOR = "compactor"


class AgentType(Enum):
    """Tipos de agentes disponíveis"""

    ORCHESTRATOR_GLOBAL = "orchestrator-global"
    DEEPSEEK = "deepseek"
    VISION = "vision"


class StorageEnv(Enum):
    """Ambientes de armazenamento"""

    LOCAL = "local"
    S3 = "s3"
    GCS = "gcs"


# Listas de valores válidos para validação
VALID_TOOL_NAMES = [t.value for t in ToolName]
VALID_ASSET_TYPES = [a.value for a in AssetType]
VALID_DOCUMENT_TYPES = [d.value for d in DocumentType]
VALID_TASK_STATUSES = [s.value for s in TaskStatus]
VALID_STORAGE_ENVS = [e.value for e in StorageEnv]

# Mapeamentos úteis
ASSET_TYPE_TO_CONTENT_TYPE = {
    AssetType.IMAGE.value: AssetContentType.IMAGE.value,
    AssetType.VIDEO.value: AssetContentType.VIDEO.value,
}

ASSET_CONTENT_TYPE_TO_EXTENSION = {
    AssetContentType.IMAGE.value: ".jpg",
    AssetContentType.VIDEO.value: ".mp4",
}

# Tools que requerem wait/async processing
ASYNC_TOOLS = {
    ToolName.ASSET.value,
    ToolName.VISION.value,
    ToolName.WEB_SEARCH.value,
}

# Tools que são inline (executam imediatamente no contexto)
INLINE_TOOLS = {
    ToolName.DOCUMENT.value,
    ToolName.UPDATE.value,
    ToolName.CONTEXT.value,
    ToolName.CLIENT.value,
    ToolName.TASK.value,
    ToolName.PRINT.value,
    ToolName.QUIZ.value,
    ToolName.ATTACHMENT.value,
}

# Tools que requerem acesso ao orchestrator global
ORCHESTRATOR_ONLY_TOOLS = {
    ToolName.ASSET.value,
    ToolName.VISION.value,
}

# Campos editáveis por ferramenta
EDITABLE_FIELDS_BY_TOOL = {
    ToolName.ASSET.value: {"caption", "version"},
    ToolName.TASK.value: {"status", "step_name", "step_context", "task_name"},
    ToolName.CALENDAR.value: {"new_date"},
    ToolName.DOCUMENT.value: {"content"},
    ToolName.CLIENT.value: {"content"},
}
