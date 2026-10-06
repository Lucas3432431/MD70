"""
Definições de ferramentas internas (hardcoded).
"""


def get_internal_tool_definitions():
    """Retorna lista de ferramentas internas hardcoded."""
    return [
        {
            "type": "function",
            "function": {
                "name": "print",
                "description": "Escreve uma mensagem ou raciocínio intermediário durante a execução. Use para comunicar o que está acontecendo.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "message": {
                            "type": "string",
                            "description": "O texto a ser impresso/exibido.",
                        }
                    },
                    "required": ["message"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "tools",
                "description": "Consulta informações detalhadas sobre as ferramentas disponíveis. Use para ver documentação de outras ferramentas.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "tool_name": {
                            "type": "string",
                            "description": "Nome da ferramenta para obter detalhes (opcional). Se omitido, retorna lista de todas.",
                        }
                    },
                    "required": [],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "list-agents",
                "description": "Lista agents que você pode chamar baseado na hierarquia. Você só acessa: seus sub_agents diretos, seus brothers (agentes com mesmo parent), e seu parent primário.",
                "parameters": {"type": "object", "properties": {}, "required": []},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "agent",
                "description": "Comunica com outro agent - pode fazer perguntas, delegar tarefas ou iniciar discussões. A resposta do agent é adicionada à conversa. Use para: (1) Perguntar sobre tools: 'Quais tools você tem?'; (2) Delegar tarefas: 'Implemente X'; (3) Discussões: 'O que você achou disso?'",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "agent_id": {
                            "type": "string",
                            "description": "ID único do agent a chamar (ex: 'ff16fd70-8d65-43f3-bbc2-70905641079c')",
                        },
                        "message": {
                            "type": "string",
                            "description": "Mensagem, pergunta ou tarefa para o agent. Pode ser qualquer tipo de comunicação.",
                        },
                    },
                    "required": ["agent_id", "message"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "dry-runner",
                "description": "Executa um script em modo de simulação (dry-run). Processa o script, entende o que deve fazer, mas não executa nada de verdade.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "script": {
                            "type": "string",
                            "description": "Código do script a ser simulado (Python, Bash, etc.)",
                        },
                        "script_type": {
                            "type": "string",
                            "description": "Tipo do script: 'python', 'bash', 'sql', etc.",
                        },
                    },
                    "required": ["script", "script_type"],
                },
            },
        },
    ]


