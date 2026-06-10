from __future__ import annotations

import json
import re
from dataclasses import dataclass
from difflib import unified_diff
from pathlib import Path
from typing import Any

from config import (
    CURRENT_SECTION_STATUS_PATH,
    CURRENT_STORY_STATE_PATH,
    MODEL_PROOFREADER,
    PROJECT_META_PATH,
    SECTION_PROOFREADER_SYSTEM_PATH,
    SECTION_PROOFREADER_USER_TEMPLATE_PATH,
    SECTIONS_DIR,
)
from io_contract import load_json, load_text, save_json, save_text
from section_output_manager import assemble_section, rebuild_manuscript
from utils import count_words_approx


def _json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2)


def parse_section_proofreader_output(raw: str) -> dict[str, str]:
    result = {
        "edit_plan": "",
        "proofread_section": "",
        "change_notes": "",
    }

    pattern = r"```(?:text|markdown)?\s*(.*?)```"
    blocks = re.findall(pattern, raw, flags=re.DOTALL)

    for block in blocks:
        stripped = block.strip()
        if stripped.startswith("[EDIT_PLAN]"):
            result["edit_plan"] = stripped
        elif stripped.startswith("[PROOFREAD_SECTION]"):
            result["proofread_section"] = stripped
        elif stripped.startswith("[CHANGE_NOTES]"):
            result["change_notes"] = stripped

    if not result["proofread_section"]:
        result["proofread_section"] = f"[PROOFREAD_SECTION]\n{raw.strip()}"
    if not result["edit_plan"]:
        result["edit_plan"] = "[EDIT_PLAN]\n- unavailable due to malformed model output"
    if not result["change_notes"]:
        result["change_notes"] = "[CHANGE_NOTES]\n- unavailable due to malformed model output"

    return result


def strip_labeled_block(block_text: str, label: str) -> str:
    text = block_text.strip()
    prefix = f"[{label}]"
    if text.startswith(prefix):
        return text[len(prefix):].strip()
    return text


def _section_dir(section_id: str) -> Path:
    return SECTIONS_DIR / section_id


def _proofreading_dir(section_id: str) -> Path:
    return _section_dir(section_id) / "proofreading"


def _load_section_index(section_id: str) -> dict[str, Any]:
    path = _section_dir(section_id) / "index.json"
    return load_json(path, {})


def _extract_candidate_terms(text: str) -> list[str]:
    """
    Heuristic named-term extractor.
    Conservative first version:
    - Latin words / identifiers / mixed alnum underscore terms
    - digit-containing tokens
    - quoted terms
    - CJK multi-char bracketed / emphasized tokens are not reliably extractable here,
      so we focus on terms likely to matter operationally.
    """
    found: set[str] = set()

    patterns = [
        r"\b[A-Za-z_][A-Za-z0-9_\-]{1,}\b",
        r"\b[A-Za-z0-9_\-]*\d+[A-Za-z0-9_\-]*\b",
        r"「([^」]{1,30})」",
        r"『([^』]{1,30})』",
        r"“([^”]{1,30})”",
        r"\"([^\"]{1,30})\"",
    ]

    for pattern in patterns:
        for m in re.findall(pattern, text):
            if isinstance(m, tuple):
                for x in m:
                    x = x.strip()
                    if len(x) >= 2:
                        found.add(x)
            else:
                x = str(m).strip()
                if len(x) >= 2:
                    found.add(x)

    return sorted(found)


def _find_missing_terms(original: str, revised: str) -> list[str]:
    original_terms = _extract_candidate_terms(original)
    if not original_terms:
        return []

    missing: list[str] = []
    for term in original_terms:
        if term not in revised:
            missing.append(term)
    return missing


def _make_unified_diff(original: str, revised: str, section_id: str) -> str:
    original_lines = original.splitlines()
    revised_lines = revised.splitlines()
    diff_lines = list(
        unified_diff(
            original_lines,
            revised_lines,
            fromfile=f"{section_id}/assembled.md",
            tofile=f"{section_id}/proofread.md",
            lineterm="",
            n=3,
        )
    )

    if not diff_lines:
        return "# Diff\n\nNo textual differences detected.\n"

    body = "\n".join(diff_lines)
    return f"# Diff\n\n```diff\n{body}\n```\n"


@dataclass
class ProofreadGuards:
    max_relative_word_delta: float = 0.10
    max_absolute_word_delta: int = 300
    reject_on_missing_named_terms: bool = True


