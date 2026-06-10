from __future__ import annotations

import math
import random
from pathlib import Path

from dataclasses import asdict
from typing import Any

from config import (
    DEFAULT_SEGMENT_WORDS,
    MODEL_PLANNER,
    MODEL_CREATIVE,
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
    CREATIVE_WORDS_PATH,
    CREATIVE_WORD_SELECTOR_SYSTEM_PATH,
    CREATIVE_WORD_SELECTOR_USER_TEMPLATE_PATH,
    CREATIVE_SITUATION_SYSTEM_PATH,
    CREATIVE_SITUATION_USER_TEMPLATE_PATH,
    CREATIVE_PACKET_PATH,
    DEFAULT_CREATIVE_RANDOM_POOL_SIZE,
    DEFAULT_CREATIVE_SELECTED_WORDS,
    DEFAULT_CREATIVE_SITUATION_COUNT,
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
        
    def _generate_json_from_prompt_creativeModel(
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
            model=MODEL_CREATIVE,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
        )    
        

    def run(self, meta: ProjectMeta, metric_schema: dict) -> dict:
        meta_dict = asdict(meta)

        creative_packet = self.build_creative_packet(meta_dict)
        save_json(CREATIVE_PACKET_PATH, creative_packet)

        concept = self.generate_concept(meta_dict, creative_packet)
        save_json(STORY_CONCEPT_PATH, concept)

        bible = self.generate_bible(meta_dict, concept, creative_packet)
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

    def generate_concept(self, meta_dict: dict, creative_packet: dict) -> dict:
        return self._generate_json_from_prompt(
            system_path=PLANNER_CONCEPT_SYSTEM_PATH,
            user_template_path=PLANNER_CONCEPT_USER_TEMPLATE_PATH,
            mapping={
                "PROJECT_META_JSON": meta_dict,
                "CREATIVE_PACKET_JSON": creative_packet,
            },
        )
        
    def generate_bible(self, meta_dict: dict, concept: dict, creative_packet: dict) -> dict:
        return self._generate_json_from_prompt(
            system_path=PLANNER_BIBLE_SYSTEM_PATH,
            user_template_path=PLANNER_BIBLE_USER_TEMPLATE_PATH,
            mapping={
                "PROJECT_META_JSON": meta_dict,
                "STORY_CONCEPT_JSON": concept,
                "CREATIVE_PACKET_JSON": creative_packet,
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
            
            
    def build_creative_packet(self, meta_dict: dict) -> dict:
        random_pool = self.sample_random_words(
            word_file=CREATIVE_WORDS_PATH,
            sample_size=DEFAULT_CREATIVE_RANDOM_POOL_SIZE,
        )

        if not random_pool:
            return {
                "enabled": False,
                "random_words_pool": [],
                "selected_words": [],
                "selection_rationale": [],
                "everyday_situations": [],
                "usage_note": "Creative divergence disabled because no word list could be loaded.",
            }

        deduped_selected = []
        # keep only words from the random pool
        pool_set = {w.strip() for w in random_pool}
        
        if DEFAULT_CREATIVE_RANDOM_POOL_SIZE > DEFAULT_CREATIVE_SELECTED_WORDS :
            selected_payload = self._generate_json_from_prompt_creativeModel(
                system_path=CREATIVE_WORD_SELECTOR_SYSTEM_PATH,
                user_template_path=CREATIVE_WORD_SELECTOR_USER_TEMPLATE_PATH,
                mapping={
                    "PROJECT_META_JSON": meta_dict,
                    "RANDOM_WORD_POOL_JSON": random_pool,
                    "SELECT_COUNT": DEFAULT_CREATIVE_SELECTED_WORDS,
                },
            )

            selected_words = selected_payload.get("selected_words", [])
            if not isinstance(selected_words, list):
                selected_words = []

            selected_words = [
                str(x).strip() for x in selected_words
                if isinstance(x, str) and str(x).strip()
            ]

            seen = set()
            for word in selected_words:
                if word in pool_set and word not in seen:
                    deduped_selected.append(word)
                    seen.add(word)

            if len(deduped_selected) > DEFAULT_CREATIVE_SELECTED_WORDS:
                deduped_selected = deduped_selected[:DEFAULT_CREATIVE_SELECTED_WORDS]
                
            if len(deduped_selected) < DEFAULT_CREATIVE_SELECTED_WORDS:
                for word in random_pool:
                    if word not in seen:
                        deduped_selected.append(word)
                        seen.add(word)
                    if len(deduped_selected) >= DEFAULT_CREATIVE_SELECTED_WORDS:
                        break
        else :
            deduped_selected.extend(pool_set)


        situation_payload = self._generate_json_from_prompt_creativeModel(
            system_path=CREATIVE_SITUATION_SYSTEM_PATH,
            user_template_path=CREATIVE_SITUATION_USER_TEMPLATE_PATH,
            mapping={
                "SELECTED_WORDS_JSON": deduped_selected,
                "SITUATION_COUNT": DEFAULT_CREATIVE_SITUATION_COUNT,
            },
        )

        everyday_situations = situation_payload.get("everyday_situations", [])
        if not isinstance(everyday_situations, list):
            everyday_situations = []

        if len(everyday_situations) < DEFAULT_CREATIVE_SITUATION_COUNT:
            fallback_sentences = [
                f"Someone has to deal with {word} during an ordinary but mildly inconvenient part of the day."
                for word in deduped_selected[:DEFAULT_CREATIVE_SITUATION_COUNT]
            ]
            for sentence in fallback_sentences:
                if len(everyday_situations) >= DEFAULT_CREATIVE_SITUATION_COUNT:
                    break
                everyday_situations.append(sentence)

        everyday_situations = [
            str(x).strip() for x in everyday_situations
            if isinstance(x, str) and str(x).strip()
        ]

        return {
            "enabled": True,
            #"random_words_pool": random_pool,
            #"selected_words": deduped_selected,
            "everyday_situations": everyday_situations,
            #"guidance": (
            #    "Use this packet only as soft inspiration. "
            #    "Do not force literal inclusion of any word or situation. "
            #    "Prefer subtle transformation into mood, objects, habits, pressures, "
            #   "misunderstandings, or scene texture."
            #),
        }

    def sample_random_words(self, *, word_file: Path, sample_size: int) -> list[str]:
        try:
            text = load_text(word_file, "")
        except Exception:
            text = ""

        words = [
            line.strip()
            for line in text.splitlines()
            if line.strip()
        ]

        # dedupe while preserving order
        deduped = []
        seen = set()
        for word in words:
            if word not in seen:
                deduped.append(word)
                seen.add(word)

        if not deduped:
            return []

        if sample_size >= len(deduped):
            shuffled = deduped[:]
            random.shuffle(shuffled)
            return shuffled

        return random.sample(deduped, sample_size)
