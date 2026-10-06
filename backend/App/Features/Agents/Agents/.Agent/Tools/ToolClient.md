# client — Salvar Informações Persistentes do Cliente

**Objetivo:** Persistir dados estratégicos do cliente (briefing, ICP, estratégias) que ficam disponíveis entre chats.

## Exemplo
```
client(
  document="Briefing_ACME",
  content="# Briefing ACME\n\n## Produto\nSuplemento de sono natural...\n\n## ICP\nMulheres 28-45 anos..."
)
```

## Parâmetros

| Parâmetro | Tipo | Descrição |
|-----------|------|-----------|
| `document` | string (obrigatório) | Nome do documento (identificador único) |
| `content` | string (obrigatório) | Conteúdo em markdown |

## Quando usar

- ✅ Salvar briefing inicial do cliente
- ✅ Persistir ICP, avatares, posicionamento
- ✅ Registrar estratégias aprovadas para reutilizar em futuros chats
- ✅ Qualquer informação que deva sobreviver entre sessões

**Retorna:** ID único e `short_description` do documento salvo. Use `context(type="client")` para recuperar depois.
