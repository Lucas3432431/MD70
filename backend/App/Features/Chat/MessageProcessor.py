"""
MessageProcessor - Processa mensagens usando agents e LLM
Integra ChatManager, LLMClient e agentes para gerar respostas
"""

from typing import List, Dict, Any, Optional
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import json
import uuid
import time

import re as _re

from App.Core.Logs import debug, error, warning, info
from App.Features.Llm import LLMClient
from App.Features.Llm.ToolResponseRegistry import get_tool_call_response
from App.Features.Chat.ChatManager import ChatManager
from App.Features.Tools import Core
from App.Features.Credits import CreditsManager
from App.Core.Crunch import DatabaseManager
from App.Core.Crunch.TablesSQL.Models import IsolatedMessage, User, GeneratedContent
from App.Core.Queues import MultiQueueManager, OperationType
from App.Core.Settings import load_config
from sqlalchemy import text


def _parse_tool_arguments(arguments) -> dict:
    """Parse tool arguments tolerando JSON com newlines/tabs literais gerados pelo LLM."""
    if not isinstance(arguments, str):
        return arguments if isinstance(arguments, dict) else {}
    try:
        return json.loads(arguments)
    except json.JSONDecodeError:
        try:
            sanitized = _re.sub(r"(?<!\\)\n", r"\\n", arguments)
            sanitized = _re.sub(r"(?<!\\)\r", r"\\r", sanitized)
            sanitized = _re.sub(r"(?<!\\)\t", r"\\t", sanitized)
            return json.loads(sanitized)
        except json.JSONDecodeError:
            return {}


@dataclass
class ProcessResult:
    """Resultado do processamento de uma mensagem."""

    success: bool
    response: str
    agent_id: str
    model: str
    tokens_used: Dict[str, int]
    error: Optional[str] = None
    tool_calls: List[Dict[str, Any]] = None
    job_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Converte para dicionrio."""
        return {
            "success": self.success,
            "response": self.response,
            "agent_id": self.agent_id,
            "model": self.model,
            "tokens_used": self.tokens_used,
            "error": self.error,
            "tool_calls": self.tool_calls or [],
            "job_id": self.job_id,
        }


class MessageProcessor:
    """
    Processa mensagens de usurios usando agents configurados.
    Integra ChatManager para histrico e LLMClient para IA.
    """

    @staticmethod
    def has_required_signup_documents(user_id: str) -> bool:
        """
        Verifica se user criou AMBOS os documentos requeridos para signup setup.
        Exportado para ser usado por CreditsManager.

        Args:
            user_id: ID do usurio

        Returns:
            bool: True se user tem AMBOS business_canvas E brand_communication, False caso contrrio
        """
        try:
            # Consultar documentos do user
            query = """
                SELECT tool_type
                FROM documents
                WHERE user_id = :user_id
                AND tool_type IN ('business_canvas', 'brand_communication')
            """
            results = DatabaseManager.fetch_all(query, {"user_id": user_id})

            if not results:
                debug(f"[MessageProcessor] User {user_id} no tem documentos de setup")
                return False

            tool_types = {doc.get("tool_type") for doc in results}

            has_business_canvas = "business_canvas" in tool_types
            has_brand_communication = "brand_communication" in tool_types

            result = has_business_canvas and has_brand_communication

            if result:
                debug(
                    f"[MessageProcessor] User {user_id} tem todos os documentos de setup requeridos"
                )
            else:
                missing = []
                if not has_business_canvas:
                    missing.append("business_canvas")
                if not has_brand_communication:
                    missing.append("brand_communication")
                debug(f"[MessageProcessor] User {user_id} faltam documentos: {missing}")

            return result

        except Exception as e:
            error(f"[MessageProcessor] Erro ao verificar documentos de setup: {e}")
            # Assumir que precisa de setup (True = ainda em setup)
            return False

    @staticmethod
    def detect_malformed_tool_calls(response_text: str) -> bool:
        """
        Detecta se a resposta contm descrio textual de tool calls ao invs de estrutura formal.
        Padro procurado: "Tool: ...\nArgs: ..."

        Exportado para uso em SyncManager e outros mdulos.

        Args:
            response_text: Texto da resposta do LLM

        Returns:
            bool: True se contm descrio textual (malformado), False se OK
        """
        if not response_text:
            return False

        lines = response_text.split("\n")
        for i, line in enumerate(lines):
            line_stripped = line.strip()
            # Procura padro "Tool: ..."
            if line_stripped.startswith("Tool:"):
                # Verificar se prximas linhas tm "Args:"
                # Aumentado para procurar em at 10 linhas subsequentes
                for j in range(i + 1, min(i + 11, len(lines))):
                    next_line = lines[j].strip()
                    if next_line.startswith("Args:"):
                        return True
                    # Se encontrar outro "Tool:" antes de "Args:", interrompe a busca para este bloco
                    if next_line.startswith("Tool:"):
                        break

        return False

    # Alias para compatibilidade com cdigo antigo
    _detect_malformed_tool_calls = detect_malformed_tool_calls

    def __init__(
        self,
        chat_manager: ChatManager,
        agents_manager: Any,  # AgentsManager
        config: Dict[str, Any],
        core=None,  # SHARED Core instance (created in AppSetup)
        chat_service_sync_callback=None,  # Callback para sincronizar aps processar
    ):
        """
        Inicializa MessageProcessor.

        Args:
            chat_manager: Gerenciador de chats com histrico
            agents_manager: Gerenciador de agents (AgentsManager)
            config: Configuraes da aplicao (contm API keys)
            core: Instncia compartilhada de Core (criada em AppSetup)
            chat_service_sync_callback: Callback(chat_id, agent_id) para sincronizar isolatedmain
        """
        # CRITICAL: Validate agents_manager is available
        if agents_manager is None:
            error(
                "[CRITICAL] MessageProcessor initialization failed: agents_manager is None"
            )
            error("[CRITICAL] Cannot process messages without agents configuration")
            error("[CRITICAL] Server will exit now")
            import sys

            sys.exit(1)

        self.chat_manager = chat_manager
        self.agents_manager = agents_manager
        self.config = config
        self.db_manager = DatabaseManager
        self.chat_service_sync_callback = chat_service_sync_callback

        # Use shared Core instance if provided, otherwise create one (for backwards compatibility)
        if core is not None:
            self.core = core
            debug(
                "MessageProcessor using SHARED Core instance (print_used state shared with web-search workers)"
            )
        else:
            self.core = Core(
                message_processor=self,
                chat_manager=chat_manager,
                agents_manager=agents_manager,
                db_manager=self.db_manager,
            )
            debug("MessageProcessor created its own Core instance (legacy mode)")

        self.queue_manager = MultiQueueManager()
        self.cancelled_jobs = set()  # Rastrear jobs cancelados
        self.tools_config = (
            self._load_tools_config()
        )  # Cache da configurao de ferramentas
        debug("MessageProcessor initialized")

    def mark_job_cancelled(self, chat_id: str, job_id: Optional[str] = None):
        """
        Marca um job como cancelado.

        Args:
            chat_id: ID do chat que foi cancelado (legado, mantido para compatibilidade)
            job_id: ID especfico do job para rastreamento
        """
        # Preferir job_id se disponvel, fallback para chat_id
        identifier = job_id or chat_id
        self.cancelled_jobs.add(identifier)
        debug(f"[MessageProcessor] Job marked as cancelled: {identifier}")

    def is_job_cancelled(self, chat_id: str, job_id: Optional[str] = None) -> bool:
        """
        Verifica se um job foi cancelado.

        Args:
            chat_id: ID do chat (legado, mantido para compatibilidade)
            job_id: ID especfico do job para verificao

        Returns:
            True se o job foi cancelado, False caso contrrio
        """
        # Preferir job_id se disponvel para evitar falsos positivos com chat_id compartilhado
        if job_id:
            return job_id in self.cancelled_jobs
        return chat_id in self.cancelled_jobs

    def clear_job_cancelled(self, job_id: str):
        """
        Remove um job do set de cancelados (limpar aps concluso).

        Args:
            job_id: ID do job a remover
        """
        self.cancelled_jobs.discard(job_id)
        debug(f"[MessageProcessor] Cancelled flag cleared for job: {job_id}")

    def _is_image_attachment(self, attachment_id: str, user_id: str) -> bool:
        """
        Verifica se um attachment  uma imagem (por extenso).
        Retorna True se for imagem, False caso contrrio.
        """
        try:
            query = "SELECT extension FROM attachments WHERE attachment_id = :attachment_id AND user_id = :user_id AND deleted_at IS NULL LIMIT 1"
            result = self.db_manager.fetch_one(
                query, {"attachment_id": attachment_id, "user_id": user_id}
            )

            if not result:
                return False

            ext = result.get("extension", "").lower()
            image_extensions = {
                "jpg",
                "jpeg",
                "png",
                "gif",
                "webp",
                "bmp",
                "svg",
                "ico",
            }
            return ext in image_extensions
        except Exception as e:
            debug(f"[IS_IMAGE] Erro ao verificar se  imagem: {e}")
            return False

    def _describe_image_with_ai(self, media_uri: str) -> Optional[str]:
        """
        Chama IA (gpt-4o vision) para descrever uma imagem em detalhes.
        Adapta o prompt baseado no tipo de imagem detectado:
        - UI Web/Layout: foco em estrutura, componentes, wireframe
        - Imagens criativas: anlise profunda de design, cores, emoo, texturas

        Args:
            media_uri: URL temporria da imagem

        Returns:
            Descrio detalhada da imagem ou None se falhar
        """
        try:
            debug(
                f"[IMAGE_DESCRIBE] Iniciando descrio da imagem. URL: {media_uri[:80]}..."
            )
            llm_client = LLMClient(ai="openai", model="gpt-4o")
            debug(f"[IMAGE_DESCRIBE] LLMClient inicializado")

            # Prompt adaptativo que detecta tipo de imagem
            adaptive_prompt = """Primeiro, classifique esta imagem:
-  um layout de UI web, prototipo, wireframe ou interface de aplicao?
-  uma imagem criativa, design, ilustrao, fotografia ou material de marketing?

**Se for UI Web/Layout:**
1. **Resumo**: Tipo de interface (pgina web, app, dashboard, etc) e seu propsito
2. **Estrutura**: Componentes principais, hierarquia, grid, responsividade
3. **Texto**: Transcreva todos os textos, labels, CTAs, navegao
4. **Interatividade**: Elementos clicveis, states, fluxos
5. **Design System**: Cores base, tipografia, componentes reutilizveis

**Se for Imagem Criativa/Design/Fotografia/Marketing:**
1. **Resumo do Contedo**: O que  exatamente? Qual  o propsito? Que tipo de material?

2. **Anlise de Composio Visual**:
   - **Posio dos Elementos**: Descreva EXATAMENTE onde cada elemento est (canto superior esquerdo, centro, etc)
   - **Disposio Geral**: Layout, fluxo visual, pesos visuais, profundidade

3. **Anlise de Cores**:
   - **Paleta de Cores**: Todas as cores predominantes (hex ou descrio)
   - **Regra das 3 Cores**: Identifique cor primria, secundria e acentos (se aplicvel)
   - **Saturao**: Cores vibrantes, pastel, dessaturadas, monocromticas?
   - **Harmonia**: Que tipo de harmonia (complementar, anloga, tridica)?

4. **Anlise de Tipografia**:
   - **Fontes**: Identifique as fontes (serif, sans-serif, script, etc)
   - **Tamanhos de Texto**: Hierarquia (ttulo, subttulo, body, pequeno)
   - **Posicionamento de Texto**: Onde est cada texto? Alinhamentos?
   - **Peso/Estilo**: Bold, regular, light? Maisculas, minsculas?

5. **Anlise de Emoo e Estilo**:
   - **Emoo**: Que sensao transmite? (moderno, clssico, alegre, srio, premium, casual?)
   - **Textura e Acabamento**: Liso, granulado, spero, polido? Efeitos visuais?
   - **Estilo Visual**: Minimalista, maximalist, flat, 3D, handmade, fotogrfico?

6. **Anlise de Qualidade e Iluminao**:
   - **Qualidade da Imagem**: A resoluo  boa, mdia ou baixa? H pixelao, borramento ou compresso visvel?
   - **Iluminao**: Como  a iluminao? (natural, artificial, estdio, contrastada, soft, backlight, frontal?) H sombras? A iluminao  homognea ou dramtica?
   - **Contraste**: Alto contraste, mdio ou baixo contraste?

7. **Transcrio de Texto**: Transcreva EXATAMENTE todo o texto visvel

