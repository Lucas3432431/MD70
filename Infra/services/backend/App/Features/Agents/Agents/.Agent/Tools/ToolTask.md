# task — Criar e Gerenciar Tarefas

**Objetivo:** Criar pipelines de trabalho com etapas rastreáveis, atualizar status e listar tasks.

## Ações

### Criar task
```
task(action="create", name="PIPELINE CAMPANHA", steps=[
  {"step_context": "PESQUISA_DO_ANUNCIANTE", "task_name": "1. Pesquisa"},
  {"step_context": "PESQUISA_DO_MERCADO",    "task_name": "2. Mercado"}
])
```

### Atualizar status de um step
```
task(action="update", step_context="PESQUISA_DO_ANUNCIANTE", status="completed")
```

### Listar tasks
```
task(action="list")
```

## Parâmetros

| Parâmetro | Tipo | Descrição |
|-----------|------|-----------|
| `action` | string (obrigatório) | `create` \| `update` \| `list` |
| `name` | string | Nome da task (para `create`) |
| `steps` | array | Array de `{step_context, task_name}` (para `create`) |
| `step_context` | string | ID único do step definido em STEPS.json (para `update`) |
| `status` | string | `pending` \| `in_progress` \| `completed` (para `update`) |

> **`step_context` DEVE ser o ID único definido em STEPS.json** — o backend retorna automaticamente as instruções da etapa correspondente.
