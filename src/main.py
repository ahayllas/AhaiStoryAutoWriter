from __future__ import annotations

import argparse
import uuid

from config import (
    ACTIVE_SEGMENT_PATH,
    COMPLETED_SEGMENTS_PATH,
    CURRENT_FACT_BRIEF_PATH,
    CURRENT_RECONCILED_SEGMENT_PLAN_PATH,
    CURRENT_SECTION_STATUS_PATH,
    CURRENT_SEGMENT_PLAN_PATH,
    CURRENT_SITUATION_BRIEF_PATH,
    CURRENT_STATE_UPDATE_PATH,
    CURRENT_STORY_STATE_PATH,
    DEFAULT_LANGUAGE_HINT,
    DEFAULT_SEGMENT_WORDS,
    DEFAULT_TARGET_TOTAL_WORDS,
    LAST_VALIDATION_REPORT_PATH,
    MANUSCRIPT_PATH,
    METRIC_SCHEMA_PATH,
    PROJECT_META_PATH,
    PROJECT_STATUS_PATH,
    REVEAL_GUARD_PACKAGE_PATH,
    SECTION_INDEX_PATH,
    SEGMENT_QUEUE_PATH,
    STORY_PLAN_PATH,
    CURRENT_SECTION_PLAN_PATH,
    STORY_CONCEPT_PATH,
    STORY_BIBLE_PATH,
    SECTION_DRAFT_PATH,
)
from cycle_manager import CycleManager
from io_contract import load_json, load_text, save_json, save_text
from llm_client import LLMClient
from metric_validator import (
    MetricValidator,
    parse_metric_schema,
    parse_section_envelope,
    parse_segment_metric_target,
)
from queue_manager import QueueManager
from reveal_guard_builder import RevealGuardBuilder
from schemas import ProjectMeta
from section_expander import SectionExpander, SectionPlanExhaustedError
from section_planner import SectionPlanner
from segment_reconciler import SegmentReconciler
from situation_analyzer import SituationAnalyzer
from state_manager import StateManager
from story_planner import StoryPlanner
from utils import count_words_approx, infer_phase_by_progress, read_jsonl
from segment_writer import SegmentWriter

LANGUAGE_ENFORCEMENT_TEMPLATE = """STRICT LANGUAGE COMPLIANCE RULE (HIGHEST PRIORITY)

The system messages are in English only to give clear instructions.
However, EVERYTHING you generate for the story MUST be written in the exact language specified below:

Target Language: {language_hint}

Rules:
1. Produce the entire output in the target language only.
2. This applies to all text: narration, dialogue, thoughts, descriptions, and terminology.

Failure to follow this rule will cause the generated content to be rejected.
"""

def get_language_enforcement_prompt() -> str:
    """從 project_meta 讀取 language_hint 並生成語言強制提示"""
    meta_raw = load_json(PROJECT_META_PATH, {})
    language_hint = meta_raw.get("language_hint", "中文").strip()

    return LANGUAGE_ENFORCEMENT_TEMPLATE.format(language_hint=language_hint) 
    

def init_project(title: str, premise: str, target_total_words: int, language_hint: str) -> None:
    project_id = uuid.uuid4().hex[:12]

    meta = ProjectMeta(
        project_id=project_id,
        title=title,
        premise=premise,
        language_hint=language_hint,
        target_total_words=target_total_words,
        default_segment_words=DEFAULT_SEGMENT_WORDS,
    )

    save_json(PROJECT_META_PATH, meta)
    save_json(STORY_CONCEPT_PATH, {})
    save_json(STORY_BIBLE_PATH, {})
    save_json(SECTION_DRAFT_PATH, {})
    save_json(STORY_PLAN_PATH, {})
    save_json(SECTION_INDEX_PATH, [])
    save_json(SEGMENT_QUEUE_PATH, {"items": []})
    save_json(ACTIVE_SEGMENT_PATH, {"active": False, "item": None})
    save_json(COMPLETED_SEGMENTS_PATH, {"items": []})
    save_json(CURRENT_SEGMENT_PLAN_PATH, {})
    save_json(CURRENT_RECONCILED_SEGMENT_PLAN_PATH, {})
    save_json(CURRENT_SECTION_PLAN_PATH, {})
    save_json(CURRENT_SECTION_STATUS_PATH, {})
    save_json(CURRENT_SITUATION_BRIEF_PATH, {})
    save_json(CURRENT_STORY_STATE_PATH, {
        "known_facts": [],
        "active_threads": [],
        "character_positions": {},
        "recent_consequences": [],
    })
    save_json(CURRENT_FACT_BRIEF_PATH, {
        "known_facts": [],
        "active_threads": [],
        "character_positions": {},
        "unresolved_questions": [],
        "recent_consequences": [],
    })
    save_json(CURRENT_STATE_UPDATE_PATH, {})
    save_json(REVEAL_GUARD_PACKAGE_PATH, {})
    save_json(LAST_VALIDATION_REPORT_PATH, {})
    save_json(PROJECT_STATUS_PATH, {
        "completed": False,
        "story_completed": False,
        "target_total_words": target_total_words,
    })
    save_text(MANUSCRIPT_PATH, "")

    print("Project initialized.")
    print(f"project_id={project_id}")
    print(f"metric_schema expected at: {METRIC_SCHEMA_PATH}")


