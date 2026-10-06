"""
PlansSync - Sincronização de planos do plans.json com as tabelas plans, prices e features.
"""

import json
from pathlib import Path
from sqlalchemy import text
from App.Core.Logs import info, warning, error
import uuid as uuid_lib


class PlansSync:
    """Gerencia a sincronização de planos com o banco de dados."""

    @staticmethod
    def sync(engine, config) -> None:
        """
        Lê plans.json e sincroniza com as tabelas plans, prices e features.

        Args:
            engine: SQLAlchemy engine
            config: Configuração da aplicação
        """
        try:
            # TENTAR VÁRIOS CAMINHOS POSSÍVEIS
            # __file__ = App/Core/Crunch/PlansSync.py → parent(4) = backend raiz
            _backend_root = Path(__file__).parent.parent.parent.parent
            possible_paths = [
                _backend_root / "plans.json",
                _backend_root.parent / "plans.json",
                Path.cwd() / "plans.json",
            ]

            plans_file = None
            for path in possible_paths:
                if path.exists():
                    plans_file = path
                    break

            if not plans_file:
                warning(
                    f"[PLANS SYNC] Arquivo de planos não encontrado em nenhum dos caminhos: {possible_paths}"
                )
                return

            with open(plans_file, "r", encoding="utf-8") as f:
                plans_data = json.load(f)

            info(
                f"[PLANS SYNC] Sincronizando {len(plans_data)} planos de {plans_file.relative_to(_backend_root)}"
            )

            with engine.connect() as connection:
                # 1. Desativar todos os planos atuais (vamos reativar/criar os que estão no JSON)
                connection.execute(text("UPDATE plans SET active = 0"))

                plans_created = 0
                plans_updated = 0
                errors = []

                for plan_conf in plans_data:
                    try:
                        name = plan_conf.get("name")
                        description = plan_conf.get("description", "").replace(
                            "'", "''"
                        )
                        message = plan_conf.get("message", "").replace("'", "''")

                        users_limit = plan_conf.get("users_limit")
                        cumulative_credits = plan_conf.get("cumulative_credits")
                        cumulative_resets_in = plan_conf.get("cumulative_resets_in")
                        non_cumulative_credits = plan_conf.get("non_cumulative_credits")
                        non_cumulative_resets_in = plan_conf.get(
                            "non_cumulative_resets_in"
                        )
                        sell = plan_conf.get("sell", 0)
                        billing_type = plan_conf.get("billing_type", "plan")
                        plan_type = plan_conf.get("plan_type")

                        users_limit_sql = (
                            f"{users_limit}" if users_limit is not None else "NULL"
                        )
                        cumulative_credits_sql = (
                            f"{cumulative_credits}"
                            if cumulative_credits is not None
                            else "NULL"
                        )
                        cumulative_resets_in_sql = (
                            f"{cumulative_resets_in}"
                            if cumulative_resets_in is not None
                            else "NULL"
                        )
                        non_cumulative_credits_sql = (
                            f"{non_cumulative_credits}"
                            if non_cumulative_credits is not None
                            else "NULL"
                        )
                        non_cumulative_resets_in_sql = (
                            f"{non_cumulative_resets_in}"
                            if non_cumulative_resets_in is not None
                            else "NULL"
                        )

                        # Verificar se o plano já existe pelo nome
                        result = connection.execute(
                            text(
                                f"SELECT plan_id FROM plans WHERE name = '{name}' ORDER BY created_at DESC LIMIT 1"
                            )
                        )
                        existing_plan = result.fetchone()

                        if existing_plan:
                            plan_id = existing_plan[0]
                            # Atualiza plano existente e reativa
                            update_sql = f"""
                                UPDATE plans SET
                                    description = '{description}',
                                    message = '{message}',
                                    cumulative_credits = {cumulative_credits_sql},
                                    cumulative_resets_in = {cumulative_resets_in_sql},
                                    non_cumulative_credits = {non_cumulative_credits_sql},
                                    non_cumulative_resets_in = {non_cumulative_resets_in_sql},
                                    users_limit = {users_limit_sql},
                                    active = 1,
                                    sell = {sell},
                                    billing_type = '{billing_type}',
                                    plan_type = '{plan_type}',
                                    updated_at = CURRENT_TIMESTAMP
                                WHERE plan_id = '{plan_id}'
                            """
                            connection.execute(text(update_sql))
                            plans_updated += 1
                        else:
                            # Cria novo plano
                            plan_id = str(uuid_lib.uuid4())
                            insert_sql = f"""
                                INSERT INTO plans (
                                    plan_id, name, description, message, cumulative_credits,
                                    cumulative_resets_in, non_cumulative_credits, non_cumulative_resets_in,
                                    users_limit, active, sell, billing_type, plan_type, test_id
                                ) VALUES (
                                    '{plan_id}', '{name}', '{description}', '{message}',
                                    {cumulative_credits_sql},
                                    {cumulative_resets_in_sql}, {non_cumulative_credits_sql}, {non_cumulative_resets_in_sql},
                                    {users_limit_sql}, 1,
                                    {sell}, '{billing_type}', '{plan_type}', NULL
                                )
                            """
                            connection.execute(text(insert_sql))
                            plans_created += 1

                        # Limpar preços e features antigas deste plano
                        connection.execute(
                            text(f"DELETE FROM prices WHERE plan_id = '{plan_id}'")
                        )
                        connection.execute(
                            text(f"DELETE FROM features WHERE plan_id = '{plan_id}'")
                        )

                        # Inserir novos preços
                        currency_data = plan_conf.get("currency", {})
                        for curr_symbol, stages in currency_data.items():
                            for (
                                stage_name,
                                periods,
                            ) in stages.items():  # early_adopter, late_adopter
                                for (
                                    period_name,
                                    price_val,
                                ) in periods.items():  # monthly, annual
                                    if price_val is not None:
                                        price_insert = f"""
                                            INSERT INTO prices (plan_id, currency, price, period, adoption_stage)
                                            VALUES ('{plan_id}', '{curr_symbol}', {price_val}, '{period_name}', '{stage_name}')
                                        """
                                        connection.execute(text(price_insert))

                        # Inserir novas features
                        features_data = plan_conf.get("features", {})
                        if isinstance(features_data, dict):
                            for (
                                feature_type,
                                langs,
                            ) in (
                                features_data.items()
                            ):  # main_features, early_adopters_features
                                mapped_type = (
                                    "main"
                                    if feature_type == "main_features"
                                    else "early_adopter"
                                )
                                for lang, feats in langs.items():
                                    for feat in feats:
                                        feat_escaped = feat.replace("'", "''")
                                        feat_insert = f"""
                                            INSERT INTO features (plan_id, language, feature_type, feature)
                                            VALUES ('{plan_id}', '{lang}', '{mapped_type}', '{feat_escaped}')
                                        """
                                        connection.execute(text(feat_insert))

                    except Exception as e:
                        errors.append(f"Plano '{plan_conf.get('name')}': {e}")
                        error(
                            f"[PLANS SYNC] Erro ao sincronizar plano '{plan_conf.get('name')}': {e}"
                        )

                connection.commit()

            if errors:
                error(
                    f"[PLANS SYNC] ✗ Sincronização com erros. Criados: {plans_created}, Atualizados: {plans_updated}. Erros: {'; '.join(errors)}"
                )
            else:
                info(
                    f"[PLANS SYNC] ✓ Sincronização concluída com sucesso. Criados: {plans_created}, Atualizados: {plans_updated}"
                )

        except Exception as e:
            error(f"[PLANS SYNC] ✗ Erro geral ao sincronizar planos: {e}")
            raise

    @staticmethod
    def get_active_plans(engine) -> list:
        """
        Retorna todos os planos ativos do banco de dados.

        Returns:
            Lista de dicionários com os dados dos planos
        """
        try:
            with engine.connect() as connection:
                result = connection.execute(
                    text("SELECT * FROM plans WHERE active = 1")
                )
                # Converter para lista de dicionários
                return [dict(row) for row in result.mappings()]
        except Exception as e:
            error(f"[PLANS SYNC] Erro ao obter planos ativos: {e}")
            return []
