from __future__ import annotations

from typing import Any

from config import (
    METRIC_REPAIR_SYSTEM_PATH,
    METRIC_REPAIR_USER_TEMPLATE_PATH,
    MODEL_PLANNER,
    STORY_PLAN_METRIC_REPAIR_PATH,
)
from io_contract import load_text, save_json
from utils import fill_template
from .analyzer import MetricFlowAnalyzer
from .context_builder import StoryPlanRepairContextBuilder


class MetricRepairPlanner:
    def __init__(self, llm_client=None) -> None:
        self.llm_client = llm_client
        self.analyzer = MetricFlowAnalyzer()
        self.context_builder = StoryPlanRepairContextBuilder()

    def plan_repairs(
        self,
        *,
        story_plan: dict[str, Any],
        metric_schema: dict[str, Any],
        metric_analysis: dict[str, Any],
        top_n: int = 2,
    ) -> dict[str, Any]:
        if not self.llm_client:
            report = {
                "repair_needed": bool(metric_analysis.get("issues")),
                "repair_summary": "No LLM client provided. Numeric analysis only.",
                "transition_reports": [],
                "combined": self.empty_combined_report(),
            }
            save_json(STORY_PLAN_METRIC_REPAIR_PATH, report)
            return report

        transitions = metric_analysis.get("top_problem_transitions", [])[:top_n]
        transition_reports = []

        for t in transitions:
            from_id = t.get("from_section_id")
            to_id = t.get("to_section_id")

            if not from_id or not to_id:
                continue

            transition_report = self.plan_single_transition_repair(
                story_plan=story_plan,
                metric_schema=metric_schema,
                metric_analysis=metric_analysis,
                from_section_id=from_id,
                to_section_id=to_id,
            )
            transition_reports.append(transition_report)

        combined = self.combine_reports(transition_reports)

        report = {
            "repair_needed": bool(transition_reports),
            "repair_summary": self.build_summary(combined, transition_reports),
            "transition_reports": transition_reports,
            "combined": combined,
        }

        save_json(STORY_PLAN_METRIC_REPAIR_PATH, report)
        return report

    def plan_single_transition_repair(
        self,
        *,
        story_plan: dict[str, Any],
        metric_schema: dict[str, Any],
        metric_analysis: dict[str, Any],
        from_section_id: str,
        to_section_id: str,
    ) -> dict[str, Any]:
        repair_context = self.context_builder.build_transition_context(
            story_plan=story_plan,
            from_section_id=from_section_id,
            to_section_id=to_section_id,
            include_neighbors=True,
        )

        analysis_slice = self.analyzer.transition_slice(
            metric_analysis,
            from_section_id=from_section_id,
            to_section_id=to_section_id,
        )

        system_prompt = load_text(METRIC_REPAIR_SYSTEM_PATH)
        user_template = load_text(METRIC_REPAIR_USER_TEMPLATE_PATH)

        user_prompt = fill_template(
            user_template,
            {
                # Keep placeholder name same to avoid rewriting template if you want.
                # But content is now compact repair context, not full plan.
                "STORY_PLAN_JSON": repair_context,
                "METRIC_SCHEMA_JSON": metric_schema,
                "METRIC_ANALYSIS_JSON": analysis_slice,
            },
        )

        result = self.llm_client.generate_json(
            model=MODEL_PLANNER,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
        )

        normalized = self.normalize_report(result)
        normalized["focused_transition"] = {
            "from_section_id": from_section_id,
            "to_section_id": to_section_id,
        }
        return normalized

    def empty_combined_report(self) -> dict[str, Any]:
        return {
            "suggestions": [],
            "insert_sections": [],
            "add_bridge_facts": [],
            "adjust_section_events": [],
            "adjust_metric_envelopes": [],
        }

    def combine_reports(self, reports: list[dict[str, Any]]) -> dict[str, Any]:
        combined = self.empty_combined_report()

        for report in reports:
            for key in combined.keys():
                items = report.get(key, [])
                if isinstance(items, list):
                    combined[key].extend(items)

        # de-duplicate bridge_id and section metric patches lightly
        seen_bridge_ids = set()
        dedup_bridges = []
        for b in combined["add_bridge_facts"]:
            bid = b.get("bridge_id") if isinstance(b, dict) else None
            if bid and bid in seen_bridge_ids:
                continue
            if bid:
                seen_bridge_ids.add(bid)
            dedup_bridges.append(b)
        combined["add_bridge_facts"] = dedup_bridges

        return combined

    def build_summary(
        self,
        combined: dict[str, Any],
        transition_reports: list[dict[str, Any]],
    ) -> str:
        return (
            f"Generated repair suggestions for {len(transition_reports)} transition(s): "
            f"{len(combined.get('add_bridge_facts', []))} bridge patch(es), "
            f"{len(combined.get('adjust_section_events', []))} event patch(es), "
            f"{len(combined.get('adjust_metric_envelopes', []))} metric patch(es), "
            f"{len(combined.get('insert_sections', []))} insert section suggestion(s)."
        )

    def normalize_report(self, report: Any) -> dict[str, Any]:
        if not isinstance(report, dict):
            report = {}

        report.setdefault("repair_needed", False)
        report.setdefault("repair_summary", "")
        report.setdefault("suggestions", [])
        report.setdefault("insert_sections", [])
        report.setdefault("add_bridge_facts", [])
        report.setdefault("adjust_section_events", [])
        report.setdefault("adjust_metric_envelopes", [])

        for key in [
            "suggestions",
            "insert_sections",
            "add_bridge_facts",
            "adjust_section_events",
            "adjust_metric_envelopes",
        ]:
            if not isinstance(report.get(key), list):
                report[key] = []

        return report