# Supabase — Download DB Snapshot

**Objetivo:** Baixar o snapshot mais recente do banco de dados SQLite via Litestream S3 e salvá-lo como arquivo no chat para manipulação direta no terminal.

## Sequência obrigatória

```
1. help(name="supabase__download_db")   ← carrega estas instruções
2. mcp__supabase__download_db(...)       ← realiza o download e salva no chat
3. terminal(shell="...")                 ← manipula o arquivo localmente
```

## O que esta tool faz

Restaura o snapshot do banco via `litestream restore` direto do bucket S3 configurado na integração Supabase e salva o arquivo `.db` como attachment do chat. O arquivo é automaticamente injetado no sandbox do terminal — o agente pode consultá-lo com `python3` + `sqlite3` sem precisar de nenhum download adicional.

---

## Ferramenta: `mcp__supabase__download_db`

```
mcp__supabase__download_db(filename="snapshot.db")
```

**Parâmetros:**
- `filename` *(opcional)*: nome do arquivo a salvar no chat. Padrão: `snapshot.db`.

**Retorno (sucesso):**
```json
{
  "success": true,
  "attachment_id": "uuid-do-attachment",
  "filename": "snapshot.db",
  "content": "Banco restaurado e salvo no chat como 'snapshot.db' (13420 KB). O arquivo está disponível no terminal como 'snapshot.db'."
}
```

**Retorno (erro):**
```json
{
  "success": false,
  "error": "Descrição do erro"
}
```

---

## Como manipular o banco após o download

O arquivo é injetado no sandbox do terminal no diretório **`user/`**. Use a CLI `sqlite3` diretamente:

```bash
# Listar tabelas
sqlite3 user/snapshot.db .tables

# Ver schema de uma tabela
sqlite3 user/snapshot.db ".schema users"

# Consultar dados
sqlite3 user/snapshot.db "SELECT COUNT(*) FROM users"
sqlite3 user/snapshot.db "SELECT * FROM users LIMIT 10"

# Modo coluna com headers
sqlite3 -column -header user/snapshot.db "SELECT * FROM users LIMIT 5"
```

> **Atenção:** o arquivo fica em `user/snapshot.db` (não na raiz). Sempre use o prefixo `user/`.

---

## Pré-requisitos na integração

A integração Supabase deve ter os campos configurados:
- `SUPABASE_URL` + `SUPABASE_SERVICE_KEY` — obrigatórios
- `SUPABASE_STORAGE_BUCKET` — nome do bucket (ex: `prox-db`)
- `SUPABASE_STORAGE_DB_PATH` — caminho no bucket (ex: `Prox_prod`)
- `SUPABASE_S3_ACCESS_KEY_ID` + `SUPABASE_S3_SECRET_ACCESS_KEY` — chaves S3 do Supabase Storage
