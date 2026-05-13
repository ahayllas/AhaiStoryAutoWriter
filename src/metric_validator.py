from __future__ import annotations

from typing import Optional

from schemas import (
    CrossMetricRule,
    MetricDefinition,
    MetricRange,
    MetricSchemaV1,
    SectionMetricEnvelope,
    SegmentMetricTarget,
    StepConstraint,
    ValidationIssue,
    ValidationReport,
)


def parse_metric_schema(raw: dict) -> MetricSchemaV1:
    metrics = {}
    for name, item in raw.get("metrics", {}).items():
        metrics[name] = MetricDefinition(
            name=name,
            description=item["description"],
            allowed_range=MetricRange(
                min_value=item["allowed_range"]["min_value"],
                max_value=item["allowed_range"]["max_value"],
            ),
            default_step=StepConstraint(
                max_up=item["default_step"]["max_up"],
                max_down=item["default_step"]["max_down"],
            ),
            monotonic_bias=item.get("monotonic_bias"),
        )

    rules = []
    for rule in raw.get("cross_metric_rules", []):
        rules.append(CrossMetricRule(
            rule_id=rule["rule_id"],
            description=rule["description"],
            rule_type=rule["rule_type"],
            params=rule["params"],
        ))

    return MetricSchemaV1(
        version=raw["version"],
        metrics=metrics,
        cross_metric_rules=rules,
    )


def parse_section_envelope(raw: dict) -> SectionMetricEnvelope:
    return SectionMetricEnvelope(
        section_id=raw["section_id"],
        label=raw.get("label", raw["section_id"]),
        metric_min=raw["metric_min"],
        metric_max=raw["metric_max"],
        metric_expected_center=raw.get("metric_expected_center", {}),
        notes=raw.get("notes", ""),
    )


def parse_segment_metric_target(raw: dict) -> SegmentMetricTarget:
    step_overrides = None
    if raw.get("step_overrides"):
        step_overrides = {
            k: StepConstraint(
                max_up=v["max_up"],
                max_down=v["max_down"],
            )
            for k, v in raw["step_overrides"].items()
        }

    return SegmentMetricTarget(
        segment_id=raw["segment_id"],
        section_id=raw["section_id"],
        snapshot=raw["snapshot"],
        rationale=raw.get("rationale", ""),
        step_overrides=step_overrides,
    )


