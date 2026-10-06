"""
Gerenciador de referral - atribuição de créditos ao compartilhador (referrer).
"""

import random
import uuid
from datetime import datetime, timedelta

from App.Core.Logs import debug, info, warning, error
from App.Core.Crunch.TablesSQL.DBManager import DatabaseManager
from App.Features.Credits.CreditsManager import CreditsManager

TRIAL_CREDITS_REFERRER = 10
SUBSCRIPTION_CREDITS_REFERRER = 100
TRIAL_CREDITS_REFERRED = 10
AB_VARIANTS = ["24h", "72h"]


class ReferralManager:
    @staticmethod
    def create_attribution(fingerprint_id: str, campaign_short_code: str) -> bool:
        """
        Cria atribuição de referral após o usuário se cadastrar via link de compartilhamento ou convite.
        Chamado logo após criar o usuário trial em AgreementRoutes.
        """
        try:
            db = DatabaseManager()

            # Verificar se é um invite token individual (?i=token)
            invite_token = db.fetch_one(
                "SELECT * FROM invite_tokens WHERE short_code = :code",
                {"code": campaign_short_code},
            )
            if invite_token:
                return ReferralManager._create_attribution_from_invite(
                    db, fingerprint_id, invite_token
                )

            campaign = db.fetch_one(
                "SELECT * FROM campaigns WHERE short_code = :code AND is_active = 1",
                {"code": campaign_short_code},
            )
            if not campaign or campaign.get("channel") != "shared_link":
                debug(
                    f"[REFERRAL] Campanha '{campaign_short_code}' não é shared_link, ignorando"
                )
                return False

            referrer_user_id = campaign.get("owner_user_id")
            if not referrer_user_id:
                return False

            referred_user = db.fetch_one(
                "SELECT user_id FROM users WHERE fingerprint_id = :fp",
                {"fp": fingerprint_id},
            )
            if not referred_user:
                return False

            referred_user_id = referred_user["user_id"]

            if str(referrer_user_id) == str(referred_user_id):
                debug("[REFERRAL] Auto-referral ignorado")
                return False

            existing = db.fetch_one(
                "SELECT id FROM referral_attributions WHERE referred_user_id = :uid",
                {"uid": referred_user_id},
            )
            if existing:
                debug(
                    f"[REFERRAL] Atribuição já existe para referred={referred_user_id}"
                )
                return False

            ab_variant = random.choice(AB_VARIANTS)
            hours = 24 if ab_variant == "24h" else 72
            bonus_expires = datetime.utcnow() + timedelta(hours=hours)
            attribution_id = str(uuid.uuid4())

            db.execute_query(
                """
                INSERT INTO referral_attributions (
                    attribution_id, referrer_user_id, referred_user_id,
                    referred_fingerprint_id, campaign_short_code,
                    status, ab_test_variant, bonus_window_expires_at, registered_at
                ) VALUES (
                    :attribution_id, :referrer_user_id, :referred_user_id,
                    :fingerprint_id, :campaign_short_code,
                    'registered', :ab_variant, :bonus_expires, datetime('now')
                )
                """,
                {
                    "attribution_id": attribution_id,
                    "referrer_user_id": referrer_user_id,
                    "referred_user_id": referred_user_id,
                    "fingerprint_id": fingerprint_id,
                    "campaign_short_code": campaign_short_code,
                    "ab_variant": ab_variant,
                    "bonus_expires": bonus_expires,
                },
            )

            CreditsManager.add_credits(
                referred_user_id,
                TRIAL_CREDITS_REFERRED,
                "Créditos de boas-vindas por entrar via convite de um amigo",
            )
            db.execute_query(
                "UPDATE referral_attributions SET trial_credits_awarded_referred = 1 WHERE attribution_id = :aid",
                {"aid": attribution_id},
            )

            info(
                f"[REFERRAL] Atribuição criada — referrer={referrer_user_id}, referred={referred_user_id}, variant={ab_variant}"
            )
            return True

        except Exception as e:
            error(f"[REFERRAL] Erro ao criar atribuição: {e}")
            return False

    @staticmethod
    def _create_attribution_from_invite(
        db, fingerprint_id: str, invite_token: dict
    ) -> bool:
        """Cria atribuição a partir de invite token individual."""
        referrer_user_id = invite_token.get("referrer_user_id")
        invite_id = invite_token.get("invite_id")

        referred_user = db.fetch_one(
            "SELECT user_id FROM users WHERE fingerprint_id = :fp",
            {"fp": fingerprint_id},
        )
        if not referred_user:
            return False

        referred_user_id = referred_user["user_id"]

        if str(referrer_user_id) == str(referred_user_id):
            debug("[REFERRAL] Auto-referral via invite ignorado")
            return False

        existing = db.fetch_one(
            "SELECT id FROM referral_attributions WHERE referred_user_id = :uid",
            {"uid": referred_user_id},
        )
        if existing:
            debug(f"[REFERRAL] Atribuição já existe para referred={referred_user_id}")
            return False

        ab_variant = random.choice(AB_VARIANTS)
        hours = 24 if ab_variant == "24h" else 72
        bonus_expires = datetime.utcnow() + timedelta(hours=hours)
        attribution_id = str(uuid.uuid4())

        db.execute_query(
            """
            INSERT INTO referral_attributions (
                attribution_id, referrer_user_id, referred_user_id,
                referred_fingerprint_id, status, ab_test_variant, bonus_window_expires_at, registered_at
            ) VALUES (
                :attribution_id, :referrer_user_id, :referred_user_id,
                :fingerprint_id, 'registered', :ab_variant, :bonus_expires, datetime('now')
            )
            """,
            {
                "attribution_id": attribution_id,
                "referrer_user_id": referrer_user_id,
                "referred_user_id": referred_user_id,
                "fingerprint_id": fingerprint_id,
                "ab_variant": ab_variant,
                "bonus_expires": bonus_expires,
            },
        )

        db.execute_query(
            """
            UPDATE invite_tokens SET attribution_id = :aid, status = 'registered', used_at = datetime('now')
            WHERE invite_id = :iid
            """,
            {"aid": attribution_id, "iid": invite_id},
        )

        CreditsManager.add_credits(
            referred_user_id,
            TRIAL_CREDITS_REFERRED,
            "Créditos de boas-vindas por entrar via convite de um amigo",
        )
        db.execute_query(
            "UPDATE referral_attributions SET trial_credits_awarded_referred = 1 WHERE attribution_id = :aid",
            {"aid": attribution_id},
        )

        info(
            f"[REFERRAL] Atribuição via invite criada — referrer={referrer_user_id}, referred={referred_user_id}, invite={invite_id}"
        )
        return True

    @staticmethod
    def award_trial_credits_to_referrer(referred_user_id: str) -> bool:
        """
        Concede 10 créditos ao referrer quando o referred cria o primeiro chat.
        """
        try:
            db = DatabaseManager()

            attribution = db.fetch_one(
                """
                SELECT attribution_id, referrer_user_id, trial_credits_awarded_referrer
                FROM referral_attributions
                WHERE referred_user_id = :uid
                """,
                {"uid": referred_user_id},
            )

            if not attribution:
                return False

            if attribution.get("trial_credits_awarded_referrer"):
                return False

            referrer_user_id = attribution["referrer_user_id"]
            attribution_id = attribution["attribution_id"]

            CreditsManager.add_credits(
                referrer_user_id,
                TRIAL_CREDITS_REFERRER,
                "Seu amigo testou o MD70 pelo seu link de convite",
            )

            db.execute_query(
                """
                UPDATE referral_attributions
                SET trial_credits_awarded_referrer = 1, status = 'trialed', trialed_at = datetime('now')
                WHERE attribution_id = :aid
                """,
                {"aid": attribution_id},
            )
            db.execute_query(
                "UPDATE invite_tokens SET status = 'trialed' WHERE attribution_id = :aid",
                {"aid": attribution_id},
            )

            info(
                f"[REFERRAL] 10cr → referrer={referrer_user_id} (referred={referred_user_id} criou 1° chat)"
            )
            return True

        except Exception as e:
            error(f"[REFERRAL] Erro ao conceder créditos de trial ao referrer: {e}")
            return False

    @staticmethod
    def award_subscription_credits_to_referrer(referred_user_id: str) -> bool:
        """
        Concede 100 créditos ao referrer quando referred assina.
        Verifica janela A/B: se referred assinar dentro da janela, aplica bônus de 1° mês grátis.
        """
        try:
            db = DatabaseManager()

            attribution = db.fetch_one(
                """
                SELECT attribution_id, referrer_user_id,
                       subscription_credits_awarded_referrer,
                       subscription_bonus_awarded_referred,
                       ab_test_variant, bonus_window_expires_at
                FROM referral_attributions
                WHERE referred_user_id = :uid
                """,
                {"uid": referred_user_id},
            )

            if not attribution:
                return False

            attribution_id = attribution["attribution_id"]
            referrer_user_id = attribution["referrer_user_id"]

            if not attribution.get("subscription_credits_awarded_referrer"):
                CreditsManager.add_credits(
                    referrer_user_id,
                    SUBSCRIPTION_CREDITS_REFERRER,
                    "Seu amigo assinou o MD70 pelo seu link de convite",
                )
                db.execute_query(
                    """
                    UPDATE referral_attributions
                    SET subscription_credits_awarded_referrer = 1,
                        status = 'subscribed', subscribed_at = datetime('now')
                    WHERE attribution_id = :aid
                    """,
                    {"aid": attribution_id},
                )
                db.execute_query(
                    "UPDATE invite_tokens SET status = 'subscribed' WHERE attribution_id = :aid",
                    {"aid": attribution_id},
                )
                info(
                    f"[REFERRAL] 100cr → referrer={referrer_user_id} (referred={referred_user_id} assinou)"
                )

            # TODO: Bônus 1° mês grátis para o referred dentro da janela A/B.
            # Quando o referred assina dentro de bonus_window_expires_at, aplicar cupom
            # de desconto de 100% no primeiro mês via gateway de pagamento (ex: Stripe coupon).
            # Por ora apenas loga a elegibilidade para rastreamento.
            if not attribution.get("subscription_bonus_awarded_referred"):
                bonus_expires_str = attribution.get("bonus_window_expires_at")
                if bonus_expires_str:
                    try:
                        bonus_expires = datetime.fromisoformat(str(bonus_expires_str))
                        if datetime.utcnow() <= bonus_expires:
                            # TODO: criar e aplicar cupom de 1° mês grátis no gateway de pagamento
                            info(
                                f"[REFERRAL] [TODO-COUPON] referred={referred_user_id} elegível para 1° mês grátis "
                                f"(variant={attribution.get('ab_test_variant')}, expira={bonus_expires_str})"
                            )
                        else:
                            info(
                                f"[REFERRAL] referred={referred_user_id} fora da janela A/B, sem bônus de 1° mês"
                            )
                    except Exception as date_err:
                        warning(
                            f"[REFERRAL] Erro ao verificar janela de bônus: {date_err}"
                        )

            return True

        except Exception as e:
            error(
                f"[REFERRAL] Erro ao conceder créditos de assinatura ao referrer: {e}"
            )
            return False


__all__ = ["ReferralManager"]
