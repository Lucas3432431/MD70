# google-analytics (MCP)

Consulta relatórios do Google Analytics 4 (GA4) com métricas e dimensões customizadas.

## Permissões necessárias

| Escopo | Operações |
|--------|-----------|
| `analytics.readonly` | Leitura de relatórios GA4 |

---

## Relatórios

```
mcp__google-analytics__get_report(start_date="30daysAgo", end_date="today", metrics=["sessions","activeUsers"], dimensions=["pagePath"])
  → retorna tabela de métricas × dimensões para o período

start_date / end_date:
  "today" | "yesterday" | "7daysAgo" | "30daysAgo" | "YYYY-MM-DD"

property_id: ID da propriedade GA4 (ex: "123456789") — só necessário se não configurado na integração
```

---

## Métricas disponíveis

| Métrica | Descrição |
|---------|-----------|
| `sessions` | Total de sessões |
| `activeUsers` | Usuários ativos únicos |
| `newUsers` | Novos usuários |
| `screenPageViews` | Visualizações de página |
| `bounceRate` | Taxa de rejeição |
| `averageSessionDuration` | Duração média da sessão (segundos) |
| `engagementRate` | Taxa de engajamento |
| `eventCount` | Total de eventos |
| `conversions` | Total de conversões |

---

## Dimensões disponíveis

| Dimensão | Descrição |
|----------|-----------|
| `pagePath` | Caminho da página (ex: /blog/artigo) |
| `country` | País do usuário |
| `city` | Cidade do usuário |
| `deviceCategory` | Dispositivo: desktop, mobile, tablet |
| `sessionSource` | Fonte da sessão (ex: google, facebook) |
| `sessionMedium` | Mídia (ex: organic, cpc, email) |
| `date` | Data no formato YYYYMMDD |

---

## Exemplos

```
# Visão geral dos últimos 30 dias
mcp__google-analytics__get_report(
  start_date="30daysAgo",
  end_date="today",
  metrics=["sessions", "activeUsers", "bounceRate"]
)

# Top páginas da semana
mcp__google-analytics__get_report(
  start_date="7daysAgo",
  end_date="today",
  metrics=["screenPageViews", "activeUsers"],
  dimensions=["pagePath"]
)

# Tráfego por fonte no mês
mcp__google-analytics__get_report(
  start_date="2026-07-01",
  end_date="2026-07-31",
  metrics=["sessions", "conversions"],
  dimensions=["sessionSource", "sessionMedium"]
)
```