def run_story_planner() -> None:
    meta_raw = load_json(PROJECT_META_PATH, {})
    if not meta_raw:
        raise RuntimeError("Missing project meta. Run init first.")

    metric_schema = load_json(METRIC_SCHEMA_PATH, {})
    if not metric_schema:
        raise RuntimeError("Missing metric_schema_v1.json")

    client = LLMClient()
    planner = StoryPlanner(client)
    plan = planner.run(meta=ProjectMeta(**meta_raw), metric_schema=metric_schema)

    print("Story planner completed.")
    print(f"arcs={len(plan.get('arcs', []))}")
    print(f"sections={len(plan.get('sections', []))}")
    print(f"queue_items={len(plan.get('segment_queue', []))}")


def build_reveal_guard() -> None:
    package = RevealGuardBuilder().build()
    print("Reveal guard built.")
    print(f"segment_id={package.get('segment_id')}")


def reconcile_segment() -> None:
    reconciled = SegmentReconciler().reconcile()
    print("Segment reconciled.")
    print(f"segment_id={reconciled.get('segment_id')}")


def analyze_situation() -> None:
    metric_schema = load_json(METRIC_SCHEMA_PATH, {})
    if not metric_schema:
        raise RuntimeError("Missing metric schema.")

    client = LLMClient()
    analyzer = SituationAnalyzer(client)
    brief = analyzer.run(metric_schema=metric_schema)
    print("Situation analyzed.")
    print(f"segment_id={brief.get('segment_id')}")


def expand_next() -> None:
    metric_schema = load_json(METRIC_SCHEMA_PATH, {})
    if not metric_schema:
        raise RuntimeError("Missing metric schema.")

    client = LLMClient()
    qm = QueueManager()
    planner = SectionPlanner()

    active_section = planner.get_or_create_active_section()
    if not active_section:
        print("No active section available.")
        return

    section_plan = planner.ensure_section_plan(
        llm_client=client,
        metric_schema=metric_schema,
    )
    if not section_plan:
        print("Failed to build section plan.")
        return

    queue_item = qm.get_active_item()
    if not queue_item:
        queue_item = qm.get_next_pending_item()
        if queue_item:
            queue_item = qm.activate_item(queue_item)

    if not queue_item:
        queue_item = planner.build_next_queue_item()
        if queue_item:
            qm.enqueue_item(queue_item)
            queue_item = qm.activate_item(queue_item) or queue_item

    if not queue_item:
        print("No queue item available.")
        return

    try:
        expanded = SectionExpander(client).run(
            queue_item=queue_item,
            metric_schema=metric_schema,
        )
    except SectionPlanExhaustedError as exc:
        print(f"[WARN] {exc}")
        print("[WARN] Section plan exhausted. Marking current section as completed by fallback.")
        finalize_current_section_as_completed("blueprints_exhausted_fallback")
        return

    print("Expanded next segment.")
    print(f"segment_id={expanded.get('segment_id')}")


def validate_segment() -> None:
    metric_schema_raw = load_json(METRIC_SCHEMA_PATH, {})
    segment_plan = load_json(CURRENT_SEGMENT_PLAN_PATH, {})
    if not metric_schema_raw or not segment_plan:
        raise RuntimeError("Missing metric schema or current segment plan.")

    schema = parse_metric_schema(metric_schema_raw)
    validator = MetricValidator(schema)
    target = parse_segment_metric_target(segment_plan["metric_target"])

    story_plan = load_json(STORY_PLAN_PATH, {})
    envelope_raw = None
    for section in story_plan.get("sections", []):
        if section.get("section_id") == segment_plan.get("section_id"):
            envelope_raw = section.get("metric_envelope")
            break
    envelope = parse_section_envelope(envelope_raw) if envelope_raw else None

    rows = read_jsonl(PROJECT_STATUS_PATH.parent / "metrics_history.jsonl")
    previous_snapshot = rows[-1]["target_metrics"] if rows else None

    report = validator.validate_target(
        target=target,
        previous_snapshot=previous_snapshot,
        section_envelope=envelope,
    )

    payload = {
        "is_valid": report.is_valid,
        "issues": [
            {
                "level": x.level,
                "code": x.code,
                "metric_name": x.metric_name,
                "message": x.message,
            }
            for x in report.issues
        ],
        "normalized_snapshot": report.normalized_snapshot,
    }
    save_json(LAST_VALIDATION_REPORT_PATH, payload)

    print("Validation complete.")
    print(f"is_valid={report.is_valid}")
    print(f"issues={len(report.issues)}")


def apply_state_update() -> None:
    state_update_payload = load_json(CURRENT_STATE_UPDATE_PATH, {})
    raw_text = state_update_payload.get("raw_state_update_text", "")
    sm = StateManager()
    patch = sm.parse_state_update_text(raw_text)
    result = sm.apply_patch(patch)
    print("State updated.")
    print(f"known_facts={len(result['story_state'].get('known_facts', []))}")
    print(f"active_threads={len(result['story_state'].get('active_threads', []))}")


