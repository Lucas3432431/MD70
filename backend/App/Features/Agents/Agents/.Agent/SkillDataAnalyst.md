# 📊 Data Analyst Skill

**Objetivo:** Transformar dados brutos do usuário em insights acionáveis — análise exploratória, visualizações, testes estatísticos, modelos preditivos e relatórios — usando o ambiente Python isolado do `terminal`.

**Pré-requisitos:** Nenhum

**Disponível:** Imediatamente — basta o usuário ter dados (CSV, Excel, colagem de tabela ou descrição do problema)

**Saída:** Gráficos PNG (attachments), tabelas formatadas, relatório em `document()` ou dashboard em `html()`

---

## 🚀 Fluxo de Trabalho Obrigatório

```
1. Entender os dados e o objetivo (quiz ou leitura direta do arquivo)
2. EDA — exploração inicial obrigatória antes de qualquer análise
3. Análise principal (ver árvore de decisão abaixo)
4. Visualizações — salvas como PNG (attachments automáticos)
5. Conclusão acionável — não apenas números, mas "o que fazer com isso"
```

> ⚠️ **NUNCA pule a EDA.** Mesmo que o usuário peça um gráfico específico, rode `df.info()`, `df.describe()` e verifique nulos antes. Dados sujos produzem análises erradas.

> ✅ **Arquivos do usuário** ficam disponíveis em `user/` automaticamente — use `os.listdir("user/")` para listar o que foi enviado.

> ✅ **Arquivos gerados** (PNG, CSV, Excel) são automaticamente salvos como attachments do chat e retornados com `attachment_id` — use `vision(image_input="attach_xxx")` para referenciar gráficos gerados se precisar analisá-los.

---

## 🌳 Árvore de Decisão — Qual Análise Fazer

```
Usuário tem dados?
├── NÃO → Quiz para entender o objetivo e pedir o arquivo
└── SIM → EDA primeiro
         ├── "Quero entender meus dados" → EDA Completa
         ├── "Quero comparar grupos/períodos" → Teste de Hipótese / A/B Test
         ├── "Quero prever o futuro" → Forecasting (Prophet / ARIMA)
         ├── "Quero entender relações" → Correlação / Regressão
         ├── "Quero segmentar clientes" → Clustering (K-Means / PCA)
         ├── "Quero analisar campanha/marketing" → Análise de Marketing
         ├── "Quero análise financeira" → VPL / TIR / ROI / Amortização
         ├── "Quero detectar problemas" → Anomaly Detection
         └── "Quero um dashboard" → html() com Chart.js / ApexCharts
```

---

## 📋 Quiz Inicial (quando dados não foram enviados)

```
quiz([
  {"question": "O que você quer descobrir com esses dados?",
   "options": ["Entender o panorama geral (EDA)", "Comparar grupos ou períodos (A/B / hipótese)", "Prever tendências futuras", "Segmentar clientes ou produtos", "Análise financeira (ROI, VPL, TIR)", "Detectar anomalias ou outliers", "Outro — vou descrever"]},
  {"question": "Qual é o formato dos seus dados?", "attachment": true,
   "options": ["CSV / Excel — vou enviar o arquivo", "Colei a tabela no chat", "Não tenho arquivo — vou descrever os dados"]}
])
```

Se o usuário colou dados no chat ou descreveu, use `terminal` para reconstruí-los em memória:

```python
# Dados colados diretamente
import pandas as pd, io
csv_text = """col1,col2,col3
v1,v2,v3"""
df = pd.read_csv(io.StringIO(csv_text))
```

---

## 🔍 FASE 1 — EDA (Exploração Inicial — SEMPRE obrigatória)

```python
import pandas as pd
import numpy as np

# Ler arquivo do usuário (sempre prefira user/ para arquivos enviados)
import os
arquivos = os.listdir("user/")
print("Arquivos disponíveis:", arquivos)

# Detectar formato e ler
fname = "user/" + arquivos[0]
if fname.endswith(".xlsx") or fname.endswith(".xls"):
    df = pd.read_excel(fname)
else:
    # Tentar detectar separador automaticamente
    df = pd.read_csv(fname, sep=None, engine="python")

# ── Panorama ──────────────────────────────────────────────────────────────────
print("=== SHAPE ===")
print(df.shape)

print("\n=== TIPOS ===")
print(df.dtypes)

print("\n=== NULOS (%) ===")
print((df.isnull().sum() / len(df) * 100).sort_values(ascending=False).round(2))

print("\n=== ESTATÍSTICAS ===")
print(df.describe(include="all").T.to_string())

print("\n=== PRIMEIRAS LINHAS ===")
print(df.head(5).to_string())

# Colunas numéricas e categóricas
num_cols = df.select_dtypes(include="number").columns.tolist()
cat_cols = df.select_dtypes(include=["object", "category"]).columns.tolist()
print(f"\nNuméricas: {num_cols}")
print(f"Categóricas: {cat_cols}")
```

