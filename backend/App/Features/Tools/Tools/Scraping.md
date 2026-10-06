# Scraping Tool Documentation

Tool de scraping e análise de cores para extrair conteúdo e identidade visual de sites.

## Instalação

### Dependências Obrigatórias
```bash
pip install crawl4ai playwright pillow requests
playwright install chromium
```

## Uso Básico

### 1. Scraping de URL
```bash
python Scraping.py --url "https://exemplo.com.br"
```

**O que faz:**
- Faz scraping da página e converte para Markdown
- **Automaticamente** extrai as 3 cores predominantes do site
- Retorna cores da favicon quando disponível
- Fallback para screenshot se favicon não tiver cores úteis

**Saída padrão:**
```
[Conteúdo em Markdown da página]

---

## Colors

**Favicon:** https://www.xaviercamargo.com.br/assets/img/gfr10k99.png

**1. #b52531** - rgb(181, 37, 49) (5.2%)
**2. #ffffff** - rgb(255, 255, 255) (13.6%)
**3. #2c3e50** - rgb(44, 62, 80) (2.1%)
```

### 2. Scraping com Busca Google
```bash
python Scraping.py --search "Imóveis Rio Claro - SP"
```

**O que faz:**
- Busca no Google
- Retorna resultados em Markdown
- **Sem análise de cores** (Google Search não suporta)

### 3. Scraping com Seletor CSS
```bash
python Scraping.py --url "https://exemplo.com.br" --selector ".main-content"
```

**O que faz:**
- Extrai apenas o elemento que corresponde ao seletor CSS
- Análise de cores funciona normalmente

## Features Avançadas

### Análise de Cores com Favicon

O script usa uma estratégia inteligente de 2 camadas:

**Camada 1: Favicon (Primária)**
- Extrai automaticamente a favicon do site
- Análise de cores da favicon (logo/ícone da marca)
- Sem filtros - retorna todas as cores
- Ideal para identidade visual da marca

**Camada 2: Screenshot (Fallback)**
- Se a favicon não tiver cores úteis
- Faz screenshot da página completa
- Analisa pixels e identifica cores predominantes
- Filtra apenas #ffffff (branco puro)

### Formatos de Saída

#### Saída Padrão (JSON com conteúdo)
```bash
python Scraping.py --url "https://exemplo.com.br"
```

Retorna:
- Conteúdo Markdown
- Separador `---`
- Seção `## Colors` com as 3 cores em markdown

#### Saída Legível (Human-Readable)
```bash
python Scraping.py --url "https://exemplo.com.br" --human
```

Exibe:
```
==================================================
CONTEÚDO DA PÁGINA
==================================================
[conteúdo aqui]

==================================================
CORES PREDOMINANTES
==================================================

🎨 Favicon: https://www.xaviercamargo.com.br/assets/img/gfr10k99.png

Cor 1:
  HEX: #b52531
  RGB: rgb(181, 37, 49)
  Prevalência: 5.2%
...
```

## Exemplos de Uso

### Scraping simples
```bash
python Scraping.py --url "https://www.xaviercamargo.com.br"
```

### Com seletor CSS específico
```bash
python Scraping.py --url "https://www.xaviercamargo.com.br" --selector ".hero-section"
```

### Busca no Google
```bash
python Scraping.py --search "Imobiliária Rio Claro SP"
```

### Saída formatada para humanos
```bash
python Scraping.py --url "https://www.xaviercamargo.com.br" --human
```

## Detalhes Técnicos

### Análise de Cores

**Fonte Primária - Favicon:**
- URL extraída dinamicamente do HTML
- Suporta: `<link rel="icon">`, `<link rel="apple-touch-icon">`, `<meta property="og:image">`
- Análise de até 10 cores dominantes
- Retorna as 3 principais

**Fonte Secundária - Screenshot:**
- Renderização completa da página com Playwright
- Timeout: 30 segundos
- Redimensiona screenshot para 300x300px (performance)
- Filtra #ffffff específico (fundo padrão)
- Análise de até 10 cores dominantes
- Retorna as 3 principais

**Formato de Cores:**
- **HEX**: `#RRGGBB` (ex: `#b52531`)
- **RGB**: `rgb(R, G, B)` (ex: `rgb(181, 37, 49)`)
- **Percentual**: Prevalência relativa na imagem (ex: `5.2%`)

**Favicon URL:**
- Extraída automaticamente do HTML
- URL completa (pode ser usada em APIs externas)
- Formatos suportados: PNG, ICO, SVG, JPG, WebP
- Retornado quando cores são extraídas da favicon
- `null` quando fallback usa screenshot

### Performance

| Operação | Tempo Típico |
|----------|-------------|
| Scraping simples | 3-8s |
| Extração de favicon | +2-3s |
| Screenshot (fallback) | +5-10s |
| Total (favicon + fallback) | 10-20s |

### Limitações

- **Favicon**: Precisa estar acessível via HTTP(S)
- **Screenshot**: Requer browser Chromium
- **Timeout**: Máximo 30 segundos por página
- **Cores**: Retorna apenas as 3 mais predominantes

## Integração com Ferramentas Externas

### ColorViewer - Visualizar Cores

```bash
# Extrai cores
python Scraping.py --url "https://exemplo.com.br" > resultado.txt

# Abre no visualizador
python OpenColorViewer.py "#b52531"
```

### IA de Geração de Imagens

A URL da favicon é retornada em cada requisição para usar como:
- **Referência visual** para gerar imagens similares
- **Prompt image** em APIs como DALL-E, Midjourney, Ideogram
- **Brand reference** para manter consistência visual

**Exemplo de uso com API:**
```python
import requests

# Extrai informações do site
resultado = requests.get(
    "seu-scraper-endpoint",
    params={"url": "https://exemplo.com.br"}
)

data = resultado.json()
favicon_url = data["favicon_url"]
colors = [c["hex"] for c in data["colors"]]

# Usa com IA de geração
payload = {
    "prompt": f"Gere uma imagem baseada nesta marca: {favicon_url}",
    "reference_image": favicon_url,
    "color_palette": colors
}
```

**Formatos suportados:**
- PNG (.png) - Transparência preservada
- ICO (.ico) - Favicon padrão
- SVG (.svg) - Vetorial
- JPG/JPEG (.jpg) - Imagens"

## Troubleshooting

### ❌ "Dependências faltando"
```bash
pip install playwright pillow requests crawl4ai
playwright install chromium
```

### ❌ Página não carrega
- Verifique URL
- Aumente timeout (edite script, padrão 30s)
- Tente com `--human` para debug

### ❌ Cores não aparecem
- Favicon pode estar inacessível (tenta screenshot)
- Screenshot pode ter timed out
- Verifique conexão de internet

### ❌ Cores estranhas
- Screenshot usa amostragem de 300x300px
- Se precisa precisão, edite o `thumbnail((300, 300))`

## Changelog

### v1.0 - Features Atuais
- ✅ Scraping com crawl4ai
- ✅ Extração automática de cores
- ✅ Análise primária de favicon
- ✅ Fallback para screenshot
- ✅ Suporte a CSS selectors
- ✅ Busca Google integrada
- ✅ Múltiplos formatos de saída

## Autor

Desenvolvido para MD70 MVP - Backend Data Tools
