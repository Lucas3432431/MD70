"""
_gate_engine.py — Generic skill gate engine (DAG-based).

Reads GATES/*.json to enforce sequential tool workflows per skill.
Each skill has its own JSON config describing a DAG of required steps.

Schema (GATES/<SkillName>.json):
{
  "skill":                string   — display name
  "lookup_file":          string   — exact filename the agent must look up (e.g. "SkillCatalog.md")
  "allow_message_response": bool  — when false, MessageProcessor blocks plain-text responses
  "cycle_end_step":       string  — step_id whose completion marks end of one cycle (gate resets)
  "entry_step":           string  — first step_id in the DAG
  "exempt_tools":         [str]   — tools always allowed regardless of gate state
  "steps": {
    "<step_id>": {
      "name":          string
      "allowed_tools": [str]       — tools permitted when this is the current step
      "completion": {
        "fn":          string      — "quiz_answered" | "tool_called" | "document_saved"
        ...fn-specific fields...
      }
      "on_success":    string|null — next step_id after completion, null = end of flow
      "blocked_error": string      — error message when tool is not in allowed_tools
      "correction":    [{step, call}]  — hint list for correction_required
    }
  }
}

Completion fn contracts:
  quiz_answered:   { "fn": "quiz_answered", "has_attachment": bool }
  tool_called:     { "fn": "tool_called", "tool": "vision" | "asset" | ... }
  document_saved:  { "fn": "document_saved", "document_type": "catalog" | ... }
"""

import json
import uuid as _uuid_mod
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple

from App.Core.Logs import debug

_IMAGE_EXTS = {
    ".jpg",
    ".jpeg",
    ".png",
    ".webp",
    ".gif",
    ".fav",
    ".ico",
    ".avif",
    ".bmp",
    ".svg",
    ".tiff",
    ".tif",
}