8. **Detalhes Tcnicos**: Qualquer detalhe importante para recriao perfeita"""

            messages = [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": adaptive_prompt},
                        {"type": "image_url", "image_url": {"url": media_uri}},
                    ],
                }
            ]

            debug(f"[IMAGE_DESCRIBE] Chamando LLM...")
            response = llm_client.chat(messages=messages, temperature=0.7)

            debug(f"[IMAGE_DESCRIBE] Resposta recebida. Type: {type(response)}")

            # A resposta j vem processada pelo LLMClient com a chave 'content' direto
            if response and isinstance(response, dict):
                description = response.get("content", "")
                debug(
                    f"[IMAGE_DESCRIBE] Description extracted (length: {len(description)})"
                )

                if description:
                    debug(
                        f"[IMAGE_DESCRIBE] Descrio da imagem gerada com sucesso (length: {len(description)})"
                    )
                    return description

            warning("[IMAGE_DESCRIBE] Resposta vazia da IA ao descrever imagem")
            return None
        except Exception as e:
            error_msg = str(e)
            if "invalid_image_url" in error_msg or "downloading" in error_msg.lower():
                error(
                    f"[IMAGE_DESCRIBE] Erro ao descrever imagem - Provavelmente ngrok est indisponvel ou URL no  acessvel: {e}"
                )
            else:
                error(f"[IMAGE_DESCRIBE] Erro ao descrever imagem: {e}")
            return None

    def get_template_context(self, template_id: str) -> Optional[dict]:
        """
        Busca o contexto enriquecido de um template de inspirao.

        Retorna apenas os campos essenciais para injeo na mensagem:
        - id, name, description
        - aspect_ratio, prompt (instrues de gerao)
        - url, image

        Args:
            template_id: ID do template (ex: 'insp-14')

        Returns:
            Dict com contexto essencial do template, ou None se no encontrado
        """
        try:
            from App.Core.Services.Inspirations.InspirationRoutes import (
                get_inspiration_by_id,
            )

            template = get_inspiration_by_id(template_id)
            if not template:
                warning(f"[TemplateContext] Template no encontrado: {template_id}")
                return None

            # Construir contexto JSON com apenas campos essenciais
            image_url = template.get("image", "")
            if image_url and not image_url.startswith(("http://", "https://")):
                from App.Core.Settings.Settings import load_config

                config = load_config()
                public_url = config.get("public_url", "").rstrip("/")
                if public_url:
                    image_url = f"{public_url}/{image_url.lstrip('/')}"

            context = {
                "id": template.get("id"),
                "name": template.get("name"),
                "description": template.get("description"),
                "aspect_ratio": template.get("aspect_ratio"),
                "prompt": template.get("prompt"),
                "url": template.get("url"),
                "image": image_url,
            }

            # Remover campos nulos/vazios para manter JSON limpo
            context = {k: v for k, v in context.items() if v is not None and v != ""}

            debug(
                f"[TemplateContext] Contexto enriquecido (JSON) retornado para template: {template_id}"
            )
            return context

        except Exception as e:
            warning(
                f"[TemplateContext] Erro ao buscar contexto do template {template_id}: {e}"
            )
            return None

    def set_sync_callback(self, callback):
        """
        Define callback para sincronizar isolatedmain aps processar mensagem.

        Args:
            callback: Funo(chat_id, agent_id) que sincroniza
        """
        self.chat_service_sync_callback = callback
        debug("[MessageProcessor] Sync callback registrado")

    def _sanitize_final_response(self, response: str) -> str:
        """
        Remove sintaxe literal de ferramentas na resposta final.
        Remove: print(...), task(...), context(...), web-search(...), document(...), mediaai(...), wait(...), message(...)

        Args:
            response: Resposta gerada pelo LLM

        Returns:
            Resposta com sintaxe literal de ferramentas removida
        """
        import re

        if not response:
            return response

        # Remove function call syntax: print(...), task(...), context(...), web-search(...), etc
        # Matches: tool_name(...)
        function_pattern = r"\b(print|task|context|web-search|document|mediaai|wait|quiz|message)\s*\([^)]*\)"
        response = re.sub(function_pattern, "", response, flags=re.IGNORECASE)

        # Remove JSON blocks com "tool": "..."
        json_block_pattern = r'```json\s*\{[^}]*"tool":\s*"[^"]*"[^}]*\}\s*```'
        response = re.sub(
            json_block_pattern, "", response, flags=re.IGNORECASE | re.DOTALL
        )

        # Limpar quebras de linha extras
        response = re.sub(r"\n\s*\n\s*\n+", "\n\n", response).strip()

        return response

    def _load_tools_config(self) -> Dict[str, Any]:
        """
        Carrega configurao de ferramentas do TOOLS.json para cache.
        Utilizado para determinar qual ferramenta retorna JSON estruturado.

        Returns:
            Dict com tool_definitions do TOOLS.json
        """
        try:
            import os

            tools_json_path = os.path.join(
                os.path.dirname(__file__), "..", "Tools", "Tools", "TOOLS.json"
            )

            if os.path.exists(tools_json_path):
                with open(tools_json_path, "r", encoding="utf-8") as f:
                    tools_data = json.load(f)
                    return tools_data.get("tool_definitions", {})
        except Exception as e:
            debug(f"[MessageProcessor] Erro ao carregar TOOLS.json: {e}")

        return {}

    def _should_return_structured_json(self, tool_name: str) -> bool:
        """
        Determina se uma ferramenta deve retornar JSON estruturado.
        L configurao do TOOLS.json via output_structured_json.

        Args:
            tool_name: Nome da ferramenta

        Returns:
            True se output_structured_json=true no TOOLS.json, False caso contrrio
        """
        if not self.tools_config or tool_name not in self.tools_config:
            return False

        tool_def = self.tools_config.get(tool_name, {})
        return tool_def.get("output_structured_json", False)

    @staticmethod
    def _mcp_auditable_output(tool_content: str, args_str: str) -> str:
        """Adiciona o input original ao JSON de output de MCP tools para auditoria."""
        try:
            obj = json.loads(tool_content) if tool_content else {}
            if not isinstance(obj, dict):
                obj = {"result": tool_content}
        except (json.JSONDecodeError, TypeError):
            obj = {"result": tool_content}
        try:
            obj["input"] = (
                json.loads(args_str) if isinstance(args_str, str) else args_str
            )
        except (json.JSONDecodeError, TypeError):
            obj["input"] = args_str
        return json.dumps(obj, ensure_ascii=False)

    def _extract_tool_content(self, tool_result: str, tool_name: str = "") -> str:
        """
        Extrai o contedo legvel do resultado da ferramenta.
        Se for JSON com 'message', extrai o valor.
        Seno, retorna o JSON estruturado como string.
        Tools com output_structured_json=true em TOOLS.json retornam JSON completo.

        Args:
            tool_result: Resultado bruto da ferramenta (pode ser JSON ou string)
            tool_name: Nome da ferramenta (para tratamento especial)

        Returns:
            Contedo legvel da ferramenta (JSON estruturado ou string)
        """
        if not tool_result:
            return ""

        try:
            # Tenta fazer parse como JSON
            parsed = json.loads(tool_result)

            # Tools que devem retornar JSON completo (estruturado)
            # Carregado dinamicamente de TOOLS.json via output_structured_json
            if self._should_return_structured_json(tool_name):
                return (
                    json.dumps(parsed, ensure_ascii=False)
                    if isinstance(parsed, dict)
                    else tool_result
                )

            # Se tem 'message', retorna isso (tools com formatao extra)
            if isinstance(parsed, dict) and "message" in parsed:
                return parsed["message"]

            # Se  um dict (ex: resposta de task/agent), retorna JSON como string
            if isinstance(parsed, dict):
                return json.dumps(parsed, ensure_ascii=False)

            return str(tool_result)
        except (json.JSONDecodeError, ValueError):
            # No  JSON, retorna como est
            return tool_result

    def _get_operation_type(self, tool_name: str) -> OperationType:
        """
        Determina o OperationType baseado no nome da ferramenta.

        TODO: ESTE MTODO EST HARDCODED E NO  USADO.
        Deveria ser dinmico: ler field "operation_type" de TOOLS.json para cada tool
        em vez de manter mapeamento hardcoded aqui.

        Args:
            tool_name: Nome da ferramenta

        Returns:
            OperationType correspondente
        """
        if tool_name == "web-search":
            return OperationType.SCRAPING
        elif tool_name == "gen-img":
            return OperationType.IMAGE_GEN
        elif tool_name == "gen-film":
            return OperationType.VIDEO_GEN
        elif tool_name == "vision":
            return OperationType.VISION
        else:
            return OperationType.IMAGE_GEN  # Fallback

    def _is_queued_tool(self, tool_name: str) -> bool:
        """
        Verifica se a ferramenta deve ser enfileirada ou executada inline.

        Args:
            tool_name: Nome da ferramenta

        Returns:
            True se deve usar fila, False se executar inline
        """
        queued_tools = {"web-search", "asset", "vision"}
        return tool_name in queued_tools

    def _poll_job_result(
        self, chat_id: str, job_id: str, timeout: int = 300
    ) -> Dict[str, Any]:
        """
        Aguarda o resultado de um job enfileirado com retries.

        Args:
            chat_id: ID do chat
            job_id: ID do job
            timeout: Timeout em segundos

        Returns:
            Resultado do job ou erro
        """
        start_time = time.time()
        poll_interval = 2  # segundos
        max_retries = 3

        while (time.time() - start_time) < timeout:
            try:
                result = self.queue_manager.get_job_result(chat_id, job_id)
                if result:
                    debug(f"[MessageProcessor] Job {job_id} result retrieved")
                    return result
            except Exception as e:
                debug(f"[MessageProcessor] Error polling job {job_id}: {e}")

            time.sleep(poll_interval)

        # Timeout alcanado
        error(f"[MessageProcessor] Job {job_id} timeout after {timeout}s")
        return {"success": False, "error": f"Job timeout after {timeout} seconds"}

    def _get_tool_definitions(
        self, agent_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Retorna definies de ferramentas carregadas de TOOLS.json via Core.py.

        MessageProcessor delega para Core.py, que  responsvel por gerenciar ferramentas.

        Args:
            agent_id: ID do agent que est solicitando as ferramentas

        Returns:
            Lista de ferramentas que o agent pode usar (formato OpenAI)
        """
        if not hasattr(self, "core") or self.core is None:
            debug(f"[MessageProcessor] Core no inicializado, retornando lista vazia")
            return []

        tools = self.core.get_available_tools(agent_id=agent_id)
        debug(f"[MessageProcessor] Carregadas {len(tools)} ferramentas para {agent_id}")
        return tools

    def _filter_context_noise_DISABLED(self, isolated_messages: List) -> List:
        """
        Remove tool_calls documentadas (exceto print, task, message, context(help=true)).
        Procura pela ltima tool_call de document() com sucesso.
        Remove todos os tool_calls diferentes de print/task/message/context-help ANTES dela.

        TODO: REVISAR - Esta funo parece ser responsabilidade do SyncManager ou DBManager,
        no do MessageProcessor. MessageProcessor no deveria filtrar histrico de contexto.

        Args:
            isolated_messages: Lista de IsolatedMessage objects do banco

        Returns:
            Lista filtrada de IsolatedMessage objects
        """
        if not isolated_messages:
            return isolated_messages

        # Encontrar a LTIMA tool_call de document com sucesso
        last_document_success_index = -1

        for i, msg in enumerate(isolated_messages):
            if msg.type == "tool_call" and msg.role == "assistant":
                try:
                    content_json = json.loads(msg.content)
                    # Procurar por: "success": true, "tool": "document"
                    if (
                        content_json.get("success") == True
                        and content_json.get("tool") == "document"
                    ):
                        last_document_success_index = i
                        debug(f"[MessageProcessor] Found document success at index {i}")
                except:
                    pass

        # Se no encontrou document com sucesso, retornar sem filtrar
        if last_document_success_index == -1:
            debug(
                f"[MessageProcessor] No successful document() found, no filtering needed"
            )
            return isolated_messages

        # IDs de ferramentas que devem ser mantidas sempre
        keep_tools = {"print", "task", "message", "context"}
        tools_to_remove_uuids = set()

        # Marcar para remoo: todas as tool_calls ANTES da ltima document,
        # EXCETO print, task, message, e context(help=true)
        for i in range(last_document_success_index):
            msg = isolated_messages[i]
            if msg.type == "tool_call" and msg.role == "assistant":
                try:
                    content_json = json.loads(msg.content)
                    tool_name = content_json.get("tool", "")

                    # Manter: print, task, message
                    if tool_name in {"print", "task", "message"}:
                        continue

                    # Manter: context(help=true) - ignorar context(context=true)
                    if tool_name == "context":
                        args = content_json.get("args", {})
                        if args.get("help") == True:
                            continue

                    # Remover: tudo o mais (web-search, asset, vision, etc)
                    tools_to_remove_uuids.add(msg.uuid)
                    debug(
                        f"[MessageProcessor] Marked for removal: {tool_name} {msg.uuid[:8]}..."
                    )
                except:
                    pass

        # Filtrar: remover tool_calls e suas respostas (OUTPUT com mesmo UUID)
        filtered = []
        for msg in isolated_messages:
            if msg.uuid in tools_to_remove_uuids:
                debug(
                    f"[MessageProcessor] Removing: {msg.uuid[:8]}... (type={msg.type})"
                )
                continue
            filtered.append(msg)

        debug(
            f"[MessageProcessor] Context noise filtering: {len(isolated_messages)}  {len(filtered)} messages"
        )
        return filtered

    def _check_and_load_signin_if_missing(
        self, agent_id: str, chat_id: str, user_id: int, job_id: Optional[str]
    ) -> Optional[str]:
        """
        Verifica se business_canvas ou brand_communication esto faltando (coluna tool_type).
        Se um dos dois faltar, carrega apenas o SIGNIN.md no SystemPrompt.

        OBS: Skills (SkillBusinessCanvas, SkillBranding) NO so mais injetados aqui.
        O user deve usar lookup(skill='...') para consult-los quando necessrio.

        Returns:
            Contedo do SIGNIN.md, None caso contrrio
        """
        try:
            # Chamar context(type="document") para listar documentos
            documents_result = self.core.execute_tool(
                tool_name="context",
                arguments=json.dumps({"type": "document"}),
                agent_id=agent_id,
                chat_id=chat_id,
                user_id=user_id,
                job_id=job_id,
            )

            if not documents_result:
                debug(
                    f"[MessageProcessor] Nenhum documento encontrado - carregando SIGNIN.md"
                )
                signin_content = self._load_signin_md()
                return signin_content

            documents_json = json.loads(documents_result)
            documents = documents_json.get("documents", [])

            # Verificar se business_canvas e brand_communication existem (verificar coluna tool_type)
            has_business_canvas = any(
                doc.get("tool_type") == "business_canvas" for doc in documents
            )
            has_brand_communication = any(
                doc.get("tool_type") == "brand_communication" for doc in documents
            )

            # Se um dos dois faltar, carregar APENAS SIGNIN.md
            if not has_business_canvas or not has_brand_communication:
                debug(
                    f"[MessageProcessor] Faltam documentos - business_canvas: {has_business_canvas}, brand_communication: {has_brand_communication}"
                )
                debug(
                    f"[MessageProcessor] Carregando SIGNIN.md (skills devem ser consultados via lookup)"
                )
                signin_content = self._load_signin_md()
                return signin_content

            debug(
                f"[MessageProcessor]  Business Canvas e Brand Communication encontrados"
            )
            return None

        except Exception as e:
            debug(f"[MessageProcessor] Erro ao verificar documentos: {e}")
            return None

    # DEPRECATED: _load_missing_skills_lookups() removido
    # Razo: Skills no so mais injetados automaticamente no SystemPrompt
    # Users devem consultar skills via lookup(skill='...') quando necessrio
    # Isto garante que eles aprendam a estrutura correta antes de criar documentos

    def _load_skill_file(self, filename: str) -> Optional[str]:
        """
        Carrega contedo de um arquivo skill (.Agent/filename).

        Args:
            filename: Nome do arquivo (ex: SkillBranding.md, SkillBusinessCanvas.md)

        Returns:
            Contedo do arquivo ou None se no encontrado
        """
        try:
            skill_path = (
                Path(__file__).parent.parent / "Agents" / "Agents" / ".Agent" / filename
            )

            if skill_path.exists():
                with open(skill_path, "r", encoding="utf-8") as f:
                    content = f.read()
                    debug(
                        f"[MessageProcessor]  {filename} carregado ({len(content)} chars)"
                    )
                    return content
            else:
                debug(f"[MessageProcessor]  {filename} no encontrado em {skill_path}")
                return None

        except Exception as e:
            debug(f"[MessageProcessor] Erro ao carregar {filename}: {e}")
            return None

    def _get_agent_instructions_list(self) -> Optional[Dict[str, str]]:
        """
        Lista todos os arquivos .md na pasta .\\.Agent e retorna seus titulos.
        Permite que o agente descubra dinamicamente as instrucoes disponiveis.

        Returns:
            Dict com {nome_arquivo: titulo_extraido} ou None se pasta nao existir
        """
        try:
            instructions_dir = (
                Path(__file__).parent.parent / "Agents" / "Agents" / ".Agent"
            )

            if not instructions_dir.exists():
                debug(
                    f"[MessageProcessor]  Pasta .Agent no encontrada: {instructions_dir}"
                )
                return None

            instructions = {}

            # Itera sobre arquivos .md na pasta
            for md_file in sorted(instructions_dir.glob("*.md")):
                try:
                    with open(md_file, "r", encoding="utf-8") as f:
                        # L primeira linha para extrair ttulo
                        first_line = f.readline().strip()

                        # Remove markdown heading markers (#, ##, etc)
                        title = first_line.lstrip("#").strip()

                        # Se no conseguir extrair do ttulo, usa nome do arquivo
                        if not title:
                            title = md_file.stem.replace("_", " ").title()

                        instructions[md_file.name] = title
                        debug(
                            f"[MessageProcessor]  Instruo carregada: {md_file.name}  {title[:60]}..."
                        )

                except Exception as e:
                    warning(f"[MessageProcessor]  Erro ao ler {md_file.name}: {e}")
                    continue

            if instructions:
                debug(
                    f"[MessageProcessor]  {len(instructions)} arquivos de instruo encontrados"
                )
                return instructions
            else:
                debug(
                    f"[MessageProcessor]  Nenhum arquivo .md encontrado em {instructions_dir}"
                )
                return None

        except Exception as e:
            error(f"[MessageProcessor] Erro ao listar instrues: {e}")
            return None

    def _load_signin_md(self) -> Optional[str]:
        """
        Carrega o contedo do arquivo SignIn.md para injetar no contexto.

        Returns:
            Contedo do SignIn.md ou None se no encontrado
        """
        try:
            # Tenta carregar de .\.Agent\SignIn.md (caminho relativo)
            signin_path = (
                Path(__file__).parent.parent
                / "Agents"
                / "Agents"
                / ".Agent"
                / "SignIn.md"
            )

            if signin_path.exists():
                with open(signin_path, "r", encoding="utf-8") as f:
                    signin_content = f.read()
                    debug(
                        f"[MessageProcessor]  SignIn.md carregado ({len(signin_content)} chars)"
                    )
                    return signin_content
            else:
                warning(f"[MessageProcessor]  SignIn.md no encontrado em {signin_path}")
                return None
        except Exception as e:
            error(f"[MessageProcessor] Erro ao carregar SignIn.md: {e}")
            return None

    def _get_consolidated_context(
        self,
        agent_id: str,
        agent_name: str,
        chat_id: str,
        user_id: int,
        job_id: Optional[str],
    ) -> Dict[str, Any]:
        """
        Obtm contexto consolidado (tools_instructions, user_info, calendar, signin_guidance).
        Retorna dict para ser combinado com system_prompt em uma nica mensagem.

        Returns:
            Dict com {tools_instructions, user_info, calendar, signin_guidance}
        """
        # Executar ferramentas para consolidar contexto
        tools_instructions = None
        user_info = None
        calendar_data = None

        # 1. Obter instrues das ferramentas via context(type="instructions")
        try:
            instructions_result = self.core.execute_tool(
                tool_name="context",
                arguments=json.dumps({"type": "instructions"}),
                agent_id=agent_id,
                chat_id=chat_id,
                user_id=user_id,
                job_id=job_id,
            )
            if instructions_result:
                instructions_json = json.loads(instructions_result)
                if instructions_json.get("success"):
                    tools_instructions = instructions_json.get("help")
                    debug(f"[MessageProcessor]  Tools instructions obtidas")
        except Exception as e:
            debug(f"[MessageProcessor] Erro ao obter tools instructions: {e}")

        # 2. Obter informaes do usurio via context(type="client")
        try:
            client_result = self.core.execute_tool(
                tool_name="context",
                arguments=json.dumps({"type": "client"}),
                agent_id=agent_id,
                chat_id=chat_id,
                user_id=user_id,
                job_id=job_id,
            )
            if client_result:
                client_json = json.loads(client_result)
                if client_json.get("success"):
                    user_info = client_json
                    debug(f"[MessageProcessor]  User info obtida")
        except Exception as e:
            debug(f"[MessageProcessor] Erro ao obter user info: {e}")

        # 3. Obter calendrio de posts (agendamentos do usurio)
        try:
            schedules_result = self.core.execute_tool(
                tool_name="calendar",
                arguments=json.dumps({"calendar": "schedules"}),
                agent_id=agent_id,
                chat_id=chat_id,
                user_id=user_id,
                job_id=job_id,
            )
            if schedules_result:
                schedules_json = json.loads(schedules_result)
                if schedules_json.get("success"):
                    calendar_data = schedules_json
                    total_posts = schedules_json.get("total_calendar", 0)
                    debug(
                        f"[MessageProcessor]  Calendar com {total_posts} posts agendados obtido"
                    )
        except Exception as e:
            debug(f"[MessageProcessor] Erro ao obter calendar schedules: {e}")

        # 5. Verificar se briefing ou business_canvas faltam e carregar SIGNIN.md
        signin_guidance = self._check_and_load_signin_if_missing(
            agent_id=agent_id, chat_id=chat_id, user_id=user_id, job_id=job_id
        )

        # 6. Listar instrues escalveis disponveis na pasta .Agent
        agent_instructions_list = self._get_agent_instructions_list()

        return {
            "tools_instructions": tools_instructions,
            "user_info": user_info,
            "calendar": calendar_data,
            "signin_guidance": signin_guidance,
            "agent_instructions_list": agent_instructions_list,
        }

    def process_message(
        self,
        job_id: str,
        user_message: str,
        agent_id: str = "orchestrator-global",
        chat_id: Optional[str] = None,
        user_id: Optional[str] = None,
        message_id: Optional[str] = None,
        job: Optional[object] = None,
        attachment: Optional[Dict[str, str]] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> ProcessResult:
        """
        Processa uma mensagem de usurio usando um agente especfico.

        Args:
            job_id: ID do job de processamento
            user_message: Mensagem do usurio
            agent_id: ID do agente a usar
            chat_id: ID do chat principal (para sincronizao)
            user_id: ID do usurio (para banco isolado e consumo de crditos)
            message_id: ID da mensagem do user (j salvo em main_chat, ser usado como isolated_message_id)
            job: Objeto do job para marcar como completo quando resposta final  salva

        Returns:
            ProcessResult com resposta e metadados
        """
        db_session = None
        sync_enqueued = False  # True when enqueue_sync_message succeeds; defers mark_completed to SyncWorker
        waiting_for_tool = (
            False  # Initialized early so finally block never hits UnboundLocalError
        )
        waiting_tool_name = None
        try:
            debug(f"[MessageProcessor] Processing message with agent: {agent_id}")

            # Recuperar job do job_manager se no foi fornecido mas job_id existe
            if not job and job_id:
                try:
                    from App.Features.Job import get_job_manager

                    job_manager = get_job_manager()
                    job = job_manager.get_job(job_id)
                    if job:
                        debug(
                            f"[MessageProcessor] Job {job_id} recuperado do job_manager"
                        )
                    else:
                        debug(
                            f"[MessageProcessor] Job {job_id} no encontrado no job_manager"
                        )
                except Exception as e:
                    debug(
                        f"[MessageProcessor] Erro ao recuperar job do job_manager: {e}"
                    )

            #  VERIFICAR E RESETAR CRDITOS SE NECESSRIO
            if user_id:
                CreditsManager.reset_credits_if_needed(user_id)
                has_credits, available = CreditsManager.check_credits(user_id)
                debug(
                    f"[MessageProcessor] Usurio {user_id}: {available} crditos disponveis"
                )

            # 1. Carrega configurao do agente
            agent = self.agents_manager.get_agent(agent_id)
            if not agent:
                error(f"Agent {agent_id} not found")
                return ProcessResult(
                    success=False,
                    response="",
                    agent_id=agent_id,
                    model="unknown",
                    tokens_used={"input": 0, "output": 0},
                    error=f"Agent {agent_id} not found",
                )

            # Obtm nome do agente para logging
            agent_name = agent.get("name", agent_id)

            # 1.5. Se h attachment do tipo "template", buscar contexto e concatenar  mensagem
            has_template_attachment = False
            media_uri = None
            if attachment and isinstance(attachment, dict):
                attachment_type = attachment.get("attachment_type")
                attachment_id = attachment.get("attachment_id")

                if attachment_type == "template" and attachment_id:
                    template_context = self.get_template_context(attachment_id)
                    if template_context:
                        # Injetar contexto do template como JSON no incio da mensagem
                        template_json = json.dumps(
                            template_context, ensure_ascii=False, indent=2
                        )
                        user_message = (
                            f"[TEMPLATE]\n{template_json}\n\n---\n\n{user_message}"
                        )
                        has_template_attachment = True
                        debug(
                            f"[MessageProcessor]  Template context injetado como JSON no incio da mensagem (template_id: {attachment_id})"
                        )
                    else:
                        warning(
                            f"[MessageProcessor]  Template no encontrado ou sem contexto: {attachment_id}"
                        )

                elif attachment_type == "file" and attachment_id:
                    # Buscar nome do arquivo para referência no terminal
                    try:
                        _file_row = self.db_manager.fetch_one(
                            "SELECT file_name, extension FROM attachments WHERE attachment_id = :aid AND user_id = :uid AND deleted_at IS NULL LIMIT 1",
                            {"aid": attachment_id, "uid": user_id},
                        )
                        _file_name = (
                            (_file_row.get("file_name") or attachment_id)
                            if _file_row
                            else attachment_id
                        )
                    except Exception:
                        _file_name = attachment_id

                    is_image = self._is_image_attachment(attachment_id, user_id)
                    if is_image:
                        from App.Features.Tools._asset import (
                            _attachment_as_base64,
                            _call_vision_with_fallback,
                        )

                        image_data_uri = _attachment_as_base64(attachment_id, user_id)
                        image_description = None
                        if image_data_uri:
                            _prompt = (
                                "Descreva detalhadamente esta imagem: layout, cores, elementos visuais, "
                                "texto, design, estilo e qualquer aspecto relevante."
                            )
                            image_description = _call_vision_with_fallback(
                                image_data_uri, _prompt
                            )

                        if image_description:
                            user_message = f"[IMAGEM: {_file_name} (id: {attachment_id})]\n\n[DESCRIÇÃO TÉCNICA DA IMAGEM]:\n{image_description}\n\n---\n\n{user_message}"
                        else:
                            user_message = f"[IMAGEM: {_file_name} (id: {attachment_id})]\n\n---\n\n{user_message}"
                        debug(
                            f"[MessageProcessor] Image vision injected for {attachment_id} ({_file_name})"
                        )
                    else:
                        _note = f"[ARQUIVO: {_file_name} (id: {attachment_id})]"
                        user_message = (
                            f"{_note}\n\n{user_message}"
                            if user_message.strip()
                            else _note
                        )
                        debug(
                            f"[MessageProcessor] File note injected for {attachment_id} ({_file_name})"
                        )

            # 1.6. Injetar referências de arquivos do Google Drive (do context)
            if context and isinstance(context, dict):
                drive_files = context.get("drive_files")
                if drive_files and isinstance(drive_files, list):
                    refs = "\n".join(
                        f'[Google Drive: "{f.get("name", "")}" — id: {f.get("file_id", "")}]'
                        for f in drive_files
                        if f.get("file_id")
                    )
                    if refs:
                        user_message = (
                            f"{user_message.strip()}\n\n{refs}"
                            if user_message.strip()
                            else refs
                        )
                        debug(
                            f"[MessageProcessor] Drive file refs injetados ({len(drive_files)} arquivos)"
                        )

            # 2. Criar/obter chat isolado no banco de dados se user_id fornecido
            isolated_chat = None
            if chat_id and user_id:
                db_session = self.db_manager.get_session()
                isolated_chat = self.db_manager.get_or_create_isolated_chat(
                    session=db_session,
                    chat_id=chat_id,
                    user_id=user_id,
                    agent_id=agent_id,
                )
                debug(
                    f"[MessageProcessor] Isolated chat created/retrieved: {isolated_chat.id}"
                )

                # 2.1. Salvar system prompt como PRIMEIRA mensagem (antes de user message)
                agent = self.agents_manager.get_agent(agent_id)
                if agent and isolated_chat and db_session:
                    system_prompt = agent.get(
                        "system_prompt", "Voc  um assistente til."
                    )

                    # Verificar se system_prompt j foi salvo (evitar duplicatas)
                    debug(
                        f"[MessageProcessor] Checking for existing system message with isolated_chat_id={isolated_chat.chat_id}"
                    )
                    try:
                        existing_system = (
                            db_session.query(IsolatedMessage)
                            .filter(
                                IsolatedMessage.isolated_chat_id
                                == isolated_chat.chat_id,
                                IsolatedMessage.role == "system",
                            )
                            .first()
                        )
                        debug(
                            f"[MessageProcessor] Query executed successfully. Existing system: {existing_system}"
                        )
                    except Exception as query_err:
                        error(
                            f"[MessageProcessor] Error querying for existing system message: {query_err}"
                        )
                        existing_system = None

                    if not existing_system and system_prompt:
                        debug(
                            f"[MessageProcessor] Saving system prompt with consolidated context... (system_prompt_len={len(system_prompt)})"
                        )
                        try:
                            # CONSOLIDAR SYSTEM PROMPT + CONTEXTO EM UMA NICA MENSAGEM
                            consolidated_data = self._get_consolidated_context(
                                agent_id=agent_id,
                                agent_name=agent_id,
                                chat_id=chat_id,
                                user_id=user_id,
                                job_id=job_id,
                            )

                            # Combinar system_prompt + consolidated_context em um JSON
                            combined_message = {
                                "type": "system",
                                "system_prompt": system_prompt,
                                "tools_instructions": consolidated_data.get(
                                    "tools_instructions"
                                ),
                                "user_info": consolidated_data.get("user_info"),
                                "calendar": consolidated_data.get("calendar"),
                            }

                            # Injetar skills de marca quando contexto indica brand_analysis
                            _is_brand_analysis = (
                                context
                                and isinstance(context, dict)
                                and context.get("brand_analysis")
                            )

                            _, doc_status = self.core._check_required_documents_exist()

                            if _is_brand_analysis:
                                # Análise de marca autônoma: injetar ambas as skills + ToolBrand
                                skill_bc_content = self._load_skill_file(
                                    "SkillBusinessCanvas.md"
                                )
                                if skill_bc_content:
                                    combined_message[
                                        "skill_business_canvas"
                                    ] = skill_bc_content
                                skill_bi_content = self._load_skill_file(
                                    "SkillBrandIdentity.md"
                                )
                                if skill_bi_content:
                                    combined_message[
                                        "skill_brand_identity"
                                    ] = skill_bi_content
                                tool_brand_content = self._load_skill_file(
                                    "Tools/ToolBrand.md"
                                )
                                if tool_brand_content:
                                    combined_message["tool_brand"] = tool_brand_content
                                debug(
                                    "[MessageProcessor] brand_analysis: SkillBusinessCanvas + SkillBrandIdentity + ToolBrand injetadas"
                                )
                            elif not doc_status.get("business_canvas"):
                                # Fluxo normal: injetar SkillBusinessCanvas quando não existe business_canvas
                                skill_bc_content = self._load_skill_file(
                                    "SkillBusinessCanvas.md"
                                )
                                if skill_bc_content:
                                    combined_message[
                                        "skill_business_canvas"
                                    ] = skill_bc_content
                                    debug(
                                        f"[MessageProcessor]  skill_business_canvas injected (user has no business_canvas)"
                                    )

                            # Injetar custom_skills ativas do usuário
                            if user_id:
                                try:
                                    from App.Core.Crunch.TablesSQL.DBManager import (
                                        DatabaseManager,
                                    )
                                    from App.Core.Services.Skills.SkillsService import (
                                        SkillsService,
                                    )

                                    _skills_service = SkillsService()
                                    active_skills = DatabaseManager.execute_transaction(
                                        lambda session: _skills_service.list_active_skills(
                                            session, str(user_id)
                                        )
                                    )
                                    if active_skills:
                                        skills_lines = "\n".join(
                                            f"- \"{s['name']}\" (id: {s['id']})"
                                            + (
                                                f" — {s['description']}"
                                                if s.get("description")
                                                else ""
                                            )
                                            for s in active_skills
                                        )
                                        skills_block = (
                                            "O usuário possui as seguintes skills personalizadas ativas. "
                                            "Use skill(action='read', skill_id='<id>') para carregar o conteúdo completo de uma skill quando o usuário solicitar seu uso.\n\n"
                                            + skills_lines
                                        )
                                        combined_message["custom_skills"] = skills_block
                                        debug(
                                            f"[MessageProcessor]  {len(active_skills)} custom skill(s) listada(s) no system prompt (sem conteúdo)"
                                        )
                                except Exception as skill_err:
                                    debug(
                                        f"[MessageProcessor] Erro ao injetar custom skills: {skill_err}"
                                    )

                            self.db_manager.save_isolated_message(
                                session=db_session,
                                isolated_chat_id=isolated_chat.chat_id,
                                agent_id=agent_id,
                                agent=agent_id,
                                role="system",
                                content=json.dumps(
                                    combined_message, ensure_ascii=False, indent=2
                                ),
                                message_type="message",
                            )
                            debug(
                                f"[MessageProcessor]  System prompt + consolidated context saved as FIRST message to isolated chat {isolated_chat.id}"
                            )
                        except Exception as sys_err:
                            error(
                                f"[MessageProcessor] Error saving system prompt with context: {sys_err}"
                            )

            # 3. Salva mensagem do usurio no histrico
            # Prioridade: Banco isolado > ChatManager (fallback)
            # NO SALVA se vem de AgentHandler (task_name: ... indica isso)
            debug(
                f"[MessageProcessor] About to save user message (isolated_chat={isolated_chat is not None}, db_session={db_session is not None})"
            )
            if isolated_chat and db_session:
                # Limpar contedo da mensagem (remover task_name e JSON)
                cleaned_content = user_message
                is_from_agent_handler = "task_name:" in cleaned_content.lower()

                # Remover task_name se existir
                if is_from_agent_handler:
                    lines = cleaned_content.split("\n")
                    cleaned_content = "\n".join(
                        [l for l in lines if "task_name:" not in l.lower()]
                    ).strip()

                # Tentar extrair contedo legvel se for JSON
                quiz_response_data = None
                try:
                    parsed = json.loads(cleaned_content)
                    # Detectar se  resposta de quiz: {"tool": "quiz", "uuid": "...", "answer": "..."}
                    if (
                        isinstance(parsed, dict)
                        and parsed.get("tool") == "quiz"
                        and "uuid" in parsed
                    ):
                        quiz_response_data = parsed
                        debug(
                            f"[MessageProcessor] Detected quiz response with UUID: {parsed.get('uuid')}"
                        )
                    elif isinstance(parsed, dict) and "message" in parsed:
                        cleaned_content = parsed["message"]
                except:
                    pass

                # Se for resposta de quiz, buscar pergunta anterior e adicionar answers ao contedo original
                if quiz_response_data:
                    try:
                        # Tentar quiz_call_id primeiro (novo formato), depois uuid (compatibilidade)
                        quiz_uuid = quiz_response_data.get(
                            "quiz_call_id"
                        ) or quiz_response_data.get("uuid")
                        quiz_answers = quiz_response_data.get("answers", [])

                        # Buscar a mensagem anterior do quiz (INPUT) para pegar o contedo original
                        quiz_input_msg = (
                            db_session.query(IsolatedMessage)
                            .filter(
                                IsolatedMessage.isolated_chat_id
                                == isolated_chat.chat_id,
                                IsolatedMessage.isolated_message_id == quiz_uuid,
                                IsolatedMessage.role
                                == "assistant",  # INPUT  role=assistant
                                IsolatedMessage.type == "tool_call",
                            )
                            .first()
                        )

                        if quiz_input_msg:
                            # Parsear o contedo original para adicionar as respostas
                            try:
                                # O contedo original tem formato "Tool: quiz\nArgs: {...}"
                                original_content = quiz_input_msg.content

                                # Parsear os args originais
                                if "Args: " in original_content:
                                    args_part = original_content.split("Args: ", 1)[1]
                                    args_json = json.loads(args_part)

                                    # Adicionar final_answers aos args
                                    args_json["final_answers"] = quiz_answers

                                    # Preparar contedo final com resposta includa
                                    final_content = f"Tool: quiz\nArgs: {json.dumps(args_json, ensure_ascii=False)}"
                                else:
                                    final_content = original_content
                            except Exception as parse_err:
                                debug(
                                    f"[MessageProcessor] Erro ao parsear quiz original, usando como est: {parse_err}"
                                )
                                final_content = original_content

                            # Salvar como OUTPUT da tool quiz com o contedo completo (com respostas)
                            self.db_manager.save_isolated_message(
                                session=db_session,
                                isolated_chat_id=isolated_chat.chat_id,
                                agent_id="user",
                                agent="USER",
                                role="user",
                                content=final_content,  # Contedo completo com answers
                                message_type="tool_call",
                                tool_call_id=quiz_uuid,  # Usar tool_call_id para agrupar com INPUT
                                isolated_message_id=quiz_uuid,
                                tool_called="quiz",
                                tool_call_type="output",
                            )
                            debug(
                                f"[MessageProcessor]  Quiz response saved com contedo completo (UUID: {quiz_uuid})"
                            )
                        else:
                            debug(
                                f"[MessageProcessor]  Quiz INPUT no encontrado para UUID {quiz_uuid}, salvando resposta simples"
                            )
                            # Fallback: salvar resposta simples
                            quiz_output = {
                                "success": True,
                                "tool": "quiz",
                                "uuid": quiz_uuid,
                                "answers": quiz_answers,
                            }
                            self.db_manager.save_isolated_message(
                                session=db_session,
                                isolated_chat_id=isolated_chat.chat_id,
                                agent_id="user",
                                agent="USER",
                                role="user",
                                content=json.dumps(quiz_output, ensure_ascii=False),
                                message_type="tool_call",
                                isolated_message_id=quiz_uuid,
                                tool_called="quiz",
                                tool_call_type="output",
                            )

                        # Enfileirar sincronizao imediata para sync isolated  main
                        try:
                            self.queue_manager.enqueue_sync_message(
                                chat_id=chat_id, agent_id="user", job_id=job_id
                            )
                            sync_enqueued = True
                            debug(
                                f"[MessageProcessor]  Sync enfileirado para resposta do quiz"
                            )
                        except Exception as sync_err:
                            warning(
                                f"[MessageProcessor] Erro ao enfileirar sync da resposta do quiz: {sync_err}"
                            )
                    except Exception as quiz_err:
                        error(
                            f"[MessageProcessor] Error saving quiz response: {quiz_err}"
                        )
                        raise
                    # Skip saving as normal user message
                else:
                    # S salva como "user" se for mensagem DIRETA do usurio
                    # Se vem de AgentHandler, ser salva pelo AgentHandler como "orchestrator-global"
                    if not is_from_agent_handler:
                        # VERIFICAR SE MENSAGEM J EXISTE (evita IntegrityError em retomadas de tool)
                        existing_msg = None
                        if message_id:
                            existing_msg = (
                                db_session.query(IsolatedMessage)
                                .filter(
                                    IsolatedMessage.isolated_chat_id
                                    == isolated_chat.chat_id,
                                    IsolatedMessage.isolated_message_id == message_id,
                                )
                                .first()
                            )

                        if existing_msg:
                            debug(
                                f"[MessageProcessor] Message {message_id} already exists in isolated chat, skipping save"
                            )
                        else:
                            debug(
                                f"[MessageProcessor] Saving user message to DB (not from AgentHandler)"
                            )
                            debug(
                                f"[MessageProcessor] Before save_isolated_message call: isolated_chat_id={isolated_chat.chat_id}, content_len={len(cleaned_content)}, message_id={message_id}, has_template_attachment={has_template_attachment}"
                            )
                            try:
                                # trigger_display sobrepõe o prompt bruto para exibição no chat
                                display_content = (
                                    context.get("trigger_display") or cleaned_content
                                    if context
                                    else cleaned_content
                                )
                                result = self.db_manager.save_isolated_message(
                                    session=db_session,
                                    isolated_chat_id=isolated_chat.chat_id,
                                    agent_id="user",
                                    agent="USER",
                                    role="user",
                                    content=display_content,
                                    message_type="message",
                                    isolated_message_id=message_id,  #  Usar o message_id da main_chat
                                )
                                debug(
                                    f"[MessageProcessor] save_isolated_message returned successfully: {result}"
                                )
                                if has_template_attachment:
                                    debug(
                                        f"[MessageProcessor]  User message saved with TEMPLATE ATTACHMENT (template_id: {attachment.get('attachment_id')})"
                                    )
                                else:
                                    debug(
                                        f"[MessageProcessor] User message saved to isolated chat {isolated_chat.id}"
                                    )
                            except Exception as user_msg_err:
                                error(
                                    f"[MessageProcessor] Error saving user message: {user_msg_err}"
                                )
                                raise
                    else:
                        debug(
                            f"[MessageProcessor] Skipping user message save (from AgentHandler, will be saved by orchestrator)"
                        )
            else:
                self.chat_manager.save_message(
                    job_id=job_id,
                    role="user",
                    content=user_message,
                    agent_id=agent_id,
                )
                debug(f"[MessageProcessor] User message saved to isolated chat")

            # 3. Obtm histrico de conversa
            # Prepara histrico para LLM
            # Se h isolated_chat, carregar mensagens do banco isolado
            # Caso contrrio, usar session.conversation_history
            compacted_context = None  # Pode ser usado na system_prompt
            cut_message_isolated_message_id_for_filtering = None

            if isolated_chat and db_session:
                debug(
                    f"[MessageProcessor] Carregando mensagens do isolated_chat {isolated_chat.id}"
                )
                isolated_messages = (
                    db_session.query(IsolatedMessage)
                    .filter(IsolatedMessage.isolated_chat_id == isolated_chat.chat_id)
                    .all()
                )

                # 3.0. Filtrar rudo de context=true documentadas
                # TODO: DISABLED - Esta responsabilidade pertence ao SyncManager, no ao MessageProcessor
                # isolated_messages = self._filter_context_noise(isolated_messages)

                # 3.1. Verificar se h contexto compactado disponvel
                from App.Core.Crunch.TablesSQL.Models import ContextWindow

                latest_context_window = (
                    db_session.query(ContextWindow)
                    .filter(ContextWindow.isolated_chat_id == isolated_chat.chat_id)
                    .order_by(ContextWindow.created_at.desc())
                    .first()
                )

                if latest_context_window:
                    compacted_context = latest_context_window.context_generated
                    cut_message_isolated_message_id_for_filtering = (
                        latest_context_window.cut_message_isolated_message_id
                    )
                    debug(
                        f"[MessageProcessor] Contexto compactado encontrado (cut_uuid: {cut_message_isolated_message_id_for_filtering[:8]}...)"
                    )

                    # Filtrar mensagens para incluir apenas aquelas aps cut_message_isolated_message_id
                    cut_index = -1
                    for i, msg in enumerate(isolated_messages):
                        if str(msg.uuid) == str(
                            cut_message_isolated_message_id_for_filtering
                        ):
                            cut_index = i
                            break

                    if cut_index >= 0:
                        # Incluir a mensagem do cut point e todas aps
                        isolated_messages = isolated_messages[cut_index:]
                        debug(
                            f"[MessageProcessor] Filtrando mensagens aps cut point (ndice {cut_index})"
                        )

                _window = isolated_messages[-40:]
                # Garante que as mensagens iniciais (system/user com o pedido original) não sejam cortadas
                # quando há muitas tool calls acumuladas.
                if isolated_messages and isolated_messages[0] not in _window:
                    _anchor = []
                    for _m in isolated_messages:
                        if _m.role in ("system", "user"):
                            _anchor.append(_m)
                        if len(_anchor) >= 2:
                            break
                    _window_ids = {id(_m) for _m in _window}
                    _prepend = [_m for _m in _anchor if id(_m) not in _window_ids]
                    if _prepend:
                        _window = _prepend + list(_window)
                messages = [
                    {"role": msg.role, "content": msg.content} for msg in _window
                ]
                debug(
                    f"[MessageProcessor] {len(messages)} mensagens carregadas do isolated_chat (compacted_context: {compacted_context is not None})"
                )
            else:
                debug(
                    f"[MessageProcessor] Carregando mensagens da session.conversation_history"
                )
                messages = [
                    {
                        "role": "user" if msg["role"] == "user" else "assistant",
                        "content": msg["content"],
                    }
                    for msg in session.conversation_history[
                        -40:
                    ]  # últimas 40 mensagens
                ]
                debug(
                    f"[MessageProcessor] {len(messages)} mensagens carregadas da session"
                )

            # 4. Obtm system prompt do agente (j foi salvo como primeira mensagem em 2.1)
            system_prompt = agent.get("system_prompt", "Voc  um assistente til.")

            # 4.1. Se h contexto compactado, incluir na system_prompt
            if compacted_context:
                system_prompt = f"""{system_prompt}

---

## Contexto Compactado da Conversa Anterior

{compacted_context}

---

Considere o contexto acima para continuar a conversa de forma consistente."""
                debug(
                    f"[MessageProcessor] Sistema prompt atualizado com contexto compactado"
                )

            # 5. Inicializa LLMClient com modelo do agente
            ai_provider = agent.get("ai", "openai")
            model = agent.get("model", "gpt-4o-mini")

            try:
                llm_client = LLMClient(ai=ai_provider, model=model)
                debug(
                    f"[MessageProcessor] LLMClient initialized: {ai_provider}/{model}"
                )
            except Exception as e:
                error(f"Failed to initialize LLMClient: {e}")
                return ProcessResult(
                    success=False,
                    response="",
                    agent_id=agent_id,
                    model=model,
                    tokens_used={"input": 0, "output": 0},
                    error=f"Failed to initialize LLM: {str(e)}",
                )

            # 6. Obtm definies de ferramentas (filtradas para este agent)
            # Garantir current_user_id antes de injetar ferramentas MCP
            if user_id and self.core:
                self.core.current_user_id = user_id
            tool_definitions = self._get_tool_definitions(agent_id=agent_id)

            # 7. Loop de execuo com tool handling
            ai_response = ""
            total_input_tokens = 0
            total_output_tokens = 0
            max_tool_iterations = 50  # Batch format: 1 print + 1 batch task create + 15 updates + extras (web-search, mediaai, etc)
            iteration = 0
            tool_calls = (
                []
            )  # Inicializar antes do loop para evitar UnboundLocalError se o job for cancelado antes da primeira iteração
            waiting_for_tool = (
                False  # Flag para parar iteraes quando wait() est aguardando
            )
            waiting_tool_name = None  # Track which tool caused the waiting state (only 'quiz' sets job status to waiting)
            # Flag para trigger chats: foi chamada ferramenta de conclusão (send/telegram_send/cancel)?
            _TRIGGER_CONCLUSION_TOOLS = {"send", "telegram_send", "cancel"}
            _trigger_conclusion_called = False
            # Flag para steps tool: bloqueia saída de texto enquanto houver passos pendentes
            _steps_active = False
            _steps_block_count = 0

            while iteration < max_tool_iterations:
                iteration += 1

                # VERIFICAR CANCELAMENTO: Se o job foi cancelado, interromper loop
                # Usar job_id para evitar falsos positivos com mltiplos jobs no mesmo chat
                if job_id and self.is_job_cancelled(chat_id, job_id):
                    debug(
                        f"[MessageProcessor] Job {job_id} foi cancelado - interrompendo loop de iteraes"
                    )
                    break

                debug(f"[MessageProcessor] LLM call iteration {iteration}")

                # Debug: log the first user message to verify context is there
                if iteration == 1:
                    for i, msg in enumerate(messages):
                        if msg["role"] == "user":
                            content_preview = (
                                msg["content"][:200]
                                if len(msg["content"]) > 200
                                else msg["content"]
                            )
                            debug(
                                f"[MessageProcessor] First user message (iteration {iteration}): {content_preview}..."
                            )
                            if "[CONTEXTO DA IMAGEM ANEXADA]" in msg["content"]:
                                debug(
                                    f"[MessageProcessor]  Image context detected in user message!"
                                )
                            break

                # Chama LLM com ferramentas
                try:
                    llm_response = llm_client.chat(
                        messages=messages,
                        system_prompt=system_prompt,
                        tools=tool_definitions,
                        tool_choice="auto",
                        temperature=0.7,
                        user_id=user_id,
                        isolated_chat_id=chat_id,
                        isolated_message_id=message_id,
                    )
                except Exception as llm_err:
                    #  Erros de saldo insuficiente ou quota devem quebrar a execuo
                    error_str = str(llm_err).lower()
                    if (
                        "insufficient" in error_str
                        or "balance" in error_str
                        or "402" in error_str
                        or "quota" in error_str
                        or "billing" in error_str
                    ):
                        error(
                            f"[MessageProcessor] API BILLING ERROR: {llm_err} - Interrompendo execuo"
                        )
                        return ProcessResult(
                            success=False,
                            response="",
                            agent_id=agent_id,
                            model=model,
                            tokens_used={
                                "input": total_input_tokens,
                                "output": total_output_tokens,
                            },
                            error=f"API Billing/Quota Error: {str(llm_err)}",
                        )
                    else:
                        # Outros erros so relanados
                        raise

                # VERIFICAR CANCELAMENTO: Se foi cancelado enquanto esperava LLM, quebra loop
                if job_id and self.is_job_cancelled(chat_id, job_id):
                    debug(
                        f"[MessageProcessor] Job {job_id} foi cancelado durante LLM call - interrompendo"
                    )
                    break

                if llm_response.get("error"):
                    error(f"LLM call failed: {llm_response['error']}")
                    if job:
                        try:
                            job.mark_error(f"LLM call failed: {llm_response['error']}")
                        except Exception:
                            pass
                    return ProcessResult(
                        success=False,
                        response="",
                        agent_id=agent_id,
                        model=model,
                        tokens_used={
                            "input": total_input_tokens,
                            "output": total_output_tokens,
                        },
                        error=llm_response["error"],
                    )

                # Acumula tokens
                usage = llm_response.get("usage", {})
                total_input_tokens += usage.get("input", 0)
                total_output_tokens += usage.get("output", 0)

                # ===== COMPACTING LOGIC DISABLED FOR TESTING =====
                # Ser reativado aps validao completa
                # if iteration == 1 and isolated_chat and db_session:
                #     max_context_tokens = agent.get("max_context_tokens", 128000)
                #     context_threshold = int(max_context_tokens * 0.65)  # 65% do limite
                #
                #     if total_input_tokens > context_threshold:
                #         # Enfileirar compactao em background
                #         last_user_msg_uuid = None
                #         for msg in reversed(isolated_messages):
                #             if msg.role == "user":
                #                 last_user_msg_uuid = msg.isolated_message_id
                #                 break
                #
                #         if last_user_msg_uuid:
                #             self.enqueue_compaction(
                #                 isolated_chat_id=isolated_chat.chat_id,
                #                 chat_id=chat_id,
                #                 user_id=user_id,
                #                 cut_message_isolated_message_id=last_user_msg_uuid,
                #                 agent_id=agent_id
                #             )
                #             info(f"[MessageProcessor] Context threshold exceeded ({total_input_tokens}/{max_context_tokens} tokens), "
                #                  f"compaction enqueued (65% threshold: {context_threshold})")
                #     else:
                #         debug(f"[MessageProcessor] Context OK: {total_input_tokens}/{max_context_tokens} tokens "
                #               f"({int(total_input_tokens/max_context_tokens*100)}% of limit)")

                # Extrai resposta
                ai_response = llm_response.get("content", "")
                tool_calls = llm_response.get("tool_calls", [])
                stop_reason = llm_response.get("stop_reason", "end_turn")

                debug(
                    f"[MessageProcessor] LLM iteration {iteration}: {len(ai_response)} chars, {len(tool_calls)} tool calls"
                )

                # Verificar se h descrio textual malformada de tool calls (Tool: ... Args: ...)
                if not tool_calls and self._detect_malformed_tool_calls(ai_response):
                    warning(
                        f"[MessageProcessor] Resposta contm descrio textual de tool call ao invs de estrutura formal"
                    )
                    warning(
                        f"[MessageProcessor] Rejeitando e retomando loop para corrigir"
                    )

                    # SALVAR RESPOSTA MALFORMADA em isolated_messages para o agente ver seu erro
                    malformed_response_id = str(uuid.uuid4())
                    if isolated_chat and db_session:
                        self.db_manager.save_isolated_message(
                            session=db_session,
                            isolated_chat_id=isolated_chat.chat_id,
                            agent_id=agent_id,
                            agent=agent_name,
                            role="assistant",
                            content=ai_response,
                            message_type="message",
                            isolated_message_id=malformed_response_id,
                            input_tokens=usage.get("input", 0),
                            output_tokens=usage.get("output", 0),
                        )
                        debug(
                            f"[MessageProcessor] Resposta malformada salva em isolated_messages: {malformed_response_id}"
                        )
                    else:
                        # Fallback: salvar via chat_manager
                        self.chat_manager.save_message(
                            job_id=job_id,
                            role="assistant",
                            content=ai_response,
                            agent_id=agent_id,
                            model=model,
                        )
                        debug(
                            f"[MessageProcessor] Resposta malformada salva via chat_manager (fallback)"
                        )

                    # Adicionar mensagem de erro ao histrico para forar agente a corrigir
                    error_msg = (
                        "Erro: Sua resposta descreve um tool call textualmente (formato 'Tool: ...' e 'Args: ...') "
                        "mas no o estrutura corretamente. "
                        "Para executar uma ferramenta, use a estrutura formal com tool call JSON. "
                        "Tente novamente com a estrutura correta."
                    )
                    messages.append({"role": "user", "content": error_msg})
                    debug(
                        f"[MessageProcessor] Mensagem de erro adicionada ao histrico para retry"
                    )

                    # Continuar o loop para a prxima iterao (nova tentativa do agente)
                    iteration += 1
                    if iteration >= max_tool_iterations:
                        error(
                            f"[MessageProcessor] Mximo de iteraes atingido tentando corrigir tool calls malformados"
                        )
                        return ProcessResult(
                            success=False,
                            response="",
                            agent_id=agent_id,
                            model=model,
                            tokens_used={
                                "input": total_input_tokens,
                                "output": total_output_tokens,
                            },
                            error="Tool call format error: response contains textual description instead of formal structure",
                        )
                    continue

                # Se no h tool calls (e no  malformado), sai do loop
                # SETUP GATE COMENTADO: agente livre para variações e fluxos sem setup obrigatório
                # if (
                #     not tool_calls
                #     and user_id
                #     and not self.has_required_signup_documents(user_id)
                # ):
                #     ...inject "continue setup"...
                #     continue

                #  GATE: bloquear resposta de texto quando skill com allow_message_response=false está ativa
                # Cobre SkillCopywriting (hardcoded) + qualquer skill com JSON gate (e.g. SkillCatalog)
                _block_text = False
                _block_text_reason = ""
                if not tool_calls and user_id and chat_id:
                    # Hardcoded: SkillCopywriting
                    if self._copywriting_skill_active_without_document(
                        chat_id, user_id
                    ):
                        _block_text = True
                        _block_text_reason = (
                            "Resposta de texto bloqueada: SkillCopywriting foi carregada mas o documento copywriting ainda não foi criado. "
                            "Continue o fluxo: quiz (se ainda não respondido) → document(type='copywriting', ...)."
                        )
                    # Generic JSON gate: skills com allow_message_response=false
                    if not _block_text and self.core._gate_blocks_message_response():
                        _block_text = True
                        _block_text_reason = (
                            "Resposta de texto bloqueada: skill ativa com sequência obrigatória em andamento. "
                            "Continue o fluxo da skill antes de enviar mensagens livres."
                        )
                if _block_text:
                    messages.append({"role": "assistant", "content": ai_response or ""})
                    messages.append({"role": "user", "content": _block_text_reason})
                    debug(
                        f"[MessageProcessor] Gate JSON: resposta de texto bloqueada, continuando loop"
                    )
                    continue

                # Gate para trigger chats: bloqueia saída sem tool de conclusão
                if (
                    not tool_calls
                    and context
                    and context.get("trigger_display")
                    and not _trigger_conclusion_called
                ):
                    provider = "externo"
                    try:
                        import json as _json

                        _td = _json.loads(context["trigger_display"])
                        provider = _td.get("provider", "externo")
                    except Exception:
                        pass
                    _provider_hints = {
                        "telegram": (
                            '• send(message="sua resposta")  ← para RESPONDER ao remetente\n'
                            '• cancel(cancel=true, reason="motivo")  ← para ENCERRAR sem responder\n'
                            '• cancel(cancel=true, escalate_to_human=true, reason="motivo")  ← para ESCALAR para humano'
                        ),
                    }.get(
                        provider,
                        (
                            '• send(message="sua resposta")  ← para RESPONDER ao remetente\n'
                            '• cancel(cancel=true, reason="motivo")  ← para ENCERRAR o fluxo\n'
                            '• cancel(cancel=true, escalate_to_human=true, reason="motivo")  ← para ESCALAR para humano'
                        ),
                    )
                    messages.append({"role": "assistant", "content": ai_response or ""})
                    messages.append(
                        {
                            "role": "user",
                            "content": (
                                "⚠️ BLOQUEADO: Você respondeu com texto simples em um chat de trigger externo. "
                                "Texto simples NÃO é entregue ao remetente.\n\n"
                                "Você DEVE chamar uma destas ferramentas AGORA (escolha a mais adequada):\n"
                                f"{_provider_hints}"
                            ),
                        }
                    )
                    debug("[MessageProcessor] Trigger gate: continuando loop")
                    continue

                # Resposta truncada por max_tokens: injeta continuação e mantém loop
                if not tool_calls and stop_reason == "max_tokens":
                    warning(
                        "[MessageProcessor] Resposta truncada por max_tokens — injetando continuação"
                    )
                    messages.append({"role": "assistant", "content": ai_response or ""})
                    messages.append({"role": "user", "content": "Continue."})
                    continue

                # Gate steps: se steps() foi chamado nesta sessão, pula o break e continua.
                # Verifica em qualquer role: durante loop ativo o resultado fica em role=user,
                # mas ao reconstruir do DB fica em role=assistant.
                if not tool_calls and _steps_block_count < 6:
                    _has_steps_in_history = any(
                        "Tool 'steps' result:" in (m.get("content") or "")  # loop ativo
                        or (
                            '"tool": "steps"' in (m.get("content") or "")
                            and '"steps_created"' in (m.get("content") or "")
                        )  # reconstruído do DB
                        for m in messages
                    )
                    if _has_steps_in_history:
                        _steps_block_count += 1
                        if ai_response:
                            messages.append(
                                {"role": "assistant", "content": ai_response}
                            )
                        debug(
                            f"[MessageProcessor] steps gate: continuando loop ({_steps_block_count}/6)"
                        )
                        continue

                if not tool_calls:
                    _steps_active = False
                    break

                # Adiciona resposta do assistant ao histrico
                messages.append({"role": "assistant", "content": ai_response or ""})

                # Executa cada ferramenta
                for tool_call in tool_calls:
                    # VERIFICAR CANCELAMENTO: Se foi cancelado entre ferramentas, quebra loop
                    if job_id and self.is_job_cancelled(chat_id, job_id):
                        debug(
                            f"[MessageProcessor] Job {job_id} foi cancelado durante execuo de ferramentas - interrompendo"
                        )
                        break

                    tool_name = tool_call.get("name", "")
                    tool_id = tool_call.get("id", "")
                    arguments = tool_call.get("arguments", "{}")
                    is_inline = self.core.is_inline_tool(
                        tool_name
                    )  # l TOOLS.json uma vez, reutilizado consistentemente

                    if tool_name in _TRIGGER_CONCLUSION_TOOLS:
                        _trigger_conclusion_called = True

                    debug(f"[MessageProcessor] Processing tool: {tool_name}")

                    try:
                        # Categorize tool: inline or external
                        if is_inline:
                            # INLINE TOOLS: Execute immediately (quick)
                            debug(
                                f"[MessageProcessor] Executing inline tool: {tool_name}"
                            )
                            debug(
                                f"[MessageProcessor] Tool {tool_name} args: {arguments}"
                            )
                            tool_result = self.core.execute_tool(
                                tool_name=tool_name,
                                arguments=arguments,
                                agent_id=agent_id,
                                chat_id=chat_id,
                                user_id=user_id,
                                job_id=job_id,
                                isolated_message_id=message_id,
                            )
                            # QUIZ SPECIAL HANDLING: Save only INPUT when waiting for response, setup polling
                            if tool_name == "quiz":
                                try:
                                    quiz_result = json.loads(tool_result)
                                    tool_call_uuid = str(uuid.uuid4())
                                    args_str = (
                                        arguments
                                        if isinstance(arguments, str)
                                        else json.dumps(arguments, ensure_ascii=False)
                                    )
                                    quiz_call_id = quiz_result.get(
                                        "quiz_call_id", ""
                                    ) or str(
                                        uuid.uuid4()
                                    )  # Gerar se vazio

                                    if (
                                        quiz_result.get("success", False)
                                        and quiz_result.get("status") == "waiting"
                                    ):
                                        # Quiz request created: save only INPUT
                                        # No OUTPUT saved yet - waiting for user response
                                        # quiz_call_id j foi extrado acima com gerao de UUID se vazio

                                        # Injetar quiz_call_id e flags do resultado nos args para o frontend e validators
                                        try:
                                            args_obj = json.loads(args_str)
                                            args_obj["quiz_call_id"] = quiz_call_id
                                            if quiz_result.get("is_user_browser_auth"):
                                                args_obj["is_user_browser_auth"] = True
                                            if quiz_result.get("plan"):
                                                args_obj["plan"] = quiz_result["plan"]
                                            args_str_with_id = json.dumps(
                                                args_obj, ensure_ascii=False
                                            )
                                        except:
                                            args_str_with_id = args_str

                                        self.db_manager.save_isolated_message(
                                            session=db_session,
                                            isolated_chat_id=isolated_chat.chat_id,
                                            agent_id=agent_id,
                                            agent=agent_name,
                                            role="assistant",
                                            content=f"Tool: {tool_name}\nArgs: {args_str_with_id}",
                                            message_type="tool_call",
                                            isolated_message_id=tool_call_uuid,
                                            tool_call_id=quiz_call_id,  # Preencher tool_call_id para agrupamento no sync
                                            tool_called=tool_name,
                                            tool_call_type="input",
                                            input_tokens=usage.get("input", 0),
                                            output_tokens=usage.get("output", 0),
                                        )
                                        debug(
                                            f"[MessageProcessor] Quiz INPUT saved with UUID {tool_call_uuid} and quiz_call_id {quiz_call_id}"
                                        )

                                        # Atualizar status do job para "waiting"
                                        if job:
                                            if hasattr(job, "set_status"):
                                                debug(
                                                    f"[MessageProcessor] Job object existe, chamando set_status('waiting') para quiz"
                                                )
                                                job.set_status("waiting")
                                                info(
                                                    f"[MessageProcessor]  TOOL quiz RETORNOU STATUS='waiting'"
                                                )
                                                info(
                                                    f"[MessageProcessor]  Job {job.job_id} status alterado para 'waiting'"
                                                )
                                                info(
                                                    f"[MessageProcessor] Job.status agora: {job.status}"
                                                )
                                            else:
                                                warning(
                                                    f"[MessageProcessor]  Job no tem mtodo set_status!"
                                                )
                                        else:
                                            warning(f"[MessageProcessor]  Job  None!")

                                        # Set flag to break main loop - job stays open (processing), waiting for response via /quiz_answer
                                        waiting_for_tool = True
                                        waiting_tool_name = "quiz"
                                        break  # Break tool_calls loop

                                    else:
                                        # Error case: save INPUT + OUTPUT with error (different isolated_message_ids, same tool_call_id)
                                        error_input_message_id = str(uuid.uuid4())
                                        error_output_message_id = str(uuid.uuid4())

                                        self.db_manager.save_isolated_message(
                                            session=db_session,
                                            isolated_chat_id=isolated_chat.chat_id,
                                            agent_id=agent_id,
                                            agent=agent_name,
                                            role="assistant",
                                            content=f"Tool: {tool_name}\nArgs: {args_str}",
                                            message_type="tool_call",
                                            isolated_message_id=error_input_message_id,
                                            tool_call_id=tool_call_uuid,
                                            tool_called=tool_name,
                                            tool_call_type="input",
                                            input_tokens=usage.get("input", 0),
                                            output_tokens=usage.get("output", 0),
                                        )
                                        debug(
                                            f"[MessageProcessor] Quiz INPUT saved (tool_call_id: {tool_call_uuid})"
                                        )

                                        # Save error OUTPUT
                                        error_json = {
                                            "success": False,
                                            "tool": "quiz",
                                            "error": quiz_result.get(
                                                "error", "Unknown error"
                                            ),
                                            "errors": quiz_result.get("errors", []),
                                        }
                                        result_content = json.dumps(
                                            error_json, ensure_ascii=False
                                        )
                                        self.db_manager.save_isolated_message(
                                            session=db_session,
                                            isolated_chat_id=isolated_chat.chat_id,
                                            agent_id=agent_id,
                                            agent=agent_name,
                                            role="user",
                                            content=result_content,
                                            message_type="tool_call",
                                            isolated_message_id=error_output_message_id,
                                            tool_call_id=tool_call_uuid,
                                            tool_called=tool_name,
                                            tool_call_type="output",
                                        )
                                        debug(
                                            f"[MessageProcessor] Quiz error OUTPUT saved (tool_call_id: {tool_call_uuid})"
                                        )
                                        # Continue to next iteration so IA can try again
                                        pass

                                except (json.JSONDecodeError, TypeError) as e:
                                    debug(
                                        f"[MessageProcessor] Error processing quiz result: {e}"
                                    )
                                    pass

                            # STEPS TRACKING: ativa gate de looping quando steps registrados sem pause
                            if tool_name == "steps" and tool_result:
                                try:
                                    _sr = json.loads(tool_result)
                                    if (
                                        _sr.get("success")
                                        and _sr.get("status") != "waiting"
                                    ):
                                        _steps_active = True
                                        debug(
                                            "[MessageProcessor] steps() registrado — gate de looping ativo"
                                        )
                                except (json.JSONDecodeError, TypeError):
                                    pass

                        else:
                            # EXTERNAL TOOL CALLS (is_inline_tool=false): Enqueue and continue
                            # NOVO: Suporte a wait=true para bloquear loop at tool terminar
                            # EXCEPT context=true: retorna histrico imediatamente
                            args_dict = _parse_tool_arguments(arguments)
                            wait_enabled = args_dict.get("wait", True)

                            if args_dict.get("context") == True:
                                # context=true: retorna histrico, no enfileira
                                tool_result = self.core.execute_tool(
                                    tool_name=tool_name,
                                    arguments=arguments,
                                    agent_id=agent_id,
                                    chat_id=chat_id,
                                    user_id=user_id,
                                    job_id=job_id,
                                )
                                debug(
                                    f"[MessageProcessor] External tool {tool_name} context=true executed (returns history)"
                                )
                            else:
                                # Execuo normal: enfileira
                                from App.Core.Queues import ToolCall

                                tool_call_id = str(uuid.uuid4())

                                # TODO: REFACTOR - generated_content_id generation  responsabilidade indevida aqui
                                # Deveria estar no DBManager/QueueManager quando a tool  enfileirada.
                                # Por enquanto mantido para no quebrar fluxo, mas precisa ser movido.
                                generated_content_id = ""
                                # Gerar ID apenas para media-generating tools (asset)
                                if tool_name == "asset":
                                    generated_content_id = str(uuid.uuid4())
                                    args_dict[
                                        "generated_content_id"
                                    ] = generated_content_id

                                # IMPORTANTE: Salvar mensagem ANTES de enfileirar a tool
                                # Assim wait() pode encontrar a mensagem no BD imediatamente
                                try:
                                    tool_call_content = f"Tool: {tool_name}\nArgs: {json.dumps(args_dict, ensure_ascii=False)}"
                                    self.db_manager.save_isolated_message(
                                        session=db_session,
                                        isolated_chat_id=isolated_chat.chat_id,
                                        agent_id=agent_id,
                                        agent=agent_id,
                                        role="assistant",
                                        content=tool_call_content,
                                        message_type="tool_call",
                                        isolated_message_id=tool_call_id,
                                        tool_call_id=tool_call_id,
                                        tool_called=tool_name,
                                        tool_call_type="input",
                                        input_tokens=usage.get("input", 0),
                                        output_tokens=usage.get("output", 0),
                                    )
                                    debug(
                                        f"[MessageProcessor] External tool message saved to DB BEFORE enqueue: {tool_call_id}"
                                    )
                                except Exception as e:
                                    debug(
                                        f"[MessageProcessor] Erro ao salvar mensagem de tool externa: {e}"
                                    )

                                # Get client_id from users table
                                client_id = ""
                                try:
                                    user_row = (
                                        db_session.query(User)
                                        .filter(User.user_id == user_id)
                                        .first()
                                        if user_id
                                        else None
                                    )
                                    client_id = user_row.client_id if user_row else ""
                                except:
                                    pass

                                tool_call_obj = ToolCall(
                                    tool_call_id=tool_call_id,
                                    message_id=tool_id,
                                    job_id=job_id,
                                    chat_id=chat_id,
                                    user_id=user_id,
                                    tool_name=tool_name,
                                    arguments=args_dict,
                                    tool_type="external",
                                    agent_id=agent_id,
                                    generated_content_id=generated_content_id,
                                    client_id=client_id,
                                    isolated_message_id=message_id,
                                )
                                self.queue_manager.enqueue_tool_call(tool_call_obj)
                                debug(
                                    f"[MessageProcessor] External tool call {tool_name} enqueued (will process async)"
                                )

                                # NOVO: Se wait=true, no retorna mensagem - apenas quebra o loop
                                if wait_enabled:
                                    waiting_for_tool = True
                                    waiting_tool_name = (
                                        tool_name  # Track which tool caused waiting
                                    )
                                    debug(
                                        f"[MessageProcessor] External tool {tool_name} enqueued com wait=true - quebra do loop"
                                    )
                                    tool_result = None  # No h resposta intermediria - quebra o loop
                                    break  # Quebra o loop de tool_calls para no processar mais ferramentas nesta iterao
                                else:
                                    # Status "queued": continua processando normalmente
                                    tool_result = json.dumps(
                                        {
                                            "status": "queued",
                                            "message": f"Tool call enqueued for processing",
                                        }
                                    )

                        # EXTERNAL TOOL WAIT DETECTION (is_inline_tool=false): Apenas quiz deve retornar status="waiting" e quebrar o loop
                        # External tools continuam processando normalmente
                        # Nota: quiz j quebra o loop na seo anterior quando detectado
                        if not is_inline and tool_name != "quiz":
                            try:
                                tool_result_obj = json.loads(tool_result)
                                if tool_result_obj.get("status") == "waiting":
                                    info(
                                        f"[MessageProcessor]  TOOL {tool_name} retornou status='waiting' - ignorando"
                                    )
                                    info(
                                        f"[MessageProcessor] Somente 'quiz' deveria retornar waiting. Continuando processamento normal."
                                    )
                                    # NO quebra o loop - external tools continuam sendo processadas
                            except (json.JSONDecodeError, TypeError) as e:
                                debug(
                                    f"[MessageProcessor] Erro ao parsear tool_result para deteco de waiting: {e}"
                                )

                        # Extrai contedo que a IA passou para a ferramenta
                        tool_input_content = (
                            arguments if isinstance(arguments, str) else str(arguments)
                        )

                        # Se tool_result  None, significa que  external tool com wait=true
                        # Nesse caso, no h resposta intermediria - apenas quebra o loop
                        if tool_result is None:
                            debug(
                                f"[MessageProcessor] External tool {tool_name} com wait=true - nenhuma resposta intermediria"
                            )
                            break

                        # GENERIC: Todas as inline tools tm seu resultado adicionado ao histrico
                        # para garantir que a IA veja que foram executadas (exceto external tools enfileiradas).
                        if is_inline:
                            # INLINE TOOLS: Sempre adiciona ao histrico de mensagens para o LLM
                            messages.append(
                                {
                                    "role": "user",
                                    "content": f"Tool '{tool_name}' result: {tool_result}",
                                }
                            )
                            debug(
                                f"[MessageProcessor] {tool_name} result added to messages (ensuring LLM sees it)"
                            )

                        # Verifica se a ferramenta foi executada com sucesso
                        try:
                            tool_result_obj = json.loads(tool_result)

                            if tool_result_obj.get("status") == "queued":
                                debug(
                                    f"[MessageProcessor] External tool {tool_name} enqueued successfully (status: queued)"
                                )
                            elif not tool_result_obj.get("success", False):
                                error_msg = tool_result_obj.get(
                                    "error", "Unknown error"
                                )
                                debug(
                                    f"[MessageProcessor] Tool {tool_name} failed: {error_msg}"
                                )

                                # Persistir falha de inline tool em isolated_messages para ficar visível no chat
                                if is_inline and isolated_chat and db_session:
                                    try:
                                        _fail_call_id = str(uuid.uuid4())
                                        _args_str = (
                                            arguments
                                            if isinstance(arguments, str)
                                            else json.dumps(
                                                arguments, ensure_ascii=False
                                            )
                                        )
                                        self.db_manager.save_isolated_message(
                                            session=db_session,
                                            isolated_chat_id=isolated_chat.chat_id,
                                            agent_id=agent_id,
                                            agent=agent_name,
                                            role="assistant",
                                            content=f"Tool: {tool_name}\nArgs: {_args_str}",
                                            message_type="tool_call",
                                            isolated_message_id=str(uuid.uuid4()),
                                            tool_call_id=_fail_call_id,
                                            tool_called=tool_name,
                                            tool_call_type="input",
                                        )
                                        self.db_manager.save_isolated_message(
                                            session=db_session,
                                            isolated_chat_id=isolated_chat.chat_id,
                                            agent_id=agent_id,
                                            agent=agent_name,
                                            role="user",
                                            content=self._mcp_auditable_output(
                                                tool_result, _args_str
                                            )
                                            if tool_name.startswith("mcp__")
                                            else tool_result,
                                            message_type="tool_call",
                                            isolated_message_id=str(uuid.uuid4()),
                                            tool_call_id=_fail_call_id,
                                            tool_called=tool_name,
                                            tool_call_type="output",
                                        )
                                        debug(
                                            f"[MessageProcessor] Tool {tool_name} failure persisted to isolated_messages"
                                        )
                                    except Exception as _e:
                                        debug(
                                            f"[MessageProcessor] Erro ao persistir falha de {tool_name}: {_e}"
                                        )

                                continue

                            # Se tool retornou status="waiting", no adiciona ao histrico
                            # (resultado chegar depois quando a tool completar)
                            if tool_result_obj.get("status") == "waiting":
                                # AUTONOMY GATE: pending_tool_approval precisa ser persistido
                                # para aparecer no chat principal e permitir que o usuário aprove/rejeite
                                if (
                                    tool_result_obj.get("pending_tool_approval")
                                    and isolated_chat
                                    and db_session
                                ):
                                    try:
                                        _approval_call_id = str(uuid.uuid4())
                                        _input_msg_id = str(uuid.uuid4())
                                        _output_msg_id = str(uuid.uuid4())
                                        _args_str = (
                                            arguments
                                            if isinstance(arguments, str)
                                            else json.dumps(
                                                arguments, ensure_ascii=False
                                            )
                                        )
                                        self.db_manager.save_isolated_message(
                                            session=db_session,
                                            isolated_chat_id=isolated_chat.chat_id,
                                            agent_id=agent_id,
                                            agent=agent_name,
                                            role="assistant",
                                            content=f"Tool: {tool_name}\nArgs: {_args_str}",
                                            message_type="tool_call",
                                            isolated_message_id=_input_msg_id,
                                            tool_call_id=_approval_call_id,
                                            tool_called=tool_name,
                                            tool_call_type="input",
                                            input_tokens=usage.get("input", 0),
                                            output_tokens=usage.get("output", 0),
                                        )
                                        self.db_manager.save_isolated_message(
                                            session=db_session,
                                            isolated_chat_id=isolated_chat.chat_id,
                                            agent_id=agent_id,
                                            agent=agent_name,
                                            role="user",
                                            content=tool_result,
                                            message_type="tool_call",
                                            isolated_message_id=_output_msg_id,
                                            tool_call_id=_approval_call_id,
                                            tool_called=tool_name,
                                            tool_call_type="output",
                                        )
                                        try:
                                            self.queue_manager.enqueue_sync_message(
                                                chat_id=chat_id,
                                                agent_id=agent_id,
                                                job_id=job_id,
                                            )
                                            sync_enqueued = True
                                        except Exception as _sync_err:
                                            debug(
                                                f"[MessageProcessor] Erro ao sync tool_approval: {_sync_err}"
                                            )
                                        debug(
                                            f"[MessageProcessor] pending_tool_approval persistido: tool={tool_name}, id={tool_result_obj.get('tool_approval_id')}"
                                        )
                                    except Exception as _persist_err:
                                        error(
                                            f"[MessageProcessor] Erro ao persistir pending_tool_approval: {_persist_err}"
                                        )
                                    # Pausa o job como quiz: fica waiting até o usuário aprovar/rejeitar
                                    if job and hasattr(job, "set_status"):
                                        job.set_status("waiting")
                                    waiting_for_tool = True
                                    waiting_tool_name = tool_name
                                debug(
                                    f"[MessageProcessor] Tool {tool_name} retornou status='waiting' - no adicionando ao histrico"
                                )
                                if waiting_for_tool:
                                    break  # break tool_calls loop; outer while quebra no check 2889
                                continue
                        except (json.JSONDecodeError, AttributeError):
                            # Se no conseguir fazer parse, assume sucesso (compatibilidade)
                            pass

                            # Adiciona resultado ao histrico
                            messages.append(
                                {
                                    "role": "user",
                                    "content": f"Tool '{tool_name}' result: {tool_result}",
                                }
                            )

                            debug(
                                f"[MessageProcessor] Tool {tool_name} executed successfully"
                            )

                        # Extrai contedo legvel do resultado
                        tool_content = self._extract_tool_content(
                            tool_result, tool_name=tool_name
                        )

                        # SINCRONIZAR PROGRESSO: Salva resultado da ferramenta em tempo real
                        args_dict = _parse_tool_arguments(arguments)

                        # Verificar se  context=true
                        is_context_true = args_dict.get("context") == True

                        if (
                            isolated_chat
                            and db_session
                            and is_context_true
                            and not is_inline
                        ):
                            # Para context=true em external tools: salvar INPUT + OUTPUT com mesmo tool_call_id, mas isolated_message_ids diferentes
                            tool_call_id = str(uuid.uuid4())
                            input_message_id = str(uuid.uuid4())
                            output_message_id = str(uuid.uuid4())
                            args_str = (
                                arguments
                                if isinstance(arguments, str)
                                else json.dumps(arguments, ensure_ascii=False)
                            )

                            # Salvar INPUT
                            self.db_manager.save_isolated_message(
                                session=db_session,
                                isolated_chat_id=isolated_chat.chat_id,
                                agent_id=agent_id,
                                agent=agent_name,
                                role="assistant",
                                content=f"Tool: {tool_name}\nArgs: {args_str}",
                                message_type="tool_call",
                                isolated_message_id=input_message_id,
                                tool_call_id=tool_call_id,
                                tool_called=tool_name,
                                tool_call_type="input",
                                input_tokens=usage.get("input", 0),
                                output_tokens=usage.get("output", 0),
                            )
                            debug(
                                f"[MessageProcessor] {tool_name} context=true INPUT saved (tool_call_id: {tool_call_id})"
                            )

                            # Salvar OUTPUT
                            self.db_manager.save_isolated_message(
                                session=db_session,
                                isolated_chat_id=isolated_chat.chat_id,
                                agent_id=agent_id,
                                agent=agent_name,
                                role="user",
                                content=self._mcp_auditable_output(
                                    tool_content, args_str
                                )
                                if tool_name.startswith("mcp__")
                                else tool_content,
                                message_type="tool_call",
                                isolated_message_id=output_message_id,
                                tool_call_id=tool_call_id,
                                tool_called=tool_name,
                                tool_call_type="output",
                            )
                            debug(
                                f"[MessageProcessor] {tool_name} context=true OUTPUT saved (tool_call_id: {tool_call_id})"
                            )
                            continue

                        # PULAR se context=true e j foi salvo acima
                        if is_context_true:
                            debug(
                                f"[MessageProcessor] Skipping sync for {tool_name} with context=true (already saved or not external)"
                            )
                            continue

                        # PULAR se est aguardando resposta de tool (quiz com waiting)
                        if waiting_for_tool:
                            debug(
                                f"[MessageProcessor] Skipping further processing - waiting for tool response"
                            )
                            continue

                        # TODO: DISABLED - Sync filtering no  responsabilidade do MessageProcessor
                        # Deveria estar em SyncManager
                        # Tools que NO devem sincronizar para main chat: context, quiz
                        # should_sync_to_main = True
                        # if tool_name in ["context", "quiz"]:
                        #     should_sync_to_main = False

                        if isolated_chat and db_session:
                            # GENERIC INLINE TOOL SAVE: All inline tools save INPUT + OUTPUT with tool_called + tokens
                            if is_inline:
                                tool_call_id = str(uuid.uuid4())
                                input_message_id = str(uuid.uuid4())
                                output_message_id = str(uuid.uuid4())
                                args_str = (
                                    arguments
                                    if isinstance(arguments, str)
                                    else json.dumps(arguments, ensure_ascii=False)
                                )

                                # Salvar INPUT (argumentos da tool)
                                self.db_manager.save_isolated_message(
                                    session=db_session,
                                    isolated_chat_id=isolated_chat.chat_id,
                                    agent_id=agent_id,
                                    agent=agent_name,
                                    role="assistant",
                                    content=f"Tool: {tool_name}\nArgs: {args_str}",
                                    message_type="tool_call",
                                    isolated_message_id=input_message_id,
                                    tool_call_id=tool_call_id,
                                    tool_called=tool_name,
                                    tool_call_type="input",
                                    input_tokens=usage.get("input", 0),
                                    output_tokens=usage.get("output", 0),
                                )
                                debug(
                                    f"[MessageProcessor] {tool_name} INPUT saved (tool_call_id: {tool_call_id})"
                                )

                                # Salvar OUTPUT (resultado da tool)
                                self.db_manager.save_isolated_message(
                                    session=db_session,
                                    isolated_chat_id=isolated_chat.chat_id,
                                    agent_id=agent_id,
                                    agent=agent_name,
                                    role="assistant",
                                    content=self._mcp_auditable_output(
                                        tool_content, args_str
                                    )
                                    if tool_name.startswith("mcp__")
                                    else tool_content,
                                    message_type="tool_call",
                                    isolated_message_id=output_message_id,
                                    tool_call_id=tool_call_id,
                                    tool_called=tool_name,
                                    tool_call_type="output",
                                )
                                debug(
                                    f"[MessageProcessor] {tool_name} OUTPUT saved (tool_call_id: {tool_call_id})"
                                )
                            else:
                                # EXTERNAL TOOL (is_inline_tool=false): INPUT j foi salvo durante enfileiragemachine
                                # Apenas log do que foi enfileirado
                                debug(
                                    f"[MessageProcessor] External tool {tool_name} enqueued (INPUT already saved, OUTPUT will be saved when tool completes)"
                                )

                            # Sync will be handled at the end via background queue
                            debug(
                                f"[MessageProcessor] {tool_name} salvo isoladamente (sincronizao acontecer via fila de background)"
                            )
                        else:
                            # TODO: HARDCODING - Se no h isolated_chat/db_session, salva via chat_manager
                            # Excludes alguns tools (message, status) que no devem ser salvos no chat_manager
                            # Isso precisa ser refatorado para ser genrico baseado em flag do TOOLS.json
                            if tool_name not in ["message", "status"]:
                                self.chat_manager.save_message(
                                    job_id=job_id,
                                    role="assistant",
                                    content=tool_content,
                                    agent_id=agent_id,
                                    model=model,
                                )
                            debug(
                                f"[MessageProcessor] Tool {tool_name} salvo isoladamente (sincronizao via fila)"
                            )

                    except Exception as e:
                        error(
                            f"[MessageProcessor] Error executing tool {tool_name}: {e}"
                        )
                        messages.append(
                            {
                                "role": "user",
                                "content": f"Tool '{tool_name}' error: {str(e)}",
                            }
                        )

                        # SINCRONIZAR ERRO: Salva erro da ferramenta em tempo real
                        if isolated_chat and db_session:
                            # Salva INPUT + OUTPUT com erro com tool_call_id igual, mas isolated_message_ids diferentes
                            error_tool_call_id = str(uuid.uuid4())
                            error_input_message_id = str(uuid.uuid4())
                            error_output_message_id = str(uuid.uuid4())

                            # Salvar INPUT do tool_call (argumentos)
                            args_str = (
                                arguments
                                if isinstance(arguments, str)
                                else json.dumps(arguments, ensure_ascii=False)
                            )
                            self.db_manager.save_isolated_message(
                                session=db_session,
                                isolated_chat_id=isolated_chat.chat_id,
                                agent_id=agent_id,
                                agent=agent_name,
                                role="assistant",
                                content=f"Tool: {tool_name}\nArgs: {args_str}",
                                message_type="tool_call",
                                isolated_message_id=error_input_message_id,
                                tool_call_id=error_tool_call_id,
                                tool_called=tool_name,
                                tool_call_type="input",
                                input_tokens=usage.get("input", 0),
                                output_tokens=usage.get("output", 0),
                            )
                            debug(
                                f"[MessageProcessor] Tool_call ERROR INPUT saved for {tool_name} (tool_call_id: {error_tool_call_id})"
                            )

                            # Salvar OUTPUT do tool_call (erro)
                            _err_input = (
                                json.loads(args_str)
                                if isinstance(args_str, str)
                                else args_str
                            )
                            error_content = json.dumps(
                                {
                                    "success": False,
                                    "error": str(e),
                                    **(
                                        {"input": _err_input}
                                        if tool_name.startswith("mcp__")
                                        else {}
                                    ),
                                },
                                ensure_ascii=False,
                            )
                            self.db_manager.save_isolated_message(
                                session=db_session,
                                isolated_chat_id=isolated_chat.chat_id,
                                agent_id=agent_id,
                                agent=agent_name,
                                role="assistant",
                                content=error_content,
                                message_type="tool_call",
                                isolated_message_id=error_output_message_id,
                                tool_call_id=error_tool_call_id,
                                tool_called=tool_name,
                                tool_call_type="output",
                            )
                            debug(
                                f"[MessageProcessor] Tool_call ERROR OUTPUT saved for {tool_name} (tool_call_id: {error_tool_call_id})"
                            )

                            # Sync will be handled at the end via background queue
                            debug(
                                f"[MessageProcessor] Erro de {tool_name} salvo isoladamente (sincronizao acontecer via fila de background)"
                            )
                        else:
                            self.chat_manager.save_message(
                                job_id=job_id,
                                role="assistant",
                                content=f"[{tool_name}] Erro: {str(e)}",
                                agent_id=agent_id,
                                model=model,
                            )
                            debug(
                                f"[MessageProcessor] Erro de {tool_name} salvo isoladamente (sincronizao via fila)"
                            )

                #  COBRANA PS-EXECUO: Cobrar tools com base nos output_tokens reais da IA
                if tool_calls and user_id:
                    current_iteration_output_tokens = usage.get("output", 0)

                    # Cobrar cada tool que foi chamada nesta iterao
                    for tool_call in tool_calls:
                        tool_name = tool_call.get("name", "")

                        try:
                            # Chamar cobrana com output_tokens reais
                            (
                                has_credits,
                                error_msg,
                                remaining,
                            ) = CreditsManager.check_and_consume_for_tool(
                                user_id,
                                tool_name,
                                current_iteration_output_tokens,
                                isolated_chat_id=chat_id,
                                isolated_message_id=message_id,
                            )

                            if has_credits:
                                debug(
                                    f"[MessageProcessor] Tool '{tool_name}' charged: {current_iteration_output_tokens} output_tokens, remaining: {remaining:.6f}"
                                )
                            else:
                                warning(
                                    f"[MessageProcessor] Insufficient credits for tool '{tool_name}': {error_msg}"
                                )

                        except Exception as e:
                            error(
                                f"[MessageProcessor] Error charging tool '{tool_name}': {str(e)}"
                            )

                # SYNC IMEDIATO: Enfileira sync aps cada iterao do MessageWorker
                # job_id="" → SyncWorker sincroniza mensagens (dispara db_updated) mas
                # NÃO marca o job como completed aqui — há tools ainda em execução.
                # O sync final (linha ~3083, após resposta LLM gerada) usa job_id real.
                if isolated_chat and db_session and tool_calls:
                    try:
                        self.queue_manager.enqueue_sync_message(
                            chat_id=chat_id,
                            agent_id=agent_id or "orchestrator-global",
                            job_id="",  # Vazio → SyncWorker não marca completed neste sync intermediário
                            user_id=user_id or 0,
                        )
                        sync_enqueued = True
                    except Exception as _se:
                        warning(
                            f"[MessageProcessor] Erro ao enfileirar sync após iteração: {_se}"
                        )
                    debug(
                        f"[MessageProcessor]  Sync intermediário enqueued (sem mark_completed) após iteration {iteration}"
                    )

                # VERIFICAR CANCELAMENTO: Se foi cancelado, quebra o loop principal
                if job_id and self.is_job_cancelled(chat_id, job_id):
                    info(
                        f"[MessageProcessor]  QUEBRA DO LOOP PRINCIPAL: Job {job_id} foi cancelado"
                    )
                    break

                # Se wait() retornou "waiting", quebra o loop principal
                if waiting_for_tool:
                    info(
                        f"[MessageProcessor]  QUEBRA DO LOOP PRINCIPAL: waiting_for_tool={waiting_for_tool}"
                    )
                    break

            # 8. Sanitizar resposta final para remover sintaxe literal de ferramentas
            ai_response = self._sanitize_final_response(ai_response)

            # NOVO: Se loop foi quebrado por waiting_for_tool, apenas QUIZ deve marcar job como "waiting"
            # Para outras ferramentas, job continua "running" enquanto processa em background
            if waiting_for_tool and job:
                try:
                    info(
                        f"[MessageProcessor]  LOOP INTERROMPIDO - Aguardando {waiting_tool_name}"
                    )
                    info(f"[MessageProcessor] Job {job.job_id}")
                    info(f"[MessageProcessor] Job.status atual: {job.status}")
                    info(
                        f"[MessageProcessor] waiting_for_tool={waiting_for_tool}, waiting_tool_name={waiting_tool_name}"
                    )

                    # quiz e pending_tool_approval marcam job como "waiting" (bloqueante)
                    # Outras ferramentas com wait=true apenas quebram o loop, mas job continua processando
                    _is_bloqueante = waiting_tool_name == "quiz" or (
                        waiting_tool_name and waiting_tool_name.startswith("mcp__")
                    )
                    if (
                        _is_bloqueante
                        and hasattr(job, "set_status")
                        and job.status != "waiting"
                    ):
                        job.set_status("waiting")
                        debug(
                            f"[MessageProcessor] Job {job.job_id} marcado como WAITING ({waiting_tool_name})"
                        )
                    elif not _is_bloqueante:
                        debug(
                            f"[MessageProcessor] Job {job.job_id} continua em background ({waiting_tool_name} com wait=true)"
                        )
                except Exception as e:
                    warning(
                        f"[MessageProcessor] Erro ao processar waiting_for_tool: {e}"
                    )

            # 9. SALVAR FINAL RESPONSE em isolated_messages
            # No salvar se estamos aguardando output de external tool (!=quiz)  o output ainda no chegou.
            # Para quiz o ai_response  a contextualizao do agent antes do quiz aparecer, deve ser salvo.
            _skip_final_response = waiting_for_tool and waiting_tool_name != "quiz"

            # Se ai_response  idntico ao content de alguma tool message existente, finaliza sem salvar.
            if (
                isolated_chat
                and db_session
                and ai_response.strip()
                and not _skip_final_response
            ):
                _tool_msg_match = (
                    db_session.query(IsolatedMessage)
                    .filter(
                        IsolatedMessage.isolated_chat_id == isolated_chat.chat_id,
                        IsolatedMessage.type == "tool_call",
                        IsolatedMessage.content == ai_response.strip(),
                    )
                    .first()
                )
                if _tool_msg_match:
                    debug(
                        f"[MessageProcessor] ai_response  idntico a tool message existente  finalizando job sem salvar no DB"
                    )
                    _skip_final_response = True
                    if job and job.status == "running":
                        try:
                            job.mark_completed(ai_response)
                            info(
                                f"[MessageProcessor]  Job {job.job_id} marcado como COMPLETED (resposta duplicada de tool message)"
                            )
                        except Exception as _je:
                            error(
                                f"[MessageProcessor] Erro ao marcar job como completed (duplicate tool msg): {_je}"
                            )

            if (
                isolated_chat
                and db_session
                and ai_response.strip()
                and not _skip_final_response
            ):
                try:
                    final_response_uuid = str(uuid.uuid4())
                    self.db_manager.save_isolated_message(
                        session=db_session,
                        isolated_chat_id=isolated_chat.chat_id,
                        agent_id=agent_id,
                        agent=agent_name,
                        role="assistant",
                        content=ai_response,
                        message_type="message",
                        isolated_message_id=final_response_uuid,
                        input_tokens=total_input_tokens,
                        output_tokens=total_output_tokens,
                    )
                    db_session.commit()
                    debug(
                        f"[MessageProcessor] Final response saved to isolated_messages"
                    )

                    # Enfileirar sincronizao imediata para sync isolated  main
                    # O SyncWorker chama mark_completed após confirmar o sync — evita race condition
                    # onde o frontend busca mensagens antes do sync terminar.
                    try:
                        self.queue_manager.enqueue_sync_message(
                            chat_id=chat_id,
                            agent_id=agent_id or "orchestrator-global",
                            job_id=job_id,
                        )
                        sync_enqueued = True
                        debug(
                            f"[MessageProcessor]  Sync enfileirado para chat {chat_id} — mark_completed será feito pelo SyncWorker"
                        )
                    except Exception as sync_err:
                        warning(
                            f"[MessageProcessor] Erro ao enfileirar sync: {sync_err}"
                        )

                    debug(
                        f"[MessageProcessor] waiting_for_tool: {waiting_for_tool}, tool_calls count: {len(tool_calls) if tool_calls else 0}, sync_enqueued: {sync_enqueued}"
                    )

                except Exception as e:
                    db_session.rollback()
                    warning(
                        f"[MessageProcessor] Failed to save final response to isolated_messages: {str(e)}"
                    )

            # FALLBACK: Se job ainda não foi marcado como completed/waiting, marcar como completed
            # Isso evita que jobs fiquem presos em estado "running"
            # MAS: não marcar se há tool calls pendentes OU se sync foi enfileirado
            # (nesse caso, o SyncWorker chamará mark_completed após o sync terminar)
            has_pending_tool_calls_fallback = tool_calls and len(tool_calls) > 0
            if (
                job
                and job.status == "running"
                and not waiting_for_tool
                and not has_pending_tool_calls_fallback
                and not sync_enqueued
            ):
                try:
                    job.mark_completed(ai_response or "Processamento concluído")
                    info(
                        f"[MessageProcessor]  Job {job.job_id} marcado como COMPLETED (fallback)"
                    )
                except Exception as job_err:
                    error(
                        f"[MessageProcessor] Erro ao marcar job como completed (fallback): {job_err}"
                    )
            elif job and job.status == "running" and has_pending_tool_calls_fallback:
                debug(
                    f"[MessageProcessor] Fallback skipped: Job {job.job_id} ainda tem {len(tool_calls)} tool(s) pendente(s)"
                )
            elif sync_enqueued:
                debug(
                    f"[MessageProcessor] Fallback skipped: sync enfileirado, SyncWorker marcará COMPLETED"
                )

            # Note: mark_message_completed is called by MessageWorker after process_message completes
            # This enqueues to SYNC_MESSAGE_QUEUE for SyncMessageWorker to sync isolated_chat  main_chat

            # Para trigger chats: se o agente finalizou sem chamar ferramenta de conclusão,
            # salva um aviso no chat (visível ao usuário) mas não bloqueia o fluxo.
            if (
                context
                and context.get("trigger_display")
                and not _trigger_conclusion_called
                and not waiting_for_tool
                and isolated_chat
                and db_session
            ):
                try:
                    import uuid as _uuid_mod

                    warning(
                        f"[MessageProcessor] Trigger chat {chat_id} finalizou sem chamar ferramenta de conclusão"
                    )
                    _warn_content = json.dumps(
                        {
                            "type": "trigger_no_conclusion",
                            "message": (
                                "⚠️ O agente não chamou uma ferramenta de conclusão. "
                                "A resposta em texto simples NÃO foi enviada ao remetente externo. "
                                'Use send(message="...") ou cancel() para concluir corretamente.'
                            ),
                        },
                        ensure_ascii=False,
                    )
                    self.db_manager.save_isolated_message(
                        session=db_session,
                        isolated_chat_id=isolated_chat.chat_id,
                        agent_id="user",
                        agent="SYSTEM",
                        role="user",
                        content=_warn_content,
                        message_type="message",
                        isolated_message_id=str(_uuid_mod.uuid4()),
                    )
                except Exception as _we:
                    debug(
                        f"[MessageProcessor] Erro ao salvar aviso de trigger sem conclusão: {_we}"
                    )

            # Log final status
            if job:
                info(f"[MessageProcessor]  PROCESSO FINALIZADO")
                info(f"[MessageProcessor] Job {job.job_id}")
                info(f"[MessageProcessor] Job.status final: {job.status}")
                info(f"[MessageProcessor] waiting_for_tool: {waiting_for_tool}")
            else:
                warning(f"[MessageProcessor]  PROCESSO FINALIZADO (sem job)")

            # CLEANUP: Limpar flag de cancelamento para este job (evita falsos positivos em retomadas)
            if job_id:
                self.clear_job_cancelled(job_id)
                debug(
                    f"[MessageProcessor] Limpeza: Removido cancelamento flag para job {job_id}"
                )

            return ProcessResult(
                success=True,
                response=ai_response,
                agent_id=agent_id,
                model=model,
                tokens_used={
                    "input": total_input_tokens,
                    "output": total_output_tokens,
                },
                tool_calls=[],
                job_id=job_id,
            )

        except Exception as e:
            error(f"[MessageProcessor] Unexpected error: {e}")
            import traceback

            error(f"[MessageProcessor] Traceback: {traceback.format_exc()}")

            # Cancel job immediately on error
            if job:
                try:
                    job.mark_error(f"MessageProcessor error: {str(e)}")
                    debug(f"[MessageProcessor] Job {job_id} marcado como erro")
                except Exception as job_err:
                    error(f"[MessageProcessor] Erro ao marcar job como erro: {job_err}")

            # Return error result instead of raising
            return ProcessResult(
                success=False,
                response="",
                agent_id=agent_id,
                model="unknown",
                tokens_used={"input": 0, "output": 0},
                error=f"MessageProcessor error: {str(e)}",
                job_id=job_id,
            )
        finally:
            # NO fechar session se h tools enfileiradas (waiting for tool processing)
            # A session ser fechada quando o tool terminar
            if db_session and not waiting_for_tool:
                db_session.close()
                debug(f"[MessageProcessor] Database session closed")
            elif waiting_for_tool:
                debug(
                    f"[MessageProcessor] Session NO foi fechada - aguardando processamento de tool enfileirado ({waiting_tool_name})"
                )

            # Mark job as finalized if it's still running (BUT NOT if waiting for tool or sync pending)
            if (
                job
                and hasattr(job, "status")
                and job.status == "running"
                and not waiting_for_tool
                and not sync_enqueued
            ):
                try:
                    job.mark_completed("Processamento concluído (session closed)")
                    info(
                        f"[MessageProcessor]  Job {job.job_id} marcado como COMPLETED (on session close)"
                    )
                except Exception as job_err:
                    error(
                        f"[MessageProcessor] Erro ao marcar job como completed (on session close): {job_err}"
                    )

    def resume_after_tool_call(
        self,
        chat_id: str,
        message_id: str,
        content: str,
        user_id: str,
        agent_id: str = "orchestrator-global",
        job_id: Optional[str] = None,
        job: Optional[Any] = None,
    ) -> ProcessResult:
        """
        Retoma o processamento aps resposta de tool_call (quiz, wait, etc).
        Processa a resposta como mensagem de continuao.

        Args:
            chat_id: ID do chat
            message_id: UUID da tool_call original
            content: Contedo da resposta
            user_id: ID do usurio
            agent_id: ID do agente a usar
            job_id: ID do job j criado (opcional)
            job: Objeto do job j criado (opcional)

        Returns:
            ProcessResult com resposta da IA
        """
        try:
            debug(f"[MessageProcessor] Retomando aps tool_call: {message_id}")

            from App.Features.Job import get_job_manager
            from App.Features.Job.JobManager import ProcessingJob

            job_manager = get_job_manager()

            # 1. Recuperar ou criar job
            if not job:
                if job_id:
                    # Tentar buscar job existente pelo ID
                    job = job_manager.get_job(job_id)
                    if not job:
                        debug(
                            f"[MessageProcessor] Job {job_id} no encontrado no manager, criando novo"
                        )
                        # Job não encontrado no DB — reconstrói o objeto em memória
                        # com o job_id original (sem criar novo registro no banco)
                        job = ProcessingJob(
                            job_id=job_id,
                            chat_id=chat_id,
                            user_id=str(user_id) if user_id else None,
                        )
                        debug(
                            f"[MessageProcessor] Job {job_id} reconstruído em memória para retomada"
                        )
                else:
                    # Criar novo se nada foi passado
                    job = job_manager.create_job(
                        chat_id=chat_id, user_id=str(user_id) if user_id else None
                    )

            job_id = job.job_id if hasattr(job, "job_id") else str(uuid.uuid4())

            # Restaurar job para status "running" quando retoma
            if job and hasattr(job, "set_status"):
                job.set_status("running")
                debug(
                    f"[MessageProcessor] Job {job_id} restaurado para status 'running'"
                )

            debug(f"[MessageProcessor] Usando job: {job_id} para retomada")

            # 2. Chamar process_message com a resposta como mensagem
            # MessageProcessor processar normalmente, vendo a resposta no DB
            result = self.process_message(
                job_id=job_id,
                user_message=content,  # Resposta da tool_call
                agent_id=agent_id,
                chat_id=chat_id,
                user_id=user_id,
                message_id=message_id,  # Pass the message_id here!
                job=job,
            )

            # Injetar o job_id no resultado para que quem chamou saiba qual job pollar
            if result:
                result.job_id = job_id

            info(f"[MessageProcessor] Retomada concluda: {message_id}  {job_id}")
            return result

        except Exception as e:
            error(f"[MessageProcessor] Erro ao retomar tool_call: {e}")
            import traceback

            error(f"[MessageProcessor] Traceback: {traceback.format_exc()}")

            return ProcessResult(
                success=False,
                response=f"Erro ao retomar processamento: {str(e)}",
                agent_id=agent_id or "orchestrator-global",
                model="",
                tokens_used={"input": 0, "output": 0},
                tool_calls=[],
                error=str(e),
            )

    def _copywriting_skill_active_without_document(
        self, chat_id: str, user_id: str
    ) -> bool:
        """Returns True when SkillCopywriting was loaded but no copywriting document exists yet."""
        try:
            from App.Core.Crunch.TablesSQL.Models import IsolatedMessage as _IM

            _sess = self.db_manager.get_session()
            try:
                _skill_lookup = (
                    _sess.query(_IM)
                    .filter(
                        _IM.isolated_chat_id == chat_id,
                        _IM.tool_called == "lookup",
                        _IM.tool_call_type == "output",
                        _IM.content.ilike('%"SkillCopywriting.md"%'),
                        ~_IM.content.ilike("%blocked_files%"),
                    )
                    .order_by(_IM.id.desc())
                    .first()
                )
            finally:
                _sess.close()
            if not _skill_lookup:
                return False
            # Se o fluxo foi cancelado após o lookup, a skill não está mais ativa
            if self.core._check_flow_cancelled_in_chat(
                _skill_lookup.isolated_chat_id, since_id=_skill_lookup.id
            ):
                return False
            # Check if a copywriting document was created AFTER the most recent skill load in this chat.
            # Scoping by timestamp handles re-invocations of the skill in the same conversation.
            _result = DatabaseManager.fetch_all(
                "SELECT document_id FROM documents "
                "WHERE chat_id = :cid AND tool_type = 'copywriting' AND created_at > :after",
                {"cid": chat_id, "after": _skill_lookup.created_at},
            )
            return len(_result) == 0
        except Exception:
            return False

    def cancel_chat_processing(self, chat_id: str):
        """
        Cancela o processamento de um chat.
        Deve ser chamado quando POST /api/chat/{chat_id}/job/{job_id}/cancel  recebido.

        Args:
            chat_id: ID do chat a cancelar

        Returns:
            Dict com sucesso e mensagem
        """
        if not chat_id:
            return {"success": False, "error": "chat_id  obrigatrio"}

        self.mark_job_cancelled(chat_id)
        return {
            "success": True,
            "message": f"Chat {chat_id} foi marcado como cancelado",
            "chat_id": chat_id,
        }

    def process_parallel_agents(
        self,
        session_id: str,
        user_message: str,
        parent_agent_id: str,
    ) -> Dict[str, ProcessResult]:
        """
        Processa mensagem com mltiplos agentes em paralelo.

        Args:
            session_id: ID da sesso
            user_message: Mensagem do usurio
            parent_agent_id: ID do agente pai que coordena

        Returns:
            Dicionrio {agent_id: ProcessResult} para cada agente paralelo
        """
        import concurrent.futures

        try:
            debug(
                f"[MessageProcessor] Processing with parallel agents from: {parent_agent_id}"
            )

            # Obtm agentes paralelos
            parallel_agents = self.agents_manager.get_agents_for_parallel_execution(
                parent_agent_id
            )

            if not parallel_agents:
                debug(f"No parallel agents found for {parent_agent_id}")
                return {}

            debug(f"Found {len(parallel_agents)} agents to execute in parallel")

            results = {}

            # Executa agentes em paralelo usando ThreadPoolExecutor
            with concurrent.futures.ThreadPoolExecutor(
                max_workers=len(parallel_agents)
            ) as executor:
                futures = {}

                for agent in parallel_agents:
                    agent_id = agent.get("id")
                    future = executor.submit(
                        self.process_message,
                        session_id=session_id,
                        user_message=user_message,
                        agent_id=agent_id,
                    )
                    futures[future] = agent_id

                # Coleta resultados conforme ficam prontos
                for future in concurrent.futures.as_completed(futures):
                    agent_id = futures[future]
                    try:
                        result = future.result()
                        results[agent_id] = result
                        debug(f"Parallel agent {agent_id} completed: {result.success}")
                    except Exception as e:
                        error(f"Parallel agent {agent_id} failed: {e}")
                        results[agent_id] = ProcessResult(
                            success=False,
                            response="",
                            agent_id=agent_id,
                            model="unknown",
                            tokens_used={"input": 0, "output": 0},
                            error=str(e),
                        )

            return results

        except Exception as e:
            error(f"[MessageProcessor] Error in parallel processing: {e}")
            return {}

    def compact_context(
        self,
        isolated_chat_id: str,
        chat_id: str,
        user_id: str,
        cut_message_isolated_message_id: str,
    ) -> Dict[str, Any]:
        """
        Compacta o contexto da conversa at um ponto especfico.
        Usa o Agent Compactor para resumir conversas longas mantendo ~10k tokens.

        LGICA DE COMPACTING:
        1. Detecta quando contexto isolado ultrapassa 65% do limite (84.8k/128k tokens)
        2. Enfileira um job de compactao assncrona (no bloqueia processamento)
        3. Agent Compactor recupera mensagens at um cut_point (ltima mensagem de user)
        4. Resume a conversa mantendo informaes crticas (~10k tokens)
        5. Substitui bloco antigo no isolado_messages com resumo compactado
        6. Prximas iteraes do LLM usam contexto menor, ganhando mais espao para novas mensagens

        MOTIVAO:
        - Contexto isolado cresce indefinidamente em conversas longas
        - Sem compactao: 128k limite  ultrapassado rapidamente
        - Compactao mantm histrico rico mas resumido
        - Permite conversas muito longas sem perder coeso

        Args:
            isolated_chat_id: Chat ID (text) do chat isolado
            chat_id: ID do chat principal
            user_id: ID do usurio
            cut_message_isolated_message_id: UUID at qual mensagem compactar

        Returns:
            Dict com contexto compactado e metadados
        """
        try:
            # Carrega o agente compactor do AGENTS.json
            # Agent Compactor usa system_prompt especializado em resumir sem perder contexto
            agent_id = "context-compactor"
            compactor_agent = self.agents_manager.get_agent(agent_id)

            if not compactor_agent:
                error(f"[Compactor] Agent '{agent_id}' not found in AGENTS.json")
                return {
                    "success": False,
                    "error": f"Agent '{agent_id}' not found in configuration",
                    "tokens": 0,
                }

            db_session = self.db_manager.get_session()

            # ========== FASE 1: RECUPERAR MENSAGENS PARA COMPACTAR ==========
            # Localizar o chat isolado no banco
            from App.Core.Crunch.TablesSQL.Models import IsolatedChat, IsolatedMessage

            isolated_chat = (
                db_session.query(IsolatedChat)
                .filter(IsolatedChat.chat_id == isolated_chat_id)
                .first()
            )

            if not isolated_chat:
                return {
                    "success": False,
                    "error": "Isolated chat not found",
                    "tokens": 0,
                }

            # Recuperar TODAS as mensagens ativas (context_window=True)
            # Excluir: system prompts (metadata interna, no precisa resumir)
            # Incluir: user, assistant, tool calls (contexto importante da conversa)
            messages_to_compact = (
                db_session.query(IsolatedMessage)
                .filter(
                    IsolatedMessage.isolated_chat_id == isolated_chat_id,
                    IsolatedMessage.role != "system",
                    IsolatedMessage.context_window
                    == True,  # Apenas mensagens na janela ativa
                )
                .order_by(IsolatedMessage.created_at)
                .all()
            )

            if not messages_to_compact:
                debug(f"[Compactor] No messages to compact for chat {chat_id}")
                return {
                    "success": True,
                    "context_generated": "",
                    "tokens": 0,
                    "messages_compacted": 0,
                }

            # ========== FASE 2: PREPARAR MENSAGENS PARA COMPACTOR ==========
            # Construir preview legvel das mensagens
            # Limitar cada msg a 500 chars para evitar enviando dados enormes ao compactor
            # O Agent Compactor vai ler esse resumo e criar um resumo ainda mais curto
            messages_text = "\n".join(
                [
                    f"[{msg.agent}] {msg.role.upper()}: {msg.content[:500]}"  # Limitar para preview
                    for msg in messages_to_compact
                ]
            )

            # ========== FASE 3: ENVIAR PARA AGENT COMPACTOR ==========
            # Agent Compactor  um agente especial com system_prompt otimizado para resumir
            # Ele vai receber as mensagens e gerar um resumo mantendo:
            # - Contexto da conversa
            # - Decises importantes
            # - Dados crticos do usurio
            # - Mas DESCARTANDO: confirmaes, pequenas interaes, metadados internos
            debug(
                f"[Compactor] Sending {len(messages_to_compact)} messages to compactor for chat {chat_id}"
            )

            # Construir user message com contexto das mensagens
            compactor_user_message = f"""Resuma a seguinte conversa mantendo informaes crticas:

{messages_text}

Mantenha o resumo conciso e em formato markdown."""

            compactor_result = self.process_message(
                job_id=str(uuid.uuid4()),
                user_message=compactor_user_message,
                agent_id=agent_id,
                chat_id=chat_id,
                user_id=user_id,
                # system_prompt  obtido automaticamente de AGENTS.json via agent_id
            )

            if not compactor_result.success:
                error(
                    f"[Compactor] Failed to compact context: {compactor_result.error}"
                )
                return {"success": False, "error": compactor_result.error, "tokens": 0}

            context_generated = compactor_result.response
            tokens_used = compactor_result.tokens_used.get("output", 0)

            # Salvar contexto compactado em tabela context_window
            from App.Core.Crunch.TablesSQL.Models import ContextWindow

            context_window_entry = ContextWindow(
                isolated_chat_id=isolated_chat_id,
                cut_isolated_message_id=cut_message_isolated_message_id,
                context_generated=context_generated,
                agent_id=agent_id,
                agent="CONTEXT_COMPACTOR",
                tokens=tokens_used,
            )

            db_session.add(context_window_entry)

            # Marcar mensagens anteriores como no-contexto (context_window=False)
            for msg in messages_to_compact:
                msg.context_window = False

            db_session.commit()

            info(
                f"[Compactor] Context compacted: {len(messages_to_compact)} messages  {tokens_used} tokens"
            )

            return {
                "success": True,
                "context_generated": context_generated,
                "tokens": tokens_used,
                "messages_compacted": len(messages_to_compact),
                "cut_message_isolated_message_id": cut_message_isolated_message_id,
            }

        except Exception as e:
            error(f"[Compactor] Error compacting context: {e}", exc_info=True)
            if db_session:
                db_session.rollback()
            return {"success": False, "error": str(e), "tokens": 0}
        finally:
            if db_session:
                db_session.close()

    def enqueue_compaction(
        self,
        isolated_chat_id: str,
        chat_id: str,
        user_id: str,
        cut_message_isolated_message_id: str,
        agent_id: str,
    ) -> bool:
        """
        Enfileira um job de compactao de contexto quando tokens > 65%.

        Args:
            isolated_chat_id: Chat ID (text) do chat isolado
            chat_id: ID do chat principal
            user_id: ID do usurio
            cut_message_isolated_message_id: UUID at qual mensagem compactar
            agent_id: ID do agente que solicitou a compactao

        Returns:
            True se enfileirado com sucesso
        """
        try:
            from App.Core.Queues.MultiQueueManager import CompactorJob

            # Valida que o agente compactor existe no AGENTS.json
            compactor_agent_id = "context-compactor"
            if not self.agents_manager.get_agent(compactor_agent_id):
                error(
                    f"[Compactor] Agent '{compactor_agent_id}' not found in AGENTS.json, skipping enqueue"
                )
                return False

            # Obter client_id do usurio
            client_query = "SELECT client_id FROM users WHERE user_id = :user_id"
            client_result = DatabaseManager.fetch_one(
                client_query, {"user_id": user_id}
            )
            client_id = client_result.get("client_id") if client_result else 1

            # Converter isolated_chat_id para int (armazenado como text no banco)
            try:
                isolated_chat_id_int = (
                    int(isolated_chat_id)
                    if isinstance(isolated_chat_id, str)
                    else isolated_chat_id
                )
            except (ValueError, TypeError):
                error(f"[Compactor] Invalid isolated_chat_id: {isolated_chat_id}")
                return False

            compactor_job = CompactorJob(
                job_id=str(uuid.uuid4()),
                chat_id=chat_id,
                client_id=client_id,
                isolated_chat_id=isolated_chat_id_int,
                cut_message_uuid=cut_message_isolated_message_id,
                agent_id=compactor_agent_id,
                priority=5,  # Mdia prioridade
            )

            self.queue_manager.enqueue_job(
                operation_type=OperationType.COMPACTOR,
                chat_id=chat_id,
                job_data=compactor_job.to_dict(),
                priority=5,
            )

            info(
                f"[Compactor] Enqueued compaction job for chat {chat_id} (up to {cut_message_isolated_message_id[:8]}...)"
            )
            return True

        except Exception as e:
            error(f"[Compactor] Failed to enqueue compaction: {e}")
            return False