def run_cycle() -> None:
    metric_schema = load_json(METRIC_SCHEMA_PATH, {})
    if not metric_schema:
        raise RuntimeError("Missing metric schema.")

    meta = load_json(PROJECT_META_PATH, {})
    default_segment_words = meta.get("default_segment_words", DEFAULT_SEGMENT_WORDS)

    client = LLMClient()

    queue_manager = QueueManager()
    section_expander = SectionExpander(client)
    situation_analyzer = SituationAnalyzer(client)
    state_manager = StateManager()
    writer = SegmentWriter(client, default_segment_words=default_segment_words)

    cycle_manager = CycleManager(
        queue_manager=queue_manager,
        section_expander=section_expander,
        situation_analyzer=situation_analyzer,
        state_manager=state_manager,
        writer=writer,
    )

    result = cycle_manager.run_cycle(metric_schema=metric_schema)

    print("Cycle finished.")
    for k, v in result.items():
        print(f"{k}={v}")

def finalize_current_section_as_completed(reason: str) -> None:
    section_status = load_json(CURRENT_SECTION_STATUS_PATH, {})
    if not section_status:
        return

    section_status["section_complete"] = True
    section_status["completion_reason"] = reason
    section_status["completion_source"] = "section_plan_exhausted_fallback"


    save_json(CURRENT_SECTION_STATUS_PATH, section_status)

    # Clear active queue item so the next call can move on
    save_json(ACTIVE_SEGMENT_PATH, {"active": False, "item": None})


def show_status() -> None:
    meta = load_json(PROJECT_META_PATH, {})
    manuscript = load_text(MANUSCRIPT_PATH, "")
    queue = load_json(SEGMENT_QUEUE_PATH, {"items": []})
    completed = load_json(COMPLETED_SEGMENTS_PATH, {"items": []})
    active = load_json(ACTIVE_SEGMENT_PATH, {"active": False, "item": None})
    section_status = load_json(CURRENT_SECTION_STATUS_PATH, {})
    project_status = load_json(PROJECT_STATUS_PATH, {})
    current_words = count_words_approx(manuscript)
    target = int(meta.get("target_total_words", DEFAULT_TARGET_TOTAL_WORDS)) if meta else DEFAULT_TARGET_TOTAL_WORDS
    progress = 0.0 if target <= 0 else current_words / target

    print("Status")
    print("------")
    print(f"meta_exists={bool(meta)}")
    print(f"story_plan_exists={bool(load_json(STORY_PLAN_PATH, {}))}")
    print(f"queue_items={len(queue.get('items', []))}")
    print(f"completed_segments={len(completed.get('items', []))}")
    print(f"active_segment={active.get('item', {}).get('segment_id') if active.get('item') else None}")
    print(f"active_section={section_status.get('section_id')}")
    print(f"section_complete={section_status.get('section_complete')}")
    print(f"project_completed={project_status.get('completed')}")
    print(f"story_completed={project_status.get('story_completed')}")
    print(f"current_segment_plan_exists={bool(load_json(CURRENT_SEGMENT_PLAN_PATH, {}))}")
    print(f"current_situation_brief_exists={bool(load_json(CURRENT_SITUATION_BRIEF_PATH, {}))}")
    print(f"manuscript_words_approx={current_words}")
    print(f"target_total_words={target}")
    print(f"progress={progress * 100:.2f}%")
    print(f"phase={infer_phase_by_progress(progress)}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Long-form fiction pipeline v2")
    sub = parser.add_subparsers(dest="cmd")

    p_init = sub.add_parser("init")
    p_init.add_argument("--title", required=True)
    p_init.add_argument("--premise", required=True)
    p_init.add_argument("--target", type=int, default=DEFAULT_TARGET_TOTAL_WORDS)
    p_init.add_argument("--lang", default=DEFAULT_LANGUAGE_HINT)

    sub.add_parser("plan_story")
    sub.add_parser("expand_next")
    sub.add_parser("validate_segment")
    sub.add_parser("build_reveal_guard")
    sub.add_parser("reconcile_segment")
    sub.add_parser("analyze_situation")
    sub.add_parser("apply_state_update")
    sub.add_parser("run_cycle")
    sub.add_parser("show_status")

    args = parser.parse_args()

    if args.cmd == "init":
        init_project(args.title, args.premise, args.target, args.lang)
    elif args.cmd == "plan_story":
        run_story_planner()
    elif args.cmd == "expand_next":
        expand_next()
    elif args.cmd == "validate_segment":
        validate_segment()
    elif args.cmd == "build_reveal_guard":
        build_reveal_guard()
    elif args.cmd == "reconcile_segment":
        reconcile_segment()
    elif args.cmd == "analyze_situation":
        analyze_situation()
    elif args.cmd == "apply_state_update":
        apply_state_update()
    elif args.cmd == "run_cycle":
        run_cycle()
    elif args.cmd == "show_status":
        show_status()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()