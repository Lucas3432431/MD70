from fastapi import APIRouter, BackgroundTasks, HTTPException, Header
from pydantic import BaseModel
from sqlalchemy import text
from typing import Optional
import uuid
import bcrypt
import jwt
from datetime import datetime, timedelta

from App.Core.Logs import info, error
from App.Core.Crunch.TablesSQL.DBManager import DatabaseManager
from App.Core.Settings.Settings import SECRET_KEY

consumer_auth_router = APIRouter(tags=["ConsumerAuth"], prefix="/api/auth/consumer")

_EXPIRY = 86400 * 30  # 30 dias


def _enc(v: Optional[str]) -> Optional[str]:
    if not v:
        return None
    try:
        from App.Core.Services.Subscription.EncryptionUtil import encrypt_field
        return encrypt_field(v)
    except Exception:
        return v


def _dec(v: Optional[str]) -> Optional[str]:
    if not v:
        return None
    try:
        from App.Core.Services.Subscription.EncryptionUtil import decrypt_field
        return decrypt_field(v)
    except Exception:
        return v


def _issue_token(consumer_id: str, email: str) -> str:
    payload = {
        "sub": consumer_id,
        "email": email,
        "type": "consumer",
        "iat": datetime.utcnow(),
        "exp": datetime.utcnow() + timedelta(seconds=_EXPIRY),
    }
    return jwt.encode(payload, SECRET_KEY or "insecure-default", algorithm="HS256")


def _verify_token(authorization: Optional[str]) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Token ausente")
    token = authorization.split(" ", 1)[1]
    try:
        payload = jwt.decode(token, SECRET_KEY or "insecure-default", algorithms=["HS256"])
        if payload.get("type") != "consumer":
            raise HTTPException(status_code=401, detail="Token inválido")
        return payload["sub"]
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expirado")
    except Exception:
        raise HTTPException(status_code=401, detail="Token inválido")


# ── Models ────────────────────────────────────────────────────────────────────

class ValidateEmailBody(BaseModel):
    email: str


class ConsumerLoginBody(BaseModel):
    email: str
    password: str
    name: Optional[str] = None


class GoogleLoginBody(BaseModel):
    code: str


class AddressBody(BaseModel):
    label: Optional[str] = None
    cep: str
    rua: str
    numero: str
    complemento: Optional[str] = None
    bairro: str
    cidade: str
    estado: str


class CardBody(BaseModel):
    last4: str
    brand: Optional[str] = None
    holder: str


class CpfBody(BaseModel):
    cpf: str


class ProfileBody(BaseModel):
    name: Optional[str] = None
    cpf: Optional[str] = None
    phone: Optional[str] = None
    birth_date: Optional[str] = None
    gender: Optional[str] = None


# ── Auth ──────────────────────────────────────────────────────────────────────

@consumer_auth_router.get("/check")
async def check_consumer_token(authorization: Optional[str] = Header(None)):
    consumer_id = _verify_token(authorization)
    row = DatabaseManager.fetch_one(
        "SELECT consumer_id, name, email FROM consumers WHERE consumer_id = :cid LIMIT 1",
        {"cid": consumer_id},
    )
    if not row:
        raise HTTPException(status_code=401, detail="Consumer não encontrado")
    return {"valid": True, "consumer_id": row["consumer_id"], "name": row.get("name"), "email": row["email"]}


@consumer_auth_router.post("/validate-email")
async def validate_consumer_email(body: ValidateEmailBody):
    row = DatabaseManager.fetch_one(
        "SELECT consumer_id, name FROM consumers WHERE email = :email LIMIT 1",
        {"email": body.email.lower().strip()},
    )
    if row:
        return {"exists": True, "name": row.get("name")}
    return {"exists": False}


def _send_consumer_welcome(email: str, name: str) -> None:
    import os
    from App.Core.Services.AdminEmail import admin_email_service
    from App.Core.Services.AdminEmail.AdminEmailService import NOREPLY_FROM

    _html_dir = os.path.join(os.path.dirname(__file__), "../../../../HTMLs")
    with open(os.path.join(_html_dir, "email_boas_vindas_consumer.html"), encoding="utf-8") as _f:
        html = _f.read().replace("{{name}}", name)

    admin_email_service.send_email(
        to=email,
        subject="Sua conta no MD70 está pronta",
        html_body=html,
        from_email=NOREPLY_FROM,
    )


