from __future__ import annotations

import copy
import datetime as dt
import math
from typing import Any

from config import (
    METRIC_ENVELOPE_SYSTEM_PATH,
    METRIC_ENVELOPE_USER_TEMPLATE_PATH,
    METRIC_REPAIR_SYSTEM_PATH,
    METRIC_REPAIR_USER_TEMPLATE_PATH,
    METRIC_SCHEMA_PATH,
    METRIC_SCHEMA_SYSTEM_PATH,
    METRIC_SCHEMA_USER_TEMPLATE_PATH,
    MODEL_PLANNER,
    STORY_PLAN_METRIC_ANALYSIS_PATH,
    STORY_PLAN_METRIC_REPAIR_PATH,
    STORY_PLAN_PATH,
)
from io_contract import load_json, load_text, save_json
from utils import fill_template


class StoryPlanMetricizer:
    """
    Test-purpose metricization pass.

    Reads existing story_plan.json, appends:
    - metric_schema
    - per-section metric_envelope
    - metric_design_notes
    - optional metric_repair_report

    This class is intentionally independent from story_planner.
    """

    def __init__(self, llm_client=None) -> None:
        self.llm_client = llm_client

    def run(
        self,
        *,
        auto_schema: bool = False,
        repair: bool = False,
        apply_repair: bool = False,
    ) -> dict[str, Any]:
        story_plan = load_json(STORY_PLAN_PATH, {})
        if not story_plan:
            raise RuntimeError("Missing story_plan.json. Run plan_story first.")

        metric_schema = self.load_or_build_metric_schema(
            story_plan=story_plan,
            auto_schema=auto_schema,
        )

        metricized_plan = copy.deepcopy(story_plan)
        metricized_plan["metric_schema"] = metric_schema
        metricized_plan["metric_design_notes"] = self.build_metric_design_notes(metric_schema)

        envelope_payload = self.assign_metric_envelopes(
            story_plan=metricized_plan,
            metric_schema=metric_schema,
        )

        self.apply_envelopes_to_sections(
            story_plan=metricized_plan,
            envelope_payload=envelope_payload,
        )

        analysis = self.analyze_metric_flow(
            story_plan=metricized_plan,
            metric_schema=metric_schema,
        )
        save_json(STORY_PLAN_METRIC_ANALYSIS_PATH, analysis)
        metricized_plan["metric_analysis"] = analysis

        if repair:
            repair_report = self.build_repair_report(
                story_plan=metricized_plan,
                metric_schema=metric_schema,
                metric_analysis=analysis,
            )
            save_json(STORY_PLAN_METRIC_REPAIR_PATH, repair_report)
            metricized_plan["metric_repair_report"] = repair_report

            if apply_repair:
                self.apply_repair_report(metricized_plan, repair_report)

        metricized_plan["metricized_at"] = dt.datetime.now(dt.timezone.utc).isoformat()

        save_json(STORY_PLAN_PATH, metricized_plan)
        return metricized_plan

    # -------------------------------------------------------------------------
    # 4A. Metric schema
    # -------------------------------------------------------------------------

    def load_or_build_metric_schema(
        self,
        *,
        story_plan: dict[str, Any],
        auto_schema: bool,
    ) -> dict[str, Any]:
        existing = load_json(METRIC_SCHEMA_PATH, {})
        if existing:
            return self.normalize_metric_schema(existing)

        schema = self.python_suggest_metric_schema(story_plan)

        if auto_schema:
            ai_schema = self.ai_refine_metric_schema(
                story_plan=story_plan,
                seed_schema=schema,
            )
            if ai_schema:
                schema = ai_schema

        schema = self.normalize_metric_schema(schema)
        save_json(METRIC_SCHEMA_PATH, schema)
        return schema

    def python_suggest_metric_schema(self, story_plan: dict[str, Any]) -> dict[str, Any]:
        genre = str(story_plan.get("genre", ""))
        tone = str(story_plan.get("tone", ""))
        premise = str(story_plan.get("premise", ""))

        text = f"{genre} {tone} {premise}"

        metrics: dict[str, Any] = {}

        def add_metric(
            name: str,
            description: str,
            monotonic_bias: str | None = None,
            max_up: int = 20,
            max_down: int = 15,
        ) -> None:
            metrics[name] = {
                "name": name,
                "description": description,
                "allowed_range": {
                    "min_value": 0,
                    "max_value": 100,
                },
                "default_step": {
                    "max_up": max_up,
                    "max_down": max_down,
                },
                "monotonic_bias": monotonic_bias,
            }

        # Baseline long-form fiction metrics.
        add_metric(
            "tension",
            "整體情節壓力、危機感、讀者預期與衝突強度。",
            monotonic_bias="rising",
            max_up=25,
            max_down=15,
        )
        add_metric(
            "protagonist_agency",
            "主角主動選擇、承擔後果、推動情節的程度。",
            monotonic_bias=None,
            max_up=25,
            max_down=20,
        )
        add_metric(
            "relationship_strain",
            "主角與重要角色之間的不信任、隔閡、衝突或情感壓力。",
            monotonic_bias="rising",
            max_up=25,
            max_down=20,
        )
        add_metric(
            "mystery_pressure",
            "未知規則、未解真相、懸念與讀者探索壓力。",
            monotonic_bias=None,
            max_up=25,
            max_down=20,
        )
        add_metric(
            "emotional_cost",
            "主角因選擇、秘密、失敗或傷害他人而承受的心理代價。",
            monotonic_bias="rising",
            max_up=25,
            max_down=15,
        )

        # Genre/tone-specific additions.
        if any(k in text for k in ["心理", "驚悚", "恐懼", "壓抑", "崩潰"]):
            add_metric(
                "psychological_fragility",
                "主角的精神不穩、現實感剝離、焦慮、罪惡感與崩潰風險。",
                monotonic_bias="rising",
                max_up=25,
                max_down=10,
            )

        if any(k in text for k in ["超能力", "預知", "未來", "因果", "命運", "時間"]):
            add_metric(
                "causal_instability",
                "因果被干預後出現的連鎖錯位、不可控後果與世界穩定性下降程度。",
                monotonic_bias="rising",
                max_up=30,
                max_down=10,
            )
            add_metric(
                "power_dependency",
                "主角對特殊能力、捷徑或外部工具的依賴程度。",
                monotonic_bias=None,
                max_up=30,
                max_down=25,
            )

        if any(k in text for k in ["成長", "青春", "校園", "中學生", "高中"]):
            add_metric(
                "identity_pressure",
                "主角對自我價值、同儕眼光、社會位置與成長焦慮的壓力。",
                monotonic_bias=None,
                max_up=25,
                max_down=20,
            )

        cross_metric_rules = [
            {
                "rule_id": "high_power_dependency_requires_cost",
                "description": "當 power_dependency 很高時，emotional_cost 或 causal_instability 不應過低。",
                "rule_type": "minimum_when_metric_high",
                "params": {
                    "trigger_metric": "power_dependency",
                    "trigger_min": 70,
                    "required_metric_any": ["emotional_cost", "causal_instability"],
                    "required_min": 55,
                },
            },
            {
                "rule_id": "late_story_tension_should_not_collapse",
                "description": "後段 tension 不應突然大幅下降，除非已進入結局收束。",
                "rule_type": "phase_trend",
                "params": {
                    "metric": "tension",
                    "late_min": 65,
                },
            },
        ]

        return {
            "version": "v1",
            "metrics": metrics,
            "cross_metric_rules": cross_metric_rules,
        }

    def ai_refine_metric_schema(
        self,
        *,
        story_plan: dict[str, Any],
        seed_schema: dict[str, Any],
    ) -> dict[str, Any]:
        if not self.llm_client:
            return seed_schema

        system_prompt = load_text(METRIC_SCHEMA_SYSTEM_PATH)
        user_template = load_text(METRIC_SCHEMA_USER_TEMPLATE_PATH)
        user_prompt = fill_template(
            user_template,
            {
                "STORY_PLAN_JSON": story_plan,
                "SEED_METRIC_SCHEMA_JSON": seed_schema,
            },
        )

        result = self.llm_client.generate_json(
            model=MODEL_PLANNER,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
        )

        return self.normalize_metric_schema(result)

    def normalize_metric_schema(self, schema: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(schema, dict):
            schema = {}

        schema.setdefault("version", "v1")

        metrics = schema.get("metrics", {})
        if not isinstance(metrics, dict):
            metrics = {}

        normalized_metrics = {}

        for name, raw in metrics.items():
            if not isinstance(raw, dict):
                continue

            metric_name = str(raw.get("name") or name)

            allowed_range = raw.get("allowed_range", {})
            if not isinstance(allowed_range, dict):
                allowed_range = {}

            default_step = raw.get("default_step", {})
            if not isinstance(default_step, dict):
                default_step = {}

            normalized_metrics[metric_name] = {
                "name": metric_name,
                "description": str(raw.get("description", "")),
                "allowed_range": {
                    "min_value": self.safe_int(allowed_range.get("min_value"), 0),
                    "max_value": self.safe_int(allowed_range.get("max_value"), 100),
                },
                "default_step": {
                    "max_up": self.safe_int(default_step.get("max_up"), 20),
                    "max_down": self.safe_int(default_step.get("max_down"), 15),
                },
                "monotonic_bias": raw.get("monotonic_bias"),
            }

        schema["metrics"] = normalized_metrics

        rules = schema.get("cross_metric_rules", [])
        if not isinstance(rules, list):
            rules = []
        schema["cross_metric_rules"] = rules

        return schema

    # -------------------------------------------------------------------------
    # 4B. Assign section metric envelopes
    # -------------------------------------------------------------------------

    def assign_metric_envelopes(
        self,
        *,
        story_plan: dict[str, Any],
        metric_schema: dict[str, Any],
    ) -> dict[str, Any]:
        if self.llm_client:
            return self.ai_assign_metric_envelopes(
                story_plan=story_plan,
                metric_schema=metric_schema,
            )

        return self.python_assign_metric_envelopes(
            story_plan=story_plan,
            metric_schema=metric_schema,
        )

    def ai_assign_metric_envelopes(
        self,
        *,
        story_plan: dict[str, Any],
        metric_schema: dict[str, Any],
    ) -> dict[str, Any]:
        system_prompt = load_text(METRIC_ENVELOPE_SYSTEM_PATH)
        user_template = load_text(METRIC_ENVELOPE_USER_TEMPLATE_PATH)
        user_prompt = fill_template(
            user_template,
            {
                "STORY_PLAN_JSON": story_plan,
                "METRIC_SCHEMA_JSON": metric_schema,
            },
        )

        result = self.llm_client.generate_json(
            model=MODEL_PLANNER,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
        )

        return self.normalize_envelope_payload(
            payload=result,
            story_plan=story_plan,
            metric_schema=metric_schema,
        )

    def python_assign_metric_envelopes(
        self,
        *,
        story_plan: dict[str, Any],
        metric_schema: dict[str, Any],
    ) -> dict[str, Any]:
        sections = story_plan.get("sections", [])
        metrics = list(metric_schema.get("metrics", {}).keys())
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

            for metric in metrics:
                value = self.default_metric_value(metric, ratio, role, text)
                center[metric] = value

            metric_min = {
                m: max(0, v - 12)
                for m, v in center.items()
            }
            metric_max = {
                m: min(100, v + 12)
                for m, v in center.items()
            }

            envelopes.append(
                {
                    "section_id": section.get("section_id", f"sec_{idx + 1:02d}"),
                    "label": section.get("title", f"Section {idx + 1}"),
                    "metric_min": metric_min,
                    "metric_max": metric_max,
                    "metric_expected_center": center,
                    "notes": "Assigned via Python fallback using section_role, position, and summary.",
                }
            )


        return {
            "section_metric_envelopes": envelopes,
            "assignment_notes": [
                "Python fallback mode used.",
                "Values are test-purpose only.",
            ],
        }

    def default_metric_value(self, metric: str, ratio: float, role: str, text: str) -> int:
        # Basic rising curve.
        base = 25 + int(ratio * 55)

        if "opening" in role:
            base -= 10
        if "midpoint" in role:
            base += 5
        if "crisis" in role:
            base += 15
        if "climax" in role or "resolution" in role:
            base += 20

        # Metric-specific curves.
        if metric == "tension":
            value = base
        elif metric == "protagonist_agency":
            value = 35 + int(math.sin(ratio * math.pi) * 35)
            if "climax" in role:
                value = 85
        elif metric == "relationship_strain":
            value = 20 + int(ratio * 60)
        elif metric == "mystery_pressure":
            value = 35 + int(math.sin(ratio * math.pi) * 40)
            if ratio > 0.8:
                value -= 15
        elif metric == "emotional_cost":
            value = 20 + int(ratio * 70)
        elif metric == "psychological_fragility":
            value = 15 + int(ratio * 75)
        elif metric == "causal_instability":
            value = 10 + int(ratio * 80)
        elif metric == "power_dependency":
            if ratio < 0.6:
                value = 25 + int(ratio * 85)
            else:
                value = 85 - int((ratio - 0.6) * 100)
        elif metric == "identity_pressure":
            value = 35 + int(math.sin(ratio * math.pi) * 35)
        else:
            value = base

        # Keyword nudges.
        if any(k in text for k in ["崩潰", "危機", "災難", "意外", "生死", "高潮"]):
            value += 10
        if any(k in text for k in ["平靜", "回歸", "釋然", "接受"]):
            if metric in ["tension", "mystery_pressure"]:
                value -= 15

        return max(0, min(100, int(value)))

    def normalize_envelope_payload(
        self,
        *,
        payload: dict[str, Any],
        story_plan: dict[str, Any],
        metric_schema: dict[str, Any],
    ) -> dict[str, Any]:
        if not isinstance(payload, dict):
            payload = {}

        sections = story_plan.get("sections", [])
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

        for idx, section in enumerate(sections):
            section_id = section.get("section_id", f"sec_{idx + 1:02d}")
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

                metric_min[metric] = max(0, min(100, lo))
                metric_max[metric] = max(0, min(100, hi))
                center[metric] = max(0, min(100, c))

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

        result = {}

        for name in metric_names:
            result[name] = max(0, min(100, self.safe_int(values.get(name), default)))

        return result

    def apply_envelopes_to_sections(
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
            section_id = section.get("section_id")
            if section_id in by_id:
                section["metric_envelope"] = by_id[section_id]

        story_plan["metric_assignment_notes"] = envelope_payload.get("assignment_notes", [])

    # -------------------------------------------------------------------------
    # Analysis
    # -------------------------------------------------------------------------

    def analyze_metric_flow(
        self,
        *,
        story_plan: dict[str, Any],
        metric_schema: dict[str, Any],
    ) -> dict[str, Any]:
        sections = story_plan.get("sections", [])
        metric_names = list(metric_schema.get("metrics", {}).keys())

        issues = []
        series = {
            metric: []
            for metric in metric_names
        }

        for section in sections:
            section_id = section.get("section_id")
            env = section.get("metric_envelope", {})
            center = env.get("metric_expected_center", {})

            for metric in metric_names:
                value = self.safe_int(center.get(metric), 50)
                series[metric].append(
                    {
                        "section_id": section_id,
                        "value": value,
                    }
                )

        # Step checks.
        for metric in metric_names:
            metric_def = metric_schema.get("metrics", {}).get(metric, {})
            step = metric_def.get("default_step", {})
            max_up = self.safe_int(step.get("max_up"), 20)
            max_down = self.safe_int(step.get("max_down"), 15)
            values = series.get(metric, [])

            for i in range(1, len(values)):
                prev = values[i - 1]
                cur = values[i]
                delta = cur["value"] - prev["value"]

                if delta > max_up:
                    issues.append(
                        {
                            "level": "warning",
                            "code": "metric_jump_up",
                            "metric_name": metric,
                            "from_section_id": prev["section_id"],
                            "to_section_id": cur["section_id"],
                            "message": f"{metric} increased by {delta}, exceeding the recommended max_up={max_up}.",
                        }
                    )
                elif -delta > max_down:
                    issues.append(
                        {
                            "level": "warning",
                            "code": "metric_drop_down",
                            "metric_name": metric,
                            "from_section_id": prev["section_id"],
                            "to_section_id": cur["section_id"],
                            "message": f"{metric} decreased by {-delta}, exceeding the recommended max_down={max_down}.",
                        }
                    )


        # Section duration + bridge simple check.
        bridge_pairs = set()
        for bridge in story_plan.get("between_section_bridges", []):
            bridge_pairs.add((bridge.get("from_section_id"), bridge.get("to_section_id")))

        for i in range(1, len(sections)):
            prev = sections[i - 1]
            cur = sections[i]
            prev_tw = prev.get("time_window", {})
            cur_tw = cur.get("time_window", {})
            prev_end = self.safe_int(prev_tw.get("end_day"), 0)
            cur_start = self.safe_int(cur_tw.get("start_day"), prev_end)
            gap = cur_start - prev_end

            if gap >= 1 and (prev.get("section_id"), cur.get("section_id")) not in bridge_pairs:
                issues.append(
                    {
                        "level": "warning",
                        "code": "missing_bridge_for_time_gap",
                        "metric_name": None,
                        "from_section_id": prev.get("section_id"),
                        "to_section_id": cur.get("section_id"),
                        "message": f"There is a {gap}-day time skip between sections without any bridge facts.",
                    }
                )


        return {
            "series": series,
            "issues": issues,
            "summary": {
                "metric_count": len(metric_names),
                "section_count": len(sections),
                "issue_count": len(issues),
            },
        }

    # -------------------------------------------------------------------------
    # 5. Repair
    # -------------------------------------------------------------------------

    def build_repair_report(
        self,
        *,
        story_plan: dict[str, Any],
        metric_schema: dict[str, Any],
        metric_analysis: dict[str, Any],
    ) -> dict[str, Any]:
        if not self.llm_client:
            return {
                "repair_needed": bool(metric_analysis.get("issues")),
                "repair_summary": "No LLM client provided. Only numeric issues were detected.",
                "suggestions": [],
                "insert_sections": [],
                "add_bridge_facts": [],
                "adjust_section_events": [],
                "adjust_metric_envelopes": [],
                "raw_metric_issues": metric_analysis.get("issues", []),
            }

        system_prompt = load_text(METRIC_REPAIR_SYSTEM_PATH)
        user_template = load_text(METRIC_REPAIR_USER_TEMPLATE_PATH)
        user_prompt = fill_template(
            user_template,
            {
                "STORY_PLAN_JSON": story_plan,
                "METRIC_SCHEMA_JSON": metric_schema,
                "METRIC_ANALYSIS_JSON": metric_analysis,
            },
        )

        result = self.llm_client.generate_json(
            model=MODEL_PLANNER,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
        )

        return self.normalize_repair_report(result)

    def normalize_repair_report(self, report: Any) -> dict[str, Any]:
        if not isinstance(report, dict):
            report = {}

        report.setdefault("repair_needed", False)
        report.setdefault("repair_summary", "")
        report.setdefault("suggestions", [])
        report.setdefault("insert_sections", [])
        report.setdefault("add_bridge_facts", [])
        report.setdefault("adjust_section_events", [])
        report.setdefault("adjust_metric_envelopes", [])

        if not isinstance(report["suggestions"], list):
            report["suggestions"] = []
        if not isinstance(report["insert_sections"], list):
            report["insert_sections"] = []
        if not isinstance(report["add_bridge_facts"], list):
            report["add_bridge_facts"] = []
        if not isinstance(report["adjust_section_events"], list):
            report["adjust_section_events"] = []
        if not isinstance(report["adjust_metric_envelopes"], list):
            report["adjust_metric_envelopes"] = []

        return report

    def apply_repair_report(
        self,
        story_plan: dict[str, Any],
        repair_report: dict[str, Any],
    ) -> None:
        """
        Conservative patching for test use.

        Applies:
        - add_bridge_facts
        - adjust_metric_envelopes
        - adjust_section_events

        Inserted sections are recorded under pending_insert_sections,
        but not automatically inserted by default because this can disrupt downstream section ids.
        """
        existing_bridges = story_plan.setdefault("between_section_bridges", [])

        for bridge in repair_report.get("add_bridge_facts", []):
            if isinstance(bridge, dict):
                existing_bridges.append(bridge)

        section_by_id = {
            s.get("section_id"): s
            for s in story_plan.get("sections", [])
            if isinstance(s, dict)
        }

        for patch in repair_report.get("adjust_metric_envelopes", []):
            if not isinstance(patch, dict):
                continue

            section_id = patch.get("section_id")
            if section_id not in section_by_id:
                continue

            section = section_by_id[section_id]
            env = section.setdefault("metric_envelope", {})
            center_patch = patch.get("metric_expected_center", {})

            if isinstance(center_patch, dict):
                center = env.setdefault("metric_expected_center", {})
                for metric, value in center_patch.items():
                    center[metric] = max(0, min(100, self.safe_int(value, 50)))

        for patch in repair_report.get("adjust_section_events", []):
            if not isinstance(patch, dict):
                continue

            section_id = patch.get("section_id")
            if section_id not in section_by_id:
                continue

            section = section_by_id[section_id]

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

        # Do not auto-insert sections in test mode.
        story_plan["pending_insert_sections"] = repair_report.get("insert_sections", [])

    def build_metric_design_notes(self, metric_schema: dict[str, Any]) -> list[str]:
        return [
            f"{name}: {metric.get('description', '')}"
            for name, metric in metric_schema.get("metrics", {}).items()
            if isinstance(metric, dict)
        ]

    def safe_int(self, value: Any, default: int = 0) -> int:
        try:
            return int(value)
        except Exception:
            return default