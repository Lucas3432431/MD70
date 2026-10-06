# schedule — Agendar Postagens de Conteúdo

**Objetivo:** Planejar e agendar posts em redes sociais, consultar data/hora atual e verificar status de campanhas.

## Consultar data/hora atual
```
schedule(calendar="now")
schedule(day="today")
```

## Modo simplificado (apenas data + descrição)
```
schedule(plan=[
  {day: "15/08/2026", short_description: "Anúncio com CTA de produto"},
  {day: "16/08/2026", short_description: "Depoimento de cliente"}
])
```

## Modo completo (múltiplas campanhas)
```
schedule(schedules=[
  {
    name: "CAMPANHA_VERAO",
    posts: [
      {
        date: "15.08.2026",
        platform: "instagram",
        stage: "awareness",
        content_type: "awareness",
        short_description: "Hook sobre o problema",
        copy: "Você acorda cansado mesmo dormindo 8 horas?"
      },
      {
        date: "16.08.2026",
        platform: "instagram",
        stage: "conversion",
        content_type: "conversion",
        short_description: "CTA com urgência",
        copy: "Oferta encerra em 48h"
      }
    ]
  }
])
```

## Verificar status
```
schedule(action="status", name="CAMPANHA_VERAO")
```

## Parâmetros

| Parâmetro | Tipo | Descrição |
|-----------|------|-----------|
| `calendar` | string | `"now"` → retorna data/hora atual |
| `day` | string | `"today"` → retorna data atual |
| `plan` | array | Modo simples: `[{day, short_description}]` |
| `schedules` | array | Modo completo: campanhas com posts |
| `action` | string | `"status"` → consulta status de campanha |
| `name` | string | Nome da campanha (para `status`) |

## Content types

| Valor | Uso |
|-------|-----|
| `awareness` | Storytelling, hooks, problema |
| `educational` | Solução, ciência, dados |
| `branding` | Identidade e valores da marca |
| `conversion` | CTA direto, oferta, urgência, FOMO |
| `cart_recovery` | Recuperação de carrinho abandonado |

> **`content_type` e `short_description` são obrigatórios** em cada post do modo completo.
