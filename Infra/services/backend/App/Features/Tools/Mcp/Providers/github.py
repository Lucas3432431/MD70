"""Provider GitHub para MCP nativo."""
from typing import Dict, Any, List
import httpx

TOOL_DEFINITIONS: List[Dict] = [
    {
        "name": "mcp__github__list_repos",
        "description": "[GITHUB] Lista os repositórios do usuário autenticado — inclui repos PRIVADOS, pois usa o token configurado. Para listar repos de outro usuário/org use list_public_repos.",
        "parameters": {
            "type": "object",
            "properties": {
                "type": {
                    "type": "string",
                    "description": "Tipo: all, public, private, forks, sources (padrão: all)",
                },
                "sort": {
                    "type": "string",
                    "description": "Ordenar por: created, updated, pushed, full_name (padrão: updated)",
                },
                "limit": {
                    "type": "integer",
                    "description": "Máximo de resultados (padrão 30)",
                },
            },
        },
    },
    {
        "name": "mcp__github__list_public_repos",
        "description": "[GITHUB] Lista repositórios públicos de outro usuário ou organização. Use apenas quando precisar acessar repos externos — para repos próprios use list_repos.",
        "parameters": {
            "type": "object",
            "properties": {
                "username_or_org": {
                    "type": "string",
                    "description": "Username ou nome da organização no GitHub",
                },
                "limit": {
                    "type": "integer",
                    "description": "Máximo de resultados (padrão 30)",
                },
            },
            "required": ["username_or_org"],
        },
    },
    {
        "name": "mcp__github__get_repo",
        "description": "[GITHUB] Obtém detalhes de um repositório: descrição, stars, forks, issues, linguagem, topics. Funciona com repos privados do usuário autenticado.",
        "parameters": {
            "type": "object",
            "properties": {
                "owner": {
                    "type": "string",
                    "description": "Dono do repositório — opcional, padrão: usuário autenticado",
                },
                "repo": {"type": "string", "description": "Nome do repositório"},
            },
            "required": ["repo"],
        },
    },
    {
        "name": "mcp__github__list_issues",
        "description": "[GITHUB] Lista issues de um repositório com filtros por estado, labels e assignee. Funciona com repos privados do usuário autenticado.",
        "parameters": {
            "type": "object",
            "properties": {
                "owner": {
                    "type": "string",
                    "description": "Dono do repositório — opcional, padrão: usuário autenticado",
                },
                "repo": {"type": "string", "description": "Nome do repositório"},
                "state": {
                    "type": "string",
                    "description": "Estado: open, closed, all (padrão: open)",
                },
                "labels": {
                    "type": "string",
                    "description": "Labels separadas por vírgula (ex: bug,enhancement)",
                },
                "assignee": {
                    "type": "string",
                    "description": "Username do assignee (opcional)",
                },
                "limit": {"type": "integer", "description": "Máximo (padrão 20)"},
            },
            "required": ["repo"],
        },
    },
    {
        "name": "mcp__github__get_issue",
        "description": "[GITHUB] Obtém detalhes de uma issue específica: título, corpo, labels, comentários. Funciona com repos privados do usuário autenticado.",
        "parameters": {
            "type": "object",
            "properties": {
                "owner": {
                    "type": "string",
                    "description": "Dono do repositório — opcional, padrão: usuário autenticado",
                },
                "repo": {"type": "string", "description": "Nome do repositório"},
                "issue_number": {
                    "type": "integer",
                    "description": "Número da issue",
                },
            },
            "required": ["repo", "issue_number"],
        },
    },
    {
        "name": "mcp__github__list_pull_requests",
        "description": "[GITHUB] Lista pull requests de um repositório. Funciona com repos privados do usuário autenticado.",
        "parameters": {
            "type": "object",
            "properties": {
                "owner": {
                    "type": "string",
                    "description": "Dono do repositório — opcional, padrão: usuário autenticado",
                },
                "repo": {"type": "string", "description": "Nome do repositório"},
                "state": {
                    "type": "string",
                    "description": "Estado: open, closed, all (padrão: open)",
                },
                "base": {
                    "type": "string",
                    "description": "Branch base de destino para filtrar (opcional)",
                },
                "limit": {"type": "integer", "description": "Máximo (padrão 20)"},
            },
            "required": ["repo"],
        },
    },
    {
        "name": "mcp__github__get_pull_request",
        "description": "[GITHUB] Obtém detalhes de um pull request: título, corpo, estado, arquivos alterados, reviewers. Funciona com repos privados do usuário autenticado.",
        "parameters": {
            "type": "object",
            "properties": {
                "owner": {
                    "type": "string",
                    "description": "Dono do repositório — opcional, padrão: usuário autenticado",
                },
                "repo": {"type": "string", "description": "Nome do repositório"},
                "pr_number": {
                    "type": "integer",
                    "description": "Número do pull request",
                },
            },
            "required": ["repo", "pr_number"],
        },
    },
    {
        "name": "mcp__github__list_commits",
        "description": "[GITHUB] Lista commits recentes de um repositório ou branch. Funciona com repos privados do usuário autenticado.",
        "parameters": {
            "type": "object",
            "properties": {
                "owner": {
                    "type": "string",
                    "description": "Dono do repositório — opcional, padrão: usuário autenticado",
                },
                "repo": {"type": "string", "description": "Nome do repositório"},
                "branch": {
                    "type": "string",
                    "description": "Nome do branch (opcional — usa o padrão do repo)",
                },
                "author": {
                    "type": "string",
                    "description": "Filtrar por autor (username ou email, opcional)",
                },
                "limit": {"type": "integer", "description": "Máximo (padrão 20)"},
            },
            "required": ["repo"],
        },
    },
    {
        "name": "mcp__github__get_file_content",
        "description": "[GITHUB] Lê o conteúdo de um arquivo de um repositório. Funciona com repos privados do usuário autenticado — use sempre que precisar ver o conteúdo de arquivos, incluindo repos privados.",
        "parameters": {
            "type": "object",
            "properties": {
                "owner": {
                    "type": "string",
                    "description": "Dono do repositório — opcional, padrão: usuário autenticado",
                },
                "repo": {"type": "string", "description": "Nome do repositório"},
                "path": {
                    "type": "string",
                    "description": "Caminho do arquivo (ex: src/index.ts)",
                },
                "ref": {
                    "type": "string",
                    "description": "Branch, tag ou commit SHA (opcional — usa o padrão do repo)",
                },
            },
            "required": ["repo", "path"],
        },
    },
    {
        "name": "mcp__github__list_branches",
        "description": "[GITHUB] Lista branches de um repositório. Funciona com repos privados do usuário autenticado.",
        "parameters": {
            "type": "object",
            "properties": {
                "owner": {
                    "type": "string",
                    "description": "Dono do repositório — opcional, padrão: usuário autenticado",
                },
                "repo": {"type": "string", "description": "Nome do repositório"},
                "limit": {"type": "integer", "description": "Máximo (padrão 30)"},
            },
            "required": ["repo"],
        },
    },
    {
        "name": "mcp__github__search_issues",
        "description": "[GITHUB] Busca issues e pull requests no GitHub por texto, repositório, labels e estado.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Texto de busca. Suporta qualificadores: repo:owner/repo, label:bug, is:pr, is:issue, state:open",
                },
                "limit": {"type": "integer", "description": "Máximo (padrão 10)"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "mcp__github__list_directory",
        "description": "[GITHUB] Lista o conteúdo de uma pasta de um repositório (arquivos e subpastas). Funciona com repos privados do usuário autenticado — use para explorar a estrutura de pastas.",
        "parameters": {
            "type": "object",
            "properties": {
                "owner": {
                    "type": "string",
                    "description": "Dono do repositório — opcional, padrão: usuário autenticado",
                },
                "repo": {"type": "string", "description": "Nome do repositório"},
                "path": {
                    "type": "string",
                    "description": "Caminho da pasta (ex: src/components). Use '' ou '/' para a raiz.",
                },
                "ref": {
                    "type": "string",
                    "description": "Branch, tag ou SHA (opcional — usa o padrão do repo)",
                },
            },
            "required": ["repo"],
        },
    },
    {
        "name": "mcp__github__search_file",
        "description": "[GITHUB] Busca arquivos pelo nome dentro de um repositório. Funciona com repos privados do usuário autenticado.",
        "parameters": {
            "type": "object",
            "properties": {
                "owner": {
                    "type": "string",
                    "description": "Dono do repositório — opcional, padrão: usuário autenticado",
                },
                "repo": {"type": "string", "description": "Nome do repositório"},
                "filename": {
                    "type": "string",
                    "description": "Nome (ou parte do nome) do arquivo a buscar",
                },
                "limit": {
                    "type": "integer",
                    "description": "Máximo de resultados (padrão 20)",
                },
            },
            "required": ["repo", "filename"],
        },
    },
    {
        "name": "mcp__github__search_folder",
        "description": "[GITHUB] Busca pastas pelo nome dentro de um repositório. Funciona com repos privados do usuário autenticado.",
        "parameters": {
            "type": "object",
            "properties": {
                "owner": {
                    "type": "string",
                    "description": "Dono do repositório — opcional, padrão: usuário autenticado",
                },
                "repo": {"type": "string", "description": "Nome do repositório"},
                "folder": {
                    "type": "string",
                    "description": "Nome (ou parte do nome) da pasta a buscar",
                },
                "ref": {
                    "type": "string",
                    "description": "Branch ou SHA (opcional — usa o branch padrão do repo)",
                },
            },
            "required": ["repo", "folder"],
        },
    },
    {
        "name": "mcp__github__search_code",
        "description": "[GITHUB] Busca por uma string dentro do conteúdo dos arquivos de um repositório e retorna trechos com contexto. Funciona com repos privados do usuário autenticado.",
        "parameters": {
            "type": "object",
            "properties": {
                "owner": {
                    "type": "string",
                    "description": "Dono do repositório — opcional, padrão: usuário autenticado",
                },
                "repo": {"type": "string", "description": "Nome do repositório"},
                "query": {
                    "type": "string",
                    "description": "String a buscar no conteúdo dos arquivos",
                },
                "limit": {
                    "type": "integer",
                    "description": "Máximo de arquivos retornados (padrão 10)",
                },
            },
            "required": ["repo", "query"],
        },
    },
    {
        "name": "mcp__github__create_branch",
        "description": "[GITHUB] Cria um novo branch a partir de outro branch ou commit. Use SEMPRE antes de create_file/update_file para nunca alterar main/master diretamente.",
        "parameters": {
            "type": "object",
            "properties": {
                "owner": {
                    "type": "string",
                    "description": "Dono do repositório (padrão: usuário autenticado)",
                },
                "repo": {"type": "string", "description": "Nome do repositório"},
                "branch": {
                    "type": "string",
                    "description": "Nome do novo branch (ex: fix/typo-readme)",
                },
                "from_branch": {
                    "type": "string",
                    "description": "Branch de origem (padrão: branch principal do repo)",
                },
            },
            "required": ["repo", "branch"],
        },
    },
    {
        "name": "mcp__github__create_pull_request",
        "description": "[GITHUB] Abre um Pull Request de um branch para outro. Use após create_file/update_file em um branch isolado para submeter as mudanças para revisão.",
        "parameters": {
            "type": "object",
            "properties": {
                "owner": {
                    "type": "string",
                    "description": "Dono do repositório (padrão: usuário autenticado)",
                },
                "repo": {"type": "string", "description": "Nome do repositório"},
                "title": {"type": "string", "description": "Título do Pull Request"},
                "head": {
                    "type": "string",
                    "description": "Branch com as mudanças (ex: fix/typo-readme)",
                },
                "base": {
                    "type": "string",
                    "description": "Branch de destino (padrão: branch principal)",
                },
                "body": {"type": "string", "description": "Descrição do PR (opcional)"},
                "draft": {
                    "type": "boolean",
                    "description": "Abrir como rascunho (padrão: false)",
                },
            },
            "required": ["repo", "title", "head"],
        },
    },
    {
        "name": "mcp__github__create_file",
        "description": "[GITHUB] Cria um novo arquivo em um repositório com o conteúdo fornecido. Falha se o arquivo já existir — use update_file para atualizar.",
        "parameters": {
            "type": "object",
            "properties": {
                "owner": {
                    "type": "string",
                    "description": "Dono do repositório (padrão: usuário autenticado)",
                },
                "repo": {"type": "string", "description": "Nome do repositório"},
                "path": {
                    "type": "string",
                    "description": "Caminho do arquivo no repositório (ex: src/utils/helper.py)",
                },
                "content": {
                    "type": "string",
                    "description": "Conteúdo do arquivo em texto puro",
                },
                "message": {
                    "type": "string",
                    "description": "Mensagem do commit (padrão: 'Create {path}')",
                },
                "branch": {
                    "type": "string",
                    "description": "Branch de destino (padrão: branch principal)",
                },
            },
            "required": ["repo", "path", "content"],
        },
    },
    {
        "name": "mcp__github__update_file",
        "description": "[GITHUB] Atualiza um arquivo existente em um repositório. Busca o SHA atual automaticamente se não fornecido. Falha se o arquivo não existir — use create_file para criar.",
        "parameters": {
            "type": "object",
            "properties": {
                "owner": {
                    "type": "string",
                    "description": "Dono do repositório (padrão: usuário autenticado)",
                },
                "repo": {"type": "string", "description": "Nome do repositório"},
                "path": {
                    "type": "string",
                    "description": "Caminho do arquivo no repositório",
                },
                "content": {
                    "type": "string",
                    "description": "Novo conteúdo completo do arquivo",
                },
                "message": {
                    "type": "string",
                    "description": "Mensagem do commit (padrão: 'Update {path}')",
                },
                "branch": {
                    "type": "string",
                    "description": "Branch de destino (padrão: branch principal)",
                },
                "sha": {
                    "type": "string",
                    "description": "SHA atual do arquivo — buscado automaticamente se omitido",
                },
            },
            "required": ["repo", "path", "content"],
        },
    },
    {
        "name": "mcp__github__delete_file",
        "description": "[GITHUB] Deleta um arquivo de um repositório. Busca o SHA atual automaticamente.",
        "parameters": {
            "type": "object",
            "properties": {
                "owner": {
                    "type": "string",
                    "description": "Dono do repositório (padrão: usuário autenticado)",
                },
                "repo": {"type": "string", "description": "Nome do repositório"},
                "path": {
                    "type": "string",
                    "description": "Caminho do arquivo a deletar",
                },
                "message": {
                    "type": "string",
                    "description": "Mensagem do commit (padrão: 'Delete {path}')",
                },
                "branch": {
                    "type": "string",
                    "description": "Branch de destino (padrão: branch principal)",
                },
            },
            "required": ["repo", "path"],
        },
    },
]


