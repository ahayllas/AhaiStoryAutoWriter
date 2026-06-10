from __future__ import annotations

from config import (
    CURRENT_SECTION_ENTRY_PLAN_PATH,
    CURRENT_SECTION_PLAN_PATH,
    CURRENT_SECTION_STATUS_PATH,
    CURRENT_STATE_UPDATE_PATH,
    CURRENT_STORY_STATE_PATH,
    SECTION_ENTRY_PLANNER_SYSTEM_PATH,
    SECTION_ENTRY_PLANNER_USER_TEMPLATE_PATH,
    MODEL_SECTION_ARCHITECT,
    STORY_PLAN_PATH,
)
from io_contract import load_json, load_text, save_json
from state_manager import StateManager
from utils import fill_template


class SectionEntryPlanner:
    """
    Plans the pre-section entry layer that sits before section_architect.

    Responsibilities:
    - consume the incoming between_section_bridge for the active section
    - build a reduced planning context with strong time anchoring
    - plan what the entry writer should cover vs defer
    - generate a state update that prepares downstream components
    - persist both the entry plan and the state update payload
    - apply the state patch immediately so downstream steps read updated state

    Notes:
    - This planner intentionally does NOT feed next_section.
    - It is meant to make the first real segment of the section start from a correct state.
    """

    def __init__(self, llm_client, state_manager: StateManager) -> None:
        self.llm_client = llm_client
        self.state_manager = state_manager

    def _find_active_section_bundle(
        self,
        story_plan: dict,
        current_section_status: dict,
    ) -> dict:
        sections = story_plan.get("sections", [])
        bridges = story_plan.get("between_section_bridges", [])
        current_section_id = current_section_status.get("section_id")

        current_section = None
        prev_section = None
        incoming_bridge = None
        outgoing_bridge = None

        for i, sec in enumerate(sections):
            if sec.get("section_id") == current_section_id:
                current_section = sec
                if i > 0:
                    prev_section = sections[i - 1]
                if i < len(sections) - 1:
                    next_section = sections[i + 1]
                else:
                    next_section = None
                break
        else:
            next_section = None

        if prev_section and current_section:
            prev_id = prev_section.get("section_id")
            cur_id = current_section.get("section_id")
            for bridge in bridges:
                if (
                    bridge.get("from_section_id") == prev_id
                    and bridge.get("to_section_id") == cur_id
                ):
                    incoming_bridge = bridge
                    break

        if current_section and next_section:
            cur_id = current_section.get("section_id")
            next_id = next_section.get("section_id")
            for bridge in bridges:
                if (
                    bridge.get("from_section_id") == cur_id
                    and bridge.get("to_section_id") == next_id
                ):
                    outgoing_bridge = bridge
                    break

        return {
            "prev_section": prev_section,
            "current_section": current_section,
            "incoming_bridge": incoming_bridge,
            "outgoing_bridge": outgoing_bridge,
        }

    def _safe_int(self, value):
        try:
            if value is None:
                return None
            return int(value)
        except Exception:
            return None

    def _build_time_context(
        self,
        prev_section: dict | None,
        current_section: dict | None,
        incoming_bridge: dict | None,
    ) -> dict:
        prev_tw = (prev_section or {}).get("time_window", {})
        cur_tw = (current_section or {}).get("time_window", {})

        prev_end_day = self._safe_int(prev_tw.get("end_day"))
        current_start_day = self._safe_int(cur_tw.get("start_day"))
        current_end_day = self._safe_int(cur_tw.get("end_day"))

        bridge_start_day = self._safe_int((incoming_bridge or {}).get("start_day"))
        bridge_end_day = self._safe_int((incoming_bridge or {}).get("end_day"))

        elapsed_days_from_prev_section = None
        if prev_end_day is not None and current_start_day is not None:
            elapsed_days_from_prev_section = current_start_day - prev_end_day

        continuity_mode = "unknown"
        if prev_section is None:
            continuity_mode = "opening_section"
        elif elapsed_days_from_prev_section is None:
            continuity_mode = "unknown"
        elif elapsed_days_from_prev_section <= 0:
            continuity_mode = "continuous_or_same_day"
        elif elapsed_days_from_prev_section == 1:
            continuity_mode = "next_day"
        elif elapsed_days_from_prev_section <= 3:
            continuity_mode = "short_skip"
        else:
            continuity_mode = "timeskip"

        return {
            "prev_section_end_day": prev_end_day,
            "current_section_start_day": current_start_day,
            "current_section_end_day": current_end_day,
            "incoming_bridge_start_day": bridge_start_day,
            "incoming_bridge_end_day": bridge_end_day,
            "elapsed_days_from_prev_section": elapsed_days_from_prev_section,
            "continuity_mode": continuity_mode,
            "prev_time_label": prev_tw.get("label"),
            "current_time_label": cur_tw.get("label"),
            "incoming_bridge_time_elapsed": (incoming_bridge or {}).get("time_elapsed"),
            "incoming_bridge_continuity_notes": (incoming_bridge or {}).get("continuity_notes"),
        }

    def build_entry_context(
        self,
        story_plan: dict,
        current_section_status: dict,
        current_story_state: dict,
        existing_section_plan: dict,
        existing_entry_plan: dict,
        metric_schema: dict,
    ) -> dict:
        section_bundle = self._find_active_section_bundle(
            story_plan=story_plan,
            current_section_status=current_section_status,
        )

        prev_section = section_bundle["prev_section"]
        current_section = section_bundle["current_section"]
        incoming_bridge = section_bundle["incoming_bridge"]
        outgoing_bridge = section_bundle["outgoing_bridge"]

        time_context = self._build_time_context(
            prev_section=prev_section,
            current_section=current_section,
            incoming_bridge=incoming_bridge,
        )

        context = {
            "prev_section": prev_section,
            "current_section": current_section,
            "incoming_bridge": incoming_bridge,
            "outgoing_bridge": outgoing_bridge,
            "time_context": time_context,
            "current_section_status": current_section_status,
            "current_story_state": current_story_state,
            "existing_section_plan": existing_section_plan,
            "existing_entry_plan": existing_entry_plan,
            "metric_schema": metric_schema,
        }


        story_overview = {
            "title": story_plan.get("title"),
            "premise": story_plan.get("premise"),
            "genre": story_plan.get("genre"),
            "tone": story_plan.get("tone"),
            "setting": story_plan.get("setting")
        }
        context["story_overview"] = story_overview

        return context

    def build_user_prompt(self, context: dict) -> str:
        template = load_text(SECTION_ENTRY_PLANNER_USER_TEMPLATE_PATH)
        return fill_template(template, {
            "STORY_OVERVIEW_JSON": context["story_overview"],
            "PREV_SECTION_JSON": context["prev_section"] or "null",
            "CURRENT_SECTION_JSON": context["current_section"] or "null",
            "INCOMING_BRIDGE_JSON": context["incoming_bridge"] or "null",
            "OUTGOING_BRIDGE_JSON": context["outgoing_bridge"] or "null",
            "TIME_CONTEXT_JSON": context["time_context"],
            "CURRENT_SECTION_STATUS_JSON": context["current_section_status"],
            "CURRENT_STORY_STATE_JSON": context["current_story_state"],
            "EXISTING_SECTION_PLAN_JSON": context["existing_section_plan"] or {},
            "EXISTING_ENTRY_PLAN_JSON": context["existing_entry_plan"] or {},
            "METRIC_SCHEMA_JSON": context["metric_schema"],
        })

    def _extract_state_update_dict(self, entry_plan: dict) -> dict | None:
        for key in (
            "authoritative_state_patch",
            "state_update",
            "current_state_update",
            "state_update_payload",
        ):
            payload = entry_plan.get(key)
            if isinstance(payload, dict) and payload:
                return payload
        return None

    def _extract_state_update_text(self, entry_plan: dict) -> str:
        for key in (
            "state_update_text",
            "raw_state_update_text",
            "state_update_raw_text",
        ):
            value = entry_plan.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return ""

    def _resolve_state_update_patch(self, entry_plan: dict) -> dict | None:
        payload = self._extract_state_update_dict(entry_plan)
        if payload:
            return self.state_manager._normalize_state_patch(payload)

        raw_text = self._extract_state_update_text(entry_plan)
        if raw_text:
            return self.state_manager.parse_state_update_text(raw_text)

        return None

    def _persist_state_update(self, state_update_payload: dict) -> None:
        if not state_update_payload:
            return

        payload = dict(state_update_payload)
        payload.setdefault("_source", "section_entry_planner")
        save_json(CURRENT_STATE_UPDATE_PATH, payload)

    def run(self, metric_schema: dict) -> dict:
        story_plan = load_json(STORY_PLAN_PATH, {})
        current_section_status = load_json(CURRENT_SECTION_STATUS_PATH, {})
        current_story_state = load_json(CURRENT_STORY_STATE_PATH, {})
        existing_section_plan = load_json(CURRENT_SECTION_PLAN_PATH, {})
        existing_entry_plan = load_json(CURRENT_SECTION_ENTRY_PLAN_PATH, {})

        if not current_section_status:
            raise RuntimeError("Missing current section status.")

        context = self.build_entry_context(
            story_plan=story_plan,
            current_section_status=current_section_status,
            current_story_state=current_story_state,
            existing_section_plan=existing_section_plan,
            existing_entry_plan=existing_entry_plan,
            metric_schema=metric_schema,
        )

        if not context.get("current_section"):
            raise RuntimeError("Active section not found in story plan.")

        system_prompt = load_text(SECTION_ENTRY_PLANNER_SYSTEM_PATH)
        user_prompt = self.build_user_prompt(context)

        entry_plan = self.llm_client.generate_json(
            model=MODEL_SECTION_ARCHITECT,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
        )

        save_json(CURRENT_SECTION_ENTRY_PLAN_PATH, entry_plan)

        state_patch = self._resolve_state_update_patch(entry_plan)
        apply_result = None

        if state_patch:
            self._persist_state_update(state_patch)
            apply_result = self.state_manager.apply_patch(state_patch)

        return {
            "entry_plan": entry_plan,
            "state_patch": state_patch,
            "apply_result": apply_result,
        }