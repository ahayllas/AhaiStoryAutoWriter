from __future__ import annotations

from config import CURRENT_SEGMENT_PLAN_PATH, CURRENT_STORY_STATE_PATH, REVEAL_GUARD_PACKAGE_PATH
from io_contract import load_json, save_json


class RevealGuardBuilder:
    """
    MVP:
    - derive a minimal reveal guard package from current segment constraints
    - no global reveal map yet
    """

    def build(self) -> dict:
        current_story_state = load_json(CURRENT_STORY_STATE_PATH, {})
        current_segment_plan = load_json(CURRENT_SEGMENT_PLAN_PATH, {})

        package = {
            "segment_id": current_segment_plan.get("segment_id"),
            "section_id": current_segment_plan.get("section_id"),
            "hard_reveal_constraints": current_segment_plan.get("reveal_constraints", []),
            "known_facts": current_story_state.get("known_facts", []),
            "active_threads": current_story_state.get("active_threads", []),
            "policy_notes": [
                "Do not confirm prohibited reveals.",
                "Do not collapse unresolved mystery unless explicitly allowed by segment plan.",
                "Prefer implication over explicit confirmation when information_release is low."
            ],
        }

        save_json(REVEAL_GUARD_PACKAGE_PATH, package)
        return package