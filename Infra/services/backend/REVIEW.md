# Revisões Pendentes

## [VARIAÇÕES] Quiz de Canais e Formatos

**O que falta**: O fluxo de variação não coleta canais nem formatos antes de gerar o documento/asset.
No fluxo de produção normal, a Etapa 2 do quiz exige:
- `channels` — canais onde o criativo vai rodar (instagram, facebook, google...)
- `aspect_ratio` — derivado automaticamente dos canais selecionados pelo validador

No fluxo de variação, o agente passa `channels` e `aspect_ratio` direto no documento sem perguntar ao usuário, o que pode gerar formatos incorretos.

**Proposta**: Adicionar quiz de Etapa 2 ao fluxo de variação (após image_selection ou após vision no attachment), com pelo menos:
- `channels` — para derivar os formatos corretos
- Opcionalmente `asset_quantity` — para controlar quantos assets gerar por variação

**Referências**:
- Gate atual da Etapa 2: `_quiz.py:1123`
- Derivação de aspect_ratio por canal: `_document_validators.py:1869`
- SkillCopywriting.md — seção "Variações A/B"

---

## [VARIAÇÕES] Múltiplos prompts para category="Criativo"

**O que foi feito**: O expansor agora usa o `prompt` do `variation_N` como primário, com fallback para o `assets[0].prompt` e para o campo `style` da variação. Isso resolve o caso imediato.

**O que ainda pode melhorar**: O agente deveria incluir um `prompt` completo (objeto estruturado) em cada `variation_N` quando `category = "Criativo"`, não apenas `style` como string. O SkillCopywriting.md precisa documentar o schema esperado de `variation_N.prompt`.

**Schema ideal de variation_N para Criativo**:
```json
{
  "variation_1": {
    "prompt": {
      "description": "Studio premium clean — produto centralizado, fundo branco...",
      "composition": { "angle": "CloseUpShot", "grid": "Centralized" },
      "environment": { "place": "Estúdio profissional", "objects": ["frasco do produto"] },
      "colors": { "background": { "hex": ["#FFFFFF"], "bg_type": "color" } }
    }
  }
}
```
