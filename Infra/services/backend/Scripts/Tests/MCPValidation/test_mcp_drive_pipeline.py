"""
Diagnóstico completo do pipeline MCP para o usuário admin com Google Drive configurado.

Testa cada camada individualmente para identificar onde a falha ocorre:
  1. DB: get_mcp_configs retorna registros?
  2. Descriptografia: env_vars decriptados têm as chaves certas?
  3. MCPClientManager.get_all_tools retorna tools?
  4. MCPClientManager.call_tool chama a API real?
  5. Core.py flow: user_id → client_id → get_all_tools (simula fluxo do agente)

Uso:
    cd /home/lucascamargo/Lucas/Apps/MD70/App/mvp/services/backend
    python Scripts/Tests/MCPValidation/test_mcp_drive_pipeline.py
"""

import asyncio
import json
import sys
from pathlib import Path
from types import ModuleType

backend_root = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(backend_root))

# Mock de módulos problemáticos ANTES de qualquer import para quebrar o chain circular:
# MCPClientManager → App.Core.Services.Common.Dependencies
#                  → App.Core.Services.Common.__init__ → AppSetup → LLMClient → Core → MCPClientManager
_COMPONENTS: dict = {}


def _mock_module(name: str, **attrs):
    m = ModuleType(name)
    for k, v in attrs.items():
        setattr(m, k, v)
    sys.modules[name] = m
    return m


_mock_module("App.Core.Services.Common.Dependencies", COMPONENTS=_COMPONENTS)
# Bloqueia os __init__.py dos pacotes pai para não disparar o chain
_mock_module("App.Core.Services")
_mock_module("App.Core.Services.Common")

ADMIN_USER_ID = "551"
ADMIN_CLIENT_ID = "551"

SEP = "─" * 60


def _ok(msg):
    print(f"  ✓ {msg}")


def _fail(msg):
    print(f"  ✗ {msg}")


def _info(msg):
    print(f"  · {msg}")


# ─────────────────────────────────────────────────────────────────────────────
# PASSO 1: Banco — get_mcp_configs
# ─────────────────────────────────────────────────────────────────────────────


def test_db_mcp_configs():
    print(f"\n{SEP}")
    print("PASSO 1 — DB: get_mcp_configs")
    print(SEP)

    from App.Core.Crunch import get_db_manager

    db = get_db_manager()

    configs = db.execute_transaction(
        lambda session: db.get_mcp_configs(session, ADMIN_CLIENT_ID)
    )

    if not configs:
        _fail(f"Nenhuma config MCP encontrada para client_id={ADMIN_CLIENT_ID}")
        return []

    for cfg in configs:
        _ok(f"Provider: {cfg['provider']}")
        env_keys = list(cfg.get("env", {}).keys())
        _info(f"  env_vars keys: {env_keys}")
        if not env_keys:
            _fail("  env_vars VAZIO — dados não decriptados ou não salvos!")
        else:
            _ok(f"  {len(env_keys)} chaves de env presentes")

    return configs


# ─────────────────────────────────────────────────────────────────────────────
# PASSO 2: Criptografia — raw do banco antes da descriptografia
# ─────────────────────────────────────────────────────────────────────────────


