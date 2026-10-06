# gmail (MCP)

Lê e envia e-mails pela conta Gmail do usuário via OAuth2.

## Permissões necessárias

| Escopo | Operações |
|--------|-----------|
| `gmail.readonly` | Listar e ler e-mails |
| `gmail.send` | Enviar e-mails |
| `gmail.modify` | Leitura + envio + modificar labels |

---

## Leitura

```
mcp__gmail__list_emails(max_results=10, query="")
  → lista e-mails recentes: ID, remetente, assunto, data, prévia
  query: filtros no formato Gmail Search (ex: "from:fulano@email.com", "subject:proposta", "is:unread")

mcp__gmail__read_email(message_id="17f...")
  → lê o conteúdo completo de um e-mail pelo ID
  → retorna: remetente, destinatários, assunto, data, corpo (texto ou HTML convertido)
  message_id: obtido via list_emails
```

---

## Envio

```
mcp__gmail__send_email(to="contato@empresa.com", subject="Proposta", body="Olá...")
  → envia e-mail pelo Gmail do usuário autenticado
  body: aceita texto puro ou HTML
```

---

## Filtros de busca úteis (query)

| Filtro | Exemplo |
|--------|---------|
| Remetente | `from:gerente@empresa.com` |
| Assunto | `subject:NF-e` |
| Não lido | `is:unread` |
| Com anexo | `has:attachment` |
| Data | `after:2026/07/01` |
| Período | `after:2026/06/01 before:2026/07/01` |

---

## Fluxo típico

```
1. mcp__gmail__list_emails(query="from:cliente@empresa.com is:unread") → lista não lidos
2. mcp__gmail__read_email(message_id="...")                            → lê conteúdo
3. mcp__gmail__send_email(to="...", subject="Re: ...", body="...")      → responde
```
