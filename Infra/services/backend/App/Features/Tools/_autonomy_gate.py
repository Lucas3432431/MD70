"""
_autonomy_gate.py — Mixin extraído de Core.py.
Core.py importa este módulo e herda AutonomyGateMixin.
NÃO edite a assinatura da classe — use Core.py como entry point.
"""

# ruff: noqa
# type: ignore
from __future__ import annotations
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    pass

import json
import uuid as uuid_lib
from App.Core.Logs import debug, error

# Tools that are always allowed regardless of autonomy level
# (structural/meta tools that don't perform external actions)
_ALWAYS_ALLOWED = {
    "context",
    "message",
    "chain_of_thought",
    "cancel",
    "status",
    "quiz",
    "task",
    "agent",
    "skill",
}

# Tools que sempre requerem aprovação explícita (geração paga, ações irreversíveis)
# Level 5 (bypass pós-aprovação) é o único que as executa sem parar
_ALWAYS_REQUIRE_APPROVAL = {
    "gen_free_image",
}

# Prefixes for DELETE-class operations (require autonomy level >= 4)
_DELETE_PREFIXES = (
    "delete_",
    "remove_",
    "trash_",
    "archive_",
    "revoke_",
)

# Prefixes for PATCH/PUT-class operations (require autonomy level >= 3)
_PATCH_PUT_PREFIXES = (
    "update_",
    "patch_",
    "edit_",
    "enable_",
    "disable_",
    "activate_",
    "deactivate_",
    "pause_",
    "mute_",
    "unmute_",
    "mark_",
    "move_",
)

# Prefixes for POST-class operations (require autonomy level >= 3)
# Create/send/publish são tão impactantes quanto editar — ex: enviar email, criar campanha
_POST_PREFIXES = (
    "create_",
    "send_",
    "add_",
    "insert_",
    "publish_",
    "schedule_",
    "submit_",
    "post_",
    "new_",
    "set_",
    "share_",
    "invite_",
    "grant_",
    "copy_",
    "clone_",
    "upload_",
    "generate_",
    "compose_",
    "reply_",
    "forward_",
)


def _is_delete_mcp_tool(tool_name: str) -> bool:
    """Returns True if the MCP tool performs a DELETE operation."""
    parts = tool_name.split("__")
    action = parts[-1].lower() if parts else tool_name.lower()
    bare_delete = {"delete", "remove", "trash", "archive", "revoke"}
    return action in bare_delete or any(action.startswith(p) for p in _DELETE_PREFIXES)


def _is_patch_put_mcp_tool(tool_name: str) -> bool:
    """Returns True if the MCP tool performs a PATCH or PUT operation."""
    parts = tool_name.split("__")
    action = parts[-1].lower() if parts else tool_name.lower()
    bare_patch_put = {
        "update",
        "patch",
        "edit",
        "enable",
        "disable",
        "activate",
        "deactivate",
        "pause",
        "mute",
        "unmute",
        "mark",
        "move",
    }
    return action in bare_patch_put or any(
        action.startswith(p) for p in _PATCH_PUT_PREFIXES
    )


def _is_post_mcp_tool(tool_name: str) -> bool:
    """Returns True if the MCP tool performs a POST/create operation.
    Tratado como nível 3 (igual a PATCH/PUT) pois criar campanhas, enviar emails
    ou publicar conteúdo é tão impactante quanto editar.
    """
    parts = tool_name.split("__")
    action = parts[-1].lower() if parts else tool_name.lower()
    bare_post = {
        "create",
        "send",
        "add",
        "insert",
        "publish",
        "schedule",
        "submit",
        "post",
        "new",
        "set",
        "share",
        "invite",
        "grant",
        "copy",
        "clone",
        "upload",
        "generate",
        "compose",
        "reply",
        "forward",
    }
    return action in bare_post or any(action.startswith(p) for p in _POST_PREFIXES)


