# Paid Campaign Report Skill

**Objetivo:** Parametrizar campanhas Meta Ads antes de publicá-las, coletar resultados via API após rodarem, cruzar parâmetros × métricas no `terminal` e gerar um relatório HTML interativo que evidencie diferenças de performance e o impacto de escala.

**Pré-requisitos:** Integração Meta Ads conectada (`mcp__meta-ads__*`)

**Saída:** Arquivo HTML com dashboard de performance + tabela de parâmetros cruzados com métricas

---

## Visão Geral do Fluxo

```
ANTES de publicar       →  PARAMETRIZAR cada campanha/ad/criativo na tabela interna
DEPOIS de rodar         →  COLETAR métricas via meta-ads tools
CRUZAR                  →  parâmetros × métricas no terminal (Python/pandas)
REPORTAR                →  HTML interativo com gráficos + alertas de escala
```

---

## FASE 1 — Parametrização (antes de publicar)

### Quando ativar
O usuário diz que vai criar uma campanha, subir um anúncio ou pede para registrar parâmetros.

### Tabelas de parâmetros

O agente deve registrar os parâmetros usando `document()` ou armazenando em CSV via `terminal` antes de publicar qualquer campanha. Existem três tabelas separadas:

#### Tabela 1 — Briefing Estratégico (por campanha/conjunto)

| Campo | Descrição |
|---|---|
| `campaign_id` | Preenchido após publicação |
| `adset_id` | Preenchido após publicação |
| `campaign_name` | Nome descritivo interno |
| `archetype` | Arquétipo do público (ex: "Herói", "Sábio", "Explorador") |
| `target_public` | Descrição do público-alvo (quem é) |
| `pain_ambition` | Dor ou ambição central sendo atacada |
| `triggers` | Gatilhos emocionais usados (urgência, prova social, escassez…) |
| `objections` | Objeções que o criativo tenta quebrar |
| `channels` | Canais / placements (Feed, Stories, Reels, Audience Network…) |
| `segmentation` | Resumo da segmentação (interesses, lookalike, retargeting…) |
| `objective` | Objetivo da campanha (LEADS, SALES, TRAFFIC…) |
| `daily_budget_brl` | Orçamento diário em R$ |
| `expected_cpm` | CPM esperado/referência (R$) |
| `expected_ctr` | CTR esperada (%) |
| `expected_cpl` | CPL esperado (R$) |
| `notes` | Observações livres |

#### Tabela 2 — Parâmetros do Criativo (por anúncio individual)

| Campo | Descrição |
|---|---|
| `ad_id` | Preenchido após publicação |
| `ad_name` | Nome descritivo interno |
| `campaign_name` | Referência à campanha |
| `creative_has_people` | Sim / Não — o criativo mostra pessoas? |
| `creative_title_hook` | Título/hook principal do criativo |
| `creative_subtitle` | Subtítulo ou linha de apoio |
| `creative_cta` | CTA do criativo (ex: "Saiba mais", "Compre agora") |
| `ads_text` | Texto do anúncio (primary text) |
| `ads_cta_button` | Botão CTA (LEARN_MORE, SHOP_NOW, SIGN_UP…) |
| `caption` | Legenda / caption do post |
| `camera_perspective` | Perspectiva da câmera (frontal, POV, drone, close-up…) |
| `enquadramento` | Enquadramento (plano fechado, plano aberto, meio corpo…) |
| `visual_hierarchy` | Hierarquia visual: o que aparece em 1º, 2º, 3º plano |
| `colors` | Paleta de cores predominante |
| `contrast` | Nível de contraste (alto / médio / baixo) |
| `textures` | Texturas presentes (liso, granulado, orgânico…) |
| `lightning` | Tipo de iluminação (natural, estúdio, baixa luz, rim light…) |
| `format` | Formato do criativo (imagem estática, carrossel, vídeo, reels) |
| `aspect_ratio` | Proporção (9:16, 1:1, 4:5, 16:9) |
| `notes` | Observações livres |

### Código: criar/salvar tabelas

```python
import pandas as pd, json, os

# Caminhos no sandbox
BRIEFING_FILE = "campaign_briefing.csv"
CREATIVES_FILE = "creative_params.csv"

# Inicializar (ou carregar se já existir)
briefing_cols = [
    "campaign_id","adset_id","campaign_name","archetype","target_public",
    "pain_ambition","triggers","objections","channels","segmentation",
    "objective","daily_budget_brl","expected_cpm","expected_ctr","expected_cpl","notes"
]
creative_cols = [
    "ad_id","ad_name","campaign_name","creative_has_people","creative_title_hook",
    "creative_subtitle","creative_cta","ads_text","ads_cta_button","caption",
    "camera_perspective","enquadramento","visual_hierarchy","colors","contrast",
    "textures","lightning","format","aspect_ratio","notes"
]

df_brief   = pd.read_csv(BRIEFING_FILE)  if os.path.exists(BRIEFING_FILE)   else pd.DataFrame(columns=briefing_cols)
df_creative = pd.read_csv(CREATIVES_FILE) if os.path.exists(CREATIVES_FILE) else pd.DataFrame(columns=creative_cols)

# Adicionar nova campanha
nova_campanha = {
    "campaign_id": "",        # preencher após publicar
    "adset_id": "",           # preencher após publicar
    "campaign_name": "NOME_AQUI",
    "archetype": "...",
    "target_public": "...",
    "pain_ambition": "...",
    "triggers": "...",
    "objections": "...",
    "channels": "Feed,Stories",
    "segmentation": "...",
    "objective": "OUTCOME_LEADS",
    "daily_budget_brl": 30,
    "expected_cpm": 15.0,
    "expected_ctr": 1.5,
    "expected_cpl": 20.0,
    "notes": ""
}
df_brief = pd.concat([df_brief, pd.DataFrame([nova_campanha])], ignore_index=True)
df_brief.to_csv(BRIEFING_FILE, index=False)
print(f"Briefing salvo: {df_brief.shape[0]} campanha(s) registrada(s)")
print(df_brief.tail(3).to_string())
```

