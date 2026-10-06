"""Provider Supabase para MCP nativo."""
import json
import os
from typing import Dict, Any, List
import httpx

TOOL_DEFINITIONS: List[Dict] = [
    {
        "name": "mcp__supabase__list_tables",
        "description": "[SUPABASE] Lista todas as tabelas do projeto Supabase.",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "mcp__supabase__query",
        "description": "[SUPABASE] Executa uma função RPC no Supabase (via /rest/v1/rpc/{function_name}). Use para consultas SQL arbitrárias que estejam expostas como funções.",
        "parameters": {
            "type": "object",
            "properties": {
                "function_name": {
                    "type": "string",
                    "description": "Nome da função RPC cadastrada no Supabase",
                },
                "params": {
                    "type": "object",
                    "description": "Parâmetros passados à função (objeto JSON)",
                },
            },
            "required": ["function_name"],
        },
    },
    {
        "name": "mcp__supabase__get",
        "description": "[SUPABASE] Consulta (SELECT) linhas de uma tabela com filtros opcionais via query string PostgREST.",
        "parameters": {
            "type": "object",
            "properties": {
                "table": {
                    "type": "string",
                    "description": "Nome da tabela",
                },
                "filters": {
                    "type": "object",
                    "description": 'Filtros PostgREST como pares chave=valor (ex: {"id": "eq.123", "status": "eq.active"})',
                },
                "select": {
                    "type": "string",
                    "description": "Colunas a retornar (padrão *)",
                },
                "limit": {
                    "type": "integer",
                    "description": "Máximo de linhas (padrão 100)",
                },
                "order": {
                    "type": "string",
                    "description": "Ordenação PostgREST (ex: created_at.desc)",
                },
            },
            "required": ["table"],
        },
    },
    {
        "name": "mcp__supabase__post",
        "description": "[SUPABASE] Insere uma ou mais linhas em uma tabela (INSERT).",
        "parameters": {
            "type": "object",
            "properties": {
                "table": {"type": "string", "description": "Nome da tabela"},
                "data": {
                    "description": "Objeto ou array de objetos a inserir",
                },
            },
            "required": ["table", "data"],
        },
    },
    {
        "name": "mcp__supabase__patch",
        "description": "[SUPABASE] Atualiza linhas de uma tabela (UPDATE) que correspondam aos filtros.",
        "parameters": {
            "type": "object",
            "properties": {
                "table": {"type": "string", "description": "Nome da tabela"},
                "filters": {
                    "type": "object",
                    "description": "Filtros PostgREST que selecionam as linhas a atualizar",
                },
                "data": {
                    "type": "object",
                    "description": "Campos e valores a atualizar",
                },
            },
            "required": ["table", "filters", "data"],
        },
    },
    {
        "name": "mcp__supabase__put",
        "description": "[SUPABASE] Faz upsert de linhas em uma tabela (INSERT ou UPDATE se já existir).",
        "parameters": {
            "type": "object",
            "properties": {
                "table": {"type": "string", "description": "Nome da tabela"},
                "data": {
                    "description": "Objeto ou array de objetos para upsert",
                },
            },
            "required": ["table", "data"],
        },
    },
    {
        "name": "mcp__supabase__delete",
        "description": "[SUPABASE] Deleta linhas de uma tabela que correspondam aos filtros.",
        "parameters": {
            "type": "object",
            "properties": {
                "table": {"type": "string", "description": "Nome da tabela"},
                "filters": {
                    "type": "object",
                    "description": "Filtros PostgREST que selecionam as linhas a deletar",
                },
            },
            "required": ["table", "filters"],
        },
    },
    {
        "name": "mcp__supabase__download_db",
        "description": "[SUPABASE] Baixa o snapshot do banco SQLite via Litestream S3 e salva como attachment do chat, permitindo que o agente manipule o arquivo diretamente no terminal.",
        "parameters": {
            "type": "object",
            "properties": {
                "filename": {
                    "type": "string",
                    "description": "Nome do arquivo a salvar no chat (padrão: snapshot.db)",
                },
            },
        },
    },
]


