# CRM — Funil Analítico e Cohorts de Marketing

**Objetivo:** Visão macro do pipeline de vendas — distribuição por etapa, taxas de conversão, segmentação por origem/qualificação e gerenciamento de cohorts de marketing.

Use `leads()` para CRUD de leads individuais. Use `crm()` para análise e cohorts.

## Ações disponíveis

| Ação | O que faz |
|------|-----------|
| `funnel` | Resumo do funil: leads por estágio + taxas de conversão |
| `segment` | Agrupa leads por dimensão (origin_type, qualification, etc.) |
| `cohort_read` | Lista cohorts CRM (com contagem de leads em cada um) |
| `cohort_post` | Cria novo cohort CRM |
| `cohort_patch` | Atualiza cohort existente |
| `cohort_delete` | Remove cohort |

---

## Funil (action="funnel")

Retorna a distribuição de leads em cada estágio com taxa de conversão entre etapas consecutivas.

```
crm(action="funnel")
crm(action="funnel", funnel_type="self_service")
crm(action="funnel", cohort_id="uuid-cohort-meta-jul25")
crm(action="funnel", origin_type="campaign", date_from="2025-07-01")
```

### Resposta
```json
{
  "success": true,
  "action": "funnel",
  "funnel_type": "consultivo",
  "total_leads": 847,
  "pipeline": [
    { "stage_id": "nao_atendido", "label": "Cadastrado", "count": 500, "pct_of_total": 59.0, "conversion_from_prev": null },
    { "stage_id": "atendido", "label": "Atendido", "count": 320, "pct_of_total": 37.8, "conversion_from_prev": 64.0 },
    { "stage_id": "proposta", "label": "Proposta", "count": 45, "pct_of_total": 5.3, "conversion_from_prev": 14.1 },
    { "stage_id": "fechado", "label": "Fechado", "count": 12, "pct_of_total": 1.4, "conversion_from_prev": 26.7,
      "avg_qualification": 4.2, "hot_leads": 10 }
  ],
  "post_sale": [
    { "stage_id": "sucesso", "label": "Sucesso", "count": 8 }
  ],
  "isolated": [
    { "stage_id": "perdido", "label": "Perdido", "count": 22 },
    { "stage_id": "recuperacao", "label": "Recuperação", "count": 5 }
  ]
}
```

---

## Segmentação (action="segment")

Agrupa e conta leads por uma dimensão para análise cruzada.

```
crm(action="segment", by="origin_type")
crm(action="segment", by="consciousness_level", funnel_stage="proposta")
crm(action="segment", by="qualification", cohort_id="uuid")
```

### Dimensões disponíveis (`by`)
| Valor | Descrição |
|-------|-----------|
| `origin_type` | Origem do lead: campaign, referral, social_media... |
| `funnel_stage` | Distribuição por estágio |
| `consciousness_level` | Nível de consciência 1-5 |
| `qualification` | Qualificação 1-5 |
| `mql_level` | Nível MQL |
| `payment_method` | Forma de pagamento preferida |

---

## Cohorts CRM

Cohorts são segmentos nomeados de leads. Exemplo: "Meta Ads — Jul/25" agrupando leads vindos de campanhas específicas.

### Workflow típico de cohort de campanha

```
# 1. Criar o cohort
crm(action="cohort_post",
  name="Meta Ads — Campanha Verão Jul/25",
  type="paid_ads",
  tracking_params={
    "channel": "meta-ads",
    "utm_campaign": "verao-2025",
    "utm_content": "adset-jovens-sp",
    "campaign_id": "123456789"
  }
)
# Retorna: { "id": "cohort-uuid" }

# 2. Vincular leads ao cohort (via tool leads)
leads(action="read", origin_type="campaign", date_from="2025-07-01")
# Para cada lead relevante:
leads(action="patch", chat_id="...", cohort_ids=["cohort-uuid"])

# 3. Analisar o funil filtrado pelo cohort
crm(action="funnel", cohort_id="cohort-uuid")

# 4. Ver segmentação por estágio dentro do cohort
crm(action="segment", by="funnel_stage", cohort_id="cohort-uuid")
```

### Criar cohort
```
crm(action="cohort_post",
  name="Meta Ads — Jul/25",
  description="Leads da campanha de remarketing de julho",
  type="paid_ads",
  tracking_params={
    "channel": "meta-ads",
    "utm_campaign": "remarketing-jul25",
    "campaign_id": "act_123456",
    "adset_id": "789012"
  }
)
```

### Listar cohorts (com contagem de leads)
```
crm(action="cohort_read")
```

### Buscar cohort específico
```
crm(action="cohort_read", id="<uuid>")
```

### Atualizar cohort
```
crm(action="cohort_patch", id="<uuid>", name="Novo Nome", description="...")
```

### Deletar cohort
```
crm(action="cohort_delete", id="<uuid>")
```

---

## Filtros comuns

Todos os filtros abaixo funcionam em `funnel` e `segment`:

| Parâmetro | Descrição |
|-----------|-----------|
| `origin_type` | Filtrar por tipo de origem |
| `cohort_id` | Filtrar leads deste cohort |
| `date_from` | created_at >= YYYY-MM-DD |
| `date_to` | created_at <= YYYY-MM-DD |
| `funnel_type` | `consultivo` (padrão) \| `self_service` \| `acp` |

---

## Integração com analytics SDK

Para cruzar dados de CRM com dados de comportamento do site (UTM → funil CRM):

1. Use `crm(action="cohort_post", tracking_params={utm_campaign: "..."})` para criar o cohort com os UTMs da campanha.
2. Use `leads(action="patch", cohort_ids=[...])` para vincular leads com aquela origem.
3. Use `crm(action="funnel", cohort_id="...")` para ver o funil filtrado.
4. O painel de Triggers já cruza automaticamente com analytics SDK quando cohort tem `utm_campaign` no `tracking_params`.

---

## Tipos de cohort

| `type` | Uso |
|--------|-----|
| `lead` | Segmento genérico de leads |
| `paid_ads` | Campanha paga (Meta, Google, LinkedIn) |
| `email` | E-mail marketing |
| `url` | Landing page específica |
| `client` | Segmento de clientes existentes |