**Após EDA, comunicar ao usuário:**
- Quantas linhas/colunas
- Quais colunas têm mais nulos (e se precisam de tratamento)
- Tipo de dados detectados
- Quais análises fazem sentido com esses dados

---

## 📈 CASOS COMUNS

### C1 — Análise Descritiva + Gráfico de Barras / Linhas

Ideal para: "Quero ver o desempenho por canal / período / categoria"

```python
import pandas as pd
import seaborn as sns
import matplotlib.pyplot as plt

df = pd.read_csv("user/dados.csv")

# Agrupar e somar
resultado = df.groupby("canal")["receita"].sum().sort_values(ascending=False)
print(resultado.to_string())

# Gráfico de barras
fig, ax = plt.subplots(figsize=(10, 5))
resultado.plot(kind="bar", ax=ax, color="#4F46E5", edgecolor="white")
ax.set_title("Receita por Canal", fontsize=14, fontweight="bold")
ax.set_xlabel("")
ax.set_ylabel("Receita (R$)")
ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, _: f"R${x:,.0f}"))
for bar in ax.patches:
    ax.annotate(f"R${bar.get_height():,.0f}", (bar.get_x() + bar.get_width() / 2, bar.get_height()),
                ha="center", va="bottom", fontsize=9)
plt.tight_layout()
plt.savefig("receita_por_canal.png", dpi=150)
print("Gráfico salvo: receita_por_canal.png")
```

---

### C2 — Análise Temporal (série histórica)

Ideal para: "Quero ver evolução ao longo do tempo"

```python
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

df = pd.read_csv("user/historico.csv")
df["data"] = pd.to_datetime(df["data"])
df = df.sort_values("data")

# Agrupamento mensal
mensal = df.set_index("data").resample("ME")["valor"].sum().reset_index()

fig, ax = plt.subplots(figsize=(12, 5))
ax.plot(mensal["data"], mensal["valor"], marker="o", linewidth=2, color="#4F46E5")
ax.fill_between(mensal["data"], mensal["valor"], alpha=0.1, color="#4F46E5")
ax.xaxis.set_major_formatter(mdates.DateFormatter("%b/%Y"))
ax.xaxis.set_major_locator(mdates.MonthLocator())
plt.xticks(rotation=45)
ax.set_title("Evolução Mensal", fontsize=14, fontweight="bold")
ax.set_ylabel("Valor")
plt.tight_layout()
plt.savefig("serie_temporal.png", dpi=150)
print("Gráfico salvo: serie_temporal.png")
```

---

### C3 — Correlação entre Variáveis

Ideal para: "O que influencia mais X?" / "Essas variáveis estão relacionadas?"

```python
import pandas as pd
import seaborn as sns
import matplotlib.pyplot as plt

df = pd.read_csv("user/dados.csv")
num_df = df.select_dtypes(include="number")

# Matriz de correlação
corr = num_df.corr()
print("=== CORRELAÇÕES MAIS FORTES ===")
pairs = corr.abs().unstack().sort_values(ascending=False)
pairs = pairs[pairs < 1].drop_duplicates().head(10)
print(pairs.to_string())

# Heatmap
fig, ax = plt.subplots(figsize=(10, 8))
sns.heatmap(corr, annot=True, fmt=".2f", cmap="RdBu_r", center=0,
            vmin=-1, vmax=1, ax=ax, annot_kws={"size": 9})
ax.set_title("Matriz de Correlação", fontsize=14, fontweight="bold")
plt.tight_layout()
plt.savefig("correlacao.png", dpi=150)
print("Heatmap salvo: correlacao.png")
```

---

### C4 — Análise de Campanhas de Marketing

Ideal para: planilhas de Meta Ads, Google Ads, TikTok Ads

