# UserBrowsing Skill

## O que é esta skill

Esta skill habilita o agente a controlar o navegador real do usuário em tempo real através da ferramenta `user_browser`. Com ela o agente pode navegar para sites, clicar em elementos, digitar texto, rolar a página, fazer scrape de conteúdo e capturar screenshots diretamente na aba ativa do usuário.

> CRÍTICO: A ferramenta `user_browser` só pode ser executada após este fluxo ser concluído com autorização explícita do usuário. O sistema bloqueia qualquer chamada fora deste fluxo.

---

## Sequência Obrigatória

```
1. lookup(file="SkillUserBrowsing.md")
2. Apresentar ao usuário o planejamento (o que será feito no browser, passo a passo)
3. quiz([{ pergunta de autorização, options: ["Sim", "Não"] }])
        |
        +-- SE "Sim" -----> Executar user_browser actions
        |
        +-- SE "Não" -----> cancel(reason="Usuário não autorizou controle do browser")
```

> CRÍTICO: Nunca execute `user_browser` sem que o quiz de autorização tenha sido respondido com "Sim". O sistema bloqueia e retorna erro se tentar.

---

## Passo 2 — Apresentar o Planejamento

Antes do quiz, explique ao usuário **o que exatamente o agente irá realizar no browser**, em linguagem clara e sequencial. Exemplo:

> "Vou realizar as seguintes ações no seu browser:
> 1. Abrir o site X
> 2. Clicar no campo de busca e digitar Y
> 3. Navegar pelos resultados e capturar as informações Z
> 4. Retornar o conteúdo encontrado para você"

---

## Passo 3 — Quiz de Autorização (chamada única)

```
quiz(
  quiz=[{
    question: "Você autoriza eu executar o planejamento descrito acima?",
    type: "multiple_choice",
    options: ["Sim", "Não"]
  }],
  plan="1. Passo A\n2. Passo B\n3. Passo C"
)
```

> OBRIGATÓRIO: O campo `plan` é **obrigatório** — lista numerada das ações que serão executadas. Sem ele, o quiz é rejeitado.
> OBRIGATÓRIO: O quiz deve conter exatamente uma pergunta com as opções `["Sim", "Não"]` apenas. Nenhuma outra opção deve ser adicionada.
> OBRIGATÓRIO: Após carregar esta skill, **somente o quiz é permitido**. Nenhuma mensagem ou outra ferramenta pode ser usada até o quiz ser respondido.

---

## Ações disponíveis no user_browser

| Ação | Descrição | Parâmetros |
|---|---|---|
| `redirect` | Abre uma URL na aba do agente | `url` |
| `click_text` | Clica em elemento pelo texto visível | `text` |
| `click_xy` | Clica em coordenada exata | `x`, `y` |
| `type` | Digita texto num campo | `selector`, `text` |
| `scroll` | Rola a página | `amount` (px, negativo = cima) |
| `scrape` | Extrai conteúdo limpo da página atual | — |
| `screenshot` | Captura print da aba como imagem | — |
| `research` | Varredura em domínio: busca no Google, visita cada resultado e faz scrape | `domain`, `terms` (lista) ou `term`, `pages` |
| `product_research` | Scrape de páginas de listagem em marketplaces (ML, Shopee, Amazon, custom) | `marketplace`, `keyword`, `pages` (1–10) |

**Pesquisa em domínio (research):**
```
user_browser(action='research', domain='myshopify.com', terms=['moda feminina', 'vestido'], pages=2)
```
O agente busca `site:domain term` no Google, visita cada resultado e extrai o conteúdo completo da página. Retorna lista com `title`, `url`, `description` e `content` de cada página visitada.

**Pesquisa de produtos em marketplace (product_research):**
```
user_browser(action='product_research', marketplace='mercadolivre', keyword='tênis nike', pages=3)
```
Scrape direto nas páginas de listagem do marketplace — sem Google, sem intermediário. Retorna o conteúdo de cada página de resultados (preços, títulos, links de produto).

| marketplace | URL gerada (exemplo com `pages=2`) |
|---|---|
| `mercadolivre` | `lista.mercadolivre.com.br/{kw}_NoIndex_True` → `..._Desde_49_...` |
| `shopee` | `shopee.com.br/search?keyword={kw}&page=0` → `page=1` |
| `amazon` | `amazon.com.br/s?k={kw}&page=1` → `page=2` |
| URL template | `https://site.com/busca?q={keyword}&p={page}` |

**Parâmetros:**
- `marketplace`: `'mercadolivre'` | `'shopee'` | `'amazon'` | URL template com `{keyword}` e `{page}`
- `keyword`: termo de busca
- `pages`: quantas páginas de listagem scraper (1–10 por keyword)

**Fluxo recomendado para análise de produtos:**
```
1. product_research(marketplace='mercadolivre', keyword='tênis nike', pages=3)
   → retorna listagem com títulos, preços e URLs dos produtos
2. Para cada produto de interesse:
   user_browser(action='redirect', url='https://www.mercadolivre.com.br/...')
   user_browser(action='scrape')
   → retorna detalhes completos do produto
```

**Fluxo de busca manual:**
```
user_browser(action='redirect', url='https://site.com')
user_browser(action='type', selector="input[name='q']", text='termo')
user_browser(action='scrape')
```
> `type` envia Enter automaticamente — não é necessário `press_key`.

---

## Regras de execução

- Execute as ações em sequência — o browser é síncrono, cada ação aguarda o resultado antes da próxima.
- Após `redirect`, aguarde o scrape antes de interagir (a página pode precisar de um momento para carregar).
- Use `screenshot` para confirmar o estado visual da página quando houver ambiguidade.
- Use `scrape` para extrair conteúdo — evite reconstruir informações por memória.
- Se o usuário cancelar durante a execução, pare imediatamente e chame `cancel`.
