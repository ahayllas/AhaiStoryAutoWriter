from __future__ import annotations

import math
from dataclasses import asdict
from typing import Any

from config import (
    DEFAULT_SEGMENT_WORDS,
    MODEL_PLANNER,
    PLANNER_CONCEPT_SYSTEM_PATH,
    PLANNER_CONCEPT_USER_TEMPLATE_PATH,
    PLANNER_BIBLE_SYSTEM_PATH,
    PLANNER_BIBLE_USER_TEMPLATE_PATH,
    PLANNER_SECTIONS_SYSTEM_PATH,
    PLANNER_SECTIONS_USER_TEMPLATE_PATH,
    SECTION_DRAFT_PATH,
    SECTION_INDEX_PATH,
    SEGMENT_QUEUE_PATH,
    STORY_BIBLE_PATH,
    STORY_CONCEPT_PATH,
    STORY_PLAN_PATH,
)
from io_contract import load_text, save_json
from schemas import ProjectMeta
from utils import fill_template


class StoryPlanner:
    def __init__(self, llm_client) -> None:
        self.llm_client = llm_client

    def _generate_json_from_prompt(
        self,
        *,
        system_path,
        user_template_path,
        mapping: dict[str, Any],
    ) -> dict:
        system_prompt = load_text(system_path)
        user_template = load_text(user_template_path)
        user_prompt = fill_template(user_template, mapping)

        return self.llm_client.generate_json(
            model=MODEL_PLANNER,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
        )

    def run(self, meta: ProjectMeta, metric_schema: dict) -> dict:
        meta_dict = asdict(meta)

        concept = self.generate_concept(meta_dict)
        save_json(STORY_CONCEPT_PATH, concept)

        bible = self.generate_bible(meta_dict, concept)
        save_json(STORY_BIBLE_PATH, bible)

        section_draft = self.generate_sections(meta_dict, concept, bible)
        section_draft = self.normalize_section_draft(
            section_draft=section_draft,
            target_total_words=meta.target_total_words,
            default_segment_words=meta.default_segment_words or DEFAULT_SEGMENT_WORDS,
        )
        save_json(SECTION_DRAFT_PATH, section_draft)

        plan = self.assemble_story_plan(
            meta=meta_dict,
            concept=concept,
            bible=bible,
            section_draft=section_draft,
        )

        save_json(STORY_PLAN_PATH, plan)
        save_json(SECTION_INDEX_PATH, plan.get("sections", []))

        # segment_queue is now intentionally empty.
        # Current runtime derives queue items from active section plans.
        save_json(SEGMENT_QUEUE_PATH, {"items": []})

        return plan

    def generate_concept(self, meta_dict: dict) -> dict:
        return self._generate_json_from_prompt(
            system_path=PLANNER_CONCEPT_SYSTEM_PATH,
            user_template_path=PLANNER_CONCEPT_USER_TEMPLATE_PATH,
            mapping={
                "PROJECT_META_JSON": meta_dict,
            },
        )

    def generate_bible(self, meta_dict: dict, concept: dict) -> dict:
        return self._generate_json_from_prompt(
            system_path=PLANNER_BIBLE_SYSTEM_PATH,
            user_template_path=PLANNER_BIBLE_USER_TEMPLATE_PATH,
            mapping={
                "PROJECT_META_JSON": meta_dict,
                "STORY_CONCEPT_JSON": concept,
            },
        )

    def generate_sections(self, meta_dict: dict, concept: dict, bible: dict) -> dict:
        return self._generate_json_from_prompt(
            system_path=PLANNER_SECTIONS_SYSTEM_PATH,
            user_template_path=PLANNER_SECTIONS_USER_TEMPLATE_PATH,
            mapping={
                "PROJECT_META_JSON": meta_dict,
                "STORY_CONCEPT_JSON": concept,
                "STORY_BIBLE_JSON": bible,
            },
        )

    def normalize_section_draft(
        self,
        *,
        section_draft: dict,
        target_total_words: int,
        default_segment_words: int,
    ) -> dict:
        sections = section_draft.get("sections", [])
        if not isinstance(sections, list):
            sections = []
            section_draft["sections"] = sections

        self.normalize_section_ids(sections)
        self.normalize_time_windows(sections)
        self.allocate_section_segments(
            sections=sections,
            target_total_words=target_total_words,
            default_segment_words=default_segment_words,
        )
        self.normalize_between_section_bridges(section_draft, sections)

        return section_draft

    def normalize_section_ids(self, sections: list[dict]) -> None:
        for idx, section in enumerate(sections, start=1):
            section["section_id"] = f"sec_{idx:02d}"

    def normalize_time_windows(self, sections: list[dict]) -> None:
        previous_end_day = 0

        for idx, section in enumerate(sections):
            tw = section.get("time_window")
            if not isinstance(tw, dict):
                tw = {}

            start_day = self.safe_int(tw.get("start_day"), previous_end_day)
            end_day = self.safe_int(tw.get("end_day"), start_day)

            if idx == 0:
                start_day = min(start_day, 0)
                if start_day < 0:
                    start_day = 0

            if start_day < previous_end_day:
                start_day = previous_end_day

            if end_day < start_day:
                end_day = start_day

            tw["start_day"] = start_day
            tw["end_day"] = end_day
            tw.setdefault("label", f"Story Day {start_day} to Day {end_day}")
            tw.setdefault("duration_summary", self.describe_duration(start_day, end_day))

            if idx == 0:
                tw.setdefault("time_skip_from_previous", "None, this is the story opening.")
            else:
                gap = start_day - previous_end_day
                if gap <= 0:
                    tw.setdefault("time_skip_from_previous", "No significant time jump, continues directly from the previous section.")
                elif gap == 1:
                    tw.setdefault("time_skip_from_previous", "Approximately one day since the end of the previous section.")
                else:
                    tw.setdefault("time_skip_from_previous", f"Approximately {gap} days since the end of the previous section.")

            tw.setdefault(
                "time_continuity_notes",
                "Downstream generation must respect this section's relative day range. Specific times within the same day may be handled according to scene needs.",
            )

            section["time_window"] = tw
            previous_end_day = end_day

    def normalize_between_section_bridges(self, section_draft: dict, sections: list[dict]) -> None:
        bridges = section_draft.get("between_section_bridges", [])
        if not isinstance(bridges, list):
            bridges = []

        section_by_id = {s.get("section_id"): s for s in sections}
        normalized = []

        for idx, bridge in enumerate(bridges, start=1):
            if not isinstance(bridge, dict):
                continue

            from_id = bridge.get("from_section_id")
            to_id = bridge.get("to_section_id")

            if from_id not in section_by_id or to_id not in section_by_id:
                continue

            from_tw = section_by_id[from_id].get("time_window", {})
            to_tw = section_by_id[to_id].get("time_window", {})

            from_end = self.safe_int(from_tw.get("end_day"), 0)
            to_start = self.safe_int(to_tw.get("start_day"), from_end)

            start_day = self.safe_int(bridge.get("start_day"), from_end)
            end_day = self.safe_int(bridge.get("end_day"), to_start)

            if start_day < from_end:
                start_day = from_end
            if end_day > to_start:
                end_day = to_start
            if end_day < start_day:
                end_day = start_day

            bridge["bridge_id"] = bridge.get("bridge_id") or f"bridge_{from_id}_{to_id}"
            bridge["start_day"] = start_day
            bridge["end_day"] = end_day
            bridge.setdefault("time_elapsed", self.describe_duration(start_day, end_day))
            bridge.setdefault("offscreen_events", [])
            bridge.setdefault("facts_available_to_later_sections", [])
            bridge.setdefault("should_be_written_as_segment", False)
            bridge.setdefault(
                "continuity_notes",
                "These events occur between two sections and may be referenced in later sections through brief recap, dialogue, or status changes.",
            )
            normalized.append(bridge)

        section_draft["between_section_bridges"] = normalized

    def allocate_section_segments(
        self,
        *,
        sections: list[dict],
        target_total_words: int,
        default_segment_words: int,
    ) -> None:
        if not sections:
            return

        total_segments = max(1, math.ceil(target_total_words / max(default_segment_words, 1)))

        weights = []
        for idx, section in enumerate(sections):
            raw_weight = section.get("narrative_weight")
            try:
                weight = float(raw_weight)
            except Exception:
                weight = self.default_section_weight(idx, len(sections))
            weights.append(max(0.5, weight))

        weight_sum = sum(weights) or 1.0

        mins = []
        remainders = []

        for idx, weight in enumerate(weights):
            exact = total_segments * weight / weight_sum
            base = max(1, int(math.floor(exact)))
            mins.append(base)
            remainders.append((exact - base, idx))

        current_total = sum(mins)

        if current_total < total_segments:
            deficit = total_segments - current_total
            for _, idx in sorted(remainders, reverse=True)[:deficit]:
                mins[idx] += 1
        elif current_total > total_segments:
            surplus = current_total - total_segments
            for _, idx in sorted(remainders):
                if surplus <= 0:
                    break
                if mins[idx] > 1:
                    mins[idx] -= 1
                    surplus -= 1

        for idx, section in enumerate(sections):
            section["planned_segments_min"] = mins[idx]
            section["planned_segments_max"] = max(
                mins[idx] + 1,
                self.safe_int(section.get("planned_segments_max"), mins[idx] + 1),
            )

    def default_section_weight(self, idx: int, total: int) -> float:
        if total <= 1:
            return 1.0

        ratio = idx / max(total - 1, 1)

        if ratio < 0.15:
            return 0.9
        if ratio < 0.35:
            return 1.0
        if ratio < 0.65:
            return 1.2
        if ratio < 0.85:
            return 1.3
        return 1.1

    def assemble_story_plan(
        self,
        *,
        meta: dict,
        concept: dict,
        bible: dict,
        section_draft: dict,
    ) -> dict:
        sections = section_draft.get("sections", [])

        plan = {
            "title": bible.get("title") or concept.get("working_title") or meta.get("title"),
            "premise": bible.get("premise") or meta.get("premise"),
            "target_total_words": meta.get("target_total_words"),
            "genre": bible.get("genre") or concept.get("genre") or "",
            "tone": bible.get("tone") or concept.get("tone") or "",
            "setting": bible.get("setting", {}),
            "protagonist": bible.get("protagonist", {}),
            "core_conflict": bible.get("core_conflict", {}),
            "ending_overview": bible.get("ending_overview", {}),
            "sections": sections,

            # Additional planner-v2 fields.
            "story_concept": concept,
            "major_characters": bible.get("major_characters", []),
            "story_spine": bible.get("story_spine", concept.get("story_spine", [])),
            "global_constraints": bible.get("global_constraints", {}),
            "timeline": section_draft.get("timeline", {}),
            "between_section_bridges": section_draft.get("between_section_bridges", []),

            # Runtime currently no longer depends on planner-seeded queue.
            "segment_queue": [],
        }

        return plan

    def describe_duration(self, start_day: int, end_day: int) -> str:
        if end_day <= start_day:
            return "Within the same day"
        days = end_day - start_day
        if days == 1:
            return "Approximately one day"
        return f"Approximately {days} days"

    def safe_int(self, value: Any, default: int = 0) -> int:
        try:
            return int(value)
        except Exception:
            return default
