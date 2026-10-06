# google-drive (MCP)

Acessa e gerencia arquivos no Google Drive do usuário via OAuth2.

## Permissões necessárias

| Escopo | Operações |
|--------|-----------|
| `drive.readonly` | Buscar, listar, ler arquivos |
| `drive.file` | Criar, atualizar, deletar arquivos criados pelo app |
| `drive` | Acesso completo (criar, atualizar, deletar qualquer arquivo) |

---

## Leitura

```
mcp__google-drive__list(max_results=10)
  → lista arquivos recentes do Drive: ID, nome, tipo, data de modificação

mcp__google-drive__search(query="relatorio mensal")
  → busca arquivos por nome ou texto; retorna ID, nome, tipo, link

mcp__google-drive__read(file_id="1BxiM...")
  → lê conteúdo de um arquivo de texto pelo ID
  → Docs/Sheets exportados como texto simples automaticamente
```

---

## Escrita

```
mcp__google-drive__create(name="relatorio.txt", content="...", folder_id="...")
  → cria novo arquivo de texto no Drive
  folder_id: ID da pasta de destino (opcional — usa raiz se omitido)

mcp__google-drive__update(file_id="1BxiM...", content="novo conteúdo")
  → substitui o conteúdo de um arquivo existente

mcp__google-drive__delete(file_id="1BxiM...")
  → move o arquivo para a lixeira (não exclui permanentemente)
```

---

## Fluxo típico

```
1. mcp__google-drive__search(query="proposta comercial")   → encontra o arquivo, obtém file_id
2. mcp__google-drive__read(file_id="...")                  → lê o conteúdo
3. mcp__google-drive__update(file_id="...", content="...") → atualiza com nova versão
```
