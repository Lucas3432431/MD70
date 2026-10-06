import asyncio
import json
import os
from typing import Dict, List, Any, Optional
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

import httpx

from App.Core.Logs import debug, info, warning, error
from App.Core.Services.Common.Dependencies import COMPONENTS

from .Providers._shared import _TokenExpiredError, _refresh_access_token
from .Providers import (
    google_drive,
    google_calendar,
    gmail,
    google_analytics,
    google_ads,
    meta_ads,
    instagram,
    google_tasks,
    supabase,
    resend,
    linkedin,
    github,
)

# Providers implementados nativamente (sem processo externo)
_NATIVE_PROVIDERS = {
    "google-drive",
    "google-calendar",
    "gmail",
    "google-analytics",
    "google-ads",
    "meta-ads",
    "instagram",
    "google-tasks",
    "supabase",
    "resend",
    "github",
    "linkedin",
}

# Definições de ferramentas nativas por provider
_NATIVE_TOOL_DEFS: Dict[str, List[Dict]] = {
    "google-drive": google_drive.TOOL_DEFINITIONS,
    "google-calendar": google_calendar.TOOL_DEFINITIONS,
    "gmail": gmail.TOOL_DEFINITIONS,
    "google-analytics": google_analytics.TOOL_DEFINITIONS,
    "google-ads": google_ads.TOOL_DEFINITIONS,
    "meta-ads": meta_ads.TOOL_DEFINITIONS,
    "instagram": instagram.TOOL_DEFINITIONS,
    "google-tasks": google_tasks.TOOL_DEFINITIONS,
    "supabase": supabase.TOOL_DEFINITIONS,
    "resend": resend.TOOL_DEFINITIONS,
    "linkedin": linkedin.TOOL_DEFINITIONS,
    "github": github.TOOL_DEFINITIONS,
}

_NATIVE_CALLERS = {
    "google-drive": google_drive.call,
    "google-calendar": google_calendar.call,
    "gmail": gmail.call,
    "google-analytics": google_analytics.call,
    "google-ads": google_ads.call,
    "meta-ads": meta_ads.call,
    "instagram": instagram.call,
    "google-tasks": google_tasks.call,
    "supabase": supabase.call,
    "resend": resend.call,
    "linkedin": linkedin.call,
    "github": github.call,
}


