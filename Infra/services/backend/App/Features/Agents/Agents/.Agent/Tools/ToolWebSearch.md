# web-search — Pesquisar e Navegar na Web

**Objetivo:** Buscar informações no Google, extrair conteúdo de URLs e analisar design de sites. Suporta execução paralela.

## Exemplos

### Pesquisar no Google
```
web-search(query="tendências marketing digital 2026", wait=true)
```

### Extrair conteúdo de URL
```
web-search(fetch="https://exemplo.com.br", wait=true)
```

### Análise visual de design
```
web-search(visual-analysis="https://concorrente.com", wait=true)
```

### Múltiplas pesquisas em paralelo
```
web-search(searches=[
  {"query": "benchmarks do setor"},
  {"fetch": "https://exemplo.com/produto"},
  {"visual-analysis": "https://concorrente.com"}
], wait=true)
```

## Parâmetros

| Parâmetro | Tipo | Descrição |
|-----------|------|-----------|
| `query` | string | Termo para pesquisar no Google |
| `fetch` | string | URL para extrair conteúdo em markdown |
| `visual-analysis` | string | URL para análise completa de design |
| `searches` | array | Array de múltiplas pesquisas simultâneas |
| `wait` | boolean | `true` = aguarda resultado (padrão) \| `false` = executa em background |

**Retorna:** Resultados de busca, conteúdo em markdown ou análise visual de design.
