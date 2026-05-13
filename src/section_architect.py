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
    """
    Build one section-level execution blueprint.

    Responsibilities:
    - read current active section status
    - read whole story plan and current story state
    - generate a section plan exactly once per active section
    - persist the runtime section plan
    """

    def __init__(self, llm_client) -> None:
        self.llm_client = llm_client

    def build_user_prompt(
        self,
        story_plan: dict,
        current_section_status: dict,
        current_story_state: dict,
        existing_section_plan: dict,
        metric_schema: dict,
    ) -> str:
        template = load_text(SECTION_ARCHITECT_USER_TEMPLATE_PATH)
        return fill_template(template, {
            "STORY_PLAN_JSON": story_plan,
            "CURRENT_SECTION_STATUS_JSON": current_section_status,
            "CURRENT_STORY_STATE_JSON": current_story_state,
            "EXISTING_SECTION_PLAN_JSON": existing_section_plan,
            "METRIC_SCHEMA_JSON": metric_schema,
        })

    def run(self, metric_schema: dict) -> dict:
        story_plan = load_json(STORY_PLAN_PATH, {})
        current_section_status = load_json(CURRENT_SECTION_STATUS_PATH, {})
        current_story_state = load_json(CURRENT_STORY_STATE_PATH, {})
        existing_section_plan = load_json(CURRENT_SECTION_PLAN_PATH, {})

        if not current_section_status:
            raise RuntimeError("Missing current section status.")

        system_prompt = load_text(SECTION_ARCHITECT_SYSTEM_PATH)
        user_prompt = self.build_user_prompt(
            story_plan=story_plan,
            current_section_status=current_section_status,
            current_story_state=current_story_state,
            existing_section_plan=existing_section_plan,
            metric_schema=metric_schema,
        )

        section_plan = self.llm_client.generate_json(
            model=MODEL_SECTION_ARCHITECT,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
        )

        save_json(CURRENT_SECTION_PLAN_PATH, section_plan)
        return section_plan