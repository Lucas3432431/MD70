# context — Recuperar Contexto Persistente

**Objetivo:** Recuperar documentos salvos, dados do cliente, tasks e mídia gerada em chats anteriores.

## Ações

```
context(type="document")   → lista documentos salvos com IDs
context(type="client")     → dados persistentes do cliente
context(type="task")       → status de tarefas em execução
context(type="media")      → informações sobre mídia gerada
```

## Parâmetros

| Parâmetro | Tipo | Descrição |
|-----------|------|-----------|
| `type` | string | `document` \| `client` \| `task` \| `media` |

## Quando usar

- ✅ Recuperar IDs para usar com `document()`, `asset()`, etc.
- ✅ Confirmar informações persistentes do cliente antes de agir
- ✅ Ver status de tasks em andamento
- ✅ Verificar se um documento já existe antes de criar um novo
