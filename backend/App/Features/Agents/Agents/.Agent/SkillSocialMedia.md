# Social Media Skill

> Use esta skill para conteudo ORGANICO em redes sociais.
> Para anuncios pagos, use SkillCopywriting.md (Paid Ads).

---

## Sequencia Obrigatoria

```
1. lookup(file="SkillSocialMedia.md")
2. quiz([...])   — 4 perguntas JUNTAS em UMA unica chamada
        |
        +-- SE Attachment --> vision(image_input="<attach_id>")
        |                             |
        |                             v
        |                     document(type="social_media", data={...})
        |
        +-- SE Link -------> web-search(fetch="<url>", visual-analysis="<url>")
                                      |
                                      v
                             quiz([{ type: "image_selection", ... }])
                                      |
                                      v
                             vision(image_input="<url_confirmada>")
                                      |
                                      v
                             document(type="social_media", data={...})
                                      |
                         (ambos os fluxos convergem aqui)
                                      v
                             asset(document_id="<uuid>")
```

> CRITICO: As 4 perguntas do quiz inicial devem ser enviadas JUNTAS em UMA unica chamada quiz().

---

## Quiz Inicial (4 perguntas — unica chamada)

> OBRIGATORIO: A pergunta com `attachment: true` deve ser a SEGUNDA do quiz (apos formato).

```javascript
// Template: Quiz de Social Media — todas as 4 perguntas em UMA chamada
quiz([
  {
    question: "Qual o formato do conteudo?",
    type: "multiple_choice",
    // Story = 9:16 | Carrossel = sequencia de slides 4:5 | Photo = imagem unica 1:1 ou 4:5
    options: ["Story (9:16)", "Carrossel (4:5)", "Photo (1:1)", "Photo (4:5)"]
  },
  {
    question: "Qual a inspiracao ou base visual? (cole URL ou faca upload do attachment)",
    type: "url",
    options: [],
    // true = aceita upload de imagem como referencia
    attachment: true
  },
  {
    question: "Qual o tipo de conteudo?",
    type: "multiple_choice",
    // Define a intencao estrategica do post
    options: ["Branding", "Educacional", "Awareness", "Conversao"]
  },
  {
    question: "Qual o canal principal?",
    type: "multiple_choice",
    options: ["Instagram", "TikTok", "Pinterest", "LinkedIn", "YouTube"]
  }
])
```

### Como ler a resposta do quiz

- `final_answers[0].answer` → formato selecionado (ex: "Story (9:16)")
- `final_answers[1].answer` → "attach_XXXXXXXX" (upload) ou URL da inspiracao
- `final_answers[2].answer` → tipo de conteudo
- `final_answers[3].answer` → canal

Converta o formato para aspect_ratio:
| Resposta | aspect_ratio |
|---|---|
| Story (9:16) | `"9:16"` |
| Carrossel (4:5) | `"4:5"` |
| Photo (1:1) | `"1:1"` |
| Photo (4:5) | `"4:5"` |

---

## Fluxo Attachment

```
quiz([...])   — final_answers[1].answer contem "attach_XXXXXXXX"
vision(image_input="attach_XXXXXXXX")
document(type="social_media", data={ reference_image: "attach_XXXXXXXX", ... })
asset(document_id="<uuid>")
```

> Attachment ja foi curado pelo usuario — nao precisa de quiz de confirmacao de imagem.

---

## Fluxo Link (URL)

```
quiz([...])   — final_answers[1].answer contem a URL
web-search(fetch="<url>", visual-analysis="<url>")
quiz([{
  question: "Extrai algumas imagens do seu produto, qual imagem voce prefere usar como referencia?",
  type: "image_selection",
  options: ["<url1.jpg>", "<url2.png>", ...]
}])
vision(image_input="<url_imagem_confirmada>")
document(type="social_media", data={ reference_image: "<url_confirmada>", ... })
asset(document_id="<uuid>")
```

---

## Estrutura Obrigatoria do Documento

