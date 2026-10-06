# AgentSessionManager - Arquitetura Modularizada

## Visão Geral

O `AgentSessionManager` gerencia execuções isoladas de agents com separação clara de responsabilidades. Cada módulo tem uma função específica e até 440 linhas.

## Estrutura de Arquivos

```
AgentSessionManager/
├── __init__.py              # Coordenação e classe principal (157 linhas)
├── models.py               # Data models - AgentSession dataclass (23 linhas)
├── config_loader.py        # Carregamento de configurações (58 linhas)
├── prompt_manager.py       # Gerenciamento de system prompts (62 linhas)
├── file_manager.py         # Operações com arquivos (154 linhas)
├── session_executor.py     # Criação e execução de sessões (299 linhas)
├── session_sync.py         # Sincronização com main history (272 linhas)
├── session_queries.py      # Consultas de status (64 linhas)
└── README.md              # Este arquivo

BACKUP:
├── agent_session_manager_legacy.py  # Arquivo original completo (717 linhas)
├── agent_session_manager.py         # Arquivo proxy que importa do novo módulo
```

## Detalhamento dos Módulos

### 1. **models.py** (23 linhas)
Define a dataclass `AgentSession` com campos:
- `session_id`: ID único da sessão
- `agent_id`, `agent_name`: Identificação do agent
- `caller_agent_id`: Quem chamou o agent
- `task`: Tarefa a executar
- `status`: pending, in_progress, completed, failed
- `agent_history`: Histórico isolado
- `result`, `error`: Resultado/erro
- `iterations`, `tools_executed`: Métricas

### 2. **config_loader.py** (58 linhas)
Responsável por:
- `load_agents_config()`: Carrega AGENTS.json
- `find_agent_system_prompt()`: Busca recursiva de system prompts

**Exports**: `ConfigLoader` (classe estática)

### 3. **prompt_manager.py** (62 linhas)
Responsável por:
- `combine_system_prompts()`: Combina main + specific prompts
- Estrutura clara com separadores e instrução de priorização

**Exports**: `PromptManager` (classe estática)

### 4. **file_manager.py** (154 linhas)
Responsável por:
- `create_clean_agent_file()`: Cria arquivo limpo com system_prompt
- `ensure_agent_file_exists()`: Cria arquivo se não existir
- `load_agent_history_from_file()`: Carrega histórico do arquivo

**Exports**: `FileManager` (classe estática)

### 5. **session_executor.py** (299 linhas)
Responsável por:
- `create_session()`: Cria nova sessão isolada
- `execute_session()`: Executa agent na sessão
- Gerencia context switch entre main e agent history

**Exports**: `SessionExecutor`

### 6. **session_sync.py** (272 linhas)
Responsável por:
- `sync_session_to_history()`: Sincroniza resultado de volta
- `_load_updated_agent_history()`: Carrega histórico atualizado
- `_sync_agent_messages()`: Sincroniza PAIRS (assistant + tool)
- `_extract_final_result()`: Extrai resposta final
- `_save_final_response()`: Salva em ASSISTANT.json

**Exports**: `SessionSync`

### 7. **session_queries.py** (64 linhas)
Responsável por:
- `get_session()`: Retorna sessão pelo ID
- `get_session_status()`: Status de uma sessão
- `list_sessions()`: Lista todas as sessões
- `cleanup_session()`: Remove sessão

**Exports**: `SessionQueries`

### 8. **__init__.py** (157 linhas)
Coordena todos os módulos:
- Cria classe `AgentSessionManager` que orquestra os submódulos
- Delegação clara: `self.executor`, `self.sync`, `self.queries`
- Interface pública que mantém compatibilidade com código anterior

## Como Usar

### Uso Normal (sem mudanças)
```python
from modules.tools.agent_session_manager import AgentSessionManager

manager = AgentSessionManager(llm_client, chat_manager, tool_facilitator, agent_manager)
session = manager.create_session(...)
result = manager.execute_session(session)
```

### Uso Direto de Componentes
```python
from modules.tools.AgentSessionManager import SessionExecutor, SessionSync
from modules.tools.AgentSessionManager.config_loader import ConfigLoader
from modules.tools.AgentSessionManager.prompt_manager import PromptManager

config = ConfigLoader.load_agents_config()
prompt = PromptManager.combine_system_prompts(main, specific, name)
```

## Vantagens da Modularização

1. **Separação de Responsabilidades**: Cada módulo tem uma única função
2. **Facilita Testes**: Módulos podem ser testados isoladamente
3. **Manutenibilidade**: Arquivos pequenos são mais fáceis de entender
4. **Reusabilidade**: Componentes podem ser usados de forma independente
5. **Escalabilidade**: Fácil adicionar novos recursos sem afetar outros módulos
6. **Compatibilidade**: Código antigo continua funcionando sem mudanças

## Migrração (Se necessário)

Se precisar reverter para a versão original:
```bash
# Restaurar do backup
cp agent_session_manager_legacy.py agent_session_manager.py
```

## Tamanho dos Arquivos

| Arquivo | Linhas | Status |
|---------|--------|--------|
| models.py | 23 | ✓ |
| config_loader.py | 58 | ✓ |
| prompt_manager.py | 62 | ✓ |
| file_manager.py | 154 | ✓ |
| session_queries.py | 64 | ✓ |
| session_sync.py | 272 | ✓ |
| session_executor.py | 299 | ✓ |
| __init__.py | 157 | ✓ |
| **TOTAL** | **1,089** | **Modularizado** |
| **Original** | 717 | Backup em _legacy.py |

Todos os arquivos ficaram abaixo de 440 linhas conforme requisitado.

## Fluxo de Execução

```
[Requisição de Agent]
         ↓
[AgentSessionManager.__init__ importa submódulos]
         ↓
[create_session]
  ├─→ SessionExecutor.create_session()
  │   ├─→ ConfigLoader.find_agent_system_prompt()
  │   ├─→ PromptManager.combine_system_prompts()
  │   └─→ Cria AgentSession
  └─→ Armazena em self.sessions
         ↓
[execute_session]
  ├─→ SessionExecutor.execute_session()
  │   ├─→ FileManager.create_clean_agent_file()
  │   ├─→ MessageProcessor.process_message()
  │   └─→ Retorna resultado
  └─→ Atualiza status
         ↓
[sync_session_to_history]
  ├─→ SessionSync.sync_session_to_history()
  │   ├─→ FileManager.load_agent_history_from_file()
  │   ├─→ Sincroniza PAIRS (assistant + tool)
  │   ├─→ Extrai resposta final
  │   └─→ Salva em ASSISTANT.json
  └─→ Retorna histórico atualizado
```

## Próximos Passos Opcionais

1. Adicionar testes unitários para cada módulo
2. Implementar cache para configurações de agents
3. Adicionar logging estruturado
4. Considerar async/await para paralelização
