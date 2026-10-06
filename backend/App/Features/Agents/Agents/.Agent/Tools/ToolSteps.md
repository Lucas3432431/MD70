# steps

Registra os passos de uma tarefa **sem interromper o loop do agente**. Use no início de tarefas multi-etapa para deixar o plano visível no chat e então executar cada passo em sequência.

## Quando usar

- Ao iniciar uma tarefa com 3+ etapas claras
- Quando o usuário precisa ver o plano antes da execução
- Para substituir `task` em contextos que não são copywriting (sem validação de formato)

## Diferença em relação a `task`

| | `task` | `steps` |
|---|---|---|
| Interrompe o loop? | Sim (validações bloqueantes) | Não |
| Validação de formato | Rígida (copywriting) | Livre |
| `pause=true` | — | Pausa e aguarda usuário |

## Uso

```
steps(name="...", steps=[...])
steps(name="...", steps=[...], pause=true)

name    opcional — nome da tarefa (default: "Tarefa")
steps   obrigatório — array de strings ou {step, status}
pause   opcional — se true, pausa o loop após registrar
```

## Exemplos

```
# Plano simples — loop continua imediatamente
steps(
  name="Análise de concorrentes",
  steps=[
    "Pesquisar top 5 concorrentes",
    "Analisar preços e posicionamento",
    "Identificar gaps de mercado",
    "Gerar relatório"
  ]
)

# Com status explícito
steps(
  name="Campanha Meta Ads",
  steps=[
    {"step": "Criar copy do anúncio", "status": "pending"},
    {"step": "Gerar imagens criativas", "status": "pending"},
    {"step": "Configurar conjunto de anúncios", "status": "pending"}
  ]
)

# Pausar para o usuário confirmar antes de continuar
steps(
  name="Automação de Instagram",
  steps=["Publicar post", "Responder comentários", "Atualizar stories"],
  pause=true
)
```

## Comportamento

- Sem `pause`: registra os passos no banco e retorna imediatamente → **loop continua**
- Com `pause=true`: registra os passos, exibe o plano no chat e **pausa o loop** — o agente só continua quando o usuário enviar uma nova mensagem
