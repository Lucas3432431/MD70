# google-ads (MCP)

Gerencia campanhas, ad groups e anúncios do Google Ads via API v18.

## Permissões necessárias

| Escopo | Operações |
|--------|-----------|
| `adwords` | Leitura e escrita na conta Google Ads |

---

## Campanhas

```
mcp__google-ads__list_campaigns(status="ENABLED")
  → lista campanhas: ID, nome, status, tipo, orçamento
  status: ENABLED | PAUSED | REMOVED (opcional — retorna todas se omitido)

mcp__google-ads__get_campaign_stats(campaign_id="...", days=30)
  → métricas: impressões, cliques, custo, conversões, CTR, CPC médio
  campaign_id: opcional — omitir para métricas de todas as campanhas

mcp__google-ads__update_campaign(campaign_id="...", name="Novo Nome", status="PAUSED")
  → atualiza nome e/ou status de uma campanha

mcp__google-ads__pause_campaign(campaign_id="...")
  → pausa a campanha (status → PAUSED)

mcp__google-ads__enable_campaign(campaign_id="...")
  → ativa a campanha (status → ENABLED)

mcp__google-ads__delete_campaign(campaign_id="...")
  → remove permanentemente — use com cuidado (prefira pause_campaign)
```

---

## Ad Groups

```
mcp__google-ads__list_ad_groups(campaign_id="...")
  → lista ad groups de uma campanha: ID, nome, status

mcp__google-ads__update_ad_group(ad_group_id="...", name="...", status="...")
  → atualiza nome e/ou status de um ad group

mcp__google-ads__pause_ad_group(ad_group_id="...")
  → pausa o ad group

mcp__google-ads__enable_ad_group(ad_group_id="...")
  → ativa o ad group
```

---

## Anúncios (Criativos)

```
mcp__google-ads__list_ads(campaign_id="...", ad_group_id="...")
  → lista anúncios de um ad group ou campanha: ID, tipo, status, headlines, URLs

mcp__google-ads__pause_ad(ad_id="...", ad_group_id="...")
  → pausa um anúncio específico

mcp__google-ads__enable_ad(ad_id="...", ad_group_id="...")
  → ativa um anúncio específico
```

---

## Keywords

```
mcp__google-ads__list_keywords(campaign_id="...", ad_group_id="...")
  → lista palavras-chave de um ad group ou campanha: texto, tipo de correspondência, status, QS
```

---

## Fluxo típico de análise

```
1. mcp__google-ads__list_campaigns()                           → lista campanhas ativas
2. mcp__google-ads__get_campaign_stats(campaign_id="...", days=7) → métricas da semana
3. mcp__google-ads__list_ad_groups(campaign_id="...")          → ad groups da campanha
4. mcp__google-ads__list_keywords(ad_group_id="...")           → keywords por ad group
```

## Fluxo típico de otimização

```
1. mcp__google-ads__get_campaign_stats()                  → identifica campanhas com baixo ROI
2. mcp__google-ads__pause_campaign(campaign_id="...")     → pausa as ineficientes
3. mcp__google-ads__enable_campaign(campaign_id="...")    → ativa as de melhor desempenho
```