@consumer_auth_router.post("/login")
async def consumer_login(body: ConsumerLoginBody):
    email = body.email.lower().strip()
    session = DatabaseManager.get_session()
    try:
        row = session.execute(
            text("SELECT * FROM consumers WHERE email = :email LIMIT 1"),
            {"email": email},
        ).fetchone()

        if row:
            row_dict = dict(row._mapping)
            if not bcrypt.checkpw(body.password.encode(), row_dict["password_hash"].encode()):
                raise HTTPException(status_code=401, detail="Senha incorreta")
            token = _issue_token(row_dict["consumer_id"], email)
            info(f"[CONSUMER] Login: {email}")
            return {"token": token, "consumer_id": row_dict["consumer_id"], "name": row_dict.get("name"), "email": email, "is_new": False}

        consumer_id = str(uuid.uuid4())
        password_hash = bcrypt.hashpw(body.password.encode(), bcrypt.gensalt()).decode()
        derived_name = body.name or email.split("@")[0]
        session.execute(
            text("INSERT INTO consumers (consumer_id, email, password_hash, name, created_at, updated_at) VALUES (:cid, :email, :ph, :name, :now, :now)"),
            {"cid": consumer_id, "email": email, "ph": password_hash, "name": derived_name, "now": datetime.utcnow()},
        )
        session.commit()
        token = _issue_token(consumer_id, email)
        info(f"[CONSUMER] Registro: {email}")
        return {"token": token, "consumer_id": consumer_id, "name": derived_name, "email": email, "is_new": True}

    except HTTPException:
        raise
    except Exception as e:
        session.rollback()
        error(f"[CONSUMER] Erro login: {e}")
        raise HTTPException(status_code=500, detail="Erro interno")
    finally:
        session.close()


@consumer_auth_router.post("/google-login")
async def consumer_google_login(body: GoogleLoginBody):
    import httpx
    from App.Core.Settings.Settings import GOOGLE_AUTH_CLIENT_ID, GOOGLE_AUTH_CLIENT_SECRET

    if not GOOGLE_AUTH_CLIENT_ID or not GOOGLE_AUTH_CLIENT_SECRET:
        raise HTTPException(status_code=503, detail="Google OAuth não configurado")

    try:
        async with httpx.AsyncClient(timeout=10.0) as http:
            token_res = await http.post(
                "https://oauth2.googleapis.com/token",
                data={
                    "code": body.code,
                    "client_id": GOOGLE_AUTH_CLIENT_ID,
                    "client_secret": GOOGLE_AUTH_CLIENT_SECRET,
                    "redirect_uri": "postmessage",
                    "grant_type": "authorization_code",
                },
            )
            if token_res.status_code != 200:
                raise HTTPException(status_code=400, detail="Código Google inválido")
            access_token = token_res.json().get("access_token")

            info_res = await http.get(
                "https://www.googleapis.com/oauth2/v3/userinfo",
                headers={"Authorization": f"Bearer {access_token}"},
            )
            if info_res.status_code != 200:
                raise HTTPException(status_code=400, detail="Erro ao obter dados do Google")
            g_user = info_res.json()
    except HTTPException:
        raise
    except Exception as e:
        error(f"[CONSUMER] Google exchange error: {e}")
        raise HTTPException(status_code=500, detail="Erro na autenticação Google")

    g_email = g_user.get("email", "").lower().strip()
    g_name = g_user.get("name") or g_user.get("given_name") or g_email.split("@")[0]
    if not g_email:
        raise HTTPException(status_code=400, detail="Email não retornado pelo Google")

    session = DatabaseManager.get_session()
    try:
        row = session.execute(
            text("SELECT * FROM consumers WHERE email = :email LIMIT 1"),
            {"email": g_email},
        ).fetchone()

        if row:
            row_dict = dict(row._mapping)
            token = _issue_token(row_dict["consumer_id"], g_email)
            info(f"[CONSUMER] Google login: {g_email}")
            return {"token": token, "consumer_id": row_dict["consumer_id"], "name": row_dict.get("name") or g_name, "email": g_email}

        consumer_id = str(uuid.uuid4())
        placeholder_hash = f"GOOGLE_{uuid.uuid4().hex}"
        session.execute(
            text("INSERT INTO consumers (consumer_id, email, password_hash, name, created_at, updated_at) VALUES (:cid, :email, :ph, :name, :now, :now)"),
            {"cid": consumer_id, "email": g_email, "ph": placeholder_hash, "name": g_name, "now": datetime.utcnow()},
        )
        session.commit()
        token = _issue_token(consumer_id, g_email)
        info(f"[CONSUMER] Google registro: {g_email}")
        return {"token": token, "consumer_id": consumer_id, "name": g_name, "email": g_email}
    except HTTPException:
        raise
    except Exception as e:
        session.rollback()
        error(f"[CONSUMER] Erro google login: {e}")
        raise HTTPException(status_code=500, detail="Erro interno")
    finally:
        session.close()


