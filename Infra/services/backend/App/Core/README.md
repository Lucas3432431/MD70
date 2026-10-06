# 🔐 CryptographyManager Backend (Python)

Gerenciador de criptografia Python que funciona em sincronização com frontend.

## Configuração

### 1. Adicionar ao `.env` ou arquivo de configuração

```env
# Mesma chave do frontend
ENCRYPTION_KEY=0123456789abcdef0123456789abcdef
```

⚠️ **IMPORTANTE**:
- Use a **MESMA CHAVE** do frontend para compatibilidade!
- A chave é carregada automaticamente via `settings.py` (config.get('encryption_key'))
- Não é necessário importar do os.getenv() diretamente

### 2. Instalar dependência

```bash
pip install pycryptodome
```

## Como usar

### Básico: Descriptografar request

```python
from App.Core.CryptographyManager import get_cryptography_manager

@router.post('/payment/process')
async def process_payment(data: dict):
    crypto = get_cryptography_manager()

    # data vem do frontend criptografado
    # Descriptografar
    decrypted = crypto.decrypt_object(
        data,
        fields_to_decrypt=['card_number', 'cvv']
    )

    # Agora usar dados descriptografados
    card_number = decrypted['card_number']
    print(f'Cartão: {card_number}')  # "1234567890123456"

    return {'status': 'success'}
```

### Criptografar response

```python
@router.get('/billing/info')
async def get_billing():
    crypto = get_cryptography_manager()

    billing_data = {
        'document': '12345678901',
        'phone_number': '11999999999',
        'address': 'Rua X, 123'
    }

    # Criptografar dados sensíveis
    encrypted = crypto.encrypt_object(
        billing_data,
        fields_to_encrypt=['document', 'phone_number']
    )

    return encrypted  # Frontend vai receber criptografado
```

### Usando Decoradores (Recomendado)

#### Decorador 1: Apenas descriptografar request

```python
from App.Core.CryptographyManager.decorators import decrypt_request

@router.post('/subscription/cards')
@decrypt_request(fields_to_decrypt=['card_number', 'cvv'])
async def save_card(data: dict):
    # 'data' já vem descriptografado automaticamente
    card_number = data['card_number']  # "1234567890123456"
    return {'status': 'success'}
```

#### Decorador 2: Apenas criptografar response

```python
from App.Core.CryptographyManager.decorators import encrypt_response

@router.get('/subscription/cards')
@encrypt_response(fields_to_encrypt=['card_number', 'expiry_month'])
async def get_cards():
    return {
        'card_number': '1234567890123456',
        'expiry_month': '12',
        'holder_name': 'JOÃO'
    }
    # Response retorna com card_number e expiry_month criptografados
```

#### Decorador 3: Ambos (request + response)

```python
from App.Core.CryptographyManager.decorators import auto_crypto

@router.post('/payment/tokenize')
@auto_crypto(
    decrypt_fields=['card_number', 'cvv', 'holder_name'],
    encrypt_fields=['token', 'expiry']
)
async def tokenize_card(data: dict):
    # 'data' vem descriptografado
    card_number = data['card_number']

    # Processar...
    token = 'tok_xxxxx'
    expiry = '12/25'

    # Response vai ser criptografado
    return {'token': token, 'expiry': expiry}
```

## Campos criptografados por padrão

Se não especificar `fields_to_encrypt`, esses são usados:
- `card_number`
- `cvv`
- `holder_name`
- `expiry_month`, `expiry_year`
- `document`, `cpf`, `cnpj`
- `phone_number`
- `email`

## Exemplo completo: Subscription routes

```python
from fastapi import APIRouter
from App.Core.CryptographyManager import get_cryptography_manager
from App.Core.CryptographyManager.decorators import auto_crypto
from App.Core.Logs import debug

subscription_router = APIRouter(tags=["Subscription"], prefix="/api/subscription")


@subscription_router.post('/billing')
@auto_crypto(
    decrypt_fields=['document', 'phone_number'],
    encrypt_fields=[]  # Não criptografa response
)
async def save_billing(data: dict, current_user):
    """
    Salva informações de faturamento.
    Request vem criptografado, descriptografa automaticamente.
    """
    # data já vem descriptografado
    document = data.get('document')  # "12345678901"
    phone = data.get('phone_number')  # "11999999999"

    # Salvar no banco
    billing = BillingInfo(
        user_id=current_user.id,
        document=document,
        phone_number=phone,
        address=data.get('address')
    )
    db.add(billing)
    db.commit()

    return {'status': 'success'}


@subscription_router.get('/billing')
async def get_billing(current_user):
    """
    Retorna informações de faturamento criptografadas.
    """
    crypto = get_cryptography_manager()

    billing = db.query(BillingInfo).filter_by(user_id=current_user.id).first()

    if not billing:
        return {'status': 'not_found'}

    data = {
        'document': billing.document,
        'phone_number': billing.phone_number,
        'address': billing.address
    }

    # Criptografar antes de retornar
    encrypted = crypto.encrypt_object(
        data,
        fields_to_encrypt=['document', 'phone_number']
    )

    return encrypted


@subscription_router.post('/cards')
@auto_crypto(
    decrypt_fields=['card_number', 'cvv', 'holder_name'],
    encrypt_fields=['last_4']  # Retorna last_4 criptografado também
)
async def save_card(data: dict, current_user):
    """
    Salva cartão com criptografia automática em ambas direções.
    """
    # Request vem descriptografado
    card_number = data['card_number']
    cvv = data['cvv']

    # Tokenizar com PagaMe...
    token = await pagame_service.tokenize(
        card_number=card_number,
        cvv=cvv,
        holder_name=data['holder_name']
    )

    # Salvar
    card = Card(
        user_id=current_user.id,
        token=token,
        last_4=card_number[-4:]
    )
    db.add(card)
    db.commit()

    # Response retorna last_4 criptografado
    return {
        'status': 'success',
        'last_4': card_number[-4:]
    }
```

## Verificar se criptografia está disponível

```python
crypto = get_cryptography_manager()

if crypto.is_available():
    print('✓ Criptografia habilitada')
else:
    print('⚠️ Criptografia desabilitada')
```

## Segurança

✅ Mesma chave frontend/backend (compatibilidade)
✅ AES-256-CBC (padrão militar)
✅ IV aleatório por criptografia
✅ Padding automático
✅ Base64 encoding para transmissão
✅ Compatible com crypto-js (frontend)

## Troubleshooting

### "ENCRYPTION_KEY não configurada"

Adicione ao `.env.backend`:
```env
ENCRYPTION_KEY=0123456789abcdef0123456789abcdef
```

### Dados não descriptografam

- Verifique se **mesma chave** em frontend e backend
- Se chave foi alterada, dados antigos não vão desencriptar
- Cheque logs para erros de descriptografia

### Performance

- AES-256 é rápido: ~0.1ms por campo
- Se lento, é problema na rede, não na criptografia