### Confirmação Pré-Publicação (obrigatória antes de `create_campaign`)

**Antes de chamar qualquer tool de criação (`mcp__meta-ads__create_campaign`, `create_ad_set`, `create_ad`), o agente DEVE confirmar todos os parâmetros com o usuário.** Isso garante que os dados registrados nas tabelas correspondem exatamente ao que vai ao ar.

Estrutura de confirmação:

```
📋 CONFIRMAÇÃO ANTES DE PUBLICAR

ESTRATÉGICO (campaign_briefing):
• Campanha:       [campaign_name]
• Arquétipo:      [archetype]
• Público-alvo:   [target_public]
• Dor/Ambição:    [pain_ambition]
• Gatilhos:       [triggers]
• Objeções:       [objections]
• Canais:         [channels]
• Segmentação:    [segmentation]
• Objetivo:       [objective]
• Orçamento/dia:  R$ [daily_budget_brl]
• CPM esperado:   R$ [expected_cpm]
• CTR esperada:   [expected_ctr]%
• CPL esperado:   R$ [expected_cpl]

CRIATIVO (creative_params — por variação):
• Criativo:       [ad_name / style_label]
• Tem pessoas:    [creative_has_people]
• Hook/Título:    [creative_title_hook]
• Subtítulo:      [creative_subtitle]
• CTA criativo:   [creative_cta]
• Texto do ad:    [ads_text]
• Botão CTA:      [ads_cta_button]
• Perspectiva:    [camera_perspective]
• Enquadramento:  [enquadramento]
• Cores:          [colors]
• Iluminação:     [lightning]
• Formato:        [format] — [aspect_ratio]

Tudo correto? Posso publicar a campanha?
```

Só avançar para `create_campaign` após confirmação explícita do usuário. Se algum parâmetro precisar de correção, atualizar os CSVs antes de publicar.

---

### Após publicar: vincular IDs

```python
# Preencher campaign_id e adset_id após publicar
df_brief = pd.read_csv(BRIEFING_FILE)
mask = df_brief["campaign_name"] == "NOME_AQUI"
df_brief.loc[mask, "campaign_id"] = "ID_RETORNADO_PELA_API"
df_brief.loc[mask, "adset_id"]    = "ID_ADSET_RETORNADO"
df_brief.to_csv(BRIEFING_FILE, index=False)
print("IDs vinculados com sucesso")
```

---

## FASE 2 — Coleta de Métricas (após rodar)

### Buscar dados via meta-ads tools

```
1. mcp__meta-ads__get_account_info          → confirmar conta e account_id
2. mcp__meta-ads__list_campaigns            → listar todas as campanhas
3. mcp__meta-ads__get_campaign_insights     → métricas por campanha (impressões, cliques, gasto, CTR, CPC, CPM)
4. mcp__meta-ads__list_ad_sets              → conjuntos de anúncios de cada campanha
5. mcp__meta-ads__get_ad_set_insights       → métricas por ad set
6. mcp__meta-ads__list_ads                  → anúncios individuais
7. mcp__meta-ads__get_ad_insights           → métricas por anúncio (para cruzar com criativos)
```

### Código: montar DataFrame de resultados

```python
import pandas as pd, json

# Exemplo de estrutura retornada pelas tools (adaptar ao output real)
# Cada insights call retorna: impressions, clicks, spend, ctr, cpc, cpm, reach, conversions

resultados = [
    {
        "campaign_id": "120247316733860600",
        "campaign_name": "Campanha Nike",
        "impressions": 45000,
        "clicks": 810,
        "spend": 315.00,
        "ctr": 1.80,
        "cpc": 0.39,
        "cpm": 7.00,
        "reach": 38000,
        "conversions": 32,
        "date_preset": "last_30d"
    },
    # ... demais campanhas
]

df_results = pd.DataFrame(resultados)

# Métricas derivadas
df_results["cpl"] = (df_results["spend"] / df_results["conversions"].replace(0, float("nan"))).round(2)
df_results["conversion_rate"] = (df_results["conversions"] / df_results["clicks"].replace(0, float("nan")) * 100).round(2)
df_results["roas_proxy"] = None  # preencher se tiver receita

print(df_results.to_string())
df_results.to_csv("campaign_results.csv", index=False)
```

---

## FASE 3 — Cruzamento Parâmetros × Métricas