class AutonomyGateMixin:
    """
    Gate de autonomia para todos os chats (normais, schedules e triggers).

    Níveis (schedules/triggers):
      1 — Sem autonomia: nenhuma tool externa executada (apenas texto)
      2 — Somente leitura livre (GET): POST/PATCH/PUT e DELETE aguardam aprovação
      3 — Leitura + escrita livre (GET, POST, PATCH/PUT): DELETE aguarda aprovação
      4 — Autonomia total (GET, POST, PATCH/PUT, DELETE): execução sem restrição
      5 — Bypass pós-aprovação: usado internamente pelo submit_tool_approval
          após o usuário confirmar — nunca configurar manualmente em schedules

    Chats normais (sem level configurado):
      Padrão = nível 2 (somente GET livre; POST/PATCH/PUT e DELETE exigem aprovação).

    Integra com trigger_tool_approvals: retorna {"status": "waiting", "pending_tool_approval": true}
    para que o MessageProcessor pause o loop e aguarde /tool_approval.
    """

    # Memoize por chat_id para evitar N queries por execução
    _autonomy_cache: dict = {}

    def _get_trigger_autonomy(self) -> Optional[int]:
        """
        Busca o autonomy_level do trigger ou scheduled_task vinculado ao chat atual.
        Retorna None se não encontrado (chat normal).
        """
        chat_id = getattr(self, "current_chat_id", None)
        if not chat_id:
            return None

        cache_key = chat_id
        if cache_key in self._autonomy_cache:
            return self._autonomy_cache[cache_key]

        try:
            from App.Core.Crunch.TablesSQL.DBManager import DatabaseManager as _DB

            # Tenta webhook trigger (chats com source='trigger', trigger_id = web_secret_id)
            row = _DB.fetch_one(
                """
                SELECT ws.autonomy_level
                FROM chats c
                JOIN webhook_secrets ws ON ws.web_secret_id = c.trigger_id
                WHERE c.chat_id = :cid AND c.source = 'trigger'
                LIMIT 1
                """,
                {"cid": chat_id},
            )
            if row and row.get("autonomy_level") is not None:
                level = int(row["autonomy_level"])
                self._autonomy_cache[cache_key] = level
                debug(f"[AutonomyGate] webhook chat={chat_id} → autonomy_level={level}")
                return level

            # Tenta scheduled task (chats com source='scheduled')
            row = _DB.fetch_one(
                """
                SELECT st.autonomy_level
                FROM chats c
                JOIN task_executions te ON te.chat_id = c.chat_id
                JOIN scheduled_tasks st ON st.id = te.task_id
                WHERE c.chat_id = :cid AND c.source = 'scheduled'
                LIMIT 1
                """,
                {"cid": chat_id},
            )
            if row and row.get("autonomy_level") is not None:
                level = int(row["autonomy_level"])
                self._autonomy_cache[cache_key] = level
                debug(
                    f"[AutonomyGate] scheduled chat={chat_id} → autonomy_level={level}"
                )
                return level

            self._autonomy_cache[cache_key] = None
            return None
        except Exception as e:
            debug(f"[AutonomyGate] Erro ao buscar autonomy_level: {e}")
            return None

    def _check_trigger_autonomy_gate(self, tool_name: str, args: dict) -> Optional[str]:
        """
        Verifica se a tool pode ser executada.

        Retorna:
            None        → execução permitida
            JSON str    → bloqueio ou waiting (aprovação pendente)
        """
        # Tools estruturais nunca são bloqueadas
        if tool_name in _ALWAYS_ALLOWED:
            return None

        # None = chat normal → nível 2 por padrão (GET/POST livres, PATCH/PUT/DELETE pedem aprovação)
        level = self._get_trigger_autonomy() or 2

        # Nível 5 = bypass pós-aprovação (set pelo submit_tool_approval) — passa direto
        if level >= 5:
            return None

        # Nível 1: sem autonomia — bloqueia qualquer tool externa (inclusive leitura)
        if level == 1:
            return json.dumps(
                {
                    "success": False,
                    "blocked_by_autonomy": True,
                    "autonomy_level": level,
                    "tool": tool_name,
                    "error": (
                        f"Tool '{tool_name}' bloqueada: autonomia desativada (nível 1). "
                        f"Apenas resposta em texto é permitida neste modo."
                    ),
                },
                ensure_ascii=False,
            )

        # Tools que sempre requerem aprovação explícita do usuário (geração paga)
        if tool_name in _ALWAYS_REQUIRE_APPROVAL:
            if level < 5:
                return self._create_tool_approval_pending(tool_name, args)

        if tool_name.startswith("mcp__"):
            # DELETE: requer nível >= 4 (ou aprovação explícita)
            if _is_delete_mcp_tool(tool_name):
                if level < 4:
                    return self._create_tool_approval_pending(tool_name, args)

            # PATCH/PUT e POST (write operations): requer nível >= 3
            elif _is_patch_put_mcp_tool(tool_name) or _is_post_mcp_tool(tool_name):
                if level < 3:
                    return self._create_tool_approval_pending(tool_name, args)

        return None

    def _try_fetch_current_values(self, tool_name: str, args: dict) -> dict | None:
        """
        Para tools de update conhecidas, busca os valores atuais da entidade via API
        para que o frontend possa exibir antigo → novo.
        Falha silenciosamente se não conseguir.
        """
        # tool_name pode vir como mcp__meta_ads__update_ad_set — extrair só a ação
        action = tool_name.split("__")[-1] if "__" in tool_name else tool_name

        _UPDATE_ENTITY_MAP = {
            "update_ad_set": ("ad_set_id", "name,status,daily_budget,lifetime_budget"),
            "pause_ad_set": ("ad_set_id", "name,status"),
            "enable_ad_set": ("ad_set_id", "name,status"),
            "update_campaign": (
                "campaign_id",
                "name,status,daily_budget,lifetime_budget",
            ),
            "pause_campaign": ("campaign_id", "name,status"),
            "enable_campaign": ("campaign_id", "name,status"),
            "update_ad": ("ad_id", "name,status"),
            "pause_ad": ("ad_id", "name,status"),
            "enable_ad": ("ad_id", "name,status"),
        }
        if action not in _UPDATE_ENTITY_MAP:
            return None

        id_key, fields = _UPDATE_ENTITY_MAP[action]
        entity_id = args.get(id_key)
        if not entity_id:
            return None

        try:
            from App.Core.Crunch.TablesSQL.DBManager import DatabaseManager as _DB
            import httpx

            user_id = getattr(self, "current_user_id", None)
            if not user_id:
                return None

            user_row = _DB.fetch_one(
                "SELECT client_id FROM users WHERE user_id = :uid LIMIT 1",
                {"uid": user_id},
            )
            if not user_row or not user_row.get("client_id"):
                return None
            client_id = user_row["client_id"]

            row = _DB.fetch_one(
                """
                SELECT env_vars FROM integrations_mcp
                WHERE client_id = :cid AND provider = 'meta-ads'
                  AND is_active = 1
                ORDER BY created_at DESC LIMIT 1
                """,
                {"cid": client_id},
            )
            if not row or not row.get("env_vars"):
                return None

            env = (
                json.loads(row["env_vars"])
                if isinstance(row["env_vars"], str)
                else row["env_vars"]
            )
            token = env.get("META_ACCESS_TOKEN", "")
            if not token:
                return None

            resp = httpx.get(
                f"https://graph.facebook.com/v21.0/{entity_id}",
                params={"fields": fields, "access_token": token},
                timeout=3.0,
            )
            data = resp.json()
            if "error" in data:
                return None
            data.pop("id", None)
            return data
        except Exception as e:
            debug(f"[AutonomyGate] _try_fetch_current_values falhou: {e}")
            return None

    def _create_tool_approval_pending(self, tool_name: str, args: dict) -> str:
        """
        Cria um registro pending em trigger_tool_approvals e retorna o JSON
        de waiting que faz o MessageProcessor pausar o job.
        Funciona para chats normais e scheduled/trigger.
        """
        chat_id = getattr(self, "current_chat_id", None)
        job_id = getattr(self, "current_job_id", None)
        tool_approval_id = str(uuid_lib.uuid4())

        current_values = self._try_fetch_current_values(tool_name, args)

        try:
            from App.Core.Crunch.TablesSQL.DBManager import DatabaseManager as _DB

            _DB.execute_query(
                """
                INSERT INTO trigger_tool_approvals
                    (id, chat_id, job_id, tool_name, args_json, status)
                VALUES
                    (:id, :chat_id, :job_id, :tool_name, :args_json, 'pending')
                """,
                {
                    "id": tool_approval_id,
                    "chat_id": chat_id,
                    "job_id": job_id,
                    "tool_name": tool_name,
                    "args_json": json.dumps(args, ensure_ascii=False),
                },
            )
            debug(
                f"[AutonomyGate] tool_approval criado: id={tool_approval_id}, tool={tool_name}"
            )
        except Exception as e:
            error(f"[AutonomyGate] Erro ao criar tool_approval: {e}")

        payload: dict = {
            "success": True,
            "status": "waiting",
            "pending_tool_approval": True,
            "tool_approval_id": tool_approval_id,
            "tool": tool_name,
            "args": args,
            "message": (
                f"Aprovação necessária para executar '{tool_name}'. "
                f"Aguardando confirmação do usuário..."
            ),
        }
        if current_values:
            payload["current_values"] = current_values

        return json.dumps(payload, ensure_ascii=False)
