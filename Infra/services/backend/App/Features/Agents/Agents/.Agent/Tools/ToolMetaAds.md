# meta-ads (MCP)

Acessa campanhas, conjuntos de anúncios, criativos e métricas do Meta Ads via Graph API.

## Níveis de permissão

| Nível | Escopos necessários | Operações |
|-------|---------------------|-----------|
| **read** | `ads_read` | GET — consultar campanhas, ad sets, ads, insights, públicos, contas |
| **write** | `ads_management` | POST, PATCH, PUT, DELETE — criar/editar/pausar/excluir campanhas e anúncios |

## Operações READ (ads_read)

```
mcp__meta-ads__get_ad_accounts          → lista contas de anúncios acessíveis
mcp__meta-ads__get_campaigns            → lista campanhas de uma conta
mcp__meta-ads__get_adsets               → lista conjuntos de anúncios
mcp__meta-ads__get_ads                  → lista anúncios individuais
mcp__meta-ads__get_ad_insights          → métricas: impressões, cliques, CPM, CPC, ROAS, conversões
mcp__meta-ads__get_ad_creatives         → criativos associados a anúncios
mcp__meta-ads__get_custom_audiences     → públicos personalizados e Lookalike
mcp__meta-ads__get_targeting_search     → pesquisa de interesses, demografias e localizações
```

## Operações WRITE (ads_management)

```
mcp__meta-ads__create_campaign          → cria campanha (objetivo, budget, datas)
mcp__meta-ads__update_campaign          → edita nome, status, orçamento de campanha
mcp__meta-ads__create_adset             → cria conjunto (targeting, budget, placement)
mcp__meta-ads__update_adset             → edita targeting, orçamento, datas de ad set
mcp__meta-ads__create_ad               → cria anúncio vinculando criativo + ad set
mcp__meta-ads__update_ad               → edita status (ACTIVE/PAUSED) ou criativo
mcp__meta-ads__delete_campaign          → remove campanha (DELETE)
mcp__meta-ads__delete_adset             → remove conjunto de anúncios
mcp__meta-ads__delete_ad               → remove anúncio individual
mcp__meta-ads__create_ad_creative       → sobe criativo (imagem/vídeo + copy + CTA)
```

## Parâmetros comuns

- `account_id` — ID da conta no formato `act_XXXXXXXXX`
- `campaign_id` / `adset_id` / `ad_id` — IDs numéricos
- `date_preset` — `last_7d`, `last_30d`, `last_quarter`, `this_year`
- `fields` — campos a retornar (separados por vírgula)
- `status` — `ACTIVE`, `PAUSED`, `ARCHIVED`
- `objective` — `OUTCOME_TRAFFIC`, `OUTCOME_SALES`, `OUTCOME_LEADS`, `OUTCOME_AWARENESS`

## Fluxo típico de análise

```
1. mcp__meta-ads__get_campaigns(account_id="act_XXX", fields="id,name,status,objective")
2. mcp__meta-ads__get_ad_insights(campaign_id="...", date_preset="last_30d", fields="impressions,clicks,spend,cpc,cpm,roas")
3. Analisar → recomendar ajustes de orçamento ou targeting
```

## Fluxo típico de criação

```
1. mcp__meta-ads__create_campaign(account_id="act_XXX", name="...", objective="OUTCOME_TRAFFIC", daily_budget=5000)
2. mcp__meta-ads__create_adset(campaign_id="...", targeting={...}, billing_event="IMPRESSIONS")
3. mcp__meta-ads__create_ad_creative(account_id="act_XXX", image_url="...", message="...", call_to_action="LEARN_MORE")
4. mcp__meta-ads__create_ad(adset_id="...", creative_id="...", name="...")
```
