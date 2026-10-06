# google-tasks (MCP)

Lê tarefas do Google Tasks do usuário via OAuth2.

## Permissões necessárias

| Escopo | Operações |
|--------|-----------|
| `tasks.readonly` | Listar listas e tarefas |
| `tasks` | Criar, atualizar e deletar tarefas |

---

## Listas de Tarefas

```
mcp__google-tasks__list_task_lists()
  → lista todas as listas de tarefas: ID, título, data de atualização
```

---

## Tarefas

```
mcp__google-tasks__list_tasks(tasklist_id="...", show_completed=false, max_results=20)
  → lista tarefas de uma lista: ID, título, notas, data de vencimento, status
  show_completed: incluir tarefas já concluídas (padrão false)
  tasklist_id: obtido via list_task_lists

mcp__google-tasks__get_task(tasklist_id="...", task_id="...")
  → detalhes completos de uma tarefa: título, notas, vencimento, status, subtarefas
```

---

## Fluxo típico

```
1. mcp__google-tasks__list_task_lists()                        → lista as listas disponíveis
2. mcp__google-tasks__list_tasks(tasklist_id="...")            → lista tarefas pendentes
3. mcp__google-tasks__get_task(tasklist_id="...", task_id="...") → detalhes de uma tarefa
```