```python
import pandas as pd
import numpy as np

df = pd.read_csv("user/campanhas.csv")

# Calcular métricas padrão
df["CTR"] = (df["cliques"] / df["impressoes"] * 100).round(2)
df["CPC"] = (df["gasto"] / df["cliques"]).round(2)
df["CPA"] = (df["gasto"] / df["conversoes"]).round(2)
df["ROAS"] = (df["receita"] / df["gasto"]).round(2)

# Resumo por campanha
resumo = df.groupby("campanha").agg({
    "gasto": "sum",
    "impressoes": "sum",
    "cliques": "sum",
    "conversoes": "sum",
    "receita": "sum",
    "CTR": "mean",
    "CPA": "mean",
    "ROAS": "mean",
}).round(2)

from tabulate import tabulate
print(tabulate(resumo.reset_index(), headers="keys", tablefmt="simple", floatfmt=".2f"))

# Exportar
resumo.reset_index().to_csv("resumo_campanhas.csv", index=False)
print("Exportado: resumo_campanhas.csv")
```

---

### C5 — Comparação de Períodos (MoM, YoY)

```python
import pandas as pd

df = pd.read_csv("user/vendas.csv")
df["data"] = pd.to_datetime(df["data"])
df["mes"] = df["data"].dt.to_period("M")

mensal = df.groupby("mes")["receita"].sum().reset_index()
mensal["receita_anterior"] = mensal["receita"].shift(1)
mensal["variacao_pct"] = ((mensal["receita"] - mensal["receita_anterior"]) / mensal["receita_anterior"] * 100).round(1)
mensal["tendencia"] = mensal["variacao_pct"].apply(lambda x: "▲" if x > 0 else "▼" if x < 0 else "→")

from tabulate import tabulate
print(tabulate(mensal.tail(6).to_string()))
```

---

## 🔬 CASOS AVANÇADOS

### A1 — Teste A/B e Significância Estatística

Ideal para: experimentos de produto, campanhas, onboarding, pricing

```python
import pandas as pd
from scipy import stats
from statsmodels.stats.proportion import proportion_confint
import numpy as np

df = pd.read_csv("user/ab_test.csv")  # colunas: grupo, conversao (0/1)

controle = df[df["grupo"] == "controle"]["conversao"]
variante = df[df["grupo"] == "variante"]["conversao"]

# Taxas
taxa_c = controle.mean()
taxa_v = variante.mean()
uplift = (taxa_v - taxa_c) / taxa_c * 100

# Teste chi-quadrado (para proporções)
from scipy.stats import chi2_contingency
tabela = pd.crosstab(df["grupo"], df["conversao"])
chi2, p_value, dof, _ = chi2_contingency(tabela)

# Intervalos de confiança (95%)
ci_c = proportion_confint(controle.sum(), len(controle), alpha=0.05)
ci_v = proportion_confint(variante.sum(), len(variante), alpha=0.05)

print(f"=== RESULTADO DO TESTE A/B ===")
print(f"Controle:  {taxa_c:.2%}  IC95%: [{ci_c[0]:.2%}, {ci_c[1]:.2%}]  n={len(controle)}")
print(f"Variante:  {taxa_v:.2%}  IC95%: [{ci_v[0]:.2%}, {ci_v[1]:.2%}]  n={len(variante)}")
print(f"Uplift:    {uplift:+.1f}%")
print(f"p-value:   {p_value:.4f}")
print(f"Resultado: {'✅ SIGNIFICATIVO (p<0.05) — VARIANTE VENCE' if p_value < 0.05 else '⚠️ Não significativo — aguardar mais dados'}")

# Tamanho amostral necessário (para futuras iterações)
from statsmodels.stats.power import NormalIndPower
effect_size = abs(taxa_v - taxa_c) / np.sqrt(((taxa_c + taxa_v) / 2) * (1 - (taxa_c + taxa_v) / 2))
n_needed = NormalIndPower().solve_power(effect_size=effect_size, alpha=0.05, power=0.80)
print(f"Tamanho amostral mínimo recomendado (80% power): {int(n_needed * 2)} total ({int(n_needed)} por grupo)")
```

---

### A2 — Regressão Linear (Previsão e Impacto)

Ideal para: "O que afeta minha receita?" / "Qual seria o resultado se eu investir X?"

