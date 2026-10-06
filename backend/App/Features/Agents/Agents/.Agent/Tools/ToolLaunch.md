# Launch — Lançamentos Financeiros

**Objetivo:** Registrar lançamentos financeiros em **partidas dobradas assimétricas** — múltiplos débitos e/ou créditos, com totais equilibrados.

## Sequência obrigatória

```
1. help(name="launch")              ← carrega estas instruções
2. terminal(cmd="date +%Y-%m-%d")   ← confirma a data atual antes de qualquer lançamento
3. launch(action="...")             ← executa a operação
```

> **Sempre verifique a data atual via `terminal` antes de preencher `occurred_at` e `competence_at`.** Nunca assuma o ano ou mês — use o resultado do terminal como âncora.

---

## Como coletar as informações do usuário

Solicite os dados em uma das formas abaixo — você classifica e estrutura:

**1. Upload de documento**
> "Envie a fatura, extrato bancário, nota fiscal ou comprovante de pagamento."

Leia com `document()` ou `vision()`, extraia os lançamentos e registre em lote via `launches=[...]`.

**2. Áudio ou texto livre**
> "Descreva o que foi pago ou recebido: valor, data, de quem, para quê."

Mapeie a descrição para os campos de débito/crédito usando a lógica de classificação abaixo.

---

## Classificação assistida — o usuário provavelmente não sabe contabilidade

**Parta do princípio que o usuário não conhece os termos contábeis.** Nunca pergunte "qual é a classification?" diretamente. Em vez disso, siga este fluxo:

### Passo 1 — Perguntar se já tem classificação definida

> "Você já tem um plano de contas ou sabe em que categoria essa conta costuma entrar? (Ex: custo de produto, despesa administrativa, receita de venda...)"

- **Se sim:** use a resposta como âncora e mapeie para a segmentação mais próxima.
- **Se não:** siga para o Passo 2.

### Passo 2 — Consultar documentos da marca

Use `context(action="lookup")` ou `rag_query(query="...")` para buscar informações sobre o negócio — o que a empresa faz, quais são seus produtos/serviços, modelo de receita. Isso orienta as perguntas de classificação.

### Passo 3 — Perguntas de indução por natureza do gasto/receita

Faça **uma pergunta por vez**, em linguagem simples, e use a resposta para determinar a segmentação. Guia de perguntas:

**Para pagamentos / saídas:**

| Pergunta | Se sim → segmentação provável |
|----------|-------------------------------|
| "Esse gasto faz parte direto de entregar o produto ou serviço ao cliente? (matéria-prima, mão de obra direta, plataforma ou ferramenta essencial para o serviço...)" | `(-) CMV/CSV` |
| "É um custo fixo de operação — aluguel, contador, internet, software de gestão?" | `(-) Despesas Gerais e Administrativas` |
| "É gasto com divulgação, anúncios, agência de marketing, influenciadores?" | `(-) Despesas com Vendas / Marketing` |
| "É salário, pró-labore, benefícios ou encargos de funcionários?" | `(-) Despesas Gerais e Administrativas` ou `Salários e Contribuições` (PC) |
| "É pagamento de parcela de empréstimo ou financiamento?" | `Empréstimos` (PC) ou `Empréstimos (NC)` (PNC) |
| "É imposto — DAS, IRPJ, CSLL, ISS, ICMS?" | `(-) Impostos` |
| "É devolução de um pagamento recebido antes, adiantamento ou depósito?" | `Adiantamento a Diretores` (AC) ou `Outras Contas a Pagar` (PC) |
| "É aquisição de equipamento, software ou ativo que vai durar mais de 1 ano?" | `Intangível` ou `Outros Ativos Não Circulantes` (ANC) |

**Para recebimentos / entradas:**

| Pergunta | Se sim → segmentação provável |
|----------|-------------------------------|
| "É receita de venda do produto ou serviço principal da empresa?" | `(+) Receita` |
| "É receita de outra fonte — aluguel de espaço, juros recebidos, venda de ativo?" | `(+) Outras Receitas` |
| "É um empréstimo ou aporte que precisa ser devolvido?" | `Empréstimos` (PC) ou `Caixa` (AC) contra `Empréstimos` |
| "É aporte dos sócios sem previsão de devolução?" | `PL` |

### Passo 4 — Confirmar antes de lançar

Depois de concluir a classificação, apresente um resumo em linguagem simples antes de registrar:

> "Vou registrar como: **[descrição humana]** — débito em [conta] e crédito em [conta], valor R$ X. Confirma?"

