from __future__ import annotations

from config import (
    CURRENT_SECTION_PLAN_PATH,
    CURRENT_SECTION_STATUS_PATH,
    CURRENT_SEGMENT_PLAN_PATH,
    CURRENT_STORY_STATE_PATH,
    EXPANDER_SYSTEM_PATH,
    EXPANDER_USER_TEMPLATE_PATH,
    MODEL_EXPANDER,
    STORY_PLAN_PATH,
)
from io_contract import load_json, load_text, save_json
from utils import fill_template


class SectionPlanExhaustedError(RuntimeError):
    """Raised when the current section is still active but no matching blueprint remains."""


class SectionExpander:
    """
    Segment-level executor that must follow the current section plan.

    Despite the legacy class name, this component should only expand
    exactly one segment blueprint into one executable segment plan.
    """

    def __init__(self, llm_client) -> None:
        self.llm_client = llm_client

    def _pick_segment_blueprint(
        self,
        section_plan: dict,
        queue_item: dict,
    ) -> dict:
        blueprints = section_plan.get("segment_blueprints", [])
        if not isinstance(blueprints, list):
            blueprints = []

        target_index = int(queue_item.get("section_step", 0) or 0)

        # 1) exact match by segment_index
        for bp in blueprints:
            if not isinstance(bp, dict):
                continue
            try:
                if int(bp.get("segment_index", 0) or 0) == target_index:
                    return bp
            except Exception:
                continue

        # 2) fallback by alternative step keys
        for bp in blueprints:
            if not isinstance(bp, dict):
                continue
            for key in ("section_step", "ordinal", "step"):
                try:
                    if int(bp.get(key, 0) or 0) == target_index:
                        return bp
                except Exception:
                    continue

        # 3) fallback by 1-based position
        idx = target_index - 1
        if 0 <= idx < len(blueprints):
            bp = blueprints[idx]
            if isinstance(bp, dict):
                return bp

        return {}

    def build_user_prompt(
        self,
        story_plan: dict,
        current_section_status: dict,
        current_section_plan: dict,
        target_segment_blueprint: dict,
        queue_item: dict,
        current_story_state: dict,
        metric_schema: dict,
    ) -> str:
        template = load_text(EXPANDER_USER_TEMPLATE_PATH)
        return fill_template(template, {
            "STORY_PLAN_JSON": story_plan,
            "CURRENT_SECTION_STATUS_JSON": current_section_status,
            "CURRENT_SECTION_PLAN_JSON": current_section_plan,
            "TARGET_SEGMENT_BLUEPRINT_JSON": target_segment_blueprint,
            "QUEUE_ITEM_JSON": queue_item,
            "CURRENT_STORY_STATE_JSON": current_story_state,
            "METRIC_SCHEMA_JSON": metric_schema,
        })

    def run(self, queue_item: dict, metric_schema: dict) -> dict:
        story_plan = load_json(STORY_PLAN_PATH, {})
        current_section_status = load_json(CURRENT_SECTION_STATUS_PATH, {})
        current_section_plan = load_json(CURRENT_SECTION_PLAN_PATH, {})
        current_story_state = load_json(CURRENT_STORY_STATE_PATH, {})

        if not current_section_plan:
            raise RuntimeError("Missing current section plan.")

        target_segment_blueprint = self._pick_segment_blueprint(
            section_plan=current_section_plan,
            queue_item=queue_item,
        )
        if not target_segment_blueprint:
            blueprints = current_section_plan.get("segment_blueprints", [])
            available_indexes = []
            for bp in blueprints:
                if not isinstance(bp, dict):
                    continue
                available_indexes.append({
                    "segment_index": bp.get("segment_index"),
                    "section_step": bp.get("section_step"),
                    "ordinal": bp.get("ordinal"),
                    "step": bp.get("step"),
                    "segment_id": bp.get("segment_id"),
                })

            raise SectionPlanExhaustedError(
                "SECTION_PLAN_EXHAUSTED: no target segment blueprint for current queue item. "
                f"section_id={current_section_status.get('section_id')!r}, "
                f"queue_item={queue_item!r}, "
                f"available_blueprints={available_indexes!r}"
            )

        system_prompt = load_text(EXPANDER_SYSTEM_PATH)
        user_prompt = self.build_user_prompt(
            story_plan=story_plan,
            current_section_status=current_section_status,
            current_section_plan=current_section_plan,
            target_segment_blueprint=target_segment_blueprint,
            queue_item=queue_item,
            current_story_state=current_story_state,
            metric_schema=metric_schema,
        )

        expanded = self.llm_client.generate_json(
            model=MODEL_EXPANDER,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
        )

        save_json(CURRENT_SEGMENT_PLAN_PATH, expanded)
        return expanded