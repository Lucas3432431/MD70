# escalate

Escala a conversa para atendimento humano. Para o agente imediatamente e marca a execução como **pending_review** no painel — o operador verá a conversa com botões de Aprovar/Rejeitar.

## Quando usar

- Usuário pede explicitamente para falar com um humano
- Situação que exige julgamento humano (reclamação grave, negociação fora do script, dúvida jurídica/financeira)
- Agente não tem informações suficientes para continuar com segurança

## Uso

```
escalate(reason="...", user_message="...")

reason        obrigatório — motivo visível apenas para o operador no painel
user_message  opcional — mensagem enviada ao usuário antes de escalar
```

## Exemplos

```
# Usuário pediu atendente humano
escalate(
  reason="Cliente solicitou falar com atendente humano",
  user_message="Claro! Vou te conectar com um de nossos atendentes. Aguarde um momento 😊"
)

# Situação fora do escopo do agente
escalate(
  reason="Solicitação de reembolso — requer aprovação da equipe",
  user_message="Entendi! Vou encaminhar seu pedido para nossa equipe. Em breve alguém entrará em contato."
)

# Agente sem contexto suficiente
escalate(
  reason="Cliente com dúvida técnica específica que não consigo responder com precisão"
)
```

## Comportamento

1. Envia `user_message` ao usuário pelo canal original (Instagram, WhatsApp, Telegram) se fornecida
2. Marca a execução como `pending_review` — aparece no painel com notificação
3. **PARA o agente** — não envie mais mensagens automáticas após escalate

> Após usar `escalate`, pare completamente. Não use `send`, não responda mais nada.