```python
import pandas as pd
import numpy as np
import statsmodels.api as sm
import matplotlib.pyplot as plt
import seaborn as sns

df = pd.read_csv("user/dados.csv")

# Variáveis — ajustar conforme os dados reais
X = df[["investimento", "sazonalidade", "concorrentes_ativos"]]
y = df["receita"]

X = sm.add_constant(X)
modelo = sm.OLS(y, X).fit()

print(modelo.summary())
print(f"\nR² = {modelo.rsquared:.3f} — o modelo explica {modelo.rsquared*100:.1f}% da variação na receita")
print(f"F-statistic p-value: {modelo.f_pvalue:.4f}")

# Coeficientes significativos
coefs = pd.DataFrame({"coeficiente": modelo.params, "p_value": modelo.pvalues})
coefs["significativo"] = coefs["p_value"] < 0.05
print("\n=== COEFICIENTES ===")
print(coefs.to_string())

# Gráfico: previsto vs real
fig, ax = plt.subplots(figsize=(8, 5))
ax.scatter(modelo.fittedvalues, y, alpha=0.5, color="#4F46E5")
ax.plot([y.min(), y.max()], [y.min(), y.max()], "r--", lw=2)
ax.set_xlabel("Previsto")
ax.set_ylabel("Real")
ax.set_title(f"Previsto vs Real (R²={modelo.rsquared:.3f})")
plt.tight_layout()
plt.savefig("regressao_previsto_real.png", dpi=150)
```

---

### A3 — Forecasting com Prophet

Ideal para: previsão de vendas, tráfego, demanda com sazonalidade

```python
import pandas as pd
from prophet import Prophet
import matplotlib.pyplot as plt

df = pd.read_csv("user/serie.csv")  # colunas: ds (data), y (valor)
df["ds"] = pd.to_datetime(df["ds"])

modelo = Prophet(
    yearly_seasonality=True,
    weekly_seasonality=True,
    daily_seasonality=False,
    changepoint_prior_scale=0.05,
)
modelo.fit(df)

# Prever próximos 90 dias
futuro = modelo.make_future_dataframe(periods=90)
previsao = modelo.predict(futuro)

# Resultado
resultado = previsao[["ds", "yhat", "yhat_lower", "yhat_upper"]].tail(90)
print(resultado.to_string(index=False))

# Gráfico
fig = modelo.plot(previsao, figsize=(12, 5))
fig.axes[0].set_title("Forecasting — Próximos 90 dias", fontsize=14, fontweight="bold")
plt.tight_layout()
fig.savefig("forecast.png", dpi=150)
print("Gráfico salvo: forecast.png")

# Componentes
fig2 = modelo.plot_components(previsao, figsize=(12, 8))
plt.tight_layout()
fig2.savefig("forecast_componentes.png", dpi=150)
print("Componentes salvos: forecast_componentes.png")
```

---

### A4 — Segmentação de Clientes (K-Means + PCA)

Ideal para: "Quais são os perfis de clientes?" / RFM / segmentação comportamental

```python
import pandas as pd
import numpy as np
from sklearn.preprocessing import StandardScaler
from sklearn.cluster import KMeans
from sklearn.decomposition import PCA
import matplotlib.pyplot as plt
import seaborn as sns

df = pd.read_csv("user/clientes.csv")

# Features numéricas para clustering
features = df.select_dtypes(include="number").dropna(axis=1)
scaler = StandardScaler()
X_scaled = scaler.fit_transform(features)

# Elbow method — encontrar número ideal de clusters
inertias = []
for k in range(2, 9):
    km = KMeans(n_clusters=k, n_init=10, random_state=42)
    km.fit(X_scaled)
    inertias.append(km.inertia_)

fig, ax = plt.subplots(figsize=(8, 4))
ax.plot(range(2, 9), inertias, marker="o", color="#4F46E5")
ax.set_title("Elbow Method — Número Ideal de Clusters")
ax.set_xlabel("K (clusters)")
ax.set_ylabel("Inércia")
plt.tight_layout()
plt.savefig("elbow.png", dpi=150)

# Cluster com K escolhido (ajustar após ver o elbow)
K = 4
km = KMeans(n_clusters=K, n_init=10, random_state=42)
df["cluster"] = km.fit_predict(X_scaled)

# Perfil de cada cluster
perfil = df.groupby("cluster")[features.columns].mean().round(2)
print("=== PERFIL DOS CLUSTERS ===")
print(perfil.to_string())
print(f"\nDistribuição: {df['cluster'].value_counts().sort_index().to_dict()}")

# Visualização 2D via PCA
pca = PCA(n_components=2)
coords = pca.fit_transform(X_scaled)
df["pca1"], df["pca2"] = coords[:, 0], coords[:, 1]

fig, ax = plt.subplots(figsize=(9, 6))
for c in range(K):
    mask = df["cluster"] == c
    ax.scatter(df.loc[mask, "pca1"], df.loc[mask, "pca2"], label=f"Cluster {c}", alpha=0.6, s=40)
ax.set_title(f"Segmentação de Clientes ({K} grupos) — PCA 2D")
ax.legend()
plt.tight_layout()
plt.savefig("clusters_pca.png", dpi=150)
print("Gráficos salvos: elbow.png, clusters_pca.png")

df.to_csv("clientes_segmentados.csv", index=False)
print("Exportado: clientes_segmentados.csv")
```

