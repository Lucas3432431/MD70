# Leads — Gerenciamento de Leads/Contatos CRM

**Objetivo:** Consultar, criar, atualizar e remover leads individuais do CRM. Use `crm()` para visões analíticas macro (funil, segmentos, cohorts).

## Ações disponíveis

| Ação | O que faz |
|------|-----------|
| `read` | Consulta leads com filtros. Retorna lista de leads. |
| `post` | Cria novo lead manualmente (sem conversa pré-existente). |
| `patch` | Atualiza campos de um lead existente (identifica por `chat_id`). |
| `delete` | Remove um lead e seu histórico de alterações. |

---

## Comportamento obrigatório ao cadastrar ou atualizar leads

**Quando o usuário pedir para cadastrar um lead ou atualizar informações, conduza uma entrevista ativa.** Não crie o lead com apenas o nome — colete o máximo de informações possível fazendo perguntas ao usuário.

### Perguntas obrigatórias (sempre pergunte)
1. **Nome completo** — se ainda não informado
2. **Contato** — e-mail e/ou telefone
3. **Produto/serviço de interesse** e valor estimado
4. **Origem** — como esse lead chegou até você? (indicação, campanha, redes sociais, busca orgânica...)
5. **Nível de consciência** — explique as opções e peça para o usuário escolher:
   - 1 = Não sabe que tem o problema
   - 2 = Sabe que tem o problema, mas não conhece solução
   - 3 = Conhece soluções, mas não seu produto especificamente
   - 4 = Conhece seu produto, está avaliando
   - 5 = Pronto para comprar, só precisa da oferta certa
6. **Qualificação** — com base no que o usuário conta, avalie e confirme:
   - 1 = Frio (sem interesse claro)
   - 2 = Morno (interesse, mas sem urgência)
   - 3 = Quente (interesse real, budget provável)
   - 4 = Muito quente (quer comprar em breve)
   - 5 = Pronto para fechar

### Perguntas complementares (pergunte quando relevante)
- **Dores e ambições** — qual o principal problema que quer resolver? O que quer conquistar?
- **Objeções** — tem alguma preocupação ou barreira para avançar? (preço, prazo, concorrente...)
- **Cargo/perfil** — qual a função dele na empresa? É o decisor?
- **Próximo follow-up** — quando você quer retomar o contato?
- **Observações livres** — algo importante para anotar sobre essa conversa?

### Como conduzir
- Faça as perguntas de forma natural, como numa conversa — não num formulário rígido
- Se o usuário já deu informações na descrição do pedido, não repita as perguntas — use o que foi dito
- Use `quiz()` se quiser estruturar as opções de nível de consciência e qualificação
- Só chame `leads(action="post")` ou `leads(action="patch")` depois de ter coletado o suficiente
- Ao final, confirme o que foi salvo resumindo as informações em uma mensagem clara

---

## Fluxo padrão para trabalhar com leads

```
1. leads(action="read", limit=20)         ← lista leads recentes
2. leads(action="read", search="João")    ← busca por nome/email/telefone
3. leads(action="patch", chat_id="...", qualification=4, notes="...")  ← atualiza
```

> **chat_id** é a chave de identificação do lead. Sempre obtenha via `read` antes de usar `patch` ou `delete`.

---

## Campos do lead

### Identificação e contato
- `name` (texto) — Nome completo
- `email` (texto) — E-mail
- `phone` (texto) — Telefone com DDD

### Posição no funil
- `funnel_stage` (texto) — Estágio atual:
  - **Consultivo:** `nao_atendido` → `atendido` → `agendamento` → `reuniao` → `proposta` → `fechado`
  - **Pós-venda:** `sucesso` | `indicacao` | `expansao`
  - **Isolados:** `recuperacao` | `perdido` | `suporte`
  - **Self-service:** `carrinho` → `checkout` → `formulario` → `pago`
  - **ACP:** `audiencia` → `comunidade` → `produto`

### Qualificação e perfil
- `consciousness_level` (1-5):
  - 1 = Inconsciente do problema
  - 2 = Consciente da dor
  - 3 = Consciente da solução
  - 4 = Consciente do produto
  - 5 = Consciente da oferta (pronto para comprar)
