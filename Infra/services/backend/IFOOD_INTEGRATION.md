# Integração iFood — Roteiro Técnico

Documentação de referência para integrar o MD70 à API oficial do iFood como Software House/Integradora.

Referência oficial: https://developer.ifood.com.br/en-US/docs/references

---

## Pré-requisitos

- CNPJ válido com CNAE de tecnologia (CPF não é aceito)
- Sistema funcional para demonstrar na homologação
- Cadastro no [Portal do Desenvolvedor iFood](https://developer.ifood.com.br)

O portal libera imediatamente: documentação, Client ID/Secret de sandbox e uma loja de teste.

---

## Arquitetura da API

A API é RESTful com JSON. Módulos principais:

| Módulo      | Responsabilidade                                          |
|-------------|-----------------------------------------------------------|
| `Merchant`  | Consulta de dados e status da loja                        |
| `Order`     | Ciclo de vida do pedido (receber, confirmar, despachar)   |
| `Catalog`   | Criação e sincronização de cardápio (produtos, preços)    |
| `Financial` | Conciliação bancária e repasses                           |

---

## Autenticação (OAuth 2.0)

Dois tokens distintos:

**1. Token do App** — autenticação da sua aplicação:
```http
POST /oauth/token
Body: client_id, client_secret, grant_type=client_credentials
```

**2. Token da Loja (Merchant)** — cada restaurante precisa autorizar o MD70:
- O dono gera um código de autorização no Portal do Parceiro iFood
- Ele insere esse código no MD70
- O MD70 troca o código por um Access Token específico daquele CNPJ

```http
POST /oauth/token
Body: client_id, client_secret, authorizationCode, grant_type=authorization_code
```

Cada loja tem seu próprio token. O MD70 precisa armazenar e renovar esses tokens por CNPJ.

---

## Event Feed (Polling de Pedidos)

O iFood **não usa WebSocket como padrão** — usa uma fila de eventos com polling. A razão é confiabilidade: o evento fica na fila até o MD70 confirmar que recebeu (ACK). Se o servidor cair, os pedidos não se perdem.

### Fluxo obrigatório:

```
Loop a cada 30s:
  GET /events:polling
    → recebe lista de eventos (PLACED, CONFIRMED, CANCELLED, etc.)
  
  Para cada evento:
    → processa (salva pedido, notifica cozinha, etc.)
    → POST /events/acknowledgment  ← obrigatório, senão o evento volta para a fila
```

### Onde implementar no MD70

Criar o módulo em `Core/Webhooks/` — o Event Poller é infraestrutura (como `Queues` e `Scheduler`), não uma feature de negócio. Features como `Delivery` consumiriam esse core.

```
Core/
  Webhooks/
    __init__.py
    IFoodClient.py       # OAuth, requisições HTTP autenticadas
    EventPoller.py       # worker de polling (asyncio loop / background thread)
    OrderProcessor.py    # lógica de negócio por tipo de evento
    WebhookRouter.py     # endpoints FastAPI para o frontend consumir
```

O `EventPoller` deve rodar como task assíncrona no startup do FastAPI:

```python
# Main.py ou lifespan
asyncio.create_task(ifood_poller.start())
```

---

## Ciclo de Vida do Pedido

Após capturar um evento `PLACED`, o MD70 deve:

1. **Confirmar** — `POST /order/{orderId}/confirm` dentro do SLA do iFood (normalmente ~1 min)
2. **Despachar** — `POST /order/{orderId}/dispatch` quando o entregador sair
3. **Cancelar** — `POST /order/{orderId}/cancel` com motivo, se necessário

Não confirmar dentro do prazo resulta em cancelamento automático pelo iFood.

---

## Sincronização de Cardápio

Via módulo `Catalog`, o MD70 pode:

- Criar/editar produtos e categorias
- Atualizar preços em tempo real
- Pausar/reativar itens (útil quando estoque zera)

Isso fecha o loop com o módulo de estoque do MD70: quando um item zera no estoque, o sistema pausa automaticamente no iFood.

---

## Homologação e Produção

1. Implementar e testar tudo no ambiente Sandbox
2. Solicitar homologação via Portal do Desenvolvedor
3. A equipe do iFood agenda teste técnico (~1 semana para aprovação)
4. Aprovado: criar App de Produção com chaves definitivas

---

## Pendências antes de começar

- [x] Confirmar CNPJ/CNAE — CNAE 7020400 (Consultoria em gestão empresarial) já consta como secundário e é aceito pelo iFood
- [ ] Cadastro no Portal do Desenvolvedor iFood
- [ ] Criar módulo `Core/Webhooks/` no backend
- [ ] Implementar storage de tokens OAuth por CNPJ de loja
- [ ] Implementar Event Poller como background task