class MetricValidator:
    def __init__(self, metric_schema: MetricSchemaV1) -> None:
        self.metric_schema = metric_schema

    def validate_target(
        self,
        target: SegmentMetricTarget,
        previous_snapshot: Optional[dict[str, int]] = None,
        section_envelope: Optional[SectionMetricEnvelope] = None,
    ) -> ValidationReport:
        issues: list[ValidationIssue] = []
        normalized = dict(target.snapshot)

        self._validate_metric_presence(normalized, issues)
        self._validate_range(normalized, issues)
        self._validate_step_size(normalized, previous_snapshot, target, issues)
        self._validate_section_envelope(normalized, section_envelope, issues)
        self._validate_consistency(normalized, issues)

        is_valid = not any(issue.level == "error" for issue in issues)
        return ValidationReport(
            is_valid=is_valid,
            issues=issues,
            normalized_snapshot=normalized,
        )

    def _validate_metric_presence(self, snapshot: dict[str, int], issues: list[ValidationIssue]) -> None:
        expected = set(self.metric_schema.metrics.keys())
        actual = set(snapshot.keys())

        for metric_name in sorted(expected - actual):
            issues.append(ValidationIssue(
                level="error",
                code="missing_metric",
                metric_name=metric_name,
                message=f"Missing required metric: {metric_name}",
            ))

        for metric_name in sorted(actual - expected):
            issues.append(ValidationIssue(
                level="error",
                code="unknown_metric",
                metric_name=metric_name,
                message=f"Unknown metric: {metric_name}",
            ))

    def _validate_range(self, snapshot: dict[str, int], issues: list[ValidationIssue]) -> None:
        for metric_name, value in snapshot.items():
            definition = self.metric_schema.metrics.get(metric_name)
            if not definition:
                continue

            lo = definition.allowed_range.min_value
            hi = definition.allowed_range.max_value

            if not isinstance(value, int):
                issues.append(ValidationIssue(
                    level="error",
                    code="non_integer_metric",
                    metric_name=metric_name,
                    message=f"{metric_name} must be integer, got {type(value).__name__}",
                ))
                continue

            if value < lo or value > hi:
                issues.append(ValidationIssue(
                    level="error",
                    code="out_of_range",
                    metric_name=metric_name,
                    message=f"{metric_name}={value} outside allowed range [{lo}, {hi}]",
                ))

    def _validate_step_size(
        self,
        snapshot: dict[str, int],
        previous_snapshot: Optional[dict[str, int]],
        target: SegmentMetricTarget,
        issues: list[ValidationIssue],
    ) -> None:
        if not previous_snapshot:
            return

        for metric_name, current_value in snapshot.items():
            if metric_name not in previous_snapshot:
                continue

            definition = self.metric_schema.metrics.get(metric_name)
            if not definition:
                continue

            prev = previous_snapshot[metric_name]
            delta = current_value - prev

            step = definition.default_step
            if target.step_overrides and metric_name in target.step_overrides:
                step = target.step_overrides[metric_name]

            if delta > step.max_up:
                issues.append(ValidationIssue(
                    level="error",
                    code="step_up_exceeded",
                    metric_name=metric_name,
                    message=f"{metric_name} increased by {delta}, exceeds max_up={step.max_up}",
                ))
            elif delta < -step.max_down:
                issues.append(ValidationIssue(
                    level="error",
                    code="step_down_exceeded",
                    metric_name=metric_name,
                    message=f"{metric_name} decreased by {abs(delta)}, exceeds max_down={step.max_down}",
                ))

    def _validate_section_envelope(
        self,
        snapshot: dict[str, int],
        envelope: Optional[SectionMetricEnvelope],
        issues: list[ValidationIssue],
    ) -> None:
        if not envelope:
            return

        for metric_name, value in snapshot.items():
            if metric_name not in envelope.metric_min or metric_name not in envelope.metric_max:
                continue

            lo = envelope.metric_min[metric_name]
            hi = envelope.metric_max[metric_name]
            if value < lo or value > hi:
                issues.append(ValidationIssue(
                    level="error",
                    code="section_envelope_violation",
                    metric_name=metric_name,
                    message=f"{metric_name}={value} outside section envelope [{lo}, {hi}]",
                ))

    def _validate_consistency(self, snapshot: dict[str, int], issues: list[ValidationIssue]) -> None:
        for rule in self.metric_schema.cross_metric_rules:
            p = rule.params

            if rule.rule_type == "max_gap":
                a = snapshot.get(p["metric_a"])
                b = snapshot.get(p["metric_b"])
                if a is None or b is None:
                    continue
                if abs(a - b) > p["max_abs_diff"]:
                    issues.append(ValidationIssue(
                        level="warning",
                        code="max_gap_exceeded",
                        metric_name=None,
                        message=f"{p['metric_a']} and {p['metric_b']} differ by more than {p['max_abs_diff']}",
                    ))

            elif rule.rule_type == "conditional_cap":
                cond = snapshot.get(p["if_metric"])
                target = snapshot.get(p["target_metric"])
                if cond is None or target is None:
                    continue
                if cond >= p["if_gte"] and target > p["max_value"]:
                    issues.append(ValidationIssue(
                        level="warning",
                        code="conditional_cap_violation",
                        metric_name=p["target_metric"],
                        message=(
                            f"{p['target_metric']}={target} exceeds max_value={p['max_value']} "
                            f"when {p['if_metric']}>={p['if_gte']}"
                        ),
                    ))

            elif rule.rule_type == "min_dependency":
                cond = snapshot.get(p["if_metric"])
                target = snapshot.get(p["target_metric"])
                if cond is None or target is None:
                    continue
                if cond >= p["if_gte"] and target < p["target_min"]:
                    issues.append(ValidationIssue(
                        level="warning",
                        code="min_dependency_violation",
                        metric_name=p["target_metric"],
                        message=(
                            f"{p['target_metric']}={target} below min={p['target_min']} "
                            f"when {p['if_metric']}>={p['if_gte']}"
                        ),
                    ))

            elif rule.rule_type == "soft_dependency":
                cond = snapshot.get(p["if_metric"])
                target = snapshot.get(p["target_metric"])
                if cond is None or target is None:
                    continue
                if cond >= p["if_gte"] and target < p["target_min"]:
                    issues.append(ValidationIssue(
                        level="warning",
                        code="soft_dependency_violation",
                        metric_name=p["target_metric"],
                        message=f"{p['target_metric']}={target} looks low given {p['if_metric']}={cond}",
                    ))