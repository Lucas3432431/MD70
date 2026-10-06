"""File operations for agent sessions."""

import json
from pathlib import Path
from datetime import datetime
from typing import Optional
from App.Core.Logs import debug, error


class FileManager:
    """Gerencia operações com arquivos de agents."""

    @staticmethod
    def create_clean_agent_file(
        agent_name: str, agent_id: str, system_prompt: Optional[str], chat_manager
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
            chat_manager: Gerenciador de chats
        """
        try:
            if not chat_manager.current_chat_id:
                debug(
                    f"Nenhum chat_id disponível, pulando criação de arquivo agent limpo"
                )
                return

            # Determina o caminho do arquivo
            chat_folder = (
                Path(chat_manager.chats_dir) / f"chat_{chat_manager.current_chat_id}"
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

    @staticmethod
    def ensure_agent_file_exists(
        agent_name: str, agent_id: str, agent_system_prompt: str, chat_manager
    ) -> None:
        """
        Cria arquivo do agent com system_prompt se não existir.

        Isso garante que quando o agent executar, ele terá seu próprio arquivo
        já contendo sua mensagem de sistema personalizada.

        Args:
            agent_name: Nome do agent
            agent_id: ID do agent
            agent_system_prompt: System prompt específico do agent
            chat_manager: Gerenciador de chats
        """
        if not chat_manager.current_chat_id:
            debug(f"Nenhum chat_id disponível, pulando criação de arquivo agent")
            return

        try:
            # Determina o caminho do arquivo do agent
            chat_folder = (
                Path(chat_manager.current_chat_file).parent
                if chat_manager.current_chat_file
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

            # Use o prompt fornecido ou fallback
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

    @staticmethod
    def load_agent_history_from_file(agent_name: str, chat_manager) -> list:
        """
        Carrega o histórico de um agent do arquivo.

        Args:
            agent_name: Nome do agent
            chat_manager: Gerenciador de chats

        Returns:
            Lista de mensagens ou lista vazia se não encontrar
        """
        try:
            if not chat_manager.current_chat_id:
                return []

            chat_folder = (
                Path(chat_manager.chats_dir) / f"chat_{chat_manager.current_chat_id}"
            )
            agent_file = chat_folder / f"{agent_name}.json"

            if agent_file.exists():
                with open(agent_file, "r", encoding="utf-8") as f:
                    agent_data = json.load(f)
                    return agent_data.get("messages", [])
        except Exception as e:
            debug(f"Erro ao carregar histórico do agent: {e}")

        return []
