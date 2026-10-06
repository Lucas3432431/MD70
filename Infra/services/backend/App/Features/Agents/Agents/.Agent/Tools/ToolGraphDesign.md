# GraphDesign

Cria o layout visual editável do criativo (Canva-like) sobre o asset gerado, usando camadas Konva.

---

## Sequencia Unica (obrigatoria)

```
1. help(name="graph_design")
2. graph_design(composition_id, asset_id, title, aspect_ratio, composition)
```

> Sempre chame APOS `asset()` ter retornado os `asset_id` gerados.

---

## Chamada Basica

```javascript
graph_design(
  composition_id="abc123",
  asset_id="abc123.jpg",
  title="Post - Produto X",
  aspect_ratio="1:1",
  composition={
    "dimensions": { "width": 1080, "height": 1080 },
    "backgroundColor": "#ffffff",
    "layers": {
      "bg-image": {
        "id": "bg-image",
        "type": "image",
        "x_position": 50,
        "y_position": 50,
        "width": 100,
        "height": 100,
        "rotate": 0,
        "scale": 1,
        "opacity": 1,
        "zIndex": 0,
        "props": { "src": null }
      },
      "L1": { ... }
    }
  }
)
```

### Regras criticas

| Regra | Detalhe |
|-------|---------|
| `bg-image` SEMPRE primeiro | Layer de fundo obrigatorio com `src: null` — o frontend injeta o blob da imagem gerada |
| `composition_id` = `asset_id` sem extensao | Ex: asset_id `abc123.jpg` → composition_id `abc123` |
| `x_position` / `y_position` em % (0–100) | Relativo ao canvas. 50 = centro |
| `width` / `height` em % (0–100) | Relativo ao canvas. `"auto"` para texto |
| `zIndex` crescente | 0 = fundo, maiores ficam na frente |

---

## Principios de Design (OBRIGATORIO seguir)

### bg-image: SEMPRE full canvas — REGRA INVIOLÁVEL
`bg-image` DEVE ter `width: 100, height: 100` — ocupa 100% do canvas.

> ⛔ PROIBIDO reduzir a imagem para qualquer fim. Imagem com width/height < 100 é ERRO GRAVE.
> ⛔ PROIBIDO criar design com "imagem solta em fundo branco" — isso destrói o impacto visual.
> ✅ SEMPRE trabalhe com texto e elementos NAS FOLGAS DA IMAGEM (áreas vazias, bordas, espaço negativo).

A imagem sempre ocupa o canvas inteiro. Texto, overlays e shapes ficam SOBRE ela.

### Minimalismo: menos e mais
Use no máximo 3–4 layers além do bg-image. Criativos de alto impacto têm poucas camadas bem posicionadas.

| Nao faca | Faca |
|----------|------|
| Fundo preto pesado cobrindo 50%+ da imagem | Gradiente sutil de 20–30% de altura na borda inferior |
| 5+ textos em tamanhos similares | 1 headline dominante + 1 CTA pequeno |
| Texto centralizado sobre a área mais ocupada da foto | Texto em área de espaço negativo da imagem |
| Overlay rect opacidade > 0.5 | Gradient overlay com opacidade 0.6–0.8 e alpha no hex |

### Hierarquia visual

A hierarquia visual **é a razão pela qual um criativo converte**. Escolha UMA das quatro estruturas abaixo e aplique com consistência:

---

#### 1. Hierarquia por Escala e Peso (Contraste Extremo)
O olho humano lê o elemento maior e mais grosso primeiro. Use quando o benefício é imediato e óbvio.
- Headline: **3× maior** que o restante. Font *Black* ou *Extra Bold* (800–900).
- Subtítulo: peso drasticamente menor (*Regular* ou *Light*), tamanho 40–50% do headline.
- CTA: ganha peso pelo botão (rect sólido), não pelo tamanho da fonte.

```
Headline    → fontSize 56–80, fontWeight 900
Subheadline → fontSize 20–28, fontWeight 400
CTA label   → fontSize 16–20, fontWeight 600
```

