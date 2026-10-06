# user_browser

**Objetivo:** Controlar o navegador real do usuário em tempo real para automações, scraping, pesquisa de produtos e interações web.

## Sequência obrigatória

> CRÍTICO: O sistema bloqueia `user_browser` sem autorização explícita via quiz. Siga o fluxo abaixo sem desvio.

```
1. help(name="user_browser")   ← carrega estas instruções (já feito)
2. Apresente ao usuário o planejamento das ações (o que será feito no browser)
3. quiz(                       ← autorização obrigatória
     quiz=[{
       "question": "Você autoriza a execução das ações descritas acima no seu navegador?",
       "type": "multiple_choice",
       "options": ["Sim", "Não"]
     }],
     is_user_browser_auth=True,   ← OBRIGATÓRIO: sem este campo o sistema não reconhece como autorização de browser
     plan="1. Passo A\n2. Passo B\n3. Passo C"  ← OBRIGATÓRIO: lista das ações que serão executadas
   )
   SE "Sim" → executar user_browser(action="...")
   SE "Não" → cancel(reason="Usuário não autorizou controle do browser")
```

> OBRIGATÓRIO: O quiz DEVE incluir:
> - `is_user_browser_auth=True` — sem este campo o validador não reconhece a autorização
> - `plan` — lista numerada das ações que serão executadas no browser
> - Exatamente uma pergunta com options `["Sim", "Não"]` (sem variações, sem texto extra)

## Como funciona

O usuário instala a extensão **MD70** no Chrome. A extensão estabelece um túnel WebSocket com o backend quando o usuário acessa domínios autorizados (`localhost` ou `prox.app.br`). O agente envia comandos JSON pelo túnel, executados instantaneamente no browser do usuário.

---

## Ações disponíveis

### `redirect`
Redireciona a aba do agente para uma nova URL.
```
user_browser(action="redirect", url="https://google.com")
```

### `click_text`
Busca um elemento por texto visível e clica nele.
```
user_browser(action="click_text", text="Entrar")
```

### `click_xy`
Clica em coordenada exata da tela.
```
user_browser(action="click_xy", x=400, y=300)
```

### `type`
Digita texto num campo e envia Enter automaticamente ao final.
```
user_browser(action="type", text="meu email", selector="#email")
```

### `scroll`
Rola a página. Positivo = baixo, Negativo = cima.
```
user_browser(action="scroll", amount=500)
```

### `scrape`
Extrai o conteúdo visível e limpo da página atual (sem scripts, estilos, navs).
```
user_browser(action="scrape")
```

### `screenshot`
Captura print screen da aba e retorna como Data URI (`data:image/png;base64,...`).
```
user_browser(action="screenshot")
```

### `research`
Pesquisa um ou mais termos num domínio específico via Google (N páginas por termo).
```
user_browser(action="research", domain="myshopify.com", terms=["moda feminina", "vestido"], pages=2)
```

### `product_research`
Scrape de páginas de listagem de marketplace — sem intermediário Google.
```
user_browser(action="product_research", marketplace="mercadolivre", keyword="tênis nike", pages=3)
```
- `marketplace`: `"mercadolivre"` | `"shopee"` | `"amazon"` | URL template com `{keyword}` e `{page}`
- `pages`: 1–10 páginas de listagem por keyword

---

## Fluxo típico de busca

```
user_browser(action="redirect", url="https://site.com")
→ user_browser(action="type", selector="input[name='q']", text="termo")
→ user_browser(action="scrape")
```

---

## Quando usar cada ação

| Situação | Ação recomendada |
|---|---|
| Acessar uma URL | `redirect` |
| Clicar num botão por texto | `click_text` |
| Preencher formulário | `type` |
| Ler conteúdo da página | `scrape` |
| Capturar estado visual | `screenshot` |
| Pesquisar em domínio via Google | `research` |
| Listar produtos de marketplace | `product_research` |

---

## Configuração

No ambiente local, a extensão conecta em `ws://localhost:8081/ws/agent`.
Certifique-se de que o Gateway (Nginx) permite upgrade WebSocket na rota `/ws`.
