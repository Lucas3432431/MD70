#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core.py - Classe principal ToolFacilitator

Facilitador de ferramentas para a IA.
Fornece uma interface simplificada para que a IA execute comandos,
visualize arquivos, busque código, edite arquivos, execute scripts, etc.
"""

import sys
import json
import locale
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Union, Any

BASE_DIR = Path(__file__).parent.parent.parent.parent.parent


from App.Features.Tools.ToolsFilter import ToolsFilter
from App.Core.Logs.Logs import debug as log_debug, info, warning, error
from App.Core.Settings.Settings import load_config
from .ToolDefinitions import get_internal_tool_definitions
from .AgentMethods import get_accessible_agent_ids


class ToolFacilitator:
    """
    Facilitador que abstrai as ferramentas disponíveis para a IA.
    Centraliza a definição, execução e documentação de todas as ferramentas.
    """

    def __init__(
        self,
        tools_dir: Optional[Path] = None,
        debug_mode: bool = False,
        agent_manager: Optional[Any] = None,
        plan_manager: Optional[Any] = None,
    ):
        """
        Inicializa o facilitador de ferramentas.

        Args:
            tools_dir: Diretório onde estão os scripts de ferramentas.
                      Se None, usa o diretório padrão ../Tools
            debug_mode: Se True, ativa logs de depuração detalhados.
            agent_manager: Instância do AgentManager para filtrar tools por agent.
                          Se None, retorna todas as tools sem filtro.
            plan_manager: (Deprecated) Not used in MD70
        """
        if tools_dir is None:
            # Caminho relativo: Core.py está em Backend/App/Features/Tools/ToolFacilitator/
            # Tools está em Backend/Data/Tools/
            tools_dir = (
                Path(__file__).parent.parent.parent.parent.parent / "Data" / "Tools"
            )

        self.tools_dir = Path(tools_dir)
        self.debug_mode = debug_mode
        self.agent_manager = agent_manager
        self.tools_filter = ToolsFilter()

        # AgentSessionManager será inicializado via set_agent_session_manager()
        # quando todos os componentes (llm_client, chat_manager) estiverem disponíveis
        self.agent_session_manager = None

        if not self.tools_dir.exists():
            raise FileNotFoundError(
                f"Diretorio de ferramentas nao encontrado: {self.tools_dir}"
            )

        self.env_finder_path = self.tools_dir / "EnvFinder.py"
        if not self.env_finder_path.exists():
            raise FileNotFoundError(
                f"Script EnvFinder.py não encontrado em: {self.env_finder_path}"
            )

    def _load_tools_config(self):
        """Carrega a configuração das ferramentas do _TOOLS.json."""
        try:
            tools_file = self.tools_dir / "_TOOLS.json"
            if not tools_file.exists():
                return {}
            with open(tools_file, "r", encoding="utf-8") as f:
                tools_data = json.load(f)
            return {tool.get("name"): tool for tool in tools_data.get("tools", [])}
        except Exception as e:
            error(f"ERRO ao carregar configuração de tools: {str(e)}")
            return {}

    def get_tool_definitions(self):
        """Retorna definições das ferramentas no formato OpenAI."""
        try:
            tools_file = self.tools_dir / "_TOOLS.json"
            if not tools_file.exists():
                return get_internal_tool_definitions()

            with open(tools_file, "r", encoding="utf-8") as f:
                tools_data = json.load(f)

            openai_tools = get_internal_tool_definitions()

            # Adiciona ferramentas externas
            for tool in tools_data.get("tools", []):
                openai_tool = {
                    "type": "function",
                    "function": {
                        "name": tool.get("name"),
                        "description": tool.get("description", ""),
                        "parameters": {
                            "type": "object",
                            "properties": {},
                            "required": [],
                        },
                    },
                }

                if tool.get("parameters"):
                    for param_name, param_desc in tool["parameters"].items():
                        clean_name = (
                            param_name.replace(" (opcional)", "")
                            .replace("(opcional)", "")
                            .strip()
                        )
                        openai_tool["function"]["parameters"]["properties"][
                            clean_name
                        ] = {"type": "string", "description": param_desc}
                        if "(opcional)" not in param_name:
                            openai_tool["function"]["parameters"]["required"].append(
                                clean_name
                            )

                openai_tools.append(openai_tool)

            return openai_tools

        except Exception as e:
            error(f"ERRO ao ler _TOOLS.json: {str(e)}")
            return get_internal_tool_definitions()

    def get_tool_definitions_for_agent(
        self, agent_id: Optional[str] = None
    ) -> List[Dict]:
        """Retorna definições de ferramentas filtradas para um agent específico."""
        if not self.agent_manager or agent_id is None:
            return self.get_tool_definitions()

        try:
            agent_config = self.agent_manager.get_agent(agent_id)
            if not agent_config:
                return self.get_tool_definitions()

            allowed_tool_names = set()
            if hasattr(agent_config, "tools") and agent_config.tools:
                if isinstance(agent_config.tools, dict):
                    allowed_tool_names.update(
                        agent_config.tools.get("default_tools", [])
                    )
                    allowed_tool_names.update(agent_config.tools.get("task_tools", []))

            if not allowed_tool_names and hasattr(agent_config, "allowed_tools"):
                allowed_tool_names = set(agent_config.allowed_tools or [])

            mandatory_tools = {"tools", "print", "agent", "list-agents", "dry-runner"}
            allowed_tool_names.update(mandatory_tools)

            all_tools = self.get_tool_definitions()
            return [
                tool
                for tool in all_tools
                if tool["function"]["name"] in allowed_tool_names
            ]

        except Exception as e:
            if self.debug_mode:
                error(f"[TOOL_FILTER] ERRO: {str(e)}")
            return self.get_tool_definitions()

    def check_tool_authorization(
        self, tool_name: str, agent_id: Optional[str] = None
    ) -> tuple[bool, Optional[str]]:
        """
        Verifica se uma tool pode ser usada por um agent.

        Args:
            tool_name: Nome da ferramenta
            agent_id: ID do agent

        Returns:
            Tupla (is_authorized, error_message)
            - is_authorized: True se a tool pode ser usada
            - error_message: Mensagem de erro se não autorizada, None se autorizada
        """
        if not agent_id or not self.agent_manager:
            return True, None

        try:
            agent_config = self.agent_manager.get_agent(agent_id)
            if not agent_config:
                return True, None

            can_use, error_msg = self.tools_filter.can_use_tool(
                agent_id, tool_name.lower(), agent_config
            )
            return can_use, error_msg if not can_use else None
        except Exception as e:
            return True, None

    def execute_tool(
        self, tool_name: str, arguments: str, agent_id: Optional[str] = None
    ) -> str:
        """Executa uma chamada de ferramenta."""
        try:
            try:
                args_dict = json.loads(arguments) if arguments else {}
            except json.JSONDecodeError:
                args_dict = {"_raw": arguments}

            debug = args_dict.get("--debug", False) or args_dict.get("debug", False)
            args_dict_clean = {
                k: v for k, v in args_dict.items() if k not in ("--debug", "debug")
            }
            tool_name = tool_name.lower()

            if debug:
                log_debug(
                    f"\nTool: {tool_name}\n[DEBUG] Raw JSON: {arguments}\n[DEBUG] Parsed Args: {args_dict_clean}"
                )

            # Verifica se a tool pode ser usada (valida com ToolsFilter)
            if agent_id and self.agent_manager:
                agent_config = self.agent_manager.get_agent(agent_id)
                if agent_config:
                    can_use, error_msg = self.tools_filter.can_use_tool(
                        agent_id, tool_name, agent_config
                    )
                    if not can_use:
                        return self.format_response_for_llm(
                            {"success": False, "error": error_msg}
                        )

            # Ferramentas internas
            if tool_name == "print":
                end_answer = args_dict_clean.get("end-answer", "false").lower() in (
                    "true",
                    "1",
                    "yes",
                )
                return self.format_response_for_llm(
                    self.print_message(
                        args_dict_clean.get("message", ""), end_answer=end_answer
                    )
                )

            elif tool_name == "tools":
                return self.format_response_for_llm(
                    self.tools(args_dict_clean.get("tool_name"), agent_id=agent_id)
                )

            elif tool_name == "list-agents":
                return self.format_response_for_llm(
                    self.list_agents(caller_agent_id=agent_id)
                )

            elif tool_name == "agent":
                # [GUARD] Bloqueia agent calls apenas para agentes que não são raiz
                # Agentes raiz (sem parent) podem chamar children
                # Agentes child (chamados via broadcast) não devem chamar outros agents
                if agent_id and agent_id != "user":
                    # Verifica se o agent é raiz (não tem parent)
                    caller_agent = self.agent_manager.get_agent(agent_id)
                    if caller_agent and caller_agent.parent_id:
                        # Agent tem parent - é um child chamado via broadcast, não pode chamar outros
                        return self.format_response_for_llm(
                            {
                                "success": False,
                                "error": f"⚠️ Agent '{agent_id}' não pode chamar outros agents durante execução isolada. Apenas responda à pergunta.",
                            }
                        )

                target_agent_id = args_dict_clean.get("agent_id")
                message = args_dict_clean.get("message")

                # [VALIDAÇÃO] Verifica erros ANTES do timeout
                if not target_agent_id or not message:
                    return self.format_response_for_llm(
                        {"success": False, "error": "agent_id e message obrigatórios"}
                    )

                # [FIX] Timeout de 10 segundos APÓS validação básica para garantir isolamento
                import time
                from App.Core.Logs import info

                info(
                    f"⏳ [TIMEOUT] Aguardando 10 segundos antes de processar agent: {target_agent_id}"
                )
                time.sleep(10)
                info(
                    f"✓ [TIMEOUT] 10 segundos completados, processando {target_agent_id}"
                )

                # [NOVO] PRIMEIRA COISA: Detecta "all" para enviar a todos os filhos diretos
                # Faz isso ANTES de qualquer outra lógica de agent
                if str(target_agent_id).strip().lower() == "all":
                    log_debug(f"[agent tool] ✓✓✓ DETECTADO 'all' BROADCAST ✓✓✓")
                    log_debug(f"[agent tool]  Chamador (agent_id): '{agent_id}'")
                    log_debug(f"[agent tool]  Processando TODOS os filhos diretos...")

                    if not self.agent_manager:
                        log_debug(f"[agent tool] ✗ Agent manager não configurado!")
                        return self.format_response_for_llm(
                            {"success": False, "error": "Agent manager não configurado"}
                        )

                    # Obtém agent chamador
                    caller_agent = self.agent_manager.get_agent(agent_id)
                    if not caller_agent:
                        log_debug(
                            f"[agent tool] ✗ Agent chamador '{agent_id}' não encontrado"
                        )
                        return self.format_response_for_llm(
                            {
                                "success": False,
                                "error": f"Agent chamador '{agent_id}' não encontrado",
                            }
                        )

                    # Obtém children diretos - pode ser 'children' ou 'sub_agents'
                    child_ids_raw = getattr(caller_agent, "children", None) or getattr(
                        caller_agent, "sub_agents", []
                    )
                    # Se for dict em vez de objeto, tenta acessar como dict
                    if isinstance(caller_agent, dict):
                        child_ids_raw = caller_agent.get(
                            "children", caller_agent.get("sub_agents", [])
                        )

                    # [FIX] Extrai apenas os IDs (string) dos AgentConfig objects ou dicts
                    child_ids = []
                    for child in child_ids_raw:
                        if isinstance(child, str):
                            child_ids.append(child)
                        elif hasattr(child, "id"):
                            # AgentConfig object
                            child_ids.append(child.id)
                        elif isinstance(child, dict):
                            child_ids.append(child.get("id", child))
                        else:
                            child_ids.append(str(child))

                    if not child_ids:
                        return self.format_response_for_llm(
                            {
                                "success": False,
                                "error": f"Agent '{agent_id}' não tem sub-agents filhos",
                            }
                        )

                    log_debug(
                        f"[agent tool] Enviando para todos os {len(child_ids)} sub-agents filhos: {child_ids}"
                    )

                    # Envia para cada filho em fila sequencial e coleta respostas
                    results = []
                    if hasattr(self, "bot") and self.bot:
                        # Remove tool_calls incompletos do histórico
                        if hasattr(self.bot.chat_manager, "conversation_history"):
                            removed_count = 0
                            while (
                                self.bot.chat_manager.conversation_history
                                and self.bot.chat_manager.conversation_history[-1].get(
                                    "role"
                                )
                                == "assistant"
                                and self.bot.chat_manager.conversation_history[-1].get(
                                    "tool_calls"
                                )
                            ):
                                self.bot.chat_manager.conversation_history.pop()
                                removed_count += 1

                        history = getattr(
                            self.bot.chat_manager, "conversation_history", []
                        )

                        # [NOVO] Processa cada child em fila sequencial
                        import time
                        import copy

                        for idx, child_id in enumerate(child_ids):
                            # [FIX] Timeout de 10 segundos entre broadcasts para evitar race conditions
                            if idx > 0:
                                log_debug(
                                    f"[all] Aguardando 10s antes de processar próximo agent..."
                                )
                                time.sleep(10)

                            # [FIX] Cria cópia limpa do histórico para cada child
                            # Remove qualquer tool_calls incompletos do broadcast anterior
                            clean_history = copy.deepcopy(history)
                            while (
                                clean_history
                                and clean_history[-1].get("role") == "assistant"
                                and clean_history[-1].get("tool_calls")
                            ):
                                log_debug(
                                    f"[all] Removendo assistant com tool_calls incompletos antes de chamar {child_id}"
                                )
                                clean_history.pop()

                            child_agent = self.agent_manager.get_agent(child_id)
                            # Suporta tanto dict quanto objeto
                            if isinstance(child_agent, dict):
                                child_name = child_agent.get("name", child_id)
                            else:
                                child_name = (
                                    getattr(child_agent, "name", child_id)
                                    if child_agent
                                    else child_id
                                )

                            # [NOVO] Adiciona aviso de broadcast na mensagem
                            broadcast_warning = (
                                "\n\n---\n"
                                "**[AVISO IMPORTANTE]** Você está sendo consultado como parte de um broadcast conjunto. "
                                "Responda APENAS com sua opinião pessoal sobre o tema. "
                                "**NÃO contate ou consulte outros agents nesta resposta.** "
                                "Seja conciso. Você será compilado junto com os demais conselheiros."
                            )
                            # Adiciona nome do agent na mensagem
                            child_message = (
                                f"{child_name}, {message}{broadcast_warning}"
                                if not message.startswith(child_name)
                                else f"{message}{broadcast_warning}"
                            )

                            log_debug(
                                f"[all] Processando {child_name} ({child_id}) em fila..."
                            )

                            # [NOVO] Chama broadcast_to_agent que criará arquivo e contexto
                            result = self.bot.broadcast_to_agent(
                                target_agent_id=child_id,
                                message=child_message,
                                from_agent_id=agent_id,
                                full_conversation_history=clean_history,
                                max_iterations=10,
                            )

                            response_text = result.get("result", "")
                            log_debug(
                                f"[all] {child_name} respondeu: {len(response_text)} chars"
                            )

                            results.append(
                                {
                                    "agent_id": child_id,
                                    "agent_name": child_name,
                                    "response": response_text,
                                    "success": result.get("success", False),
                                }
                            )

                        # [NOVO] Compila respostas em formato narrativo para sincronizar ao histórico
                        if not results:
                            log_debug(f"⚠️  [all] AVISO: Nenhum resultado de agents!")
                            compiled_response = (
                                "❌ ERRO: Nenhum agent respondeu ao broadcast 'all'"
                            )
                        else:
                            compiled_response = "## Respostas dos Conselheiros:\n\n"
                            for idx, result in enumerate(results, 1):
                                compiled_response += f"### {idx}. {result['agent_name']} ({result['agent_id']})\n"
                                compiled_response += f"{result['result']}\n\n"

                        log_debug(
                            f"[all] Compilado: {len(compiled_response)} chars de {len(results)} agents"
                        )

                        if not compiled_response or len(compiled_response) < 50:
                            log_debug(
                                f"⚠️  [all] AVISO: Resposta compilada está vazia ou muito curta!"
                            )
                            log_debug(
                                f"   Results count: {len(results) if results else 0}"
                            )
                            if results:
                                log_debug(
                                    f"   Agents: {[r['agent_name'] for r in results]}"
                                )
                                log_debug(
                                    f"   Response sizes: {[len(r['result']) for r in results]}"
                                )

                        # [CRÍTICO] Retorna APENAS a string compilada, não o dict
                        # Assim o Processor salva corretamente como tool message no caller
                        # (não passa por broadcast_to_agent que salvaria no arquivo do agent chamado)
                        info(
                            f"✅ [BROADCAST COMPLETO] Retornando {len(compiled_response)} chars compilados para o caller"
                        )
                        return compiled_response
                    return self.format_response_for_llm(
                        {"success": False, "error": "Bot não configurado"}
                    )

                # [ORIGINAL] Chamada para agent específico
                # [PROMPT INJECTION] Adiciona nome do agent no início da message
                # Permite que o main chat mostre quem foi chamado
                if self.agent_manager:
                    target_agent = self.agent_manager.get_agent(target_agent_id)
                    if target_agent:
                        agent_name = getattr(target_agent, "name", None)
                        if agent_name and not message.startswith(agent_name + ","):
                            message = f"{agent_name}, {message}"

                # 🛡️ Bloqueia auto-chamadas recursivas
                if agent_id != "user" and target_agent_id == agent_id:
                    agent_name = (
                        getattr(
                            self.agent_manager.get_agent(agent_id), "name", agent_id
                        )
                        if self.agent_manager
                        else agent_id
                    )
                    return self.format_response_for_llm(
                        {
                            "success": False,
                            "error": f"Agent '{agent_name}' não pode chamar a si mesmo - recursão bloqueada",
                        }
                    )

                # "user" tem acesso irrestrito a todos os agents
                # Outros agents têm restrições baseadas na hierarquia
                if agent_id != "user":
                    accessible_ids = get_accessible_agent_ids(
                        agent_id, BASE_DIR, self.agent_manager, self.debug_mode
                    )
                    if target_agent_id not in accessible_ids:
                        caller_name = agent_id if agent_id else "Unknown"
                        return self.format_response_for_llm(
                            {
                                "success": False,
                                "error": f"Agent '{caller_name}' sem permissão para chamar '{target_agent_id}'",
                            }
                        )

                if hasattr(self, "bot") and self.bot:
                    # [OK] Multi-agent Communication via broadcast_to_agent()
                    # Suporta qualquer tipo de comunicação:
                    # - Perguntas: "Quais tools você tem?"
                    # - Tarefas: "Implemente X"
                    # - Discussões: "O que você achou disso?"
                    # Resposta do agent é salva com seu prefix na conversa de grupo

                    # [WARNING] Remove mensagens com tool_calls incompletos do histórico
                    # Caso contrário, broadcast_to_agent() recebe [assistant com tool_calls]
                    # sem [tool message] respondendo, causando erro 400 no LLM
                    # Remove TODOS os assistants com tool_calls do final (podem haver múltiplos em sequência)
                    if hasattr(self.bot.chat_manager, "conversation_history"):
                        # Remover DIRETAMENTE do conversation_history do chat_manager
                        removed_count = 0
                        while (
                            self.bot.chat_manager.conversation_history
                            and self.bot.chat_manager.conversation_history[-1].get(
                                "role"
                            )
                            == "assistant"
                            and self.bot.chat_manager.conversation_history[-1].get(
                                "tool_calls"
                            )
                        ):
                            log_debug(
                                f"[agent tool] Removendo assistant com tool_calls incompleto: {len(self.bot.chat_manager.conversation_history[-1].get('tool_calls', []))} calls"
                            )
                            self.bot.chat_manager.conversation_history.pop()
                            removed_count += 1
                        if removed_count > 0:
                            log_debug(
                                f"[agent tool] {removed_count} mensagens com tool_calls incompletos removidas"
                            )

                    history = getattr(self.bot.chat_manager, "conversation_history", [])

                    # [FIX] Limpa histórico de tool_calls incompletos antes de chamar agent
                    import copy

                    clean_history = copy.deepcopy(history)
                    while (
                        clean_history
                        and clean_history[-1].get("role") == "assistant"
                        and clean_history[-1].get("tool_calls")
                    ):
                        log_debug(
                            f"[agent tool] Removendo assistant com tool_calls incompletos antes de chamar {target_agent_id}"
                        )
                        clean_history.pop()

                    result = self.bot.broadcast_to_agent(
                        target_agent_id=target_agent_id,
                        message=message,
                        from_agent_id=agent_id,
                        full_conversation_history=clean_history,
                        max_iterations=10,
                    )
                    return self.format_response_for_llm(result)
                return self.format_response_for_llm(
                    {"success": False, "error": "Bot não configurado"}
                )

            elif tool_name == "dry-runner":
                return self._handle_dry_runner(args_dict_clean, debug)

            else:
                # Ferramentas externas
                tools_map = self._load_tools_config()
                if tool_name not in tools_map:
                    return self.format_response_for_llm(
                        {
                            "success": False,
                            "error": f"Ferramenta desconhecida: {tool_name}",
                            "exit_code": -1,
                        }
                    )

                args_list = self._convert_args_to_cli(args_dict_clean, debug)
                result = self._run_tool(tool_name, args_list)

        except Exception as e:
            import traceback

            return f"Erro: {str(e)}\n{traceback.format_exc()}"

        return self.format_response_for_llm(result)

    def _handle_dry_runner(self, args_dict_clean: Dict, debug: bool):
        """Handler para dry-runner."""
        script = args_dict_clean.get("script")
        script_type = args_dict_clean.get("script_type", "python")

        if not script:
            return self.format_response_for_llm(
                {"success": False, "error": "Campo 'script' obrigatório"}
            )

        try:
            simulation_output = self._simulate_script_execution(script, script_type)
            return self.format_response_for_llm(
                {
                    "success": True,
                    "script_type": script_type,
                    "simulation": "MODO DRY-RUN",
                    "predicted_output": simulation_output,
                }
            )
        except Exception as e:
            return self.format_response_for_llm(
                {"success": False, "error": f"Erro ao simular: {str(e)}"}
            )

    def _convert_args_to_cli(self, args_dict: Dict, debug: bool) -> List[str]:
        """Converte argumentos dict para CLI."""
        args_list = []
        for key, value in args_dict.items():
            if key.startswith("_"):
                if key == "_raw":
                    args_list.append(str(value))
            elif isinstance(value, list):
                for v in value:
                    # Verifica se a chave já começa com - ou --
                    flag = key if (key.startswith("-")) else f"--{key}"
                    args_list.extend([flag, str(v)])
            elif isinstance(value, bool):
                if value:
                    flag = key if (key.startswith("-")) else f"--{key}"
                    args_list.append(flag)
            elif value is not None:
                flag = key if (key.startswith("-")) else f"--{key}"
                args_list.extend([flag, str(value)])

        if debug:
            log_debug(f"CLI Args: {' '.join(args_list)}")
        return args_list

    def _run_tool(
        self, tool_name: str, args: List[str]
    ) -> Dict[str, Union[str, int, bool]]:
        """Executa uma ferramenta externa."""
        tool_name = tool_name.lower()
        tools_map = self._load_tools_config()
        tool_config = tools_map.get(tool_name)

        if not tool_config or not tool_config.get("file"):
            return {
                "success": False,
                "error": f"Ferramenta '{tool_name}' não configurada",
                "exit_code": -1,
            }

        try:
            result = subprocess.run(
                [
                    sys.executable,
                    str(self.env_finder_path),
                    "--name",
                    tool_config.get("file"),
                ],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode != 0:
                return {
                    "success": False,
                    "error": result.stderr.strip(),
                    "exit_code": result.returncode,
                }

            tool_path = result.stdout.strip()
            if not tool_path:
                return {"success": False, "error": f"Caminho vazio", "exit_code": -1}

            result = subprocess.run(
                [sys.executable, tool_path] + args,
                capture_output=True,
                text=True,
                encoding=locale.getpreferredencoding(False),
                errors="replace",
                timeout=300,
            )
            return {
                "success": result.returncode == 0,
                "output": result.stdout,
                "error": result.stderr,
                "exit_code": result.returncode,
            }

        except subprocess.TimeoutExpired:
            return {"success": False, "error": "Timeout na execução", "exit_code": -2}
        except Exception as e:
            return {"success": False, "error": str(e), "exit_code": -3}

    def print_message(
        self, message: str, end_answer: bool = False
    ) -> Dict[str, Union[str, int, bool]]:
        """
        Imprime uma mensagem.

        Args:
            message: Mensagem a imprimir
            end_answer: Se True, marca para finalizar resposta após print
        """
        log_debug(message)
        result = {"success": True, "output": message, "error": "", "exit_code": 0}
        if end_answer:
            result["__end_answer__"] = True
        return result

    def list_agents(
        self, caller_agent_id: str = None
    ) -> Dict[str, Union[str, int, bool]]:
        """Lista agents acessíveis categorizados por relacionamento hierárquico."""
        if not self.agent_manager:
            return {
                "success": False,
                "error": "AgentManager não configurado",
                "exit_code": -1,
            }

        try:
            all_agents = self.agent_manager.list_all_agents()
            if not all_agents:
                return {
                    "success": True,
                    "output": "Nenhum agent disponível.",
                    "error": "",
                    "exit_code": 0,
                }

            from .AgentMethods import flatten_agents

            log_debug(f"[list-agents] caller_agent_id={caller_agent_id}")

            accessible_ids = get_accessible_agent_ids(
                caller_agent_id, BASE_DIR, self.agent_manager, self.debug_mode
            )
            log_debug(f"[list-agents] accessible_ids={len(accessible_ids)} agents")

            if not accessible_ids:
                return {
                    "success": True,
                    "output": "Sem acesso a agents.",
                    "error": "",
                    "exit_code": 0,
                }

            # Achatar agents para acesso a parent_id
            all_agents_flat = flatten_agents(all_agents)
            log_debug(
                f"[list-agents] all_agents_flat tem {len(all_agents_flat)} agents"
            )

            # Função para buscar agent recursivamente
            def find_agent_recursive(agents_list, agent_id):
                if not agent_id:
                    return None
                for agent in agents_list:
                    if agent.get("id") == agent_id:
                        return agent
                    if "sub_agents" in agent and agent["sub_agents"]:
                        result = find_agent_recursive(agent["sub_agents"], agent_id)
                        if result:
                            return result
                return None

            # Buscar caller na lista achatada (tem parent_id preenchido)
            caller = next(
                (a for a in all_agents_flat if a.get("id") == caller_agent_id), None
            )
            if not caller:
                log_debug(f"[list-agents] Caller não encontrado: {caller_agent_id}")
                # Fallback: retorna todos os agents acessíveis
                output = f"Agents Acessíveis:\n{'=' * 80}\n\n"
                accessible_agents = [
                    a for a in all_agents_flat if a.get("id") in accessible_ids
                ]
                for agent in accessible_agents:
                    output += (
                        f"• {agent.get('name', 'Unknown')} (ID: {agent.get('id')})\n"
                    )
                    output += f"  Tipo: {agent.get('agent_type', 'unknown')}\n"
                    output += f"  Parent: {agent.get('parent_id', 'root')}\n\n"
                return {"success": True, "output": output, "error": "", "exit_code": 0}

            log_debug(
                f"[list-agents] Caller encontrado: {caller.get('name')}, parent_id={caller.get('parent_id')}"
            )

            # Inicializar categorias
            parent_agent = None
            brother_agents = []

            # Children: procura na lista achatada por agents com parent_id = caller_agent_id
            children_agents = [
                a for a in all_agents_flat if a.get("parent_id") == caller_agent_id
            ]
            log_debug(f"[list-agents] Encontrados {len(children_agents)} children")

            # Encontrar parent
            if caller.get("parent_id"):
                parent_agent = next(
                    (a for a in all_agents_flat if a.get("id") == caller["parent_id"]),
                    None,
                )
                log_debug(
                    f"[list-agents] Parent encontrado: {parent_agent.get('name') if parent_agent else 'none'}"
                )

            # Encontrar brothers (agents com mesmo parent_id, excluindo o caller)
            if caller.get("parent_id"):
                brother_agents = [
                    a
                    for a in all_agents_flat
                    if a.get("parent_id") == caller["parent_id"]
                    and a.get("id") != caller_agent_id
                ]
                log_debug(f"[list-agents] Encontrados {len(brother_agents)} brothers")

            log_debug(
                f"[list-agents] parent={parent_agent.get('name') if parent_agent else 'none'}, brothers={len(brother_agents)}, children={len(children_agents)}"
            )

            # Formatar output
            caller_name = caller.get("name", caller_agent_id or "Unknown")
            output = f"AGENTS PARA: {caller_name}\n"
            output += "=" * 80 + "\n\n"

            # Parent - SOMENTE SE ACESSÍVEL
            if parent_agent and parent_agent.get("id") in accessible_ids:
                output += "👆 PARENT (Supervisor):\n"
                output += "-" * 80 + "\n"
                output += f"  Nome: {parent_agent.get('name', 'Unknown')}\n"
                output += f"  ID: {parent_agent.get('id', 'Unknown')}\n"
                output += f"  Tipo: {parent_agent.get('agent_type', 'unknown')}\n"
                output += f"  Descrição: {parent_agent.get('description', 'Sem descrição')}\n\n"
            else:
                output += "👆 PARENT: Nenhum (é um agent raiz)\n\n"

            # Children
            if children_agents:
                output += f"👇 CHILDREN ({len(children_agents)} sub-agent(s)):\n"
                output += "-" * 80 + "\n"
                for child in children_agents:
                    output += f"  • {child.get('name', 'Unknown')}\n"
                    output += f"    ID: {child.get('id', 'Unknown')}\n"
                    output += f"    Tipo: {child.get('agent_type', 'unknown')}\n"
                output += "\n"
            else:
                output += "👇 CHILDREN: Nenhum\n\n"

            # Brothers
            if brother_agents:
                output += f"➡️  BROTHERS ({len(brother_agents)} colega(s)):\n"
                output += "-" * 80 + "\n"
                for brother in brother_agents:
                    output += f"  • {brother.get('name', 'Unknown')}\n"
                    output += f"    ID: {brother.get('id', 'Unknown')}\n"
                    output += f"    Tipo: {brother.get('agent_type', 'unknown')}\n"
                output += "\n"
            else:
                output += "➡️  BROTHERS: Nenhum\n"

            log_debug(f"[list-agents] Saída gerada: {len(output)} caracteres")
            return {"success": True, "output": output, "error": "", "exit_code": 0}
        except Exception as e:
            log_error = f"ERRO ao listar agents: {str(e)}"
            error(log_error)
            import traceback

            error(traceback.format_exc())
            return {"success": False, "error": log_error, "exit_code": -1}

    def tools(
        self, tool_name: Optional[str] = None, agent_id: Optional[str] = None
    ) -> Dict[str, Union[str, int, bool]]:
        """Retorna informações sobre ferramentas disponíveis - FILTRADAS por agent_id."""
        try:
            tools_file = self.tools_dir / "_TOOLS.json"
            if not tools_file.exists():
                return {
                    "success": False,
                    "error": "Arquivo _TOOLS.json não encontrado",
                    "exit_code": -1,
                }

            with open(tools_file, "r", encoding="utf-8") as f:
                tools_data = json.load(f)

            # Obter ferramentas permitidas para este agent
            allowed_default_tools = []
            allowed_task_tools = []
            if agent_id and self.agent_manager:
                agent_config = self.agent_manager.get_agent(agent_id)
                if agent_config:
                    # Obtém tools do agent_config
                    if hasattr(agent_config, "tools") and agent_config.tools:
                        allowed_default_tools = agent_config.tools.get(
                            "default_tools", []
                        )
                        allowed_task_tools = agent_config.tools.get("task_tools", [])
                    else:
                        # Fallback para allowed_tools
                        allowed_default_tools = getattr(
                            agent_config, "allowed_tools", []
                        )

            if tool_name:
                tool_info = next(
                    (
                        t
                        for t in tools_data.get("tools", [])
                        if t["name"] == tool_name.lower()
                    ),
                    None,
                )
                if not tool_info:
                    # Lê lista de ferramentas internas do _TOOLS.json
                    internal_tools = tools_data.get(
                        "internal_tools",
                        ["print", "agent", "list-agents", "dry-runner"],
                    )
                    if tool_name.lower() in internal_tools:
                        return {
                            "success": True,
                            "output": self._get_internal_tool_details(
                                tool_name.lower()
                            ),
                            "error": "",
                            "exit_code": 0,
                        }
                    return {
                        "success": False,
                        "error": f"Ferramenta não encontrada",
                        "exit_code": -1,
                    }

                output = f"Ferramenta: {tool_info['name']}\n\nDescrição: {tool_info['description']}\n"
                if tool_info.get("parameters"):
                    output += "Parâmetros:\n" + "".join(
                        f"  - {p}: {d}\n" for p, d in tool_info["parameters"].items()
                    )
                return {"success": True, "output": output, "error": "", "exit_code": 0}

            # Lista geral resumida - FILTRADA por agent
            output = "Ferramentas Disponíveis:\n\n[Ferramentas Internas]\n"

            # Meta-tools internas (lidas do _TOOLS.json)
            all_internal_meta_tools = tools_data.get(
                "meta_tools", ["tools", "print", "list-agents", "agent", "plan"]
            )

            # 🔒 FILTRO: Se agent_id foi fornecido, mostra APENAS as tools que estão em allowed_tools
            internal_meta_tools = all_internal_meta_tools
            if agent_id:
                allowed_tools_set = set(allowed_default_tools + allowed_task_tools)
                internal_meta_tools = [
                    t for t in all_internal_meta_tools if t in allowed_tools_set
                ]

            for tool in internal_meta_tools:
                output += f"- {tool}\n"

            output += "\n[Ferramentas Externas]\n"
            # Filtra ferramentas externas baseado em allowed_default_tools e allowed_task_tools
            allowed_external = set(allowed_default_tools + allowed_task_tools) - set(
                all_internal_meta_tools
            )

            for tool in tools_data.get("tools", []):
                tool_name_lower = tool["name"].lower()
                # Se agent_id foi fornecido, filtra; senão, mostra todas (compatibilidade)
                if not agent_id or tool_name_lower in allowed_external:
                    output += f"- {tool['name']}: {tool['description']}\n"

            output += '\nDica: Use tools("nome_da_tool") para ver detalhes.\n'
            return {"success": True, "output": output, "error": "", "exit_code": 0}

        except Exception as e:
            return {
                "success": False,
                "error": f"ERRO ao ler _TOOLS.json: {str(e)}",
                "exit_code": -1,
            }

    def _get_internal_tool_details(self, tool_name: str) -> str:
        """Retorna detalhes completos sobre ferramentas internas com orientações."""
        details = {
            "tools": "Ferramenta Interna - Consulta documentação das ferramentas disponíveis",
            "print": """
