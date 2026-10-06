# github (MCP)

Acessa repositórios GitHub via Personal Access Token. Inclui leitura de código, issues, PRs e escrita segura via branches.

## Permissões necessárias

| Escopo | Operações |
|--------|-----------|
| `repo` | Repos privados: leitura, branches, commits, arquivos |
| `public_repo` | Repos públicos apenas |
| `issues` | Issues e comentários |
| `pull_requests` | Pull requests |

---

## Repositórios

```
mcp__github__list_repos(type="all", sort="updated", limit=30)
  → repos do usuário autenticado (inclui privados)
  type: all | public | private | forks | sources

mcp__github__list_public_repos(username_or_org="...", limit=30)
  → repos públicos de outro usuário ou organização

mcp__github__get_repo(repo="...", owner="...")
  → detalhes: descrição, stars, forks, issues abertas, linguagem, topics
```

---

## Branches e Commits

```
mcp__github__list_branches(repo="...", owner="...", limit=30)
  → lista branches do repositório

mcp__github__list_commits(repo="...", owner="...", branch="...", author="...", limit=20)
  → commits recentes de um repo ou branch específico
```

---

## Arquivos e Código

```
mcp__github__list_directory(repo="...", path="", ref="...", owner="...")
  → lista arquivos e subpastas de um caminho (use path="" para raiz)

mcp__github__get_file_content(repo="...", path="src/index.ts", ref="...", owner="...")
  → lê conteúdo de um arquivo (decodifica base64 automaticamente)

mcp__github__search_file(repo="...", filename="config.py", limit=20)
  → busca arquivos pelo nome dentro do repositório

mcp__github__search_folder(repo="...", folder="components", ref="...")
  → busca pastas pelo nome dentro do repositório

mcp__github__search_code(repo="...", query="def login", limit=10)
  → busca string dentro do conteúdo dos arquivos, retorna trechos com contexto
```

---

## Issues e Pull Requests (READ)

```
mcp__github__list_issues(repo="...", state="open", labels="bug", assignee="...", limit=20)
  → issues do repositório; state: open | closed | all

mcp__github__get_issue(repo="...", issue_number=42)
  → detalhes de uma issue: título, corpo, labels, comentários

mcp__github__search_issues(query="is:open label:bug repo:owner/repo", limit=10)
  → busca global de issues/PRs com qualificadores GitHub

mcp__github__list_pull_requests(repo="...", state="open", base="main", limit=20)
  → PRs do repositório

mcp__github__get_pull_request(repo="...", pr_number=12)
  → detalhes de um PR: título, corpo, estado, arquivos alterados, reviewers
```

---

## Escrita Segura (branch → PR)

**Fluxo recomendado — nunca altere main/master diretamente:**

```
1. mcp__github__create_branch(repo="...", branch="fix/typo-readme", from_branch="main")
   → cria branch isolado para as mudanças

2. mcp__github__create_file(repo="...", path="docs/CONTRIBUTING.md", content="...", branch="fix/typo-readme")
   → cria novo arquivo no branch (falha se já existir)

   mcp__github__update_file(repo="...", path="README.md", content="...", branch="fix/typo-readme")
   → atualiza arquivo existente (busca SHA automaticamente)

   mcp__github__delete_file(repo="...", path="old/file.txt", branch="fix/typo-readme")
   → deleta arquivo (busca SHA automaticamente)

3. mcp__github__create_pull_request(repo="...", title="Fix typo", head="fix/typo-readme", base="main", body="...")
   → abre PR para revisão humana antes do merge
```

```
mcp__github__create_branch(repo="...", branch="feat/nova-feature", from_branch="develop", owner="...")
  from_branch: branch de origem (padrão: branch principal do repo)

mcp__github__create_file(repo="...", path="src/new.py", content="...", message="Add new.py", branch="...")
  → falha se o arquivo já existir — use update_file para atualizar

mcp__github__update_file(repo="...", path="src/existing.py", content="...", message="Update existing.py", branch="...", sha="...")
  sha: buscado automaticamente se omitido

mcp__github__delete_file(repo="...", path="deprecated.py", message="Remove deprecated.py", branch="...")

mcp__github__create_pull_request(repo="...", title="Feat: X", head="feat/x", base="main", body="...", draft=false)
  draft: true para abrir como rascunho
```
