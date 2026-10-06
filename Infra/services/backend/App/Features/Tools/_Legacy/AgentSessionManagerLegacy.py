"""
agent_session_manager.py

Gerencia execuções isoladas de agentes.
Quando um agent é chamado, abre uma nova "sessão" com seu próprio contexto,
evitando que múltiplas tool calls fiquem incompletas na OpenAI.

Fluxo:
1. Main agent chama tool "agent" → Retorna sucesso imediatamente
2. AgentSessionManager abre NOVA conexão para o agent chamado
3. Agent chamado executa independentemente com seu próprio MessageProcessor
4. Resultado é sincronizado de volta ao histórico principal
"""

import json
from typing import Dict, Any, Optional, List
from datetime import datetime
from pathlib import Path
from App.Core.Logs import info, debug, error, warning
from dataclasses import dataclass, field


@dataclass
class AgentSession:
    """Representa uma execução isolada de um agent"""

    session_id: str
    agent_id: str
    agent_name: str
    caller_agent_id: Optional[str]  # Quem chamou (None = user/manager)
    task: str
    started_at: str
    completed_at: Optional[str] = None
    status: str = "pending"  # pending, in_progress, completed, failed
    agent_history: List[Dict] = field(default_factory=list)  # Cópia isolada
    result: Optional[str] = None
    error: Optional[str] = None
    iterations: int = 0
    tools_executed: int = 0