```python
import pandas as pd
import numpy as np

df_brief   = pd.read_csv("campaign_briefing.csv")
df_results = pd.read_csv("campaign_results.csv")

# Merge por campaign_id
df = pd.merge(df_brief, df_results, on="campaign_id", how="inner")

print(f"Campanhas com dados completos: {len(df)}")

# ── Análise por variável qualitativa ────────────────────────────────────────
# Quais parâmetros estão associados a melhores métricas?

categorical_params = ["archetype", "target_public", "pain_ambition", "channels", "segmentation"]

for param in categorical_params:
    if param not in df.columns or df[param].nunique() < 2:
        continue
    group = df.groupby(param).agg(
        n=("campaign_id", "count"),
        cpm_medio=("cpm", "mean"),
        cpl_medio=("cpl", "mean"),
        ctr_medio=("ctr", "mean"),
        spend_total=("spend", "sum"),
    ).round(2).sort_values("cpl_medio")
    print(f"\n=== Por {param.upper()} ===")
    print(group.to_string())

# ── Análise de impacto de escala ─────────────────────────────────────────────
# Diferença de CPM: quanto isso representa em escala?
print("\n=== ANÁLISE DE ESCALA ===")
if len(df) >= 2:
    df_sorted = df.sort_values("cpm")
    melhor_cpm  = df_sorted["cpm"].iloc[0]
    pior_cpm    = df_sorted["cpm"].iloc[-1]
    diff_cpm    = pior_cpm - melhor_cpm

    # Se escalar para R$ 1.000/dia por 30 dias:
    budget_escala  = 30_000  # R$
    impressoes_melhor = budget_escala / melhor_cpm * 1000
    impressoes_pior   = budget_escala / pior_cpm   * 1000
    diff_impressoes   = impressoes_melhor - impressoes_pior

    print(f"Melhor CPM:      R$ {melhor_cpm:.2f} ({df_sorted['campaign_name'].iloc[0]})")
    print(f"Pior CPM:        R$ {pior_cpm:.2f} ({df_sorted['campaign_name'].iloc[-1]})")
    print(f"Diferença CPM:   R$ {diff_cpm:.2f}")
    print(f"\nEm escala de R$ {budget_escala:,.0f} investidos:")
    print(f"  Melhor → {impressoes_melhor:,.0f} impressões")
    print(f"  Pior   → {impressoes_pior:,.0f} impressões")
    print(f"  Delta  → +{diff_impressoes:,.0f} impressões desperdiçadas na campanha mais cara")

    # E em leads?
    ctr_medio = df["ctr"].mean() / 100
    cvr_medio = df["conversion_rate"].mean() / 100 if "conversion_rate" in df.columns else 0.03
    leads_delta = diff_impressoes * ctr_medio * cvr_medio
    print(f"  Delta em leads (estimado): {leads_delta:,.0f} leads a mais na campanha mais barata")
```

---

## FASE 4 — Relatório HTML

