# Competitor Analysis

**Objetivo:** Pesquisar concorrentes com acesso real ao browser — descobrir site, extrair mídias sociais, analisar posicionamento e conteúdo, avaliar anúncios ativos na Meta Ad Library e entregar tudo em um dashboard visual.

**Pré-requisitos obrigatórios:**
1. `document(type="business_canvas")` — Business Canvas criado
2. `document(type="brand_communication")` — Brand Identity criada

> ⚠️ Não use `web-search` nesta skill. Use `terminal` (curl), `user_browser` e `html`.

---

## 🚀 Fluxo Obrigatório

```
1. lookup(file="SkillCompetitorAnalysis.md")
2. lookup(file="SkillUserBrowsing.md")
3. lookup(file="SkillDashboard.md")
4. context(type="document", document_id="<business_canvas_id>")
5. context(type="document", document_id="<brand_communication_id>")
6. Pedir ao usuário o nome ou site do(s) concorrente(s) (quiz se não informado)
7. terminal — descobrir URLs das mídias sociais via curl
8. Apresentar plano de browsing + quiz de autorização (UserBrowsing)
9. user_browser — navegar site, redes sociais e Meta Ad Library
10. html — dashboard com análise completa
```

---

## Etapa 1 — Descobrir Site e Mídias Sociais

Se o usuário não fornecer o site, tente `<nome>.com.br` e `<nome>.com`.

Use `terminal` com curl para extrair os links de redes sociais diretamente do HTML do site:

```python
terminal(shell="""
curl -sL --max-time 15 -A 'Mozilla/5.0' '<URL_DO_SITE>' |
grep -oE '(https?://)?(www\\.)?(instagram\\.com|facebook\\.com|tiktok\\.com|linkedin\\.com|twitter\\.com|youtube\\.com|pinterest\\.com)/[A-Za-z0-9_./@-]+' |
sort -u | head -20
""")
```

Consolide os perfis encontrados. Se não achar, tente o rodapé ou a página /contato:

```python
terminal(shell="curl -sL --max-time 15 -A 'Mozilla/5.0' '<URL>/contato' | grep -oE 'instagram\\.com/[A-Za-z0-9_.]+' | head -5")
```

---

## Etapa 2 — Plano de Browsing (antes do quiz)

Apresente ao usuário o que será feito no browser, por exemplo:

> "Vou navegar no seu browser para:
> 1. Abrir o site **<concorrente>.com.br** e capturar o posicionamento da home
> 2. Acessar o perfil do Instagram **instagram.com/<handle>** e analisar últimos posts
> 3. Acessar o Facebook **facebook.com/<page>** e verificar posicionamento
> 4. Acessar a Meta Ad Library: **facebook.com/ads/library?q=<marca>** e capturar anúncios ativos
> 5. Acessar o TikTok / LinkedIn se encontrados
> 6. Gerar dashboard com análise completa"

Em seguida, quiz de autorização (obrigatório pela SkillUserBrowsing):

```python
quiz([{"pergunta": "Posso controlar seu browser para fazer a análise de concorrentes?", "options": ["Sim, pode acessar", "Não"]}])
```

---

## Etapa 3 — Navegação com user_browser

### 3a. Site do concorrente
```python
user_browser(action="navigate", url="<site_concorrente>")
user_browser(action="screenshot")
user_browser(action="scrape_text", selector="body")
```

### 3b. Instagram
```python
user_browser(action="navigate", url="https://www.instagram.com/<handle>/")
user_browser(action="screenshot")
user_browser(action="scrape_text", selector="body")
# Role para ver posts
user_browser(action="scroll", direction="down", amount=3)
user_browser(action="screenshot")
```

### 3c. Facebook / Página
```python
user_browser(action="navigate", url="https://www.facebook.com/<page>")
user_browser(action="screenshot")
user_browser(action="scrape_text", selector="body")
```

### 3d. Meta Ad Library — Anúncios Ativos
```python
user_browser(action="navigate", url="https://www.facebook.com/ads/library/?active_status=active&ad_type=all&country=BR&q=<marca>&search_type=keyword_unordered")
user_browser(action="screenshot")
user_browser(action="scrape_text", selector="body")
user_browser(action="scroll", direction="down", amount=5)
user_browser(action="screenshot")
```

### 3e. TikTok (se encontrado)
```python
user_browser(action="navigate", url="https://www.tiktok.com/@<handle>")
user_browser(action="screenshot")
```

### 3f. LinkedIn (se encontrado)
```python
user_browser(action="navigate", url="https://www.linkedin.com/company/<handle>")
user_browser(action="screenshot")
```

---

## Etapa 4 — Dashboard Final (`html`)

Após coletar todos os dados, gere um dashboard visual com:

```python
lookup(file="SkillDashboard.md")  # já feito no início
html(
  title="Análise de Concorrente — <Nome>",
  html='...'
)
```

### Estrutura do dashboard:

```
┌─────────────────────────────────────────────────────────┐
│  COMPETITOR ANALYSIS — <NOME>              [data]        │
├──────────────┬──────────────┬──────────────┬────────────┤
│   SITE       │  INSTAGRAM   │   FACEBOOK   │  TIKTOK    │
│  posicion.   │  estilo      │  posts       │  formatos  │
├──────────────┴──────────────┴──────────────┴────────────┤
│  META AD LIBRARY — Anúncios Ativos                       │
│  [lista de anúncios capturados com CTA, oferta, visual]  │
├─────────────────────────────────────────────────────────┤
│  TOM DE VOZ      │  OFERTA PRINCIPAL  │  CTA PADRÃO     │
├─────────────────────────────────────────────────────────┤
│  GAPS E OPORTUNIDADES para <Marca do Cliente>            │
│  (baseado no Business Canvas e Brand Identity lidos)     │
└─────────────────────────────────────────────────────────┘
```

**Padrão visual:** fundo preto (`#0a0a0a`), texto claro, acentos coloridos. Use Tailwind CSS + Chart.js se precisar de gráficos.

---

## 📋 Dimensões de Análise

### 1. Site e Posicionamento
- Proposta de valor na headline
- Tom de voz e linguagem
- Oferta principal e CTA

### 2. Redes Sociais
- Frequência de postagem
- Formatos dominantes (feed, reels, stories, carrossel)
- Estilo visual (UGC, studio, lifestyle, ilustração)
- Engajamento aparente

### 3. Anúncios Ativos (Meta Ad Library)
- Quantos anúncios ativos
- Formatos usados
- Mensagem principal e CTA
- Há promoções, urgência ou garantias?

### 4. Gaps para a Marca do Cliente
- O que o concorrente NÃO está comunicando?
- Ângulos que a marca pode explorar
- Formatos não utilizados pelo concorrente

---

## 💡 Notas

- Se o browser bloquear o Instagram/TikTok (login obrigatório), documente no dashboard como "acesso restrito" e analise o que estava visível.
- Para múltiplos concorrentes, repita as Etapas 1–4 e gere seções separadas no dashboard.
- Esta skill NÃO cria documentos — produz apenas o dashboard de análise.
