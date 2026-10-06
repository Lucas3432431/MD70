"""System prompt management and combination."""

from typing import Optional
from App.Core.Logs import info, warning


class PromptManager:
    """Gerencia combinação e estruturação de system prompts."""

    @staticmethod
    def combine_system_prompts(
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