```python
import pandas as pd, json, datetime

df = pd.read_csv("campaign_results.csv")
df_brief = pd.read_csv("campaign_briefing.csv")
df_merged = pd.merge(df_brief, df, on="campaign_id", how="inner") if "campaign_id" in df_brief.columns else df

now = datetime.datetime.now().strftime("%d/%m/%Y %H:%M")

# Serializar dados para Chart.js
labels    = json.dumps(df["campaign_name"].tolist())
cpm_data  = json.dumps(df["cpm"].tolist())
ctr_data  = json.dumps(df["ctr"].tolist())
cpl_data  = json.dumps(df["cpl"].fillna(0).tolist())
spend_data = json.dumps(df["spend"].tolist())

# Tabela de parâmetros cruzados
def df_to_html_table(df, cols):
    rows = ""
    for _, row in df[cols].iterrows():
        rows += "<tr>" + "".join(f"<td>{v}</td>" for v in row) + "</tr>"
    headers = "".join(f"<th>{c}</th>" for c in cols)
    return f"<table><thead><tr>{headers}</tr></thead><tbody>{rows}</tbody></table>"

param_cols = ["campaign_name_x", "archetype", "target_public", "pain_ambition", "cpm", "ctr", "cpl"]
param_cols_available = [c for c in param_cols if c in df_merged.columns]

html = f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<title>Paid Campaign Report</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: 'Inter', sans-serif; background: #0f172a; color: #e2e8f0; padding: 24px; }}
  h1 {{ font-size: 1.6rem; font-weight: 700; color: #f8fafc; margin-bottom: 4px; }}
  .subtitle {{ color: #94a3b8; font-size: 0.85rem; margin-bottom: 32px; }}
  .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 20px; margin-bottom: 32px; }}
  .card {{ background: #1e293b; border-radius: 12px; padding: 20px; border: 1px solid #334155; }}
  .card h2 {{ font-size: 0.9rem; font-weight: 600; color: #94a3b8; text-transform: uppercase; letter-spacing: .05em; margin-bottom: 12px; }}
  .kpi-grid {{ display: grid; grid-template-columns: repeat(2, 1fr); gap: 12px; margin-bottom: 32px; }}
  .kpi {{ background: #1e293b; border-radius: 10px; padding: 16px 20px; border: 1px solid #334155; }}
  .kpi .label {{ font-size: 0.75rem; color: #64748b; margin-bottom: 4px; }}
  .kpi .value {{ font-size: 1.5rem; font-weight: 700; color: #f1f5f9; }}
  .kpi .delta {{ font-size: 0.78rem; margin-top: 4px; }}
  .delta.good {{ color: #4ade80; }}
  .delta.bad  {{ color: #f87171; }}
  .scale-box {{ background: #1e293b; border: 1px solid #f59e0b44; border-radius: 12px; padding: 20px; margin-bottom: 32px; }}
  .scale-box h2 {{ color: #f59e0b; font-size: 1rem; margin-bottom: 12px; }}
  .scale-box p {{ color: #cbd5e1; font-size: 0.9rem; line-height: 1.6; }}
  .scale-box .highlight {{ color: #fbbf24; font-weight: 700; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 0.82rem; }}
  th {{ background: #0f172a; color: #94a3b8; padding: 8px 12px; text-align: left; font-weight: 600; border-bottom: 1px solid #334155; }}
  td {{ padding: 8px 12px; border-bottom: 1px solid #1e293b; color: #cbd5e1; }}
  tr:hover td {{ background: #1e293b; }}
  .tag {{ display: inline-block; background: #334155; border-radius: 4px; padding: 2px 6px; font-size: 0.72rem; color: #94a3b8; }}
</style>
</head>
<body>

<h1>📊 Paid Campaign Report</h1>
<p class="subtitle">Gerado em {now} · {len(df)} campanha(s) analisada(s)</p>

<div class="kpi-grid">
  <div class="kpi">
    <div class="label">Investimento Total</div>
    <div class="value">R$ {df["spend"].sum():,.2f}</div>
  </div>
  <div class="kpi">
    <div class="label">CPM Médio</div>
    <div class="value">R$ {df["cpm"].mean():.2f}</div>
    <div class="delta bad">Variação: R$ {df["cpm"].max() - df["cpm"].min():.2f} entre campanhas</div>
  </div>
  <div class="kpi">
    <div class="label">CTR Médio</div>
    <div class="value">{df["ctr"].mean():.2f}%</div>
  </div>
  <div class="kpi">
    <div class="label">CPL Médio</div>
    <div class="value">R$ {df["cpl"].mean():.2f}</div>
  </div>
</div>

<div class="grid">
  <div class="card">
    <h2>CPM por Campanha</h2>
    <canvas id="cpmChart"></canvas>
  </div>
  <div class="card">
    <h2>CTR por Campanha</h2>
    <canvas id="ctrChart"></canvas>
  </div>
  <div class="card">
    <h2>CPL por Campanha</h2>
    <canvas id="cplChart"></canvas>
  </div>
  <div class="card">
    <h2>Gasto por Campanha (R$)</h2>
    <canvas id="spendChart"></canvas>
  </div>
</div>

<div class="scale-box">
  <h2>⚡ Impacto de Escala</h2>
  <p>
    Uma diferença de <span class="highlight">R$ {df["cpm"].max() - df["cpm"].min():.2f} de CPM</span>
    entre a melhor e a pior campanha pode parecer pequena agora.
    Mas em um investimento de <span class="highlight">R$ 30.000/mês</span>,
    a campanha mais barata entrega
    <span class="highlight">{(30000 / max(df["cpm"].min(), 0.01) * 1000):,.0f} impressões</span>
    contra
    <span class="highlight">{(30000 / max(df["cpm"].max(), 0.01) * 1000):,.0f} impressões</span>
    da mais cara —
    uma diferença de
    <span class="highlight">{abs(30000 / max(df["cpm"].min(), 0.01) * 1000 - 30000 / max(df["cpm"].max(), 0.01) * 1000):,.0f} impressões</span>
    com o mesmo orçamento.
  </p>
</div>

<div class="card" style="margin-bottom: 32px;">
  <h2>Parâmetros Cruzados com Métricas</h2>
  {df_to_html_table(df_merged, param_cols_available) if param_cols_available else "<p style='color:#64748b'>Sem parâmetros de briefing vinculados ainda.</p>"}
</div>

<script>
const LABELS = {labels};
const colors = ["#6366f1","#22d3ee","#f59e0b","#4ade80","#f87171","#a78bfa","#fb923c"];
function barChart(id, data, label, prefix="", suffix="") {{
  new Chart(document.getElementById(id), {{
    type: "bar",
    data: {{
      labels: LABELS,
      datasets: [{{ label, data, backgroundColor: colors, borderRadius: 6 }}]
    }},
    options: {{
      responsive: true,
      plugins: {{
        legend: {{ display: false }},
        tooltip: {{ callbacks: {{ label: ctx => prefix + ctx.parsed.y.toFixed(2) + suffix }} }}
      }},
      scales: {{
        x: {{ ticks: {{ color: "#94a3b8", font: {{ size: 11 }} }}, grid: {{ color: "#1e293b" }} }},
        y: {{ ticks: {{ color: "#94a3b8" }}, grid: {{ color: "#334155" }} }}
      }}
    }}
  }});
}}
barChart("cpmChart",   {cpm_data},   "CPM",   "R$ ");
barChart("ctrChart",   {ctr_data},   "CTR",   "",   "%");
barChart("cplChart",   {cpl_data},   "CPL",   "R$ ");
barChart("spendChart", {spend_data}, "Gasto", "R$ ");
</script>
</body>
</html>"""

with open("paid_campaign_report.html", "w", encoding="utf-8") as f:
    f.write(html)
print("Relatório salvo: paid_campaign_report.html")
```

---

## Roteiro Completo — Do Zero ao Relatório

