# google-calendar (MCP)

Lê e gerencia eventos na agenda do usuário via Google Calendar API.

## Permissões necessárias

| Escopo | Operações |
|--------|-----------|
| `calendar.readonly` | Listar e ler eventos |
| `calendar.events` | Criar, atualizar e deletar eventos |

---

## Leitura

```
mcp__google-calendar__list_events(max_results=10, days_ahead=7)
  → lista eventos futuros: ID, título, data/hora início e fim, descrição, local
  days_ahead: quantos dias à frente incluir (padrão 7)
```

---

## Criação e Edição

```
mcp__google-calendar__create_event(title="Reunião", start="2026-07-10T10:00:00", end="2026-07-10T11:00:00", description="...")
  → cria evento; retorna event_id
  Formato de data: ISO 8601 (ex: 2026-07-10T10:00:00)
  Para eventos de dia inteiro usar YYYY-MM-DD sem horário

mcp__google-calendar__update_event(event_id="...", title="...", start="...", end="...", description="...", location="...")
  → atualiza campos parcialmente (informe apenas o que mudar)
  event_id obrigatório; demais campos opcionais

mcp__google-calendar__delete_event(event_id="...")
  → remove o evento permanentemente
```

---

## Fluxo típico

```
1. mcp__google-calendar__list_events(days_ahead=14)        → visualiza agenda dos próximos 14 dias
2. mcp__google-calendar__create_event(...)                 → agenda novo compromisso
3. mcp__google-calendar__update_event(event_id="...", ...) → reagenda ou edita detalhes
```
