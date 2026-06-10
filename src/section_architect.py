from __future__ import annotations

from config import (
    CURRENT_SECTION_PLAN_PATH,
    CURRENT_SECTION_STATUS_PATH,
    CURRENT_STORY_STATE_PATH,
    SECTION_ARCHITECT_SYSTEM_PATH,
    SECTION_ARCHITECT_USER_TEMPLATE_PATH,
    MODEL_SECTION_ARCHITECT,
    STORY_PLAN_PATH,
)
from io_contract import load_json, load_text, save_json
from utils import fill_template


class SectionArchitect:
    def __init__(self, llm_client) -> None:
        self.llm_client = llm_client

    def build_section_context(
        self,
        story_plan: dict,
        current_section_status: dict,
        current_story_state: dict,
        existing_section_plan: dict,
        metric_schema: dict,
    ) -> dict:
        """Builds a reduced context instead of passing the full story plan."""
        sections = story_plan.get("sections", [])
        current_section_id = current_section_status.get("section_id")

        current_section = None
        prev_section = None
        next_section = None

        for i, sec in enumerate(sections):
            if sec.get("section_id") == current_section_id:
                current_section = sec
                if i > 0:
                    prev_section = sections[i - 1]
                if i < len(sections) - 1:
                    next_section = sections[i + 1]
                break

        # Create story_overview (slim version)
        story_overview = {
            "title": story_plan.get("title"),
            "premise": story_plan.get("premise"),
            "genre": story_plan.get("genre"),
            "tone": story_plan.get("tone"),
            "protagonist": story_plan.get("protagonist"),
            "core_conflict": story_plan.get("core_conflict"),
            "ending_overview": story_plan.get("ending_overview"),
        }

        return {
            "story_overview": story_overview,
            "prev_section": prev_section,
            "current_section": current_section,
            "next_section": next_section,
            "current_story_state": current_story_state,
            "existing_section_plan": existing_section_plan,
            "metric_schema": metric_schema,
        }

    def build_user_prompt(self, context: dict) -> str:
        template = load_text(SECTION_ARCHITECT_USER_TEMPLATE_PATH)
        return fill_template(template, {
            "STORY_OVERVIEW_JSON": context["story_overview"],
            "PREV_SECTION_JSON": context["prev_section"] or "null",
            "CURRENT_SECTION_JSON": context["current_section"],
            "NEXT_SECTION_JSON": context["next_section"] or "null",
            "CURRENT_STORY_STATE_JSON": context["current_story_state"],
            "EXISTING_SECTION_PLAN_JSON": context["existing_section_plan"],
            "METRIC_SCHEMA_JSON": context["metric_schema"],
        })

    def run(self, metric_schema: dict) -> dict:
        story_plan = load_json(STORY_PLAN_PATH, {})
        current_section_status = load_json(CURRENT_SECTION_STATUS_PATH, {})
        current_story_state = load_json(CURRENT_STORY_STATE_PATH, {})
        existing_section_plan = load_json(CURRENT_SECTION_PLAN_PATH, {})

        if not current_section_status:
            raise RuntimeError("Missing current section status.")

        context = self.build_section_context(
            story_plan=story_plan,
            current_section_status=current_section_status,
            current_story_state=current_story_state,
            existing_section_plan=existing_section_plan,
            metric_schema=metric_schema,
        )

        system_prompt = load_text(SECTION_ARCHITECT_SYSTEM_PATH)
        user_prompt = self.build_user_prompt(context)

        section_plan = self.llm_client.generate_json(
            model=MODEL_SECTION_ARCHITECT,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
        )

        save_json(CURRENT_SECTION_PLAN_PATH, section_plan)
        return section_plan