# Terminal

**Objetivo:** Executar comandos bash em sandbox isolado para cálculos, análise de dados, pipelines e consultas a APIs externas

## Sequência obrigatória

```
1. help(name="terminal")   ← carrega estas instruções
2. terminal(shell="...")        ← executa o comando
```

## O que é esta tool

Executa comandos bash em um **sandbox isolado por usuário**. O ambiente é separado do backend — sem secrets, sem rede interna, com limites de recursos automáticos.

Use quando precisar de cálculos, análise de dados, pipelines de processamento, ou consulta a APIs externas.

---

## Ferramenta: `terminal`

```
terminal(shell='comando bash')
```

**Parâmetro único:**
- `shell`: qualquer comando bash — pode encadear com `|`, `&&`, `;`, usar variáveis, heredocs, etc.

**Retorno:**
```json
{
  "success": true,
  "command": "comando executado",
  "exit_code": 0,
  "stdout": "resultado",
  "stderr": ""
}
```

---

## ⚠️ Regras de ouro — leia antes de usar

### 1. Sempre use aspas simples no argumento `shell`

```python
# ✅ Correto
terminal(shell='python3 -c "import json; print(json.dumps({\"a\": 1}))"')

# ❌ Evitar — aspas duplas externas causam conflito com aspas internas
terminal(shell="python3 -c \"import json; ...\"")
```

### 2. Para scripts Python multi-linha: use heredoc

Nunca use `python3 -c "código longo"` com quebras de linha — o bash quebra o comando.
Use o padrão heredoc:

```python
terminal(shell='cat > /tmp/script.py << \'EOF\'
import pandas as pd
from tabulate import tabulate

dados = [["Meta", 3.2, 5000], ["Google", 1.8, 8000]]
df = pd.DataFrame(dados, columns=["Canal", "CTR%", "Impressões"])
print(tabulate(df.values, headers=df.columns, tablefmt="simple"))
EOF
python3 /tmp/script.py')
```

### 3. Para scripts com muitas aspas internas: arquivo temporário via printf

```python
terminal(shell="printf '%s\\n' 'import sys' 'print(sys.version)' > /tmp/s.py && python3 /tmp/s.py")
```

### 4. Encadeamento de comandos

```python
# Múltiplos passos numa chamada só
terminal(shell='cmd1 && cmd2 && cmd3')

# Pipeline
terminal(shell='curl -s https://api.site.com/dados | python3 -c "import sys,json; d=json.load(sys.stdin); print(d)"')
```

---

## Quando usar

| Situação | Padrão recomendado |
|---|---|
| Cálculo simples | `terminal(shell='python3 -c "print(1+1)"')` |
| Script multi-linha | heredoc → arquivo temporário |
| Fetch de API + parse | `curl URL \| python3 -c "..."` |
| Análise com pandas | heredoc |
| Tabela formatada | heredoc com tabulate |
| Ler PDF anexado | heredoc com `fitz` (pymupdf) |
| Múltiplos comandos | `&&` encadeados |

---

## Arquivos do chat (attachments)

Arquivos anexados ao chat (pelo usuário ou pelo agente via `file` ou `download_db`) são injetados automaticamente no diretório **`user/`** dentro do sandbox.

Para acessá-los, use o prefixo `user/`:

```bash
# Listar arquivos disponíveis
ls user/

# Consultar banco SQLite baixado via download_db
sqlite3 user/snapshot.db .tables
sqlite3 user/snapshot.db "SELECT COUNT(*) FROM users"

# Ler CSV
python3 -c "import csv; print(list(csv.reader(open('user/dados.csv')))[:5])"
```

> **sqlite3 CLI** está disponível diretamente — prefira `sqlite3 user/arquivo.db` a usar `import sqlite3` no Python quando quiser explorar bancos interativamente.

---

## Ferramentas CLI disponíveis

| Ferramenta | Uso típico |
|---|---|
| `sqlite3` | Consultar bancos SQLite diretamente: `sqlite3 user/arquivo.db .tables` |
| `python3` | Scripts e cálculos |
| `bash` | Comandos shell gerais |
| `curl` | Chamadas HTTP externas (apenas HTTPS) |

