from __future__ import annotations

import re

from config import (
    CURRENT_RECONCILED_SEGMENT_PLAN_PATH,
    CURRENT_SECTION_STATUS_PATH,
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
    JSON_REPAIR_MAX_RETRIES,
)
from io_contract import append_jsonl, load_json, load_text, save_json, save_text
from section_output_manager import assemble_section, rebuild_manuscript, save_section_segment
from utils import count_words_approx, extract_recent_excerpt


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

    if not result["narrative_prose"] and raw.strip():
        result["narrative_prose"] = f"[NARRATIVE_PROSE]\n{raw.strip()}"

    return result


def strip_labeled_block(block_text: str, label: str) -> str:
    text = block_text.strip()
    prefix = f"[{label}]"
    if text.startswith(prefix):
        return text[len(prefix):].strip()
    return text


def _extract_positive_int(value) -> int | None:
    try:
        ivalue = int(value)
    except Exception:
        return None
    if ivalue <= 0:
        return None
    return ivalue


def infer_segment_order(plan: dict) -> int | None:
    payloads = [plan]

    for key in ("queue_item", "segment_outline", "blueprint"):
        nested = plan.get(key)
        if isinstance(nested, dict):
            payloads.append(nested)

    candidate_keys = (
        "segment_order",
        "segment_index",
        "order",
        "sequence_index",
        "sequence_no",
        "position",
    )

    for payload in payloads:
        for key in candidate_keys:
            value = _extract_positive_int(payload.get(key))
            if value is not None:
                return value

    return None


def has_required_writer_blocks(parsed: dict[str, str]) -> bool:
    return bool(parsed.get("writing_plan") and parsed.get("state_update"))


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
        current_section_status = load_json(CURRENT_SECTION_STATUS_PATH, {})

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

        raw = ""
        parsed = {}
        last_missing = []

        for attempt in range(1, JSON_REPAIR_MAX_RETRIES + 1):
            raw = self.llm_client.generate_text(
                model=MODEL_WRITER,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
            )

            parsed = parse_writer_output(raw)

            missing = [
                key for key in ("writing_plan", "narrative_prose", "state_update")
                if not parsed.get(key)
            ]
            if not missing:
                break

            last_missing = missing
        else:
            raise RuntimeError(
                f"Writer output malformed after {JSON_REPAIR_MAX_RETRIES} retries; "
                f"missing required blocks: {', '.join(last_missing)}"
            )

        writing_plan = parsed["writing_plan"]
        narrative = strip_labeled_block(parsed["narrative_prose"], "NARRATIVE_PROSE")
        state_update = strip_labeled_block(parsed["state_update"], "STATE_UPDATE")

        segment_id = reconciled_plan.get("segment_id", "unknown_segment")
        section_id = (
            reconciled_plan.get("section_id")
            or current_section_status.get("section_id")
            or "unknown_section"
        )
        segment_order = infer_segment_order(reconciled_plan)

        save_text(SEGMENTS_DIR / f"{segment_id}.md", narrative)

        save_section_segment(
            section_id=section_id,
            segment_id=segment_id,
            narrative=narrative,
            segment_order=segment_order,
            meta={
                "source": "segment_writer",
            },
        )
        assemble_section(section_id)
        rebuilt_manuscript = rebuild_manuscript()

        save_json(SEGMENT_LOGS_DIR / f"{segment_id}.json", {
            "segment_id": segment_id,
            "section_id": section_id,
            "segment_order": segment_order,
            "writing_plan": writing_plan,
            "narrative_prose": narrative,
            "state_update": state_update,
            "raw_output": raw,
        })

        save_json(CURRENT_STATE_UPDATE_PATH, {
            "segment_id": segment_id,
            "raw_state_update_text": state_update,
        })

        # append_jsonl(METRICS_HISTORY_PATH, {
        #     "segment_id": segment_id,
        #     "target_metrics": reconciled_plan.get("metric_target", {}).get("snapshot", {}),
        # })

        current_words = count_words_approx(rebuilt_manuscript)
        project_status = load_json(PROJECT_STATUS_PATH, {})
        target_words = int(project_status.get("target_total_words", 0) or 0)

        return {
            "segment_id": segment_id,
            "section_id": section_id,
            "segment_order": segment_order,
            "writing_plan": writing_plan,
            "narrative_prose": narrative,
            "state_update": state_update,
            "current_words": current_words,
            "target_words": target_words,
        }
        
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

        return result