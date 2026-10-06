# quiz — Fazer Pergunta ao Usuário

**Objetivo:** Apresentar uma ou mais perguntas com opções de múltipla escolha e aguardar a resposta antes de continuar.

> **BLOQUEANTE:** O pipeline para até o usuário responder.

## Exemplo
```
quiz(quiz=[
  {
    "question": "Qual é seu principal objetivo agora?",
    "options": ["Aumentar vendas", "Gerar leads", "Awareness de marca"],
    "type": "múltipla escolha"
  },
  {
    "question": "Qual plataforma é prioridade?",
    "options": ["Instagram", "LinkedIn", "Meta Ads", "Todas"],
    "type": "múltipla escolha"
  }
])
```

## Parâmetros

| Parâmetro | Tipo | Descrição |
|-----------|------|-----------|
| `quiz` | array (obrigatório) | Array de perguntas |

### Estrutura de cada pergunta

| Campo | Tipo | Descrição |
|-------|------|-----------|
| `question` | string | Texto da pergunta |
| `options` | array | 2 a 5 opções de resposta |
| `type` | string | Categoria/tipo da pergunta (descritivo) |

**Retorna:** Respostas selecionadas pelo usuário.
