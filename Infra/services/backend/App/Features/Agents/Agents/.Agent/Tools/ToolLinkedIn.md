# linkedin (MCP)

Publica conteúdo e consulta métricas de ads no LinkedIn via OAuth2.

## Permissões necessárias

| Escopo | Operações |
|--------|-----------|
| `openid`, `profile`, `email` | Perfil do usuário autenticado |
| `w_member_social` | Publicar posts no perfil pessoal |
| `w_organization_social` | Publicar em páginas de empresa |
| `r_organization_social` | Ler páginas de empresa |
| `r_ads` | Ler contas e campanhas de anúncio |
| `r_ads_reporting` | Métricas de performance de ads |

---

## Perfil e Empresa

```
mcp__linkedin__get_profile()
  → retorna: nome, email, URN do usuário autenticado

mcp__linkedin__list_organizations()
  → lista páginas de empresa que o usuário administra: org_id, nome, URN
```

---

## Publicações

```
mcp__linkedin__create_post(text="Texto do post (máx 3000 caracteres)")
  → publica no perfil pessoal do usuário autenticado
  → retorna: post_id, link do post

mcp__linkedin__create_organization_post(org_id="123456789", text="Texto do post")
  → publica em nome de uma página de empresa
  org_id: ID numérico da organização (obtido via list_organizations)
```

---

## LinkedIn Ads

```
mcp__linkedin__list_ad_accounts()
  → lista contas de anúncio: account_id, nome, status, moeda

mcp__linkedin__list_campaigns(account_id="...")
  → lista Campaign Groups da conta: ID, nome, status, objetivo

mcp__linkedin__get_campaign_insights(account_id="...", campaign_group_id="...", date_range="LAST_30_DAYS")
  → métricas de performance: impressões, cliques, gasto, CTR, CPC
  date_range: LAST_7_DAYS | LAST_30_DAYS | THIS_MONTH | LAST_MONTH
  campaign_group_id: opcional — omitir para métricas agregadas da conta
```

---

## Fluxo de publicação

```
1. mcp__linkedin__get_profile()                              → confirma conta autenticada
2. mcp__linkedin__create_post(text="Novo insight...")        → publica no perfil
   ou
   mcp__linkedin__list_organizations()                       → encontra a empresa
   mcp__linkedin__create_organization_post(org_id="...", text="...") → publica na página
```

## Fluxo de análise de ads

```
1. mcp__linkedin__list_ad_accounts()                         → encontra account_id
2. mcp__linkedin__list_campaigns(account_id="...")           → lista campanhas
3. mcp__linkedin__get_campaign_insights(account_id="...", date_range="LAST_30_DAYS") → métricas
```