```
ETAPA 1 — Antes de publicar
  → Coletar parâmetros via quiz ou coleta direta
  → Salvar campaign_briefing.csv e creative_params.csv no terminal
  → Criar campanhas via mcp__meta-ads__create_campaign
  → Vincular IDs retornados às tabelas

ETAPA 2 — Após período de teste (mínimo 7 dias, ideal 14-21 dias)
  → mcp__meta-ads__list_campaigns + insights por campanha
  → mcp__meta-ads__list_ad_sets + insights por ad set
  → mcp__meta-ads__list_ads + insights por anúncio
  → Montar campaign_results.csv no terminal

ETAPA 3 — Análise
  → Merge briefing × results
  → Calcular CPM, CTR, CPL, CPA
  → Agrupar por parâmetro qualitativo (archetype, trigger, canal...)
  → Calcular impacto de escala para cada diferença identificada

ETAPA 4 — Relatório
  → Gerar paid_campaign_report.html
  → Destacar: melhor criativo, melhor público, pior CPM, diferencial de escala
  → Recomendar: o que pausar, o que escalar, o que testar a seguir

ETAPA 5 — Geração de hipóteses e próximos testes (FASE 5 abaixo)
  → Calcular ganho marginal por camada do funil
  → Determinar qual camada está "esgotada" e qual é a próxima prioridade
  → Gerar hipóteses concretas e sugerir testes A/B na ordem correta
```

---

## Quiz Inicial

Quando o usuário pede análise de campanha sem dados prontos:

```
quiz([
  {"question": "Qual é o momento atual?",
   "options": [
     "Quero parametrizar campanhas ANTES de publicar",
     "Campanhas já rodaram — quero analisar os resultados",
     "Quero fazer os dois (parametrizar novas + analisar antigas)"
   ]},
  {"question": "Você tem o briefing das campanhas (arquétipo, público, gatilhos)?",
   "options": ["Sim, vou descrever agora", "Não — me ajude a montar"]},
  {"question": "Qual período de dados da Meta Ads?",
   "options": ["Últimos 7 dias", "Últimos 30 dias", "Últimos 90 dias", "Definir manualmente"]}
])
```

---

## Alertas de Qualidade de Amostra

Antes de qualquer conclusão, verificar se os dados têm amostra suficiente. Os limiares abaixo refletem o mínimo estatístico por métrica — **não são intercambiáveis**:

| Métrica | Amostra mínima por variação | Justificativa |
|---|---|---|
| **CPM** | ~2.000–5.000 impressões | CPM é média de custo — converge rápido, mas < 2k ainda tem alta variância por leilão |
| **CTR** | ~100 cliques (~5k–10k impressões a CTR de 1–2%) | Teste binomial: ~100 eventos/variação detecta diferença de 20% com 80% de poder (p < 0,05) |
| **CVR / CPL** | ~50–100 conversões/variação | Meta exige 50 conversões/semana para sair da fase de aprendizado; < 50 significa que o algoritmo ainda está otimizando |

> **Nota sobre "1.000 pessoas":** Esse número é popularmente usado como regra geral, mas só é válido como floor de CPM. Para CTR ou CVR, 1.000 impressões geralmente resulta em 10–20 cliques e 0–5 conversões — amostra insuficiente para qualquer conclusão.

```python
# Amostra mínima por métrica — alertas automáticos
for _, row in df.iterrows():
    alertas = []
    if row["impressions"] < 2000:
        alertas.append("⚠️ <2.000 impressões — CPM instável (ruído de leilão)")
    elif row["impressions"] < 5000:
        alertas.append("⚡ 2k–5k impressões — CPM aceitável, mas confirmar tendência")
    if row["clicks"] < 100:
        alertas.append(f"⚠️ <100 cliques ({row['clicks']:.0f}) — CTR não confiável para decisão")
    convs = row.get("conversions", 0)
    if convs < 50:
        alertas.append(f"⚠️ <50 conversões ({convs:.0f}) — CPL/CVR dentro da fase de aprendizado do Meta")
    elif convs < 100:
        alertas.append(f"⚡ 50–100 conversões — CPL confiável, CVR ainda pode oscilar")
    if alertas:
        print(f"[{row['campaign_name']}]")
        for a in alertas:
            print(f"  {a}")
```

> Uma diferença de R$ 5 de CPM com 500 impressões pode ser ruído de leilão — ou pode representar dezenas de milhares de impressões desperdiçadas em escala. Sempre comunicar o nível de confiança **por métrica** antes de recomendar pausar, escalar ou declarar um vencedor.

---

---

## FASE 5 — Geração de Hipóteses e Próximos Testes

### A Hierarquia de Ganho Marginal no Funil

Antes de sugerir qualquer teste, calcular onde está o maior ganho marginal. A ordem é sempre do topo do funil para baixo — porque melhorar a camada mais alta multiplica o efeito de todas as camadas abaixo.

```
FUNIL DE TRÁFEGO PAGO — hierarquia de impacto:

[IMPRESSÃO]
     ↓  → CPM: quanto custa aparecer?
[CRIATIVO VISUAL]          ← CAMADA 1 — maior ganho marginal
  Imagem/Vídeo: stop no scroll, qualidade visual, has_people, formato
     ↓  → CTR inicial (thumb-stop rate, hook rate)
[HOOK / TÍTULO]            ← CAMADA 2
  Primeira linha de texto sobreposta ou headline estático
     ↓  → CTR qualificado
[SUBTÍTULO / BODY COPY]   ← CAMADA 3
  Apoia o hook, quebra objeção, amplifica desejo
     ↓  → CTR para o CTA
[CTA DO CRIATIVO]          ← CAMADA 4
  Texto/botão no próprio criativo (ex: "Garanta já", "Ver mais")
     ↓  → Clique
[CTA / TEXTO DO ANÚNCIO]  ← CAMADA 5 (Meta/Google Ads)
  Primary text, headline do ad, botão CTA da plataforma
     ↓  → Chegada na LP
[LANDING PAGE]             ← CAMADA 6 — menor ganho marginal por impressão
  Headline, prova social, formulário, pricing, A/B na LP
     ↓
[CONVERSÃO]
```

