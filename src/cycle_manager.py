from __future__ import annotations

from typing import Any

from config import CURRENT_SECTION_STATUS_PATH, PROJECT_META_PATH, PROJECT_STATUS_PATH
from io_contract import load_json, save_json
from queue_manager import QueueManager
from section_expander import SectionExpander
from section_planner import SectionPlanner
from situation_analyzer import SituationAnalyzer
from state_manager import StateManager
from segment_writer import SegmentWriter


class CycleManager:
    """
    Completion-first cycle manager with section-level planning.

    Core policy:
    - only one active section at a time
    - each section gets one section-wide execution plan
    - only one just-in-time segment at a time
    - segment expansion must follow section plan
    - section completion gates section advancement
    - final section completion ends the story
    """

    def __init__(
        self,
        queue_manager: QueueManager,
        section_expander: SectionExpander,
        situation_analyzer: SituationAnalyzer,
        state_manager: StateManager,
        writer: SegmentWriter,
    ) -> None:
        self.queue_manager = queue_manager
        self.section_expander = section_expander
        self.situation_analyzer = situation_analyzer
        self.state_manager = state_manager
        self.writer = writer
        self.section_planner = SectionPlanner()

    def run_cycle(self, metric_schema: dict[str, Any]) -> dict[str, Any]:
        project_meta = load_json(PROJECT_META_PATH, {})
        project_status = load_json(PROJECT_STATUS_PATH, {
            "completed": False,
            "story_completed": False,
        })

        if project_status.get("completed") or project_status.get("story_completed"):
            return {
                "status": "completed",
                "reason": "project already completed",
                "project_status": project_status,
            }

        active_section = self.section_planner.get_or_create_active_section()
        if not active_section:
            self._mark_project_completed(reason="no available sections")
            return {
                "status": "completed",
                "reason": "no available sections",
                "project_status": load_json(PROJECT_STATUS_PATH, {}),
            }

        section_plan = self.section_planner.ensure_section_plan(
            llm_client=self.section_expander.llm_client,
            metric_schema=metric_schema,
        )
        if not section_plan:
            return {
                "status": "idle",
                "reason": "failed to create section plan",
                "project_status": load_json(PROJECT_STATUS_PATH, {}),
            }

        queue_item = self._get_or_create_queue_item()
        if not queue_item:
            next_section = self.section_planner.advance_if_complete()
            if not next_section:
                self._mark_project_completed(reason="all sections completed")
                return {
                    "status": "completed",
                    "reason": "all sections completed",
                    "project_status": load_json(PROJECT_STATUS_PATH, {}),
                }

            section_plan = self.section_planner.ensure_section_plan(
                llm_client=self.section_expander.llm_client,
                metric_schema=metric_schema,
            )
            if not section_plan:
                return {
                    "status": "idle",
                    "reason": "failed to create next section plan",
                    "project_status": load_json(PROJECT_STATUS_PATH, {}),
                }

            queue_item = self._get_or_create_queue_item()
            if not queue_item:
                return {
                    "status": "idle",
                    "reason": "failed to create queue item",
                    "project_status": load_json(PROJECT_STATUS_PATH, {}),
                }

        segment_plan = self.section_expander.run(
            queue_item=queue_item,
            metric_schema=metric_schema,
        )

        situation_brief = self.situation_analyzer.run(metric_schema=metric_schema)
        write_result = self.writer.run()

        patch = self.state_manager.parse_state_update_text(write_result.get("state_update", ""))
        updated_state = self.state_manager.apply_patch(patch)

        self._complete_queue_item(queue_item, write_result)

        section_status = self.section_planner.mark_segment_result(
            segment_plan=segment_plan,
            state_update_patch=patch,
        )

        if section_status and section_status.get("section_complete"):
            next_section = self.section_planner.advance_if_complete()
            if next_section is None:
                self._mark_project_completed(reason="final section completed")

        current_words = self._safe_int(write_result.get("current_words"), default=0)
        target_total_words = self._safe_int(project_meta.get("target_total_words"), default=0)

        if (
            target_total_words > 0
            and current_words > int(target_total_words * 1.2)
            and not self.section_planner.is_story_complete()
        ):
            status = load_json(PROJECT_STATUS_PATH, {})
            status["completed"] = True
            status["story_completed"] = True
            status["completion_reason"] = "safety stop: exceeded 120% target words"
            save_json(PROJECT_STATUS_PATH, status)

        final_status = load_json(PROJECT_STATUS_PATH, {})
        return {
            "status": "completed" if final_status.get("completed") else "ok",
            "queue_item": queue_item,
            "segment_plan": segment_plan,
            "situation_brief": situation_brief,
            "write_result": write_result,
            "state_patch": patch,
            "updated_state": updated_state,
            "section_status": load_json(CURRENT_SECTION_STATUS_PATH, {}),
            "project_status": final_status,
        }

    def _get_or_create_queue_item(self) -> dict[str, Any] | None:
        active_item = self.queue_manager.get_active_item()
        if active_item:
            return active_item

        pending_item = self.queue_manager.get_next_pending_item()
        if pending_item:
            return self.queue_manager.activate_item(pending_item) or pending_item

        new_item = self.section_planner.build_next_queue_item()
        if not new_item:
            return None

        self.queue_manager.enqueue_item(new_item)
        return self.queue_manager.activate_item(new_item) or new_item

    def _complete_queue_item(self, queue_item: dict[str, Any], write_result: dict[str, Any]) -> None:
        if not queue_item:
            return

        completed = self.queue_manager.complete_active_item(write_result)
        if completed is not None:
            return

        self.queue_manager.mark_item_completed(queue_item, write_result)

    def _mark_project_completed(self, reason: str) -> None:
        project_status = load_json(PROJECT_STATUS_PATH, {})
        project_status["completed"] = True
        project_status["story_completed"] = True
        project_status["completion_reason"] = reason
        save_json(PROJECT_STATUS_PATH, project_status)

    def _safe_int(self, value: Any, default: int) -> int:
        try:
            return int(value)
        except Exception:
            return default