Só chame `launch(action="post", ...)` após confirmação explícita do usuário.

---

## Princípio de partidas dobradas (assimétricas)

Cada lançamento tem **N débitos** e **M créditos** — os números podem ser diferentes, mas os **totais devem ser iguais**:

```
sum(debits.amount) == sum(credits.amount)
```

**Exemplo assimétrico — venda parcelada (1 débito, 2 créditos):**
```
Débito:  (+) Receita          R$ 1.000   [DRE]
Crédito: Caixa                R$   100   [AC]
Crédito: Contas a Receber     R$   900   [AC]
```

**Exemplo assimétrico — pagamento de múltiplas contas com um cheque (2 débitos, 1 crédito):**
```
Débito:  Fornecedores a Pagar R$   600   [PC]
Débito:  Aluguéis a Pagar     R$   400   [PC]
Crédito: Caixa                R$ 1.000   [AC]
```

---

## Regras de validação

| Regra | Descrição |
|-------|-----------|
| `amount > 0` | Cada linha individual deve ter valor positivo |
| `sum(débitos) == sum(créditos)` | Tolerância de 0,001 |
| Pelo menos 1 débito e 1 crédito | Obrigatório |
| Não pode ser tudo DRE | Pelo menos uma conta BP deve existir no lançamento |
| DRE↔DRE proibido | Ambos os lados não podem ser todos DRE |

---

## Estrutura da chamada

```json
launch(action="post",
  occurred_at="YYYY-MM-DD",
  competence_at="YYYY-MM-01",  // sempre dia 01 — competência é mensal
  debits=[
    {"classification": "...", "segmentation": "...", "amount": 0.00},
    ...
  ],
  credits=[
    {"classification": "...", "segmentation": "...", "amount": 0.00},
    ...
  ],
  // campos opcionais do cabeçalho:
  settled_at="YYYY-MM-DD",       // data de efetivação no caixa
  document_id="...",             // opcional: URL da NF, attach_id do comprovante, ou ID do arquivo no Drive/Notion/OneDrive
  client_id="usr_xyz",           // user_id do cliente (quando é receita de um usuário)
  supplier_id="12.345.678/0001-90", // CNPJ do fornecedor (quando é custo de supplier)
  collaborator_id="123.456.789-00", // CPF do colaborador (quando é custo de funcionário)
  campaign_id="act_123456",      // ID da campanha Meta/Google Ads (quando é custo de marketing)
  notes="..."                    // observações livres
)
```

---

## Guia de IDs opcionais — quando usar cada campo

> **Nunca peça CNPJ ou CPF do próprio usuário que está registrando o lançamento.** Esses campos identificam a *contraparte* da transação.

| Campo | O que colocar | Quando usar |
|-------|--------------|-------------|
| `client_id` | `user_id` do cliente na plataforma | Receita gerada por um usuário/cliente cadastrado |
| `supplier_id` | CNPJ do fornecedor (`XX.XXX.XXX/XXXX-XX`) | Custo pago a um fornecedor/empresa |
| `collaborator_id` | CPF do colaborador (`XXX.XXX.XXX-XX`) | Salário, pró-labore, reembolso de funcionário |
| `campaign_id` | ID da campanha no Meta Ads ou Google Ads (ex: `act_123456`) | Custo de marketing rastreável por campanha |

Se o usuário não souber o CNPJ, CPF ou ID da campanha no momento, deixe o campo em branco — pode ser preenchido depois via `launch(action="patch", ...)`.

## Campo document_id — comprovante do lançamento

`document_id` é **opcional** e serve para vincular o lançamento ao comprovante que o originou. Aceita qualquer um dos formatos:

| Formato | Exemplo |
|---------|---------|
| URL da nota fiscal ou recibo | `"https://nfe.fazenda.sp.gov.br/..."` |
| `attach_id` de arquivo enviado pelo usuário no chat | `"attach_5a9d39c4209d"` |
| ID de arquivo no Google Drive, Notion ou OneDrive | `"1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgVE2upms"` |

**Pergunte ao usuário** antes de lançar:

> "Você tem algum comprovante para vincular a esse lançamento — nota fiscal, recibo, ou arquivo no Drive/Notion? Se tiver, me passe o link ou o ID."

Se o usuário não tiver ou não quiser informar, registre sem `document_id`. Pode ser adicionado depois via `launch(action="patch", id="...", document_id="...")`.

---

## Tabela de classificações e segmentações

