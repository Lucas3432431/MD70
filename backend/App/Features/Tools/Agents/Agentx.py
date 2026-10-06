#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
agentx.py

Gerenciador de Agents com isolamento de contexto e hierarquia.
Similar ao tool_facilitor.py, mas para orquestração de agents.

Carrega AGENTS.json e fornece:
- Acesso restrito: cada agent só vê seus direct sub-agents
- Conversas isoladas: cada dupla de agents tem sua própria conversa
- Definições para a IA: formato similar ao _TOOLS.json
"""

import json
import sys
import uuid
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict, field
from datetime import datetime
from App.Core.Logs import info, debug
from enum import Enum


class AgentType(Enum):
    """Tipos de agents disponíveis"""

    ORCHESTRATOR = "orchestrator"
    CODER = "coder"
    DOCUMENTER = "documenter"
    REVIEWER = "rereader"
    GENERAL = "general"


@dataclass
class AgentConfig:
    """Representação tipada de um agent do JSON"""

    id: str
    name: str
    agent_type: str
    description: str
    parent_id: Optional[str]
    system_prompt: str
    context_folder: str
    status: str
    created_at: str
    updated_at: str
    seniority_level: str = "mid"
    allowed_tools: List[str] = field(
        default_factory=lambda: ["tools", "print", "agent"]
    )
    tools: Dict[str, List[str]] = field(
        default_factory=lambda: {"default_tools": [], "task_tools": []}
    )
    sub_agents: List["AgentConfig"] = field(default_factory=list)
    max_context_tokens: int = (
        128000  # Limite de tokens do modelo (padrão para modelos médios)
    )

    def is_active(self) -> bool:
        """Verifica se o agent está ativo"""
        return self.status == "active"

    def is_orchestrator(self) -> bool:
        """Verifica se é um orchestrator"""
        return self.agent_type == AgentType.ORCHESTRATOR.value

    def get_direct_sub_agents(self) -> List["AgentConfig"]:
        """Retorna apenas os direct sub-agents (primeiro nível)"""
        return [a for a in self.sub_agents if a.is_active()]


@dataclass
class AgentMessage:
    """Mensagem entre agents (compatível com estrutura do chat.json)"""

    role: str  # 'user', 'assistant', 'tool'
    content: str
    timestamp: str
    agent_id: Optional[str] = None
    agent_name: Optional[str] = None  # Nome do agent que enviou/recebeu
    tool_calls: Optional[List[Dict]] = None
    tool_call_id: Optional[str] = None
    name: Optional[str] = None


class AgentManager:
    """Gerenciador universal de agents com hierarquia e isolamento"""

    def __init__(
        self, agents_json_path: str = "Agentx/AGENTS.json", debug_mode: bool = False
    ):
        """
        Inicializa o gerenciador de agents.

        Args:
            agents_json_path: Caminho para o arquivo AGENTS.json
            debug_mode: Se True, ativa logs detalhados
        """
        self.agents_json_path = Path(agents_json_path)
        self.debug_mode = debug_mode
        self.agents_map: Dict[str, AgentConfig] = {}
        self._load_agents()

    def _load_agents(self):
        """Carrega AGENTS.json e mapeia todos os agents"""
        if not self.agents_json_path.exists():
            raise FileNotFoundError(
                f"Arquivo AGENTS.json não encontrado: {self.agents_json_path}"
            )

        try:
            with open(self.agents_json_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except json.JSONDecodeError as e:
            raise ValueError(f"Erro ao decodificar AGENTS.json: {e}")

        # Mapeia todos os agents recursivamente
        for agent_data in data.get("agents", []):
            self._map_agent(agent_data)

        if self.debug_mode:
            info(f"Carregados {len(self.agents_map)} agents")

    def _map_agent(self, agent_data: Dict, parent: Optional[AgentConfig] = None):
        """
        Mapeia agent e seus sub-agents recursivamente

        Args:
            agent_data: Dados do agent do JSON
            parent: Agent pai (para construir hierarquia)
        """
        config = self._parse_agent(agent_data)
        self.agents_map[config.id] = config

        # Processa sub-agents recursivamente PRIMEIRO para popular agents_map
        for sub_agent_data in agent_data.get("sub_agents", []):
            self._map_agent(sub_agent_data, config)
            # Depois, adiciona a referência completa (já com sub_agents preenchidos) à config
            sub_config = self.agents_map[sub_agent_data["id"]]
            config.sub_agents.append(sub_config)

    def _parse_agent(self, agent_data: Dict) -> AgentConfig:
        """Parseia dados do JSON em AgentConfig"""
        # Extrai tools do JSON ou usa padrão vazio
        tools_config = agent_data.get("tools", {})
        if not isinstance(tools_config, dict):
            tools_config = {}

        # Garante que default_tools e task_tools existem
        if "default_tools" not in tools_config:
            tools_config["default_tools"] = []
        if "task_tools" not in tools_config:
            tools_config["task_tools"] = []

        return AgentConfig(
            id=agent_data["id"],
            name=agent_data["name"],
            agent_type=agent_data["agent_type"],
            description=agent_data.get("description", ""),
            parent_id=agent_data.get("parent_id"),
            system_prompt=agent_data.get("system_prompt", ""),
            context_folder=agent_data.get("context_folder", ""),
            status=agent_data.get("status", "active"),
            created_at=agent_data.get("created_at", ""),
            updated_at=agent_data.get("updated_at", ""),
            seniority_level=agent_data.get("seniority_level", "mid"),
            allowed_tools=agent_data.get("allowed_tools", ["tools", "print", "agent"]),
            tools=tools_config,
            sub_agents=[],
        )

    # ========================================================================
    # ACESSO RESTRITO POR HIERARQUIA
    # ========================================================================

    def get_agent(self, agent_id: str) -> Optional[AgentConfig]:
        """Retorna configuração do agent pelo ID"""
        return self.agents_map.get(agent_id)

    def get_agent_by_name(self, name: str) -> Optional[AgentConfig]:
        """Retorna configuração do agent pelo nome"""
        for agent in self.agents_map.values():
            if agent.name == name:
                return agent
        return None

    def list_all_agents(self) -> List[Dict[str, Any]]:
        """
        Retorna lista de todos os agents disponíveis em formato dicionário hierárquico.
        Preserva a estrutura de sub_agents para que flatten_agents possa processar corretamente.

        Returns:
            Lista de dicionários com hierarquia de sub_agents
        """

        def agent_config_to_dict(agent_config: AgentConfig) -> Dict[str, Any]:
            """Converte AgentConfig para dicionário preservando hierarquia"""
            return {
                "id": agent_config.id,
                "name": agent_config.name,
                "description": agent_config.description,
                "agent_type": agent_config.agent_type,
                "status": agent_config.status,
                "parent_id": agent_config.parent_id,
                "sub_agents": [
                    agent_config_to_dict(sub) for sub in agent_config.sub_agents
                ],
            }

        # Retorna apenas root agents (parent_id=None) para que a hierarquia seja preservada
        root_agents = [a for a in self.agents_map.values() if a.parent_id is None]
        return [agent_config_to_dict(agent) for agent in root_agents]

    def get_accessible_agents(self, caller_agent_id: str) -> List[AgentConfig]:
        """
        Retorna APENAS os direct sub-agents acessíveis ao caller.

        Regra:
        - Agent orquestrador pode acessar seus direct sub-agents
        - Agent comum NÃO pode chamar ninguém
        - Manager (None) pode acessar todos os root orchestrators

        Args:
            caller_agent_id: ID do agent que está pedindo acesso

        Returns:
            Lista de agents que o caller pode acessar (apenas direct sub-agents)
        """
        # Manager (principal) pode acessar todos os root orchestrators
        if caller_agent_id is None or caller_agent_id == "manager":
            return [
                a
                for a in self.agents_map.values()
                if a.parent_id is None and a.is_active()
            ]

        # Busca o agent que está fazendo a requisição
        caller = self.get_agent(caller_agent_id)
        if not caller:
            return []

        # Apenas orchestrators podem ter acesso a sub-agents
        if not caller.is_orchestrator():
            return []

        # Retorna apenas os direct sub-agents (primeiro nível)
        return caller.get_direct_sub_agents()

    def can_call_agent(self, caller_agent_id: str, target_agent_id: str) -> bool:
        """
        Verifica se caller pode chamar target_agent.

        Args:
            caller_agent_id: ID do agent que quer chamar
            target_agent_id: ID do agent que será chamado

        Returns:
            True se permitido, False caso contrário
        """
        # "user" (API/human) pode chamar qualquer agent
        if caller_agent_id == "user":
            return True

        accessible = self.get_accessible_agents(caller_agent_id)
        return any(a.id == target_agent_id for a in accessible)

    # ========================================================================
    # REGISTRO DE EXECUÇÃO NO CHAT CENTRALIZADO
    # ========================================================================

    def register_agent_execution(
        self,
        messages: List[Dict],
        agent_id: str,
        agent_name: str,
        task_description: str,
        result: str,
        caller_agent_id: Optional[str] = None,
    ) -> List[Dict]:
        """
        Registra execução de um agent no histórico de mensagens centralizado.

        SIMPLIFICADO: Apenas retorna o histórico sem modificá-lo.
        O histórico é gerenciado automaticamente pelo message_processor.py
        quando as ferramentas são executadas (agent).

        Args:
            messages: Lista de mensagens atual do chat
            agent_id: ID do agent que executou
            agent_name: Nome do agent que executou
            task_description: Descrição da tarefa (prompt do user)
            result: Resultado retornado pelo agent
            caller_agent_id: ID do agent que chamou (None = Manager)

        Returns:
            Lista de mensagens (sem modificações)
        """
        # Histórico é mantido como está - message_processor.py gerencia as adições
        return messages

    # ========================================================================
    # EXECUÇÃO DE TAREFA
    # ========================================================================

    def execute_agent_task(
        self,
        agent_id: str,
        task: str,
        conversation_history: List[Dict],
        caller_agent_id: Optional[str] = None,
        llm_client=None,
    ) -> Dict[str, Any]:
        """
        Executa tarefa em um agent com histórico centralizado.

        A conversa fica registrada no chat.json original, com metadata de agent.

        Args:
            agent_id: ID do agent que vai executar
            task: Tarefa/prompt a executar
            conversation_history: Histórico de mensagens do chat (lista mutável)
            caller_agent_id: ID do agent que está chamando (None = manager)
            llm_client: Cliente LLM para executar (OpenAI/Ollama)

        Returns:
            {
                'success': bool,
                'agent_id': str,
                'agent_name': str,
                'agent_type': str,
                'result': str,
                'updated_history': List[Dict],  # Histórico atualizado
                'timestamp': str,
                'error': str (apenas se success=False)
            }
        """
        try:
            # Valida se agent existe
            agent_config = self.get_agent(agent_id)
            if not agent_config:
                return {
                    "success": False,
                    "error": f"Agent {agent_id} não encontrado",
                    "timestamp": datetime.now().isoformat(),
                }

            # Valida se agent está ativo
            if not agent_config.is_active():
                return {
                    "success": False,
                    "error": f"Agent {agent_id} está inativo",
                    "timestamp": datetime.now().isoformat(),
                }

            # Valida acesso
            if not self.can_call_agent(caller_agent_id, agent_id):
                return {
                    "success": False,
                    "error": f"Agent {caller_agent_id} não tem permissão para chamar {agent_id}",
                    "timestamp": datetime.now().isoformat(),
                }

            # Cria cópia do histórico para não modificar o original enquanto processa
            agent_history = [
                msg.copy() if isinstance(msg, dict) else msg
                for msg in conversation_history
            ]

            # DEBUG: Log do histórico para diagnóstico
            info(
                f"[execute_agent_task] Histórico recebido para {agent_config.name}: {len(agent_history)} mensagens"
            )
            for i, msg in enumerate(agent_history):
                info(
                    f"  [{i}] role={msg.get('role')}, has_tool_calls={bool(msg.get('tool_calls'))}, has_tool_call_id={bool(msg.get('tool_call_id'))}"
                )

            # [CONTEXT INJECTION] Injeta tools disponíveis na primeira mensagem se histórico vazio
            user_message_with_context = task
            if not agent_history:  # Se não há histórico, injeta contexto
                # Constrói lista simplificada de tools disponíveis
                tools_list = "## Tools Disponíveis:\n"
                if agent_config.allowed_tools:
                    for tool in agent_config.allowed_tools:
                        tools_list += f"- {tool}\n"
                else:
                    tools_list += "- Nenhuma ferramenta específica configurada\n"

                user_message_with_context = f"{tools_list}\n---\n\n{task}"
                info(
                    f"[execute_agent_task] Injetando contexto de tools para {agent_config.name}"
                )

            # Executa com LLM (sem modificar histórico global)
            if llm_client:
                response = llm_client.get_ai_response(
                    user_message=user_message_with_context,
                    conversation_history=agent_history,
                    agent_id=agent_config.id,
                )

                # Trata resposta (pode ser text, tool_calls, ou error)
                if isinstance(response, dict):
                    response_type = response.get("type", "unknown")
                    if response_type == "text":
                        result_text = response.get("content", "Sem resposta")
                    elif response_type == "tool_calls":
                        # Tool calls não são processadas iterativamente - apenas reportadas
                        # Agents devem usar chamadas de tools apenas para comunicação
                        tool_calls = response.get("tool_calls", [])
                        tool_names = [
                            tc.get("function", {}).get("name", "unknown")
                            for tc in tool_calls
                        ]
                        result_text = f"[Agent tentou chamar: {', '.join(tool_names)}]"
                        debug(
                            f"[execute_agent_task] {agent_config.name} tentou chamar: {tool_names}"
                        )
                    elif response_type == "error":
                        # Erro da LLM - retornar como falha para não sobrescrever histórico
                        error_msg = (
                            f"ERRO: {response.get('content', 'Erro desconhecido')}"
                        )
                        return {
                            "success": False,
                            "error": error_msg,
                            "agent_id": agent_config.id,
                            "agent_name": agent_config.name,
                            "timestamp": datetime.now().isoformat(),
                        }
                    else:
                        result_text = response.get("content", str(response))
                else:
                    result_text = str(response)
            else:
                # Mock para testes
                result_text = f"[MOCK] {agent_config.name} responderia: {task}"

            # Registra no histórico centralizado
            updated_history = self.register_agent_execution(
                messages=conversation_history,
                agent_id=agent_config.id,
                agent_name=agent_config.name,
                task_description=task,
                result=result_text,
                caller_agent_id=caller_agent_id,
            )

            return {
                "success": True,
                "agent_id": agent_config.id,
                "agent_name": agent_config.name,
                "agent_type": agent_config.agent_type,
                "result": result_text,
                "updated_history": updated_history,
                "timestamp": datetime.now().isoformat(),
            }

        except Exception as e:
            if self.debug_mode:
                print(f"[ERROR] execute_agent_task: {str(e)}", file=sys.stderr)
            return {
                "success": False,
                "error": str(e),
                "timestamp": datetime.now().isoformat(),
            }

    # ========================================================================
    # DEFINIÇÕES PARA A IA (similar a get_tool_definitions)
    # ========================================================================

    def get_agent_definitions(
        self, caller_agent_id: Optional[str] = None
    ) -> List[Dict]:
        """
        Retorna definições dos agents acessíveis em formato para OpenAI Function Calling.
        Similar ao get_tool_definitions() do tool_facilitor.py

        Args:
            caller_agent_id: ID do agent que está pedindo as definições

        Returns:
            Lista de funções em formato OpenAI compatível
        """
        accessible_agents = self.get_accessible_agents(caller_agent_id)

        functions = []

        for agent in accessible_agents:
            functions.append(
                {
                    "type": "function",
                    "function": {
                        "name": f"call_agent_{agent.name.lower().replace('-', '_').replace(' ', '_')}",
                        "description": f"Chama o agent '{agent.name}' ({agent.agent_type}) para executar uma tarefa. {agent.description}",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "task": {
                                    "type": "string",
                                    "description": f"Tarefa a ser executada pelo {agent.name}",
                                }
                            },
                            "required": ["task"],
                        },
                    },
                }
            )

        return functions

    # ========================================================================
    # DEBUG E VISUALIZAÇÃO
    # ========================================================================

    def print_hierarchy(self, agent_id: Optional[str] = None, indent: int = 0):
        """
        Imprime hierarquia de agents em formato árvore.

        Args:
            agent_id: ID do agent para começar (None = mostra tudo)
            indent: Nível de indentação
        """
        if agent_id is None:
            # Mostra todos os root agents
            root_agents = [
                a
                for a in self.agents_map.values()
                if a.parent_id is None and a.is_active()
            ]
            for agent in root_agents:
                self._print_agent_tree(agent, indent)
        else:
            agent = self.get_agent(agent_id)
            if agent:
                self._print_agent_tree(agent, indent)

    def _print_agent_tree(self, agent: AgentConfig, indent: int = 0):
        """Imprime agent e seus sub-agents recursivamente"""
        prefix = "  " * indent
        status_emoji = "[OK]" if agent.is_active() else "[ERROR]"
        agent_type_icon = "[TARGET]" if agent.is_orchestrator() else "[GEAR]"

        print(
            f"{prefix}{status_emoji} {agent_type_icon} "
            f"{agent.name} ({agent.agent_type})"
        )

        for sub_agent in agent.sub_agents:
            self._print_agent_tree(sub_agent, indent + 1)

    def get_agent_interactions(self, messages: List[Dict]) -> Dict[str, Any]:
        """
        Extrai interações de agents do histórico centralizado.

        Analisa o histórico de mensagens e identifica:
        - Quais agents foram chamados
        - Quem chamou (caller)
        - Quantas vezes cada agent foi usado

        Args:
            messages: Lista de mensagens do chat.json

        Returns:
            {
                'total_agents_called': int,
                'agents': {
                    'agent_id': {
                        'name': str,
                        'calls': int,
                        'callers': [caller_names]
                    }
                }
            }
        """
        agent_stats = {}

        for msg in messages:
            if isinstance(msg, dict) and msg.get("_agent_execution"):
                exec_data = msg["_agent_execution"]
                agent_id = exec_data.get("agent_id")
                agent_name = exec_data.get("agent_name")
                caller_name = exec_data.get("caller_name", "Unknown")

                if agent_id not in agent_stats:
                    agent_stats[agent_id] = {
                        "name": agent_name,
                        "calls": 0,
                        "callers": [],
                    }

                agent_stats[agent_id]["calls"] += 1
                if caller_name not in agent_stats[agent_id]["callers"]:
                    agent_stats[agent_id]["callers"].append(caller_name)

        return {"total_agents_called": len(agent_stats), "agents": agent_stats}
