# RAG Query — Busca em Documentos

**Objetivo:** Recuperar trechos relevantes dos documentos indexados do usuário (Google Drive, Notion, OneDrive, etc.) usando busca semântica por similaridade vetorial.

## Sequência obrigatória

```
1. help(name="rag_query")   ← carrega estas instruções
2. rag_query(query="...")   ← executa a busca
```

---

## Quando usar

- O usuário pede para "buscar no meu drive", "verificar nos meus documentos", "procurar no Notion"
- Uma pergunta pode ser respondida com dados internos da empresa
- O usuário menciona relatórios, planilhas, políticas, contratos ou documentos próprios
- Complementar uma resposta com contexto dos arquivos do usuário

## Como usar os resultados

Cada resultado contém:

| Campo | Descrição |
|-------|-----------|
| `content` | Trecho do documento mais relevante para a query |
| `file_name` | Nome do arquivo de origem |
| `file_path` | Caminho do arquivo no sistema de origem |
| `source_url` | URL direta para o arquivo (Google Drive, Notion, etc.) |
| `file_source` | Provedor: `google-drive`, `notion`, `onedrive`, etc. |

Use `content` para compor sua resposta. Cite `file_name` e `source_url` quando referenciar a fonte.

---

## Estrutura da chamada

```json
rag_query(
  query="texto da busca em linguagem natural",
  sources=["google-drive", "notion"],   // opcional — filtra por provedor
  top_k=5                               // opcional — número de resultados (máx 20)
)
```

### Parâmetros

| Parâmetro | Tipo | Obrigatório | Descrição |
|-----------|------|-------------|-----------|
| `query` | string | Sim | Texto da busca em linguagem natural |
| `sources` | string[] | Não | Filtra por provedor. Omitir para buscar em todos |
| `top_k` | integer | Não | Quantidade de resultados (padrão 5, máx 20) |

### Provedores disponíveis

`google-drive` · `notion` · `onedrive` · `supabase` · `github`

---

## Exemplos

### Busca geral
```
rag_query(query="política de reembolso de despesas")
```

### Busca filtrada por provedor
```
rag_query(query="contrato com fornecedor Acme", sources=["google-drive", "notion"], top_k=3)
```

---

## Boas práticas

- Use queries descritivas em linguagem natural — não use palavras-chave isoladas
- Se o usuário menciona um documento específico, inclua o nome na query
- Se não encontrar resultado relevante (score baixo / sem conteúdo útil), informe o usuário e sugira verificar se a integração está ativa em Configurações → Integrações
- Nunca invente conteúdo — use apenas o que vier em `content`
