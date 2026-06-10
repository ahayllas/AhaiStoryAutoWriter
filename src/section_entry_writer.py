from __future__ import annotations

import json
import re

from config import (
    CURRENT_SECTION_ENTRY_PLAN_PATH,
    CURRENT_SECTION_STATUS_PATH,
    CURRENT_STORY_STATE_PATH,
    MODEL_WRITER,
    SECTION_ENTRY_WRITER_SYSTEM_PATH,
    SECTION_ENTRY_WRITER_USER_TEMPLATE_PATH,
    SEGMENTS_DIR,
    SEGMENT_LOGS_DIR,
)
from io_contract import load_json, load_text, save_json, save_text
from section_output_manager import assemble_section, rebuild_manuscript, save_section_entry
from utils import count_words_approx


def _json_text(value) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2)


def parse_entry_writer_output(raw: str) -> dict[str, str]:
    result = {
        "writing_plan": "",
        "narrative_prose": "",
    }

    pattern = r"```(?:text|markdown)?\s*(.*?)```"
    blocks = re.findall(pattern, raw, flags=re.DOTALL)

    for block in blocks:
        stripped = block.strip()
        if stripped.startswith("[WRITING_PLAN]"):
            result["writing_plan"] = stripped
        elif stripped.startswith("[NARRATIVE_PROSE]"):
            result["narrative_prose"] = stripped

    if not result["narrative_prose"]:
        result["narrative_prose"] = f"[NARRATIVE_PROSE]\n{raw.strip()}"
    if not result["writing_plan"]:
        result["writing_plan"] = "[WRITING_PLAN]\n- unavailable due to malformed model output"

    return result


def strip_labeled_block(block_text: str, label: str) -> str:
    text = block_text.strip()
    prefix = f"[{label}]"
    if text.startswith(prefix):
        return text[len(prefix):].strip()
    return text


class SectionEntryWriter:
    """
    Writer is intentionally non-authoritative.
    It follows CURRENT_SECTION_ENTRY_PLAN_PATH and only produces prose artifacts.
    """

    def __init__(self, llm_client) -> None:
        self.llm_client = llm_client

    def build_user_prompt(
        self,
        current_story_state: dict,
        current_section_entry_plan: dict,
    ) -> str:
        template = load_text(SECTION_ENTRY_WRITER_USER_TEMPLATE_PATH)
        return (
            template
            .replace("{{CURRENT_STORY_STATE_JSON}}", _json_text(current_story_state))
            .replace("{{CURRENT_SECTION_ENTRY_PLAN_JSON}}", _json_text(current_section_entry_plan))
        )

    def run(self) -> dict:
        current_section_status = load_json(CURRENT_SECTION_STATUS_PATH, {})
        current_story_state = load_json(CURRENT_STORY_STATE_PATH, {})
        current_section_entry_plan = load_json(CURRENT_SECTION_ENTRY_PLAN_PATH, {})

        if not current_section_status:
            raise RuntimeError("Missing current_section_status.")
        if not current_section_entry_plan:
            raise RuntimeError("Missing current_section_entry_plan.")

        system_prompt = load_text(SECTION_ENTRY_WRITER_SYSTEM_PATH)
        user_prompt = self.build_user_prompt(
            current_story_state=current_story_state,
            current_section_entry_plan=current_section_entry_plan,
        )

        raw = self.llm_client.generate_text(
            model=MODEL_WRITER,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
        )

        parsed = parse_entry_writer_output(raw)

        writing_plan = parsed["writing_plan"]
        narrative = strip_labeled_block(parsed["narrative_prose"], "NARRATIVE_PROSE")

        section_id = current_section_entry_plan.get("section_id") or current_section_status.get("section_id") or "unknown_section"
        entry_id = current_section_entry_plan.get("entry_id") or f"{section_id}__entry"

        save_text(SEGMENTS_DIR / f"{entry_id}.md", narrative)

        save_section_entry(
            section_id=section_id,
            entry_id=entry_id,
            narrative=narrative,
            meta={
                "section_entry_completed": True,
            },
        )
        assemble_section(section_id)
        rebuilt_manuscript = rebuild_manuscript()

        save_json(SEGMENT_LOGS_DIR / f"{entry_id}.json", {
            "kind": "section_entry",
            "section_id": section_id,
            "entry_id": entry_id,
            "writing_plan": writing_plan,
            "narrative_prose": narrative,
            "authoritative_state_patch": current_section_entry_plan.get("authoritative_state_patch", {}),
            "raw_output": raw,
        })

        current_words = count_words_approx(rebuilt_manuscript)

        return {
            "kind": "section_entry",
            "section_id": section_id,
            "entry_id": entry_id,
            "writing_plan": writing_plan,
            "narrative_prose": narrative,
            "authoritative_state_patch": current_section_entry_plan.get("authoritative_state_patch", {}),
            "current_words": current_words,
        }