"""
Valida se o GOOGLE_REFRESH_TOKEN está funcional para envio de e-mail via Gmail API.
Testa autenticação OAuth2 + envia um e-mail de teste para o próprio ADMIN_EMAIL.

Uso:
    python Scripts/Tools/validate_gmail_token.py
"""

import sys
from pathlib import Path

# Adicionar backend ao PYTHONPATH
backend_dir = Path(__file__).resolve().parent.parent.parent
sys.path.append(str(backend_dir))

from App.Core.Settings.Settings import (
    ADMIN_EMAIL,
    GOOGLE_CLIENT_ID,
    GOOGLE_CLIENT_SECRET,
    GOOGLE_REFRESH_TOKEN,
)

SEP = "─" * 52


def check(label: str, value: str) -> bool:
    ok = bool(value and value.strip())
    status = "✅" if ok else "❌  NÃO CONFIGURADO"
    preview = f"  ({value[:12]}...)" if ok else ""
    print(f"  {status}  {label}{preview}")
    return ok


def test_token() -> bool:
    try:
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request

        creds = Credentials(
            token=None,
            refresh_token=GOOGLE_REFRESH_TOKEN,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=GOOGLE_CLIENT_ID,
            client_secret=GOOGLE_CLIENT_SECRET,
            scopes=["https://www.googleapis.com/auth/gmail.send"],
        )
        creds.refresh(Request())
        return True, creds
    except Exception as e:
        return False, str(e)


def send_test_email(creds) -> bool:
    import base64
    from email.mime.text import MIMEText
    from email.mime.multipart import MIMEMultipart
    from googleapiclient.discovery import build

    try:
        service = build("gmail", "v1", credentials=creds)

        msg = MIMEMultipart()
        msg["To"] = ADMIN_EMAIL
        msg["From"] = ADMIN_EMAIL
        msg["Subject"] = "✅ Teste de e-mail — MD70 Gmail OK"

        body = """
<h3>Teste bem-sucedido!</h3>
<p>O token OAuth2 do Gmail está funcionando corretamente.<br/>
Este e-mail foi enviado automaticamente pelo script <code>validate_gmail_token.py</code>.</p>
<hr/>
<p><small>MD70 · validate_gmail_token.py</small></p>
"""
        msg.attach(MIMEText(body, "html"))

        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("utf-8")
        service.users().messages().send(userId="me", body={"raw": raw}).execute()
        return True
    except Exception as e:
        return False, str(e)


def main():
    print(f"\n{SEP}")
    print("  Gmail Token Validator — MD70")
    print(SEP)

    # 1. Variáveis de ambiente
    print("\n[1] Variáveis de ambiente:")
    all_set = all(
        [
            check("ADMIN_EMAIL", ADMIN_EMAIL),
            check("GOOGLE_CLIENT_ID", GOOGLE_CLIENT_ID),
            check("GOOGLE_CLIENT_SECRET", GOOGLE_CLIENT_SECRET),
            check("GOOGLE_REFRESH_TOKEN", GOOGLE_REFRESH_TOKEN),
        ]
    )

    if not all_set:
        print(f"\n❌  Corrija as variáveis acima no .env e rode novamente.")
        print(f"    Para gerar um novo refresh token:\n")
        print(f"    python Scripts/Tools/get_gmail_refresh_token.py\n")
        sys.exit(1)

    # 2. Testar renovação do access token
    print(f"\n[2] Renovando access token via OAuth2...")
    result = test_token()
    ok, payload = result if isinstance(result, tuple) else (result, "")

    if not ok:
        print(f"  ❌  Falha ao renovar token: {payload}")
        print(f"\n  O refresh token expirou ou foi revogado.")
        print(f"  Solução: gere um novo rodando:\n")
        print(f"    python Scripts/Tools/get_gmail_refresh_token.py\n")
        sys.exit(1)

    print(f"  ✅  Token renovado com sucesso.")

    # 3. Enviar e-mail de teste
    print(f"\n[3] Enviando e-mail de teste para {ADMIN_EMAIL}...")
    send_result = send_test_email(payload)
    send_ok = send_result is True
    if not send_ok:
        err = send_result[1] if isinstance(send_result, tuple) else send_result
        print(f"  ❌  Falha ao enviar: {err}")
        sys.exit(1)

    print(f"  ✅  E-mail enviado! Verifique sua caixa de entrada.")

    print(f"\n{SEP}")
    print("  Tudo OK — Gmail está operacional.")
    print(SEP + "\n")


if __name__ == "__main__":
    main()