def test_raw_encryption():
    print(f"\n{SEP}")
    print("PASSO 2 — Criptografia: raw env_vars no banco")
    print(SEP)

    from App.Core.Crunch import get_db_manager
    from App.Core.Crunch.TablesSQL.DBCryptographyManager import DBCryptographyManager
    from App.Core.Crunch.TablesSQL.Models import IntegrationMCP

    db = get_db_manager()
    session = db.get_session()

    try:
        records = (
            session.query(IntegrationMCP)
            .filter(IntegrationMCP.client_id == ADMIN_CLIENT_ID)
            .all()
        )

        if not records:
            _fail(f"Nenhum registro IntegrationMCP para client_id={ADMIN_CLIENT_ID}")
            return

        for r in records:
            _ok(f"Provider: {r.provider} | is_active={r.is_active}")
            raw = r.env_vars or {}
            _info(f"  env_vars raw type: {type(raw).__name__}")
            _info(
                f"  env_vars raw keys: {list(raw.keys()) if isinstance(raw, dict) else '(não é dict)'}"
            )

            if isinstance(raw, dict) and "_enc" in raw:
                _ok("  Formato criptografado {'_enc': ...} detectado")
                ciphertext = raw["_enc"]
                _info(f"  Primeiros 80 chars do ciphertext: {ciphertext[:80]}...")

                decrypted = DBCryptographyManager.decrypt_field(ciphertext)
                if decrypted:
                    _ok("  Descriptografia OK")
                    try:
                        env_dict = json.loads(decrypted)
                        _ok(f"  JSON parsed OK — chaves: {list(env_dict.keys())}")
                    except Exception as e:
                        _fail(f"  JSON parse falhou: {e}")
                        _info(f"  Conteúdo raw decriptado: {decrypted[:200]}")
                else:
                    _fail("  decrypt_field retornou None!")
            elif isinstance(raw, dict):
                _info(
                    "  Dado plain (não criptografado) — chaves: "
                    + str(list(raw.keys()))
                )
            else:
                _fail(f"  Formato desconhecido: {raw}")
    finally:
        session.close()


# ─────────────────────────────────────────────────────────────────────────────
# PASSO 3: MCPClientManager.get_all_tools
# ─────────────────────────────────────────────────────────────────────────────


async def test_get_all_tools():
    print(f"\n{SEP}")
    print("PASSO 3 — MCPClientManager.get_all_tools")
    print(SEP)

    from App.Core.Crunch import get_db_manager
    from App.Features.Tools.Mcp.MCPClientManager import mcp_manager
    from App.Core.Services.Common.Dependencies import COMPONENTS

    db = get_db_manager()
    COMPONENTS["db_manager"] = db

    tools = await mcp_manager.get_all_tools(ADMIN_CLIENT_ID)

    if not tools:
        _fail(f"get_all_tools retornou lista VAZIA para client_id={ADMIN_CLIENT_ID}")
    else:
        _ok(f"{len(tools)} ferramentas retornadas:")
        for t in tools:
            _info(f"  - {t['name']}")

    return tools


# ─────────────────────────────────────────────────────────────────────────────
# PASSO 4: MCPClientManager.call_tool (Drive list)
# ─────────────────────────────────────────────────────────────────────────────


async def test_call_tool():
    print(f"\n{SEP}")
    print("PASSO 4 — MCPClientManager.call_tool (mcp__google-drive__list)")
    print(SEP)

    from App.Core.Crunch import get_db_manager
    from App.Features.Tools.Mcp.MCPClientManager import mcp_manager
    from App.Core.Services.Common.Dependencies import COMPONENTS

    db = get_db_manager()
    COMPONENTS["db_manager"] = db

    result = await mcp_manager.call_tool(
        ADMIN_CLIENT_ID,
        "mcp__google-drive__list",
        {"max_results": 5},
    )

    if result.get("success"):
        _ok("call_tool retornou sucesso!")
        _info(f"  Conteúdo:\n{result.get('content', '')[:500]}")
    else:
        _fail(f"call_tool falhou: {result.get('error', result)}")


# ─────────────────────────────────────────────────────────────────────────────
# PASSO 5: Simula fluxo do Core.py (user_id → client_id → tools)
# ─────────────────────────────────────────────────────────────────────────────


async def test_core_flow():
    print(f"\n{SEP}")
    print("PASSO 5 — Fluxo Core.py: user_id → client_id → get_all_tools")
    print(SEP)

    from App.Core.Crunch import get_db_manager
    from App.Features.Tools.Mcp.MCPClientManager import mcp_manager
    from App.Core.Services.Common.Dependencies import COMPONENTS

    db = get_db_manager()
    COMPONENTS["db_manager"] = db

    # Resolve client_id a partir do user_id (o que Core.py faz)
    client_id = db.execute_transaction(
        lambda session: db.get_client_id_by_user_id(session, ADMIN_USER_ID)
    )

    _info(f"user_id={ADMIN_USER_ID}")

    if not client_id:
        _fail(f"get_client_id_by_user_id retornou None para user_id={ADMIN_USER_ID}")
        return

    _ok(f"client_id resolvido: {client_id}")

    if str(client_id) != ADMIN_CLIENT_ID:
        _fail(
            f"client_id DIVERGE do esperado! got={client_id} expected={ADMIN_CLIENT_ID}"
        )
    else:
        _ok("client_id bate com o esperado")

    tools = await mcp_manager.get_all_tools(str(client_id))
    if not tools:
        _fail("get_all_tools retornou VAZIO via fluxo Core.py")
    else:
        _ok(f"{len(tools)} ferramentas via fluxo Core.py: {[t['name'] for t in tools]}")