class AgentSessionManager:
    """
    Gerencia sessões isoladas de execução de agents.

    Responsabilidades:
    - Criar nova sessão quando agent é chamado
    - Manter cópia isolada do histórico
    - Sincronizar resultados de volta ao histórico principal
    - Rastrear execuções paralelas ou sequenciais
    """

    def __init__(self, llm_client, chat_manager, tool_facilitator, agent_manager):
        """
        Inicializa o gerenciador de sessões.

        Args:
            llm_client: Cliente LLM (OpenAI ou Ollama)
            chat_manager: Gerenciador de chats
            tool_facilitator: Facilitador de ferramentas
            agent_manager: Gerenciador de agentes (agentx.py)
        """
        self.llm_client = llm_client
        self.chat_manager = chat_manager
        self.tool_facilitator = tool_facilitator
        self.agent_manager = agent_manager

        self.sessions: Dict[str, AgentSession] = {}
        self.session_counter = 0

        # Carrega configurações dos agents
        self.agents_config = self._load_agents_config()

    def create_session(
        self,
        agent_id: str,
        agent_name: str,
        task: str,
        conversation_history: List[Dict],
        caller_agent_id: Optional[str] = None,
    ) -> AgentSession:
        """
        Cria uma nova sessão isolada para execução de agent.

        Args:
            agent_id: ID do agent a executar
            agent_name: Nome do agent
            task: Tarefa/prompt a executar
            conversation_history: Histórico da conversa principal (será copiado)
            caller_agent_id: ID do agent que chamou (None = user/manager)

        Returns:
            AgentSession com contexto isolado criado
        """
        self.session_counter += 1
        session_id = f"{agent_id}-{self.session_counter}"

        # [CRÍTICO] Extract main system prompt from conversation_history
        # O agent recebe: Main system_prompt (behavioral guidelines) + Agent-specific system_prompt (identity)
        main_system_prompt = None
        if conversation_history and len(conversation_history) > 0:
            first_msg = conversation_history[0]
            if first_msg.get("role") == "system":
                main_system_prompt = first_msg.get("content")

        # Get agent-specific system prompt
        agent_system_prompt = self._find_agent_system_prompt(agent_id)

        # Combine system prompts
        combined_system_prompt = self._combine_system_prompts(
            main_system_prompt, agent_system_prompt, agent_name
        )

        agent_history = [
            {
                "role": "system",
                "content": combined_system_prompt,
                "timestamp": datetime.now().isoformat(),
            }
        ]
        removed = 0

        session = AgentSession(
            session_id=session_id,
            agent_id=agent_id,
            agent_name=agent_name,
            caller_agent_id=caller_agent_id,
            task=task,
            started_at=datetime.now().isoformat(),
            agent_history=agent_history,
        )

        self.sessions[session_id] = session

        debug(f"Sessão criada: {session_id}")
        debug(
            f"Agent: {agent_name} | Histórico: {len(agent_history)} msgs (removidas {removed} incompletas) | Tarefa: {task[:50]}..."
        )

        return session

    def execute_session(
        self, session: AgentSession, max_iterations: int = 25
    ) -> Dict[str, Any]:
        """
        Executa um agent em sua sessão isolada.

        Este método:
        1. Salva o histórico principal do chat_manager
        2. Substitui pelo histórico isolado da sessão
        3. Executa o agent com seu próprio contexto
        4. Restaura o histórico principal
        5. Sincroniza resultados de volta

        Args:
            session: AgentSession a executar
            max_iterations: Limite de iterações do loop

        Returns:
            Dict com resultado da execução
        """
        try:
            session.status = "in_progress"
            debug(f"Executando sessão: {session.session_id}")

            # Importa aqui para evitar circular imports
            from App.Features.MessageProcessor import MessageProcessor

            # [CRÍTICO] Salva o histórico principal E o arquivo principal
            # Isso garante que as mensagens do agent sejam salvas no arquivo do agent, não no main
            saved_conversation_history = self.chat_manager.conversation_history
            saved_chat_file = self.chat_manager.current_chat_file
            self.chat_manager.conversation_history = session.agent_history

            # [CRÍTICO] Muda o current_chat_file para o arquivo do agent
            # Isso faz com que save_message() salve em AGENT.json, não em chat_1.json
            from pathlib import Path

            if self.chat_manager.current_chat_id:
                chat_folder = (
                    Path(self.chat_manager.chats_dir)
                    / f"chat_{self.chat_manager.current_chat_id}"
                )
                agent_chat_file = chat_folder / f"{session.agent_name}.json"
                self.chat_manager.current_chat_file = agent_chat_file
                debug(f"Current chat file alterado para: {agent_chat_file}")

            debug(
                f"Substituído histórico para sessão isolada: {len(session.agent_history)} msgs com system_prompt combinado (main + specific)"
            )

            # [CRÍTICO] Cria arquivo limpo do agent com APENAS o system_prompt COMBINADO
            # Isso garante que o agent comece do zero sem mensagens anteriores
            self._create_clean_agent_file(
                session.agent_name,
                session.agent_id,
                (
                    session.agent_history[0].get("content")
                    if session.agent_history
                    and session.agent_history[0].get("role") == "system"
                    else None
                ),
            )

            # [IMPORTANTE] Obtém informações do caller (quem chamou o agent)
            caller_agent_name = "ASSISTANT"  # Default
            caller_agent_id = session.caller_agent_id or "manager-001"

            # Obtém nome do agent que chamou
            if (
                session.caller_agent_id
                and hasattr(self, "agent_manager")
                and self.agent_manager
            ):
                caller_agent = self.agent_manager.get_agent(session.caller_agent_id)
                if caller_agent:
                    caller_agent_name = getattr(caller_agent, "name", "ASSISTANT")

            # [ARQUITETURA] UMA ÚNICA SAVE necessária:
            # CODER.json: "user" com identificação de quem enviou (SENDER attribution via metadata)
            #
            # IMPORTANTE: NÃO fazer segunda save em ASSISTANT.json porque:
            # - A mensagem já está no tool_calls message com "[Chamando 1 tool(s)]"
            # - Evita duplicação no main chat
            # - O sync_to_main_chat() vai consolidar corretamente
            # - Se fizer segunda save, vai aparecer a mensagem duplicada

            # Save: Em CODER.json como "user" (mensagem RECEBIDA pelo agent)
            # com metadados sobre quem enviou (caller)
            self.chat_manager.save_message(
                role="user",  # CODER recebe uma mensagem do usuário/agent
                content=session.task,  # Message já tem agent name injetado aqui
                agent_name=session.agent_name,  # RECEIVER: quem recebeu a mensagem
                agent_id=session.agent_id,
                # Metadata: quem enviou a mensagem (para rastreabilidade)
                _from_agent_name=caller_agent_name,
                _from_agent_id=caller_agent_id,
            )

            try:
                # Cria MessageProcessor com histórico isolado
                processor = MessageProcessor(
                    llm_client=self.llm_client,
                    chat_manager=self.chat_manager,
                    tool_facilitator=self.tool_facilitator,
                )

                # Executa completamente (vai iterar até resposta final)
                # user_message_already_saved=True porque agent_session_manager já salvou a user message com metadados
                result = processor.process_message(
                    user_message=session.task,
                    agent_id=session.agent_id,
                    max_iterations=max_iterations,
                    user_message_already_saved=True,
                )

                # Atualiza sessão com resultado
                session.result = result.get("response", "")
                session.iterations = result.get("iterations", 0)
                session.tools_executed = result.get("tool_calls_executed", 0)
                session.completed_at = datetime.now().isoformat()
                session.status = "completed" if result.get("success") else "failed"

                debug(f"Sessão completa: {session.session_id}")
                debug(f"Resultado: {session.result[:100]}...")

                return {
                    "success": True,
                    "session_id": session.session_id,
                    "agent_id": session.agent_id,
                    "agent_name": session.agent_name,
                    "result": session.result,
                    "iterations": session.iterations,
                    "tools_executed": session.tools_executed,
                    "timestamp": session.completed_at,
                }

            except Exception as e:
                error_msg = f"Erro ao executar sessão {session.session_id}: {str(e)}"
                error(f"{error_msg}")

                session.error = error_msg
                session.status = "failed"
                session.completed_at = datetime.now().isoformat()

                return {
                    "success": False,
                    "session_id": session.session_id,
                    "agent_id": session.agent_id,
                    "agent_name": session.agent_name,
                    "error": error_msg,
                    "timestamp": session.completed_at,
                }

            finally:
                # [CRÍTICO] Restaura histórico principal E arquivo principal
                # Garante que o histórico principal é restaurado mesmo se houver erro
                # NÃO incluir as mensagens intermediárias do agent - apenas a resposta final
                # (a resposta final é sincronizada via sync_session_to_history())
                self.chat_manager.conversation_history = saved_conversation_history
                self.chat_manager.current_chat_file = saved_chat_file
                debug(
                    f"Histórico e arquivo principais restaurados: {len(saved_conversation_history)} msgs (sem mensagens internas do agent)"
                )

        except Exception as e:
            error_msg = f"Erro ao executar sessão {session.session_id}: {str(e)}"
            error(f"{error_msg}")

            session.error = error_msg
            session.status = "failed"
            session.completed_at = datetime.now().isoformat()

            return {
                "success": False,
                "session_id": session.session_id,
                "agent_id": session.agent_id,
                "agent_name": session.agent_name,
                "error": error_msg,
                "timestamp": session.completed_at,
            }

    def sync_session_to_history(
        self,
        session: AgentSession,
        main_history: List[Dict],
        tool_call_id: str,
        tool_name: str = "agent",
    ) -> List[Dict]:
        """
        Sincroniza resultado da sessão de volta ao histórico principal.

        Este método:
        1. Extrai todas as tool results da sessão do agent
        2. Adiciona essas tool results ao histórico principal
        3. Inclui a resposta final do agent com sua metadata

        Args:
            session: AgentSession completada
            main_history: Histórico principal do chat
            tool_call_id: ID da tool call original que disparou o agent
            tool_name: Nome da ferramenta que foi chamada

        Returns:
            Histórico atualizado
        """
        try:
            debug(f"===== INICIANDO SYNC_SESSION_TO_HISTORY =====")
            debug(f"Session ID: {session.session_id}")
            debug(f"Agent: {session.agent_name}")
            debug(f"tool_call_id={tool_call_id}, tool_name={tool_name}")
            debug(f"Sincronizando sessão {session.session_id} de volta ao histórico")

            # [CRÍTICO] Carrega histórico ATUALIZADO do arquivo do agent
            # (as mensagens foram adicionadas durante execute_session)
            updated_agent_history = session.agent_history
            if self.chat_manager.current_chat_id:
                chat_folder = (
                    Path(self.chat_manager.chats_dir)
                    / f"chat_{self.chat_manager.current_chat_id}"
                )
                agent_file = chat_folder / f"{session.agent_name}.json"
                if agent_file.exists():
                    try:
                        with open(agent_file, "r", encoding="utf-8") as f:
                            agent_data = json.load(f)
                            updated_agent_history = agent_data.get(
                                "messages", session.agent_history
                            )
                            debug(
                                f"Carregado histórico atualizado do {session.agent_name}.json: {len(updated_agent_history)} mensagens"
                            )
                    except Exception as e:
                        debug(f"Erro ao carregar histórico do agent: {e}")

            # [CRÍTICO] Sincroniza PAIRS (assistant + tool) da sessão do agent
            # Cada tool message DEVE ser precedida por sua assistant message com tool_calls
            # Isso mantém compatibilidade com OpenAI API
            if updated_agent_history:
                synced_indices = set()  # Rastreia indices já sincronizados

                for i, msg in enumerate(updated_agent_history):
                    if i in synced_indices:
                        continue

                    # Pula mensagens de sistema
                    if msg.get("role") == "system":
                        continue

                    # Pula TODOS os user messages (não devem ser sincronizados para main_history)
                    # User messages já foram enviados pelo caller, não precisam ser re-sincronizados
                    if msg.get("role") == "user":
                        continue

                    # [CRÍTICO] Se for assistant com tool_calls, sincroniza JUNTO com suas tool responses
                    if msg.get("role") == "assistant" and msg.get("tool_calls"):
                        debug(
                            f"Sincronizando assistant message com tool_calls (índice {i})"
                        )

                        # Adiciona a assistant message
                        main_history.append(
                            {
                                "role": "assistant",
                                "content": msg.get("content", ""),
                                "tool_calls": msg.get("tool_calls"),
                                "agent_name": session.agent_name,
                                "agent_id": session.agent_id,
                            }
                        )
                        synced_indices.add(i)

                        # Extrai todos os tool_call_ids desta assistant message
                        tool_call_ids = set()
                        for tc in msg.get("tool_calls", []):
                            tool_call_ids.add(tc.get("id"))

                        # Procura e sincroniza todas as tool messages correspondentes
                        for j in range(i + 1, len(updated_agent_history)):
                            next_msg = updated_agent_history[j]

                            # Para se encontrar outra assistant message (fim deste grupo)
                            if next_msg.get("role") == "assistant":
                                break

                            # Se for tool message com tool_call_id que corresponde, sincroniza
                            if (
                                next_msg.get("role") == "tool"
                                and next_msg.get("tool_call_id") in tool_call_ids
                            ):
                                debug(
                                    f"Sincronizando tool result correspondente: {next_msg.get('name')} (índice {j})"
                                )
                                main_history.append(
                                    {
                                        "role": "tool",
                                        "content": next_msg.get("content", ""),
                                        "tool_call_id": next_msg.get("tool_call_id"),
                                        "name": next_msg.get("name"),
                                        "agent_name": session.agent_name,
                                        "agent_id": session.agent_id,
                                    }
                                )
                                synced_indices.add(j)
                        continue

                    # Pula tool messages que já foram sincronizadas com seu pair anterior
                    if msg.get("role") == "tool" and i in synced_indices:
                        continue

            # Extrai resultado final do agent
            # Se há updated_agent_history, usa a ÚLTIMA mensagem "assistant" como resposta
            result_content = None
            if updated_agent_history:
                debug(
                    f"Procurando resposta final em {len(updated_agent_history)} mensagens"
                )
                # Procura última mensagem "assistant" na conversa do agent
                for msg in reversed(updated_agent_history):
                    if msg.get("role") == "assistant" and not msg.get("tool_calls"):
                        # Encontrou resposta final sem tool_calls
                        result_content = msg.get("content", "")
                        debug(
                            f"Encontrada resposta final: {len(result_content)} caracteres"
                        )
                        break

            # Se não encontrou na conversation_history, usa session.result
            if not result_content:
                if session.status == "completed":
                    result_content = session.result
                    success_indicator = "OK"
                else:
                    result_content = f"[ERRO] {session.error}"
                    success_indicator = "ERRO"
            else:
                success_indicator = "OK"

            debug(f"tool_call_id={tool_call_id}, tool_name={tool_name}")
            debug(f"current_chat_id={self.chat_manager.current_chat_id}")

            # Salva resposta final como tool message no arquivo do agent caller (ex: ASSISTANT.json)
            # Não adiciona ao main_history em memória, apenas salva no arquivo
            if self.chat_manager.current_chat_id:
                assistant_chat_folder = (
                    Path(self.chat_manager.chats_dir)
                    / f"chat_{self.chat_manager.current_chat_id}"
                )
                assistant_file = assistant_chat_folder / "ASSISTANT.json"

                debug(f"Tentando salvar em: {assistant_file}")
                debug(f"Arquivo existe: {assistant_file.exists()}")

                if assistant_file.exists():
                    try:
                        with open(assistant_file, "r", encoding="utf-8") as f:
                            assistant_data = json.load(f)

                        debug(
                            f"ASSISTANT.json carregado, {len(assistant_data.get('messages', []))} mensagens"
                        )

                        # Adiciona resposta do agent como tool message
                        tool_response_msg = {
                            "role": "tool",
                            "content": result_content,
                            "tool_call_id": tool_call_id,
                            "name": tool_name,
                            "agent_name": "ASSISTANT",
                            "agent_id": "manager-001",
                            "timestamp": datetime.now().isoformat(),
                        }

                        assistant_data["messages"].append(tool_response_msg)

                        with open(assistant_file, "w", encoding="utf-8") as f:
                            json.dump(assistant_data, f, indent=2, ensure_ascii=False)

                        debug(
                            f"✓ Resposta do agent {session.agent_name} salva em ASSISTANT.json com tool_call_id={tool_call_id}"
                        )

                        # Notifica o job que o salvamento foi concluído
                        if (
                            hasattr(self.chat_manager, "current_job")
                            and self.chat_manager.current_job
                        ):
                            self.chat_manager.current_job.mark_agent_save_complete()
                    except Exception as e:
                        error(f"Erro ao salvar em ASSISTANT.json: {str(e)}")
                        debug(f"Traceback: {e}")
                else:
                    debug(f"ASSISTANT.json NÃO ENCONTRADO em {assistant_file}")
            else:
                debug(f"current_chat_id é None, não salvando")

            debug(f"Sessão sincronizada: {session.agent_name}")
            debug(f"Histórico agora tem {len(main_history)} mensagens")

            return main_history

        except Exception as e:
            error(f"Erro ao sincronizar sessão: {str(e)}")
            return main_history

    def get_session(self, session_id: str) -> Optional[AgentSession]:
        """Retorna sessão pelo ID"""
        return self.sessions.get(session_id)

    def get_session_status(self, session_id: str) -> Dict[str, Any]:
        """Retorna status de uma sessão"""
        session = self.get_session(session_id)
        if not session:
            return {"error": f"Sessão {session_id} não encontrada"}

        return {
            "session_id": session.session_id,
            "agent_id": session.agent_id,
            "agent_name": session.agent_name,
            "status": session.status,
            "iterations": session.iterations,
            "tools_executed": session.tools_executed,
            "started_at": session.started_at,
            "completed_at": session.completed_at,
            "result": session.result[:100] + "..." if session.result else None,
        }

    def list_sessions(self) -> List[Dict[str, Any]]:
        """Lista todas as sessões conhecidas"""
        return [self.get_session_status(sid) for sid in self.sessions.keys()]

    def cleanup_session(self, session_id: str):
        """Remove sessão (para limpeza após sincronização)"""
        if session_id in self.sessions:
            del self.sessions[session_id]
            debug(f"Sessão {session_id} removida")

    def _create_clean_agent_file(
        self, agent_name: str, agent_id: str, system_prompt: Optional[str]
    ) -> None:
        """
        Cria um arquivo LIMPO para o agent com APENAS o system_prompt combinado.

        Isso garante que:
        1. O arquivo é inicializado ANTES de qualquer mensagem ser processada
        2. O system_prompt é a PRIMEIRA mensagem no arquivo
        3. Não há mensagens residuais de execuções anteriores

        Args:
            agent_name: Nome do agent
            agent_id: ID do agent
            system_prompt: System prompt combinado (main + specific)
        """
        try:
            if not self.chat_manager.current_chat_id:
                debug(
                    f"Nenhum chat_id disponível, pulando criação de arquivo agent limpo"
                )
                return

            # Determina o caminho do arquivo
            from pathlib import Path

            chat_folder = (
                Path(self.chat_manager.chats_dir)
                / f"chat_{self.chat_manager.current_chat_id}"
            )
            chat_folder.mkdir(parents=True, exist_ok=True)
            agent_file = chat_folder / f"{agent_name}.json"

            # Cria estrutura LIMPA do arquivo com APENAS o system_prompt
            agent_data = {"agent_name": agent_name, "messages": []}

            # Adiciona o system_prompt como primeira mensagem
            if system_prompt:
                agent_data["messages"].append(
                    {
                        "role": "system",
                        "content": system_prompt,
                        "timestamp": datetime.now().isoformat(),
                        "agent_name": agent_name,
                        "agent_id": agent_id,
                    }
                )

            # Salva o arquivo LIMPO
            with open(agent_file, "w", encoding="utf-8") as f:
                json.dump(agent_data, f, indent=2, ensure_ascii=False)

            debug(
                f"Arquivo limpo criado para {agent_name}: {agent_file} com system_prompt combinado"
            )

        except Exception as e:
            error(f"Erro ao criar arquivo limpo para {agent_name}: {str(e)}")

    def _load_agents_config(self) -> Dict[str, Any]:
        """Carrega configurações dos agents do arquivo AGENTS.json"""
        try:
            from App.Core.Settings.Settings import BASE_DIR

            agents_file = BASE_DIR / "Data" / "Agents" / "AGENTS.json"

            if agents_file.exists():
                with open(agents_file, "r", encoding="utf-8") as f:
                    config = json.load(f)
                    debug(f"Configurações de agents carregadas: {agents_file}")
                    return config
            else:
                warning(f"Arquivo AGENTS.json não encontrado em: {agents_file}")
                return {"agents": []}
        except Exception as e:
            error(f"Erro ao carregar AGENTS.json: {str(e)}")
            return {"agents": []}

    def _find_agent_system_prompt(self, agent_id: str) -> Optional[str]:
        """Busca o system_prompt de um agent pelo ID"""
        if not self.agents_config or "agents" not in self.agents_config:
            return None

        def search_in_agents(agents_list):
            """Busca recursiva em agents e sub_agents"""
            for agent in agents_list:
                if agent.get("id") == agent_id:
                    return agent.get("system_prompt")
                # Busca em sub_agents se existir
                if "sub_agents" in agent:
                    result = search_in_agents(agent["sub_agents"])
                    if result:
                        return result
            return None

        return search_in_agents(self.agents_config.get("agents", []))

    def _ensure_agent_file_exists(self, agent_name: str, agent_id: str) -> None:
        """
        Cria arquivo do agent com system_prompt se não existir.

        Isso garante que quando o agent executar, ele terá seu próprio arquivo
        já contendo sua mensagem de sistema personalizada.
        """
        if not self.chat_manager.current_chat_id:
            debug(f"Nenhum chat_id disponível, pulando criação de arquivo agent")
            return

        try:
            # Determina o caminho do arquivo do agent
            chat_folder = (
                Path(self.chat_manager.current_chat_file).parent
                if self.chat_manager.current_chat_file
                else None
            )
            if not chat_folder:
                debug(f"Nenhuma pasta de chat disponível")
                return

            agent_file = chat_folder / f"{agent_name}.json"

            # Se o arquivo já existe, não precisa criar
            if agent_file.exists():
                debug(f"Arquivo {agent_name}.json já existe")
                return

            # Busca o system_prompt do agent
            agent_system_prompt = self._find_agent_system_prompt(agent_id)
            if not agent_system_prompt:
                debug(
                    f"Nenhum system_prompt encontrado para {agent_name}, criando arquivo sem"
                )
                agent_system_prompt = f"Você é o agent {agent_name}."

            # Cria estrutura inicial do arquivo com sistema_prompt
            agent_data = {
                "agent_name": agent_name,
                "agent_id": agent_id,
                "messages": [
                    {
                        "role": "system",
                        "content": agent_system_prompt,
                        "timestamp": datetime.now().isoformat(),
                    }
                ],
            }

            # Salva o arquivo
            with open(agent_file, "w", encoding="utf-8") as f:
                json.dump(agent_data, f, indent=2, ensure_ascii=False)

            debug(f"Arquivo {agent_name}.json criado com system_prompt")

        except Exception as e:
            error(f"Erro ao criar arquivo {agent_name}.json: {str(e)}")

    def _combine_system_prompts(
        self,
        main_system_prompt: Optional[str],
        agent_system_prompt: Optional[str],
        agent_name: str,
    ) -> str:
        """
        Combina o system prompt principal com o system prompt específico do agent.

        Estrutura:
        1. Guidelines/comportamento gerais (main_system_prompt)
        2. Identidade e responsabilidades específicas (agent_system_prompt)
        3. Instrução de priorização

        Args:
            main_system_prompt: System prompt padrão com guidelines gerais
            agent_system_prompt: System prompt específico do agent
            agent_name: Nome do agent (para fallback)

        Returns:
            System prompt combinado e estruturado
        """
        # Se nenhum dos dois existir
        if not main_system_prompt and not agent_system_prompt:
            fallback = f"Você é o agent {agent_name}."
            warning(
                f"Nenhum system_prompt encontrado para {agent_name}, usando fallback genérico"
            )
            return fallback

        # Se apenas um existir
        if main_system_prompt and not agent_system_prompt:
            warning(
                f"Nenhum system_prompt específico encontrado para {agent_name}, usando apenas main"
            )
            return main_system_prompt

        if agent_system_prompt and not main_system_prompt:
            info(
                f"Agent {agent_name} iniciado com system_prompt específico (main não encontrado)"
            )
            return agent_system_prompt

        # Ambos existem - combinar estruturadamente
        combined = f"""{main_system_prompt}

---

{agent_system_prompt}

---

**PRIORIZAÇÃO:** Se houver conflito entre as guidelines acima e a identidade específica do agent, a identidade específica tem prioridade, mas sempre respeitando os guidelines gerais de comportamento."""

        info(
            f"Agent {agent_name} iniciado com system_prompt combinado (main + specific com priorização estruturada)"
        )
        return combined
