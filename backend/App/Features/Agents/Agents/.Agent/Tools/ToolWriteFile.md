# write_file

**Objetivo:** Escrever o conteúdo de um arquivo (HTML, Python, CSV, JSON, etc.) diretamente no servidor, sem passar por bash. O arquivo fica disponível automaticamente como `{filename}` na próxima chamada `terminal()`.

## Sequência obrigatória

```
1. help(name="write_file")         ← carrega estas instruções
2. write_file(filename="...", content="...")  ← escreve o arquivo
3. terminal(shell="...")           ← usa o arquivo no sandbox (opcional)
```

## Ferramenta: `write_file`

```
write_file(
  filename="relatorio.html",
  content="<!DOCTYPE html>..."
)
```

**Parâmetros:**
- `filename` — nome do arquivo a criar (ex: `"dashboard.html"`, `"script.py"`)
- `content` — conteúdo completo do arquivo como string
- `encoding` — opcional, padrão `"utf-8"`

**Limite:** 2 MB por arquivo.

**Retorno:**
```json
{
  "success": true,
  "tool": "write_file",
  "attachment_id": "attach_abc123",
  "filename": "relatorio.html",
  "size_bytes": 12480,
  "message": "Arquivo 'relatorio.html' salvo. Disponível como 'relatorio.html' na próxima chamada terminal()."
}
```

---

## Quando usar

| Situação | Ferramenta |
|---|---|
| Gerar HTML grande (dashboards, relatórios) | `write_file` |
| Escrever script Python complexo para rodar depois | `write_file` → `terminal` |
| Criar CSV, JSON ou qualquer arquivo de texto | `write_file` |
| Arquivo pequeno gerado dentro do próprio terminal | `terminal` direto |

---

## Por que usar em vez de terminal?

O `terminal` exige que o conteúdo do arquivo esteja embutido num comando bash (heredoc ou `-c`). Isso causa problemas com arquivos grandes ou com caracteres especiais (aspas, `"""`, `</style>`, etc.) — o JSON do comando quebra.

`write_file` recebe o conteúdo diretamente como campo JSON, sem passar por bash. Funciona para qualquer tamanho até 2 MB.

---

## Exemplos

```python
# Gerar HTML interativo e disponibilizar no sandbox
write_file(
  filename="dashboard.html",
  content="""<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<title>Dashboard</title>
<style>
  body { font-family: Inter, sans-serif; background: #0B0D14; color: white; }
</style>
</head>
<body>
  <h1>Relatório de Campanha</h1>
</body>
</html>"""
)

# Depois usar o arquivo no terminal (ex: verificar tamanho)
terminal(shell='wc -c dashboard.html && echo "OK"')
```

```python
# Escrever script Python para executar no sandbox
write_file(
  filename="analise.py",
  content="""
import pandas as pd
from tabulate import tabulate

dados = [["Meta", 3.2, 5000], ["Google", 1.8, 8000]]
df = pd.DataFrame(dados, columns=["Canal", "CTR%", "Impressões"])
print(tabulate(df.values, headers=df.columns, tablefmt="simple"))
"""
)

terminal(shell='python3 analise.py')
```

---

## Upsert automático

Se você chamar `write_file` duas vezes com o mesmo `filename`, o arquivo anterior é **sobrescrito** — não duplicado. Útil para iterar sobre um HTML enquanto desenvolve.
