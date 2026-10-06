from typing import Any, Dict
from fastapi import HTTPException

# Global dictionary to store initialized components
COMPONENTS: Dict[str, Any] = {}


def get_component(name: str):
    """Função de dependência para obter um componente pelo nome."""
    component = COMPONENTS.get(name)
    if not component:
        raise HTTPException(
            status_code=500, detail=f"Componente '{name}' não inicializado."
        )
    return component


# Funções de dependência
def get_bot():
    return get_component("bot")


def get_chat_manager():
    return get_component("chat_manager")


def get_llm_client():
    return get_component("llm_client")


def get_agent_manager():
    return get_component("agent_manager")


def get_tool_facilitator():
    return get_component("tool_facilitator")


def get_specialized_agents_manager():
    return get_component("agents_manager")


def get_config():
    return get_component("config")


def get_auth_manager():
    return get_component("auth_manager")


def get_notification_service():
    return get_component("notification_service")