> **Regra de ouro:** Não avance para a Camada N+1 enquanto houver hipóteses relevantes ainda não testadas na Camada N com amostra suficiente. Uma mudança na imagem tem 10x mais impacto que ajustar o botão CTA da plataforma.

---

### Código: Calcular Ganho Marginal por Camada

```python
import pandas as pd
import numpy as np

df = pd.read_csv("campaign_results.csv")

# Métricas por camada do funil
impressions_total = df["impressions"].sum()
clicks_total      = df["clicks"].sum()
conversions_total = df["conversions"].sum()
spend_total       = df["spend"].sum()

ctr_atual  = clicks_total / impressions_total * 100
cvr_atual  = conversions_total / clicks_total * 100 if clicks_total > 0 else 0
cpl_atual  = spend_total / conversions_total if conversions_total > 0 else float("inf")
cpm_medio  = df["cpm"].mean()

print(f"=== ESTADO ATUAL ===")
print(f"Impressões: {impressions_total:,.0f}")
print(f"Cliques:    {clicks_total:,.0f}")
print(f"Conversões: {conversions_total:,.0f}")
print(f"CTR:        {ctr_atual:.2f}%")
print(f"CVR:        {cvr_atual:.2f}%")
print(f"CPL:        R$ {cpl_atual:.2f}")
print(f"CPM médio:  R$ {cpm_medio:.2f}")

# Simular melhoria de +X% em cada camada — impacto nas conversões finais
BUDGET = spend_total  # mesmo investimento

def simular_melhoria(camada, melhoria_pct):
    """Quanto ganho em conversões se melhorar X% nessa camada?"""
    if camada == "CPM":
        # CPM menor → mais impressões com mesmo budget
        novo_cpm = cpm_medio * (1 - melhoria_pct / 100)
        novas_imp = BUDGET / novo_cpm * 1000
        novas_conv = novas_imp * (ctr_atual / 100) * (cvr_atual / 100)
    elif camada == "CTR":
        # CTR maior → mais cliques
        novo_ctr = ctr_atual * (1 + melhoria_pct / 100)
        novas_conv = impressions_total * (novo_ctr / 100) * (cvr_atual / 100)
    elif camada == "CVR":
        # CVR maior → mais conversões por clique (LP ou CTA)
        novo_cvr = cvr_atual * (1 + melhoria_pct / 100)
        novas_conv = impressions_total * (ctr_atual / 100) * (novo_cvr / 100)
    else:
        novas_conv = conversions_total
    delta = novas_conv - conversions_total
    return novas_conv, delta

print(f"\n=== GANHO MARGINAL POR CAMADA (melhoria de 20%) ===")
camadas = {
    "Criativo visual (CPM -20%)":   ("CPM", 20),
    "Hook/Título (CTR +20%)":       ("CTR", 20),
    "Subtítulo/Copy (CTR +10%)":    ("CTR", 10),
    "CTA do criativo (CTR +5%)":    ("CTR",  5),
    "CTA/Texto do anúncio (CTR +3%)": ("CTR", 3),
    "Landing Page (CVR +20%)":      ("CVR", 20),
}
resultados_marginal = []
for nome, (metrica, perc) in camadas.items():
    novas_conv, delta = simular_melhoria(metrica, perc)
    resultados_marginal.append({
        "camada": nome,
        "conversoes_atual": conversions_total,
        "conversoes_novo": round(novas_conv, 1),
        "delta_conversoes": round(delta, 1),
        "delta_pct": round(delta / conversions_total * 100, 1) if conversions_total > 0 else 0,
    })

df_marginal = pd.DataFrame(resultados_marginal).sort_values("delta_conversoes", ascending=False)
print(df_marginal.to_string(index=False))

print(f"\n🔴 PRIORIDADE #1: {df_marginal.iloc[0]['camada']}")
print(f"   Potencial: +{df_marginal.iloc[0]['delta_conversoes']:.1f} conversões (+{df_marginal.iloc[0]['delta_pct']:.1f}%) com mesmo investimento")
```

---

### Critério para "Esgotar" uma Camada

Antes de descer para a próxima camada, verificar:

