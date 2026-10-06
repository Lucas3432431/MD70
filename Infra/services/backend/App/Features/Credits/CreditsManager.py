"""
CreditsManager - Gerencia créditos de usuários para processamento de mensagens
Controla verificação, consumo e reset de créditos conforme período e plano
Carrega custos do .env via Settings
"""

from datetime import datetime, timedelta
from typing import Tuple, List, Optional
import uuid as uuid_lib
from App.Core.Logs import debug, error, warning, info
from App.Core.Crunch import DatabaseManager
from App.Core.Settings.Settings import load_config, load_llm_config, RATE_LIMITING_ON


class CreditsManager:
    """Gerencia créditos de usuários para processamento de mensagens e tools."""

    @staticmethod
    def reset_credits_if_needed(user_id: str) -> bool:
        """
        Verifica e aplica resets de créditos se necessário (cumulative ou non_cumulative).
        Executado antes de requisições (messages, chats, etc.).

        Args:
            user_id: ID do usuário

        Returns:
            bool: True se tudo ok ou reset executado com sucesso
        """
        try:
            now = datetime.utcnow()

            # Obter informações do usuário
            user_query = """
                SELECT user_id, credits, last_reset, cumulative_resets_at, non_cumulative_resets_at,
                       client_id
                FROM users
                WHERE user_id = :user_id
                LIMIT 1
            """
            user = DatabaseManager.fetch_one(user_query, {"user_id": user_id})

            if not user:
                warning(
                    f"[CREDITS] Usuário não encontrado para reset - user_id={user_id}"
                )
                return False

            cumulative_resets_at = user.get("cumulative_resets_at")
            non_cumulative_resets_at = user.get("non_cumulative_resets_at")
            client_id = user.get("client_id")

            # Converter strings para datetime se necessário
            if isinstance(cumulative_resets_at, str) and cumulative_resets_at:
                cumulative_resets_at = datetime.fromisoformat(cumulative_resets_at)
            if isinstance(non_cumulative_resets_at, str) and non_cumulative_resets_at:
                non_cumulative_resets_at = datetime.fromisoformat(
                    non_cumulative_resets_at
                )

            # Obter plano do cliente
            plan_query = """
                SELECT p.plan_id, p.cumulative_credits, p.non_cumulative_credits
                FROM clients c
                JOIN plans p ON c.plan_id = p.plan_id
                WHERE c.client_id = :client_id
                LIMIT 1
            """
            plan = DatabaseManager.fetch_one(plan_query, {"client_id": client_id})

            if not plan:
                debug(f"[CREDITS] Nenhum plano encontrado para cliente {client_id}")
                return True

            plan_id = plan.get("plan_id")

            # Debug: mostrar estado dos resets
            debug(
                f"[CREDITS] Reset check for user_id={user_id}: cumulative_resets_at={cumulative_resets_at}, non_cumulative_resets_at={non_cumulative_resets_at}"
            )

            # Verificar e aplicar reset de cumulative se necessário
            if cumulative_resets_at and isinstance(cumulative_resets_at, datetime):
                if now >= cumulative_resets_at:
                    debug(
                        f"[CREDITS] Reset cumulative necessário para user_id={user_id}"
                    )
                    CreditsManager.distribute_plan_credits(user_id, plan_id)
                else:
                    debug(
                        f"[CREDITS] Reset cumulative NÃO necessário: now={now} < cumulative_resets_at={cumulative_resets_at}"
                    )
            else:
                debug(
                    f"[CREDITS] cumulative_resets_at é None ou não é datetime - pulando reset cumulative"
                )

            # Verificar e aplicar reset de non_cumulative se necessário
            if non_cumulative_resets_at and isinstance(
                non_cumulative_resets_at, datetime
            ):
                if now >= non_cumulative_resets_at:
                    debug(
                        f"[CREDITS] Reset non_cumulative necessário para user_id={user_id}"
                    )
                    CreditsManager.distribute_plan_credits(user_id, plan_id)
                else:
                    debug(
                        f"[CREDITS] Reset non_cumulative NÃO necessário: now={now} < non_cumulative_resets_at={non_cumulative_resets_at}"
                    )
            else:
                debug(
                    f"[CREDITS] non_cumulative_resets_at é None ou não é datetime - pulando reset non_cumulative"
                )

            return True

        except Exception as e:
            error(f"[CREDITS] Erro ao verificar/resetar créditos: {e}")
            return False

    SESSION_DURATION_HOURS: float = 30
    WEEK_DURATION_DAYS: int = 7

    @staticmethod
    def _get_usage_limits(user_id: str) -> dict:
        """
        Retorna os limites de sessão e semana com base no plano mensal do usuário.
        Planos free/trial não têm limites de sessão/semana (créditos escassos, sem recarga).

        Lógica (planos pagos):
          week_limit    = cumulative_credits / 4   (~1 semana de 30 dias)
          session_limit = week_limit / 4           (1/4 do limite semanal por sessão de 30h)
        """
        _zero = {"monthly_credits": 0.0, "session_limit": 0.0, "week_limit": 0.0}
        try:
            query = """
                SELECT p.cumulative_credits, p.plan_type
                FROM users u
                JOIN clients c ON u.client_id = c.client_id
                JOIN plans p ON c.plan_id = p.plan_id
                WHERE u.user_id = :user_id
                LIMIT 1
            """
            plan = DatabaseManager.fetch_one(query, {"user_id": user_id})
            if not plan:
                return _zero
            if plan.get("plan_type") in ("free", "trial"):
                return _zero
            monthly = float(plan.get("cumulative_credits") or 0)
            week_limit = monthly / 4 if monthly > 0 else 0.0
            return {
                "monthly_credits": monthly,
                "session_limit": week_limit / 4 if week_limit > 0 else 0.0,
                "week_limit": week_limit,
            }
        except Exception as e:
            error(f"[CREDITS] Erro ao obter limites de uso: {e}")
            return _zero

    @staticmethod
    def _refresh_usage_windows(user_id: str) -> dict:
        """
        Verifica se as janelas de sessão (30h) e semana (7 dias) expiraram e reseta
        o contador quando necessário. Inicializa janelas para usuários novos.

        Returns:
            dict com session_usage, session_starts_at, session_ends_at,
                      week_usage, week_starts_at, week_ends_at
        """
        try:
            now = datetime.utcnow()
            session_td = timedelta(hours=CreditsManager.SESSION_DURATION_HOURS)
            week_td = timedelta(days=CreditsManager.WEEK_DURATION_DAYS)

            query = """
                SELECT current_session_usage, current_session_starts_at,
                       current_week_usage, current_week_starts_at
                FROM users WHERE user_id = :user_id LIMIT 1
            """
            row = DatabaseManager.fetch_one(query, {"user_id": user_id})
            if not row:
                return {}

            session_usage = float(row.get("current_session_usage") or 0)
            session_starts = row.get("current_session_starts_at")
            week_usage = float(row.get("current_week_usage") or 0)
            week_starts = row.get("current_week_starts_at")

            if isinstance(session_starts, str) and session_starts:
                session_starts = datetime.fromisoformat(session_starts)
            if isinstance(week_starts, str) and week_starts:
                week_starts = datetime.fromisoformat(week_starts)

            updates: dict = {}

            # Inicializar ou resetar sessão
            if session_starts is None or now >= session_starts + session_td:
                updates["current_session_starts_at"] = now.isoformat()
                updates["current_session_usage"] = 0.0
                session_starts = now
                session_usage = 0.0
                debug(f"[CREDITS] Nova sessão iniciada para user_id={user_id}")

            # Inicializar ou resetar semana
            if week_starts is None or now >= week_starts + week_td:
                updates["current_week_starts_at"] = now.isoformat()
                updates["current_week_usage"] = 0.0
                week_starts = now
                week_usage = 0.0
                debug(f"[CREDITS] Nova semana iniciada para user_id={user_id}")

            if updates:
                set_clause = ", ".join(f"{k} = :{k}" for k in updates)
                updates["user_id"] = user_id
                DatabaseManager.execute_query(
                    f"UPDATE users SET {set_clause}, updated_at = datetime('now') WHERE user_id = :user_id",
                    updates,
                )

            return {
                "session_usage": session_usage,
                "session_starts_at": session_starts,
                "session_ends_at": session_starts + session_td,
                "week_usage": week_usage,
                "week_starts_at": week_starts,
                "week_ends_at": week_starts + week_td,
            }
        except Exception as e:
            error(f"[CREDITS] Erro ao refresh usage windows: {e}")
            return {}

    @staticmethod
    def _log_credit_transaction(
        user_id: str,
        operation_type: str,
        value: float,
        credit_type: str,
        reason: str = "",
        isolated_chat_id: Optional[str] = None,
        isolated_message_id: Optional[str] = None,
        session_usage_pct: Optional[float] = None,
        week_usage_pct: Optional[float] = None,
    ) -> bool:
        """
        Registra uma transação de créditos na tabela credits_logs.

        Args:
            user_id: ID do usuário
            operation_type: Tipo de operação ('charge' ou 'refuel')
            value: Valor da transação (negativo para charge, positivo para refuel)
            credit_type: Tipo de crédito ('cumulative' ou 'non_cumulative')
            reason: Motivo da transação
            isolated_chat_id: ID do chat isolado vinculado
            isolated_message_id: ID da mensagem isolada vinculada

        Returns:
            bool: True se registrou com sucesso
        """
        try:
            # DatabaseManager uses static methods - instantiation not needed
            logs_id = str(uuid_lib.uuid4())

            # credits_added é coluna legada NOT NULL: valor positivo para refuel, 0 para charge
            credits_added_val = abs(value) if operation_type == "refuel" else 0.0
            credits_charged_val = abs(value) if operation_type == "charge" else 0.0

            query = """
                INSERT INTO credits_logs (
                    credits_logs_id, user_id, isolated_chat_id, isolated_message_id,
                    operation_type, value, credit_type, reason,
                    credits_added, credits_charged,
                    session_usage_pct, week_usage_pct,
                    created_at, updated_at
                )
                VALUES (
                    :logs_id, :user_id, :isolated_chat_id, :isolated_message_id,
                    :operation_type, :value, :credit_type, :reason,
                    :credits_added, :credits_charged,
                    :session_usage_pct, :week_usage_pct,
                    datetime('now'), datetime('now')
                )
            """

            DatabaseManager.execute_query(
                query,
                {
                    "logs_id": logs_id,
                    "user_id": user_id,
                    "isolated_chat_id": isolated_chat_id,
                    "isolated_message_id": isolated_message_id,
                    "operation_type": operation_type,
                    "value": value,
                    "credit_type": credit_type,
                    "reason": reason,
                    "credits_added": credits_added_val,
                    "credits_charged": credits_charged_val,
                    "session_usage_pct": session_usage_pct,
                    "week_usage_pct": week_usage_pct,
                },
            )

            debug(
                f"[CREDITS] Log registrado - user_id={user_id}, type={operation_type}, value={value:.6f}, reason={reason}"
            )
            return True
        except Exception as e:
            error(f"[CREDITS] Erro ao registrar log: {e}")
            return False

    @staticmethod
    def check_credits(
        user_id: str, required_credits: float = 1.0
    ) -> Tuple[bool, float]:
        """
        Verifica se o usuário tem créditos suficientes e se o plano está ativo.

        Args:
            user_id: ID do usuário
            required_credits: Créditos necessários (padrão: 1.0)

        Returns:
            tuple: (tem_creditos_e_ativo, creditos_disponiveis)
        """
        try:
            # Query para verificar créditos e status do cliente em uma única chamada
            query = """
                SELECT u.credits, c.client_id, bs.status as sub_status
                FROM users u
                JOIN clients c ON u.client_id = c.client_id
                LEFT JOIN billing_subscriptions bs ON c.client_id = bs.client_id
                WHERE u.user_id = :user_id
                ORDER BY bs.created_at DESC
                LIMIT 1
            """
            result = DatabaseManager.fetch_one(query, {"user_id": user_id})

            if not result:
                error(f"[CREDITS] ❌ ERRO: Usuário não encontrado - user_id={user_id}")
                return False, 0.0

            # 1. Verificar Status da Assinatura
            # Bloqueio TOTAL apenas se 'canceled' ou 'payment_failed' (após retries)
            sub_status = result.get("sub_status")
            if sub_status in ["canceled", "payment_failed"]:
                warning(
                    f"[CREDITS] 💳 Acesso bloqueado: assinatura {sub_status} - user_id={user_id}"
                )
                return False, float(result["credits"])

            if sub_status == "suspended":
                debug(
                    f"[CREDITS] 💳 Assinatura suspensa (atrasada), mas permitindo uso de saldo residual - user_id={user_id}"
                )

            # 2. Verificar Saldo de Créditos
            credits = float(result["credits"])
            has_credits = credits >= required_credits

            if not has_credits:
                warning(
                    f"[CREDITS] 💳 Saldo insuficiente - user_id={user_id}, required={required_credits:.6f}, available={credits:.6f}"
                )
                return False, credits

            # 3. Verificar limites de sessão e semana (independente do saldo)
            usage = CreditsManager._refresh_usage_windows(user_id)
            if usage and RATE_LIMITING_ON:
                limits = CreditsManager._get_usage_limits(user_id)
                session_limit = limits.get("session_limit", 0)
                week_limit = limits.get("week_limit", 0)
                session_usage = usage.get("session_usage", 0)
                week_usage = usage.get("week_usage", 0)

                if session_limit > 0 and session_usage >= session_limit:
                    warning(
                        f"[CREDITS] ⏱ Limite de sessão atingido - user_id={user_id}, usage={session_usage:.6f}/{session_limit:.6f}"
                    )
                    return False, credits

                if week_limit > 0 and week_usage >= week_limit:
                    warning(
                        f"[CREDITS] 📅 Limite semanal atingido - user_id={user_id}, usage={week_usage:.6f}/{week_limit:.6f}"
                    )
                    return False, credits

            debug(
                f"[CREDITS] ✓ Check OK - user_id={user_id}, required={required_credits:.6f}, available={credits:.6f}"
            )
            return True, credits

        except Exception as e:
            error(f"[CREDITS] Erro ao verificar créditos: {e}")
            return False, 0.0

    @staticmethod
    def consume_credits(
        user_id: str,
        amount: float = 1.0,
        reason: str = "Consumo de créditos",
        isolated_chat_id: Optional[str] = None,
        isolated_message_id: Optional[str] = None,
    ) -> bool:
        """
        Consome créditos do usuário e registra no log.

        Args:
            user_id: ID do usuário
            amount: Quantidade de créditos a consumir
            reason: Motivo do consumo
            isolated_chat_id: ID do chat isolado
            isolated_message_id: ID da mensagem isolada

        Returns:
            bool: True se consumiu com sucesso
        """
        try:
            # Primeiro verifica se tem créditos
            has_credits, available = CreditsManager.check_credits(user_id, amount)
            if not has_credits:
                warning(
                    f"[CREDITS] Consumo negado: saldo insuficiente - user_id={user_id}, required={amount:.6f}, available={available:.6f}"
                )
                return False

            # Consome os créditos e incrementa contadores de sessão/semana atomicamente
            query = """
                UPDATE users
                SET credits = credits - :amount,
                    current_session_usage = COALESCE(current_session_usage, 0) + :amount,
                    current_week_usage = COALESCE(current_week_usage, 0) + :amount,
                    updated_at = datetime('now')
                WHERE user_id = :user_id
            """

            debug(
                f"[CREDITS] Executando UPDATE para reduzir {amount:.6f} créditos do user_id={user_id}"
            )
            DatabaseManager.execute_query(query, {"user_id": user_id, "amount": amount})

            # Calcular percentuais para log
            session_pct: Optional[float] = None
            week_pct: Optional[float] = None
            try:
                limits = CreditsManager._get_usage_limits(user_id)
                usage_row = DatabaseManager.fetch_one(
                    "SELECT current_session_usage, current_week_usage FROM users WHERE user_id = :user_id LIMIT 1",
                    {"user_id": user_id},
                )
                if usage_row and limits:
                    sl = limits.get("session_limit", 0)
                    wl = limits.get("week_limit", 0)
                    if sl > 0:
                        session_pct = round(
                            float(usage_row.get("current_session_usage") or 0) / sl, 6
                        )
                    if wl > 0:
                        week_pct = round(
                            float(usage_row.get("current_week_usage") or 0) / wl, 6
                        )
            except Exception:
                pass

            # ✅ REGISTRAR LOG DE CONSUMO (Negative value, operation_type='charge')
            CreditsManager._log_credit_transaction(
                user_id=user_id,
                operation_type="charge",
                value=-amount,
                credit_type="cumulative",
                reason=reason,
                isolated_chat_id=isolated_chat_id,
                isolated_message_id=isolated_message_id,
                session_usage_pct=session_pct,
                week_usage_pct=week_pct,
            )

            # Verificar novo saldo para log
            _, new_available = CreditsManager.check_credits(user_id)
            info(
                f"[CREDITS] ✓ Consumidos {amount:.6f} créditos (Saldo: {available:.6f} -> {new_available:.6f}) - user_id={user_id} | Motivo: {reason}"
            )
            return True

        except Exception as e:
            error(f"[CREDITS] Erro ao consumir créditos: {e}")
            return False

    @staticmethod
    def add_credits(
        user_id: str, amount: float, reason: str = "Adição de créditos"
    ) -> bool:
        """
        Adiciona créditos ao usuário e registra no log.

        Args:
            user_id: ID do usuário
            amount: Quantidade de créditos a adicionar
            reason: Motivo da adição

        Returns:
            bool: True se adicionou com sucesso
        """
        try:
            query = """
                UPDATE users
                SET credits = credits + :amount,
                    updated_at = datetime('now')
                WHERE user_id = :user_id
            """

            DatabaseManager.execute_query(query, {"user_id": user_id, "amount": amount})

            # ✅ REGISTRAR LOG DE REFUELLING (Positive value, operation_type='refuel')
            CreditsManager._log_credit_transaction(
                user_id=user_id,
                operation_type="refuel",
                value=amount,
                credit_type="cumulative",
                reason=reason,
            )

            info(f"[CREDITS] Adicionados {amount:.6f} créditos - user_id={user_id}")
            return True

        except Exception as e:
            error(f"[CREDITS] Erro ao adicionar créditos: {e}")
            return False

    # ========================================================================
    # MÉTODOS DE CÁLCULO DE CUSTO
    # ========================================================================

    @staticmethod
    def calculate_llm_cost(input_tokens: int, output_tokens: int, model: str) -> float:
        """
        Calcula o custo em centavos de uma chamada LLM baseado em tokens e modelo.
        Preços são por 1 milhão de tokens. Modelo é OBRIGATÓRIO.

        Args:
            input_tokens: Número de tokens de entrada
            output_tokens: Número de tokens de saída
            model: Nome do modelo (ex: "deepseek/deepseek-chat", "openai/gpt-4o")

        Returns:
            float: Custo em centavos (6 casas decimais)
        """
        try:
            if not model:
                error("[CREDITS] model é obrigatório em calculate_llm_cost")
                return 0.0

            llm_config = load_llm_config()
            providers = llm_config.get("providers", {})

            # Normalizar: "deepseek/deepseek-chat" → "deepseek-chat"
            model_key = model.split("/")[-1].lower()

            # Buscar pricing: iterar providers, localizar pelo model_key
            costs = None
            for provider_data in providers.values():
                pricing = provider_data.get("pricing", {})
                if model_key in pricing:
                    costs = pricing[model_key]
                    break

            # Fallback: tentar "default" de algum provider
            if not costs:
                for provider_data in providers.values():
                    pricing = provider_data.get("pricing", {})
                    if "default" in pricing:
                        costs = pricing["default"]
                        break

            if not costs:
                error(f"[CREDITS] Nenhuma precificação encontrada para modelo: {model}")
                return 0.0

            input_cost_per_1m = costs.get("input_cost_per_1m", 0)
            output_cost_per_1m = costs.get("output_cost_per_1m", 0)

            # Calcular custo: (tokens * custo_por_1m) / 1_000_000
            input_cost = (input_tokens * input_cost_per_1m) / 1_000_000
            output_cost = (output_tokens * output_cost_per_1m) / 1_000_000

            cost = round(input_cost + output_cost, 6)
            return max(cost, 0.000001)  # Mínimo 0.000001 centavos

        except Exception as e:
            error(f"[CREDITS] Erro ao calcular custo LLM: {e}")
            return 0.0

    @staticmethod
    def calculate_tool_cost(
        tool_name: str, output_tokens: int = 0, provider: str = None
    ) -> float:
        """
        Calcula o custo em centavos de uma ferramenta.

        Args:
            tool_name: Nome da ferramenta
            output_tokens: Número de output tokens (para tools que cobram por tokens)
            provider: Nome do provider específico (ex: "dall-e-3" para asset type="image")

        Returns:
            float: Custo em centavos (6 casas decimais)
        """
        try:
            llm_config = load_llm_config()
            tool_lower = tool_name.lower()

            # Normalização de nomes de tools
            if tool_lower in [
                "web_search",
                "web-search",
                "brave-search",
                "brave_search",
            ]:
                tool_lower = "web-search"

            # Leitura do output_token_cost do JSON ou fallback
            output_token_cost = float(
                llm_config.get("tools", {}).get("output_token_cost", 1630)
            )

            # Tools com custo fixo
            tools_fixed_costs = llm_config.get("tools", {})

            # Documentos agora são gratuitos
            if tool_lower == "document":
                return 0.0

            # Tools com custo por output_tokens apenas
            token_based_tools = {
                "print": True,
                "task": True,
                "context": True,
                "client": True,
                "calendar": True,
                "attachment": True,
            }

            # Caso especial: web-search do llm-config.json (as vezes chamado brave-search)
            fixed_cost = 0.0
            if tool_lower == "web-search":
                # Tentar pegar do config (pode estar como brave-search ou web-search)
                fixed_cost = float(
                    tools_fixed_costs.get("web-search")
                    or tools_fixed_costs.get("brave-search")
                    or 50.0
                )

            # Verificar se a tool está no config de custos fixos
            elif tool_lower in tools_fixed_costs and tool_lower != "output_token_cost":
                tool_pricing = tools_fixed_costs[tool_lower]
                if isinstance(tool_pricing, dict):
                    provider_key = provider.lower() if provider else None
                    fixed_cost = tool_pricing.get(provider_key) or tool_pricing.get(
                        "default", 0
                    )
                else:
                    fixed_cost = float(tool_pricing)

            # Calcular custo de tokens se aplicável
            token_cost = 0.0
            if (
                tool_lower in token_based_tools or fixed_cost > 0
            ) and output_tokens > 0:
                token_cost = (output_tokens / 1_000_000) * output_token_cost

            total_cost = fixed_cost + token_cost
            return round(total_cost, 6)

        except Exception as e:
            error(f"[CREDITS] Erro ao calcular custo da ferramenta {tool_name}: {e}")
            return 0.0

    @staticmethod
    def calculate_audio_cost(
        duration_seconds: float, model: str = "whisper-1"
    ) -> float:
        """
        Calcula custo em centavos para transcrição de áudio.
        Whisper cobra por minuto, arredondando para cima (mínimo 1s = 1min cobrado).
        """
        try:
            if duration_seconds <= 0:
                return 0.0
            llm_config = load_llm_config()
            providers = llm_config.get("providers", {})
            cost_per_minute = None
            for provider_data in providers.values():
                pricing = provider_data.get("pricing", {})
                if model in pricing:
                    cost_per_minute = float(pricing[model].get("cost_per_minute", 0))
                    break
            if cost_per_minute is None:
                cost_per_minute = (
                    60.0  # fallback: R$0.006/min = 60 centavos/min no custo bruto
                )
            import math

            minutes_billed = math.ceil(duration_seconds / 60)
            return round(cost_per_minute * minutes_billed, 6)
        except Exception as e:
            error(f"[CREDITS] Erro ao calcular custo de áudio: {e}")
            return 0.0

    @staticmethod
    def calculate_embedding_cost(
        token_count: int, model: str = "text-embedding-3-small"
    ) -> float:
        """Calcula custo em centavos para geração de embeddings."""
        try:
            if token_count <= 0:
                return 0.0
            llm_config = load_llm_config()
            providers = llm_config.get("providers", {})
            cost_per_1m = None
            for provider_data in providers.values():
                pricing = provider_data.get("pricing", {})
                if model in pricing:
                    cost_per_1m = float(pricing[model].get("cost_per_1m_tokens", 0))
                    break
            if cost_per_1m is None:
                cost_per_1m = 20.0  # fallback
            return round((token_count * cost_per_1m) / 1_000_000, 6)
        except Exception as e:
            error(f"[CREDITS] Erro ao calcular custo de embedding: {e}")
            return 0.0

    @staticmethod
    def centavos_to_credits(centavos: float) -> float:
        """
        Converte centavos em créditos baseado na configuração CREDIT_VALUE_COST.

        Args:
            centavos: Valor em centavos (float)

        Returns:
            float: Quantidade de créditos (com 6 casas decimais)
        """
        try:
            config = load_config()
            credit_value_cost = float(config.get("credit_value_cost"))

            if credit_value_cost <= 0:
                return 0.0

            credits = centavos / credit_value_cost
            return round(credits, 6)

        except Exception as e:
            error(f"[CREDITS] Erro ao converter centavos para créditos: {e}")
            return 0.0

    # ========================================================================
    # MÉTODOS DE VERIFICAÇÃO E CONSUMO COM INTEGRAÇÃO
    # ========================================================================

    @staticmethod
    def check_and_consume_for_llm(
        user_id: str,
        input_tokens: int,
        output_tokens: int,
        client_id: str = None,
        model: str = None,
        isolated_chat_id: Optional[str] = None,
        isolated_message_id: Optional[str] = None,
    ) -> Tuple[bool, str, float]:
        """
        Verifica e consome créditos para uma chamada LLM.

        Args:
            user_id: ID do usuário
            input_tokens: Tokens de entrada
            output_tokens: Tokens de saída
            client_id: Deprecated
            model: OBRIGATÓRIO - Nome do modelo (ex: "deepseek/deepseek-chat")
            isolated_chat_id: ID do chat isolado
            isolated_message_id: ID da mensagem isolada

        Returns:
            tuple: (sucesso, mensagem_erro, creditos_restantes)
        """
        if client_id and not user_id:
            user_id = client_id

        if not model:
            error_msg = "[CREDITS] model é obrigatório em check_and_consume_for_llm"
            error(error_msg)
            return False, error_msg, 0.0

        try:
            # Calcular custo em centavos
            cost_centavos = CreditsManager.calculate_llm_cost(
                input_tokens, output_tokens, model
            )
            cost_credits = CreditsManager.centavos_to_credits(cost_centavos)

            debug(
                f"[CREDITS] Cálculo LLM: Tokens({input_tokens} in, {output_tokens} out) -> "
                f"Model: {model} -> Custo: {cost_credits:.6f} créditos"
            )

            # Verificar e consumir
            reason = f"LLM Call: {model} ({input_tokens} in, {output_tokens} out)"
            success = CreditsManager.consume_credits(
                user_id,
                cost_credits,
                reason=reason,
                isolated_chat_id=isolated_chat_id,
                isolated_message_id=isolated_message_id,
            )

            _, remaining = CreditsManager.check_credits(user_id)
            if not success:
                return False, "Saldo insuficiente", remaining

            return True, "", remaining

        except Exception as e:
            error_msg = f"Erro no processamento de créditos: {str(e)}"
            error(f"[CREDITS] {error_msg}")
            return False, error_msg, 0.0

    @staticmethod
    def check_and_consume_for_tool(
        user_id: str,
        tool_name: str,
        output_tokens: int = 0,
        isolated_chat_id: Optional[str] = None,
        isolated_message_id: Optional[str] = None,
    ) -> Tuple[bool, str, float]:
        """
        Verifica e consome créditos para execução de uma ferramenta.
        """
        try:
            # Calcular custo em centavos
            cost_centavos = CreditsManager.calculate_tool_cost(tool_name, output_tokens)
            cost_credits = CreditsManager.centavos_to_credits(cost_centavos)

            if cost_credits <= 0:
                _, remaining = CreditsManager.check_credits(user_id)
                return True, "", remaining

            reason = f"Tool Execution: {tool_name}"
            if output_tokens > 0:
                reason += f" ({output_tokens} out tokens)"

            success = CreditsManager.consume_credits(
                user_id,
                cost_credits,
                reason=reason,
                isolated_chat_id=isolated_chat_id,
                isolated_message_id=isolated_message_id,
            )

            _, remaining = CreditsManager.check_credits(user_id)
            if not success:
                return False, f"Créditos insuficientes para {tool_name}", remaining

            return True, "", remaining

        except Exception as e:
            error_msg = f"Erro ao processar créditos para {tool_name}: {e}"
            error(error_msg)
            return False, error_msg, 0.0

    @staticmethod
    def calculate_batch_asset_cost(
        num_assets: int, provider: str = "google-vertex", asset_type: str = "image"
    ) -> float:
        """
        Calcula custo total em centavos para gerar múltiplos assets.
        """
        try:
            if num_assets <= 0:
                return 0.0

            llm_config = load_llm_config()
            tools_config = llm_config.get("tools", {})
            asset_config = tools_config.get("asset", {})

            asset_type_config = asset_config.get(asset_type, {})
            provider_key = provider.lower() if provider else None
            cost_per_asset = float(
                asset_type_config.get(provider_key)
                or asset_type_config.get("default", 0)
            )

            total_cost = round(cost_per_asset * num_assets, 6)
            return total_cost
        except Exception as e:
            error(f"[CREDITS] Erro ao calcular custo batch de assets: {e}")
            return 0.0

    @staticmethod
    def check_and_consume_for_batch_assets(
        user_id: str,
        num_assets: Optional[int] = None,
        num_successes: Optional[int] = None,
        provider: str = "gemini",
        asset_ids: Optional[List[str]] = None,
        isolated_chat_id: Optional[str] = None,
        isolated_message_id: Optional[str] = None,
    ) -> Tuple:
        """
        Gerencia créditos para batch de assets.
        """
        try:
            if num_assets is None and num_successes is None:
                return False, 0.0, 0.0 if num_successes is None else (False, 0.0)

            # MODO CHECK: validar antes de gerar
            if num_successes is None:
                cost_centavos = CreditsManager.calculate_batch_asset_cost(
                    num_assets, provider
                )
                cost_credits = CreditsManager.centavos_to_credits(cost_centavos)
                has_credits, available = CreditsManager.check_credits(
                    user_id, cost_credits
                )
                return has_credits, cost_centavos, available

            # MODO CONSUME: consumir apenas os que geraram com sucesso
            else:
                cost_centavos = CreditsManager.calculate_batch_asset_cost(
                    num_successes, provider
                )
                cost_credits = CreditsManager.centavos_to_credits(cost_centavos)

                reason = f"Asset Generation: {num_successes} {provider} {num_successes > 1 and 'assets' or 'asset'}"
                if asset_ids:
                    reason += f" | IDs: {', '.join(asset_ids)}"

                success = CreditsManager.consume_credits(
                    user_id,
                    cost_credits,
                    reason=reason,
                    isolated_chat_id=isolated_chat_id,
                    isolated_message_id=isolated_message_id,
                )
                _, remaining = CreditsManager.check_credits(user_id)
                return success, remaining

        except Exception as e:
            error(f"[CREDITS] Erro em check_and_consume_for_batch_assets: {e}")
            return (False, 0.0, 0.0) if num_successes is None else (False, 0.0)

    # ========================================================================
    # MÉTODOS DE DISTRIBUIÇÃO
    # ========================================================================

    @staticmethod
    def distribute_plan_credits(user_id: str, plan_id: str) -> bool:
        """
        Distribui créditos de um plano para um usuário.
        """
        try:
            # Obter informações do plano
            query = """
                SELECT cumulative_credits, cumulative_resets_in,
                       non_cumulative_credits
                FROM plans
                WHERE plan_id = :plan_id
                LIMIT 1
            """
            plan = DatabaseManager.fetch_one(query, {"plan_id": plan_id})
            if not plan:
                return False

            cumulative_credits = plan["cumulative_credits"] or 0
            cumulative_resets_in = plan["cumulative_resets_in"]
            non_cumulative_credits = plan["non_cumulative_credits"] or 0

            # Obter saldo atual e último tipo de reset
            user_query = (
                "SELECT credits, last_reset FROM users WHERE user_id = :user_id LIMIT 1"
            )
            user = DatabaseManager.fetch_one(user_query, {"user_id": user_id})
            if not user:
                return False

            current_credits = user["credits"] or 0
            last_reset = user.get("last_reset")
            new_credits = current_credits
            credits_to_add = 0
            new_last_reset = None

            now = datetime.utcnow()
            cumulative_resets_at = None
            non_cumulative_resets_at = None

            if last_reset == "non_cumulative":
                if current_credits < non_cumulative_credits:
                    credits_to_add = non_cumulative_credits - current_credits
                    new_credits = non_cumulative_credits
                    new_last_reset = "non_cumulative"
                    CreditsManager._log_credit_transaction(
                        user_id,
                        "refuel",
                        credits_to_add,
                        "non_cumulative",
                        f"Reset diário do plano {plan_id}",
                    )
                else:
                    new_credits = current_credits
                    new_last_reset = "non_cumulative"

            elif last_reset == "cumulative":
                if cumulative_credits > 0:
                    new_credits = current_credits + cumulative_credits
                    credits_to_add = cumulative_credits
                    new_last_reset = "cumulative"
                    CreditsManager._log_credit_transaction(
                        user_id,
                        "refuel",
                        credits_to_add,
                        "cumulative",
                        f"Distribuição cumulativa do plano {plan_id}",
                    )
                else:
                    new_credits = current_credits
                    new_last_reset = "cumulative"

            else:
                # Primeiro reset
                if cumulative_credits > 0:
                    new_credits = cumulative_credits
                    credits_to_add = cumulative_credits
                    new_last_reset = "cumulative"
                    CreditsManager._log_credit_transaction(
                        user_id,
                        "refuel",
                        credits_to_add,
                        "cumulative",
                        f"Primeiro reset do plano {plan_id}",
                    )
                elif non_cumulative_credits > 0:
                    new_credits = non_cumulative_credits
                    credits_to_add = non_cumulative_credits
                    new_last_reset = "non_cumulative"
                    CreditsManager._log_credit_transaction(
                        user_id,
                        "refuel",
                        credits_to_add,
                        "non_cumulative",
                        f"Primeiro reset do plano {plan_id}",
                    )

            # Calcular próximos resets
            if cumulative_resets_in and cumulative_resets_in > 0:
                cumulative_resets_at = now + timedelta(hours=cumulative_resets_in)

            if non_cumulative_credits and non_cumulative_credits > 0:
                next_midnight = (now + timedelta(days=1)).replace(
                    hour=0, minute=0, second=0, microsecond=0
                )
                non_cumulative_resets_at = next_midnight

            # Atualizar saldo do usuário
            update_query = """
                UPDATE users
                SET credits = :new_credits,
                    last_reset = :last_reset,
                    cumulative_resets_at = :cumulative_resets_at,
                    non_cumulative_resets_at = :non_cumulative_resets_at,
                    updated_at = datetime('now')
                WHERE user_id = :user_id
            """
            DatabaseManager.execute_query(
                update_query,
                {
                    "new_credits": new_credits,
                    "last_reset": new_last_reset,
                    "cumulative_resets_at": cumulative_resets_at.isoformat()
                    if cumulative_resets_at
                    else None,
                    "non_cumulative_resets_at": non_cumulative_resets_at.isoformat()
                    if non_cumulative_resets_at
                    else None,
                    "user_id": user_id,
                },
            )

            return True

        except Exception as e:
            error(f"[CREDITS] Erro ao distribuir créditos do plano: {e}")
            return False
