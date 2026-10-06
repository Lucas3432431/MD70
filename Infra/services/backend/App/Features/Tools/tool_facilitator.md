# ToolFacilitator - Facilitador de Ferramentas para IA

## Descrição

`ToolFacilitator` é uma classe Python que abstrai e gerencia todas as ferramentas disponíveis para a IA. Fornece uma interface simplificada para executar comandos, visualizar arquivos, buscar código, editar arquivos, executar scripts e muito mais.

## Funcionalidades Principais

- **Interface Unificada**: Centraliza a definição, execução e documentação de todas as ferramentas
- **Conversão JSON → CLI**: Converte automaticamente argumentos JSON em formato de linha de comando
- **Ferramentas Internas**: `print` e `tools` (hardcoded, sem dependência de arquivos externos)
- **Ferramentas Externas**: Carregadas dinamicamente do `_TOOLS.json`
- **Debug Mode**: Modo de depuração para diagnosticar problemas nas chamadas
- **Tratamento de Erros**: Tratamento robusto de exceções com mensagens claras

## Instalação e Uso Básico

### Inicialização

```python
from tool_facilitor import ToolFacilitator

# Inicializa com diretório padrão (../Tools)
facilitator = ToolFacilitator()

# Ou com diretório customizado
facilitator = ToolFacilitator(tools_dir="/caminho/para/Tools", debug_mode=True)
```

### Executando uma Ferramenta

```python
# Via execute_tool (genérico)
json_args = '{"script-name": "backup.py", "args": "--mode fast"}'
result = facilitator.execute_tool('script', json_args)
print(result)
```

## Ferramentas Disponíveis

### Ferramentas Internas

#### 1. `print`
Exibe mensagens intermediárias durante a execução.

**Parâmetros:**
- `message` (obrigatório): Texto a ser impresso

**Exemplo:**
```python
facilitator.execute_tool('print', '{"message": "Iniciando processamento..."}')
```

#### 2. `tools`
Consulta informações detalhadas sobre as ferramentas disponíveis.

**Parâmetros:**
- `tool_name` (opcional): Nome da ferramenta para detalhes específicos

**Exemplo:**
```python
# Lista todas as ferramentas
facilitator.execute_tool('tools', '{}')

# Detalhes de uma ferramenta específica
facilitator.execute_tool('tools', '{"tool_name": "script"}')
```

### Ferramentas Externas

Todas as ferramentas externas são carregadas do arquivo `_TOOLS.json` e seguem o mesmo padrão de execução via `execute_tool()`.

**Exemplo com `script`:**
```python
json_args = '{"script-name": "deploy.bat", "args": "--env production"}'
facilitator.execute_tool('script', json_args)
```

## Conversão JSON → CLI

ToolFacilitator converte automaticamente argumentos JSON em formato de linha de comando:

### Regras de Conversão

| Tipo JSON | Conversão CLI |
|-----------|---------------|
| `{"campo": "valor"}` | `--campo valor` |
| `{"campo": true}` | `--campo` (apenas flag) |
| `{"campo": false}` | (ignorado) |
| `{"campo": ["v1", "v2"]}` | `--campo v1 --campo v2` |
| `{"campo_nome": "valor"}` | `--campo_nome valor` |

### Exemplo de Conversão

**JSON de entrada:**
```json
{
  "script-name": "backup.py",
  "args": "--mode fast --verbose",
  "--debug": true
}
```

**Convertido para CLI:**
```
--script-name backup.py --args --mode fast --verbose --debug
```

**Nota:** `--debug` é automaticamente removido e não passa para a ferramenta, é apenas um flag de diagnóstico do ToolFacilitator.

## Modo Debug

Ative o modo debug adicionando `"--debug": true` ao JSON:

```python
json_args = '{"script-name": "test.py", "--debug": true}'
result = facilitator.execute_tool('script', json_args)
```

**Saída de Debug:**
```
[DEBUG] Tool: script
[DEBUG] Raw JSON: {"script-name": "test.py", "--debug": true}
[DEBUG] Parsed Args: {'script-name': 'test.py'}
[DEBUG] CLI Args: --script-name test.py
```

## Estrutura Interna

### `execute_tool(tool_name: str, arguments: str) -> str`

**Responsabilidades:**
1. Parse de argumentos JSON
2. Detecção e remoção do flag `--debug`
3. Roteamento para ferramentas internas ou externas
4. Conversão de argumentos JSON para CLI
5. Formatação de resposta para LLM

**Parâmetros:**
- `tool_name`: Nome da ferramenta a executar (case-insensitive)
- `arguments`: String JSON com os argumentos

**Retorno:**
- String com o resultado formatado

### `_run_tool(tool_name: str, args: List[str]) -> Dict`

**Responsabilidades:**
1. Carrega configuração da ferramenta do `_TOOLS.json`
2. Localiza o arquivo da ferramenta usando `EnvFinder.py`
3. Constrói e executa o comando via `subprocess.run()`
4. Captura saída, erro e código de retorno
5. Retorna dicionário estruturado com resultado

**Retorno:**
```python
{
    "success": bool,        # True se exit_code == 0
    "output": str,          # stdout capturado
    "error": str,           # stderr capturado
    "exit_code": int        # Código de retorno do processo
}
```

### `_load_tools_config() -> Dict`

