"""
External Validation Routes
Validação de email e telefone usando Abstract API
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import httpx
from uuid import uuid4
from sqlalchemy import text
from App.Core.Logs import debug, warning, error
from App.Core.Settings import load_config
from App.Core.Crunch.TablesSQL.DBManager import DatabaseManager
from App.Core.Crunch.TablesSQL.DBCryptographyManager import DBCryptographyManager

# Router
validation_router = APIRouter(tags=["Validation"], prefix="/api")

# ========================================================================
# MODELS
# ========================================================================


class ValidationRequest(BaseModel):
    """Request para validação"""

    value: str


@validation_router.post("/validate-cellphone")
async def validate_cellphone(body: ValidationRequest):
    """
    Valida um número de telefone usando a Abstract Phone Intelligence API.
    Salva todas as informações no banco de dados.

    Args:
        body: {value: número de telefone criptografado}

    Returns:
        dict: {
            "is_valid": bool
        }
    """
    try:
        phone = body.value.strip()

        # Sanitizar: remover apenas caracteres não numéricos
        phone_sanitized = "".join(filter(str.isdigit, phone))

        # Variações do formato para bypass
        phone_with_plus = f"+{phone_sanitized}"

        debug(f"[Phone Validation] Validando: {phone_sanitized}")

        config = load_config()
        phone_bypass_list = config.get("phone_bypass", [])

        # Verificar bypass em múltiplos formatos
        if (
            phone in phone_bypass_list
            or phone_sanitized in phone_bypass_list
            or phone_with_plus in phone_bypass_list
        ):
            debug(f"[Phone Validation] ✓ Telefone em bypass list: {phone}")
            return {"is_valid": True}

        api_key = config.get("abstract_phone_api_key")

        if not api_key:
            error("[Phone Validation] ABSTRACT_PHONE_API_KEY não configurada")
            raise HTTPException(
                status_code=500, detail="Serviço de validação indisponível"
            )

        # Chamar Abstract Phone Intelligence API com apenas números
        async with httpx.AsyncClient() as client:
            url = "https://phoneintelligence.abstractapi.com/v1/"
            params = {"api_key": api_key, "phone": phone_sanitized}

            response = await client.get(url, params=params, timeout=10)

        if response.status_code == 200:
            data = response.json()

            # Log completo da resposta para debug
            debug(f"[Phone Validation] Resposta completa: {data}")

            # Extrair is_valid de phone_validation.is_valid
            phone_validation = data.get("phone_validation", {})
            is_valid = phone_validation.get("is_valid", False)

            # Extrair informações do país
            phone_location = data.get("phone_location", {})
            phone_carrier = data.get("phone_carrier", {})

            debug(
                f"[Phone Validation] Resposta: {phone_sanitized} - is_valid={is_valid}"
            )

            try:
                session = DatabaseManager.get_session()
                validation_id = str(uuid4())

                phone_encrypted = DBCryptographyManager.e2e_decrypt_and_db_encrypt(
                    table="cellphone_validations_logs", plaintext=phone_sanitized
                )

                insert_query = text(
                    """
                    INSERT INTO cellphone_validations_logs (
                        cellphone_validation_id, phone, is_valid, country,
                        country_code, type, carrier, timezone
                    ) VALUES (
                        :id, :phone, :is_valid, :country,
                        :country_code, :type, :carrier, :timezone
                    )
                """
                )

                session.execute(
                    insert_query,
                    {
                        "id": validation_id,
                        "phone": phone_encrypted,
                        "is_valid": is_valid,
                        "country": phone_location.get("country_name", "Unknown"),
                        "country_code": phone_location.get("country_code", ""),
                        "type": phone_carrier.get("line_type", "unknown"),
                        "carrier": phone_carrier.get("name", ""),
                        "timezone": phone_location.get("timezone", ""),
                    },
                )
                session.commit()
                session.close()

                debug(f"[Phone Validation] Salvo no banco: {validation_id}")
            except Exception as db_error:
                warning(f"[Phone Validation] Erro ao salvar no banco: {str(db_error)}")
                # Não abortar a resposta se falhar ao salvar

            return {"is_valid": is_valid}
        else:
            warning(f"[Phone Validation] Status {response.status_code} para telefone")
            raise HTTPException(
                status_code=response.status_code,
                detail=f"Erro ao validar telefone: {response.status_code}",
            )

    except httpx.RequestError as e:
        error(f"[Phone Validation] Erro de conexão: {str(e)}")
        raise HTTPException(
            status_code=500, detail="Erro ao conectar com serviço de validação"
        )
    except Exception as e:
        error(f"[Phone Validation] Erro: {str(e)}")
        raise HTTPException(status_code=500, detail="Erro ao validar telefone")


@validation_router.post("/validate-postal-code")
async def validate_postal_code(body: ValidationRequest):
    """
    Valida um CEP/código postal usando a API ViaCEP.
    Retorna dados do endereço incluindo bairro.

    Args:
        body: {value: CEP/código postal descriptografado pelo middleware}

    Returns:
        dict: {"is_valid": bool, "address": str, "state": str, "city": str, "neighborhood": str}
    """
    try:
        config = load_config()
        environment = config.get("environment", "production").lower()
        is_development = environment == "development"

        postal_code = body.value

        # Sanitizar: remover apenas caracteres não numéricos
        postal_code_sanitized = "".join(filter(str.isdigit, postal_code))

        # Log apenas em development
        if is_development:
            debug(f"[Postal Code Validation] Validando CEP: {postal_code_sanitized}")

        if len(postal_code_sanitized) != 8:
            if is_development:
                debug("[Postal Code Validation] CEP inválido: comprimento incorreto")
            return {"is_valid": False}

        # Chamar ViaCEP API
        async with httpx.AsyncClient() as client:
            url = f"https://viacep.com.br/ws/{postal_code_sanitized}/json/"
            response = await client.get(url, timeout=10)

        if response.status_code == 200:
            data = response.json()

            # ViaCEP retorna "erro": true se o CEP não existe
            if data.get("erro"):
                if is_development:
                    debug(
                        "[Postal Code Validation] CEP não encontrado (ViaCEP retornou erro)"
                    )
                return {
                    "is_valid": False,
                    "address": "",
                    "state": "",
                    "city": "",
                    "neighborhood": "",
                }

            # CEP é válido
            address = data.get("logradouro", "")
            state = data.get("uf", "")
            city = data.get("localidade", "")
            neighborhood = data.get("bairro", "")

            if is_development:
                debug(
                    f"[Postal Code Validation] ✓ CEP válido: {address}, {neighborhood}, {city}, {state}"
                )

            try:
                session = DatabaseManager.get_session()
                validation_id = str(uuid4())

                postal_code_encrypted = (
                    DBCryptographyManager.e2e_decrypt_and_db_encrypt(
                        table="postal_code_validations_logs",
                        plaintext=postal_code_sanitized,
                    )
                )

                insert_query = text(
                    """
                    INSERT INTO postal_code_validations_logs (
                        postal_code_validation_id, postal_code, is_valid, city, state, address,
                        complemento, bairro, logradouro, estado, regiao, ibge, gia, ddd, siafi
                    ) VALUES (
                        :id, :postal_code, :is_valid, :city, :state, :address,
                        :complemento, :bairro, :logradouro, :estado, :regiao, :ibge, :gia, :ddd, :siafi
                    )
                """
                )

                session.execute(
                    insert_query,
                    {
                        "id": validation_id,
                        "postal_code": postal_code_encrypted,
                        "is_valid": True,
                        "city": data.get("localidade", ""),
                        "state": data.get("uf", ""),
                        "address": data.get("logradouro", ""),
                        "complemento": data.get("complemento", ""),
                        "bairro": data.get("bairro", ""),
                        "logradouro": data.get("logradouro", ""),
                        "estado": data.get("estado", ""),
                        "regiao": data.get("regiao", ""),
                        "ibge": data.get("ibge", ""),
                        "gia": data.get("gia", ""),
                        "ddd": data.get("ddd", ""),
                        "siafi": data.get("siafi", ""),
                    },
                )
                session.commit()
                session.close()

                if is_development:
                    debug(f"[Postal Code Validation] Salvo no banco: {validation_id}")
            except Exception as db_error:
                warning(
                    f"[Postal Code Validation] Erro ao salvar no banco: {str(db_error)}"
                )
                # Não abortar a resposta se falhar ao salvar

            return {
                "is_valid": True,
                "address": address,
                "state": state,
                "city": city,
                "neighborhood": neighborhood,
            }
        else:
            warning(f"[Postal Code Validation] Status {response.status_code}")
            return {
                "is_valid": False,
                "address": "",
                "state": "",
                "city": "",
                "neighborhood": "",
            }

    except httpx.RequestError as e:
        error(f"[Postal Code Validation] Erro de conexão: {str(e)}")
        return {
            "is_valid": False,
            "address": "",
            "state": "",
            "city": "",
            "neighborhood": "",
        }
    except Exception as e:
        error(f"[Postal Code Validation] Erro: {str(e)}")
        return {
            "is_valid": False,
            "address": "",
            "state": "",
            "city": "",
            "neighborhood": "",
        }


__all__ = ["validation_router"]
