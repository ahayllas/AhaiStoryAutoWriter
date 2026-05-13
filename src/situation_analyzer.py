from __future__ import annotations

from config import (
    ANALYZER_SYSTEM_PATH,
    ANALYZER_USER_TEMPLATE_PATH,
    CURRENT_FACT_BRIEF_PATH,
    CURRENT_SEGMENT_PLAN_PATH,
    CURRENT_SITUATION_BRIEF_PATH,
    CURRENT_STORY_STATE_PATH,
    MODEL_ANALYZER,
    REVEAL_GUARD_PACKAGE_PATH,
)
from io_contract import load_json, load_text, save_json
from utils import fill_template


class SituationAnalyzer:
    def __init__(self, llm_client) -> None:
        self.llm_client = llm_client

    def build_user_prompt(
        self,
        segment_plan: dict,
        current_story_state: dict,
        current_fact_brief: dict,
        reveal_guard_package: dict,
        metric_schema: dict,
    ) -> str:
        template = load_text(ANALYZER_USER_TEMPLATE_PATH)
        return fill_template(template, {
            "CURRENT_SEGMENT_PLAN_JSON": segment_plan,
            "CURRENT_STORY_STATE_JSON": current_story_state,
            "CURRENT_FACT_BRIEF_JSON": current_fact_brief,
            "REVEAL_GUARD_PACKAGE_JSON": reveal_guard_package,
            "METRIC_SCHEMA_JSON": metric_schema,
        })

    def run(self, metric_schema: dict) -> dict:
        segment_plan = load_json(CURRENT_SEGMENT_PLAN_PATH, {})
        current_story_state = load_json(CURRENT_STORY_STATE_PATH, {})
        current_fact_brief = load_json(CURRENT_FACT_BRIEF_PATH, {})
        reveal_guard_package = load_json(REVEAL_GUARD_PACKAGE_PATH, {})

        if not segment_plan:
            raise RuntimeError("Missing current segment plan.")

        system_prompt = load_text(ANALYZER_SYSTEM_PATH)
        user_prompt = self.build_user_prompt(
            segment_plan=segment_plan,
            current_story_state=current_story_state,
            current_fact_brief=current_fact_brief,
            reveal_guard_package=reveal_guard_package,
            metric_schema=metric_schema,
        )

        brief = self.llm_client.generate_json(
            model=MODEL_ANALYZER,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
        )

        save_json(CURRENT_SITUATION_BRIEF_PATH, brief)
        return brief