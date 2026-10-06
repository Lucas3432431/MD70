"""
agent_session_manager.py

Módulo de compatibilidade que importa do novo AgentSessionManager modularizado.

Quando um agent é chamado, abre uma nova "sessão" com seu próprio contexto,
evitando que múltiplas tool calls fiquem incompletas.

Fluxo:
1. Main agent chama tool "agent" → Retorna sucesso imediatamente
2. AgentSessionManager abre NOVA conexão para o agent chamado
3. Agent chamado executa independentemente com seu próprio MessageProcessor
4. Resultado é sincronizado de volta ao histórico principal

ARQUITETURA:
- Backup do código original: agent_session_manager_legacy.py
- Implementação modularizada: AgentSessionManager/
  - models.py: AgentSession dataclass
  - config_loader.py: Carregamento de AGENTS.json
  - prompt_manager.py: Combinação de system prompts
  - file_manager.py: Operações com arquivos
  - session_executor.py: Criação e execução
  - session_sync.py: Sincronização com main history
  - session_queries.py: Consultas de status
  - __init__.py: Coordenação dos submódulos
"""

from .AgentSessionManager import AgentSessionManager, AgentSession

__all__ = ["AgentSessionManager", "AgentSession"]