# ── Addresses ─────────────────────────────────────────────────────────────────

@consumer_auth_router.get("/addresses")
async def list_addresses(authorization: Optional[str] = Header(None)):
    consumer_id = _verify_token(authorization)
    rows = DatabaseManager.fetch_all(
        "SELECT * FROM consumer_addresses WHERE consumer_id = :cid ORDER BY created_at ASC",
        {"cid": consumer_id},
    )
    return [
        {
            "address_id": r["address_id"],
            "label": r.get("label"),
            "cep": _dec(r.get("cep_encrypted")),
            "rua": _dec(r.get("rua_encrypted")),
            "numero": _dec(r.get("numero_encrypted")),
            "complemento": _dec(r.get("complemento_encrypted")),
            "bairro": _dec(r.get("bairro_encrypted")),
            "cidade": _dec(r.get("cidade_encrypted")),
            "estado": _dec(r.get("estado_encrypted")),
            "is_main": bool(r.get("is_main", 0)),
        }
        for r in rows
    ]


@consumer_auth_router.post("/addresses")
async def add_address(body: AddressBody, authorization: Optional[str] = Header(None)):
    consumer_id = _verify_token(authorization)
    address_id = str(uuid.uuid4())
    session = DatabaseManager.get_session()
    try:
        session.execute(
            text("""
                INSERT INTO consumer_addresses
                  (address_id, consumer_id, label, cep_encrypted, rua_encrypted, numero_encrypted,
                   complemento_encrypted, bairro_encrypted, cidade_encrypted, estado_encrypted, created_at)
                VALUES (:aid, :cid, :label, :cep, :rua, :num, :comp, :bairro, :cidade, :estado, :now)
            """),
            {
                "aid": address_id, "cid": consumer_id, "label": body.label,
                "cep": _enc(body.cep), "rua": _enc(body.rua), "num": _enc(body.numero),
                "comp": _enc(body.complemento), "bairro": _enc(body.bairro),
                "cidade": _enc(body.cidade), "estado": _enc(body.estado),
                "now": datetime.utcnow(),
            },
        )
        session.commit()
        info(f"[CONSUMER] Endereço salvo: {consumer_id}")
        return {"address_id": address_id, "ok": True}
    except Exception as e:
        session.rollback()
        error(f"[CONSUMER] Erro salvar endereço: {e}")
        raise HTTPException(status_code=500, detail="Erro interno")
    finally:
        session.close()


@consumer_auth_router.put("/addresses/{address_id}/main")
async def set_main_address(address_id: str, authorization: Optional[str] = Header(None)):
    consumer_id = _verify_token(authorization)
    session = DatabaseManager.get_session()
    try:
        session.execute(
            text("UPDATE consumer_addresses SET is_main = 0 WHERE consumer_id = :cid"),
            {"cid": consumer_id},
        )
        session.execute(
            text("UPDATE consumer_addresses SET is_main = 1 WHERE address_id = :aid AND consumer_id = :cid"),
            {"aid": address_id, "cid": consumer_id},
        )
        session.commit()
        return {"ok": True}
    except Exception as e:
        session.rollback()
        error(f"[CONSUMER] Erro set main endereço: {e}")
        raise HTTPException(status_code=500, detail="Erro interno")
    finally:
        session.close()