```python
# Uma camada está "esgotada" quando:
CRITERIOS_ESGOTAMENTO = {
    "Criativo visual": [
        "Testou has_people=True vs False (com amostra ≥ 500 imp cada)",
        "Testou ao menos 3 formatos diferentes (imagem, carrossel, vídeo)",
        "Testou ao menos 2 enquadramentos diferentes",
        "Testou alto contraste vs contraste médio",
        "Testou ao menos 2 paletas de cores distintas",
        "O melhor criativo tem CTR > benchmark do segmento E CPM estável",
    ],
    "Hook / Título": [
        "Testou ao menos 3 hooks diferentes (dor vs ambição vs curiosidade vs prova social)",
        "Testou pergunta vs afirmação vs número vs negação",
        "O melhor hook tem CTR ≥ 20% maior que o pior com amostra ≥ 200 cliques",
    ],
    "Subtítulo / Body Copy": [
        "Testou copy curta vs longa",
        "Testou foco em dor vs foco em resultado vs foco em prova social",
        "Impacto no CTR < 5% entre variações — camada menos sensível",
    ],
    "CTA do criativo": [
        "Testou ao menos 2 CTAs diferentes",
        "Delta de CTR < 3% entre variações — pode avançar",
    ],
    "CTA / Texto do anúncio": [
        "Testou ao menos 2 primary texts diferentes",
        "Testou ao menos 2 botões CTA da plataforma",
        "Delta de CTR < 5% entre variações",
    ],
    "Landing Page": [
        "Testou headline da LP (A/B formal com ferramenta)",
        "Testou com e sem prova social acima da dobra",
        "Testou formulário curto vs longo",
        "Testou pricing page com e sem âncora de preço",
        "CVR estável com amostra ≥ 100 conversões por variação",
    ],
}

# Imprimir checklist de esgotamento
for camada, criterios in CRITERIOS_ESGOTAMENTO.items():
    print(f"\n{'='*50}")
    print(f"CAMADA: {camada}")
    for c in criterios:
        print(f"  [ ] {c}")
```

---

### Código: Gerar Hipóteses Automaticamente

```python
import pandas as pd

df_brief   = pd.read_csv("campaign_briefing.csv")
df_creative = pd.read_csv("creative_params.csv")
df_results = pd.read_csv("campaign_results.csv")

df = pd.merge(df_brief, df_results, on="campaign_id", how="inner")
df_c = pd.merge(df_creative, df_results, on="ad_id", how="inner") if "ad_id" in df_creative.columns else pd.DataFrame()

hipoteses = []

# ── CAMADA 1: Criativo Visual ────────────────────────────────────────────────
if not df_c.empty and "creative_has_people" in df_c.columns:
    group = df_c.groupby("creative_has_people")["ctr"].mean()
    if len(group) == 1:
        tem_pessoas = group.index[0]
        hipoteses.append({
            "camada": "1 — Criativo Visual",
            "hipotese": f"Só testamos criativos com pessoas={tem_pessoas}. Testar o oposto pode revelar ganho significativo de CTR.",
            "variavel": "creative_has_people",
            "acao": f"Criar variação com has_people={'True' if tem_pessoas == 'False' else 'False'}",
            "metrica_alvo": "CTR",
        })
    elif len(group) >= 2:
        melhor = group.idxmax()
        pior = group.idxmin()
        delta = (group[melhor] - group[pior]) / group[pior] * 100
        if delta > 15:
            hipoteses.append({
                "camada": "1 — Criativo Visual",
                "hipotese": f"Criativos com pessoas={melhor} têm CTR {delta:.0f}% maior. Hipótese: aprofundar — qual tipo de pessoa/contexto funciona melhor?",
                "variavel": "creative_has_people + camera_perspective",
                "acao": "Testar diferentes perspectivas/contextos dentro de has_people=True",
                "metrica_alvo": "CTR",
            })

if not df_c.empty and "colors" in df_c.columns and df_c["colors"].nunique() < 2:
    hipoteses.append({
        "camada": "1 — Criativo Visual",
        "hipotese": "Testamos apenas uma paleta de cores. Cores de alto contraste com o feed (não azul/branco) tendem a aumentar CPM negativo e CTR.",
        "variavel": "colors + contrast",
        "acao": "Testar variação com paleta oposta à atual (ex: se fundo claro, testar escuro intenso)",
        "metrica_alvo": "CTR / CPM",
    })

# ── CAMADA 2: Hook / Título ───────────────────────────────────────────────────
if not df_c.empty and "creative_title_hook" in df_c.columns:
    n_hooks_unicos = df_c["creative_title_hook"].nunique()
    if n_hooks_unicos < 3:
        hipoteses.append({
            "camada": "2 — Hook / Título",
            "hipotese": f"Apenas {n_hooks_unicos} hook(s) testado(s). Benchmark: mínimo 3 abordagens distintas antes de concluir.",
            "variavel": "creative_title_hook",
            "acao": "Testar: (1) hook de dor direta, (2) hook de resultado/ambição, (3) hook com número/dado, (4) hook de pergunta provocativa",
            "metrica_alvo": "CTR",
        })

# ── CAMADA 3: Segmentação / Público ──────────────────────────────────────────
if "segmentation" in df.columns and df["segmentation"].nunique() < 2:
    hipoteses.append({
        "camada": "3 — Segmentação",
        "hipotese": "Testamos apenas uma segmentação. Hipótese: audiência diferente pode ter CPM menor com qualidade igual ou superior.",
        "variavel": "segmentation",
        "acao": "Testar Lookalike 1% vs 3% vs interesse aberto vs retargeting",
        "metrica_alvo": "CPM / CPL",
    })

# ── CAMADA 5: Ad Text / CTA da plataforma ────────────────────────────────────
if "ads_cta_button" in df_c.columns if not df_c.empty else False:
    n_ctas = df_c["ads_cta_button"].nunique()
    if n_ctas < 2:
        hipoteses.append({
            "camada": "5 — CTA Plataforma",
            "hipotese": "Apenas 1 CTA de plataforma testado. Baixo ganho marginal esperado, mas vale testar após esgotar camadas superiores.",
            "variavel": "ads_cta_button",
            "acao": "Testar LEARN_MORE vs SIGN_UP vs SHOP_NOW vs GET_QUOTE",
            "metrica_alvo": "CTR",
        })

# ── Ordenar por camada (menor número = maior prioridade) ─────────────────────
df_hip = pd.DataFrame(hipoteses)
if not df_hip.empty:
    df_hip = df_hip.sort_values("camada")
    print("=== HIPÓTESES GERADAS — PRÓXIMOS TESTES ===")
    print(f"Total: {len(df_hip)} hipóteses ordenadas por prioridade\n")
    for i, row in df_hip.iterrows():
        print(f"[{row['camada']}]")
        print(f"  Hipótese: {row['hipotese']}")
        print(f"  Ação:     {row['acao']}")
        print(f"  Métrica:  {row['metrica_alvo']}")
        print()
    df_hip.to_csv("next_tests.csv", index=False)
    print("Exportado: next_tests.csv")
else:
    print("Nenhuma hipótese automática gerada — revisar manualmente o checklist de esgotamento.")
```