---

#### 2. Hierarquia por Fluxo de Leitura (F-Shape)
Confia no padrão de leitura Esquerda→Direita, cima→baixo. Ideal para mobile.
- Alinhe **todo** texto à esquerda (`textAlign: "left"`).
- Palavra mais importante = primeira palavra da primeira linha.
- Lado direito da imagem: espaço negativo limpo (não bloqueie o retorno do olho).

---

#### 3. Hierarquia por Espaço Negativo (Minimalismo Premium)
Elemento ganha destaque por estar **sozinho**, não por ser maior.
- Regra dos 40%: pelo menos 40% da área de texto deve ser espaço vazio.
- Margens generosas nas bordas e em relação à imagem.
- `lineHeight: 1.4–1.6` para texto mais arejado.

---

#### 4. Hierarquia por Contraste Cromático (Efeito Von Restorff)
O elemento que difere dos demais é lembrado primeiro.
- Regra 60-30-10: 60% cor dominante no fundo, 30% cor secundária, **10%** cor de conversão.
- Aplique a cor de destaque em **no máximo 2 palavras** do headline ou exclusivamente no botão CTA.
- Cards claros sobre fundo escuro (ou vice-versa) criam "portal de leitura".

---

**Regra universal:** apenas UMA fonte grande (headline ≥ 52px), tudo mais no mínimo 50% menor.

```
Headline    → fontSize 52–72, fontWeight 800–900
Subheadline → fontSize 20–28, fontWeight 500
CTA         → fontSize 16–22, fontWeight 600
Rodapé      → fontSize 12–14, fontWeight 400
```

---

## Contraste de Cores e Legibilidade (CRÍTICO para performance)

> A legibilidade é o fator que mais impacta a performance do criativo **depois da imagem em si**. Um anúncio bonito mas ilegível não converte.

### Regra fundamental: contraste mínimo

