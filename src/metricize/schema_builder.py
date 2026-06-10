from __future__ import annotations

from typing import Any

from config import (
    METRIC_SCHEMA_PATH,
    METRIC_SCHEMA_SYSTEM_PATH,
    METRIC_SCHEMA_USER_TEMPLATE_PATH,
    MODEL_PLANNER,
)
from io_contract import load_json, load_text, save_json
from utils import fill_template


class MetricSchemaBuilder:
    def __init__(self, llm_client=None) -> None:
        self.llm_client = llm_client

    def load_or_build(
        self,
        *,
        story_plan: dict[str, Any],
        auto_schema: bool = False,
        overwrite: bool = False,
    ) -> dict[str, Any]:
        existing = load_json(METRIC_SCHEMA_PATH, {})
        if existing and not overwrite:
            return self.normalize(existing)

        seed = self.python_seed_schema(story_plan)

        if auto_schema and self.llm_client:
            refined = self.ai_refine_schema(
                story_plan=story_plan,
                seed_schema=seed,
            )
            schema = refined or seed
        else:
            schema = seed

        schema = self.normalize(schema)
        save_json(METRIC_SCHEMA_PATH, schema)
        return schema

    def python_seed_schema(self, story_plan: dict[str, Any]) -> dict[str, Any]:
        genre = str(story_plan.get("genre", ""))
        tone = str(story_plan.get("tone", ""))
        premise = str(story_plan.get("premise", ""))
        text = f"{genre} {tone} {premise}"

        metrics: dict[str, Any] = {}

        def add(
            name: str,
            description: str,
            *,
            max_up: int = 20,
            max_down: int = 15,
            monotonic_bias: str | None = None,
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

        add("tension", "情節壓力、危機感與不穩定程度。", max_up=20, max_down=15, monotonic_bias="rising")
        add("mystery", "未知規則、未解真相與懸念壓力。", max_up=18, max_down=18)
        add("emotional_heat", "角色情緒強度、心理負荷與情感爆發程度。", max_up=22, max_down=18)
        add("relationship_strain", "人際關係中的隔閡、衝突、懷疑與破裂程度。", max_up=20, max_down=15)
        add("information_release", "明確揭示新資訊、規則或真相的程度。", max_up=25, max_down=20)
        add("pace", "事件密度、推進速度與場面緊湊程度。", max_up=25, max_down=20)
        add("threat_salience", "危險、傷害、風險在讀者感知中的突出程度。", max_up=22, max_down=15)
        add("hope", "修復、成功、連結或逃離危機的可能性感。", max_up=18, max_down=20)

        if any(k in text for k in ["預知", "因果", "命運", "未來", "時間"]):
            add("causal_instability", "因果干預造成的連鎖失控、錯位與世界不穩定程度。", max_up=25, max_down=12, monotonic_bias="rising")
            add("power_dependency", "主角對眼鏡、預知或捷徑的心理依賴程度。", max_up=25, max_down=25)

        if any(k in text for k in ["心理", "驚悚", "壓抑", "崩潰"]):
            add("psychological_fragility", "主角現實感剝離、焦慮、罪惡感與精神崩潰風險。", max_up=25, max_down=12, monotonic_bias="rising")

        return {
            "version": "metric_schema_v1",
            "metrics": metrics,
            "cross_metric_rules": [
                {
                    "rule_id": "high_power_dependency_requires_cost",
                    "description": "主角高度依賴能力時，情緒代價、威脅或因果不穩定不應過低。",
                    "rule_type": "minimum_when_metric_high",
                    "params": {
                        "trigger_metric": "power_dependency",
                        "trigger_min": 70,
                        "required_metric_any": [
                            "emotional_heat",
                            "threat_salience",
                            "causal_instability"
                        ],
                        "required_min": 55
                    }
                },
                {
                    "rule_id": "threat_caps_hope",
                    "description": "威脅極高時，希望感不能過度輕盈，除非是結尾釋放。",
                    "rule_type": "conditional_cap",
                    "params": {
                        "if_metric": "threat_salience",
                        "if_gte": 75,
                        "target_metric": "hope",
                        "max_value": 70
                    }
                }
            ],
        }

    def ai_refine_schema(
        self,
        *,
        story_plan: dict[str, Any],
        seed_schema: dict[str, Any],
    ) -> dict[str, Any] | None:
        if not self.llm_client:
            return None

        # schema refinement 不需要完整 metricized story_plan，先壓縮。
        compact_plan = self.compact_plan_for_schema(story_plan)

        system_prompt = load_text(METRIC_SCHEMA_SYSTEM_PATH)
        user_template = load_text(METRIC_SCHEMA_USER_TEMPLATE_PATH)

        user_prompt = fill_template(
            user_template,
            {
                "STORY_PLAN_JSON": compact_plan,
                "SEED_METRIC_SCHEMA_JSON": seed_schema,
            },
        )

        result = self.llm_client.generate_json(
            model=MODEL_PLANNER,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
        )

        return self.normalize(result)

    def compact_plan_for_schema(self, story_plan: dict[str, Any]) -> dict[str, Any]:
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
            "section_summaries": [
                {
                    "section_id": s.get("section_id"),
                    "title": s.get("title"),
                    "section_role": s.get("section_role"),
                    "summary": s.get("summary"),
                    "desired_end_state": s.get("desired_end_state"),
                }
                for s in story_plan.get("sections", [])
            ],
        }

    def normalize(self, schema: Any) -> dict[str, Any]:
        if not isinstance(schema, dict):
            schema = {}

        schema.setdefault("version", "metric_schema_v1")

        metrics = schema.get("metrics", {})
        if not isinstance(metrics, dict):
            metrics = {}

        normalized = {}
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

            normalized[metric_name] = {
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

        schema["metrics"] = normalized

        rules = schema.get("cross_metric_rules", [])
        if not isinstance(rules, list):
            rules = []
        schema["cross_metric_rules"] = rules

        return schema

    def safe_int(self, value: Any, default: int = 0) -> int:
        try:
            return int(value)
        except Exception:
            return default