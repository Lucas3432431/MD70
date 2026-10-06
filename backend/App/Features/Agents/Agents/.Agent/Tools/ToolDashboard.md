# Dashboard

> Gera dashboards, relatórios e visualizações interativas renderizadas diretamente no chat.
> Use quando precisar de gráficos, tabelas ricas, KPIs, funis, timelines ou qualquer layout visual estruturado.

## Sequência obrigatória

```
1. help(name="html")          ← carrega estas instruções
2. html(title="...", html="...")   ← gera o dashboard
```

---

## Ferramenta: `html`

```python
html(
  title="Nome do dashboard",
  html="<!DOCTYPE html><html>...</html>"
)
```

**Campos obrigatórios:**
- `title` — título exibido no card do chat
- `html` — HTML completo e auto-contido (com `<style>` e `<script>` inline)

**Retorno:** o frontend renderiza em um popup com iframe sandboxado.

---

## ⚠️ Regras críticas de aspas e escaping

### 1. O campo `html` é uma string Python — use aspas duplas no nível externo

```python
# ✅ Correto: aspas duplas externas, aspas simples nos atributos HTML
html(title="Relatório", html='<!DOCTYPE html><html><body><div class=\'container\'>...</div></body></html>')

# ❌ Errado: nunca misture aspas duplas dentro de aspas duplas sem escape
html(title="Relatório", html="<div class="container">")  # quebra o parser
```

### 2. Para HTML com muitas aspas — use string Python com aspas duplas externas e aspas simples nos atributos

```python
html(
  title="Dashboard de Vendas",
  html='<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
<style>
body { font-family: sans-serif; margin: 0; padding: 20px; background: #0a0a0a; color: #e2e8f0; }
</style>
</head>
<body>
<canvas id="chart"></canvas>
<script>
new Chart(document.getElementById("chart"), {
  type: "bar",
  data: { labels: ["Jan","Fev","Mar"], datasets: [{ label: "Vendas", data: [120,190,150] }] }
});
</script>
</body>
</html>'
)
```

### 3. Nunca use aspas duplas dentro do valor do campo `html` se as aspas externas forem duplas

Se o HTML contiver aspas duplas (ex: atributos JS), use aspas simples externas no Python:

```python
# ✅ Correto
html(title="KPIs", html='<div onclick="alert(\'ok\')">...</div>')

# ❌ Errado — confunde o parser da tool
html(title="KPIs", html="<div onclick="alert('ok')">...</div>")
```

---

## Bibliotecas disponíveis via CDN

Inclua no `<head>` do HTML. Não requerem autenticação.

| Biblioteca | CDN | Uso |
|---|---|---|
| Chart.js | `https://cdn.jsdelivr.net/npm/chart.js` | Gráficos (bar, line, pie, doughnut, radar) |
| ApexCharts | `https://cdn.jsdelivr.net/npm/apexcharts` | Gráficos avançados com animação |
| Tailwind CSS | `https://cdn.tailwindcss.com` | Estilização rápida e responsiva |
| D3.js | `https://cdn.jsdelivr.net/npm/d3` | Visualizações customizadas |
| Lucide Icons | `https://unpkg.com/lucide@latest` | Ícones SVG |

---

## Estrutura recomendada

> **Padrão visual:** use fundo preto (`#0a0a0a`) com texto claro e acentos coloridos vibrantes. Este é o estilo padrão esperado para todos os dashboards.

```html
<!DOCTYPE html>
<html lang="pt-BR">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <script src="https://cdn.tailwindcss.com"></script>
  <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
  <style>
    body { background: #0a0a0a; color: #e2e8f0; font-family: 'Inter', sans-serif; }
    .card { background: #111111; border: 1px solid #1e1e1e; border-radius: 12px; }
  </style>
</head>
<body class="p-6">

  <!-- Conteúdo do dashboard -->

  <script>
    // Scripts inline aqui
  </script>
</body>
</html>
```

---

## Exemplos prontos

### KPI Cards + Gráfico de barras

```python
html(
  title="Dashboard de Campanha",
  html='<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<script src="https://cdn.tailwindcss.com"></script>
<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
<style>
body { background: #0a0a0a; color: #e2e8f0; font-family: sans-serif; }
.card { background: #111111; border: 1px solid #1e1e1e; border-radius: 12px; padding: 20px; }
</style>
</head>
<body class="p-6">
  <h1 class="text-2xl font-bold text-white mb-6">Campanha Q1 2026</h1>

  <div class="grid grid-cols-3 gap-4 mb-8">
    <div class="card">
      <p class="text-xs text-gray-500 uppercase tracking-wider">Impressões</p>
      <p class="text-3xl font-bold text-blue-400 mt-1">124.5K</p>
      <p class="text-xs text-green-400 mt-1">▲ 12% vs mês anterior</p>
    </div>
    <div class="card">
      <p class="text-xs text-gray-500 uppercase tracking-wider">CTR</p>
      <p class="text-3xl font-bold text-purple-400 mt-1">3.2%</p>
      <p class="text-xs text-green-400 mt-1">▲ 0.4pp vs mês anterior</p>
    </div>
    <div class="card">
      <p class="text-xs text-gray-500 uppercase tracking-wider">CPA</p>
      <p class="text-3xl font-bold text-emerald-400 mt-1">R$ 18</p>
      <p class="text-xs text-red-400 mt-1">▼ Meta: R$ 15</p>
    </div>
  </div>

  <div class="card">
    <canvas id="chart" height="120"></canvas>
  </div>

  <script>
  new Chart(document.getElementById("chart"), {
    type: "bar",
    data: {
      labels: ["Jan", "Fev", "Mar"],
      datasets: [{
        label: "Vendas (R$)",
        data: [42000, 58000, 71000],
        backgroundColor: ["#3b82f6", "#8b5cf6", "#10b981"]
      }]
    },
    options: {
      plugins: { legend: { display: false } },
      scales: {
        y: { beginAtZero: true, grid: { color: "#1e1e1e" }, ticks: { color: "#94a3b8" } },
        x: { grid: { display: false }, ticks: { color: "#94a3b8" } }
      }
    }
  });
  </script>
</body>
</html>'
)
```

---

## Boas práticas

- **Auto-contido:** todo CSS e JS deve ser inline ou via CDN — sem importações que exijam build
- **Responsivo:** use `width: 100%` em canvas e containers
- **Dados reais:** popule os gráficos com os dados reais do contexto do usuário
- **Sem document.write():** não use — é bloqueado no sandbox
- **Sem fetch() para IPs internos:** sem `localhost`, `127.*`, `192.168.*`
- **Limite:** 512 KB de HTML