> **Não use `pip install sqlite3`** — o módulo Python `sqlite3` já faz parte da stdlib, e a CLI `sqlite3` já está instalada. Prefira a CLI para explorar bancos interativamente.

## Pacotes Python disponíveis

| Pacote | Uso típico |
|---|---|
| `pandas` | DataFrames, pivot tables, parse de CSV |
| `numpy` | Cálculos numéricos e vetoriais |
| `requests` | Chamadas HTTP dentro do Python |
| `tabulate` | `tabulate(rows, headers=[...], tablefmt="simple")` |
| `python-dateutil` | `from dateutil.parser import parse` |
| `openpyxl` | Ler/escrever Excel (.xlsx) |
| `pymupdf` (`fitz`) | Extrair texto de PDFs — `import fitz` |
| stdlib completa | `math`, `json`, `csv`, `statistics`, `datetime`, `re`, `collections`… |

---

## Limites

- Timeout: **30 segundos**
- RAM: **512 MB**
- Arquivo máximo: **10 MB**
- File descriptors: 256
- Processos filhos: 256
- Env isolado: sem variáveis de backend (secrets, tokens, DB)

---

## Comandos bloqueados

| Categoria | Bloqueados |
|---|---|
| Escalada de privilégio | `sudo`, `su` |
| Deleção | `rm -r`, `rm -f` |
| Download | `wget` |
| Pacotes | `apt`, `apt-get`, `pip install`, `npm install` |
| Acesso remoto | `ssh`, `scp`, `sftp`, `telnet`, `ftp` |
| Backdoor/scan | `nc`, `netcat`, `ncat`, `nmap`, `masscan` |
| Sistema | `reboot`, `shutdown`, `halt`, `poweroff` |
| Processos | `killall`, `pkill` |
| Disco | `mkfs`, `fdisk`, `dd if=`, `mount`, `umount` |
| Permissões | `chmod`, `chown` |
| Kernel | `insmod`, `modprobe`, `rmmod` |
| Rede | `iptables`, `nftables`, `ip link/addr/route` |
| IPs internos em URLs | `localhost`, `127.*`, `10.*`, `192.168.*`, `172.16-31.*`, `169.254.*`, `file://` |

---

## Exemplos prontos

```python
# Média ponderada de CTR por canal (heredoc)
terminal(shell='cat > /tmp/ctr.py << \'EOF\'
from tabulate import tabulate
dados = [["Meta", 3.2, 5000], ["Google", 1.8, 8000], ["TikTok", 4.1, 2000]]
total_imp = sum(r[2] for r in dados)
media_pond = sum(r[1]*r[2] for r in dados) / total_imp
print(tabulate(dados, headers=["Canal","CTR%","Impressões"]))
print(f"\nCTR ponderado: {media_pond:.2f}%")
EOF
python3 /tmp/ctr.py')

# Fetch de câmbio USD/BRL
terminal(shell="curl -s 'https://open.er-api.com/v6/latest/USD' | python3 -c \"import sys,json; d=json.load(sys.stdin); print('BRL:', d['rates']['BRL'])\"")

# Extrair texto de PDF anexado pelo usuário
terminal(shell='cat > /tmp/read_pdf.py << \'EOF\'
import fitz
pdf = fitz.open("user/arquivo.pdf")
for i, page in enumerate(pdf):
    print(f"--- Página {i+1} ---")
    print(page.get_text())
EOF
python3 /tmp/read_pdf.py')

# Datas de campanha (heredoc)
terminal(shell='cat > /tmp/datas.py << \'EOF\'
from dateutil.parser import parse
from datetime import timedelta
inicio = parse("2026-06-01")
fim = inicio + timedelta(days=30)
print("Início:", inicio.strftime("%d/%m/%Y"))
print("Fim:", fim.strftime("%d/%m/%Y"))
print("Duração: 30 dias")
EOF
python3 /tmp/datas.py')
```
