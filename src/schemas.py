from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class ProjectMeta:
    project_id: str
    title: str
    premise: str
    language_hint: str
    target_total_words: int
    default_segment_words: int = 2500
    planner_model: str = "gemma-4"
    expander_model: str = "gemma-4"
    analyzer_model: str = "gemma-4"
    writer_model: str = "gemma-4"


@dataclass
class MetricRange:
    min_value: int
    max_value: int


@dataclass
class StepConstraint:
    max_up: int
    max_down: int


@dataclass
class MetricDefinition:
    name: str
    description: str
    allowed_range: MetricRange
    default_step: StepConstraint
    monotonic_bias: Optional[str] = None


@dataclass
class CrossMetricRule:
    rule_id: str
    description: str
    rule_type: str
    params: dict[str, Any]


@dataclass
class MetricSchemaV1:
    version: str
    metrics: dict[str, MetricDefinition]
    cross_metric_rules: list[CrossMetricRule] = field(default_factory=list)


@dataclass
class SectionMetricEnvelope:
    section_id: str
    label: str
    metric_min: dict[str, int]
    metric_max: dict[str, int]
    metric_expected_center: dict[str, int]
    notes: str = ""


@dataclass
class SegmentMetricTarget:
    segment_id: str
    section_id: str
    snapshot: dict[str, int]
    rationale: str = ""
    step_overrides: Optional[dict[str, StepConstraint]] = None


@dataclass
class ValidationIssue:
    level: str
    code: str
    metric_name: Optional[str]
    message: str


@dataclass
class ValidationReport:
    is_valid: bool
    issues: list[ValidationIssue]
    normalized_snapshot: dict[str, int]


@dataclass
class WriterOutput:
    segment_id: str
    writing_plan: str
    narrative_prose: str
    state_update: str
    self_reported_actual_metrics: Optional[dict[str, int]] = None