# Tools — Referência de Ferramentas

Para carregar as instruções completas de qualquer ferramenta:
```
help(name="nome_da_tool")
```

---

## Comunicação

| Tool | Descrição |
|------|-----------|
| `message` | Enviar mensagem ao usuário. `message(message="...")` |
| `quiz` | Fazer pergunta com opções ao usuário — bloqueante. `help(name="quiz")` |

---

## Raciocínio e Contexto

| Tool | Descrição |
|------|-----------|
| `chain-of-thought` | Raciocínio interno estruturado — use na língua do usuário, em 1ª pessoa. Nunca 2× consecutivo. `chain-of-thought(steps=["Analisei X", "Conclusão: Y"])` |
| `context` | Recuperar documentos, dados de cliente, tasks e mídia de chats anteriores. `help(name="context")` |

---

## Pesquisa e Web

| Tool | Descrição |
|------|-----------|
| `web-search` | Buscar no Google, extrair URLs, analisar design. `help(name="web-search")` |
| `youtube_transcript` | Extrair transcrição de vídeos do YouTube. `help(name="youtube_transcript")` |

---

## Conteúdo e Assets

| Tool | Descrição |
|------|-----------|
| `document` | Salvar análises, copies e identidade visual como documentos. `help(name="document")` |
| `client` | Persistir dados estratégicos do cliente entre chats. `help(name="client")` |
| `schedule` | Planejar e agendar posts em redes sociais. `help(name="schedule")` |
| `asset` | Gerar imagens e vídeos com IA vinculados a posts. `help(name="asset")` |
| `vision` | Analisar imagens com IA. `help(name="vision")` |
| `generate_temporary_public_url` | Converter attachment_id ou arquivo local em URL pública para usar em outras tools. `help(name="generate_temporary_public_url")` |
| `gen_free_image` | Gerar imagem gratuita com IA (sem custo por crédito). `help(name="gen_free_image")` |

---

## Tarefas e Fluxo

| Tool | Descrição |
|------|-----------|
| `task` | Criar pipelines de trabalho com etapas rastreáveis (copywriting). `help(name="task")` |
| `steps` | Registrar passos de qualquer tarefa sem interromper o loop. `help(name="steps")` |
| `skill` | Carregar um skill específico de produção. `skill(name="NomeDoSkill")` |
| `lookup` | Carregar arquivo de instrução de skill. `lookup(file="SkillNome.md")` |
| `cancel` | Cancelar operação assíncrona em andamento |
| `file` | Operações com arquivos no sandbox |

---

## Integrações Externas

| Tool | Descrição |
|------|-----------|
| `launch` | Registrar lançamentos financeiros em partidas dobradas. `help(name="launch")` |
| `leads` | CRUD de leads individuais no CRM. `help(name="leads")` |
| `crm` | Análise de funil, segmentação e cohorts de marketing. `help(name="crm")` |
| `marketing` | Métricas e dados de campanhas de marketing |
| `rag_query` | Consultar base de conhecimento com RAG. `help(name="rag_query")` |
| `escalate` | Escalar conversa para atendimento humano — para o agente e notifica o painel. `help(name="escalate")` |
| `send` (Resend) | Enviar e-mails transacionais. `help(name="mcp__resend__send_email")` |
| `meta-ads` | Gerenciar campanhas no Meta Ads. `help(name="meta-ads")` |
| `instagram` | Publicar, DMs e insights do Instagram Business. `help(name="instagram")` |
| `github` | Leitura de código, issues, PRs e escrita segura via branches. `help(name="github")` |
| `google-drive` | Buscar, ler, criar e atualizar arquivos no Google Drive. `help(name="google-drive")` |
| `google-calendar` | Listar, criar, atualizar e deletar eventos na agenda. `help(name="google-calendar")` |
| `gmail` | Listar, ler e enviar e-mails pelo Gmail. `help(name="gmail")` |
| `google-analytics` | Relatórios GA4 com métricas e dimensões customizadas. `help(name="google-analytics")` |
| `google-ads` | Gerenciar campanhas, ad groups e anúncios no Google Ads. `help(name="google-ads")` |
| `google-tasks` | Listar tarefas e listas do Google Tasks. `help(name="google-tasks")` |
| `linkedin` | Publicar no LinkedIn e consultar métricas de ads. `help(name="linkedin")` |
| `brand` | Análise e mapeamento de identidade de marca. `help(name="brand")` |
| `dashboard` | Dados e métricas do dashboard do cliente. `help(name="dashboard")` |

---

## Ferramentas de Sistema

| Tool | Descrição |
|------|-----------|
| `terminal` | Executar comandos no terminal. **Obrigatório:** `help(name="terminal")` antes de usar. |
| `user_browser` | Controlar o browser real do usuário. **Obrigatório:** `help(name="user_browser")` + quiz de autorização antes de usar. |
| `graph_design` | Criar gráficos e visualizações de dados. **Obrigatório:** `help(name="graph_design")` antes de usar. |
| `convert_image` | Converter imagens entre formatos (PIL) |
| `write_file` | Escrever arquivos no sandbox do usuário. `help(name="write_file")` |

---

## Skills Disponíveis

Skills são módulos de instrução carregados via `lookup(file="SkillNome.md")`.

| Skill | Uso |
|-------|-----|
| `SkillCopywriting.md` | Criativos para anúncios pagos (Meta, Google, TikTok Ads) |
| `SkillSocialMedia.md` | Conteúdo orgânico para redes sociais |
| `SkillCatalog.md` | Imagens de catálogo para e-commerce |
| `SkillSelfKnowledge.md` | Identidade estratégica da marca — recomendado como primeiro passo |
| `SkillBusinessCanvas.md` | Proposta de valor, ICP, lifecycle e sizing de mercado |
| `SkillBrandIdentity.md` | Identidade visual: arquétipo, paleta, tipografia, tom |
| `SkillProduct.md` | Mapeamento de produto para copywriting |
| `SkillCompetitorAnalysis.md` | Benchmarking de concorrentes |
| `SkillUserBrowsing.md` | Controle de browser real do usuário |
