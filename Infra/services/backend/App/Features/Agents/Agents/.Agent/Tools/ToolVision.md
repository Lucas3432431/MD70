# vision — Analisar Imagens com IA

**Objetivo:** Analisar imagens usando visão computacional — descrever elementos visuais, extrair informações e avaliar design.

## Exemplo
```
vision(
  prompt="Descreva em detalhes os elementos visuais, cores, tipografia e layout",
  image_input="https://exemplo.com/imagem.jpg",
  temperature=0.7,
  wait=true
)
```

## Parâmetros

| Parâmetro | Tipo | Descrição |
|-----------|------|-----------|
| `prompt` | string (obrigatório) | Pergunta ou instrução sobre a imagem |
| `image_input` | string (obrigatório) | URL pública (`https://`) ou data URI (base64) |
| `temperature` | float | Criatividade da análise: 0.0–1.0 (padrão: 0.7) |
| `wait` | boolean | `true` = aguarda resultado (padrão) \| `false` = background |

## Regra de ouro — attachment_id NÃO funciona diretamente

```
// ❌ ERRO
vision(image_input="attach_a1b2c3")

// ✅ CORRETO — converter primeiro
url = generate_temporary_public_url(attachment_id="attach_a1b2c3")
vision(prompt="...", image_input=url["url"])

// ✅ URLs externas diretas funcionam sem conversão
vision(prompt="...", image_input="https://site.com/img.jpg")
```

## Imagens pré-analisadas

Se a mensagem do usuário contiver `[IMAGEM UUID: ...]` + `[DESCRIÇÃO]`, a imagem **já foi processada**. **Não chame `vision()` novamente** — use a descrição fornecida.

**Retorna:** Análise textual detalhada da imagem.