class MCPClientManager:
    """
    Gerenciador de Clientes MCP para o MD70 (Tenant-Isolated).

    Providers Google (Drive, Calendar, Gmail) são implementados nativamente via HTTP.
    Demais providers usam servidores MCP externos via stdio (npx).
    """

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(MCPClientManager, cls).__new__(cls)
            cls._instance.client_sessions = {}
            cls._instance.is_initialized = True
        return cls._instance

    def _mark_provider_token_invalid(self, client_id: str, provider: str) -> None:
        """Persiste token_valid=False no DB para o provider indicado."""
        try:
            db_manager = COMPONENTS.get("db_manager")
            if not db_manager:
                return
            from App.Core.Crunch.TablesSQL.DBManager import DatabaseManager as _DBMgr

            db_manager.execute_transaction(
                lambda session: _DBMgr.mark_integration_token_invalid(
                    session, client_id, provider
                )
            )
            debug(
                f"[MCP] Token inválido — {provider} marcado para reconexão (cliente {client_id})"
            )
        except Exception as _e:
            error(f"[MCP] Erro ao marcar token inválido ({provider}): {_e}")

    async def initialize(self):
        self.is_initialized = True
        debug("[MCP] Inicialização global concluída.")

    async def _get_client_configs(self, client_id: str) -> List[Dict[str, Any]]:
        db_manager = COMPONENTS.get("db_manager")
        if not db_manager:
            return []
        try:
            return db_manager.execute_transaction(
                lambda session: db_manager.get_mcp_configs(session, client_id)
            )
        except Exception as e:
            error(f"[MCP] Erro ao buscar configs do cliente {client_id}: {e}")
            return []

    async def _get_session(
        self, client_id: str, server_name: str
    ) -> Optional[ClientSession]:
        """Obtém ou cria sessão MCP externa (somente para providers não-nativos)."""
        if (
            client_id in self.client_sessions
            and server_name in self.client_sessions[client_id]
        ):
            return self.client_sessions[client_id][server_name]

        configs = await self._get_client_configs(client_id)
        server_config = next((c for c in configs if c["provider"] == server_name), None)
        if not server_config:
            return None

        try:
            env = os.environ.copy()
            env_vars = server_config.get("env", {})
            if isinstance(env_vars, str):
                env_vars = json.loads(env_vars)
            env.update(env_vars)

            args = server_config["args"]
            if isinstance(args, str):
                args = json.loads(args)

            params = StdioServerParameters(
                command=server_config["command"], args=args, env=env
            )

            async def run_client():
                async with stdio_client(params) as (read, write):
                    async with ClientSession(read, write) as session:
                        await session.initialize()
                        if client_id not in self.client_sessions:
                            self.client_sessions[client_id] = {}
                        self.client_sessions[client_id][server_name] = session
                        debug(f"[MCP] Sessão iniciada: {client_id}/{server_name}")
                        while (
                            client_id in self.client_sessions
                            and server_name in self.client_sessions[client_id]
                        ):
                            await asyncio.sleep(2)

            asyncio.create_task(run_client())

            for _ in range(20):
                if (
                    client_id in self.client_sessions
                    and server_name in self.client_sessions[client_id]
                ):
                    return self.client_sessions[client_id][server_name]
                await asyncio.sleep(0.5)

            error(f"[MCP] Timeout ao conectar com {server_name} para {client_id}")
            return None
        except Exception as e:
            error(f"[MCP] Erro fatal ao iniciar MCP {client_id}/{server_name}: {e}")
            return None

    async def get_all_tools(self, client_id: str) -> List[Dict[str, Any]]:
        if not client_id:
            return []

        configs = await self._get_client_configs(client_id)
        if not configs:
            return []

        all_tools = []
        for config in configs:
            provider = config["provider"]

            if provider in _NATIVE_PROVIDERS:
                # Provider nativo: retorna definições hardcoded sem spawnar processo
                all_tools.extend(_NATIVE_TOOL_DEFS.get(provider, []))
                debug(
                    f"[MCP] Provider nativo '{provider}' injetado para cliente {client_id}"
                )
                continue

            # Provider externo via MCP stdio
            session = await self._get_session(client_id, provider)
            if not session:
                continue
            try:
                response = await session.list_tools()
                for tool in response.tools:
                    all_tools.append(
                        {
                            "name": f"mcp__{provider}__{tool.name}",
                            "description": f"[{provider.upper()}] {tool.description}",
                            "parameters": tool.inputSchema,
                        }
                    )
            except Exception as e:
                error(
                    f"[MCP] Erro ao listar ferramentas de {provider} para {client_id}: {e}"
                )

        return all_tools

    async def call_tool(
        self,
        client_id: str,
        full_tool_name: str,
        arguments: Dict[str, Any],
        chat_id: str = "",
        user_id: str = "",
    ) -> Dict[str, Any]:
        try:
            if not full_tool_name.startswith("mcp__"):
                return {"error": "Nome de ferramenta MCP inválido"}

            parts = full_tool_name.split("__")
            if len(parts) < 3:
                return {"error": "Formato inválido. Use mcp__[provider]__[tool]"}

            provider = parts[1]
            tool_name = parts[2]

            # Core.py normaliza hífens → underscores no tool_name; reverter para lookup
            if provider not in _NATIVE_PROVIDERS:
                provider = provider.replace("_", "-")

            if provider in _NATIVE_PROVIDERS:
                # Buscar env_vars do banco para este cliente/provider
                configs = await self._get_client_configs(client_id)
                config = next((c for c in configs if c["provider"] == provider), None)
                if not config:
                    return {
                        "error": f"Integração '{provider}' não encontrada para este cliente."
                    }
                env = {
                    **config.get("env", {}),
                    "_chat_id": chat_id,
                    "_user_id": user_id,
                    "_client_id": client_id,
                }
                caller = _NATIVE_CALLERS[provider]
                try:
                    return await caller(tool_name, arguments, env)
                except _TokenExpiredError as _te:
                    self._mark_provider_token_invalid(client_id, provider)
                    if getattr(_te, "who", "user") == "system":
                        _err_msg = (
                            f"Developer Token do servidor para '{provider}' está inválido ou expirado "
                            "— contate o administrador do MD70."
                        )
                    else:
                        _err_msg = (
                            f"Token da sua conta '{provider}' expirou — "
                            "reconecte em Configurações → Integrações."
                        )
                    return {"success": False, "error": _err_msg}

            # Provider externo
            session = await self._get_session(client_id, provider)
            if not session:
                return {"error": f"Integração '{provider}' não encontrada ou inativa."}

            debug(f"[MCP] Executando {tool_name} (@{provider}) para {client_id}")
            result = await session.call_tool(tool_name, arguments)
            content = ""
            for c in result.content:
                if hasattr(c, "text"):
                    content += c.text + "\n"
                elif isinstance(c, dict) and "text" in c:
                    content += c["text"] + "\n"

            return {
                "success": True,
                "content": content.strip(),
                "is_error": result.isError,
            }

        except Exception as e:
            error(f"[MCP] call_tool error ({full_tool_name}): {e}")
            return {"error": str(e), "success": False}

    async def check_native_token_health(self, client_id: str) -> Dict[str, bool]:
        """
        Valida tokens dos providers nativos.
        Google: testa access_token via tokeninfo; se expirado, tenta refresh antes de marcar inválido.
        Meta/Instagram: chama /me para confirmar token.
        """
        # Mapa provider → env key do access_token
        _GOOGLE_PROVIDERS = {
            "google-drive": "GDRIVE_ACCESS_TOKEN",
            "google-calendar": "GCALENDAR_ACCESS_TOKEN",
            "gmail": "GMAIL_ACCESS_TOKEN",
            "google-analytics": "GANALYTICS_ACCESS_TOKEN",
            "google-ads": "GADS_ACCESS_TOKEN",
            "google-tasks": "GTASKS_ACCESS_TOKEN",
        }
        # Mapa provider → env key do refresh_token
        _GOOGLE_REFRESH_KEYS = {
            "google-drive": (
                "GDRIVE_CLIENT_ID",
                "GDRIVE_CLIENT_SECRET",
                "GDRIVE_REFRESH_TOKEN",
            ),
            "google-calendar": (
                "GCALENDAR_CLIENT_ID",
                "GCALENDAR_CLIENT_SECRET",
                "GCALENDAR_REFRESH_TOKEN",
            ),
            "gmail": ("GMAIL_CLIENT_ID", "GMAIL_CLIENT_SECRET", "GMAIL_REFRESH_TOKEN"),
            "google-analytics": (
                "GANALYTICS_CLIENT_ID",
                "GANALYTICS_CLIENT_SECRET",
                "GANALYTICS_REFRESH_TOKEN",
            ),
            "google-ads": (
                "GADS_CLIENT_ID",
                "GADS_CLIENT_SECRET",
                "GADS_REFRESH_TOKEN",
            ),
            "google-tasks": (
                "GTASKS_CLIENT_ID",
                "GTASKS_CLIENT_SECRET",
                "GTASKS_REFRESH_TOKEN",
            ),
        }

        results: Dict[str, bool] = {}
        configs = await self._get_client_configs(client_id)

        for config in configs:
            provider = config.get("provider", "")
            env = config.get("env", {})

            # ── Google providers ──────────────────────────────────────────────
            if provider in _GOOGLE_PROVIDERS:
                access_token = env.get(_GOOGLE_PROVIDERS[provider], "")
                if not access_token:
                    results[provider] = False
                    continue
                try:
                    async with httpx.AsyncClient(timeout=8.0) as http:
                        r = await http.get(
                            "https://www.googleapis.com/oauth2/v1/tokeninfo",
                            params={"access_token": access_token},
                        )
                    if (
                        r.status_code == 200
                        and int(r.json().get("expires_in", 0)) >= 60
                    ):
                        results[provider] = True
                        debug(f"[MCP-HEALTH] {provider} token válido")
                        continue
                    # access_token expirado — tentar refresh
                    cid_key, cs_key, rt_key = _GOOGLE_REFRESH_KEYS[provider]
                    refresh_token = env.get(rt_key, "")
                    client_id_oauth = env.get(cid_key, "")
                    client_secret = env.get(cs_key, "")
                    new_token = await _refresh_access_token(
                        client_id_oauth, client_secret, refresh_token
                    )
                    if new_token:
                        results[provider] = True
                        debug(f"[MCP-HEALTH] {provider} token renovado com sucesso")
                    else:
                        results[provider] = False
                        self._mark_provider_token_invalid(client_id, provider)
                        debug(
                            f"[MCP-HEALTH] {provider} refresh falhou — marcado inválido"
                        )
                except Exception as e:
                    debug(f"[MCP-HEALTH] Erro ao checar {provider}: {e}")

            # ── Meta / Instagram ──────────────────────────────────────────────
            elif provider in ("meta-ads", "instagram"):
                token = env.get("META_ACCESS_TOKEN", "")
                if not token:
                    continue
                try:
                    async with httpx.AsyncClient(timeout=8.0) as http:
                        resp = await http.get(
                            "https://graph.facebook.com/v21.0/me",
                            params={"access_token": token, "fields": "id"},
                        )
                        data = resp.json()
                        valid = "error" not in data
                        results[provider] = valid
                        debug(f"[MCP-HEALTH] {provider} token_valid={valid}")
                except Exception as e:
                    debug(f"[MCP-HEALTH] Erro ao checar {provider}: {e}")

            # ── GitHub ────────────────────────────────────────────────────────
            elif provider == "github":
                token = env.get("GITHUB_PERSONAL_ACCESS_TOKEN") or env.get(
                    "GITHUB_TOKEN", ""
                )
                if not token:
                    continue
                try:
                    async with httpx.AsyncClient(timeout=8.0) as http:
                        resp = await http.get(
                            "https://api.github.com/user",
                            headers={
                                "Authorization": f"Bearer {token}",
                                "X-GitHub-Api-Version": "2022-11-28",
                            },
                        )
                        valid = resp.status_code == 200
                        results[provider] = valid
                        debug(f"[MCP-HEALTH] github token_valid={valid}")
                except Exception as e:
                    debug(f"[MCP-HEALTH] Erro ao checar github: {e}")

            # ── LinkedIn ──────────────────────────────────────────────────────
            elif provider == "linkedin":
                token = env.get("LINKEDIN_ACCESS_TOKEN", "")
                if not token:
                    continue
                try:
                    async with httpx.AsyncClient(timeout=8.0) as http:
                        resp = await http.get(
                            "https://api.linkedin.com/v2/userinfo",
                            headers={"Authorization": f"Bearer {token}"},
                        )
                        valid = resp.status_code == 200
                        results[provider] = valid
                        debug(f"[MCP-HEALTH] linkedin token_valid={valid}")
                except Exception as e:
                    debug(f"[MCP-HEALTH] Erro ao checar linkedin: {e}")

        return results


# Singleton Global
mcp_manager = MCPClientManager()