@consumer_auth_router.delete("/addresses/{address_id}")
async def delete_address(address_id: str, authorization: Optional[str] = Header(None)):
    consumer_id = _verify_token(authorization)
    session = DatabaseManager.get_session()
    try:
        session.execute(
            text("DELETE FROM consumer_addresses WHERE address_id = :aid AND consumer_id = :cid"),
            {"aid": address_id, "cid": consumer_id},
        )
        session.commit()
        return {"ok": True}
    except Exception as e:
        session.rollback()
        error(f"[CONSUMER] Erro deletar endereço: {e}")
        raise HTTPException(status_code=500, detail="Erro interno")
    finally:
        session.close()


# ── Cards ─────────────────────────────────────────────────────────────────────

@consumer_auth_router.get("/cards")
async def list_cards(authorization: Optional[str] = Header(None)):
    consumer_id = _verify_token(authorization)
    rows = DatabaseManager.fetch_all(
        "SELECT * FROM consumer_cards WHERE consumer_id = :cid ORDER BY created_at ASC",
        {"cid": consumer_id},
    )
    return [
        {
            "card_id": r["card_id"],
            "last4": r["last4"],
            "brand": r.get("brand"),
            "holder": _dec(r.get("holder_encrypted")),
            "is_main": bool(r.get("is_main", 0)),
        }
        for r in rows
    ]


@consumer_auth_router.post("/cards")
async def add_card(body: CardBody, authorization: Optional[str] = Header(None)):
    consumer_id = _verify_token(authorization)
    card_id = str(uuid.uuid4())
    session = DatabaseManager.get_session()
    try:
        session.execute(
            text("INSERT INTO consumer_cards (card_id, consumer_id, last4, brand, holder_encrypted, created_at) VALUES (:cid2, :cid, :l4, :brand, :holder, :now)"),
            {
                "cid2": card_id, "cid": consumer_id, "l4": body.last4,
                "brand": body.brand, "holder": _enc(body.holder), "now": datetime.utcnow(),
            },
        )
        session.commit()
        info(f"[CONSUMER] Cartão salvo: {consumer_id}")
        return {"card_id": card_id, "ok": True}
    except Exception as e:
        session.rollback()
        error(f"[CONSUMER] Erro salvar cartão: {e}")
        raise HTTPException(status_code=500, detail="Erro interno")
    finally:
        session.close()


@consumer_auth_router.put("/cards/{card_id}/main")
async def set_main_card(card_id: str, authorization: Optional[str] = Header(None)):
    consumer_id = _verify_token(authorization)
    session = DatabaseManager.get_session()
    try:
        session.execute(
            text("UPDATE consumer_cards SET is_main = 0 WHERE consumer_id = :cid"),
            {"cid": consumer_id},
        )
        session.execute(
            text("UPDATE consumer_cards SET is_main = 1 WHERE card_id = :cid2 AND consumer_id = :cid"),
            {"cid2": card_id, "cid": consumer_id},
        )
        session.commit()
        return {"ok": True}
    except Exception as e:
        session.rollback()
        error(f"[CONSUMER] Erro set main cartão: {e}")
        raise HTTPException(status_code=500, detail="Erro interno")
    finally:
        session.close()


@consumer_auth_router.delete("/cards/{card_id}")
async def delete_card(card_id: str, authorization: Optional[str] = Header(None)):
    consumer_id = _verify_token(authorization)
    session = DatabaseManager.get_session()
    try:
        session.execute(
            text("DELETE FROM consumer_cards WHERE card_id = :cid2 AND consumer_id = :cid"),
            {"cid2": card_id, "cid": consumer_id},
        )
        session.commit()
        return {"ok": True}
    except Exception as e:
        session.rollback()
        error(f"[CONSUMER] Erro deletar cartão: {e}")
        raise HTTPException(status_code=500, detail="Erro interno")
    finally:
        session.close()


# ── CPF ───────────────────────────────────────────────────────────────────────

@consumer_auth_router.get("/cpf")
async def get_cpf(authorization: Optional[str] = Header(None)):
    consumer_id = _verify_token(authorization)
    row = DatabaseManager.fetch_one(
        "SELECT cpf_encrypted FROM consumers WHERE consumer_id = :cid LIMIT 1",
        {"cid": consumer_id},
    )
    if not row or not row.get("cpf_encrypted"):
        return {"cpf": None}
    return {"cpf": _dec(row["cpf_encrypted"])}


