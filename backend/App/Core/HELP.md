# MD70 UserBrowser Tool - Documentação

A ferramenta `user_browser` permite que o Agente de IA controle o navegador do usuário em tempo real através de uma extensão dedicada.

## Sequência obrigatória

```
1. help(name="user_browser")   ← carrega estas instruções
2. user_browser(action="...")  ← executa a ação
```

## Como Funciona
1. O usuário instala a extensão **MD70**.
2. A extensão estabelece um túnel WebSocket com o Backend quando o usuário acessa domínios autorizados (localhost ou prox.app.br).
3. O Agente de IA envia comandos JSON pelo túnel, que são executados instantaneamente no browser do usuário.

## Comandos Disponíveis (Actions)

### 1. `redirect`
Redireciona a aba do agente (grupo MD70) para uma nova URL.
- **Params:** `url` (string)

### 2. `click_xy`
Clica em uma coordenada exata da tela.
- **Params:** `x` (int), `y` (int)

### 3. `click_text`
Busca um elemento por texto e clica nele.
- **Params:** `text` (string)

### 4. `type`
Digita um texto num campo e envia Enter automaticamente ao final.
- **Params:** `text` (string), `selector` (string, CSS selector do campo)

### 5. `scroll`
Rola a página.
- **Params:** `amount` (int) — Positivo para baixo, Negativo para cima.

### 6. `scrape`
Extrai o conteúdo visível e limpo da página atual (sem scripts, estilos, navs).

### 7. `screenshot`
Captura um print screen da aba do agente e retorna como Data URI (`data:image/png;base64,...`).

### 8. `research`
Pesquisa termos num domínio específico via Google (N páginas por termo).
- **Params:** `domain` (string), `terms` (array de strings), `pages` (int)

### 9. `product_research`
Scrape de páginas de listagem de marketplace sem intermediário Google.
- **Params:** `marketplace` (`"mercadolivre"` | `"shopee"` | `"amazon"` | URL template com `{keyword}` e `{page}`), `keyword` (string), `pages` (int, 1–10)

## Configuração de Desenvolvimento
No ambiente local, a extensão tentará se conectar em ws://localhost:8081/ws/agent.
Certifique-se de que o Gateway (Nginx) está configurado para permitir o upgrade de conexão para WebSocket na rota `/ws`.
