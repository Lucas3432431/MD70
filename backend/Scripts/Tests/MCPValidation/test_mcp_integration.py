import asyncio
import json
import os
import sys
from pathlib import Path

# Adicionar raiz do backend ao path
backend_root = Path(__file__).parent.parent.parent.parent.parent
sys.path.append(str(backend_root))

from App.Core.Crunch import get_db_manager
from App.Core.Services.Common.Dependencies import COMPONENTS
from App.Core.Logs import info, error, debug, success, warning
from App.Features.Tools.Core import ToolCore
from App.Features.Tools.Mcp.MCPClientManager import mcp_manager


async def setup_test_data(db_manager):
    """Cria um cliente e uma config MCP de teste."""
    client_id = "test_client_mcp"
    user_id = "test_user_mcp"

    session = db_manager.get_session()
    try:
        from sqlalchemy import text
        from datetime import datetime
        import uuid

        # 1. Garantir que o cliente existe
        session.execute(
            text(
                "INSERT OR IGNORE INTO clients (client_id, plan_id) VALUES (:cid, 'free')"
            ),
            {"cid": client_id},
        )

        # 2. Garantir que o usuário existe
        session.execute(
            text(
                "INSERT OR IGNORE INTO users (user_id, client_id, email, password, full_name) VALUES (:uid, :cid, 'mcp@test.com', 'pwd', 'MCP Tester')"
            ),
            {"uid": user_id, "cid": client_id},
        )

        # 3. Inserir a configuração MCP (Meta Ads)
        # Limpar anterior
        session.execute(
            text(
                "DELETE FROM integrations_mcp WHERE client_id = :cid AND provider = 'meta-ads'"
            ),
            {"cid": client_id},
        )

        integration_id = str(uuid.uuid4())
        # NOTA: Usando valores dummy para o teste de descoberta.
        # Para testar a CHAMADA real, você precisaria preencher tokens válidos.
        env_vars = {
            "META_ACCESS_TOKEN": "TEST_TOKEN_DUMMY",
            "META_AD_ACCOUNT_ID": "act_123456789",
        }

        session.execute(
            text(
                """
                INSERT INTO integrations_mcp (integration_id, client_id, provider, command, args, env_vars, is_active)
                VALUES (:iid, :cid, 'meta-ads', 'npx', :args, :envs, 1)
            """
            ),
            {
                "iid": integration_id,
                "cid": client_id,
                "args": json.dumps(["-y", "meta-ads-mcp"]),
                "envs": json.dumps(env_vars),
            },
        )

        session.commit()
        success(f"Dados de teste configurados para cliente: {client_id}")
        return client_id, user_id
    except Exception as e:
        session.rollback()
        error(f"Erro ao configurar dados: {e}")
        return None, None
    finally:
        session.close()


async def run_validation():
    info("🚀 Iniciando Validação da Integração MCP...")

    # 1. Inicializar DB e Dependências
    db_manager = get_db_manager()
    if not db_manager:
        error("Falha ao inicializar DatabaseManager")
        return

    COMPONENTS["db_manager"] = db_manager

    # 2. Configurar Dados
    client_id, user_id = await setup_test_data(db_manager)
    if not client_id:
        return

    # 3. Testar Descoberta de Ferramentas via ToolCore
    info("\n--- TESTE 1: Descoberta de Ferramentas ---")
    core = ToolCore(user_id=user_id)

    # Inicializar manager (o Core fará isso via startup mas aqui fazemos manual se necessário)
    await mcp_manager.initialize()

    # Simular o que o Agente vê
    tools = core.get_available_tools(agent_id="orchestrator-global")

    mcp_tools = [t for t in tools if t["name"].startswith("mcp__")]

    if mcp_tools:
        success(f"✅ Sucesso! Encontradas {len(mcp_tools)} ferramentas MCP.")
        for t in mcp_tools:
            print(f"   - {t['name']}: {t['description'][:60]}...")
    else:
        error(
            "❌ Falha: Nenhuma ferramenta MCP encontrada. Verifique se o npx meta-ads-mcp está acessível."
        )

    # 4. Testar Execução (Simulada)
    info("\n--- TESTE 2: Execução de Ferramenta (Discovery/Help) ---")
    if mcp_tools:
        # Vamos tentar chamar a ferramenta de ajuda ou listagem do MCP da Meta
        # O nome deve ser algo como mcp__meta-ads__get_insights (depende do servidor)
        test_tool = mcp_tools[0]["name"]
        info(f"Tentando executar: {test_tool}")

        # Como não temos tokens reais, esperamos um erro do servidor MCP da Meta,
        # mas a DELEGAÇÃO do MD70 deve funcionar.
        result = core.execute_tool(test_tool, args={})
        info(f"Resultado da execução: {result}")

        if "meta-ads" in str(result).lower() or "token" in str(result).lower():
            success(
                "✅ Delegação para o processo MCP funcionou (recebemos resposta do servidor externo)."
            )
        else:
            warning(
                "⚠️ Recebemos uma resposta, mas não parece vir do servidor MCP esperado."
            )

    info("\n✅ Validação Finalizada.")


if __name__ == "__main__":
    # Importar nest_asyncio pois o Core.py usa loops aninhados
    try:
        import nest_asyncio

        nest_asyncio.apply()
    except ImportError:
        print("Aviso: nest_asyncio não instalado. Algumas chamadas podem falhar.")

    asyncio.run(run_validation())