class GateEngineMixin:
    """Mixin for Core: evaluates JSON-driven skill gate configs."""

    # ── Config loading ────────────────────────────────────────────────────────

    def _gate_all_configs(self) -> list:
        # Gate configs live alongside the skill .md files in the .Agent directory.
        # Convention: SkillFoo.json gates SkillFoo.md — same base name.
        # `lookup_file` is optional in the JSON; if absent, derived from filename.
        skills_dir = (
            Path(__file__).parent.parent / "Agents" / "Agents" / ".Agent"  # Features/
        )
        if not skills_dir.exists():
            return []
        configs = []
        for f in sorted(skills_dir.glob("Skill*.json")):
            try:
                cfg = json.loads(f.read_text(encoding="utf-8"))
                # Auto-derive lookup_file from filename when not explicitly set
                if not cfg.get("lookup_file"):
                    cfg["lookup_file"] = f.stem + ".md"
                configs.append(cfg)
            except Exception as e:
                debug(f"[GATE] Erro ao carregar {f.name}: {e}")
        return configs

    # ── Lookup detection ──────────────────────────────────────────────────────

    def _gate_skill_lookup_msg(self, session, lookup_file: str):
        """
        Returns the most recent successful (non-cancelled) IsolatedMessage for the
        given skill's lookup, or None.
        """
        from App.Core.Crunch.TablesSQL.Models import IsolatedMessage, IsolatedChat

        chat_id = self.current_chat_id
        if not chat_id:
            return None

        def _q(cid):
            return (
                session.query(IsolatedMessage)
                .filter(
                    IsolatedMessage.isolated_chat_id == cid,
                    IsolatedMessage.tool_called == "lookup",
                    IsolatedMessage.tool_call_type == "output",
                    IsolatedMessage.content.ilike(f"%{lookup_file}%"),
                    ~IsolatedMessage.content.ilike("%blocked_files%"),
                    # Exclude failed lookups (e.g. "already active" error responses)
                    ~IsolatedMessage.content.ilike('%"success": false%'),
                )
                .order_by(IsolatedMessage.id.desc())
                .first()
            )

        msg = _q(chat_id)
        if not msg:
            ic = (
                session.query(IsolatedChat)
                .filter(IsolatedChat.chat_id == chat_id)
                .first()
            )
            if ic:
                msg = _q(str(ic.id))

        if msg and self._check_flow_cancelled_in_chat(msg.isolated_chat_id, since_id=0):
            return None

        return msg

    # ── Step completion checks ────────────────────────────────────────────────

    def _gate_step_completed(
        self,
        session,
        step_def: dict,
        chat_id: str,
        since_id: int,
        since_timestamp,
    ) -> Tuple[bool, int]:
        """
        Evaluates whether a step's completion condition is met.
        Returns (is_complete, new_since_id) — new_since_id advances the DAG cursor.
        """
        from App.Core.Crunch.TablesSQL.Models import IsolatedMessage

        completion = step_def.get("completion", {})
        fn = completion.get("fn")

        if fn == "quiz_answered":
            has_attachment = completion.get("has_attachment", False)

            # Fetch all quiz inputs after cursor to find one where the FIRST question
            # has attachment: true (when has_attachment is required).
            quiz_inputs = (
                session.query(IsolatedMessage)
                .filter(
                    IsolatedMessage.isolated_chat_id == chat_id,
                    IsolatedMessage.tool_called == "quiz",
                    IsolatedMessage.tool_call_type == "input",
                    IsolatedMessage.id > since_id,
                )
                .order_by(IsolatedMessage.id.asc())
                .all()
            )

            quiz_input = None
            for _qi in quiz_inputs:
                if not has_attachment:
                    quiz_input = _qi
                    break
                # has_attachment: first question MUST have attachment: true
                try:
                    _raw = _qi.content or ""
                    _json_start = _raw.find("{")
                    _qdata = json.loads(_raw[_json_start:]) if _json_start >= 0 else {}
                    _questions = _qdata.get("quiz", [])
                    if _questions and _questions[0].get("attachment") is True:
                        quiz_input = _qi
                        break
                except Exception:
                    continue

            if not quiz_input:
                return False, since_id

            quiz_output = (
                session.query(IsolatedMessage)
                .filter(
                    IsolatedMessage.isolated_chat_id == chat_id,
                    IsolatedMessage.tool_called == "quiz",
                    IsolatedMessage.tool_call_type == "output",
                    IsolatedMessage.id > quiz_input.id,
                    ~IsolatedMessage.content.ilike('%"success": false%'),
                )
                .order_by(IsolatedMessage.id.asc())
                .first()
            )

            if quiz_output:
                # Validate that each required question got its own answer (prevents
                # bundling all options into a single response to bypass the gate).
                min_answers = completion.get("min_answers", 0)
                if min_answers > 0:
                    try:
                        output_data = json.loads(quiz_output.content)
                        n_answers = len(output_data.get("final_answers", []))
                        if n_answers < min_answers:
                            debug(
                                f"[GATE] quiz_answered: {n_answers} respostas < min_answers={min_answers}"
                            )
                            return False, since_id
                    except Exception as e:
                        debug(f"[GATE] quiz_answered min_answers parse error: {e}")
                return True, quiz_output.id
            return False, since_id

        elif fn == "tool_called":
            tool = completion.get("tool", "")
            result = (
                session.query(IsolatedMessage)
                .filter(
                    IsolatedMessage.isolated_chat_id == chat_id,
                    IsolatedMessage.tool_called == tool,
                    IsolatedMessage.tool_call_type == "output",
                    IsolatedMessage.id > since_id,
                    ~IsolatedMessage.content.ilike('%"success": false%'),
                )
                .order_by(IsolatedMessage.id.asc())
                .first()
            )
            if result:
                return True, result.id
            return False, since_id

        elif fn == "tool_called_for_attachment":
            # Context-aware: looks at the quiz answer at `answer_question_index` to decide
            # which tool is required — vision if the answer is an attachment ID, web_search if URL.
            answer_idx = completion.get("answer_question_index", 0)
            attach_tool = completion.get("attach_tool", "vision")
            url_tools = completion.get("url_tools", ["web_search", "web-search"])

            # Find the quiz output that precedes the current cursor (marks the end of s-quiz)
            quiz_boundary = (
                session.query(IsolatedMessage)
                .filter(
                    IsolatedMessage.isolated_chat_id == chat_id,
                    IsolatedMessage.tool_called == "quiz",
                    IsolatedMessage.tool_call_type == "output",
                    IsolatedMessage.id <= since_id,
                    ~IsolatedMessage.content.ilike('%"success": false%'),
                )
                .order_by(IsolatedMessage.id.desc())
                .first()
            )
            if not quiz_boundary:
                return False, since_id

            try:
                output_data = json.loads(quiz_boundary.content)
                final_answers = output_data.get("final_answers", [])
                if answer_idx >= len(final_answers):
                    return False, since_id
                answer_value = str(final_answers[answer_idx].get("answer", "")).strip()
            except Exception as e:
                debug(f"[GATE] tool_called_for_attachment parse error: {e}")
                return False, since_id

            # URL answer → web_search; anything else (attach_id, JSON array) → vision
            is_url = answer_value.lower().startswith(("http://", "https://"))
            required_tools = url_tools if is_url else [attach_tool]

            result = (
                session.query(IsolatedMessage)
                .filter(
                    IsolatedMessage.isolated_chat_id == chat_id,
                    IsolatedMessage.tool_called.in_(required_tools),
                    IsolatedMessage.tool_call_type == "output",
                    IsolatedMessage.id > since_id,
                    ~IsolatedMessage.content.ilike('%"success": false%'),
                )
                .order_by(IsolatedMessage.id.asc())
                .first()
            )
            if result:
                return True, result.id
            return False, since_id

        elif fn == "vision_after_analyze":
            # Attachment path: gate advances when vision succeeds after quiz.
            # Direct image URL path: gate advances when vision succeeds (no web_search needed).
            # Page URL path: gate advances when vision succeeds AFTER web_search succeeds.
            # "Nenhum" path: gate skips this step entirely (no analysis required).
            answer_idx = completion.get("answer_question_index", 0)
            url_tools = completion.get("url_tools", ["web_search", "web-search"])

            quiz_boundary = (
                session.query(IsolatedMessage)
                .filter(
                    IsolatedMessage.isolated_chat_id == chat_id,
                    IsolatedMessage.tool_called == "quiz",
                    IsolatedMessage.tool_call_type == "output",
                    IsolatedMessage.id <= since_id,
                    ~IsolatedMessage.content.ilike('%"success": false%'),
                )
                .order_by(IsolatedMessage.id.desc())
                .first()
            )
            if not quiz_boundary:
                return False, since_id

            try:
                output_data = json.loads(quiz_boundary.content)
                final_answers = output_data.get("final_answers", [])
                if answer_idx >= len(final_answers):
                    return False, since_id
                answer_value = str(final_answers[answer_idx].get("answer", "")).strip()
            except Exception as e:
                debug(f"[GATE] vision_after_analyze parse error: {e}")
                return False, since_id

            # "Nenhum" / empty → skip step, advance gate immediately
            if answer_value.lower() in ("nenhum", "nenhuma", "none", ""):
                return True, since_id

            is_url = answer_value.lower().startswith(("http://", "https://"))

            if is_url:
                # Detect direct image URLs (e.g. Pinterest image CDN, direct .jpg links)
                url_path = answer_value.split("?")[0].split("#")[0].lower()
                is_direct_image = any(url_path.endswith(ext) for ext in _IMAGE_EXTS)

                if is_direct_image:
                    # Direct image URL → only require vision(), skip web_search
                    vision_result = (
                        session.query(IsolatedMessage)
                        .filter(
                            IsolatedMessage.isolated_chat_id == chat_id,
                            IsolatedMessage.tool_called == "vision",
                            IsolatedMessage.tool_call_type == "output",
                            IsolatedMessage.id > since_id,
                            ~IsolatedMessage.content.ilike('%"success": false%'),
                        )
                        .order_by(IsolatedMessage.id.asc())
                        .first()
                    )
                    if vision_result:
                        return True, vision_result.id
                    return False, since_id

                # Page URL → web_search must precede vision
                web_result = (
                    session.query(IsolatedMessage)
                    .filter(
                        IsolatedMessage.isolated_chat_id == chat_id,
                        IsolatedMessage.tool_called.in_(url_tools),
                        IsolatedMessage.tool_call_type == "output",
                        IsolatedMessage.id > since_id,
                        ~IsolatedMessage.content.ilike('%"success": false%'),
                    )
                    .order_by(IsolatedMessage.id.asc())
                    .first()
                )
                if not web_result:
                    return False, since_id
                # If web_search returned content indicating JS-only SPA (no images extractable),
                # advance automatically — no vision possible, treat inspiration as unavailable.
                _JS_BLOCKED_PHRASES = (
                    "turn on javascript",
                    "enable javascript",
                    "requires javascript",
                    "javascript required",
                    "javascript is required",
                    "doesn't work unless you",
                    "without javascript",
                )
                try:
                    _ws_content = web_result.content.lower()
                    if any(phrase in _ws_content for phrase in _JS_BLOCKED_PHRASES):
                        debug(
                            "[GATE] vision_after_analyze: web_search retornou página JS-only, avançando sem vision"
                        )
                        return True, web_result.id
                except Exception:
                    pass
                # Vision with a direct image URL (photo extension) after web_search completes the step,
                # regardless of whether vision succeeded or failed (CDN access issues are not the agent's fault).
                vision_inputs = (
                    session.query(IsolatedMessage)
                    .filter(
                        IsolatedMessage.isolated_chat_id == chat_id,
                        IsolatedMessage.tool_called == "vision",
                        IsolatedMessage.tool_call_type == "input",
                        IsolatedMessage.id > web_result.id,
                    )
                    .order_by(IsolatedMessage.id.asc())
                    .all()
                )
                for vin in vision_inputs:
                    try:
                        _raw = vin.content or ""
                        # Content may be "Tool: vision\nArgs: {...}" or plain JSON
                        _json_start = _raw.find("{")
                        _args = (
                            json.loads(_raw[_json_start:]) if _json_start >= 0 else {}
                        )
                        _img = (
                            str(_args.get("image_input", ""))
                            .split("?")[0]
                            .split("#")[0]
                            .lower()
                        )
                        if any(_img.endswith(ext) for ext in _IMAGE_EXTS):
                            # Find corresponding output to use as cursor
                            _vout = (
                                session.query(IsolatedMessage)
                                .filter(
                                    IsolatedMessage.isolated_chat_id == chat_id,
                                    IsolatedMessage.tool_called == "vision",
                                    IsolatedMessage.tool_call_type == "output",
                                    IsolatedMessage.id > vin.id,
                                )
                                .order_by(IsolatedMessage.id.asc())
                                .first()
                            )
                            return True, (_vout.id if _vout else vin.id)
                    except Exception:
                        continue
                return False, since_id
            else:
                # Resposta não é URL. Pode ser:
                #   - "attach_XXXX" (single)
                #   - '["attach_AAA","attach_BBB"]' (multiple_attach JSON array)
                #   - nome de arquivo ou outro texto inválido → trata como Nenhum
                is_attach = answer_value.lower().startswith("attach_")
                if not is_attach:
                    # Tenta deserializar JSON array de attach_ids
                    try:
                        parsed = json.loads(answer_value)
                        if (
                            isinstance(parsed, list)
                            and parsed
                            and all(
                                str(v).lower().startswith("attach_") for v in parsed
                            )
                        ):
                            is_attach = True
                    except Exception:
                        pass

                if not is_attach:
                    # Nome de arquivo simples ou texto inválido → pula como Nenhum
                    return True, since_id

                # Attachment path: just look for vision after cursor
                vision_result = (
                    session.query(IsolatedMessage)
                    .filter(
                        IsolatedMessage.isolated_chat_id == chat_id,
                        IsolatedMessage.tool_called == "vision",
                        IsolatedMessage.tool_call_type == "output",
                        IsolatedMessage.id > since_id,
                        ~IsolatedMessage.content.ilike('%"success": false%'),
                    )
                    .order_by(IsolatedMessage.id.asc())
                    .first()
                )
                if vision_result:
                    return True, vision_result.id
                return False, since_id

        elif fn == "document_saved":
            doc_type = completion.get("document_type", "")
            try:
                import datetime as _dt
                from sqlalchemy import text as _sa_text

                # SQLite CURRENT_TIMESTAMP has seconds precision; IsolatedMessage.created_at
                # has microseconds. Truncate to seconds and use >= to avoid false negatives
                # when both fall in the same second.
                if isinstance(since_timestamp, _dt.datetime):
                    after_sec = since_timestamp.replace(microsecond=0)
                else:
                    after_sec = since_timestamp

                row = session.execute(
                    _sa_text(
                        "SELECT document_id FROM documents "
                        "WHERE chat_id = :cid AND tool_type = :tt AND created_at >= :after"
                    ),
                    {"cid": chat_id, "tt": doc_type, "after": after_sec},
                ).fetchone()
                if row:
                    return True, since_id
            except Exception as e:
                debug(f"[GATE] document_saved query error: {e}")
            return False, since_id

        # Unknown fn: treat as never complete
        debug(f"[GATE] Completion fn desconhecida: '{fn}'")
        return False, since_id

    # ── DAG walker ────────────────────────────────────────────────────────────

    def _gate_find_current_step(
        self, session, config: dict, chat_id: str, lookup_msg
    ) -> Optional[str]:
        """
        Walks the DAG from entry_step, advancing until an incomplete step is found.
        Returns the step_id of the current (blocking) step, or None if all steps are done.
        """
        entry = config.get("entry_step")
        steps = config.get("steps", {})

        if not entry or entry not in steps:
            return None

        since_id = lookup_msg.id
        since_timestamp = lookup_msg.created_at
        current = entry

        while current:
            step_def = steps.get(current)
            if not step_def:
                break

            is_done, new_since_id = self._gate_step_completed(
                session, step_def, chat_id, since_id, since_timestamp
            )

            if not is_done:
                return current

            # Advance cursor
            if new_since_id != since_id:
                since_id = new_since_id
                try:
                    from App.Core.Crunch.TablesSQL.Models import IsolatedMessage

                    msg = session.get(IsolatedMessage, since_id)
                    if msg and msg.created_at:
                        since_timestamp = msg.created_at
                except Exception:
                    pass

            current = step_def.get("on_success")

        return None  # all steps done

    # ── Cycle end detection ───────────────────────────────────────────────────

    def _gate_cycle_ended(
        self, session, config: dict, chat_id: str, lookup_msg
    ) -> bool:
        """
        Returns True if the cycle_end_step was completed AND no new entry_step
        has been initiated since (i.e., cycle is done, gate resets).
        This replicates the copywriting "asset executed + no new quiz" check.
        """
        cycle_end = config.get("cycle_end_step")
        if not cycle_end:
            return False

        steps = config.get("steps", {})
        step_def = steps.get(cycle_end)
        if not step_def:
            return False

        # Walk to find if cycle_end_step was completed
        entry = config.get("entry_step")
        if not entry or entry not in steps:
            return False

        since_id = lookup_msg.id
        since_timestamp = lookup_msg.created_at
        current = entry

        cycle_end_completion_id = None
        while current:
            sdef = steps.get(current)
            if not sdef:
                break
            is_done, new_since_id = self._gate_step_completed(
                session, sdef, chat_id, since_id, since_timestamp
            )
            if not is_done:
                return False
            if current == cycle_end:
                cycle_end_completion_id = new_since_id
                break
            if new_since_id != since_id:
                since_id = new_since_id
                try:
                    from App.Core.Crunch.TablesSQL.Models import IsolatedMessage

                    msg = session.get(IsolatedMessage, since_id)
                    if msg and msg.created_at:
                        since_timestamp = msg.created_at
                except Exception:
                    pass
            current = sdef.get("on_success")

        if cycle_end_completion_id is None:
            return False

        # Check if a new entry_step action started after cycle_end
        entry_step_def = steps.get(entry, {})
        entry_completion = entry_step_def.get("completion", {})
        entry_fn = entry_completion.get("fn")

        if entry_fn == "quiz_answered":
            from App.Core.Crunch.TablesSQL.Models import IsolatedMessage

            has_attachment = entry_completion.get("has_attachment", False)
            _new_quiz_inputs = (
                session.query(IsolatedMessage)
                .filter(
                    IsolatedMessage.isolated_chat_id == chat_id,
                    IsolatedMessage.tool_called == "quiz",
                    IsolatedMessage.tool_call_type == "input",
                    IsolatedMessage.id > cycle_end_completion_id,
                )
                .order_by(IsolatedMessage.id.asc())
                .all()
            )
            new_entry = None
            for _nqi in _new_quiz_inputs:
                if not has_attachment:
                    new_entry = _nqi
                    break
                try:
                    _raw = _nqi.content or ""
                    _json_start = _raw.find("{")
                    _qdata = json.loads(_raw[_json_start:]) if _json_start >= 0 else {}
                    _questions = _qdata.get("quiz", [])
                    if _questions and _questions[0].get("attachment") is True:
                        new_entry = _nqi
                        break
                except Exception:
                    continue
            if new_entry:
                return False  # new cycle started

        return True  # cycle done, no new cycle started

    # ── Gate release helper ───────────────────────────────────────────────────

    def _gate_write_flow_cancelled(self, isolated_chat_id: str) -> None:
        """Persist [FLOW_CANCELLED] to release the skill gate for this chat."""
        if not self.db_manager:
            return
        try:
            from App.Core.Crunch.TablesSQL.Models import IsolatedMessage

            session = self.db_manager.get_session()
            try:
                session.add(
                    IsolatedMessage(
                        isolated_chat_id=isolated_chat_id,
                        isolated_message_id=str(_uuid_mod.uuid4()),
                        role="system",
                        content="[FLOW_CANCELLED] Motivo: tool cancel acionada pelo agente",
                        agent_id="system",
                        agent="System",
                        created_at=datetime.utcnow(),
                    )
                )
                session.commit()
                debug(f"[GATE] [FLOW_CANCELLED] escrito para {isolated_chat_id}")
            finally:
                session.close()
        except Exception as _e:
            debug(f"[GATE] Erro ao escrever [FLOW_CANCELLED]: {_e}")

    # ── Main gate evaluator ───────────────────────────────────────────────────

    def _evaluate_gate(
        self, tool_name: str, args: dict, agent_id: str = ""
    ) -> Optional[str]:
        """
        Returns error JSON string if tool_name is blocked by an active JSON gate.
        Returns None if allowed (no gate active, tool is exempt, or step allows it).
        Called from execute_tool() before existing hardcoded gates.
        """
        # GATES DESATIVADOS TEMPORARIAMENTE
        return None
        if agent_id == "debug-agent":
            return None
        if not self.db_manager or not self.current_chat_id:
            return None

        try:
            session = self.db_manager.get_session()
            try:
                for config in self._gate_all_configs():
                    lookup_file = config.get("lookup_file", "")
                    if not lookup_file:
                        continue

                    lookup_msg = self._gate_skill_lookup_msg(session, lookup_file)
                    if not lookup_msg:
                        continue

                    # This skill is active — evaluate its gate
                    exempt = set(config.get("exempt_tools", []))
                    if tool_name in exempt:
                        # cancel tool must release the gate immediately so subsequent
                        # checks (e.g. _gate_blocks_message_response) see it released.
                        if tool_name == "cancel":
                            self._gate_write_flow_cancelled(lookup_msg.isolated_chat_id)
                        return None

                    chat_id = lookup_msg.isolated_chat_id

                    # Cycle done → gate reset
                    if self._gate_cycle_ended(session, config, chat_id, lookup_msg):
                        return None

                    current_step_id = self._gate_find_current_step(
                        session, config, chat_id, lookup_msg
                    )
                    if not current_step_id:
                        return None  # all steps done

                    step_def = config["steps"][current_step_id]
                    allowed = set(step_def.get("allowed_tools", []))

                    if tool_name in allowed:
                        return None

                    blocked_error = step_def.get(
                        "blocked_error",
                        "Siga a sequência obrigatória da skill ativa.",
                    )
                    blocked_hint = step_def.get("blocked_hint", None)
                    correction = step_def.get("correction", [])

                    # Substitui <uuid> pelo document_id real do último documento salvo
                    # (relevante no step s-asset, após document_saved completar s-document)
                    if "<uuid>" in blocked_error or any(
                        "<uuid>" in str(c) for c in correction
                    ):
                        try:
                            from sqlalchemy import text as _sa_text

                            _doc_row = session.execute(
                                _sa_text(
                                    "SELECT document_id FROM documents "
                                    "WHERE chat_id = :cid ORDER BY created_at DESC LIMIT 1"
                                ),
                                {"cid": chat_id},
                            ).fetchone()
                            if _doc_row:
                                _real_uuid = _doc_row[0]
                                blocked_error = blocked_error.replace(
                                    "<uuid>", _real_uuid
                                )
                                correction = json.loads(
                                    json.dumps(correction).replace("<uuid>", _real_uuid)
                                )
                        except Exception as _ue:
                            debug(f"[GATE] Erro ao substituir <uuid>: {_ue}")

                    _blocked_resp = {
                        "success": False,
                        "error": blocked_error,
                        "tool": tool_name,
                        "correction_required": correction,
                    }
                    if blocked_hint:
                        _blocked_resp["hint"] = blocked_hint
                    return json.dumps(_blocked_resp, ensure_ascii=False)

                return None  # no active gate found
            finally:
                session.close()
        except Exception as e:
            debug(f"[GATE] Erro ao avaliar gate: {e}")
            return None

    # ── MessageProcessor helper ───────────────────────────────────────────────

    def _gate_blocks_message_response(self) -> bool:
        """
        Returns True if any active JSON gate has allow_message_response=false AND
        the gate cycle is not yet complete.
        Called by MessageProcessor to decide whether to block plain-text responses.
        """
        # GATES DESATIVADOS TEMPORARIAMENTE
        return False
        if not self.db_manager or not self.current_chat_id:
            return False

        try:
            session = self.db_manager.get_session()
            try:
                for config in self._gate_all_configs():
                    if config.get("allow_message_response", True):
                        continue  # this gate allows text

                    lookup_file = config.get("lookup_file", "")
                    if not lookup_file:
                        continue

                    lookup_msg = self._gate_skill_lookup_msg(session, lookup_file)
                    if not lookup_msg:
                        continue

                    chat_id = lookup_msg.isolated_chat_id

                    if self._gate_cycle_ended(session, config, chat_id, lookup_msg):
                        continue

                    current_step = self._gate_find_current_step(
                        session, config, chat_id, lookup_msg
                    )
                    if current_step:
                        return True  # blocked

                return False
            finally:
                session.close()
        except Exception as e:
            debug(f"[GATE] Erro ao verificar blocks_message_response: {e}")
            return False
