# Resend — Envio de E-mail

**Objetivo:** Enviar e-mails via Resend com nome de remetente customizável, suporte a texto puro ou HTML com CSS inline, e attachments do chat.

## Ferramenta: `mcp__resend__send_email`

```
mcp__resend__send_email(
  from_name="MD70",
  to="destinatario@email.com",
  subject="Assunto do e-mail",
  html="<h1>Olá!</h1><p>Conteúdo em HTML.</p>",
)
```

### Parâmetros

| Campo | Tipo | Obrigatório | Descrição |
|---|---|---|---|
| `from_name` | string | não | Nome do remetente (padrão: "MD70"). O domínio é fixo. |
| `to` | string ou array | **sim** | Destinatário(s): `"email@x.com"` ou `["a@x.com", "b@x.com"]` |
| `subject` | string | **sim** | Assunto do e-mail |
| `html` | string | condicional | Conteúdo HTML — permite layouts complexos com CSS inline |
| `text` | string | condicional | Conteúdo em texto puro (sem formatação) |
| `attachments` | array | não | Lista de `attachment_id`s do chat para anexar |

> Forneça `html` **ou** `text`. Se fornecer os dois, ambos são enviados (clientes de e-mail usam HTML quando disponível).

---

## Retorno

**Sucesso:**
```json
{
  "success": true,
  "email_id": "re_abc123",
  "to": ["destinatario@email.com"],
  "subject": "Assunto",
  "from": "MD70 <noreply@prox.app.br>"
}
```

**Erro:**
```json
{
  "success": false,
  "error": "Descrição do problema"
}
```

---

## Exemplos

### Texto puro
```
mcp__resend__send_email(
  to="cliente@empresa.com",
  subject="Seu relatório está pronto",
  text="Olá! O relatório solicitado está disponível. Acesse sua conta para baixar."
)
```

### HTML com CSS inline
```
mcp__resend__send_email(
  from_name="Lucas · MD70",
  to="lead@empresa.com",
  subject="Proposta Comercial",
  html="""
  <div style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto">
    <h1 style="color:#1a56db">Proposta Comercial</h1>
    <p>Olá! Segue nossa proposta personalizada.</p>
    <table style="width:100%;border-collapse:collapse">
      <tr style="background:#f3f4f6">
        <th style="padding:8px;text-align:left;border:1px solid #e5e7eb">Plano</th>
        <th style="padding:8px;text-align:right;border:1px solid #e5e7eb">Valor</th>
      </tr>
      <tr>
        <td style="padding:8px;border:1px solid #e5e7eb">Pro Mensal</td>
        <td style="padding:8px;text-align:right;border:1px solid #e5e7eb">R$ 297/mês</td>
      </tr>
    </table>
    <p style="color:#6b7280;font-size:12px">MD70 · Automatize seu crescimento</p>
  </div>
  """
)
```

### Com attachment do chat
```
mcp__resend__send_email(
  to="financeiro@empresa.com",
  subject="Relatório mensal — Junho 2026",
  html="<p>Segue em anexo o relatório de junho.</p>",
  attachments=["uuid-do-attachment-no-chat"]
)
```

---

## Regras importantes

- O **domínio do remetente é fixo** (`prox.app.br`) — apenas o nome pode ser customizado
- Para e-mails marketing/newsletters, prefira `html` com estrutura completa
- Para comunicações simples (notificações, alertas), `text` é suficiente
- CSS inline é suportado — use `style="..."` diretamente nas tags HTML
- `attachment_id` deve ser de um arquivo já existente neste chat
