from uuid import uuid4
from datetime import datetime
import json
from typing import Optional, Dict, Any

from sqlalchemy import text
from App.Core.Logs import debug, warning, error


class LifecycleTracker:
    """
    Rastreia eventos do lifecycle do cliente (chat, documentos, assets, posts).
    Registra em customer_lifecycle_tracking com referência cruzada opcional a checkout_tracking_logs.
    """

    @staticmethod
    def track(
        user_id: str,
        event_type: str,
        chat_id: Optional[str] = None,
        checkout_tracking_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """
        Registra evento de lifecycle do cliente.

        Args:
            user_id: ID do usuário
            event_type: Tipo de evento (chat_initiated, business_canvas_created, brand_identity_created, asset_created, post_created, post_confirmed)
            chat_id: ID do chat (opcional)
            checkout_tracking_id: ID do tracking de checkout para referência cruzada (opcional)
            metadata: Dados adicionais em dicionário (será serializado em JSON)

        Returns:
            bool: True se registrado com sucesso, False em caso de erro
        """
        try:
            from App.Core.Crunch.TablesSQL.DBManager import DatabaseManager

            tracking_id = str(uuid4())
            now = datetime.utcnow()

            query = text(
                """
                INSERT INTO customer_lifecycle_tracking
                (tracking_id, user_id, chat_id, checkout_tracking_id, event_type, metadata, created_at, updated_at)
                VALUES (:tracking_id, :user_id, :chat_id, :checkout_tracking_id, :event_type, :metadata, :created_at, :updated_at)
            """
            )

            session = DatabaseManager.get_session()
            try:
                session.execute(
                    query,
                    {
                        "tracking_id": tracking_id,
                        "user_id": user_id,
                        "chat_id": chat_id,
                        "checkout_tracking_id": checkout_tracking_id,
                        "event_type": event_type,
                        "metadata": json.dumps(metadata) if metadata else None,
                        "created_at": now,
                        "updated_at": now,
                    },
                )
                session.commit()
                debug(
                    f"[LIFECYCLE] {event_type} | user={user_id} | chat={chat_id} | tracking_id={tracking_id}"
                )
                return True
            finally:
                session.close()

        except Exception as e:
            error(
                f"[LIFECYCLE] Falha ao registrar {event_type} para user {user_id}: {e}"
            )
            return False
