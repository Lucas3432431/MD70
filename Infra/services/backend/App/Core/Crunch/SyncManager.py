"""
SyncManager: Gerencia sincronização de mensagens isoladas para chat principal.
Lógica exclusiva de sincronização (isolated_messages → messages).
"""

import json
import re
from typing import Dict, List, Tuple, Optional, Any
from sqlalchemy.orm import Session
from App.Core.Logs import debug, info, warning, error
from App.Core.Crunch.TablesSQL.Models import IsolatedMessage, Message

# ============================================================================
# CONSTANTES - Configurações, Ferramentas, Padrões e Mensagens
# ============================================================================

# --- Ferramentas ---
# Carregar tools de TOOLS.json
import json
from pathlib import Path


def _load_tools_config():
    """Carrega TOOLS.json uma única vez"""
    # Ajustado para o caminho correto: App/Features/Tools/Tools/TOOLS.json
    tools_file = (
        Path(__file__).parent.parent.parent
        / "Features"
        / "Tools"
        / "Tools"
        / "TOOLS.json"
    )
    if tools_file.exists():
        with open(tools_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        return {name: info for name, info in data.get("tool_definitions", {}).items()}
    return {}


TOOLS_CONFIG = _load_tools_config()

# Ferramentas permitidas para sincronização (Todas por padrão a pedido do usuário)
ALLOWED_SYNC_TOOLS = list(TOOLS_CONFIG.keys())

# Ferramentas bloqueadas de sincronização (Vazio para sincronizar tudo)
SKIP_SYNC_TOOLS = []

# Ferramentas especiais
CONTEXT_TOOL = "context"

# --- Tipos de Mensagem ---
MESSAGE_TYPE_TOOL = "tool"
MESSAGE_TYPE_ASSISTANT = "assistant"
MESSAGE_TYPE_USER = "user"

# --- Tipos de Tool Call ---
TOOL_CALL_INPUT = "input"
TOOL_CALL_OUTPUT = "output"
TOOL_CALL_TYPE = "tool_call"

# --- Chaves JSON Padrão ---
JSON_KEY_TOOL = "tool"
JSON_KEY_SUCCESS = "success"
JSON_KEY_IS_UPDATE = "is_update"
JSON_KEY_NAME = "name"
JSON_KEY_STEP = "step"
JSON_KEY_STATUS = "status"
JSON_KEY_ACTION = "action"
JSON_KEY_RESULT = "result"
JSON_KEY_CONTENT = "content"
JSON_KEY_HELP = "help"
JSON_KEY_CALENDAR = "calendar"

# --- Status e Valores ---
STATUS_SUCCESS = "success"
STATUS_FAILED = "failed"
CALENDAR_NOW = "now"
CALENDAR_TODAY = "today"

# --- Padrões de Help ---
HELP_PATTERNS = [
    "help=true",
    '"help": true',
    "'help': true",
]

# --- Padrões de Calendar Auto-Injection ---
CALENDAR_AUTO_PATTERNS = [
    '"calendar": "now"',
    "'calendar': 'now'",
]

# --- Prefixos e Strings Literais ---
TOOL_PREFIX = "Tool: "
TOOL_MESSAGE_PREFIX = "Tool: message\n"

# --- Padrões Regex ---
TOOL_REGEX_PATTERN = r"Tool:\s*([\w-]+)"

# --- Nomes de Tools (comparações diretas no código) ---
TOOL_NAME_MESSAGE = "message"
TOOL_NAME_QUIZ = "quiz"
TOOL_NAME_SCHEDULE = "schedule"

# --- Comportamento de Sync em Erro ---
# Inline: False = pula output com success=false (não polui o chat com erros de ferramentas síncronas).
# Não-inline (web-search, asset, etc.): sempre sincroniza — user já viu o placeholder e precisa ver o resultado.
SYNC_ON_ERROR_INLINE = False

# --- Padrões de Schedule ---
SCHEDULE_PLAN_KEY = '"plan"'
SCHEDULE_CALENDAR_KEY = '"calendar"'
SCHEDULE_TYPE_MULTIPLE = "multiple_schedules"

# --- Modelo Padrão ---
MESSAGE_MODEL = "orchestrator"

# --- Mensagens de Debug ---
DEBUG_MESSAGES = {
    "fake_tool_call": "[SyncManager] Pulando fake tool call: conteúdo com formato 'Tool: ...' mas sem tool_called",
    "success_false": "[SyncManager] Pulando sincronização: success=false detectado",
    "help_true": "Skipping tool with help=true (tool instructions, no sync to main)",
    "help_response": "Skipping help=true response (OUTPUT, no sync to main)",
    "context_tool": "Skipping context tool - internal use only (no sync to main)",
    "lookup_tool": "Skipping lookup tool - internal use only (no sync to main)",
    "calendar_now": "Skipping calendar(calendar=now) auto-injection (no sync to main)",
    "calendar_now_output": "Skipping calendar(calendar=now) auto-injection OUTPUT (no sync to main)",
    "tool_error": "Skipping tool with error",
    "tool_pattern": "Skipping tool from content pattern",
    "tool_not_allowed": "Skipping tool - not in allowed sync tools list",
}

# ============================================================================


class SyncManager:
    """Gerencia sincronização de mensagens isoladas para chat principal"""

    @staticmethod
    def is_fake_tool_call(iso_msg: IsolatedMessage) -> bool:
        """
        Detecta se é uma tool call textual falsa ou malformada.
        """
        if not iso_msg or not iso_msg.content:
            return False
        content = iso_msg.content.strip()

        # Se é uma mensagem formal de tool_call, ela NÃO é fake, mesmo se o conteúdo tiver o padrão
        if iso_msg.type == TOOL_CALL_TYPE:
            return False

        # Se é assistant 'message' mas contém Tool: e Args:, é um alucinação textual
        if iso_msg.role == "assistant":
            # Usar lógica do MessageProcessor se disponível
            try:
                from App.Features.Chat.MessageProcessor import MessageProcessor

                if MessageProcessor.detect_malformed_tool_calls(content):
                    return True
            except:
                pass

            # Fallback manual robusto
            if content.startswith("Tool:") and (
                "Args:" in content or "Arguments:" in content
            ):
                return True

        return False

    @staticmethod
    def should_skip_sync(content: str) -> bool:
        """
        Verifica se o conteúdo tem success: false.
        """
        try:
            content_json = json.loads(content)
            if (
                isinstance(content_json, dict)
                and content_json.get(JSON_KEY_SUCCESS) is False
            ):
                debug(DEBUG_MESSAGES["success_false"])
                return True
        except:
            pass
        return False

    @staticmethod
    def _message_exists_in_main_chat(session, message_id: str) -> bool:
        """Verifica se mensagem já foi sincronizada no main chat."""
        from App.Core.Crunch.TablesSQL.Models import Message

        return (
            session.query(Message).filter(Message.message_id == message_id).first()
            is not None
        )

    @staticmethod
    def sync_isolated_messages(
        session, isolated_messages: List[IsolatedMessage], chat_id: str
    ) -> int:
        """
        Sincroniza mensagens isoladas para o chat principal em ordem cronológica.

        Usa isolated_chat_id para rastrear contexto de sincronização:
        - Se INPUT foi sincronizado (message_id existe), OUTPUT sobrepõe (UPDATE)
        - Se apenas OUTPUT chega (INPUT não foi sincronizado), insere novo (INSERT)
        """
        synced_count = 0

        # 1. Agrupar tool calls por ID
        tool_calls_map = {}
        for msg in isolated_messages:
            if msg.type == TOOL_CALL_TYPE and msg.tool_call_id:
                if msg.tool_call_id not in tool_calls_map:
                    tool_calls_map[msg.tool_call_id] = {"input": None, "output": None}

                if msg.tool_call_type == TOOL_CALL_INPUT:
                    tool_calls_map[msg.tool_call_id]["input"] = msg
                else:
                    tool_calls_map[msg.tool_call_id]["output"] = msg

        # 2. Processar mensagens na ordem original
        processed_tool_call_ids = set()
        sorted_msgs = sorted(
            isolated_messages,
            key=lambda x: (x.created_at if x.created_at else x.id, x.id),
        )

        for iso_msg in sorted_msgs:
            if iso_msg.type == TOOL_CALL_TYPE and iso_msg.tool_call_id:
                if iso_msg.tool_call_id in processed_tool_call_ids:
                    continue

                pair = tool_calls_map[iso_msg.tool_call_id]
                input_msg = pair["input"]
                output_msg = pair["output"]
                processed_tool_call_ids.add(iso_msg.tool_call_id)

                # Pular se o par deve ser ignorado (ex: Tool: ... Args: ...)
                if input_msg and SyncManager.is_fake_tool_call(input_msg):
                    continue

                should_skip_input, _ = (
                    SyncManager.should_skip_message(input_msg, session)
                    if input_msg
                    else (False, None)
                )
                should_skip_output, _ = (
                    SyncManager.should_skip_message(output_msg, session, input_msg)
                    if output_msg
                    else (False, None)
                )

                # Tool name detection (agressiva)
                tool_name = None
                if output_msg and output_msg.tool_called:
                    tool_name = output_msg.tool_called
                elif input_msg and input_msg.tool_called:
                    tool_name = input_msg.tool_called

                if not tool_name:
                    if output_msg:
                        tool_name = SyncManager.extract_tool_name(output_msg.content)
                    if not tool_name and input_msg:
                        tool_name = SyncManager.extract_tool_name(input_msg.content)

                tool_info = TOOLS_CONFIG.get(tool_name, {})
                is_inline = tool_info.get("is_inline_tool", False)

                # A. MESSAGE TOOL
                if tool_name == TOOL_NAME_MESSAGE and output_msg:
                    if SyncManager.should_skip_sync(output_msg.content):
                        continue
                    message_result = SyncManager.extract_message_message(
                        output_msg, input_msg
                    )
                    if message_result:
                        content, mtype = message_result
                        mid = (
                            input_msg.isolated_message_id
                            if input_msg
                            else output_msg.isolated_message_id
                        )
                        if SyncManager.update_or_insert_message(
                            session,
                            mid,
                            content,
                            mtype,
                            chat_id,
                            tool=None,
                            created_at=output_msg.created_at,
                        ):
                            synced_count += 1
                        continue

                # B. QUIZ EXCEPTION (INPUT deve ser sincronizado mesmo não sendo inline)
                if tool_name == TOOL_NAME_QUIZ:
                    # Se output tem erro, pula AMBOS (input + output)
                    if output_msg and SyncManager.should_skip_sync(output_msg.content):
                        continue

                    # Quiz input é exceção: SEMPRE sincroniza o input
                    if input_msg and not should_skip_input:
                        if not SyncManager.should_skip_sync(input_msg.content):
                            mtype = SyncManager.determine_message_type(input_msg)
                            if SyncManager.update_or_insert_message(
                                session,
                                input_msg.isolated_message_id,
                                input_msg.content,
                                mtype,
                                chat_id,
                                tool=tool_name,
                                created_at=input_msg.created_at,
                            ):
                                synced_count += 1
                    # Se tem output, sobrepõe o input
                    if output_msg and not should_skip_output:
                        if not SyncManager.should_skip_sync(output_msg.content):
                            mtype = SyncManager.determine_message_type(output_msg)
                            content = SyncManager.sanitize_success_content(
                                output_msg.content
                            )
                            mid = (
                                input_msg.isolated_message_id
                                if input_msg
                                else output_msg.isolated_message_id
                            )
                            if SyncManager.update_or_insert_message(
                                session,
                                mid,
                                content,
                                mtype,
                                chat_id,
                                tool=tool_name,
                                created_at=output_msg.created_at,
                            ):
                                synced_count += 1
                    continue

                # C. INLINE TOOLS (Ex: schedule, document)
                # Nunca sincroniza o input. Apenas o output.
                # Pula output com success=false (SYNC_ON_ERROR_INLINE=False).
                if is_inline:
                    if output_msg and not should_skip_output:
                        if not SYNC_ON_ERROR_INLINE and SyncManager.should_skip_sync(
                            output_msg.content
                        ):
                            continue

                        content_to_sync = output_msg.content
                        if (
                            tool_name == TOOL_NAME_SCHEDULE
                            and input_msg
                            and (
                                SCHEDULE_PLAN_KEY in input_msg.content
                                or SCHEDULE_CALENDAR_KEY in input_msg.content
                            )
                        ):
                            calendar_res = SyncManager.extract_calendar_message(
                                output_msg
                            )
                            if calendar_res:
                                content_to_sync, _ = calendar_res

                        content_to_sync = SyncManager.sanitize_success_content(
                            content_to_sync
                        )
                        content_to_sync = SyncManager.sanitize_sync_output(
                            content_to_sync
                        )
                        message_type = SyncManager.determine_message_type(output_msg)

                        mid = (
                            input_msg.isolated_message_id
                            if input_msg
                            else output_msg.isolated_message_id
                        )
                        cat = (
                            input_msg.created_at if input_msg else output_msg.created_at
                        )

                        if SyncManager.update_or_insert_message(
                            session,
                            mid,
                            content_to_sync,
                            message_type,
                            chat_id,
                            tool=tool_name,
                            created_at=cat,
                        ):
                            synced_count += 1
                    continue

                # D. OUTROS TOOL CALLS (não-inline / externos)
                # User já viu o input/placeholder → output sobrepõe mesmo com success=false (SYNC_ON_ERROR_NON_INLINE).
                mid = (
                    input_msg.isolated_message_id
                    if input_msg
                    else output_msg.isolated_message_id
                )
                cat = input_msg.created_at if input_msg else output_msg.created_at

                input_already_synced = (
                    input_msg
                    and SyncManager._message_exists_in_main_chat(
                        session, input_msg.isolated_message_id
                    )
                )

                if output_msg and not should_skip_output and input_already_synced:
                    # Output sobrepõe o input — sempre, independente de success
                    mtype = SyncManager.determine_message_type(output_msg)
                    tname = output_msg.tool_called or SyncManager.extract_tool_name(
                        output_msg.content
                    )
                    content = SyncManager.sanitize_sync_output(
                        SyncManager.sanitize_success_content(output_msg.content)
                    )
                    if SyncManager.update_or_insert_message(
                        session,
                        mid,
                        content,
                        mtype,
                        chat_id,
                        tool=tname,
                        created_at=cat,
                    ):
                        synced_count += 1

                elif output_msg and not should_skip_output and not input_already_synced:
                    # Output sem input sincronizado — usa mid (= ID do input se disponível)
                    mtype = SyncManager.determine_message_type(output_msg)
                    tname = output_msg.tool_called or SyncManager.extract_tool_name(
                        output_msg.content
                    )
                    content = SyncManager.sanitize_sync_output(
                        SyncManager.sanitize_success_content(output_msg.content)
                    )
                    if SyncManager.update_or_insert_message(
                        session,
                        mid,
                        content,
                        mtype,
                        chat_id,
                        tool=tname,
                        created_at=cat,
                    ):
                        synced_count += 1

                elif input_msg and not should_skip_input and not output_msg:
                    # Apenas input (sem output ainda): sincroniza como placeholder
                    if not SyncManager.should_skip_sync(input_msg.content):
                        mtype = SyncManager.determine_message_type(input_msg)
                        tname = input_msg.tool_called or SyncManager.extract_tool_name(
                            input_msg.content
                        )
                        # MCP tools: placeholder com content vazio para o frontend
                        # mostrar o card de loading sem expor o "Tool: mcp__... Args: ..."
                        content_to_sync = (
                            ""
                            if tname and tname.startswith("mcp__")
                            else input_msg.content
                        )
                        if SyncManager.update_or_insert_message(
                            session,
                            mid,
                            content_to_sync,
                            mtype,
                            chat_id,
                            tool=tname,
                            created_at=cat,
                        ):
                            synced_count += 1

            else:
                # MENSAGENS NORMAIS
                if SyncManager.is_fake_tool_call(iso_msg):
                    continue
                skip, reason = SyncManager.should_skip_message(iso_msg, session)
                if skip:
                    continue
                if SyncManager.should_skip_sync(iso_msg.content):
                    continue

                mtype = iso_msg.role
                content_to_sync = iso_msg.content
                if iso_msg.tool_called or iso_msg.type == TOOL_CALL_TYPE:
                    content_to_sync = SyncManager.sanitize_sync_output(content_to_sync)
                if SyncManager.update_or_insert_message(
                    session,
                    iso_msg.isolated_message_id,
                    content_to_sync,
                    mtype,
                    chat_id,
                    tool="",
                    created_at=iso_msg.created_at,
                ):
                    synced_count += 1

        session.commit()
        SyncManager.prune_main_chat(session, chat_id)

        # Atualizar context_usage_pct no chat com base nos tokens da conversa isolada
        SyncManager._update_context_usage_pct(session, chat_id)

        if synced_count > 0:
            try:
                from App.Core.Cache.RedisCache import cache_delete

                cache_delete(f"chat:{chat_id}")
            except Exception:
                pass
            try:
                from App.Core.Services.Chat.ChatRoutes import broadcast_db_updated

                broadcast_db_updated(chat_id)
            except Exception:
                pass
        return synced_count

    _MODEL_MAX_CONTEXT = 131_072  # limite do deepseek-chat (modelo principal)

    @staticmethod
    def _update_context_usage_pct(session, chat_id: str) -> None:
        """Atualiza context_usage_pct na tabela chats com base no maior input_tokens registrado."""
        try:
            from sqlalchemy import text as _text

            row = session.execute(
                _text(
                    "SELECT MAX(input_tokens) as max_tok FROM isolated_messages WHERE isolated_chat_id = :cid"
                ),
                {"cid": chat_id},
            ).fetchone()

            if row and row[0]:
                pct = round(min(row[0] / SyncManager._MODEL_MAX_CONTEXT, 1.0), 4)
                session.execute(
                    _text(
                        "UPDATE chats SET context_usage_pct = :pct WHERE chat_id = :cid"
                    ),
                    {"pct": pct, "cid": chat_id},
                )
                session.commit()
        except Exception as e:
            debug(f"[SyncManager] Erro ao atualizar context_usage_pct: {e}")

    @staticmethod
    def extract_message_message(
        output_msg: IsolatedMessage, input_msg: Optional[IsolatedMessage] = None
    ) -> Optional[Tuple[str, str]]:
        """Extrai texto da message tool."""
        try:
            data = json.loads(output_msg.content)
            if data.get(JSON_KEY_TOOL) == "message" and data.get(JSON_KEY_SUCCESS):
                return data.get("message", ""), "assistant"
        except:
            pass

        if input_msg and input_msg.tool_called == "message":
            return output_msg.content, "assistant"

        return None

    @staticmethod
    def extract_calendar_message(iso_msg: IsolatedMessage) -> Optional[Tuple[str, str]]:
        """Extrai JSON de calendário."""
        try:
            data = json.loads(iso_msg.content)
            if data.get(JSON_KEY_SUCCESS):
                data[JSON_KEY_TOOL] = "schedule"
                return json.dumps(data, ensure_ascii=False), "assistant"
        except:
            pass
        return None

    @staticmethod
    def sanitize_success_content(content: str) -> str:
        """Limpa campos de erro se success=true."""
        try:
            data = json.loads(content)
            if data.get(JSON_KEY_SUCCESS) is True:
                for k in list(data.keys()):
                    if "error" in k.lower():
                        data.pop(k)
                return json.dumps(data, ensure_ascii=False)
        except:
            pass
        return content

    @staticmethod
    def sanitize_sync_output(content: str) -> str:
        """Remove campos internos do JSON de output antes de sincronizar para o main chat.
        - Remove 'content' para evitar vazar conteúdo extenso (ex: web-search)
        - Preserva 'input' para que o frontend possa exibir os args enviados na execução
        """
        try:
            data = json.loads(content)
            if not isinstance(data, dict):
                return content
            changed = False
            if JSON_KEY_CONTENT in data:
                data.pop(JSON_KEY_CONTENT)
                changed = True
            if "results" in data and isinstance(data["results"], list):
                for item in data["results"]:
                    if isinstance(item, dict) and JSON_KEY_CONTENT in item:
                        item.pop(JSON_KEY_CONTENT)
                        changed = True
            if changed:
                return json.dumps(data, ensure_ascii=False)
        except:
            pass
        return content

    @staticmethod
    def determine_message_type(iso_msg: IsolatedMessage) -> str:
        """Determina tipo visual."""
        if iso_msg.type != TOOL_CALL_TYPE:
            return iso_msg.role
        try:
            data = json.loads(iso_msg.content)
            if data.get(JSON_KEY_TOOL) == "message" and data.get(JSON_KEY_SUCCESS):
                return "assistant"
        except:
            pass
        return "tool"

    @staticmethod
    def should_skip_message(
        iso_msg: IsolatedMessage,
        session: Session,
        input_msg: Optional[IsolatedMessage] = None,
    ) -> Tuple[bool, Optional[str]]:
        """Regras de exclusão."""
        if not iso_msg:
            return True, "Null"
        if iso_msg.role == "system":
            return True, "System"

        content = iso_msg.content.strip() if iso_msg.content else ""

        # O check de fake_tool_call agora é feito externamente ou via role:
        if SyncManager.is_fake_tool_call(iso_msg):
            return True, "Fake/Malformed Tool Call"

        # 2. Pular se parece JSON mas é inválido
        if content.startswith("{") or content.startswith("["):
            try:
                json.loads(content)
            except:
                return True, "Malformed JSON"

        # 3. Pular input de tool que não segue padrão formal nem textual
        if iso_msg.type == TOOL_CALL_TYPE and iso_msg.tool_call_type == TOOL_CALL_INPUT:
            if not content.startswith("{") and not content.startswith("Tool: "):
                # Verificar se o MessageProcessor detecta algo
                try:
                    from App.Features.Chat.MessageProcessor import MessageProcessor

                    if not MessageProcessor.detect_malformed_tool_calls(content):
                        return True, "Invalid tool input format"
                except:
                    return True, "Invalid tool input format"

        tool_name = iso_msg.tool_called
        if not tool_name:
            tool_name = SyncManager.extract_tool_name(content)

        if tool_name:
            if tool_name in SKIP_SYNC_TOOLS:
                return True, f"Tool {tool_name} blocked"

            # Filtro especial para schedule: pular registration sem IDs
            if (
                tool_name == TOOL_NAME_SCHEDULE
                and iso_msg.tool_call_type == TOOL_CALL_OUTPUT
            ):
                try:
                    data = json.loads(content)
                    if data.get("type") == SCHEDULE_TYPE_MULTIPLE:
                        results = data.get("results", [])
                        if results:
                            all_null = True
                            for r in results:
                                pids = r.get("post_ids", [])
                                if pids and any(pid is not None for pid in pids):
                                    all_null = False
                                    break
                            if all_null:
                                return (
                                    True,
                                    "Schedule registration with no IDs (Output)",
                                )
                except:
                    pass

        if "help=true" in content or '"help": true' in content:
            return True, "Help"

        return False, None

    @staticmethod
    def update_or_insert_message(
        session: Session,
        message_id: str,
        content: str,
        message_type: str,
        chat_id: str,
        tool: Optional[str] = None,
        created_at=None,
    ) -> bool:
        """Surgical update or insert."""
        from App.Core.Crunch.TablesSQL.Models import Message

        if tool is None:
            tool = SyncManager.extract_tool_name(content)
        if tool == "":
            tool = None

        existing = (
            session.query(Message).filter(Message.message_id == message_id).first()
        )

        if existing:
            # Forçar atualização se conteúdo ou tipo mudou
            if existing.content != content or existing.message_type != message_type:
                existing.content = content
                existing.message_type = message_type
                if tool is not None:
                    existing.tool = tool
                if created_at:
                    existing.created_at = created_at
                session.add(existing)
                return True
            return False

        new_msg = Message(
            message_id=message_id,
            chat_id=chat_id,
            message_type=message_type,
            content=content,
            tool=tool,
            model=MESSAGE_MODEL,
            created_at=created_at if created_at else None,
        )
        session.add(new_msg)
        return True

    @staticmethod
    def extract_tool_name(content: str) -> Optional[str]:
        """Tenta achar nome da tool."""
        try:
            data = json.loads(content)
            if isinstance(data, dict):
                if data.get(JSON_KEY_TOOL):
                    return data.get(JSON_KEY_TOOL)
                # Tentar extrair do success response
                if data.get("type") == "plan" and "calendar" in data:
                    return "schedule"
        except:
            pass
        match = re.search(r"Tool:\s*([\w-]+)", content)
        return match.group(1) if match else None

    # ── Pruning ───────────────────────────────────────────────────────────────

    @staticmethod
    def _is_error_content(content: str) -> bool:
        """Retorna True se o conteúdo JSON tem success=false."""
        try:
            return json.loads(content).get(JSON_KEY_SUCCESS) is False
        except:
            return False

    @staticmethod
    def _is_quiz_output_content(content: str) -> bool:
        """Retorna True se o conteúdo é saída de quiz (success=true ou final_answers presente)."""
        try:
            data = json.loads(content)
            return data.get(JSON_KEY_SUCCESS) is True or "final_answers" in data
        except:
            return False

    @staticmethod
    def prune_main_chat(session: Session, chat_id: str) -> int:
        """
        Limpa o main chat após sincronização:

        1. Erros antigos: remove mensagens com success=false que não sejam
           a mais recente no chat (só o último erro fica visível).

        2. Quiz inputs órfãos: remove inputs de quiz sem output correspondente
           quando já existem 2+ mensagens mais novas no chat (o quiz foi
           abandonado e nunca respondido).
        """
        from App.Core.Crunch.TablesSQL.Models import Message

        pruned = 0

        # Todos os msgs do chat ordenados por data e id interno
        all_msgs: List[Message] = (
            session.query(Message)
            .filter(Message.chat_id == chat_id)
            .order_by(Message.created_at, Message.id)
            .all()
        )

        # ── 1. Remove erros antigos (mantém só o último) ──────────────────────
        error_msgs = [m for m in all_msgs if SyncManager._is_error_content(m.content)]
        for msg in error_msgs[:-1]:  # todos menos o último
            debug(
                f"[SyncManager.prune] Removendo erro antigo: message_id={msg.message_id}"
            )
            session.delete(msg)
            all_msgs.remove(msg)
            pruned += 1

        # ── 2. Remove quiz inputs órfãos (sem output, 2+ msgs depois) ─────────
        for msg in list(all_msgs):
            if msg.tool != TOOL_NAME_QUIZ:
                continue
            if SyncManager._is_quiz_output_content(msg.content):
                continue  # já tem output, não é órfão

            # Conta mensagens posteriores (por posição na lista já ordenada)
            idx = all_msgs.index(msg)
            msgs_after = len(all_msgs) - idx - 1
            if msgs_after >= 2:
                debug(
                    f"[SyncManager.prune] Removendo quiz input órfão: message_id={msg.message_id} ({msgs_after} msgs depois)"
                )
                session.delete(msg)
                all_msgs.remove(msg)
                pruned += 1

        if pruned:
            session.commit()
            info(
                f"[SyncManager.prune] {pruned} mensagem(ns) removida(s) do main chat={chat_id}"
            )

        return pruned