@consumer_auth_router.put("/cpf")
async def set_cpf(body: CpfBody, authorization: Optional[str] = Header(None)):
    consumer_id = _verify_token(authorization)
    session = DatabaseManager.get_session()
    try:
        session.execute(
            text("UPDATE consumers SET cpf_encrypted = :cpf, updated_at = :now WHERE consumer_id = :cid"),
            {"cpf": _enc(body.cpf), "now": datetime.utcnow(), "cid": consumer_id},
        )
        session.commit()
        return {"ok": True}
    except Exception as e:
        session.rollback()
        error(f"[CONSUMER] Erro salvar CPF: {e}")
        raise HTTPException(status_code=500, detail="Erro interno")
    finally:
        session.close()


# ── Profile ───────────────────────────────────────────────────────────────────

@consumer_auth_router.get("/profile")
async def get_profile(authorization: Optional[str] = Header(None)):
    consumer_id = _verify_token(authorization)
    row = DatabaseManager.fetch_one(
        "SELECT name, email, phone_encrypted, birth_date, gender FROM consumers WHERE consumer_id = :cid LIMIT 1",
        {"cid": consumer_id},
    )
    if not row:
        raise HTTPException(status_code=404, detail="Consumer não encontrado")
    phone = None
    if row.get("phone_encrypted"):
        try:
            phone = _dec(row["phone_encrypted"])
        except Exception:
            pass
    return {
        "name": row.get("name"),
        "email": row.get("email"),
        "phone": phone,
        "birth_date": row.get("birth_date"),
        "gender": row.get("gender"),
    }


@consumer_auth_router.put("/profile")
async def update_profile(body: ProfileBody, background_tasks: BackgroundTasks, authorization: Optional[str] = Header(None)):
    consumer_id = _verify_token(authorization)
    session = DatabaseManager.get_session()
    try:
        current = session.execute(
            text("SELECT email, name FROM consumers WHERE consumer_id = :cid LIMIT 1"),
            {"cid": consumer_id},
        ).fetchone()
        current_dict = dict(current._mapping) if current else {}

        updates: list[str] = []
        params: dict = {"cid": consumer_id, "now": datetime.utcnow()}
        if body.name is not None:
            updates.append("name = :name")
            params["name"] = body.name
        if body.cpf is not None:
            updates.append("cpf_encrypted = :cpf")
            params["cpf"] = _enc(body.cpf)
        if body.phone is not None:
            updates.append("phone_encrypted = :phone")
            params["phone"] = _enc(body.phone)
        if body.birth_date is not None:
            updates.append("birth_date = :birth_date")
            params["birth_date"] = body.birth_date
        if body.gender is not None:
            updates.append("gender = :gender")
            params["gender"] = body.gender
        if not updates:
            return {"ok": True}
        updates.append("updated_at = :now")
        session.execute(
            text(f"UPDATE consumers SET {', '.join(updates)} WHERE consumer_id = :cid"),
            params,
        )
        session.commit()

        # Send welcome email on first real name confirmation
        if body.name and current_dict:
            consumer_email = current_dict.get("email", "")
            prev_name = current_dict.get("name") or ""
            email_prefix = consumer_email.split("@")[0] if consumer_email else ""
            if prev_name == email_prefix or not prev_name:
                background_tasks.add_task(_send_consumer_welcome, consumer_email, body.name)

        return {"ok": True}
    except Exception as e:
        session.rollback()
        error(f"[CONSUMER] Erro atualizar perfil: {e}")
        raise HTTPException(status_code=500, detail="Erro interno")
    finally:
        session.close()


# ── Delete account (LGPD) ──────────────────────────────────────────────────────

@consumer_auth_router.delete("/account")
async def delete_account(authorization: Optional[str] = Header(None)):
    consumer_id = _verify_token(authorization)
    session = DatabaseManager.get_session()
    try:
        session.execute(text("DELETE FROM consumer_cards WHERE consumer_id = :cid"), {"cid": consumer_id})
        session.execute(text("DELETE FROM consumer_addresses WHERE consumer_id = :cid"), {"cid": consumer_id})
        session.execute(text("DELETE FROM consumers WHERE consumer_id = :cid"), {"cid": consumer_id})
        session.commit()
        return {"ok": True}
    except Exception as e:
        session.rollback()
        error(f"[CONSUMER] Erro excluir conta: {e}")
        raise HTTPException(status_code=500, detail="Erro interno")
    finally:
        session.close()