class SectionProofreader:
    def __init__(
        self,
        llm_client,
        auto_accept: bool = False,
        guards: ProofreadGuards | None = None,
    ) -> None:
        self.llm_client = llm_client
        self.auto_accept = auto_accept
        self.guards = guards or ProofreadGuards()

    def build_user_prompt(
        self,
        language_hint: str,
        section_id: str,
        section_context: dict[str, Any],
        current_story_state: dict[str, Any],
        section_text: str,
    ) -> str:
        template = load_text(SECTION_PROOFREADER_USER_TEMPLATE_PATH)
        return (
            template
            .replace("{{LANGUAGE_HINT}}", language_hint)
            .replace("{{SECTION_ID}}", section_id)
            .replace("{{SECTION_CONTEXT_JSON}}", _json_text(section_context))
            .replace("{{CURRENT_STORY_STATE_JSON}}", _json_text(current_story_state))
            .replace("{{SECTION_TEXT}}", section_text)
        )

    def _evaluate_guards(self, original_text: str, revised_text: str) -> dict[str, Any]:
        original_words = count_words_approx(original_text)
        revised_words = count_words_approx(revised_text)
        abs_delta = abs(revised_words - original_words)
        rel_delta = abs_delta / max(1, original_words)

        missing_terms = _find_missing_terms(original_text, revised_text)

        violations: list[str] = []
        if abs_delta > self.guards.max_absolute_word_delta and rel_delta > self.guards.max_relative_word_delta:
            violations.append("word_count_delta_exceeded")

        if self.guards.reject_on_missing_named_terms and missing_terms:
            violations.append("named_term_drift_detected")

        return {
            "original_words": original_words,
            "revised_words": revised_words,
            "absolute_word_delta": abs_delta,
            "relative_word_delta": rel_delta,
            "missing_named_terms": missing_terms,
            "violations": violations,
            "passed": not violations,
        }

    def run(self, section_id: str | None = None) -> dict[str, Any]:
        section_status = load_json(CURRENT_SECTION_STATUS_PATH, {})
        if not section_id:
            section_id = section_status.get("section_id")

        if not section_id:
            raise RuntimeError("Missing section_id.")

        section_dir = _section_dir(section_id)
        section_dir.mkdir(parents=True, exist_ok=True)
        proof_dir = _proofreading_dir(section_id)
        proof_dir.mkdir(parents=True, exist_ok=True)

        assembled_text = assemble_section(section_id).strip()
        if not assembled_text:
            raise RuntimeError(f"Section {section_id} has no assembled text to proofread.")

        project_meta = load_json(PROJECT_META_PATH, {})
        current_story_state = load_json(CURRENT_STORY_STATE_PATH, {})
        section_index = _load_section_index(section_id)

        language_hint = project_meta.get("language_hint", "")
        section_context = {
            "section_id": section_id,
            "section_index": section_index,
            "section_status": section_status,
        }

        system_prompt = load_text(SECTION_PROOFREADER_SYSTEM_PATH)
        user_prompt = self.build_user_prompt(
            language_hint=language_hint,
            section_id=section_id,
            section_context=section_context,
            current_story_state=current_story_state,
            section_text=assembled_text,
        )

        raw = self.llm_client.generate_text(
            model=MODEL_PROOFREADER,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
        )

        parsed = parse_section_proofreader_output(raw)

        edit_plan = strip_labeled_block(parsed["edit_plan"], "EDIT_PLAN")
        proofread_section = strip_labeled_block(parsed["proofread_section"], "PROOFREAD_SECTION")
        change_notes = strip_labeled_block(parsed["change_notes"], "CHANGE_NOTES")

        proofread_path = section_dir / "proofread.md"
        final_path = section_dir / "final.md"
        diff_path = proof_dir / "diff.md"

        save_text(proofread_path, proofread_section)

        guard_report = self._evaluate_guards(
            original_text=assembled_text,
            revised_text=proofread_section,
        )

        diff_text = _make_unified_diff(
            original=assembled_text,
            revised=proofread_section,
            section_id=section_id,
        )
        save_text(diff_path, diff_text)

        accepted = False
        acceptance_reason = "auto_accept_disabled"
        if self.auto_accept:
            if guard_report["passed"]:
                save_text(final_path, proofread_section)
                rebuild_manuscript()
                accepted = True
                acceptance_reason = "auto_accept_passed_all_guards"
            else:
                acceptance_reason = "auto_accept_blocked_by_guards"

        result = {
            "section_id": section_id,
            "assembled_words": count_words_approx(assembled_text),
            "proofread_words": count_words_approx(proofread_section),
            "edit_plan": edit_plan,
            "change_notes": change_notes,
            "auto_accept": self.auto_accept,
            "accepted": accepted,
            "acceptance_reason": acceptance_reason,
            "guard_report": guard_report,
            "proofread_file": str(proofread_path),
            "final_file": str(final_path),
            "diff_file": str(diff_path),
            "raw_output": raw,
        }

        save_json(proof_dir / "result.json", result)

        section_index["proofreading_status"] = (
            "accepted" if accepted else "completed"
        )
        section_index["proofread_file"] = "proofread.md"
        section_index["last_proofreading_result"] = {
            "accepted": accepted,
            "acceptance_reason": acceptance_reason,
            "guard_passed": guard_report.get("passed"),
            "violations": guard_report.get("violations", []),
        }
        if accepted:
            section_index["final_file"] = "final.md"
        save_json(section_dir / "index.json", section_index)

        return result

    def run_if_needed(self, section_id: str | None = None) -> dict[str, Any] | None:
        section_status = load_json(CURRENT_SECTION_STATUS_PATH, {})
        if not section_id:
            section_id = section_status.get("section_id")

        if not section_id:
            return None

        if not section_status.get("section_complete"):
            return None

        if section_status.get("section_proofreading_completed"):
            return None

        result = self.run(section_id=section_id)

        refreshed_status = load_json(CURRENT_SECTION_STATUS_PATH, {})
        refreshed_status["section_proofreading_completed"] = True
        refreshed_status["section_proofreading_auto_accepted"] = bool(result.get("accepted"))
        refreshed_status["section_proofreading_required"] = False
        refreshed_status["section_proofreading_acceptance_reason"] = result.get("acceptance_reason")
        refreshed_status["section_proofreading_guard_report"] = result.get("guard_report", {})
        save_json(CURRENT_SECTION_STATUS_PATH, refreshed_status)

        return result