```javascript
// Template: document(type="social_media") — campos obrigatorios e opcionais
document(
  type="social_media",
  title="[Marca] - [Tipo] - [Formato]",
  data={
    // OBRIGATORIOS
    "format": "story",           // story | carrossel | photo
    "content_type": "branding",  // branding | educational | awareness | conversion
    "channels": ["instagram"],   // array de canais
    "reference_image": "attach_XXXXXXXX",  // attach_id ou URL confirmada

    // Texto do post
    "caption": "Legenda completa com hashtags e CTA",

    // OPCIONAIS — contexto da marca
    "archetype": "lider_visionario",
    "moodboard": "Referencia visual da marca",

    // Assets a gerar — minimo 1
    "assets": [
      {
        "asset_type": "img",
        "prompt": { /* ver secao Assets abaixo */ }
      }
    ]
  }
)
```

### Tipos de Conteudo e sua Intencao

| content_type | Objetivo | Tom |
|---|---|---|
| `branding` | Reforcar identidade/valores da marca | Emocional, aspiracional |
| `educational` | Ensinar algo relevante para o publico | Claro, instrutivo |
| `awareness` | Apresentar problema ou solucao | Provocativo, empático |
| `conversion` | Gerar acao (compra, link, DM) | Urgente, direto |

---

## Estrutura do Campo `assets`

O campo `prompt` deve ser um objeto, NAO uma string.

```javascript
// Template: asset individual para Social Media
{
  "asset_type": "img",
  "prompt": {
    // Descricao geral da cena — contexto visual completo
    "description": "Post de branding em ambiente urbano, paleta tons terrosos",
    "has_realistic_people": true,
    "subject_context": "Jovem profissional em espaco de trabalho criativo",
    "models": [
      {
        "sex": "female",
        "age": "25-30",
        "skin_color": "brown",
        "style": "creative casual",
        // Textura de pele: natural_glow | dewy | wet
        "skin_texture_moisture": "natural_glow"
      }
    ],
    "pose": "Sentada, relaxada, olhando para fora do frame, expressao tranquila",
    "composition": {
      // Angulo: OverheadDroneShot | CloseUpShot | MidBodyShot | EyeLevelShot | UGC | Studio
      "angle": "MidBodyShot",
      "grid": "RuleOfThirds"
    },
    "environment": {
      "place": "Cafe urbano, janelas grandes, luz natural",
      "objects": [
        { "item": "Xicara de cafe", "focus": true },
        "Notebook aberto ao fundo"
      ]
    },
    "colors": {
      // bg_type: color | outside | window | black_white | product_closeup
      "background": { "hex": ["#C8A882"], "bg_type": "outside" },
      "subject": { "hex": ["#3D2B1F"] },
      "accent": { "hex": ["#F5EFE6"] },
      "saturation_contrast": "Warm tones, soft contrast",
      "harmony": "Analogous"
    },
    "illumination": "Natural window light, golden hour",
    "emotion_style": "Relaxed, authentic, aspirational"
  }
}
```

**Regras de angulo e bg_type:**

| Cenario | Angulos validos | bg_type validos |
|---|---|---|
| `has_realistic_people: true` | Todos os angulos | Todos os bg_type |
| `has_realistic_people: true` + bg `window` ou `color` | Apenas `CloseUpShot`, `HyperCloseUpShot` | — |
| `has_realistic_people: false` (produto) | `CloseUpShot`, `DetailShot`, `HyperCloseUpShot` | `window`, `color`, `product_closeup` |
| `UGC` | Camera informal, handheld, nao posado | qualquer bg_type |

---

## Formato e Aspect Ratio para Assets

| format | aspect_ratio no prompt | Observacao |
|---|---|---|
| `story` | `"9:16"` | Vertical full-screen |
| `carrossel` | `"4:5"` | Cada slide individual |
| `photo` | `"1:1"` ou `"4:5"` | Feed padrao |

Para **Carrossel**: crie um asset por slide, com narrativa progressiva entre eles.

---

## Cancelar o Fluxo

Se o usuario desistir:

```
cancel(cancel=true, reason="Usuario decidiu nao seguir com a criacao de conteudo")
```