Carrega a configuração das ferramentas do `_TOOLS.json` e retorna um mapeamento:
```python
{
    "tool_name": {
        "name": "tool_name",
        "file": "TOOL.py",
        "description": "...",
        "parameters": {...},
        ...
    },
    ...
}
```

### `get_tool_definitions() -> List[Dict]`

Converte `_TOOLS.json` para formato OpenAI Function Calling, incluindo:
- Ferramentas internas (`print`, `tools`)
- Ferramentas externas carregadas do JSON

**Formato de Retorno:**
```python
[
    {
        "type": "function",
        "function": {
            "name": "print",
            "description": "...",
            "parameters": {
                "type": "object",
                "properties": {...},
                "required": [...]
            }
        }
    },
    ...
]
```

## Arquivo `_TOOLS.json`

### Estrutura Esperada

```json
{
  "general_guidelines": [
    "Diretrizes gerais de uso das ferramentas"
  ],
  "usage_guidelines": {
    "print": "Como usar a ferramenta print",
    "tools": "Como usar a ferramenta tools",
    "ferramenta1": "Como usar a ferramenta1",
    ...
  },
  "tools": [
    {
      "name": "script",
      "file": "SCRIPT.py",
      "description": "Descrição da ferramenta",
      "parameters": {
        "script-name": "Descrição do parâmetro 1",
        "args (opcional)": "Descrição do parâmetro 2"
      },
      "examples": [
        {
          "description": "Exemplo 1",
          "code": "{\"script-name\": \"backup.py\"}"
        }
      ],
      "notes": "Notas adicionais"
    }
  ]
}
```

### Padrão de Parâmetros

- Parâmetros obrigatórios: sem sufixo
- Parâmetros opcionais: sufixo `" (opcional)"`

```json
"parameters": {
  "field-name": "Descrição de campo obrigatório",
  "optional-field (opcional)": "Descrição de campo opcional"
}
```

## Localização de Ferramentas

ToolFacilitator usa `EnvFinder.py` para localizar ferramentas:

1. **EnvFinder.py** busca pelo nome do arquivo em `.file_mapping_name.json`
2. Retorna o caminho completo da ferramenta
3. Se não encontrar, tenta fallback com `EnvTools.py`
4. Executa a ferramenta no caminho encontrado

### Fallback com EnvTools.py

Se `EnvFinder.py` falhar:
1. Executa `EnvTools.py` para atualizar ambiente
2. Tenta `EnvFinder.py` novamente
3. Se ainda falhar, retorna erro

## Tratamento de Erros

### Tipos de Erro

| Erro | Código | Causado por |
|------|--------|------------|
| Ferramenta desconhecida | -1 | Ferramenta não existe em `_TOOLS.json` |
| Arquivo não encontrado | -1 | EnvFinder não localizou o script |
| Campo obrigatório ausente | -1 | Parâmetro obrigatório não fornecido |
| Timeout EnvFinder | -2 | Busca demorou > 10 segundos |
| Timeout EnvTools | -2 | Atualização demorou > 30 segundos |
| Timeout Execução | -2 | Ferramenta demorou > 5 minutos |
| Erro genérico | -3 | Exceção não tratada |

### Formato de Erro

```
ERRO (codigo -1):
Descrição do erro
```

## Integração com IA (LLM)

### Definições de Função para OpenAI

```python
definitions = facilitator.get_tool_definitions()
# Passa para OpenAI como "tools" no payload da API
```

### Fluxo de Execução

1. **IA chama** `execute_tool('ferramenta', json_args)`
2. **ToolFacilitator** converte JSON → CLI
3. **Ferramenta externa** executa
4. **ToolFacilitator** formata resposta
5. **IA recebe** resultado estruturado

## Exemplos de Uso

### Exemplo 1: Executar Script

```python
# JSON
json_args = '{"script-name": "backup.py", "args": "--mode fast"}'

# Execução
result = facilitator.execute_tool('script', json_args)

# Resultado
# ERRO (codigo 0):
# [Saída do script backup.py]
```

### Exemplo 2: Buscar Arquivos

```python
json_args = '{"dir": "src", "file": "*.py", "str": "funcao"}'
result = facilitator.execute_tool('search', json_args)
```

### Exemplo 3: Debug de Ferramenta

```python
json_args = '{"script-name": "test.py", "--debug": true}'
result = facilitator.execute_tool('script', json_args)

# Saída incluirá:
# [DEBUG] Tool: script
# [DEBUG] Raw JSON: ...
# [DEBUG] Parsed Args: ...
# [DEBUG] CLI Args: ...
```

## Notas Importantes

- **Sem hardcoding**: Apenas `print` e `tools` são hardcoded. Todas as outras ferramentas vêm do `_TOOLS.json`
- **Conversão automática**: JSON → CLI é automático e genérico
- **Debug sempre disponível**: Adicione `"--debug": true` para diagnosticar problemas
- **Subprocess seguro**: Usa `subprocess.run()` com capture de output e tratamento de timeout
- **Encoding UTF-8**: Suporta caracteres especiais e acentuação

## Dependências

- Python 3.7+
- Módulos padrão: `json`, `subprocess`, `locale`, `pathlib`
- Arquivos: `_TOOLS.json`, `EnvFinder.py`, `EnvTools.py` (opcional)
