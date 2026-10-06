# document — Salvar Documentos Estruturados

**Objetivo:** Persistir análises, copies, identidades visuais e metas como documentos reutilizáveis.

## Exemplos

### Business Canvas
```
document(
  type="business_canvas",
  title="ACME - Business Canvas",
  data={public_target: "b2c", demographics: {...}, icp: {...}}
)
```

### Copywriting
```
document(
  type="copy",
  title="Copy - Campanha Verão",
  content="# Copy\n\n## Headline\n..."
)
```

### Identidade Visual
```
document(
  type="visual_communication",
  title="Identidade Visual - ACME",
  content="# Visual\n\n## Paleta\n..."
)
```

### Metas SMART
```
document(
  type="goal",
  title="Metas Q3 2026",
  content="# Objetivos\n\n## Meta 1\n..."
)
```

## Parâmetros

| Parâmetro | Tipo | Descrição |
|-----------|------|-----------|
| `type` | string (obrigatório) | `business_canvas` \| `copy` \| `visual_communication` \| `goal` |
| `title` | string (obrigatório) | Nome descritivo do documento |
| `data` | object | JSON estruturado — apenas para `business_canvas` |
| `content` | string | Markdown — para `copy`, `visual_communication`, `goal` |

**Retorna:** ID único do documento criado. Use `context(type="document")` para recuperar IDs depois.
