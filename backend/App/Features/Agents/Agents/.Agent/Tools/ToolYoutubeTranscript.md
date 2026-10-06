# Tool: youtube_transcript

Busca a transcrição completa de um vídeo do YouTube. Não requer autenticação.

## Parâmetros

| Parâmetro | Tipo | Obrigatório | Descrição |
|-----------|------|-------------|-----------|
| `video_url` | string | Sim | URL completa do YouTube ou video_id (11 chars). Aceita: `youtube.com/watch?v=ID`, `youtu.be/ID`, `youtube.com/shorts/ID` |
| `languages` | string | Não | Idiomas em ordem de prioridade, separados por vírgula. Padrão: `"pt,en"` |
| `include_timestamps` | boolean | Não | Se `true`, inclui `[MM:SS]` em cada linha. Padrão: `false` |

## Retorno

```json
{
  "success": true,
  "video_id": "dQw4w9WgXcQ",
  "language": "pt",
  "segment_count": 142,
  "duration": "03:32",
  "transcript": "Texto completo da transcrição..."
}
```

Em caso de erro:
```json
{
  "success": false,
  "error": "Transcrição não disponível"
}
```

## Exemplos de uso

```python
# Transcrição em PT ou EN (padrão)
youtube_transcript(video_url="https://www.youtube.com/watch?v=dQw4w9WgXcQ")

# Preferir EN, fallback PT, com timestamps
youtube_transcript(video_url="https://youtu.be/dQw4w9WgXcQ", languages="en,pt", include_timestamps=True)

# Usando video_id diretamente
youtube_transcript(video_url="dQw4w9WgXcQ")
```

## Casos de erro comuns

- `"Transcrição não disponível"`: o vídeo não tem legendas ativadas ou o criador desativou a transcrição
- `"Não foi possível extrair video_id"`: URL inválida ou em formato não suportado
- Vídeos privados ou com restrição geográfica podem não ter transcrição acessível

## Dicas

- Use `include_timestamps=true` quando precisar referenciar momentos específicos do vídeo
- Para análise de conteúdo, o texto contínuo (padrão) é mais adequado
- A transcrição pode ser automática (gerada pelo YouTube) ou manual (enviada pelo criador) — a qualidade varia