---

### A5 — Análise Financeira (VPL, TIR, Payback, ROI)

Ideal para: avaliação de projetos, investimentos, precificação

```python
import numpy as np
import numpy_financial as npf
import pandas as pd
from tabulate import tabulate

# ── VPL e TIR ─────────────────────────────────────────────────────────────────
fluxo = [-100_000, 30_000, 40_000, 45_000, 50_000, 55_000]  # substituir com dados reais
taxa = 0.12  # WACC ou taxa mínima de atratividade

vpl = npf.npv(taxa, fluxo)
tir = npf.irr(fluxo)
payback_simples = next((i for i, f in enumerate(np.cumsum(fluxo)) if f >= 0), None)

print(f"VPL (12% a.a.):    R$ {vpl:,.2f}  {'✅ VIÁVEL' if vpl > 0 else '❌ INVIÁVEL'}")
print(f"TIR:               {tir:.2%}")
print(f"Payback simples:   {payback_simples} período(s)")

# ── Amortização SAC ────────────────────────────────────────────────────────────
principal = 500_000
taxa_mes = 0.018
n_parcelas = 36

saldo = principal
tabela = []
for i in range(1, n_parcelas + 1):
    amort = principal / n_parcelas
    juros = saldo * taxa_mes
    parcela = amort + juros
    saldo -= amort
    tabela.append({"Mês": i, "Parcela": parcela, "Amortização": amort, "Juros": juros, "Saldo": max(saldo, 0)})

df_sac = pd.DataFrame(tabela)
print("\n=== TABELA SAC (primeiras e últimas 3 parcelas) ===")
preview = pd.concat([df_sac.head(3), df_sac.tail(3)])
print(tabulate(preview, headers="keys", tablefmt="simple", floatfmt=",.2f", showindex=False))
df_sac.to_csv("amortizacao_sac.csv", index=False)
print("\nExportado: amortizacao_sac.csv")
```

---

### A6 — Detecção de Anomalias

Ideal para: detectar fraudes, erros de lançamento, outliers operacionais

```python
import pandas as pd
import numpy as np
from sklearn.ensemble import IsolationForest
import matplotlib.pyplot as plt

df = pd.read_csv("user/transacoes.csv")
num_cols = df.select_dtypes(include="number").columns.tolist()
X = df[num_cols].fillna(df[num_cols].median())

# Isolation Forest
iso = IsolationForest(contamination=0.05, random_state=42)
df["anomalia"] = iso.fit_predict(X)
df["score_anomalia"] = iso.score_samples(X)

anomalias = df[df["anomalia"] == -1].sort_values("score_anomalia")
print(f"=== {len(anomalias)} ANOMALIAS DETECTADAS ({len(anomalias)/len(df):.1%} dos registros) ===")
print(anomalias.head(10).to_string())

# Método Z-Score para validação cruzada
from scipy import stats as scipy_stats
for col in num_cols[:3]:
    z_scores = np.abs(scipy_stats.zscore(df[col].dropna()))
    outliers_z = (z_scores > 3).sum()
    print(f"Z-Score outliers em '{col}': {outliers_z}")

# Exportar
anomalias.to_csv("anomalias_detectadas.csv", index=False)
print("Exportado: anomalias_detectadas.csv")
```

---

### A7 — Análise de Churn (Cohort + Retenção)

Ideal para: SaaS, apps, e-commerce com dados de clientes ao longo do tempo

