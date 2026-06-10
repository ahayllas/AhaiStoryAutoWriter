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

    def ensure_section_plan(self, llm_client, metric_schema: dict) -> dict | None:
        status = self.get_or_create_active_section()
        if not status:
            return None

        current_plan = self._load_section_plan()
        active_section_id = str(status.get("section_id", "")).strip()
        planned_section_id = str(current_plan.get("section_id", "")).strip()

        if current_plan and planned_section_id == active_section_id:
            return current_plan

        # Pass metric_schema into SectionArchitect
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

        return "middle"

 

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
            
        