async def call(tool_name: str, args: Dict, env: Dict) -> Dict:
    token = env.get("GITHUB_PERSONAL_ACCESS_TOKEN") or env.get("GITHUB_TOKEN", "")
    default_owner = env.get("GITHUB_DEFAULT_OWNER", "")
    base_url = "https://api.github.com"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    if not token:
        return {
            "success": False,
            "error": "Token GitHub não configurado — conecte em Configurações → Integrações.",
        }

    _auth_user: Dict[str, str] = {}

    async def _get_owner(a: Dict) -> str:
        if a.get("owner"):
            return a["owner"]
        if default_owner:
            return default_owner
        if not _auth_user:
            try:
                me = await http.get(f"{base_url}/user")
                if me.status_code == 200:
                    _auth_user["login"] = me.json().get("login", "")
            except Exception:
                pass
        return _auth_user.get("login", "")

    def _gh_err(data: dict) -> Dict | None:
        if isinstance(data, dict) and "message" in data and "documentation_url" in data:
            msg = data["message"]
            if "Bad credentials" in msg or "Unauthorized" in msg:
                return {
                    "success": False,
                    "error": "Token GitHub inválido ou expirado — reconecte em Configurações → Integrações.",
                }
            return {"success": False, "error": f"GitHub API: {msg}"}
        return None

    async with httpx.AsyncClient(timeout=20.0, headers=headers) as http:
        if tool_name == "list_repos":
            params = {
                "type": args.get("type", "all"),
                "sort": args.get("sort", "updated"),
                "per_page": min(args.get("limit", 30), 100),
            }
            resp = await http.get(f"{base_url}/user/repos", params=params)
            data = resp.json()
            if err := _gh_err(data):
                return err
            lines = [
                f"{r.get('full_name','?')} | ⭐{r.get('stargazers_count',0)} | {r.get('language') or '?'} | {r.get('visibility','?')} | {(r.get('description') or '')[:60]}"
                for r in (data if isinstance(data, list) else [])
                if r
            ]
            return {
                "success": True,
                "content": f"{len(lines)} repositório(s):\n" + "\n".join(lines),
            }

        elif tool_name == "list_public_repos":
            target = args.get("username_or_org", "").strip()
            if not target:
                return {"success": False, "error": "username_or_org é obrigatório."}
            limit = min(args.get("limit", 30), 100)
            # Try user repos first; fall back to org repos on 404
            resp = await http.get(
                f"{base_url}/users/{target}/repos",
                params={"per_page": limit, "sort": "updated"},
            )
            if resp.status_code == 404:
                resp = await http.get(
                    f"{base_url}/orgs/{target}/repos",
                    params={"per_page": limit, "sort": "updated"},
                )
            data = resp.json()
            if err := _gh_err(data):
                return err
            lines = [
                f"{r.get('full_name','?')} | ⭐{r.get('stargazers_count',0)} | {r.get('language') or '?'} | {(r.get('description') or '')[:60]}"
                for r in (data if isinstance(data, list) else [])
                if r
            ]
            return {
                "success": True,
                "content": f"{len(lines)} repositório(s) de '{target}':\n"
                + "\n".join(lines),
            }

        elif tool_name == "get_repo":
            owner, repo = await _get_owner(args), args["repo"]
            resp = await http.get(f"{base_url}/repos/{owner}/{repo}")
            r = resp.json()
            if err := _gh_err(r):
                return err
            return {
                "success": True,
                "content": (
                    f"{r['full_name']} ({r.get('visibility','?')})\n"
                    f"Descrição: {r.get('description','')}\n"
                    f"⭐ Stars: {r.get('stargazers_count',0)} | Forks: {r.get('forks_count',0)} | Issues: {r.get('open_issues_count',0)}\n"
                    f"Linguagem: {r.get('language','?')} | Branch padrão: {r.get('default_branch','?')}\n"
                    f"Topics: {', '.join(r.get('topics', []))}\n"
                    f"URL: {r.get('html_url','')}"
                ),
            }

        elif tool_name == "list_issues":
            owner, repo = await _get_owner(args), args["repo"]
            params = {
                "state": args.get("state", "open"),
                "per_page": min(args.get("limit", 20), 100),
            }
            if args.get("labels"):
                params["labels"] = args["labels"]
            if args.get("assignee"):
                params["assignee"] = args["assignee"]
            resp = await http.get(
                f"{base_url}/repos/{owner}/{repo}/issues", params=params
            )
            data = resp.json()
            if err := _gh_err(data):
                return err
            # exclude PRs (issues endpoint returns both)
            issues = [
                i
                for i in (data if isinstance(data, list) else [])
                if "pull_request" not in i
            ]
            lines = [
                f"#{i['number']} {i['title']} | {i.get('state')} | {', '.join(l['name'] for l in i.get('labels',[]))} | {i.get('user',{}).get('login','?')}"
                for i in issues
            ]
            return {
                "success": True,
                "content": f"{len(lines)} issue(s):\n" + "\n".join(lines),
            }

        elif tool_name == "get_issue":
            owner, repo = await _get_owner(args), args["repo"]
            num = args["issue_number"]
            resp = await http.get(f"{base_url}/repos/{owner}/{repo}/issues/{num}")
            i = resp.json()
            if err := _gh_err(i):
                return err
            return {
                "success": True,
                "content": (
                    f"#{i['number']} {i['title']} [{i.get('state')}]\n"
                    f"Autor: {i.get('user',{}).get('login','?')} | Labels: {', '.join(l['name'] for l in i.get('labels',[]))}\n"
                    f"Comentários: {i.get('comments',0)}\n"
                    f"URL: {i.get('html_url','')}\n\n"
                    f"{(i.get('body') or '')[:800]}"
                ),
            }

        elif tool_name == "list_pull_requests":
            owner, repo = await _get_owner(args), args["repo"]
            params = {
                "state": args.get("state", "open"),
                "per_page": min(args.get("limit", 20), 100),
            }
            if args.get("base"):
                params["base"] = args["base"]
            resp = await http.get(
                f"{base_url}/repos/{owner}/{repo}/pulls", params=params
            )
            data = resp.json()
            if err := _gh_err(data):
                return err
            lines = [
                f"#{p['number']} {p['title']} | {p.get('state')} | {p.get('user',{}).get('login','?')} → {p.get('base',{}).get('ref','?')}"
                for p in (data if isinstance(data, list) else [])
            ]
            return {
                "success": True,
                "content": f"{len(lines)} PR(s):\n" + "\n".join(lines),
            }

        elif tool_name == "get_pull_request":
            owner, repo = await _get_owner(args), args["repo"]
            num = args["pr_number"]
            resp = await http.get(f"{base_url}/repos/{owner}/{repo}/pulls/{num}")
            p = resp.json()
            if err := _gh_err(p):
                return err
            reviewers = ", ".join(r["login"] for r in p.get("requested_reviewers", []))
            return {
                "success": True,
                "content": (
                    f"PR #{p['number']}: {p['title']} [{p.get('state')}]\n"
                    f"Autor: {p.get('user',{}).get('login','?')} | {p.get('head',{}).get('ref','?')} → {p.get('base',{}).get('ref','?')}\n"
                    f"Arquivos: {p.get('changed_files',0)} | +{p.get('additions',0)} -{p.get('deletions',0)}\n"
                    f"Reviewers: {reviewers or '—'} | Mergeable: {p.get('mergeable','?')}\n"
                    f"URL: {p.get('html_url','')}\n\n"
                    f"{(p.get('body') or '')[:600]}"
                ),
            }

        elif tool_name == "list_commits":
            owner, repo = await _get_owner(args), args["repo"]
            params = {"per_page": min(args.get("limit", 20), 100)}
            if args.get("branch"):
                params["sha"] = args["branch"]
            if args.get("author"):
                params["author"] = args["author"]
            resp = await http.get(
                f"{base_url}/repos/{owner}/{repo}/commits", params=params
            )
            data = resp.json()
            if err := _gh_err(data):
                return err
            lines = [
                f"{c['sha'][:7]} | {c.get('commit',{}).get('author',{}).get('name','?')} | {c.get('commit',{}).get('message','').splitlines()[0][:80]}"
                for c in (data if isinstance(data, list) else [])
            ]
            return {
                "success": True,
                "content": f"{len(lines)} commit(s):\n" + "\n".join(lines),
            }

        elif tool_name == "get_file_content":
            import base64 as _b64
            import os as _os

            owner, repo = await _get_owner(args), args["repo"]
            path = args["path"].lstrip("/")
            params = {}
            if args.get("ref"):
                params["ref"] = args["ref"]
            resp = await http.get(
                f"{base_url}/repos/{owner}/{repo}/contents/{path}", params=params
            )
            data = resp.json()
            if err := _gh_err(data):
                return err
            if isinstance(data, list):
                names = [f["name"] for f in data]
                return {
                    "success": True,
                    "content": f"Diretório '{path}':\n" + "\n".join(names),
                }
            size = data.get("size", 0)
            encoded = data.get("content", "")
            file_path = data.get("path", path)

            _INLINE_LIMIT = 20_000

            if size <= _INLINE_LIMIT:
                content = _b64.b64decode(encoded).decode("utf-8", errors="replace")
                return {
                    "success": True,
                    "content": f"Arquivo: {file_path} ({size} bytes)\n\n{content}",
                }

            # Arquivo grande: baixar completo e registrar no storage para injeção no sandbox
            if encoded:
                # Contents API retorna base64 para arquivos até ~1 MB
                raw_bytes = _b64.b64decode(encoded)
            else:
                # Arquivo > 1 MB: usar download_url (raw)
                download_url = data.get("download_url", "")
                if not download_url:
                    return {
                        "success": False,
                        "error": f"Arquivo '{file_path}' ({size} bytes) sem download_url disponível.",
                    }
                raw_resp = await http.get(download_url)
                raw_bytes = raw_resp.content

            chat_id = env.get("_chat_id", "")
            user_id = env.get("_user_id", "unknown")
            filename = _os.path.basename(file_path)

            try:
                from App.Core.Crunch.Storage.StorageManager import StorageManager
                from App.Core.Crunch.TablesSQL.DBManager import DatabaseManager
                import uuid as _uuid

                # Salvar no storage do chat (Data/Database/Chats/{chat_id}/{filename})
                folder = StorageManager.get_chat_attachment_folder(chat_id)
                dest = folder / filename
                with open(dest, "wb") as _f:
                    _f.write(raw_bytes)

                # Registrar como attachment (source=agent) para injeção automática no sandbox
                existing = DatabaseManager.fetch_one(
                    "SELECT attachment_id FROM attachments "
                    "WHERE chat_id = :chat_id AND file_name = :fname AND source = 'agent' AND deleted_at IS NULL",
                    {"chat_id": chat_id, "fname": filename},
                )
                if not existing:
                    ext = filename.rsplit(".", 1)[-1] if "." in filename else "bin"
                    DatabaseManager.execute_query(
                        "INSERT INTO attachments "
                        "(attachment_id, user_id, chat_id, file_name, extension, attachment_type, "
                        "file_size, storage_path, is_temp, source, sandbox_path) "
                        "VALUES (:att_id, :user_id, :chat_id, :file_name, :ext, 'file', "
                        ":file_size, :storage_path, 0, 'agent', :sandbox_path)",
                        {
                            "att_id": str(_uuid.uuid4()),
                            "user_id": user_id,
                            "chat_id": chat_id,
                            "file_name": filename,
                            "ext": ext,
                            "file_size": len(raw_bytes),
                            "storage_path": f"Chats/{chat_id}/{filename}",
                            "sandbox_path": filename,
                        },
                    )

                return {
                    "success": True,
                    "content": (
                        f"Arquivo '{file_path}' ({size:,} bytes) baixado e disponível no terminal como '{filename}'.\n"
                        f"Use terminal(shell='cat {filename}') ou terminal(shell='head -100 {filename}') para ler."
                    ),
                }
            except Exception as _e:
                return {
                    "success": False,
                    "error": f"Erro ao salvar arquivo '{filename}': {_e}",
                }

        elif tool_name == "list_branches":
            owner, repo = await _get_owner(args), args["repo"]
            params = {"per_page": min(args.get("limit", 30), 100)}
            resp = await http.get(
                f"{base_url}/repos/{owner}/{repo}/branches", params=params
            )
            data = resp.json()
            if err := _gh_err(data):
                return err
            lines = [b["name"] for b in (data if isinstance(data, list) else [])]
            return {
                "success": True,
                "content": f"{len(lines)} branch(es):\n" + "\n".join(lines),
            }

        elif tool_name == "search_issues":
            params = {
                "q": args["query"],
                "per_page": min(args.get("limit", 10), 30),
            }
            resp = await http.get(f"{base_url}/search/issues", params=params)
            data = resp.json()
            if err := _gh_err(data):
                return err
            items = data.get("items", [])
            lines = [
                f"#{i['number']} [{i.get('state')}] {i['title']} | {i.get('repository_url','').split('repos/')[-1]}"
                for i in items
            ]
            return {
                "success": True,
                "content": f"{data.get('total_count',0)} resultado(s) (exibindo {len(lines)}):\n"
                + "\n".join(lines),
            }

        elif tool_name == "list_directory":
            import base64 as _b64

            owner, repo = await _get_owner(args), args["repo"]
            path = (args.get("path") or "").strip("/")
            params = {}
            if args.get("ref"):
                params["ref"] = args["ref"]
            resp = await http.get(
                f"{base_url}/repos/{owner}/{repo}/contents/{path}", params=params
            )
            data = resp.json()
            if err := _gh_err(data):
                return err
            if not isinstance(data, list):
                return {
                    "success": False,
                    "error": f"'{path or '/'}' não é uma pasta — use get_file_content para ler arquivos.",
                }
            lines = []
            for item in sorted(
                data, key=lambda x: (x.get("type") != "dir", x.get("name", ""))
            ):
                icon = "📁" if item.get("type") == "dir" else "📄"
                size = (
                    f" ({item['size']}B)"
                    if item.get("type") == "file" and item.get("size")
                    else ""
                )
                lines.append(f"{icon} {item['name']}{size}")
            return {
                "success": True,
                "content": f"Conteúdo de '{path or '/'}' ({len(lines)} item(s)):\n"
                + "\n".join(lines),
            }

        elif tool_name == "search_file":
            owner, repo = await _get_owner(args), args["repo"]
            filename = args.get("filename", "")
            params = {
                "q": f"filename:{filename} repo:{owner}/{repo}",
                "per_page": min(args.get("limit", 20), 100),
            }
            resp = await http.get(f"{base_url}/search/code", params=params)
            data = resp.json()
            if err := _gh_err(data):
                return err
            items = data.get("items", [])
            lines = [f"{i.get('path','?')}  [{i.get('name','?')}]" for i in items]
            total = data.get("total_count", 0)
            return {
                "success": True,
                "content": f"{total} arquivo(s) encontrado(s) (exibindo {len(lines)}):\n"
                + "\n".join(lines),
            }

        elif tool_name == "search_folder":
            owner, repo = await _get_owner(args), args["repo"]
            folder = args.get("folder", "").lower()
            ref = args.get("ref", "")
            # Resolve ref: get default branch if not provided
            if not ref:
                r_repo = await http.get(f"{base_url}/repos/{owner}/{repo}")
                repo_data = r_repo.json()
                if err := _gh_err(repo_data):
                    return err
                ref = repo_data.get("default_branch", "main")
            resp = await http.get(
                f"{base_url}/repos/{owner}/{repo}/git/trees/{ref}",
                params={"recursive": "1"},
            )
            data = resp.json()
            if err := _gh_err(data):
                return err
            tree = data.get("tree", [])
            matches = [
                item["path"]
                for item in tree
                if item.get("type") == "tree"
                and folder in item["path"].lower().split("/")[-1]
            ]
            if not matches:
                return {
                    "success": True,
                    "content": f"Nenhuma pasta encontrada com nome '{folder}'.",
                }
            return {
                "success": True,
                "content": f"{len(matches)} pasta(s) encontrada(s):\n"
                + "\n".join(matches),
            }

        elif tool_name == "search_code":
            owner, repo = await _get_owner(args), args["repo"]
            query = args.get("query", "")
            params = {
                "q": f"{query} in:file repo:{owner}/{repo}",
                "per_page": min(args.get("limit", 10), 30),
            }
            text_match_headers = {
                **headers,
                "Accept": "application/vnd.github.text-match+json",
            }
            resp = await http.get(
                f"{base_url}/search/code", params=params, headers=text_match_headers
            )
            data = resp.json()
            if err := _gh_err(data):
                return err
            items = data.get("items", [])
            lines = []
            for item in items:
                lines.append(f"\n📄 {item.get('path','?')}")
                for match in (item.get("text_matches") or [])[:2]:
                    fragment = (match.get("fragment") or "").replace("\n", " ").strip()
                    lines.append(f"   → {fragment[:150]}")
            total = data.get("total_count", 0)
            return {
                "success": True,
                "content": f"{total} arquivo(s) com '{query}' (exibindo {len(items)}):"
                + "".join(lines),
            }

        elif tool_name == "create_branch":
            owner, repo = await _get_owner(args), args["repo"]
            new_branch = args["branch"]
            from_branch = args.get("from_branch", "")

            # Resolve SHA do branch de origem
            if not from_branch:
                repo_resp = await http.get(
                    f"{base_url}/repos/{owner}/{repo}", params={"access_token": token}
                )
                repo_data = repo_resp.json()
                from_branch = repo_data.get("default_branch", "main")

            ref_resp = await http.get(
                f"{base_url}/repos/{owner}/{repo}/git/ref/heads/{from_branch}"
            )
            ref_data = ref_resp.json()
            if err := _gh_err(ref_data):
                return err
            sha = (ref_data.get("object") or {}).get("sha", "")
            if not sha:
                return {
                    "success": False,
                    "error": f"Não foi possível resolver SHA do branch '{from_branch}'.",
                }

            resp = await http.post(
                f"{base_url}/repos/{owner}/{repo}/git/refs",
                json={"ref": f"refs/heads/{new_branch}", "sha": sha},
            )
            data = resp.json()
            if err := _gh_err(data):
                return err
            return {
                "success": True,
                "content": f"Branch '{new_branch}' criado a partir de '{from_branch}' ({sha[:7]}).",
                "branch": new_branch,
                "sha": sha,
            }

        elif tool_name == "create_pull_request":
            owner, repo = await _get_owner(args), args["repo"]
            head = args["head"]
            base = args.get("base", "")
            if not base:
                repo_resp = await http.get(f"{base_url}/repos/{owner}/{repo}")
                base = (repo_resp.json() or {}).get("default_branch", "main")

            body: Dict[str, Any] = {
                "title": args["title"],
                "head": head,
                "base": base,
            }
            if args.get("body"):
                body["body"] = args["body"]
            if args.get("draft"):
                body["draft"] = True

            resp = await http.post(f"{base_url}/repos/{owner}/{repo}/pulls", json=body)
            data = resp.json()
            if err := _gh_err(data):
                return err
            return {
                "success": True,
                "content": f"PR #{data.get('number')} aberto: {data.get('title')}\n{data.get('html_url','')}",
                "pr_number": data.get("number"),
                "url": data.get("html_url"),
            }

        elif tool_name == "create_file":
            import base64 as _b64

            owner, repo = await _get_owner(args), args["repo"]
            path = args["path"].lstrip("/")
            content_str = args.get("content", "")
            message = args.get("message", f"Create {path}")
            branch = args.get("branch", "")

            content_b64 = _b64.b64encode(content_str.encode("utf-8")).decode("ascii")

            body: Dict[str, Any] = {"message": message, "content": content_b64}
            if branch:
                body["branch"] = branch

            resp = await http.put(
                f"{base_url}/repos/{owner}/{repo}/contents/{path}", json=body
            )
            data = resp.json()
            if err := _gh_err(data):
                return err
            commit_sha = (data.get("commit") or {}).get("sha", "?")[:7]
            return {
                "success": True,
                "content": f"Arquivo '{path}' criado. Commit: {commit_sha}",
                "sha": (data.get("content") or {}).get("sha"),
                "commit": commit_sha,
            }

        elif tool_name == "update_file":
            import base64 as _b64

            owner, repo = await _get_owner(args), args["repo"]
            path = args["path"].lstrip("/")
            content_str = args.get("content", "")
            message = args.get("message", f"Update {path}")
            branch = args.get("branch", "")

            content_b64 = _b64.b64encode(content_str.encode("utf-8")).decode("ascii")

            # SHA obrigatório para update — busca se não fornecido
            sha = args.get("sha", "")
            if not sha:
                chk_params: Dict[str, Any] = {}
                if branch:
                    chk_params["ref"] = branch
                chk = await http.get(
                    f"{base_url}/repos/{owner}/{repo}/contents/{path}",
                    params=chk_params,
                )
                if chk.status_code != 200:
                    return {
                        "success": False,
                        "error": f"Arquivo '{path}' não encontrado — use create_file para criar.",
                    }
                chk_data = chk.json()
                sha = chk_data.get("sha", "") if isinstance(chk_data, dict) else ""

            if not sha:
                return {
                    "success": False,
                    "error": f"Não foi possível obter SHA de '{path}'.",
                }

            body: Dict[str, Any] = {
                "message": message,
                "content": content_b64,
                "sha": sha,
            }
            if branch:
                body["branch"] = branch

            resp = await http.put(
                f"{base_url}/repos/{owner}/{repo}/contents/{path}", json=body
            )
            data = resp.json()
            if err := _gh_err(data):
                return err
            commit_sha = (data.get("commit") or {}).get("sha", "?")[:7]
            return {
                "success": True,
                "content": f"Arquivo '{path}' atualizado. Commit: {commit_sha}",
                "sha": (data.get("content") or {}).get("sha"),
                "commit": commit_sha,
            }

        elif tool_name == "delete_file":
            owner, repo = await _get_owner(args), args["repo"]
            path = args["path"].lstrip("/")
            message = args.get("message", f"Delete {path}")
            branch = args.get("branch", "")

            chk_params2: Dict[str, Any] = {}
            if branch:
                chk_params2["ref"] = branch
            chk2 = await http.get(
                f"{base_url}/repos/{owner}/{repo}/contents/{path}", params=chk_params2
            )
            if chk2.status_code != 200:
                return {"success": False, "error": f"Arquivo '{path}' não encontrado."}
            sha = (chk2.json() or {}).get("sha")
            if not sha:
                return {
                    "success": False,
                    "error": f"Não foi possível obter SHA de '{path}'.",
                }

            body2: Dict[str, Any] = {"message": message, "sha": sha}
            if branch:
                body2["branch"] = branch

            resp2 = await http.request(
                "DELETE", f"{base_url}/repos/{owner}/{repo}/contents/{path}", json=body2
            )
            data2 = resp2.json()
            if err := _gh_err(data2):
                return err
            commit_sha = (data2.get("commit") or {}).get("sha", "?")[:7]
            return {
                "success": True,
                "content": f"Arquivo '{path}' deletado. Commit: {commit_sha}",
            }

    return {"success": False, "error": "Ferramenta não reconhecida"}