```python
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns

df = pd.read_csv("user/usuarios.csv")  # colunas: user_id, data_ativacao, data_ultimo_acesso
df["data_ativacao"]      = pd.to_datetime(df["data_ativacao"])
df["data_ultimo_acesso"] = pd.to_datetime(df["data_ultimo_acesso"])

# Cohort mensal
df["cohort"] = df["data_ativacao"].dt.to_period("M")
df["periodo"] = ((df["data_ultimo_acesso"].dt.to_period("M") - df["cohort"]).apply(lambda x: x.n))

cohort_size = df.groupby("cohort")["user_id"].nunique()
retenção = df.groupby(["cohort", "periodo"])["user_id"].nunique().unstack(fill_value=0)
retenção_pct = retenção.divide(cohort_size, axis=0).round(3) * 100

# Heatmap de retenção
fig, ax = plt.subplots(figsize=(14, 7))
sns.heatmap(retenção_pct.iloc[:, :12], annot=True, fmt=".0f", cmap="YlGn",
            vmin=0, vmax=100, ax=ax, annot_kws={"size": 8})
ax.set_title("Cohort de Retenção (%) — Meses após Ativação", fontsize=13, fontweight="bold")
ax.set_xlabel("Meses após ativação")
ax.set_ylabel("Cohort de aquisição")
plt.tight_layout()
plt.savefig("cohort_retencao.png", dpi=150)
print("Heatmap salvo: cohort_retencao.png")

print(f"\nRetenção média M1: {retenção_pct.iloc[:, 1].mean():.1f}%")
print(f"Retenção média M3: {retenção_pct.iloc[:, 3].mean():.1f}%")
print(f"Retenção média M6: {retenção_pct.iloc[:, 6].mean():.1f}%")
```

---

### A8 — SQL Analítico com DuckDB

Ideal para: usuários que preferem SQL, múltiplos arquivos, queries complexas

```python
import duckdb
import pandas as pd
import matplotlib.pyplot as plt

# DuckDB lê CSV/Parquet diretamente, sem precisar carregar em memória
con = duckdb.connect()

# Registrar CSVs
resultado = con.execute("""
    SELECT
        canal,
        DATE_TRUNC('month', CAST(data AS DATE)) AS mes,
        SUM(receita) AS receita_total,
        COUNT(*) AS transacoes,
        AVG(ticket) AS ticket_medio,
        SUM(receita) / NULLIF(SUM(gasto), 0) AS roas
    FROM read_csv_auto('user/vendas.csv')
    GROUP BY 1, 2
    ORDER BY 1, 2
""").df()

print(resultado.to_string(index=False))
resultado.to_csv("analise_sql.csv", index=False)
print("Exportado: analise_sql.csv")
```

---

## 📊 Saída Final — O que entregar

### Opção 1: Relatório textual com gráficos anexados

Use `document()` para documentar os insights principais + gráficos já estão como attachments automáticos.

### Opção 2: Dashboard interativo

Para análises que precisam de visualização dinâmica, use `help(name="html")` e crie um dashboard com Chart.js ou ApexCharts embutido — ideal quando há muitos filtros ou comparações.

### Sempre terminar com:

1. **Insight principal:** o que os dados revelam de mais importante
2. **Causa provável:** por que isso está acontecendo
3. **Ação recomendada:** o que fazer agora (específico, não genérico)
4. **Limitação da análise:** o que os dados não permitem concluir

---

## 🚨 Regras de Ouro

| ✅ FAZER | ❌ NÃO FAZER |
|---|---|
| EDA antes de qualquer análise | Pular direto para o modelo sem explorar |
| Limpar nulos antes de modelar | Assumir que os dados estão limpos |
| Comunicar limitações da análise | Afirmar causalidade por correlação |
| Usar `user/` para ler arquivos enviados | Inventar dados ou preencher com suposições |
| Salvar gráficos como PNG no CWD | Tentar exibir imagens inline no terminal |
| Exportar resultados como CSV | Entregar apenas números no stdout |
| Recomendar ação acionável | Terminar com "pode haver muitos fatores" |
| Usar `tabulate` para tabelas legíveis | Dumpar DataFrame bruto no stdout |

---

## ✅ Checklist Final

- [ ] EDA realizada (shape, tipos, nulos, describe)?
- [ ] Dados limpos antes de modelar (nulos tratados, tipos convertidos)?
- [ ] Gráficos gerados e salvos (PNG no CWD → attachments automáticos)?
- [ ] Tabela de resultados exportada (CSV no CWD → attachment automático)?
- [ ] Insight principal comunicado ao usuário?
- [ ] Ação acionável recomendada (específica, não genérica)?
- [ ] Limitações da análise mencionadas?
