from __future__ import annotations

import re

from config import (
    CURRENT_RECONCILED_SEGMENT_PLAN_PATH,
    CURRENT_SEGMENT_PLAN_PATH,
    CURRENT_SITUATION_BRIEF_PATH,
    CURRENT_STATE_UPDATE_PATH,
    CURRENT_STORY_STATE_PATH,
    MANUSCRIPT_PATH,
    METRICS_HISTORY_PATH,
    MODEL_WRITER,
    PROJECT_STATUS_PATH,
    SEGMENTS_DIR,
    SEGMENT_LOGS_DIR,
    WRITER_SYSTEM_PATH,
    WRITER_USER_TEMPLATE_PATH,
)
from io_contract import append_jsonl, load_json, load_text, save_json, save_text
from utils import append_markdown_section, count_words_approx, extract_recent_excerpt


def parse_writer_output(raw: str) -> dict[str, str]:
    result = {
        "writing_plan": "",
        "narrative_prose": "",
        "state_update": "",
    }

    pattern = r"```(?:text|markdown)?\s*(.*?)```"
    blocks = re.findall(pattern, raw, flags=re.DOTALL)

    for block in blocks:
        stripped = block.strip()
        if stripped.startswith("[WRITING_PLAN]"):
            result["writing_plan"] = stripped
        elif stripped.startswith("[NARRATIVE_PROSE]"):
            result["narrative_prose"] = stripped
        elif stripped.startswith("[STATE_UPDATE]"):
            result["state_update"] = stripped

    if not result["narrative_prose"]:
        result["narrative_prose"] = f"[NARRATIVE_PROSE]\n{raw.strip()}"
    if not result["writing_plan"]:
        result["writing_plan"] = "[WRITING_PLAN]\n- unavailable due to malformed model output"
    if not result["state_update"]:
        result["state_update"] = "[STATE_UPDATE]\n[KNOWN_FACTS_ADD]\n- unavailable due to malformed model output"

    return result


def strip_labeled_block(block_text: str, label: str) -> str:
    text = block_text.strip()
    prefix = f"[{label}]"
    if text.startswith(prefix):
        return text[len(prefix):].strip()
    return text


class SegmentWriter:
    def __init__(self, llm_client, default_segment_words: int = 300) -> None:
        self.llm_client = llm_client
        self.default_segment_words = default_segment_words

    def build_user_prompt(
        self,
        current_situation_brief: dict,
        current_reconciled_segment_plan: dict,
        recent_excerpt: str,
        current_story_state: dict,
    ) -> str:
        template = load_text(WRITER_USER_TEMPLATE_PATH)
        return template \
            .replace("{{CURRENT_SITUATION_BRIEF_JSON}}", str(current_situation_brief)) \
            .replace("{{CURRENT_RECONCILED_SEGMENT_PLAN_JSON}}", str(current_reconciled_segment_plan)) \
            .replace("{{CURRENT_STORY_STATE_JSON}}", str(current_story_state)) \
            .replace("{{RECENT_EXCERPT}}", recent_excerpt) \
            .replace("{{WORD_COUNT}}", str(self.default_segment_words)) 

    def run(self) -> dict:
        situation_brief = load_json(CURRENT_SITUATION_BRIEF_PATH, {})
        reconciled_plan = load_json(CURRENT_RECONCILED_SEGMENT_PLAN_PATH, {})
        if not reconciled_plan:
            reconciled_plan = load_json(CURRENT_SEGMENT_PLAN_PATH, {})
        current_story_state = load_json(CURRENT_STORY_STATE_PATH, {})

        if not situation_brief:
            raise RuntimeError("Missing current_situation_brief.")
        if not reconciled_plan:
            raise RuntimeError("Missing current_reconciled_segment_plan/current_segment_plan.")

        manuscript_before = load_text(MANUSCRIPT_PATH, "")
        recent_excerpt = extract_recent_excerpt(manuscript_before)

        system_prompt = load_text(WRITER_SYSTEM_PATH)
        user_prompt = self.build_user_prompt(
            current_situation_brief=situation_brief,
            current_reconciled_segment_plan=reconciled_plan,
            recent_excerpt=recent_excerpt,
            current_story_state=current_story_state,
        )

        raw = self.llm_client.generate_text(
            model=MODEL_WRITER,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
        )

        parsed = parse_writer_output(raw)

        writing_plan = parsed["writing_plan"]
        narrative = strip_labeled_block(parsed["narrative_prose"], "NARRATIVE_PROSE")
        state_update = strip_labeled_block(parsed["state_update"], "STATE_UPDATE")

        combined = append_markdown_section(manuscript_before, narrative)
        save_text(MANUSCRIPT_PATH, combined)

        segment_id = reconciled_plan.get("segment_id", "unknown_segment")

        save_text(SEGMENTS_DIR / f"{segment_id}.md", narrative)
        save_json(SEGMENT_LOGS_DIR / f"{segment_id}.json", {
            "segment_id": segment_id,
            "writing_plan": writing_plan,
            "narrative_prose": narrative,
            "state_update": state_update,
            "raw_output": raw,
        })

        save_json(CURRENT_STATE_UPDATE_PATH, {
            "segment_id": segment_id,
            "raw_state_update_text": state_update,
        })

        append_jsonl(METRICS_HISTORY_PATH, {
            "segment_id": segment_id,
            "target_metrics": reconciled_plan.get("metric_target", {}).get("snapshot", {}),
        })

        current_words = count_words_approx(combined)
        project_status = load_json(PROJECT_STATUS_PATH, {})
        target_words = int(project_status.get("target_total_words", 0) or 0)

        return {
            "segment_id": segment_id,
            "writing_plan": writing_plan,
            "narrative_prose": narrative,
            "state_update": state_update,
            "current_words": current_words,
            "target_words": target_words,
        }