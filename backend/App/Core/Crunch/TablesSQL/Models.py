"""
Modelos SQLAlchemy para o banco de dados.
"""

from datetime import datetime, date
from sqlalchemy import (
    Column,
    String,
    Integer,
    Float,
    DateTime,
    Boolean,
    Text,
    ForeignKey,
    Index,
    Numeric,
    Date,
    JSON,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
import uuid

from App.Core.Crunch.TablesSQL.Database import Base


class Client(Base):
    """Modelo para clientes."""

    __tablename__ = "clients"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(String, unique=True, nullable=False)
    plan_id = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    started_at = Column(DateTime, default=datetime.utcnow)
    finishes_at = Column(DateTime)
    users_available = Column(Integer, default=1)

    # Relacionamentos
    users = relationship("User", back_populates="client")


class User(Base):
    """Modelo para usuários."""

    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String, unique=True, nullable=False)
    client_id = Column(String, ForeignKey("clients.client_id"), nullable=False)

    email = Column(String, unique=True, nullable=False)
    password = Column(String, nullable=False)
    full_name = Column(String, nullable=False, default="new_user")
    whatsapp = Column(String)
    instagram = Column(String)
    telegram = Column(String)
    type = Column(String, default="login")  # trial ou login
    ip_address = Column(String)
    fingerprint_id = Column(String)
    credits = Column(Numeric(20, 6), default=0)
    last_reset = Column(String)  # 'cumulative' ou 'non_cumulative'
    cumulative_resets_at = Column(DateTime)
    non_cumulative_resets_at = Column(DateTime)

    cookies_accepted = Column(Boolean, default=False)
    cookies_accepted_at = Column(DateTime)
    terms_accepted = Column(Boolean, default=False)
    terms_accepted_at = Column(DateTime)
    privacy_accepted = Column(Boolean, default=False)
    privacy_accepted_at = Column(DateTime)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relacionamentos
    client = relationship("Client", back_populates="users")


class Consumer(Base):
    """Clientes finais (consumidores) do cardápio público."""

    __tablename__ = "consumers"

    id = Column(Integer, primary_key=True, index=True)
    consumer_id = Column(String, unique=True, nullable=False)
    email = Column(String, unique=True, nullable=False)
    password_hash = Column(String, nullable=False)
    name = Column(String)
    phone_encrypted = Column(String)
    cpf_encrypted = Column(String)  # encrypted; one per consumer
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ConsumerAddress(Base):
    """Endereços salvos de um consumidor (múltiplos por consumer)."""

    __tablename__ = "consumer_addresses"

    id = Column(Integer, primary_key=True, index=True)
    address_id = Column(String, unique=True, nullable=False)
    consumer_id = Column(String, nullable=False)
    label = Column(String)           # "Casa", "Trabalho", etc
    cep_encrypted = Column(String)
    rua_encrypted = Column(String)
    numero_encrypted = Column(String)
    complemento_encrypted = Column(String)
    bairro_encrypted = Column(String)
    cidade_encrypted = Column(String)
    estado_encrypted = Column(String)
    is_main = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class ConsumerCard(Base):
    """Metadados de cartões salvos de um consumidor (sem PAN)."""

    __tablename__ = "consumer_cards"

    id = Column(Integer, primary_key=True, index=True)
    card_id = Column(String, unique=True, nullable=False)
    consumer_id = Column(String, nullable=False)
    last4 = Column(String, nullable=False)   # não sensível
    brand = Column(String)                   # não sensível
    holder_encrypted = Column(String)
    is_main = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class Chat(Base):
    """Modelo para chats."""

    __tablename__ = "chats"

    id = Column(Integer, primary_key=True, index=True)
    chat_id = Column(String, unique=True, nullable=False)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user_id = Column(String, ForeignKey("users.user_id"), nullable=True)
    chat_name = Column(String)
    status = Column(String, default="active")
    chat_cover = Column(String)
    seen = Column(Integer, default=1)  # 0 = unseen, 1 = seen
    source = Column(String, nullable=True)  # 'trigger' | 'scheduled' | None
    external_sender_id = Column(
        String, nullable=True
    )  # ID externo do remetente (Telegram from.id, WhatsApp phone, etc.)
    trigger_id = Column(String, nullable=True)  # trigger que originou este chat

    # Relacionamentos
    messages = relationship(
        "Message", back_populates="chat", cascade="all, delete-orphan"
    )
    # documents = relationship("Document", back_populates="chat", cascade="all, delete-orphan")  # DEPRECATED: migrado para File + MessageFile