def get_pdv_tool_definitions():
    """Ferramentas de gerenciamento do PDV (cardápio, estoque, pedidos, configurações)."""
    return [
        {
            "type": "function",
            "function": {
                "name": "pdv_menu",
                "description": "Gerencia o cardápio do PDV: produtos e categorias. Ações: list_products, get_product, create_product, update_product, list_categories, create_category.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "action": {"type": "string", "description": "list_products | get_product | create_product | update_product | list_categories | create_category"},
                        "product_id": {"type": "integer", "description": "ID do produto (para get/update)."},
                        "sku_id": {"type": "string", "description": "SKU do produto (alternativa ao product_id)."},
                        "name": {"type": "string"},
                        "price": {"type": "number"},
                        "category": {"type": "string"},
                        "available": {"type": "boolean"},
                        "emoji": {"type": "string"},
                        "description": {"type": "string"},
                        "price_delivery": {"type": "number"},
                        "price_ifood": {"type": "number"},
                        "price_99": {"type": "number"},
                        "sort_order": {"type": "integer"},
                        "type": {"type": "string", "description": "Tipo de categoria: product | addon"},
                    },
                    "required": ["action"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "pdv_stock",
                "description": "Gerencia o estoque do PDV: insumos, compras, perdas e transações. Ações: list_items, get_item, create_item, update_item, add_purchase, register_loss, list_transactions.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "action": {"type": "string", "description": "list_items | get_item | create_item | update_item | add_purchase | register_loss | list_transactions"},
                        "item_id": {"type": "integer", "description": "ID do item de estoque."},
                        "name": {"type": "string"},
                        "emoji": {"type": "string"},
                        "unit": {"type": "string", "description": "Unidade: un, kg, l, g, ml, cx, pct..."},
                        "category": {"type": "string"},
                        "item_type": {"type": "string", "description": "supply | product"},
                        "quantity": {"type": "number"},
                        "min_stock": {"type": "number"},
                        "cost_per_unit": {"type": "number"},
                        "expiry_date": {"type": "string", "description": "Data de validade YYYY-MM-DD."},
                        "phase": {"type": "string"},
                        "total_cost": {"type": "number", "description": "Custo total da compra (add_purchase)."},
                        "note": {"type": "string"},
                        "below_min": {"type": "boolean", "description": "Se true, filtra apenas itens abaixo do mínimo."},
                        "limit": {"type": "integer"},
                    },
                    "required": ["action"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "pdv_orders",
                "description": "Gerencia pedidos do PDV: criação, atualização e consulta. Ações: list_orders, get_order, create, update, get_summary.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "action": {"type": "string", "description": "list_orders | get_order | create | update | get_summary"},
                        "order_id": {"type": "integer"},
                        "comanda_label": {"type": "string", "description": "Identificação da comanda/mesa. Obrigatório em create se payment_method não informado."},
                        "payment_method": {"type": "string", "description": "pix | dinheiro | credito | debito. Obrigatório em create se comanda_label não informado."},
                        "payment_gateway": {"type": "string"},
                        "cpf": {"type": "string"},
                        "customer_name": {"type": "string"},
                        "subtotal": {"type": "number"},
                        "garcom_fee": {"type": "number"},
                        "coupon_discount": {"type": "number"},
                        "total": {"type": "number"},
                        "items_json": {"type": "array", "description": "Lista de itens do pedido."},
                        "coupons_json": {"type": "array"},
                        "nfe_emitted": {"type": "integer"},
                        "status": {"type": "string", "description": "operacao_confirmada | cancelado. Em update, único campo editável."},
                        "date_from": {"type": "string", "description": "Data inicial YYYY-MM-DD."},
                        "date_to": {"type": "string", "description": "Data final YYYY-MM-DD."},
                        "payment_method_filter": {"type": "string"},
                        "limit": {"type": "integer"},
                    },
                    "required": ["action"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "pdv_settings",
                "description": "Gerencia configurações da loja no PDV: perfil e horários de funcionamento. Ações: get_profile, update_profile, get_hours, update_hours.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "action": {"type": "string", "description": "get_profile | update_profile | get_hours | update_hours"},
                        "name": {"type": "string", "description": "Nome da loja."},
                        "description": {"type": "string"},
                        "google_review_link": {"type": "string"},
                        "garcom_enabled": {"type": "integer", "description": "0 ou 1."},
                        "garcom_pct": {"type": "number", "description": "Percentual da taxa de garçom."},
                        "nfe_enabled": {"type": "integer", "description": "0 ou 1."},
                        "opening_hours": {
                            "type": "object",
                            "description": "Objeto com chaves mon..sun, cada uma com {open: bool, from: 'HH:MM', to: 'HH:MM'}.",
                        },
                    },
                    "required": ["action"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "pdv_promotions",
                "description": "Gerencia promoções do PDV: cupons de desconto e benefícios para clientes. Ações: list/get/create/update/delete para coupons e benefits.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "action": {"type": "string", "description": "list_coupons | get_coupon | create_coupon | update_coupon | delete_coupon | list_benefits | get_benefit | create_benefit | update_benefit | delete_benefit"},
                        "coupon_id": {"type": "integer"},
                        "benefit_id": {"type": "integer"},
                        "code": {"type": "string"},
                        "name": {"type": "string"},
                        "type": {"type": "string", "description": "percent | fixed | bonus"},
                        "value": {"type": "number"},
                        "bonus_value": {"type": "string"},
                        "min_order_value": {"type": "number"},
                        "active": {"type": "boolean"},
                        "expires_at": {"type": "string", "description": "YYYY-MM-DD"},
                        "description": {"type": "string"},
                    },
                    "required": ["action"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "pdv_payments",
                "description": "Consulta e gerencia taxas de pagamento e recebimentos líquidos. Ações: list_methods, get_method, update_method, list_gateway_rates, list_receipts.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "action": {"type": "string", "description": "list_methods | get_method | update_method | list_gateway_rates | list_receipts"},
                        "method_key": {"type": "string", "description": "pix | dinheiro | credito | debito | voucher"},
                        "name": {"type": "string"},
                        "rate": {"type": "number", "description": "Taxa percentual (ex: 2.5 para 2,5%)."},
                        "flat_fee": {"type": "number", "description": "Taxa fixa em R$ por transação."},
                        "receive_days": {"type": "integer"},
                        "enabled": {"type": "integer", "description": "0 ou 1."},
                        "sort_order": {"type": "integer"},
                        "date_from": {"type": "string"},
                        "date_to": {"type": "string"},
                        "payment_method": {"type": "string"},
                        "limit": {"type": "integer"},
                    },
                    "required": ["action"],
                },
            },
        },
    ]
