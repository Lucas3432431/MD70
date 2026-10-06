# Tool: brand

Use esta tool durante análise de marca para salvar informações progressivamente e notificar o usuário em tempo real enquanto você trabalha.

## Ações

### `progress` — informa o usuário sobre o que está fazendo
```json
{"tool": "brand", "action": "progress", "step": "Mapeando produtos da loja..."}
```
Chame sempre antes de iniciar cada etapa longa (web scraping, terminal, etc).

### `update` — salva campos de marca no banco e notifica o frontend
```json
{"tool": "brand", "action": "update", "data": {
  "name": "Nome da Marca",
  "slogan": "Tagline aqui",
  "colors": ["#1a1a2e", "#e94560"],
  "fonts": ["Inter", "Playfair Display"],
  "archetype": "O Herói",
  "positioning": "Texto de posicionamento..."
}}
```
Chame quantas vezes precisar — cada chamada faz merge com os dados existentes.

### `add_products` — salva links de produtos detectados
```json
{"tool": "brand", "action": "add_products", "links": [
  "https://loja.com/produto-1",
  "https://loja.com/produto-2"
]}
```

### `done` — sinaliza que a análise foi concluída
```json
{"tool": "brand", "action": "done"}
```
Chame ao final, depois de salvar tudo.

## Fluxo recomendado

1. `brand(action="progress", step="Acessando o site...")`
2. Usar terminal/web-search para coletar dados
3. `brand(action="update", data={...})` — salvar dados visuais (nome, cores, fontes)
4. `brand(action="progress", step="Mapeando produtos...")`
5. Usar terminal para detectar URLs de produtos
6. `brand(action="add_products", links=[...])`
7. `brand(action="progress", step="Criando documentos...")`
8. Criar document(type="business_canvas", ...) e document(type="brand_communication", ...)
9. `brand(action="done")`