- `qualification` (1-5):
  - 1 = Frio, 2 = Morno, 3 = Quente, 4 = Muito quente, 5 = Pronto para comprar
- `role` — Cargo ou função
- `demographics` — Dados demográficos (texto ou JSON)
- `mql_level` — Nível MQL (Marketing Qualified Lead)

### Origem
- `origin_type` — `campaign` | `referral` | `social_media` | `search` | `direct` | `event` | `other`
- `origin_detail` — Detalhe da origem (ex: nome da campanha, quem indicou)
- `source_url` — URL de onde o lead veio

### Produto e negócio
- `product_service` — Produto/serviço de interesse
- `product_link` — Link do produto
- `product_value` — Valor estimado do negócio
- `payment_method` — Forma de pagamento preferida
- `products_history` — Histórico de compras/interações anteriores

### Comportamento e objeções
- `pains_ambitions` — Dores e ambições identificadas
- `objections` — Objeções levantadas durante a negociação
- `notes` — Observações livres (notes de atendimento)

### CRM e rastreamento
- `cohort_ids` (array de strings) — IDs dos cohorts CRM ao qual pertence
- `dre_launch_ids` (array de strings) — IDs de lançamentos financeiros vinculados
- `next_followup` — Data/hora do próximo follow-up (ISO 8601)

---

## Exemplos de uso

### Listar leads em proposta
```
leads(action="read", funnel_stage="proposta", limit=30)
```

### Buscar lead pelo nome ou email
```
leads(action="read", search="maria@empresa.com")
```

### Leads não atendidos de campanha específica
```
leads(action="read", funnel_stage="nao_atendido", origin_type="campaign", limit=50)
```

### Leads quentes (qualification >= 4) — filtre no resultado
```
leads(action="read", qualification=4, limit=100)
```

### Criar lead manualmente
```
leads(action="post",
  name="Carlos Silva",
  email="carlos@empresa.com",
  phone="11999990000",
  funnel_stage="atendido",
  consciousness_level=3,
  qualification=3,
  origin_type="referral",
  origin_detail="Indicado por João Almeida",
  product_service="Consultoria Estratégica",
  product_value="R$ 8.000"
)
```

### Atualizar estágio e qualificação
```
leads(action="patch", chat_id="<uuid>", funnel_stage="proposta", qualification=4)
```

### Registrar objeções e próximo follow-up
```
leads(action="patch", chat_id="<uuid>",
  objections="Preço acima do orçamento. Quer parcelamento.",
  next_followup="2025-08-15T10:00:00",
  notes="Reunião agendada para apresentar proposta parcelada."
)
```

### Vincular lead a cohorts de campanha
```
leads(action="patch", chat_id="<uuid>", cohort_ids=["cohort-uuid-meta-jul25"])
```

### Ver histórico de alterações de um lead
```
leads(action="read", chat_id="<uuid>", include_logs=true)
```

### Deletar lead
```
leads(action="delete", chat_id="<uuid>")
```

---

## Parâmetros de leitura (action="read")

| Parâmetro | Tipo | Descrição |
|-----------|------|-----------|
| `chat_id` | string | Busca lead específico por ID |
| `search` | string | Texto livre em nome, email e telefone |
| `funnel_stage` | string \| string[] | Filtra por estágio (aceita array) |
| `origin_type` | string | Filtra por tipo de origem |
| `consciousness_level` | integer | Filtra por nível de consciência |
| `qualification` | integer | Filtra por qualificação |
| `cohort_id` | string | Filtra leads deste cohort |
| `date_from` | YYYY-MM-DD | updated_at >= |
| `date_to` | YYYY-MM-DD | updated_at <= |
| `limit` | integer | Máx registros (padrão 50, máx 500) |
| `include_logs` | boolean | Inclui histórico de alterações |

---

## Resposta do read

```json
{
  "success": true,
  "action": "read",
  "total": 12,
  "leads": [
    {
      "id": "uuid",
      "chat_id": "uuid",
      "name": "Maria Santos",
      "email": "maria@empresa.com",
      "funnel_stage": "proposta",
      "consciousness_level": 4,
      "qualification": 4,
      "origin_type": "campaign",
      "product_value": "R$ 5.000",
      "cohort_ids": ["cohort-meta-jul25"],
      "updated_at": "2025-07-04T15:30:00"
    }
  ]
}
```