# ─────────────────────────────────────────────────────────────────────────────
# PASSO 6: Verificação do formato get_available_tools (OpenAI schema)
# ─────────────────────────────────────────────────────────────────────────────


async def test_openai_schema():
    print(f"\n{SEP}")
    print("PASSO 6 — Formato OpenAI: tools têm 'type' e 'function'?")
    print(SEP)

    from App.Core.Crunch import get_db_manager
    from App.Features.Tools.Mcp.MCPClientManager import mcp_manager
    from App.Core.Services.Common.Dependencies import COMPONENTS

    db = get_db_manager()
    COMPONENTS["db_manager"] = db

    tools = await mcp_manager.get_all_tools(ADMIN_CLIENT_ID)

    if not tools:
        _fail("Nenhuma tool para verificar schema")
        return

    for t in tools:
        name = t.get("name", "?")
        has_type = "type" in t
        has_function = "function" in t
        has_name = "name" in t
        has_parameters = "parameters" in t

        if has_type and has_function:
            _info(f"{name}: formato OpenAI wrapper {{'type','function'}} ✓")
        elif has_name and has_parameters:
            _ok(
                f"{name}: formato direto {{'name','description','parameters'}} — Core.py precisa converter"
            )
        else:
            _fail(f"{name}: formato desconhecido — keys: {list(t.keys())}")


# ─────────────────────────────────────────────────────────────────────────────
# PASSO 7: Simula branch loop.is_running() do Core.py com nest_asyncio
# ─────────────────────────────────────────────────────────────────────────────


async def test_nested_event_loop():
    print(f"\n{SEP}")
    print("PASSO 7 — Simula branch loop.is_running() + nest_asyncio (como Core.py)")
    print(SEP)

    from App.Core.Crunch import get_db_manager
    from App.Features.Tools.Mcp.MCPClientManager import mcp_manager

    db = get_db_manager()
    _COMPONENTS["db_manager"] = db

    import asyncio
    import nest_asyncio

    loop = asyncio.get_event_loop()
    _info(f"loop.is_running()={loop.is_running()}")
    _info(f"mcp_manager.is_initialized={mcp_manager.is_initialized}")

    nest_asyncio.apply()

    # Simula exatamente o que Core.py faz:
    try:
        mcp_tools = loop.run_until_complete(mcp_manager.get_all_tools(ADMIN_CLIENT_ID))
        if mcp_tools:
            _ok(
                f"loop.run_until_complete retornou {len(mcp_tools)} tools: {[t['name'] for t in mcp_tools]}"
            )
        else:
            _fail(
                "loop.run_until_complete retornou LISTA VAZIA — este é o bug no Core.py!"
            )
    except Exception as e:
        _fail(f"Exceção em loop.run_until_complete: {e}")
        import traceback

        _info(traceback.format_exc())


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────


async def main():
    print("\n" + "═" * 60)
    print("DIAGNÓSTICO MCP PIPELINE — Google Drive")
    print(f"Admin user_id  : {ADMIN_USER_ID}")
    print(f"Admin client_id: {ADMIN_CLIENT_ID}")
    print("═" * 60)

    test_db_mcp_configs()
    test_raw_encryption()
    await test_get_all_tools()
    await test_call_tool()
    await test_core_flow()
    await test_openai_schema()
    await test_nested_event_loop()

    print(f"\n{SEP}")
    print("Diagnóstico concluído.")
    print(SEP)


if __name__ == "__main__":
    asyncio.run(main())