async def call(tool_name: str, args: Dict, env: Dict) -> Dict:
    url = env.get("SUPABASE_URL", "").rstrip("/")
    key = env.get("SUPABASE_SERVICE_KEY", "")
    if not url or not key:
        return {
            "success": False,
            "error": "SUPABASE_URL ou SUPABASE_SERVICE_KEY não configurados",
        }

    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    }

    async with httpx.AsyncClient(timeout=30.0) as http:
        if tool_name == "list_tables":
            resp = await http.get(
                f"{url}/rest/v1/",
                headers=headers,
            )
            if resp.status_code not in (200, 201):
                return {
                    "success": False,
                    "error": f"HTTP {resp.status_code}: {resp.text}",
                }
            data = resp.json()
            if isinstance(data, dict) and "definitions" in data:
                tables = list(data["definitions"].keys())
            elif isinstance(data, list):
                tables = [row.get("name", str(row)) for row in data]
            else:
                tables = list(data.keys()) if isinstance(data, dict) else [str(data)]
            return {
                "success": True,
                "content": f"{len(tables)} tabela(s):\n" + "\n".join(tables),
            }

        elif tool_name == "query":
            function_name = args.get("function_name")
            params = args.get("params") or {}
            resp = await http.post(
                f"{url}/rest/v1/rpc/{function_name}",
                headers=headers,
                json=params,
            )
            if resp.status_code not in (200, 201):
                return {
                    "success": False,
                    "error": f"HTTP {resp.status_code}: {resp.text}",
                }
            data = resp.json()
            return {
                "success": True,
                "content": json.dumps(data, ensure_ascii=False, indent=2),
            }

        elif tool_name == "get":
            table = args.get("table")
            filters = args.get("filters") or {}
            select = args.get("select", "*")
            limit = args.get("limit", 100)
            order = args.get("order")
            params: Dict = {"select": select, "limit": limit}
            params.update(filters)
            if order:
                params["order"] = order
            resp = await http.get(
                f"{url}/rest/v1/{table}",
                headers=headers,
                params=params,
            )
            if resp.status_code not in (200, 201):
                return {
                    "success": False,
                    "error": f"HTTP {resp.status_code}: {resp.text}",
                }
            data = resp.json()
            rows = data if isinstance(data, list) else [data]
            return {
                "success": True,
                "content": json.dumps(rows, ensure_ascii=False, indent=2),
            }

        elif tool_name == "post":
            table = args.get("table")
            data = args.get("data")
            resp = await http.post(
                f"{url}/rest/v1/{table}",
                headers=headers,
                json=data,
            )
            if resp.status_code not in (200, 201):
                return {
                    "success": False,
                    "error": f"HTTP {resp.status_code}: {resp.text}",
                }
            result = resp.json()
            rows = result if isinstance(result, list) else [result]
            return {
                "success": True,
                "content": f"Inserido(s) {len(rows)} registro(s):\n"
                + json.dumps(rows, ensure_ascii=False, indent=2),
            }

        elif tool_name == "patch":
            table = args.get("table")
            filters = args.get("filters") or {}
            data = args.get("data")
            resp = await http.patch(
                f"{url}/rest/v1/{table}",
                headers=headers,
                params=filters,
                json=data,
            )
            if resp.status_code not in (200, 201, 204):
                return {
                    "success": False,
                    "error": f"HTTP {resp.status_code}: {resp.text}",
                }
            result = resp.json() if resp.content else []
            rows = result if isinstance(result, list) else [result]
            return {
                "success": True,
                "content": f"Atualizado(s) {len(rows)} registro(s):\n"
                + json.dumps(rows, ensure_ascii=False, indent=2),
            }

        elif tool_name == "put":
            table = args.get("table")
            data = args.get("data")
            upsert_headers = {
                **headers,
                "Prefer": "return=representation,resolution=merge-duplicates",
            }
            resp = await http.post(
                f"{url}/rest/v1/{table}",
                headers=upsert_headers,
                json=data,
            )
            if resp.status_code not in (200, 201):
                return {
                    "success": False,
                    "error": f"HTTP {resp.status_code}: {resp.text}",
                }
            result = resp.json()
            rows = result if isinstance(result, list) else [result]
            return {
                "success": True,
                "content": f"Upsert de {len(rows)} registro(s):\n"
                + json.dumps(rows, ensure_ascii=False, indent=2),
            }

        elif tool_name == "delete":
            table = args.get("table")
            filters = args.get("filters") or {}
            resp = await http.delete(
                f"{url}/rest/v1/{table}",
                headers=headers,
                params=filters,
            )
            if resp.status_code not in (200, 201, 204):
                return {
                    "success": False,
                    "error": f"HTTP {resp.status_code}: {resp.text}",
                }
            result = resp.json() if resp.content else []
            rows = result if isinstance(result, list) else [result]
            return {
                "success": True,
                "content": f"Deletado(s) {len(rows)} registro(s)",
            }

        elif tool_name == "download_db":
            import subprocess
            import shutil
            import re
            import uuid as _uuid
            import mimetypes

            bucket = env.get("SUPABASE_STORAGE_BUCKET", "")
            db_path = env.get("SUPABASE_STORAGE_DB_PATH", "")
            access_key = env.get("SUPABASE_S3_ACCESS_KEY_ID", "")
            secret_key = env.get("SUPABASE_S3_SECRET_ACCESS_KEY", "")
            chat_id = env.get("_chat_id", "")
            user_id = env.get("_user_id", "")
            client_id = env.get("_client_id", "")

            if not bucket or not db_path or not access_key or not secret_key:
                return {
                    "success": False,
                    "error": "Configure SUPABASE_STORAGE_BUCKET, SUPABASE_STORAGE_DB_PATH, SUPABASE_S3_ACCESS_KEY_ID e SUPABASE_S3_SECRET_ACCESS_KEY na integração",
                }
            if not chat_id:
                return {
                    "success": False,
                    "error": "chat_id não disponível — tool só pode ser chamada dentro de um chat",
                }

            match = re.match(r"https://([^.]+)\.supabase\.co", url)
            if not match:
                return {"success": False, "error": f"SUPABASE_URL inválida: {url}"}
            project_ref = match.group(1)
            s3_endpoint = f"https://{project_ref}.storage.supabase.co/storage/v1/s3"

            litestream_bin = shutil.which("litestream")
            if not litestream_bin:
                return {
                    "success": False,
                    "error": "litestream não encontrado no PATH do servidor",
                }

            placeholder = "/tmp/_litestream_placeholder.db"
            tmp_dest = f"/tmp/_litestream_restore_{_uuid.uuid4().hex[:8]}.db"
            config_path = f"/tmp/litestream_restore_{_uuid.uuid4().hex[:8]}.yml"
            config_yaml = (
                f"dbs:\n"
                f"  - path: {placeholder}\n"
                f"    replicas:\n"
                f"      - type: s3\n"
                f"        bucket: {bucket}\n"
                f"        path: {db_path}\n"
                f"        endpoint: {s3_endpoint}\n"
                f"        access-key-id: {access_key}\n"
                f"        secret-access-key: {secret_key}\n"
                f"        force-path-style: true\n"
                f"        region: us-east-1\n"
            )
            with open(config_path, "w") as f:
                f.write(config_yaml)

            try:
                proc = subprocess.run(
                    [
                        litestream_bin,
                        "restore",
                        "-config",
                        config_path,
                        "-o",
                        tmp_dest,
                        placeholder,
                    ],
                    capture_output=True,
                    text=True,
                    timeout=180,
                )
                if proc.returncode != 0:
                    return {
                        "success": False,
                        "error": f"litestream restore falhou:\n{proc.stderr[-1000:]}",
                    }
                if not os.path.exists(tmp_dest) or os.path.getsize(tmp_dest) == 0:
                    return {
                        "success": False,
                        "error": f"Restore não criou arquivo válido.\nstderr: {proc.stderr[-500:]}",
                    }

                # Salvar como attachment do chat via StorageManager
                from App.Core.Crunch.Storage.StorageManager import StorageManager
                from App.Core.Crunch.TablesSQL.DBManager import DatabaseManager

                attach_id = str(_uuid.uuid4())
                filename = args.get("filename", "snapshot.db")
                if not filename.endswith(".db"):
                    filename += ".db"
                folder = StorageManager.get_chat_attachment_folder(chat_id)
                dest_path = folder / f"{attach_id}.db"
                shutil.copy2(tmp_dest, str(dest_path))
                file_size = dest_path.stat().st_size
                rel_path = str(dest_path.relative_to(StorageManager.LOCAL_STORAGE_BASE))

                DatabaseManager.execute_query(
                    "INSERT INTO attachments "
                    "(attachment_id, user_id, chat_id, file_name, extension, file_type, file_size, "
                    "storage_path, storage_env, is_temp, deleted_at) "
                    "VALUES (:aid, :uid, :cid, :fname, 'db', 'application/octet-stream', :fsize, :spath, 'local', 0, NULL)",
                    {
                        "aid": attach_id,
                        "uid": user_id,
                        "cid": chat_id,
                        "fname": filename,
                        "fsize": file_size,
                        "spath": rel_path,
                    },
                )

                size_kb = file_size // 1024
                return {
                    "success": True,
                    "attachment_id": attach_id,
                    "filename": filename,
                    "content": (
                        f"Banco baixado e salvo como '{filename}' ({size_kb} KB). "
                        f"Use terminal(shell='sqlite3 user/{filename} .tables') para listar as tabelas. "
                        f"Todos os arquivos do chat ficam em user/ no sandbox."
                    ),
                }
            except subprocess.TimeoutExpired:
                return {
                    "success": False,
                    "error": "Timeout ao restaurar snapshot (>3 min)",
                }
            except Exception as e:
                return {"success": False, "error": str(e)}
            finally:
                for p in (config_path, placeholder, tmp_dest):
                    if os.path.exists(p):
                        os.remove(p)

    return {"success": False, "error": "Ferramenta não reconhecida"}
