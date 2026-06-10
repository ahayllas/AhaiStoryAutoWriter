from __future__ import annotations

from typing import Any


class MetricFlowAnalyzer:
    def analyze(
        self,
        *,
        story_plan: dict[str, Any],
        metric_schema: dict[str, Any],
    ) -> dict[str, Any]:
        sections = story_plan.get("sections", [])
        metric_names = list(metric_schema.get("metrics", {}).keys())

        series = self.build_series(sections, metric_names)
        issues = []
        transition_scores: dict[str, dict[str, Any]] = {}

        for metric in metric_names:
            metric_def = metric_schema.get("metrics", {}).get(metric, {})
            step = metric_def.get("default_step", {})
            max_up = self.safe_int(step.get("max_up"), 20)
            max_down = self.safe_int(step.get("max_down"), 15)

            values = series.get(metric, [])

            for i in range(1, len(values)):
                prev_section = sections[i - 1]
                cur_section = sections[i]
                span_factor = self.transition_span_factor(prev_section, cur_section)

                allowed_up = max_up * span_factor
                allowed_down = max_down * span_factor
                prev = values[i - 1]
                cur = values[i]
                delta = cur["value"] - prev["value"]

                over_by = 0
                code = None

                if delta > allowed_up:
                    over_by = delta - allowed_up
                    code = "metric_jump_up"
                elif -delta > allowed_down:
                    over_by = (-delta) - allowed_down
                    code = "metric_drop_down"

                if code:
                    transition_key = f"{prev['section_id']}->{cur['section_id']}"

                    issue = {
                        "level": "warning",
                        "code": code,
                        "metric_name": metric,
                        "from_section_id": prev["section_id"],
                        "to_section_id": cur["section_id"],
                        "previous_value": prev["value"],
                        "current_value": cur["value"],
                        "delta": delta,
                        "allowed_up": max_up,
                        "allowed_down": max_down,
                        "over_by": over_by,
                        "message": f"{metric} changed by {delta}, exceeding allowed transition by {over_by}.",
                    }
                    issues.append(issue)

                    entry = transition_scores.setdefault(
                        transition_key,
                        {
                            "from_section_id": prev["section_id"],
                            "to_section_id": cur["section_id"],
                            "score": 0,
                            "issue_count": 0,
                            "metrics": [],
                        },
                    )
                    entry["score"] += over_by
                    entry["issue_count"] += 1
                    entry["metrics"].append(
                        {
                            "metric_name": metric,
                            "delta": delta,
                            "over_by": over_by,
                            "code": code,
                        }
                    )

        bridge_issues = self.analyze_bridges(story_plan)
        issues.extend(bridge_issues)

        for issue in bridge_issues:
            key = f"{issue.get('from_section_id')}->{issue.get('to_section_id')}"
            entry = transition_scores.setdefault(
                key,
                {
                    "from_section_id": issue.get("from_section_id"),
                    "to_section_id": issue.get("to_section_id"),
                    "score": 0,
                    "issue_count": 0,
                    "metrics": [],
                },
            )
            entry["score"] += 10
            entry["issue_count"] += 1
            entry["metrics"].append(
                {
                    "metric_name": None,
                    "delta": None,
                    "over_by": 10,
                    "code": issue.get("code"),
                }
            )

        top_problem_transitions = sorted(
            transition_scores.values(),
            key=lambda x: x.get("score", 0),
            reverse=True,
        )

        return {
            "series": series,
            "issues": issues,
            "top_problem_transitions": top_problem_transitions,
            "summary": {
                "metric_count": len(metric_names),
                "section_count": len(sections),
                "issue_count": len(issues),
                "problem_transition_count": len(top_problem_transitions),
            },
        }

    def build_series(
        self,
        sections: list[dict[str, Any]],
        metric_names: list[str],
    ) -> dict[str, list[dict[str, Any]]]:
        series = {metric: [] for metric in metric_names}

        for section in sections:
            sid = section.get("section_id")
            center = (
                section.get("metric_envelope", {})
                .get("metric_expected_center", {})
            )

            for metric in metric_names:
                series[metric].append(
                    {
                        "section_id": sid,
                        "value": self.safe_int(center.get(metric), 50),
                    }
                )

        return series

    def analyze_bridges(self, story_plan: dict[str, Any]) -> list[dict[str, Any]]:
        sections = story_plan.get("sections", [])
        bridges = story_plan.get("between_section_bridges", [])

        bridge_pairs = {
            (b.get("from_section_id"), b.get("to_section_id"))
            for b in bridges
            if isinstance(b, dict)
        }

        issues = []

        for i in range(1, len(sections)):
            prev = sections[i - 1]
            cur = sections[i]

            prev_id = prev.get("section_id")
            cur_id = cur.get("section_id")

            prev_end = self.safe_int(prev.get("time_window", {}).get("end_day"), 0)
            cur_start = self.safe_int(cur.get("time_window", {}).get("start_day"), prev_end)
            gap = cur_start - prev_end

            if gap >= 1 and (prev_id, cur_id) not in bridge_pairs:
                issues.append(
                    {
                        "level": "warning",
                        "code": "missing_bridge_for_time_gap",
                        "from_section_id": prev_id,
                        "to_section_id": cur_id,
                        "time_gap_days": gap,
                        "message": f"Time gap of {gap} day(s) without bridge facts.",
                    }
                )

        return issues

    def compact_summary(self, analysis: dict[str, Any], *, top_n: int = 3) -> dict[str, Any]:
        return {
            "summary": analysis.get("summary", {}),
            "top_problem_transitions": analysis.get("top_problem_transitions", [])[:top_n],
        }

    def transition_slice(
        self,
        analysis: dict[str, Any],
        *,
        from_section_id: str,
        to_section_id: str,
    ) -> dict[str, Any]:
        issues = [
            issue
            for issue in analysis.get("issues", [])
            if issue.get("from_section_id") == from_section_id
            and issue.get("to_section_id") == to_section_id
        ]

        score_entry = None
        for item in analysis.get("top_problem_transitions", []):
            if (
                item.get("from_section_id") == from_section_id
                and item.get("to_section_id") == to_section_id
            ):
                score_entry = item
                break

        return {
            "transition": {
                "from_section_id": from_section_id,
                "to_section_id": to_section_id,
            },
            "score_entry": score_entry,
            "issues": issues,
        }

    def safe_int(self, value: Any, default: int = 0) -> int:
        try:
            return int(value)
        except Exception:
            return default
            
    def transition_span_factor(
        self,
        prev_section: dict[str, Any],
        cur_section: dict[str, Any],
    ) -> int:
        prev_segments = self.safe_int(prev_section.get("planned_segments_max"), 1)
        cur_segments = self.safe_int(cur_section.get("planned_segments_min"), 1)

        # 大 section 之間允許較大變化，但不要無限放大。
        return max(1, min(3, round((prev_segments + cur_segments) / 2)))