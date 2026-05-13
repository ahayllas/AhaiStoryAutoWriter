from __future__ import annotations

from typing import Any

from config import (
    CURRENT_SECTION_PLAN_PATH,
    CURRENT_SECTION_STATUS_PATH,
    PROJECT_STATUS_PATH,
    STORY_PLAN_PATH,
)
from io_contract import load_json, save_json
from section_architect import SectionArchitect


class SectionPlanner:
    """
    Completion-first section runtime controller.

    Stopgap patch goals:
    - do NOT treat segment_plan declarations as proof of completion
    - determine beat completion primarily from state_update_patch
    - make final section completion stricter
    - reduce accidental early story ending
    """

    def __init__(self) -> None:
        pass

    # -------------------------------------------------------------------------
    # Public API
    # -------------------------------------------------------------------------

    def get_or_create_active_section(self) -> dict[str, Any] | None:
        story_plan = self._load_story_plan()
        sections = self._get_sections(story_plan)
        if not sections:
            return None

        current_status = self._load_section_status()
        if current_status and current_status.get("status") == "active":
            return current_status

        completed_ids = set(self._get_completed_section_ids())
        for index, section in enumerate(sections):
            section_id = str(section.get("section_id", "")).strip()
            if not section_id or section_id in completed_ids:
                continue
            status = self._init_section_status(
                section=section,
                section_index=index,
                total_sections=len(sections),
            )
            self._save_section_status(status)
            self._clear_section_plan_if_mismatch(section_id)
            self._touch_project_status_for_section(status)
            return status

        return None

    def ensure_section_plan(self, llm_client, metric_schema: dict[str, Any]) -> dict[str, Any] | None:
        """
        Ensure current active section has a matching section plan.
        Regenerate if missing or mismatched section_id.
        """
        status = self.get_or_create_active_section()
        if not status:
            return None

        current_plan = self._load_section_plan()
        active_section_id = str(status.get("section_id", "")).strip()
        planned_section_id = str(current_plan.get("section_id", "")).strip()

        if current_plan and planned_section_id == active_section_id:
            return current_plan

        architect = SectionArchitect(llm_client)
        return architect.run(metric_schema=metric_schema)

    def build_next_queue_item(self) -> dict[str, Any] | None:
        status = self.get_or_create_active_section()
        if not status:
            return None

        if status.get("section_complete"):
            status = self.advance_if_complete()
            if not status:
                return None

        section_id = status["section_id"]
        next_ordinal = int(status.get("segment_count", 0)) + 1
        phase = self._infer_section_phase(status, next_ordinal)

        desired_end_state = str(status.get("desired_end_state", "")).strip()

        queue_item = {
            "segment_id": f"seg_{section_id}_{next_ordinal:02d}",
            "section_id": section_id,
            "status": "pending",
            "title": f"{status.get('title', section_id)} / Segment {next_ordinal}",
            "section_step": next_ordinal,
            "section_phase": phase,
            "section_goal": str(status.get("purpose", "")).strip(),
            "desired_end_state": desired_end_state,
            "is_final_section": bool(status.get("is_final_section", False)),
            "end_condition_hint": str(status.get("ending_trigger", "")).strip(),
            "next_section_handoff": str(status.get("next_section_handoff", "")).strip(),
        }
        return queue_item


    def is_section_complete(self, section_status: dict[str, Any]) -> bool:
        current_plan = self._load_section_plan()
        blueprints = current_plan.get("segment_blueprints", []) if current_plan else []
        total_blueprints = len(blueprints)

        segment_count = int(section_status.get("segment_count", 0))

        # 只要走完所有 blueprint 就完成
        return segment_count >= total_blueprints


    def mark_segment_result(
        self,
        segment_plan: dict[str, Any] | None = None,
        state_update_patch: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:

        status = self._load_section_status()
        if not status or status.get("status") != "active":
            return None

        status["segment_count"] = int(status.get("segment_count", 0)) + 1

        # 移除原本的 beat 相關邏輯
        status["section_complete"] = self.is_section_complete(status)

        if status["section_complete"]:
            status["status"] = "complete"
            self._mark_section_completed(status["section_id"])

        self._save_section_status(status)
        self._touch_project_status_for_section(status)
        return status

    def advance_if_complete(self) -> dict[str, Any] | None:
        current_status = self._load_section_status()
        if current_status and not current_status.get("section_complete", False):
            return current_status

        story_plan = self._load_story_plan()
        sections = self._get_sections(story_plan)
        completed_ids = set(self._get_completed_section_ids())

        for index, section in enumerate(sections):
            section_id = str(section.get("section_id", "")).strip()
            if not section_id or section_id in completed_ids:
                continue
            status = self._init_section_status(
                section=section,
                section_index=index,
                total_sections=len(sections),
            )
            self._save_section_status(status)
            self._clear_section_plan_if_mismatch(section_id)
            self._touch_project_status_for_section(status)
            return status

        self._mark_story_completed()
        return None

    def is_story_complete(self) -> bool:
        project_status = self._load_project_status()
        return bool(project_status.get("completed", False) or project_status.get("story_completed", False))

    # -------------------------------------------------------------------------
    # Internal helpers
    # -------------------------------------------------------------------------

    def _load_story_plan(self) -> dict[str, Any]:
        return load_json(STORY_PLAN_PATH, {})

    def _get_sections(self, story_plan: dict[str, Any]) -> list[dict[str, Any]]:
        sections = story_plan.get("sections")
        return sections if isinstance(sections, list) else []

    def _load_section_status(self) -> dict[str, Any]:
        return load_json(CURRENT_SECTION_STATUS_PATH, {})

    def _save_section_status(self, status: dict[str, Any]) -> None:
        save_json(CURRENT_SECTION_STATUS_PATH, status)

    def _load_section_plan(self) -> dict[str, Any]:
        return load_json(CURRENT_SECTION_PLAN_PATH, {})

    def _clear_section_plan_if_mismatch(self, active_section_id: str) -> None:
        current_plan = self._load_section_plan()
        planned_section_id = str(current_plan.get("section_id", "")).strip()
        if not current_plan:
            return
        if planned_section_id != str(active_section_id).strip():
            save_json(CURRENT_SECTION_PLAN_PATH, {})

    def _load_project_status(self) -> dict[str, Any]:
        return load_json(PROJECT_STATUS_PATH, {
            "completed": False,
            "story_completed": False,
            "completed_section_ids": [],
        })

    def _save_project_status(self, status: dict[str, Any]) -> None:
        save_json(PROJECT_STATUS_PATH, status)

    def _get_completed_section_ids(self) -> list[str]:
        status = self._load_project_status()
        value = status.get("completed_section_ids", [])
        if isinstance(value, list):
            return [str(x) for x in value if str(x).strip()]
        return []

    def _mark_section_completed(self, section_id: str) -> None:
        status = self._load_project_status()
        completed = status.get("completed_section_ids", [])
        if not isinstance(completed, list):
            completed = []

        if section_id not in completed:
            completed.append(section_id)

        status["completed_section_ids"] = completed
        self._save_project_status(status)

    def _mark_story_completed(self) -> None:
        status = self._load_project_status()
        status["completed"] = True
        status["story_completed"] = True
        self._save_project_status(status)

    def _touch_project_status_for_section(self, section_status: dict[str, Any]) -> None:
        status = self._load_project_status()
        status["current_section_id"] = section_status.get("section_id", "")
        status["current_section_index"] = section_status.get("section_index", -1)
        status["current_section_title"] = section_status.get("title", "")
        status.setdefault("completed", False)
        status.setdefault("story_completed", False)
        status.setdefault("completed_section_ids", [])
        self._save_project_status(status)

    def _init_section_status(
        self,
        section: dict[str, Any],
        section_index: int,
        total_sections: int,
    ) -> dict[str, Any]:
        section_id = str(section.get("section_id", f"sec_{section_index + 1:02d}")).strip()
        title = str(section.get("title", section_id)).strip()


        planned_min = self._safe_int(
            section.get("planned_segments_min"),
            default=1,
        )

        planned_max = self._safe_int(
            section.get("planned_segments_max"),
            default=self._safe_int(section.get("planned_segments"), default=max(planned_min, 3)),
        )

        if planned_max < planned_min:
            planned_max = planned_min


        status = {
            "section_id": section_id,
            "section_index": section_index,
            "title": title,
            "purpose": str(section.get("purpose", "")).strip(),
            "summary": str(section.get("summary", "")).strip(),
            "status": "active",
            "segment_count": 0,
            "planned_segments_min": planned_min,
            "planned_segments_max": planned_max,
            "desired_end_state": str(
                section.get("desired_end_state")
                or section.get("ending_state")
                or section.get("summary")
                or ""
            ).strip(),
            "ending_trigger": str(section.get("ending_trigger", "")).strip(),
            "next_section_handoff": str(section.get("next_section_handoff", "")).strip(),
            "section_complete": False,
            "is_final_section": section_index == (total_sections - 1),
            "latest_state_patch": {},
            "latest_segment_completion_signals": {},
        }
        return status

    def _infer_section_phase(self, status: dict[str, Any], next_ordinal: int) -> str:
        planned_min = max(1, int(status.get("planned_segments_min", 1)))
        planned_max = max(planned_min, int(status.get("planned_segments_max", planned_min)))

        if next_ordinal <= 1:
            return "opening"

        if next_ordinal >= planned_max:
            return "closing"

        if next_ordinal >= planned_min and not status.get("pending_beats", []):
            return "closing"

        return "middle"

    # -------------------------------------------------------------------------
    # Stopgap completion detection
    # -------------------------------------------------------------------------

    def _detect_completed_beats(
        self,
        must_hit_beats: list[str],
        target_blueprint: dict[str, Any],
        segment_plan: dict[str, Any],
        state_update_patch: dict[str, Any],
    ) -> list[str]:
        """
        Formal-but-small-change version:
        - prioritize blueprint-assigned mandatory events
        - require patch evidence
        - do NOT trust segment_plan declarations alone
        """
        evidence_texts = self._collect_patch_evidence_texts(state_update_patch)

        blueprint_primary = str(target_blueprint.get("primary_beat", "")).strip()
        blueprint_expected_end = str(target_blueprint.get("expected_end_state", "")).strip()

        assigned_events = target_blueprint.get("mandatory_events_assigned", [])
        if not isinstance(assigned_events, list):
            assigned_events = []

        assigned_events = self._normalize_text_list(assigned_events)

        plan_required_beats = self._normalize_text_list(segment_plan.get("required_beats", []))
        plan_must_include = self._normalize_text_list(segment_plan.get("must_include", []))

        newly_hit: list[str] = []

        for beat in must_hit_beats:
            score = 0

            # A. If beat is explicitly assigned to this blueprint, raise confidence
            if self._text_matches_any(beat, assigned_events):
                score += 3

            # B. If beat aligns with blueprint primary beat, slight boost
            if blueprint_primary and self._texts_match(beat, blueprint_primary):
                score += 1

            # C. If segment plan still includes it, tiny boost only (not proof)
            if self._text_matches_any(beat, plan_required_beats):
                score += 1
            if self._text_matches_any(beat, plan_must_include):
                score += 1

            # D. Real completion evidence from patch is mandatory
            patch_evidence_ok = self._beat_has_evidence(beat, evidence_texts)

            # Strong completion:
            # assigned + patch evidence
            if score >= 3 and patch_evidence_ok:
                newly_hit.append(beat)
                continue

            # Fallback completion:
            # enough total alignment + patch evidence
            if score >= 2 and patch_evidence_ok:
                newly_hit.append(beat)
                continue

            # Last fallback:
            # direct patch evidence against expected end state
            if patch_evidence_ok and blueprint_expected_end and self._texts_match(beat, blueprint_expected_end):
                newly_hit.append(beat)
                continue

        return newly_hit

    def _collect_patch_evidence_texts(self, patch: dict[str, Any]) -> list[str]:
        if not isinstance(patch, dict):
            return []

        texts: list[str] = []

        for key in [
            "known_facts_add",
            "recent_consequences_add",
            "active_threads_resolved",
            "unresolved_questions_resolved",
        ]:
            value = patch.get(key, [])
            if isinstance(value, list):
                for item in value:
                    text = str(item).strip()
                    if text:
                        texts.append(text)

        return texts

    def _beat_has_evidence(self, beat: str, evidence_texts: list[str]) -> bool:
        beat = str(beat).strip()
        if not beat:
            return False

        beat_key = self._normalize_for_match(beat)
        if not beat_key:
            return False

        beat_parts = self._extract_meaningful_parts(beat)
        if not beat_parts:
            return False

        for evidence in evidence_texts:
            evidence = str(evidence).strip()
            if not evidence:
                continue

            evidence_key = self._normalize_for_match(evidence)

            # Strong direct containment
            if beat_key in evidence_key or evidence_key in beat_key:
                return True

            # Conservative parts overlap
            matched_parts = 0
            for part in beat_parts:
                part_key = self._normalize_for_match(part)
                if part_key and part_key in evidence_key:
                    matched_parts += 1

            # For longer compound Chinese beat descriptions, require >= 2 parts.
            if len(beat_parts) >= 2 and matched_parts >= 2:
                return True

            # For short/simple beats, require full-or-near-full mention.
            if len(beat_parts) == 1 and matched_parts >= 1 and len(beat_key) <= 8:
                return True

        return False

    def _normalize_for_match(self, text: Any) -> str:
        text = str(text).strip().lower()
        if not text:
            return ""

        replace_chars = [
            "，", "。", "、", "：", "；", "！", "？",
            ",", ".", ":", ";", "!", "?", "（", "）",
            "(", ")", "「", "」", "『", "』", "\"", "'",
            "　", " ",
        ]

        for ch in replace_chars:
            text = text.replace(ch, "")

        return text

    def _extract_meaningful_parts(self, text: str) -> list[str]:
        """
        Rough heuristic splitter for Chinese descriptive beats.
        We intentionally keep this simple and conservative.
        """
        text = str(text).strip()
        if not text:
            return []

        seps = ["，", "。", "、", "與", "及", "並", "後", "後，", "然後", "而", "在", "的"]
        parts = [text]

        for sep in seps:
            new_parts: list[str] = []
            for p in parts:
                if sep in p:
                    new_parts.extend([x.strip() for x in p.split(sep) if x.strip()])
                else:
                    new_parts.append(p)
            parts = new_parts

        cleaned: list[str] = []
        for p in parts:
            p = p.strip()
            if len(self._normalize_for_match(p)) >= 2 and p not in cleaned:
                cleaned.append(p)

        # Avoid exploding into too many tiny pieces.
        if len(cleaned) > 5:
            return cleaned[:5]

        return cleaned

    def _has_strong_ending_signal(self, section_status: dict[str, Any]) -> bool:
        """
        Stronger and safer than the old _has_ending_signal():
        - do NOT treat any resolved thread as enough
        - require evidence close to ending_trigger or desired_end_state
        - or explicit completion-like phrases in patch evidence
        """
        patch = section_status.get("latest_state_patch", {})
        evidence_texts = self._collect_patch_evidence_texts(patch)

        ending_trigger = str(section_status.get("ending_trigger", "")).strip()
        desired_end_state = str(section_status.get("desired_end_state", "")).strip()

        ending_trigger_key = self._normalize_for_match(ending_trigger)
        desired_end_state_key = self._normalize_for_match(desired_end_state)

        explicit_end_markers = [
            "故事完結",
            "故事結束",
            "正式在一起",
            "牽手離開",
            "告白成功",
            "演出結束後正式確認心意",
            "圓滿收束",
            "最終和解",
            "最終告白",
        ]
        explicit_end_marker_keys = [self._normalize_for_match(x) for x in explicit_end_markers]

        for evidence in evidence_texts:
            evidence_key = self._normalize_for_match(evidence)
            if not evidence_key:
                continue

            if ending_trigger_key and ending_trigger_key in evidence_key:
                return True

            if desired_end_state_key and desired_end_state_key in evidence_key:
                return True

            for marker_key in explicit_end_marker_keys:
                if marker_key and marker_key in evidence_key:
                    return True

        # Partial semantic overlap with ending trigger, but stricter than before.
        trigger_parts = self._extract_meaningful_parts(ending_trigger)
        if len(trigger_parts) >= 2:
            for evidence in evidence_texts:
                evidence_key = self._normalize_for_match(evidence)
                matched = 0
                for part in trigger_parts:
                    part_key = self._normalize_for_match(part)
                    if part_key and part_key in evidence_key:
                        matched += 1
                if matched >= 2:
                    return True

        return False

    def _normalize_text_list(self, values: Any) -> list[str]:
        if not isinstance(values, list):
            return []
        result: list[str] = []
        for value in values:
            text = str(value).strip()
            if text and text not in result:
                result.append(text)
        return result

    def _safe_int(self, value: Any, default: int) -> int:
        try:
            return int(value)
        except Exception:
            return default
            
    def _resolve_target_blueprint(
        self,
        section_plan: dict[str, Any],
        section_status: dict[str, Any],
        segment_plan: dict[str, Any],
    ) -> dict[str, Any]:
        if not isinstance(section_plan, dict):
            return {}

        blueprints = section_plan.get("segment_blueprints", [])
        if not isinstance(blueprints, list) or not blueprints:
            return {}

        segment_id = str(segment_plan.get("segment_id", "")).strip()
        section_step = segment_plan.get("section_step")
        inferred_step = int(section_status.get("segment_count", 0))

        # 1) exact segment_id match
        if segment_id:
            for bp in blueprints:
                if str(bp.get("segment_id", "")).strip() == segment_id:
                    return bp

        # 2) section_step / ordinal match
        candidate_steps = []
        for raw in [section_step, inferred_step]:
            try:
                candidate_steps.append(int(raw))
            except Exception:
                pass

        for step in candidate_steps:
            for bp in blueprints:
                for key in ["section_step", "segment_index", "ordinal", "step"]:
                    try:
                        if int(bp.get(key)) == step:
                            return bp
                    except Exception:
                        continue

        # 3) fallback by array position
        try:
            idx = max(0, inferred_step - 1)
            if idx < len(blueprints):
                return blueprints[idx]
        except Exception:
            pass

        return {}
        
    def _texts_match(self, a: str, b: str) -> bool:
        a_key = self._normalize_for_match(a)
        b_key = self._normalize_for_match(b)
        if not a_key or not b_key:
            return False

        if a_key in b_key or b_key in a_key:
            return True

        a_parts = self._extract_meaningful_parts(a)
        b_key_full = self._normalize_for_match(b)

        matched = 0
        for part in a_parts:
            part_key = self._normalize_for_match(part)
            if part_key and part_key in b_key_full:
                matched += 1

        return matched >= 2 if len(a_parts) >= 2 else matched >= 1


    def _text_matches_any(self, text: str, candidates: list[str]) -> bool:
        for candidate in candidates:
            if self._texts_match(text, candidate):
                return True
        return False