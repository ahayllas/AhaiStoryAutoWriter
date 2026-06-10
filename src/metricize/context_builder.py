from __future__ import annotations

from typing import Any


class StoryPlanRepairContextBuilder:
    def build_transition_context(
        self,
        *,
        story_plan: dict[str, Any],
        from_section_id: str,
        to_section_id: str,
        include_neighbors: bool = True,
    ) -> dict[str, Any]:
        sections = story_plan.get("sections", [])
        section_ids = [s.get("section_id") for s in sections]

        focus_ids = {from_section_id, to_section_id}

        if include_neighbors:
            for sid in [from_section_id, to_section_id]:
                if sid in section_ids:
                    idx = section_ids.index(sid)
                    if idx - 1 >= 0:
                        focus_ids.add(section_ids[idx - 1])
                    if idx + 1 < len(section_ids):
                        focus_ids.add(section_ids[idx + 1])

        focused_sections = [
            self.clean_full_section(s)
            for s in sections
            if s.get("section_id") in focus_ids
        ]

        return {
            "global_context": self.global_context(story_plan),
            "all_section_summaries": self.all_section_summaries(story_plan),
            "focused_transition": {
                "from_section_id": from_section_id,
                "to_section_id": to_section_id,
            },
            "focused_sections_full": focused_sections,
            "relevant_bridges": self.relevant_bridges(
                story_plan,
                focus_ids=focus_ids,
                from_section_id=from_section_id,
                to_section_id=to_section_id,
            ),
        }

    def global_context(self, story_plan: dict[str, Any]) -> dict[str, Any]:
        return {
            "title": story_plan.get("title"),
            "premise": story_plan.get("premise"),
            "target_total_words": story_plan.get("target_total_words"),
            "genre": story_plan.get("genre"),
            "tone": story_plan.get("tone"),
            "setting": story_plan.get("setting"),
            "protagonist": story_plan.get("protagonist"),
            "core_conflict": story_plan.get("core_conflict"),
            "ending_overview": story_plan.get("ending_overview"),
            "global_constraints": story_plan.get("global_constraints"),
            "timeline": story_plan.get("timeline"),
        }

    def all_section_summaries(self, story_plan: dict[str, Any]) -> list[dict[str, Any]]:
        result = []

        for s in story_plan.get("sections", []):
            env = s.get("metric_envelope", {})
            center = env.get("metric_expected_center", {})

            result.append(
                {
                    "section_id": s.get("section_id"),
                    "title": s.get("title"),
                    "section_role": s.get("section_role"),
                    "time_window": s.get("time_window"),
                    "summary": s.get("summary"),
                    "desired_end_state": s.get("desired_end_state"),
                    "ending_trigger": s.get("ending_trigger"),
                    "metric_expected_center": center,
                }
            )

        return result

    def clean_full_section(self, section: dict[str, Any]) -> dict[str, Any]:
        """
        Keep enough for repair, remove noisy top-level generated analysis.
        """
        allowed_keys = [
            "section_id",
            "title",
            "section_role",
            "narrative_weight",
            "purpose",
            "entry_state",
            "time_window",
            "summary",
            "causality_from_previous",
            "protagonist_decision",
            "mandatory_events",
            "new_facts_established",
            "state_changes",
            "desired_end_state",
            "ending_trigger",
            "next_section_handoff",
            "planned_segments_min",
            "planned_segments_max",
            "metric_envelope",
        ]

        return {
            key: section.get(key)
            for key in allowed_keys
            if key in section
        }

    def relevant_bridges(
        self,
        story_plan: dict[str, Any],
        *,
        focus_ids: set[str],
        from_section_id: str,
        to_section_id: str,
    ) -> list[dict[str, Any]]:
        bridges = story_plan.get("between_section_bridges", [])
        result = []

        for b in bridges:
            if not isinstance(b, dict):
                continue

            pair_match = (
                b.get("from_section_id") == from_section_id
                and b.get("to_section_id") == to_section_id
            )

            near_match = (
                b.get("from_section_id") in focus_ids
                or b.get("to_section_id") in focus_ids
            )

            if pair_match or near_match:
                result.append(b)

        return result