## FERRAMENTA: print

**Descrição:** Imprime mensagens ou raciocínio durante execução.

**Parâmetros:**
- message: Mensagem a imprimir (obrigatório)
- end-answer (opcional): Se definido como "true", finaliza a resposta após print

**Exemplos:**
```
print({"message": "Processando dados..."})
```

Com finalização:
```
print({"message": "Tarefa concluída com sucesso!", "end-answer": "true"})
```

Quando `end-answer` é "true", a resposta é encerrada e nenhuma ferramenta adicional pode ser executada nesta rodada.
""",
            "agent": "Ferramenta Interna - Comunica com outro agent para delegar tarefas",
            "list-agents": "Ferramenta Interna - Lista agents acessíveis baseado na hierarquia",
            "dry-runner": "Ferramenta Interna - Executa script em modo simulação (dry-run)",
        }
        return details.get(tool_name, f"Ferramenta Interna: {tool_name}")

    def _simulate_script_execution(self, script: str, script_type: str) -> str:
        """Simula execução de script."""
        if script_type.lower() == "python":
            return "[SIMULAÇÃO] Análise Python:\n" + "\n".join(
                line for line in script.split("\n") if "print" in line
            )
        return "[SIMULAÇÃO] Comandos identificados:\n" + "\n".join(
            line.strip() for line in script.split("\n") if line.strip()
        )

    def _get_accessible_agent_ids(self, caller_agent_id: Optional[str]) -> set:
        """Wrapper para manter compatibilidade com código antigo."""
        return get_accessible_agent_ids(
            caller_agent_id, BASE_DIR, self.agent_manager, self.debug_mode
        )

    def _load_agents_from_json(self) -> list:
        """Wrapper para manter compatibilidade."""
        from .AgentMethods import load_agents_from_json

        return load_agents_from_json(BASE_DIR)

    def _flatten_agents(self, agents_list: list, parent_id: str = None) -> list:
        """Wrapper para manter compatibilidade."""
        from .AgentMethods import flatten_agents

        return flatten_agents(agents_list, parent_id)

    def format_response_for_llm(
        self, result: Union[Dict[str, Union[str, int, bool]], str]
    ) -> str:
        """
        Formata resposta para LLM.

        Se result contém __end_answer__ marcado, prepara resposta especial para finalizar.
        """
        if isinstance(result, str):
            return result

        if result.get("success", False):
            output = (
                result.get("plan_display")
                or result.get("output")
                or result.get("result")
                or "Sucesso"
            )
            # Se marcado para finalizar, adiciona marcador especial
            if result.get("__end_answer__"):
                output += "\n\n__END_ANSWER__"
            return output
        return f"ERRO (codigo {result.get('exit_code', -1)}):\n{result.get('error', 'Erro desconhecido')}"

    def set_agent_session_manager(self, llm_client, chat_manager):
        """
        Inicializa o AgentSessionManager quando todos os componentes estão disponíveis.

        Este método deve ser chamado APÓS a criação do LLMClient e ChatManager,
        pois o AgentSessionManager precisa desses componentes para funcionar.

        Args:
            llm_client: Cliente LLM (OpenAI ou Ollama)
            chat_manager: Gerenciador de chats
        """
        try:
            from App.Features.Tools.Agents.AgentSessionManager import (
                AgentSessionManager,
            )

            self.agent_session_manager = AgentSessionManager(
                llm_client=llm_client,
                chat_manager=chat_manager,
                tool_facilitator=self,
                agent_manager=self.agent_manager,
            )
            log_debug(f"AgentSessionManager inicializado")
        except Exception as e:
            error(f"Erro ao inicializar AgentSessionManager: {str(e)}")
            self.agent_session_manager = None
