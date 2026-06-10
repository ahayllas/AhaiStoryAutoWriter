from __future__ import annotations

import math
from typing import Any

from config import (
    METRIC_ENVELOPE_SYSTEM_PATH,
    METRIC_ENVELOPE_USER_TEMPLATE_PATH,
    MODEL_METRICIZE,
)
from io_contract import load_text
from utils import fill_template


class MetricEnvelopeAssigner:
    def __init__(self, llm_client=None) -> None:
        self.llm_client = llm_client

    def assign(
        self,
        *,
        story_plan: dict[str, Any],
        metric_schema: dict[str, Any],
        use_ai: bool = False,
    ) -> dict[str, Any]:
        if use_ai and self.llm_client:
            return self.ai_assign(
                story_plan=story_plan,
                metric_schema=metric_schema,
            )

        return self.python_assign(
            story_plan=story_plan,
            metric_schema=metric_schema,
        )

    def compact_plan_for_envelope(self, story_plan: dict[str, Any]) -> dict[str, Any]:
        return {
            "title": story_plan.get("title"),
            "premise": story_plan.get("premise"),
            "genre": story_plan.get("genre"),
            "tone": story_plan.get("tone"),
            "setting": story_plan.get("setting"),
            "core_conflict": story_plan.get("core_conflict"),
            "ending_overview": story_plan.get("ending_overview"),
            "global_constraints": story_plan.get("global_constraints"),
            "sections": [
                {
                    "section_id": s.get("section_id"),
                    "title": s.get("title"),
                    "section_role": s.get("section_role"),
                    "narrative_weight": s.get("narrative_weight"),
                    "purpose": s.get("purpose"),
                    "entry_state": s.get("entry_state"),
                    "time_window": s.get("time_window"),
                    "summary": s.get("summary"),
                    "causality_from_previous": s.get("causality_from_previous"),
                    "protagonist_decision": s.get("protagonist_decision"),
                    "mandatory_events": s.get("mandatory_events", []),
                    "new_facts_established": s.get("new_facts_established", []),
                    "state_changes": s.get("state_changes", []),
                    "desired_end_state": s.get("desired_end_state"),
                    "ending_trigger": s.get("ending_trigger"),
                    "planned_segments_min": s.get("planned_segments_min"),
                    "planned_segments_max": s.get("planned_segments_max"),
                }
                for s in story_plan.get("sections", [])
            ],
        }

    def ai_assign(
        self,
        *,
        story_plan: dict[str, Any],
        metric_schema: dict[str, Any],
    ) -> dict[str, Any]:
        system_prompt = load_text(METRIC_ENVELOPE_SYSTEM_PATH)
        user_template = load_text(METRIC_ENVELOPE_USER_TEMPLATE_PATH)

        compact_plan = self.compact_plan_for_envelope(story_plan)

        user_prompt = fill_template(
            user_template,
            {
                "STORY_PLAN_JSON": compact_plan,
                "METRIC_SCHEMA_JSON": metric_schema,
            },
        )

        result = self.llm_client.generate_json(
            model=MODEL_METRICIZE,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
        )

        return self.normalize_envelope_payload(
            payload=result,
            story_plan=story_plan,
            metric_schema=metric_schema,
        )

    def python_assign(
        self,
        *,
        story_plan: dict[str, Any],
        metric_schema: dict[str, Any],
    ) -> dict[str, Any]:
        sections = story_plan.get("sections", [])
        metric_names = list(metric_schema.get("metrics", {}).keys())
        n = max(1, len(sections))

        envelopes = []

        for idx, section in enumerate(sections):
            ratio = idx / max(1, n - 1)
            role = str(section.get("section_role", ""))
            text = " ".join(
                [
                    str(section.get("title", "")),
                    str(section.get("purpose", "")),
                    str(section.get("summary", "")),
                    str(section.get("desired_end_state", "")),
                ]
            )

            center = {}
            for metric in metric_names:
                center[metric] = self.default_metric_value(metric, ratio, role, text)

            metric_min = {m: max(0, v - 12) for m, v in center.items()}
            metric_max = {m: min(100, v + 12) for m, v in center.items()}

            envelopes.append(
                {
                    "section_id": section.get("section_id"),
                    "label": section.get("title"),
                    "metric_min": metric_min,
                    "metric_max": metric_max,
                    "metric_expected_center": center,
                    "notes": "Python fallback envelope.",
                }
            )

        return {
            "section_metric_envelopes": envelopes,
            "assignment_notes": [
                "Python fallback mode used."
            ],
        }

    def default_metric_value(self, metric: str, ratio: float, role: str, text: str) -> int:
        base = 25 + int(ratio * 55)

        if "opening" in role:
            base -= 10
        if "midpoint" in role:
            base += 5
        if "crisis" in role:
            base += 15
        if "climax" in role or "resolution" in role:
            base += 20

        if metric == "tension":
            value = base
        elif metric == "mystery":
            value = 30 + int(math.sin(ratio * math.pi) * 35)
            if ratio > 0.75:
                value -= 10
        elif metric == "emotional_heat":
            value = 25 + int(ratio * 65)
        elif metric == "relationship_strain":
            value = 20 + int(ratio * 60)
        elif metric == "information_release":
            value = 25 + int(ratio * 55)
        elif metric == "pace":
            value = 30 + int(ratio * 55)
        elif metric == "threat_salience":
            value = 15 + int(ratio * 75)
        elif metric == "hope":
            if ratio < 0.35:
                value = 35 + int(ratio * 35)
            elif ratio < 0.8:
                value = 50 - int((ratio - 0.35) * 45)
            else:
                value = 45
        elif metric == "causal_instability":
            value = 10 + int(ratio * 80)
        elif metric == "power_dependency":
            if ratio < 0.65:
                value = 25 + int(ratio * 80)
            else:
                value = 80 - int((ratio - 0.65) * 110)
        elif metric == "psychological_fragility":
            value = 15 + int(ratio * 75)
        else:
            value = base

        if any(k in text for k in ["崩潰", "危機", "災難", "意外", "生死"]):
            value += 8

        if any(k in text for k in ["平靜", "回歸", "釋然", "接受"]):
            if metric in ["tension", "mystery", "threat_salience"]:
                value -= 10
            if metric == "hope":
                value += 10

        return max(0, min(100, int(value)))

    def normalize_envelope_payload(
        self,
        *,
        payload: Any,
        story_plan: dict[str, Any],
        metric_schema: dict[str, Any],
    ) -> dict[str, Any]:
        if not isinstance(payload, dict):
            payload = {}

        metric_names = list(metric_schema.get("metrics", {}).keys())

        raw_envelopes = payload.get("section_metric_envelopes", [])
        if not isinstance(raw_envelopes, list):
            raw_envelopes = []

        by_section_id = {
            e.get("section_id"): e
            for e in raw_envelopes
            if isinstance(e, dict)
        }

        normalized = []

        for section in story_plan.get("sections", []):
            section_id = section.get("section_id")
            raw = by_section_id.get(section_id, {})

            center = self.normalize_metric_values(
                raw.get("metric_expected_center", {}),
                metric_names,
                default=50,
            )
            metric_min = self.normalize_metric_values(
                raw.get("metric_min", {}),
                metric_names,
                default=40,
            )
            metric_max = self.normalize_metric_values(
                raw.get("metric_max", {}),
                metric_names,
                default=60,
            )

            for metric in metric_names:
                c = center[metric]
                lo = metric_min[metric]
                hi = metric_max[metric]

                if lo > c:
                    lo = max(0, c - 10)
                if hi < c:
                    hi = min(100, c + 10)

                metric_min[metric] = lo
                metric_max[metric] = hi
                center[metric] = c

            normalized.append(
                {
                    "section_id": section_id,
                    "label": raw.get("label") or section.get("title") or section_id,
                    "metric_min": metric_min,
                    "metric_max": metric_max,
                    "metric_expected_center": center,
                    "notes": raw.get("notes", ""),
                }
            )

        return {
            "section_metric_envelopes": normalized,
            "assignment_notes": payload.get("assignment_notes", []),
        }

    def normalize_metric_values(
        self,
        values: Any,
        metric_names: list[str],
        *,
        default: int,
    ) -> dict[str, int]:
        if not isinstance(values, dict):
            values = {}

        return {
            name: max(0, min(100, self.safe_int(values.get(name), default)))
            for name in metric_names
        }

    def apply_to_story_plan(
        self,
        *,
        story_plan: dict[str, Any],
        envelope_payload: dict[str, Any],
    ) -> None:
        envelopes = envelope_payload.get("section_metric_envelopes", [])
        by_id = {
            e.get("section_id"): e
            for e in envelopes
            if isinstance(e, dict)
        }

        for section in story_plan.get("sections", []):
            sid = section.get("section_id")
            if sid in by_id:
                section["metric_envelope"] = by_id[sid]

        story_plan["metric_assignment_notes"] = envelope_payload.get("assignment_notes", [])

    def safe_int(self, value: Any, default: int = 0) -> int:
        try:
            return int(value)
        except Exception:
            return default