| Texto | Fundo | Contraste mínimo (WCAG AA) |
|-------|-------|---------------------------|
| Claro (#FFFFFF, #F5F5F5) | Escuro (#000, tons escuros) | **4.5:1** |
| Escuro (#000, #1A1A1A) | Claro (#FFF, tons claros) | **4.5:1** |

**Nunca coloque texto cinza médio sobre fundo cinza.** Nunca use texto escuro direto sobre foto colorida sem overlay.

### Regras práticas de contraste

1. **Texto sobre foto → sempre adicione overlay ou sombra**
   - Texto branco sobre foto clara → adicione `grad-overlay` escuro ou `shadowEnabled: true, shadowBlur: 12`
   - Texto escuro sobre foto escura → adicione card branco (`glass` ou `rect` semitransparente claro)

2. **Regra das polaridades**
   - Fundo escuro → texto `#FFFFFF` ou `#F0F0F0` (nunca amarelo escuro ou verde escuro)
   - Fundo claro → texto `#000000`, `#1A1A1A` ou cor muito saturada (`#D62828`)
   - Nunca combine dois tons médios (ex: `#888888` sobre `#AAAAAA`)

3. **Tamanho mínimo de fonte para legibilidade em criativo (não é UI)**
   | Tipo | Mínimo absoluto |
   |------|----------------|
   | Headline principal | **42px** |
   | Subheadline / descrição | **20px** |
   | CTA / label de botão | **16px** |
   | Rodapé / legal | **12px** (evitar) |

   > Fontes abaixo de 20px perdem impacto em feed mobile. Preferir **1–2 textos grandes** a 4–5 pequenos.

4. **Fontes finas (Light/Thin) exigem tamanho maior**
   - `fontWeight: 300` → mínimo 48px para headline
   - `fontWeight: 700+` → pode ir em 32–36px na hierarquia secundária

5. **CTA deve ter o maior contraste da composição**
   - Botão CTA: combine cor vibrante com texto oposto (botão verde escuro + texto branco, ou botão branco + texto escuro)
   - Nunca use a mesma cor do headline no botão CTA

---

### Imagens de Referência de Hierarquia Visual

**Consulte estas imagens com `vision()` antes de criar um design para entender as boas práticas:**

```
vision(url="https://prox.app.br/api/proxy/references/design-examples/hierarquia-1.jpg")
vision(url="https://prox.app.br/api/proxy/references/design-examples/hierarquia-2.jpg")
vision(url="https://prox.app.br/api/proxy/references/design-examples/hierarquia-3.png")
```

| Imagem | Técnica demonstrada |
|--------|---------------------|
| `hierarquia-1.jpg` | **Hierarquia por Fluxo F + Overlay Gradiente** — texto alinhado à esquerda, fundo de foto preservado, overlay sutil garantindo legibilidade, CTA com botão verde de alto contraste |
| `hierarquia-2.jpg` | **Hierarquia por Escala Extrema** — elemento numérico ("24h") em tamanho dominante 3× maior que demais textos, criando ponto focal imediato |
| `hierarquia-3.png` | **Hierarquia por Card Branco (portal de leitura)** — card branco sobre foto escura cria zona de alto contraste, isolando o texto da complexidade da imagem. Abordagem de máxima legibilidade. |

> ⚠️ Chame `vision()` para ver as imagens antes de criar o design quando trabalhar com brief novo ou ao ajustar hierarquia visual. As imagens mostram o mesmo copy em 3 abordagens diferentes — use como calibração.

---

### Espaço negativo da imagem
Antes de posicionar texto, identifique via vision() onde estão as áreas mais "vazias" ou de baixo contraste na imagem. Posicione texto nessas zonas. Isso evita conflito visual com o sujeito principal.

Exemplos comuns:
- Produto centralizado → texto nos cantos ou borda inferior
- Modelo em pé (full body) → texto acima da cabeça ou abaixo dos joelhos
- Produto close-up → textura de fundo desfocada ao redor → use essas bordas

### Gradient em vez de rect
Prefira `gradient` a `rect` para overlays. Gradientes preservam mais da imagem original.
```json
{ "gradientColors": ["#00000000", "#000000CC"], "gradientAngle": 90, "height": 25 }
```
Use `height` entre 20–30 para gradientes de borda inferior/superior.

---

## Dimensoes por Aspect Ratio

| Aspect Ratio | width | height |
|---|---|---|
| `1:1` | 1080 | 1080 |
| `4:5` | 1080 | 1350 |
| `9:16` | 1080 | 1920 |
| `16:9` | 1920 | 1080 |

---

## Tipos de Layer

### `image` — Imagem

```json
{
  "id": "bg-image",
  "type": "image",
  "x_position": 50,
  "y_position": 50,
  "width": 100,
  "height": 100,
  "rotate": 0,
  "scale": 1,
  "opacity": 1,
  "zIndex": 0,
  "props": {
    "src": null
  }
}
```

> `src: null` = imagem do asset gerado (injetada automaticamente).
> Para imagem extra: `src: "https://..."`.
> Opcoes: `flipX`, `flipY` (boolean).

---

### `text` — Texto

```json
{
  "id": "L1",
  "type": "text",
  "x_position": 50,
  "y_position": 85,
  "width": "auto",
  "height": "auto",
  "rotate": 0,
  "scale": 1,
  "opacity": 1,
  "zIndex": 2,
  "props": {
    "content": "Frase de impacto aqui",
    "fontSize": 52,
    "fontWeight": "700",
    "fontFamily": "Montserrat",
    "color": "#FFFFFF",
    "textAlign": "center",
    "lineHeight": 1.2,
    "uppercase": true,
    "italic": false,
    "underline": false,
    "strikethrough": false
  }
}
```

**Props opcionais de efeito no texto:**
```json
"strokeColor": "#000000",    // cor do contorno
"strokeWidth": 2,            // espessura do contorno (0 = sem contorno)
"shadowEnabled": true,       // ativa sombra
"shadowColor": "#000000",    // cor da sombra
"shadowBlur": 10,            // blur da sombra
"shadowOffsetX": 4,          // deslocamento horizontal
"shadowOffsetY": 4           // deslocamento vertical
```

**Fontes recomendadas (Google Fonts):**
`Montserrat`, `Inter`, `Poppins`, `Playfair Display`, `Roboto`, `Raleway`, `Oswald`, `Bebas Neue`, `Lato`, `Source Sans Pro`

**Tamanhos de referencia:**
| Uso | fontSize |
|-----|---------|
| Headline principal | 48–72 |
| Subheadline | 28–40 |
| Corpo / chamada | 18–26 |
| Rodape / legal | 12–16 |

---

### `rect` — Retangulo / Overlay

```json
{
  "id": "overlay",
  "type": "rect",
  "x_position": 50,
  "y_position": 50,
  "width": 100,
  "height": 40,
  "rotate": 0,
  "scale": 1,
  "opacity": 0.55,
  "zIndex": 1,
  "props": {
    "backgroundColor": "#000000",
    "borderRadius": 0,
    "strokeColor": null,
    "strokeWidth": 0
  }
}
```

> Use para escurecer/clarear areas do fundo e dar legibilidade ao texto.
> `opacity` entre 0.3–0.7 para overlays semitransparentes.

---

### `gradient` — Gradiente

```json
{
  "id": "grad1",
  "type": "gradient",
  "x_position": 50,
  "y_position": 92,
  "width": 100,
  "height": 30,
  "rotate": 0,
  "scale": 1,
  "opacity": 1,
  "zIndex": 1,
  "props": {
    "gradientColors": ["#00000000", "#000000CC"],
    "gradientAngle": 90
  }
}
```

> `gradientColors`: array de 2–4 cores hex com canal alpha (ex: `#000000CC` = preto 80%).
> `gradientAngle`: 0 = esquerda→direita, 90 = topo→baixo, 180 = direita→esquerda.
> Ideal para gradiente de texto na parte inferior do criativo.

---

### `glass` — Vidro / Blur de Fundo

Elemento transparente com efeito de vidro fosco (backdrop blur). Ideal para caixas de texto legíveis sobre imagens complexas.

```json
{
  "id": "glass-box",
  "type": "glass",
  "x_position": 50,
  "y_position": 80,
  "width": 80,
  "height": 20,
  "rotate": 0,
  "scale": 1,
  "opacity": 1,
  "zIndex": 2,
  "props": {
    "backgroundColor": "rgba(255,255,255,0.15)",
    "blurRadius": 14,
    "borderRadius": 16
  }
}
```

> `backgroundColor`: cor semi-transparente (sempre use rgba). Ex: `rgba(0,0,0,0.3)` para vidro escuro.
> `blurRadius`: intensidade do blur do fundo (0–60px). Recomendado: 10–20.
> `borderRadius`: arredondamento das bordas.

---

### `star` — Estrela

```json
{
  "id": "star1",
  "type": "star",
  "x_position": 85, "y_position": 15,
  "width": 80, "height": 80,
  "rotate": 0, "scale": 1, "opacity": 1, "zIndex": 3,
  "props": {
    "backgroundColor": "#FFD700",
    "starPoints": 5,
    "innerRadius": 20
  }
}
```

> `starPoints`: número de pontas (4–12). `innerRadius`: raio interno relativo (10–45).

---

### `polygon` — Polígono (hexágono, losango, etc.)

```json
{
  "id": "hex1",
  "type": "polygon",
  "x_position": 50, "y_position": 50,
  "width": 120, "height": 120,
  "rotate": 0, "scale": 1, "opacity": 1, "zIndex": 2,
  "props": {
    "backgroundColor": "#6366f1",
    "sides": 6
  }
}
```

> `sides`: número de lados (3–12). 3=triângulo, 4=losango, 6=hexágono.

---

### `emoji` — Emoji / Ícone

```json
{
  "id": "em1",
  "type": "emoji",
  "x_position": 90, "y_position": 10,
  "width": 80, "height": 80,
  "rotate": 0, "scale": 1, "opacity": 1, "zIndex": 4,
  "props": {
    "content": "🔥",
    "backgroundColor": "transparent"
  }
}
```

> Use emojis para adicionar elementos visuais rápidos sem peso de imagem.

---

### `circle` — Circulo

```json
{
  "id": "badge",
  "type": "circle",
  "x_position": 85,
  "y_position": 15,
  "width": 15,
  "height": 15,
  "rotate": 0,
  "scale": 1,
  "opacity": 1,
  "zIndex": 3,
  "props": {
    "backgroundColor": "#FF3B30",
    "strokeColor": "#FFFFFF",
    "strokeWidth": 2
  }
}
```

---

### `line` — Linha / Separador

```json
{
  "id": "divider",
  "type": "line",
  "x_position": 50,
  "y_position": 78,
  "width": 60,
  "height": 2,
  "rotate": 0,
  "scale": 1,
  "opacity": 1,
  "zIndex": 2,
  "props": {
    "strokeColor": "#FFFFFF",
    "strokeWidth": 2,
    "points": [0, 0, 1, 0]
  }
}
```

---

## Estrutura de Camadas Recomendada (ordem zIndex)

```
zIndex 0  — bg-image       (fundo: asset gerado)
zIndex 1  — gradient/rect  (overlay de legibilidade)
zIndex 2  — elementos      (logos, badges, icones)
zIndex 3  — subheadline    (texto secundario)
zIndex 4  — headline       (texto principal)
zIndex 5  — cta / rodape   (chamada para acao)
```

---

## Exemplo Completo — Post Feed 1:1

```javascript
graph_design(
  composition_id="abc123",
  asset_id="abc123.jpg",
  title="Post Feed - Campanha Verao",
  aspect_ratio="1:1",
  composition={
    "dimensions": { "width": 1080, "height": 1080 },
    "backgroundColor": "#000000",
    "layers": {
      "bg-image": {
        "id": "bg-image", "type": "image",
        "x_position": 50, "y_position": 50,
        "width": 100, "height": 100,
        "rotate": 0, "scale": 1, "opacity": 1, "zIndex": 0,
        "props": { "src": null }
      },
      "grad-bottom": {
        "id": "grad-bottom", "type": "gradient",
        "x_position": 50, "y_position": 88,
        "width": 100, "height": 45,
        "rotate": 0, "scale": 1, "opacity": 1, "zIndex": 1,
        "props": { "gradientColors": ["#00000000", "#000000EE"], "gradientAngle": 90 }
      },
      "L-sub": {
        "id": "L-sub", "type": "text",
        "x_position": 50, "y_position": 76,
        "width": "auto", "height": "auto",
        "rotate": 0, "scale": 1, "opacity": 0.85, "zIndex": 3,
        "props": {
          "content": "NOVA COLECAO", "fontSize": 22,
          "fontWeight": "500", "fontFamily": "Montserrat",
          "color": "#F0C040", "textAlign": "center",
          "uppercase": true, "lineHeight": 1.2
        }
      },
      "L-headline": {
        "id": "L-headline", "type": "text",
        "x_position": 50, "y_position": 85,
        "width": "auto", "height": "auto",
        "rotate": 0, "scale": 1, "opacity": 1, "zIndex": 4,
        "props": {
          "content": "Verao que transforma.", "fontSize": 58,
          "fontWeight": "800", "fontFamily": "Playfair Display",
          "color": "#FFFFFF", "textAlign": "center",
          "uppercase": false, "lineHeight": 1.15
        }
      },
      "L-cta": {
        "id": "L-cta", "type": "text",
        "x_position": 50, "y_position": 94,
        "width": "auto", "height": "auto",
        "rotate": 0, "scale": 1, "opacity": 1, "zIndex": 5,
        "props": {
          "content": "Compre agora →", "fontSize": 20,
          "fontWeight": "600", "fontFamily": "Inter",
          "color": "#FFFFFF", "textAlign": "center",
          "uppercase": false, "lineHeight": 1.4
        }
      }
    }
  }
)
```

---

## Exemplo Completo — Story 9:16

```javascript
graph_design(
  composition_id="xyz789",
  asset_id="xyz789.jpg",
  title="Story - Oferta Flash",
  aspect_ratio="9:16",
  composition={
    "dimensions": { "width": 1080, "height": 1920 },
    "backgroundColor": "#000000",
    "layers": {
      "bg-image": {
        "id": "bg-image", "type": "image",
        "x_position": 50, "y_position": 50,
        "width": 100, "height": 100,
        "rotate": 0, "scale": 1, "opacity": 1, "zIndex": 0,
        "props": { "src": null }
      },
      "overlay-top": {
        "id": "overlay-top", "type": "rect",
        "x_position": 50, "y_position": 8,
        "width": 100, "height": 16,
        "rotate": 0, "scale": 1, "opacity": 0.4, "zIndex": 1,
        "props": { "backgroundColor": "#000000", "borderRadius": 0 }
      },
      "grad-bottom": {
        "id": "grad-bottom", "type": "gradient",
        "x_position": 50, "y_position": 80,
        "width": 100, "height": 50,
        "rotate": 0, "scale": 1, "opacity": 1, "zIndex": 1,
        "props": { "gradientColors": ["#00000000", "#000000F0"], "gradientAngle": 90 }
      },
      "L-badge": {
        "id": "L-badge", "type": "text",
        "x_position": 50, "y_position": 8,
        "width": "auto", "height": "auto",
        "rotate": 0, "scale": 1, "opacity": 1, "zIndex": 3,
        "props": {
          "content": "⚡ OFERTA FLASH — 24H", "fontSize": 26,
          "fontWeight": "700", "fontFamily": "Montserrat",
          "color": "#FFD700", "textAlign": "center", "uppercase": true
        }
      },
      "L-headline": {
        "id": "L-headline", "type": "text",
        "x_position": 50, "y_position": 70,
        "width": "auto", "height": "auto",
        "rotate": 0, "scale": 1, "opacity": 1, "zIndex": 4,
        "props": {
          "content": "50% OFF\nso hoje.", "fontSize": 80,
          "fontWeight": "900", "fontFamily": "Oswald",
          "color": "#FFFFFF", "textAlign": "center",
          "uppercase": true, "lineHeight": 1.05
        }
      },
      "L-cta": {
        "id": "L-cta", "type": "text",
        "x_position": 50, "y_position": 88,
        "width": "auto", "height": "auto",
        "rotate": 0, "scale": 1, "opacity": 1, "zIndex": 5,
        "props": {
          "content": "Arraste para cima e garanta o seu", "fontSize": 22,
          "fontWeight": "500", "fontFamily": "Inter",
          "color": "#CCCCCC", "textAlign": "center"
        }
      }
    }
  }
)
```

---

## 🚫 Como cancelar o fluxo

```
cancel(cancel=true, reason="Usuario decidiu nao criar o design agora")
```

---

## Erros Comuns

| Erro | Causa | Correcao |
|------|-------|----------|
| `bg-image` ausente | Layer de fundo obrigatorio nao incluido | Sempre inclua `bg-image` com `src: null` e `zIndex: 0` |
| `bg-image` com `width` ou `height` < 100 | Tentativa de "abrir espaço" para texto | **NUNCA faça isso.** Imagem DEVE ser `width: 100, height: 100` sempre |
| Imagem solta em fundo branco | `backgroundColor: "#ffffff"` com `bg-image` pequeno | Imagem ocupa 100% do canvas; texto vai SOBRE ela nas folgas |
| `composition_id` com extensao | Ex: `abc123.jpg` em vez de `abc123` | Remova a extensao |
| `x_position` / `y_position` em pixels | Deve ser 0–100 (percentual) | Divida pelo canvas width/height e multiplique por 100 |
| Texto fora do canvas | `x_position` ou `y_position` > 95 | Mantenha dentro de 5–95 para safe area |
| Fonte nao carregada | Nome digitado errado ou fonte nao suportada | Use fontes da lista recomendada (Google Fonts) |