class Message(Base):
    """Modelo para mensagens."""

    __tablename__ = "messages"

    id = Column(Integer, primary_key=True, index=True)
    message_id = Column(String, unique=True, nullable=False)

    created_at = Column(DateTime, default=datetime.utcnow)

    chat_id = Column(String, ForeignKey("chats.chat_id"), nullable=False)

    message_type = Column(String, nullable=False, default="user")  # 'user' ou 'ai'
    content = Column(Text, nullable=False)
    feedback = Column(Text, nullable=True)
    model = Column(String)
    tool = Column(String, nullable=True)
    fk_tool_id = Column(
        String, nullable=True, index=True
    )  # FK para tools (por enquanto vazio)

    # Relacionamentos
    chat = relationship("Chat", back_populates="messages")


class IntegrationMCP(Base):
    """Modelo para integrações MCP por cliente."""

    __tablename__ = "integrations_mcp"

    id = Column(Integer, primary_key=True, index=True)
    integration_id = Column(String, unique=True, nullable=False)
    client_id = Column(String, ForeignKey("clients.client_id"), nullable=False)
    provider = Column(String, nullable=False)  # ex: 'meta-ads'
    command = Column(String, nullable=False)  # ex: 'npx'
    args = Column(JSON, nullable=False)  # ex: ["-y", "meta-ads-mcp"]
    env_vars = Column(JSON, nullable=False)  # ex: {"TOKEN": "..."}
    is_active = Column(Boolean, default=True)
    token_valid = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)


# ── Omni-channel & Agent Models ───────────────────────────────────────


class AgentChat(Base):
    """Modelo para chats de agentes (Omni-channel)."""

    __tablename__ = "agent_chat"

    id = Column(Integer, primary_key=True, index=True)
    chat_id = Column(String, unique=True, nullable=False)
    user_id = Column(String, ForeignKey("users.user_id"), nullable=False)
    provider = Column(String)  # 'whatsapp', 'telegram', 'instagram', 'gmail'
    external_id = Column(String)  # ID no canal externo
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relacionamentos
    messages = relationship(
        "AgentMessage", back_populates="chat", cascade="all, delete-orphan"
    )


class AgentMessage(Base):
    """Modelo para mensagens de agentes (Omni-channel)."""

    __tablename__ = "agent_messages"

    id = Column(Integer, primary_key=True, index=True)
    message_id = Column(String, unique=True, nullable=False)
    chat_id = Column(String, ForeignKey("agent_chat.chat_id"), nullable=False)
    sender = Column(String, nullable=False)  # 'user' or 'agent'
    content = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relacionamentos
    chat = relationship("AgentChat", back_populates="messages")


