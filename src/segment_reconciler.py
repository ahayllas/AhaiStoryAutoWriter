from __future__ import annotations

from config import (
    CURRENT_RECONCILED_SEGMENT_PLAN_PATH,
    CURRENT_SEGMENT_PLAN_PATH,
    LAST_VALIDATION_REPORT_PATH,
)
from io_contract import load_json, save_json


class SegmentReconciler:
    """
    MVP:
    - if validation has only warnings, pass through
    - if validation has errors, annotate plan with reconciliation notes
    - does not auto-rewrite metrics yet
    """

    def reconcile(self) -> dict:
        plan = load_json(CURRENT_SEGMENT_PLAN_PATH, {})
        validation = load_json(LAST_VALIDATION_REPORT_PATH, {})

        if not plan:
            raise RuntimeError("Missing current segment plan.")

        issues = validation.get("issues", [])
        errors = [x for x in issues if x.get("level") == "error"]
        warnings = [x for x in issues if x.get("level") == "warning"]

        reconciled = dict(plan)
        reconciled["reconciliation"] = {
            "has_errors": bool(errors),
            "has_warnings": bool(warnings),
            "error_messages": [x.get("message", "") for x in errors],
            "warning_messages": [x.get("message", "") for x in warnings],
            "writer_instruction": (
                "Follow all original constraints carefully."
                if not errors else
                "Original metric target has validation errors. Keep narrative intent, but avoid extreme executions and prefer conservative interpretation."
            )
        }

        save_json(CURRENT_RECONCILED_SEGMENT_PLAN_PATH, reconciled)
        return reconciled