### BP — Ativo Circulante → `classification: "AC"`
`Caixa` · `Estoque` · `Contas a Receber` · `Adiantamento a Diretores` · `Impostos a Recuperar` · `Despesas Antecipadas` · `Investimentos de Curto Prazo` · `Outras Contas a Receber`

### BP — Ativo Não Circulante → `classification: "ANC"`
`Realizável a Longo Prazo` · `Depósitos Judiciais` · `Outros Ativos Não Circulantes` · `Investimentos` · `Intangível` · `Outros (Ativos)`

### BP — Permanente → `classification: "Permanente"`
(usar segmentações de ANC)

### BP — Passivo Circulante → `classification: "PC"`
`Fornecedores a Pagar` · `Empréstimos` · `Financiamentos` · `Salários e Contribuições` · `Aluguéis a Pagar` · `Outras Contas a Pagar`

### BP — Passivo Não Circulante → `classification: "PNC"`
`Financiamentos (NC)` · `Empréstimos (NC)` · `Imp e Contr a Recolher` · `Outros (P)`

### BP — Patrimônio Líquido → `classification: "PL"`
(usar segmentações de PNC conforme aplicável)

### DRE — usar `classification` do grupo BP do outro lado do lançamento
`(+) Receita` · `(+) Outras Receitas` · `(-) Devoluções de Vendas` · `(-) Descontos Oferecidos` · `(-) CMV/CSV` · `(-) Despesas Gerais e Administrativas` · `(-) Pesquisa e Desenvolvimento` · `(-) Despesas com Vendas / Marketing` · `(-) Depreciação` · `(-) Amortização` · `(+/-) Lucros / Despesas com Juros` · `(-) Provisão Contábil` · `(-) Impostos` · `(-) Distribuição de Lucros`

> Para entradas DRE, o `classification` deve ser o grupo BP do lado oposto. Ex: se o crédito é Caixa (AC), a entrada DRE no débito usa `classification: "AC"`.

---

## Exemplos

### Venda à vista
```
launch(action="post",
  occurred_at="2025-06-01", competence_at="2025-06-01",
  debits=[{"classification":"AC","segmentation":"Caixa","amount":12500}],
  credits=[{"classification":"AC","segmentation":"(+) Receita","amount":12500}],
  client_id="cli_xyz", document_id="NF-001"
)
```

### Venda parcelada — 1 DRE, 2 contas de ativo
```
launch(action="post",
  occurred_at="2025-06-01", competence_at="2025-06-01",
  debits=[{"classification":"AC","segmentation":"(+) Receita","amount":1000}],
  credits=[
    {"classification":"AC","segmentation":"Caixa","amount":100},
    {"classification":"AC","segmentation":"Contas a Receber","amount":900}
  ]
)
```

### Pagamento de múltiplas contas com um único cheque
```
launch(action="post",
  occurred_at="2025-06-10", competence_at="2025-06-10", settled_at="2025-06-10",
  debits=[
    {"classification":"PC","segmentation":"Fornecedores a Pagar","amount":600},
    {"classification":"PC","segmentation":"Aluguéis a Pagar","amount":400}
  ],
  credits=[{"classification":"AC","segmentation":"Caixa","amount":1000}],
  supplier_id="12.345.678/0001-90"
)
```

### Lote — processar extrato bancário
```
launch(action="post", launches=[
  {
    "occurred_at":"2025-06-01","competence_at":"2025-06-01",
    "debits":[{"classification":"AC","segmentation":"Caixa","amount":5000}],
    "credits":[{"classification":"AC","segmentation":"(+) Receita","amount":5000}]
  },
  {
    "occurred_at":"2025-06-03","competence_at":"2025-06-03",
    "debits":[{"classification":"AC","segmentation":"(-) Despesas Gerais e Administrativas","amount":800}],
    "credits":[{"classification":"AC","segmentation":"Caixa","amount":800}],
    "notes":"Conta de internet"
  }
])
```

### Consultar lançamentos de junho
```
launch(action="read", date_from="2025-06-01", date_to="2025-06-30")
```

### Efetivar caixa
```
launch(action="patch", id="<uuid>", settled_at="2025-06-15")
```

### Corrigir entradas de um lançamento (forneça ambos os lados)
```
launch(action="patch", id="<uuid>",
  debits=[{"classification":"AC","segmentation":"Caixa","amount":1000}],
  credits=[{"classification":"AC","segmentation":"(+) Receita","amount":1000}]
)
```

### Remover lançamento
```
launch(action="delete", id="<uuid>")
```