class AgentIsolatedChat(Base):
    """Modelo para chats isolados de agentes."""

    __tablename__ = "agent_isolated_chat"

    id = Column(Integer, primary_key=True, index=True)
    chat_id = Column(String, unique=True, nullable=False)
    user_id = Column(String, ForeignKey("users.user_id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relacionamentos
    messages = relationship(
        "AgentIsolatedMessage", back_populates="chat", cascade="all, delete-orphan"
    )


class AgentIsolatedMessage(Base):
    """Modelo para mensagens isoladas de agentes."""

    __tablename__ = "agent_isolated_messages"

    id = Column(Integer, primary_key=True, index=True)
    message_id = Column(String, unique=True, nullable=False)
    chat_id = Column(String, ForeignKey("agent_isolated_chat.chat_id"), nullable=False)
    sender = Column(String, nullable=False)  # 'user' or 'agent'
    content = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relacionamentos
    chat = relationship("AgentIsolatedChat", back_populates="messages")
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Task(Base):
    """Modelo para tasks - com linked-list para remover steps sem reordenação."""

    __tablename__ = "tasks"

    id = Column(Integer, primary_key=True, index=True)
    task_id = Column(
        String, nullable=False, index=True
    )  # UUID do grupo de tasks (pode repetir)
    step_id = Column(
        String, unique=True, nullable=False, index=True
    )  # UUID único do step

    chat_id = Column(String, ForeignKey("chats.chat_id"), nullable=False)
    user_id = Column(String, ForeignKey("users.user_id"), nullable=False)

    task_name = Column(String, nullable=False)  # Nome da task/grupo
    step_name = Column(String, nullable=False)  # Nome do step
    step_context = Column(
        String, nullable=False
    )  # Identificador do step (pode ser número ou texto)
    status = Column(
        String, nullable=False, default="pending"
    )  # pending, success, failed, finished

    # Linked-list fields: permite remover steps sem reescrever toda sequência
    previous_step_id = Column(String, ForeignKey("tasks.step_id"), nullable=True)
    next_step_id = Column(String, ForeignKey("tasks.step_id"), nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)

    # Relacionamentos
    chat = relationship("Chat")


class Calendar(Base):
    """Modelo para posts de calendário programados.

    Infra para versionamento e carrosseis:
    - generated_content_id: vincula a asset gerado (FK para assets.asset_id)
    - previous_step_id/next_step_id: linked-list para sequência de carrosseis
    - version: controla versionamento de assets (iterações/ajustes)
    - caption: SEO + LLM optimization para cada versão
    """

    __tablename__ = "calendar"

    id = Column(Integer, primary_key=True, index=True)
    post_id = Column(String, unique=True, nullable=False, index=True)

    chat_id = Column(String, ForeignKey("chats.chat_id"), nullable=False)
    user_id = Column(String, ForeignKey("users.user_id"), nullable=False)

    campaign_name = Column(String, nullable=True)
    post_date = Column(Date, nullable=False, index=True)
    short_description = Column(String, nullable=True)
    content_type = Column(
        String, nullable=True
    )  # branding, awareness, educational, conversion, cart_recovery
    full_content = Column(Text, nullable=True)  # JSON completo do post
    status = Column(
        String, default="toDo", nullable=False
    )  # toDo, made, posted, cancelled

    # Assets e carrosseis
    generated_content_id = Column(
        String, ForeignKey("assets.asset_id"), nullable=True, index=True
    )
    organization = Column(String, nullable=True)  # Organização/categoria do post

    # Linked-list para ordem de posts em carrosseis
    previous_step_id = Column(
        String, ForeignKey("calendar.post_id"), nullable=True, index=True
    )
    next_step_id = Column(
        String, ForeignKey("calendar.post_id"), nullable=True, index=True
    )

    # Caption para SEO e LLM
    caption = Column(Text, nullable=True)  # Legenda/descrição do post
    version = Column(Integer, default=1)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relacionamentos
    chat = relationship("Chat")
    user = relationship("User")
    generated_content = relationship("Asset")


# DEPRECATED: Document foi migrado para File + MessageFile (relação N-M)
# Veja tabelas 'files' e 'message_files' no SchemaManager.py
# class Document(Base):
#     """Modelo para documentos."""
#     __tablename__ = "documents"
#
#     id = Column(Integer, primary_key=True, index=True)
#     document_id = Column(Integer, unique=True, nullable=False)
#
#     created_at = Column(DateTime, default=datetime.utcnow)
#     updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
#
#     chat_id = Column(String, ForeignKey("chats.chat_id"), nullable=False)
#     client_id = Column(String, ForeignKey("clients.client_id"), nullable=False)
#
#     title = Column(String, nullable=False)
#     extension = Column(String, nullable=False)
#     link = Column(String, nullable=False)
#     type = Column(String, default="documentation")
#     description = Column(Text)
#
#     # Relacionamentos
#     chat = relationship("Chat", back_populates="documents")
#     client = relationship("Client")


class RefreshToken(Base):
    """Modelo para refresh tokens."""

    __tablename__ = "refresh_tokens"

    id = Column(Integer, primary_key=True, index=True)
    token_id = Column(String, unique=True, nullable=False)

    user_id = Column(Integer, nullable=False)
    token_hash = Column(String, nullable=False)

    expires_at = Column(DateTime, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    revoked_at = Column(DateTime, nullable=True)


class OAuthToken(Base):
    """Modelo para tokens OAuth."""

    __tablename__ = "oauth_tokens"

    token_id = Column(Integer, primary_key=True, index=True)
    service_name = Column(String, nullable=False, unique=True)

    access_token = Column(String)
    refresh_token = Column(String, nullable=False)
    token_uri = Column(String, nullable=False)
    client_id = Column(String, nullable=False)
    client_secret = Column(String, nullable=False)
    scopes = Column(String, nullable=False)

    expires_at = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


# ============================================================================
# MODELOS PARA ISOLAMENTO POR AGENTE
# ============================================================================


class IsolatedChat(Base):
    """Modelo para chats isolados por agente."""

    __tablename__ = "isolated_chat"

    id = Column(Integer, primary_key=True, index=True)

    # Referência ao chat principal
    chat_id = Column(String, ForeignKey("chats.chat_id"), nullable=False)

    # Identificador do agente
    agent_id = Column(String, nullable=False, index=True)

    # Metadados
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relacionamentos
    chat = relationship("Chat")
    messages = relationship(
        "IsolatedMessage", back_populates="isolated_chat", cascade="all, delete-orphan"
    )

    # Índice composto para garantir unicidade
    __table_args__ = (
        Index("idx_isolated_chat_unique", "chat_id", "agent_id", unique=True),
    )


class IsolatedMessage(Base):
    """Modelo para mensagens isoladas por agente."""

    __tablename__ = "isolated_messages"

    id = Column(Integer, primary_key=True, index=True)

    # Referência ao chat isolado
    isolated_chat_id = Column(
        String, ForeignKey("isolated_chat.chat_id"), nullable=False, index=True
    )

    # ID do agente que criou a mensagem
    agent_id = Column(String, nullable=False, index=True)

    # Nome/tipo do agente
    agent = Column(String, nullable=False, index=True)

    # Identificador único da mensagem
    isolated_message_id = Column(String, unique=True, nullable=False, index=True)

    # ID do tool call (mesmo para INPUT e OUTPUT da mesma tool)
    tool_call_id = Column(String, nullable=True, index=True)

    # Nome da tool chamada (context, client, task, etc)
    tool_called = Column(String, nullable=True, index=True)

    # Tipo de tool call: 'input' (LLM chamando) ou 'output' (resultado)
    tool_call_type = Column(String, nullable=True, index=True)  # 'input', 'output'

    # FK para tools (por enquanto vazio, será preenchido no futuro)
    fk_tool_id = Column(String, nullable=True, index=True)

    # Conteúdo da mensagem
    role = Column(String, nullable=False)  # 'user', 'assistant', 'system'
    content = Column(Text, nullable=False)
    type = Column(String, default="message")  # 'message', 'tool_call'

    # Tokens retornados pela LLM
    input_tokens = Column(Integer, default=0)
    output_tokens = Column(Integer, default=0)

    # Metadados
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relacionamentos
    isolated_chat = relationship("IsolatedChat", back_populates="messages")

    # Flag para controlar se mensagem está na janela de contexto ativa
    context_window = Column(Boolean, default=True)


class ContextWindow(Base):
    """Modelo para armazenar contextos compactados de conversas."""

    __tablename__ = "context_window"

    id = Column(Integer, primary_key=True, index=True)

    # Referência ao chat isolado
    isolated_chat_id = Column(
        String, ForeignKey("isolated_chat.chat_id"), nullable=False, index=True
    )

    # ID da mensagem até qual foi compactada (cut point)
    cut_message_isolated_message_id = Column(String, nullable=False, index=True)

    # Contexto compactado gerado pelo compactor
    context_generated = Column(Text, nullable=False)

    # ID do agente que fez a compactação
    agent_id = Column(String, nullable=False)

    # Nome do agente
    agent = Column(String, nullable=False)

    # Número de tokens no contexto compactado
    tokens = Column(Integer, default=0)

    # Metadados
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relacionamentos
    isolated_chat = relationship("IsolatedChat")


class CreditsLog(Base):
    """Modelo para logs de créditos (operações de charge/refuel)."""

    __tablename__ = "credits_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    credits_logs_id = Column(String, unique=True, nullable=False)
    user_id = Column(String, ForeignKey("users.user_id"), nullable=False)
    operation_type = Column(String, nullable=True)  # 'charge' or 'refuel'
    value = Column(Numeric, nullable=True)  # negative for charge, positive for refuel
    credit_type = Column(String, nullable=False)  # 'cumulative' or 'non_cumulative'
    is_signup_setup = Column(Boolean, default=False)
    reason = Column(Text, nullable=True)
    isolated_message_id = Column(
        String, ForeignKey("isolated_messages.isolated_message_id"), nullable=True
    )
    isolated_chat_id = Column(
        String, ForeignKey("isolated_chat.chat_id"), nullable=True
    )
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Document(Base):
    """Modelo para documentos com conteúdo armazenado no banco de dados."""

    __tablename__ = "documents"

    id = Column(Integer, primary_key=True, index=True)
    document_id = Column(String, unique=True, nullable=False, index=True)

    chat_id = Column(String, ForeignKey("chats.chat_id"), nullable=False)
    user_id = Column(String, ForeignKey("users.user_id"), nullable=False)

    title = Column(String, nullable=False)
    content = Column(Text, nullable=True)
    extension = Column(String, nullable=True)
    tool_type = Column(String, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relacionamentos
    chat = relationship("Chat")
    user = relationship("User")


class Attachment(Base):
    """Modelo para attachments (metadados de arquivo)."""

    __tablename__ = "attachments"

    id = Column(Integer, primary_key=True, index=True)
    attachment_id = Column(String, unique=True, nullable=False, index=True)
    extension = Column(String, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relacionamentos
    table_files = relationship(
        "TableFile", back_populates="attachment", cascade="all, delete-orphan"
    )
    text_files = relationship(
        "TextFile", back_populates="attachment", cascade="all, delete-orphan"
    )


class TableFile(Base):
    """Modelo para arquivos de tabela extraídos (CSV, XLSX)."""

    __tablename__ = "table_files"

    id = Column(Integer, primary_key=True, index=True)
    table_file_id = Column(String, unique=True, nullable=False, index=True)
    attachment_id = Column(
        String, ForeignKey("attachments.attachment_id"), nullable=False
    )

    content = Column(Text, nullable=True)  # Conteúdo CSV formatado com "" para células

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relacionamentos
    attachment = relationship("Attachment", back_populates="table_files")


class TextFile(Base):
    """Modelo para arquivos de texto extraídos."""

    __tablename__ = "text_files"

    id = Column(Integer, primary_key=True, index=True)
    text_file_id = Column(String, unique=True, nullable=False, index=True)
    attachment_id = Column(
        String, ForeignKey("attachments.attachment_id"), nullable=False
    )

    content = Column(Text, nullable=True)  # Conteúdo de texto extraído

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relacionamentos
    attachment = relationship("Attachment", back_populates="text_files")


class EmailDomain(Base):
    """Modelo para domínios de email."""

    __tablename__ = "email_domains"

    id = Column(Integer, primary_key=True, index=True)
    email_domain_id = Column(String, unique=True, nullable=False, index=True)

    email = Column(String, nullable=True)
    domain = Column(String, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Email(Base):
    """Modelo para rastreamento de emails enviados/recebidos."""

    __tablename__ = "emails"

    id = Column(Integer, primary_key=True, index=True)
    email_id = Column(String, unique=True, nullable=False, index=True)

    event_type = Column(String, nullable=False)  # 'sent' ou 'received'
    email_domain_id = Column(
        String, ForeignKey("email_domains.email_domain_id"), nullable=True
    )
    email = Column(String, nullable=True)
    content = Column(Text, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relacionamentos
    email_domain = relationship("EmailDomain")


class Asset(Base):
    """Modelo para assets gerados (imagens e vídeos)."""

    __tablename__ = "assets"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    # asset_id: ID único por asset
    asset_id = Column(String, unique=True, nullable=False, index=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    type = Column(String, nullable=False)  # 'img' ou 'film'
    content_name = Column(String, nullable=False)

    user_id = Column(String, ForeignKey("users.user_id"), nullable=True)
    client_id = Column(String, ForeignKey("clients.client_id"), nullable=True)
    chat_id = Column(String, ForeignKey("chats.chat_id"), nullable=True)

    storage_path = Column(String, nullable=True)  # Caminho no storage (S3, local, etc)
    storage_env = Column(String, nullable=True)  # 'local', 's3', 'gcs', etc

    title = Column(String, nullable=True)  # Título do asset
    caption = Column(Text, nullable=True)  # Legenda/descrição do asset
    ratio = Column(String, nullable=True)  # Aspect ratio (ex: "9:16", "4:5")
    version = Column(Integer, default=1)
    variation_id = Column(
        String, nullable=True
    )  # UUID compartilhado por variações do mesmo source_idx
    approval_status = Column(String, default="waitingJudge", nullable=True)
    feedback = Column(Text, nullable=True)

    # Indexes para consultas frequentes
    __table_args__ = (
        Index("idx_assets_type", "type"),
        Index("idx_assets_user", "user_id"),
        Index("idx_assets_chat", "chat_id"),
        Index("idx_assets_id", "asset_id"),
    )

    # Relacionamentos
    user = relationship("User")
    client = relationship("Client")
    chat = relationship("Chat")


# Compatibilidade com código existente que referencia GeneratedContent
GeneratedContent = Asset


class CreativeComposition(Base):
    """Estado JSON do editor de criativos (composição de camadas)."""

    __tablename__ = "creative_compositions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    composition_id = Column(String, unique=True, nullable=False, index=True)
    chat_id = Column(String, ForeignKey("chats.chat_id"), nullable=False, index=True)
    user_id = Column(String, ForeignKey("users.user_id"), nullable=True)

    title = Column(String, nullable=True)
    state = Column(
        JSON, nullable=True
    )  # { aspectRatio, dimensions, layers, backgroundColor }
    version = Column(Integer, default=1)
    preview_url = Column(String, nullable=True)  # deprecated — use snapshot_b64
    snapshot_b64 = Column(
        Text, nullable=True
    )  # base64 PNG do design renderizado (sem prefixo data URI)
    snapshot_version = Column(
        Integer, nullable=True
    )  # version no momento em que o snapshot foi gerado

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index("idx_creative_comp_chat", "chat_id"),
        Index("idx_creative_comp_id", "composition_id"),
    )

    chat = relationship("Chat")
    user = relationship("User")


class Brand(Base):
    """Identidade de marca por cliente — persiste brand_communication consolidado."""

    __tablename__ = "brands"

    id = Column(Integer, primary_key=True, autoincrement=True)
    client_id = Column(
        String, ForeignKey("clients.client_id"), nullable=False, index=True
    )
    chat_id = Column(String, ForeignKey("chats.chat_id"), nullable=True)
    title = Column(String, nullable=True)  # nome legível da marca (ex: "MD70")
    version = Column(Integer, default=1)
    data = Column(JSON, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (Index("idx_brands_client", "client_id"),)

    client = relationship("Client")


class TempURL(Base):
    """Modelo para tokens temporários — screenshots (vision) e attachment tokens (LLM)."""

    __tablename__ = "temp_urls"

    token = Column(String, primary_key=True, index=True)
    filepath = Column(String, nullable=True)
    origin_url = Column(String, nullable=True)
    expires_at = Column(Numeric, nullable=False)  # Unix timestamp
    attachment_id = Column(String, nullable=True)
    user_id = Column(String, nullable=True)
    used = Column(Integer, default=0, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Índice para limpeza eficiente de expirados
    __table_args__ = (Index("idx_temp_urls_expires", "expires_at"),)


class ScheduledTask(Base):
    """Tarefas agendadas — configurações de execuções periódicas do agente."""

    __tablename__ = "scheduled_tasks"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()), index=True)
    user_id = Column(
        String,
        ForeignKey("users.user_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    cron_expression = Column(String, nullable=False)
    cron_label = Column(String, nullable=True)
    prompt = Column(Text, nullable=False)
    integrations = Column(JSON, default=list)
    autonomy_level = Column(
        Integer, default=4
    )  # 1=sugere 2=rascunho 3=aprovação 4=autônomo
    utc_offset = Column(Integer, default=0)  # horas em relação a UTC, ex: -3 para BRT
    status = Column(String, default="active")  # active | paused
    last_executed_at = Column(DateTime, nullable=True)
    next_execution_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    executions = relationship(
        "TaskExecution", back_populates="task", cascade="all, delete-orphan"
    )

    __table_args__ = (Index("idx_scheduled_tasks_user", "user_id"),)


class TaskExecution(Base):
    """Execuções de tarefas agendadas — cada run do agente."""

    __tablename__ = "task_executions"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()), index=True)
    task_id = Column(
        String,
        ForeignKey("scheduled_tasks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id = Column(
        String,
        ForeignKey("users.user_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    chat_id = Column(String, nullable=True)  # isolated_chat vinculado
    status = Column(
        String, default="running"
    )  # running | completed | pending_review | approved | rejected | failed
    result_summary = Column(Text, nullable=True)
    started_at = Column(DateTime, default=datetime.utcnow)
    finished_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    task = relationship("ScheduledTask", back_populates="executions")

    __table_args__ = (
        Index("idx_task_executions_task", "task_id"),
        Index("idx_task_executions_user_status", "user_id", "status"),
    )


class CustomSkill(Base):
    """Skills personalizadas criadas pelo usuário — injetadas no system prompt do agente."""

    __tablename__ = "custom_skills"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()), index=True)
    user_id = Column(
        String,
        ForeignKey("users.user_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    content = Column(Text, nullable=False)  # instrução completa da skill
    is_active = Column(Integer, default=1, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (Index("idx_custom_skills_user", "user_id"),)


class TelegramLinkCode(Base):
    """Códigos temporários para vincular conta Telegram ao MD70."""

    __tablename__ = "telegram_link_codes"

    code = Column(String, primary_key=True)
    user_id = Column(
        String,
        ForeignKey("users.user_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    expires_at = Column(DateTime, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


# ============================================================================
# PDV — CARDÁPIO
# ============================================================================


# ============================================================================
# DELIVERY INTEGRATIONS
# ============================================================================


class DeliveryPendingAuth(Base):
    """
    Autorização iFood pendente enquanto o dono da loja insere o userCode no Portal do Parceiro.
    Expira em 10 minutos (expiresIn da resposta do iFood).
    Persistido no banco + Redis para sobreviver a restarts.
    """

    __tablename__ = "delivery_pending_auth"

    id = Column(String, primary_key=True, index=True)
    store_id = Column(String, nullable=False, index=True)
    platform = Column(String, nullable=False, default="ifood")
    user_code = Column(String, nullable=False)
    code_verifier = Column(String, nullable=False)
    expires_at = Column(DateTime, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index("idx_delivery_pending_auth_store", "store_id", "platform"),
    )


class DeliveryIntegration(Base):
    """
    Tokens OAuth de delivery por loja e plataforma.
    access_token expira em 6h, refresh_token em 168h (7 dias).
    Renovação automática via refresh_token no IFoodClient._request().
    """

    __tablename__ = "delivery_integrations"

    id = Column(String, primary_key=True, index=True)
    store_id = Column(String, nullable=False, index=True)
    platform = Column(String, nullable=False, default="ifood")
    access_token = Column(Text, nullable=False)
    refresh_token = Column(Text, nullable=True)
    expires_at = Column(DateTime, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index("idx_delivery_integrations_store", "store_id", "platform", unique=True),
    )


class PDVCategory(Base):
    """Categorias do cardápio por cliente."""

    __tablename__ = "pdv_categories"

    id = Column(Integer, primary_key=True, autoincrement=True)
    client_id = Column(String, ForeignKey("clients.client_id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(100), nullable=False)
    sort_order = Column(Integer, default=0)
    type = Column(String(20), default="product", nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)



class PDVProduct(Base):
    """Produtos do cardápio por cliente."""

    __tablename__ = "pdv_products"

    id = Column(Integer, primary_key=True, autoincrement=True)
    client_id = Column(String, ForeignKey("clients.client_id", ondelete="CASCADE"), nullable=False, index=True)
    category_id = Column(Integer, ForeignKey("pdv_categories.id", ondelete="SET NULL"), nullable=True)
    sku_id = Column(String(50), nullable=False)
    name = Column(String(255), nullable=False)
    price = Column(Numeric(10, 2), nullable=False)
    category = Column(String(100), nullable=False)
    available = Column(Boolean, default=True, nullable=False)
    emoji = Column(String(10))
    description = Column(Text)
    is_combo = Column(Boolean, default=False)
    variations_json = Column(Text)
    addons_json = Column(Text)
    recipe_json = Column(Text)
    price_delivery = Column(Numeric(10, 2), nullable=True)
    price_ifood = Column(Numeric(10, 2), nullable=True)
    price_99 = Column(Numeric(10, 2), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)



class PDVStoreProfile(Base):
    """Perfil da loja (nome, descrição, fotos, redes sociais) por cliente."""

    __tablename__ = "pdv_store_profiles"

    id = Column(Integer, primary_key=True, autoincrement=True)
    client_id = Column(String, ForeignKey("clients.client_id", ondelete="CASCADE"), unique=True, nullable=False, index=True)
    name = Column(String(255), default="Minha Loja")
    description = Column(Text)
    cover_photo = Column(Text)
    profile_photo = Column(Text)
    social_links_json = Column(Text)
    google_review_link = Column(String(500))
    garcom_enabled = Column(Integer, default=0)
    garcom_pct = Column(Float, default=10.0)
    nfe_enabled = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class PDVCustomer(Base):
    __tablename__ = "pdv_customers"

    id = Column(Integer, primary_key=True, autoincrement=True)
    client_id = Column(String, ForeignKey("clients.client_id", ondelete="CASCADE"), nullable=False, index=True)
    cpf = Column(String(11), nullable=False)
    name = Column(String(255), nullable=False)
    phone = Column(String(20))
    email = Column(String(255))
    gender = Column(String(1), nullable=True)
    birth_date = Column(String(8), nullable=True)
    total_orders = Column(Integer, default=0)
    total_spent = Column(Float, default=0.0)
    last_visit = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class PDVComanda(Base):
    __tablename__ = "pdv_comandas"

    id = Column(Integer, primary_key=True, autoincrement=True)
    client_id = Column(String, ForeignKey("clients.client_id", ondelete="CASCADE"), nullable=False, index=True)
    label = Column(String(255), nullable=False)
    cpf = Column(String(11), nullable=True)
    customer_name = Column(String(255), nullable=True)
    items_json = Column(Text, default="[]")
    status = Column(String(20), default="open")
    opened_at = Column(DateTime, default=datetime.utcnow)
    closed_at = Column(DateTime, nullable=True)


class PDVOrder(Base):
    __tablename__ = "pdv_orders"

    id = Column(Integer, primary_key=True, autoincrement=True)
    client_id = Column(String, ForeignKey("clients.client_id", ondelete="CASCADE"), nullable=False, index=True)
    comanda_label = Column(String(255))
    payment_method = Column(String(50))
    cpf = Column(String(11))
    customer_name = Column(String(255))
    subtotal = Column(Float, default=0)
    garcom_fee = Column(Float, default=0)
    coupon_discount = Column(Float, default=0)
    total = Column(Float, default=0)
    items_json = Column(Text)
    coupons_json = Column(Text)
    nfe_emitted = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)


class PDVStockItem(Base):
    """Insumos/matéria-prima do estoque por cliente."""

    __tablename__ = "pdv_stock_items"

    id = Column(Integer, primary_key=True, autoincrement=True)
    client_id = Column(String, ForeignKey("clients.client_id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    emoji = Column(String(10))
    unit = Column(String(20), nullable=False, default="un")
    category = Column(String(100))
    item_type = Column(String(20), default="supply", nullable=False)
    quantity = Column(Numeric(10, 3), default=0)
    min_stock = Column(Numeric(10, 3), default=0)
    cost_per_unit = Column(Numeric(10, 2), default=0)
    expiry_date = Column(String(10))
    phase = Column(String(30), default="ok")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class PDVStockTransaction(Base):
    """Lançamentos de compra, perda e venda de insumos."""

    __tablename__ = "pdv_stock_transactions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    client_id = Column(String, ForeignKey("clients.client_id", ondelete="CASCADE"), nullable=False, index=True)
    stock_item_id = Column(Integer, ForeignKey("pdv_stock_items.id", ondelete="CASCADE"), nullable=False, index=True)
    type = Column(String(20), nullable=False)
    quantity = Column(Numeric(10, 3), nullable=False)
    total_cost = Column(Numeric(10, 2))
    expiry_date = Column(String(10))
    note = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
