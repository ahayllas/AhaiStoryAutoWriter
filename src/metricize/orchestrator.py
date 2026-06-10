from __future__ import annotations

import copy
import datetime as dt
from typing import Any

from config import (
    DEFAULT_SEGMENT_WORDS,
    METRIC_SCHEMA_PATH,
    SECTION_INDEX_PATH,
    STORY_PLAN_METRIC_ANALYSIS_PATH,
    STORY_PLAN_PATH,
)
from io_contract import load_json, save_json
from story_planner import StoryPlanner
from .analyzer import MetricFlowAnalyzer
from .envelope_assigner import MetricEnvelopeAssigner
from .repair_planner import MetricRepairPlanner
from .schema_builder import MetricSchemaBuilder


class StoryPlanMetricizeOrchestrator:
    def __init__(self, llm_client=None) -> None:
        self.llm_client = llm_client

    def run(
        self,
        *,
        auto_schema: bool = False,
        use_ai_envelope: bool = False,
        repair: bool = False,
        apply_repair: bool = False,
        repair_top_n: int = 2,
        overwrite_schema: bool = False,
        skip_envelope: bool = False,
    ) -> dict[str, Any]:
        story_plan = load_json(STORY_PLAN_PATH, {})
        if not story_plan:
            raise RuntimeError("Missing story_plan.json")

        plan = copy.deepcopy(story_plan)

        schema_builder = MetricSchemaBuilder(self.llm_client)
        metric_schema = schema_builder.load_or_build(
            story_plan=plan,
            auto_schema=auto_schema,
            overwrite=overwrite_schema,
        )

        plan["metric_schema"] = metric_schema
        plan["metric_design_notes"] = [
            f"{name}: {m.get('description', '')}"
            for name, m in metric_schema.get("metrics", {}).items()
            if isinstance(m, dict)
        ]

        if not skip_envelope:
            envelope_assigner = MetricEnvelopeAssigner(self.llm_client)
            envelope_payload = envelope_assigner.assign(
                story_plan=plan,
                metric_schema=metric_schema,
                use_ai=use_ai_envelope,
            )
            envelope_assigner.apply_to_story_plan(
                story_plan=plan,
                envelope_payload=envelope_payload,
            )

        analyzer = MetricFlowAnalyzer()
        analysis = analyzer.analyze(
            story_plan=plan,
            metric_schema=metric_schema,
        )
        save_json(STORY_PLAN_METRIC_ANALYSIS_PATH, analysis)

        # Important: only compact summary goes back to story_plan
        plan["metric_analysis_summary"] = analyzer.compact_summary(analysis, top_n=5)

        if repair:
            repair_planner = MetricRepairPlanner(self.llm_client)
            repair_report = repair_planner.plan_repairs(
                story_plan=plan,
                metric_schema=metric_schema,
                metric_analysis=analysis,
                top_n=repair_top_n,
            )

            # Important: only compact repair summary goes into story_plan
            plan["metric_repair_summary"] = {
                "repair_needed": repair_report.get("repair_needed"),
                "repair_summary": repair_report.get("repair_summary"),
                "combined": repair_report.get("combined", {}),
            }

            if apply_repair:
                self.apply_combined_repair(
                    story_plan=plan,
                    combined=repair_report.get("combined", {}),
                )

        plan["metricized_at"] = dt.datetime.now(dt.timezone.utc).isoformat()

        save_json(STORY_PLAN_PATH, plan)
        save_json(SECTION_INDEX_PATH, plan.get("sections", []))

        # Keep schema path in sync in case schema is only embedded.
        save_json(METRIC_SCHEMA_PATH, metric_schema)

        return plan

    def apply_combined_repair(
        self,
        *,
        story_plan: dict[str, Any],
        combined: dict[str, Any],
    ) -> None:
        if not isinstance(combined, dict):
            return

        self.apply_section_event_patches(
            story_plan,
            combined.get("adjust_section_events", []),
        )
        self.apply_metric_envelope_patches(
            story_plan,
            combined.get("adjust_metric_envelopes", []),
        )

        inserted_records = self.apply_insert_section_patches(
            story_plan=story_plan,
            inserts=combined.get("insert_sections", []),
        )

        self.apply_bridge_patches(
            story_plan,
            combined.get("add_bridge_facts", []),
        )

        self.rebuild_bridges_around_insertions(
            story_plan=story_plan,
            inserted_records=inserted_records,
        )

        self.normalize_story_plan_after_structural_change(story_plan)

        # cleanup compact repair staging fields after real merge
        story_plan.pop("metric_repair_summary", None)
        story_plan.pop("pending_insert_sections", None)

    def apply_bridge_patches(
        self,
        story_plan: dict[str, Any],
        bridges: Any,
    ) -> None:
        if not isinstance(bridges, list):
            return

        existing = story_plan.setdefault("between_section_bridges", [])
        existing_ids = {
            b.get("bridge_id")
            for b in existing
            if isinstance(b, dict)
        }

        for bridge in bridges:
            if not isinstance(bridge, dict):
                continue

            bid = bridge.get("bridge_id")
            if bid and bid in existing_ids:
                continue

            existing.append(copy.deepcopy(bridge))
            if bid:
                existing_ids.add(bid)

    def apply_section_event_patches(
        self,
        story_plan: dict[str, Any],
        patches: Any,
    ) -> None:
        if not isinstance(patches, list):
            return

        section_by_id = {
            s.get("section_id"): s
            for s in story_plan.get("sections", [])
            if isinstance(s, dict)
        }

        for patch in patches:
            if not isinstance(patch, dict):
                continue

            sid = patch.get("section_id")
            section = section_by_id.get(sid)
            if not section:
                continue

            append_events = patch.get("append_mandatory_events", [])
            if isinstance(append_events, list):
                section.setdefault("mandatory_events", [])
                section["mandatory_events"].extend(str(x) for x in append_events)

            append_state_changes = patch.get("append_state_changes", [])
            if isinstance(append_state_changes, list):
                section.setdefault("state_changes", [])
                section["state_changes"].extend(str(x) for x in append_state_changes)

            notes = patch.get("repair_notes")
            if notes:
                section["metric_repair_notes"] = str(notes)

    def apply_metric_envelope_patches(
        self,
        story_plan: dict[str, Any],
        patches: Any,
    ) -> None:
        if not isinstance(patches, list):
            return

        section_by_id = {
            s.get("section_id"): s
            for s in story_plan.get("sections", [])
            if isinstance(s, dict)
        }

        for patch in patches:
            if not isinstance(patch, dict):
                continue

            sid = patch.get("section_id")
            section = section_by_id.get(sid)
            if not section:
                continue

            env = section.setdefault("metric_envelope", {})
            center = env.setdefault("metric_expected_center", {})

            center_patch = patch.get("metric_expected_center", {})
            if isinstance(center_patch, dict):
                for metric, value in center_patch.items():
                    center[metric] = max(0, min(100, self.safe_int(value, 50)))

    def apply_insert_section_patches(
        self,
        *,
        story_plan: dict[str, Any],
        inserts: Any,
    ) -> list[dict[str, str]]:
        if not isinstance(inserts, list) or not inserts:
            return []

        sections = story_plan.setdefault("sections", [])
        if not isinstance(sections, list) or not sections:
            return []

        inserted_records: list[dict[str, str]] = []
        last_inserted_after: dict[str, str] = {}

        for item in inserts:
            if not isinstance(item, dict):
                continue

            requested_after_id = str(item.get("insert_after_section_id") or "").strip()
            section = item.get("section")

            if not requested_after_id or not isinstance(section, dict):
                continue

            actual_after_id = last_inserted_after.get(requested_after_id, requested_after_id)
            insert_at = self.find_section_index(sections, actual_after_id)
            if insert_at is None:
                continue

            old_next_id = self.get_next_section_id(sections, actual_after_id)

            new_section = copy.deepcopy(section)
            requested_new_id = str(new_section.get("section_id") or f"sec_insert_{len(sections)+1}")
            actual_new_id = self.ensure_unique_section_id(sections, requested_new_id)
            new_section["section_id"] = actual_new_id

            sections.insert(insert_at + 1, new_section)

            inserted_records.append(
                {
                    "after_id": actual_after_id,
                    "inserted_id": actual_new_id,
                    "before_next_id": old_next_id or "",
                }
            )

            # if multiple inserts target the same original anchor, chain them
            last_inserted_after[requested_after_id] = actual_new_id

        return inserted_records

    def rebuild_bridges_around_insertions(
        self,
        *,
        story_plan: dict[str, Any],
        inserted_records: list[dict[str, str]],
    ) -> None:
        if not inserted_records:
            return

        bridges = story_plan.setdefault("between_section_bridges", [])
        if not isinstance(bridges, list):
            bridges = []
            story_plan["between_section_bridges"] = bridges

        for record in inserted_records:
            after_id = record.get("after_id")
            inserted_id = record.get("inserted_id")
            before_next_id = record.get("before_next_id")

            if not after_id or not inserted_id:
                continue

            if not before_next_id:
                # inserted at end; no original transition to split
                continue

            has_after_to_inserted = self.has_bridge_pair(
                bridges,
                from_id=after_id,
                to_id=inserted_id,
            )
            has_inserted_to_next = self.has_bridge_pair(
                bridges,
                from_id=inserted_id,
                to_id=before_next_id,
            )

            original_bridge = self.find_bridge(
                bridges,
                from_id=after_id,
                to_id=before_next_id,
            )

            if original_bridge is None:
                # no original bridge to split; only create skeletons if needed
                if not has_after_to_inserted:
                    bridges.append(
                        self.make_empty_bridge(
                            from_id=after_id,
                            to_id=inserted_id,
                        )
                    )
                if not has_inserted_to_next:
                    bridges.append(
                        self.make_empty_bridge(
                            from_id=inserted_id,
                            to_id=before_next_id,
                        )
                    )
                continue

            # Original A->B bridge should not survive if X is inserted between A and B
            self.remove_bridge_pair(
                bridges,
                from_id=after_id,
                to_id=before_next_id,
            )

            split_a_to_x, split_x_to_b = self.split_bridge_for_insert(
                original_bridge=original_bridge,
                inserted_section_id=inserted_id,
            )

            if not has_after_to_inserted:
                bridges.append(split_a_to_x)

            if not has_inserted_to_next:
                bridges.append(split_x_to_b)

    def split_bridge_for_insert(
        self,
        *,
        original_bridge: dict[str, Any],
        inserted_section_id: str,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        from_id = str(original_bridge.get("from_section_id") or "")
        to_id = str(original_bridge.get("to_section_id") or "")

        offscreen_events = original_bridge.get("offscreen_events", [])
        if not isinstance(offscreen_events, list):
            offscreen_events = []

        facts = original_bridge.get("facts_available_to_later_sections", [])
        if not isinstance(facts, list):
            facts = []

        first_events, second_events = self.split_list_half(offscreen_events)

        bridge_1 = {
            "bridge_id": f"bridge_{from_id}_{inserted_section_id}",
            "from_section_id": from_id,
            "to_section_id": inserted_section_id,
            "start_day": self.safe_int(original_bridge.get("start_day"), 0),
            "end_day": self.safe_int(original_bridge.get("end_day"), 0),
            "time_elapsed": str(original_bridge.get("time_elapsed") or ""),
            "offscreen_events": first_events if first_events else offscreen_events,
            "facts_available_to_later_sections": [],
            "should_be_written_as_segment": bool(original_bridge.get("should_be_written_as_segment", False)),
            "continuity_notes": self.join_notes(
                str(original_bridge.get("continuity_notes") or ""),
                f"Auto-split from original bridge {from_id}->{to_id} before inserted section {inserted_section_id}.",
            ),
        }

        bridge_2 = {
            "bridge_id": f"bridge_{inserted_section_id}_{to_id}",
            "from_section_id": inserted_section_id,
            "to_section_id": to_id,
            "start_day": self.safe_int(original_bridge.get("start_day"), 0),
            "end_day": self.safe_int(original_bridge.get("end_day"), 0),
            "time_elapsed": str(original_bridge.get("time_elapsed") or ""),
            "offscreen_events": second_events,
            "facts_available_to_later_sections": facts,
            "should_be_written_as_segment": bool(original_bridge.get("should_be_written_as_segment", False)),
            "continuity_notes": self.join_notes(
                str(original_bridge.get("continuity_notes") or ""),
                f"Auto-split from original bridge {from_id}->{to_id} after inserted section {inserted_section_id}.",
            ),
        }

        return bridge_1, bridge_2

    def normalize_story_plan_after_structural_change(
        self,
        story_plan: dict[str, Any],
    ) -> None:
        sections = story_plan.get("sections", [])
        if not isinstance(sections, list) or not sections:
            return

        planner = StoryPlanner(llm_client=None)

        # section time windows / ids
        planner.normalize_time_windows(sections)

        # recalc section segment allocation
        target_total_words = self.safe_int(story_plan.get("target_total_words"), 0)
        if target_total_words <= 0:
            target_total_words = len(sections) * DEFAULT_SEGMENT_WORDS

        planner.allocate_section_segments(
            sections=sections,
            target_total_words=target_total_words,
            default_segment_words=DEFAULT_SEGMENT_WORDS,
        )

        # normalize bridges against the new section layout
        planner.normalize_between_section_bridges(story_plan, sections)

        # refresh timeline
        first_start = self.safe_int(sections[0].get("time_window", {}).get("start_day"), 0)
        last_end = self.safe_int(sections[-1].get("time_window", {}).get("end_day"), first_start)

        timeline = story_plan.setdefault("timeline", {})
        if not isinstance(timeline, dict):
            timeline = {}
            story_plan["timeline"] = timeline

        timeline["time_unit"] = "day"
        timeline["overall_start_day"] = first_start
        timeline["overall_end_day"] = last_end
        timeline["overall_duration_summary"] = planner.describe_duration(first_start, last_end)

    def find_section_index(
        self,
        sections: list[dict[str, Any]],
        section_id: str,
    ) -> int | None:
        for i, section in enumerate(sections):
            if section.get("section_id") == section_id:
                return i
        return None

    def get_next_section_id(
        self,
        sections: list[dict[str, Any]],
        section_id: str,
    ) -> str | None:
        idx = self.find_section_index(sections, section_id)
        if idx is None:
            return None
        next_idx = idx + 1
        if next_idx >= len(sections):
            return None
        return sections[next_idx].get("section_id")

    def ensure_unique_section_id(
        self,
        sections: list[dict[str, Any]],
        base_id: str,
    ) -> str:
        existing = {
            s.get("section_id")
            for s in sections
            if isinstance(s, dict)
        }

        if base_id not in existing:
            return base_id

        idx = 2
        while f"{base_id}_{idx}" in existing:
            idx += 1
        return f"{base_id}_{idx}"

    def find_bridge(
        self,
        bridges: list[dict[str, Any]],
        *,
        from_id: str,
        to_id: str,
    ) -> dict[str, Any] | None:
        for bridge in bridges:
            if not isinstance(bridge, dict):
                continue
            if bridge.get("from_section_id") == from_id and bridge.get("to_section_id") == to_id:
                return copy.deepcopy(bridge)
        return None

    def has_bridge_pair(
        self,
        bridges: list[dict[str, Any]],
        *,
        from_id: str,
        to_id: str,
    ) -> bool:
        for bridge in bridges:
            if not isinstance(bridge, dict):
                continue
            if bridge.get("from_section_id") == from_id and bridge.get("to_section_id") == to_id:
                return True
        return False

    def remove_bridge_pair(
        self,
        bridges: list[dict[str, Any]],
        *,
        from_id: str,
        to_id: str,
    ) -> None:
        kept = []
        for bridge in bridges:
            if not isinstance(bridge, dict):
                kept.append(bridge)
                continue
            if bridge.get("from_section_id") == from_id and bridge.get("to_section_id") == to_id:
                continue
            kept.append(bridge)

        bridges[:] = kept

    def make_empty_bridge(
        self,
        *,
        from_id: str,
        to_id: str,
    ) -> dict[str, Any]:
        return {
            "bridge_id": f"bridge_{from_id}_{to_id}",
            "from_section_id": from_id,
            "to_section_id": to_id,
            "start_day": 0,
            "end_day": 0,
            "time_elapsed": "",
            "offscreen_events": [],
            "facts_available_to_later_sections": [],
            "should_be_written_as_segment": False,
            "continuity_notes": "Auto-generated bridge after section insertion.",
        }

    def split_list_half(self, items: list[Any]) -> tuple[list[Any], list[Any]]:
        if not items:
            return [], []
        mid = max(1, len(items) // 2)
        return items[:mid], items[mid:]

    def join_notes(self, left: str, right: str) -> str:
        left = (left or "").strip()
        right = (right or "").strip()
        if left and right:
            return f"{left} {right}"
        return left or right

    def safe_int(self, value: Any, default: int = 0) -> int:
        try:
            return int(value)
        except Exception:
            return default