---

### Template: Registrar Nova Hipótese Manualmente

Quando o agente ou o usuário identifica uma hipótese que não foi gerada automaticamente:

```python
# Adicionar ao next_tests.csv
nova_hipotese = {
    "camada": "1 — Criativo Visual",
    "hipotese": "Criativos com pessoas em movimento (vídeo 3s) vs. estáticos tiveram CTR diferente — hipótese: movimento aumenta thumb-stop rate",
    "variavel": "format + creative_has_people",
    "acao": "Testar reels curtos (3-5s) com a mesma pessoa/produto vs. imagem estática equivalente",
    "metrica_alvo": "CTR / CPM",
    "status": "pendente",
    "priority": 1,
}
```

---

### Convenção de Nomenclatura para Testes

Para facilitar o cruzamento futuro, nomear as campanhas/ads de teste com a variável sendo testada:

```
[PROJETO]_[CAMADA]_[VARIAVEL]_[VALOR]_[VERSAO]

Exemplos:
  Nike_C1_PEOPLE_yes_v1        → Criativo com pessoas, versão 1
  Nike_C1_PEOPLE_no_v1         → Criativo sem pessoas, versão 1
  Nike_C2_HOOK_dor_v1          → Hook de dor direta
  Nike_C2_HOOK_ambicao_v1      → Hook de ambição
  Nike_C5_CTA_learnmore_v1     → CTA "Saiba mais"
  Nike_C6_LP_headline_A        → LP variação A (headline curto)
  Nike_C6_LP_headline_B        → LP variação B (headline longo + prova social)
```

Isso garante que ao vincular o `campaign_id` / `ad_id` à tabela de parâmetros, o nome já carrega contexto suficiente para análise posterior.

---

### A/B Testing na Landing Page (Camada 6)

Só iniciar LP tests após esgotar as camadas 1-5. A LP tem menor ganho marginal por impressão, mas pode ser decisiva quando o CTR já está otimizado e o CVR ainda está baixo.

```
Variáveis de LP para testar, em ordem de impacto esperado:

1. Headline acima da dobra
   → Testar: problema direto vs. resultado vs. número vs. pergunta
   → Ferramenta: Google Optimize / VWO / Hotjar + split de UTM por anúncio

2. Prova social (posição e formato)
   → Testar: depoimento com foto vs. número de clientes vs. sem prova social acima da dobra
   → Métricas: CVR + scroll depth

3. Formulário / CTA principal
   → Testar: formulário curto (nome + email) vs. longo (+ telefone + segmento)
   → Número de campos tem impacto direto no CVR

4. Âncora de preço
   → Testar: mostrar preço vs. ocultar (levar para ligação/conversa)
   → Testar: preço anual vs. mensal em destaque

5. Velocidade e mobile
   → Verificar: LCP < 2.5s, FID < 100ms, CLS < 0.1
   → Um LCP ruim pode derrubar o CVR independente do conteúdo
```

> **Atenção:** Para A/B na LP ser estatisticamente válido, cada variação precisa de ao menos 100 conversões. Com volume baixo, use mudanças radicais (não sutis) para detectar diferença com amostra menor.

---

## Regras de Ouro

| FAZER | NÃO FAZER |
|---|---|
| Parametrizar ANTES de publicar | Tentar reconstruir parâmetros depois |
| Alertar sobre amostra insuficiente (<30 conversões) | Tirar conclusões com poucos dados |
| Calcular impacto de escala para toda diferença identificada | Apresentar métricas sem contexto de escala |
| Cruzar parâmetros qualitativos × métricas quantitativas | Analisar só o número sem entender o porquê |
| Usar `terminal` para análise — não inventar dados | Simular ou estimar métricas sem fonte |
| Vincular IDs reais após publicar | Deixar campos vazios sem vinculação |
| Recomendar ação específica (pausar X, escalar Y, testar Z) | Terminar com "depende do objetivo" |
| Comunicar nível de confiança da análise | Afirmar causalidade em testes iniciais |
| **Seguir a hierarquia de camadas — esgotar C1 antes de C2** | **Otimizar CTA da LP enquanto o criativo ainda não foi testado** |
| **Calcular ganho marginal antes de sugerir qualquer teste** | **Sugerir testes aleatórios sem priorização** |
| **Nomear campanhas com convenção [PROJ]_[CAMADA]_[VAR]_[VAL]** | **Nomes genéricos que impossibilitam cruzamento futuro** |
