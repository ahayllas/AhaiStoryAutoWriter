from __future__ import annotations

import argparse
import shutil
import uuid
from pathlib import Path

import subprocess
from shutil import which

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
    SEGMENTS_DIR,
    SEGMENT_LOGS_DIR,
    SECTIONS_DIR,
    BACKUP_DIR,
    BACKUP_STATE_DIR,
    BACKUP_OUTPUT_DIR,
    STATE_DIR,
    OUTPUT_DIR,
    
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
from metricize import StoryPlanMetricizeOrchestrator
from section_entry_planner import SectionEntryPlanner
from section_entry_writer import SectionEntryWriter
from section_output_manager import (
    assemble_section as assemble_section_text,
    rebuild_manuscript as rebuild_manuscript_text,
    rebuild_manuscript_fancy as rebuild_manuscript_fancy_text,
)
from section_proofreader import SectionProofreader


def _reset_output_dir(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)

def backup_project_state() -> None:
    """
    Create a simple backup of STATE_DIR and OUTPUT_DIR.
    Only keep the latest backup.
    """
    print("Creating backup...")

    # Remove old backup
    if BACKUP_STATE_DIR.exists():
        shutil.rmtree(BACKUP_STATE_DIR)
    if BACKUP_OUTPUT_DIR.exists():
        shutil.rmtree(BACKUP_OUTPUT_DIR)

    # Copy fresh snapshot
    shutil.copytree(STATE_DIR, BACKUP_STATE_DIR)
    shutil.copytree(OUTPUT_DIR, BACKUP_OUTPUT_DIR)

    print("Backup completed.")


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

    _reset_output_dir(SEGMENTS_DIR)
    _reset_output_dir(SEGMENT_LOGS_DIR)
    _reset_output_dir(SECTIONS_DIR)

    save_text(MANUSCRIPT_PATH, "")

    print("Project initialized.")
    print(f"project_id={project_id}")
    print(f"metric_schema expected at: {METRIC_SCHEMA_PATH}")


def restore_project_state() -> None:
    """
    Restore STATE_DIR and OUTPUT_DIR from latest backup.
    """
    if not BACKUP_STATE_DIR.exists() or not BACKUP_OUTPUT_DIR.exists():
        raise RuntimeError("No backup found to restore.")

    print("Restoring from backup...")

    # Clear current dirs
    if STATE_DIR.exists():
        shutil.rmtree(STATE_DIR)
    if OUTPUT_DIR.exists():
        shutil.rmtree(OUTPUT_DIR)

    # Restore
    shutil.copytree(BACKUP_STATE_DIR, STATE_DIR)
    shutil.copytree(BACKUP_OUTPUT_DIR, OUTPUT_DIR)

    print("Restore completed.")


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

def metricize_story_plan(
    auto_schema: bool = False,
    use_ai_envelope: bool = False,
    repair: bool = False,
    apply_repair: bool = False,
    repair_top_n: int = 2,
    overwrite_schema: bool = False,
    skip_envelope: bool = False,
) -> None:
    need_llm = auto_schema or use_ai_envelope or repair
    client = LLMClient() if need_llm else None

    orchestrator = StoryPlanMetricizeOrchestrator(client)
    plan = orchestrator.run(
        auto_schema=auto_schema,
        use_ai_envelope=use_ai_envelope,
        repair=repair,
        apply_repair=apply_repair,
        repair_top_n=repair_top_n,
        overwrite_schema=overwrite_schema,
        skip_envelope=skip_envelope,
    )

    metrics = plan.get("metric_schema", {}).get("metrics", {})
    sections = plan.get("sections", [])
    metricized_sections = [
        s for s in sections
        if s.get("metric_envelope")
    ]
    analysis_summary = plan.get("metric_analysis_summary", {})
    repair_summary = plan.get("metric_repair_summary", {})

    print("Story plan metricized.")
    print(f"metrics={len(metrics)}")
    print(f"sections={len(sections)}")
    print(f"metricized_sections={len(metricized_sections)}")
    print(f"issues={analysis_summary.get('summary', {}).get('issue_count')}")
    print(f"repair_enabled={repair}")
    print(f"repair_top_n={repair_top_n}")
    print(f"repair_needed={repair_summary.get('repair_needed') if repair_summary else None}")
    print(f"repair_applied={apply_repair}")

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
    backup_project_state()
    metric_schema = load_json(METRIC_SCHEMA_PATH, {})
    if not metric_schema:
        raise RuntimeError("Missing metric schema.")

    meta = load_json(PROJECT_META_PATH, {})
    default_segment_words = meta.get("default_segment_words", DEFAULT_SEGMENT_WORDS)

    client = LLMClient()
    
    section_proofreader = SectionProofreader(
        llm_client=client,
        auto_accept=True,
    )

    queue_manager = QueueManager()
    section_expander = SectionExpander(client)
    situation_analyzer = SituationAnalyzer(client)
    state_manager = StateManager()

    section_entry_planner = SectionEntryPlanner(
        llm_client=client,
        state_manager=state_manager,
    )
    section_entry_writer = SectionEntryWriter(
        llm_client=client,
    )

    writer = SegmentWriter(client, default_segment_words=default_segment_words)

    cycle_manager = CycleManager(
        queue_manager=queue_manager,
        section_expander=section_expander,
        situation_analyzer=situation_analyzer,
        state_manager=state_manager,
        writer=writer,
        section_entry_planner=section_entry_planner,
        section_entry_writer=section_entry_writer,
        section_proofreader=section_proofreader,
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

def assemble_section_artifact(section_id: str | None = None) -> None:
    if not section_id:
        section_status = load_json(CURRENT_SECTION_STATUS_PATH, {})
        section_id = section_status.get("section_id")

    if not section_id:
        raise RuntimeError("Missing section_id. Pass --section-id or ensure current section exists.")

    text = assemble_section_text(section_id)
    print("Section assembled.")
    print(f"section_id={section_id}")
    print(f"words={count_words_approx(text)}")


def rebuild_manuscript_artifact() -> None:
    manuscript = rebuild_manuscript_text()
    print("Manuscript rebuilt.")
    print(f"words={count_words_approx(manuscript)}")

def rebuild_manuscript_fancy_artifact() -> None:
    manuscript = rebuild_manuscript_fancy_text()
    print("Manuscript rebuilt in fancy format.")
    print(f"words={count_words_approx(manuscript)}")


def proofread_section(section_id: str | None = None, auto_accept: bool = False) -> None:
    client = LLMClient()
    proofreader = SectionProofreader(client, auto_accept=auto_accept)
    result = proofreader.run(section_id=section_id)
    print("Section proofread completed.")
    print(f"section_id={result.get('section_id')}")
    print(f"accepted={result.get('accepted')}")
    print(f"acceptance_reason={result.get('acceptance_reason')}")
    print(f"diff_file={result.get('diff_file')}")
    print(f"proofread_file={result.get('proofread_file')}")
    
    
def accept_proofread_section(section_id: str | None = None) -> None:
    section_status = load_json(CURRENT_SECTION_STATUS_PATH, {})
    if not section_id:
        section_id = section_status.get("section_id")

    if not section_id:
        raise RuntimeError("Missing section_id.")

    section_dir = SECTIONS_DIR / section_id
    proofread_path = section_dir / "proofread.md"
    final_path = section_dir / "final.md"

    if not proofread_path.exists():
        raise RuntimeError(f"Proofread file not found: {proofread_path}")

    text = load_text(proofread_path, "")
    save_text(final_path, text)

    rebuilt = rebuild_manuscript_text()

    index_path = section_dir / "index.json"
    index_payload = load_json(index_path, {})
    index_payload["proofreading_status"] = "accepted"
    index_payload["final_file"] = "final.md"
    save_json(index_path, index_payload)

    refreshed_status = load_json(CURRENT_SECTION_STATUS_PATH, {})
    if refreshed_status.get("section_id") == section_id:
        refreshed_status["section_proofreading_completed"] = True
        refreshed_status["section_proofreading_auto_accepted"] = False
        refreshed_status["section_proofreading_required"] = False
        refreshed_status["section_proofreading_acceptance_reason"] = "manually_accepted"
        save_json(CURRENT_SECTION_STATUS_PATH, refreshed_status)

    print("Proofread section accepted.")
    print(f"section_id={section_id}")
    print(f"manuscript_words={count_words_approx(rebuilt)}")
    
    
def export_pdf_artifact(
    input_path: str | None = None,
    output_path: str | None = None,
    pdf_engine: str = "xelatex",
    mainfont: str | None = None,
) -> None:
    md_path = Path(input_path) if input_path else MANUSCRIPT_PATH
    pdf_path = Path(output_path) if output_path else MANUSCRIPT_PATH.with_suffix(".pdf")

    if not md_path.exists():
        raise RuntimeError(f"Markdown source not found: {md_path}")

    pandoc_path = which("pandoc")
    if not pandoc_path:
        raise RuntimeError(
            "pandoc not found in PATH. Please install pandoc first, then try again."
        )

    cmd = [
        pandoc_path,
        str(md_path),
        "-s",
        "-o",
        str(pdf_path),
        f"--pdf-engine={pdf_engine}",
    ]

    if mainfont:
        cmd.extend(["-V", f"mainfont={mainfont}"])

    subprocess.run(cmd, check=True)

    print("PDF exported.")
    print(f"input={md_path}")
    print(f"output={pdf_path}")
    print(f"pdf_engine={pdf_engine}")
    print(f"mainfont={mainfont}")
    

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
    
    section_output_dirs = len([p for p in SECTIONS_DIR.iterdir() if p.is_dir()]) if SECTIONS_DIR.exists() else 0
    print(f"section_output_dirs={section_output_dirs}")
    
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
    sub.add_parser("rebuild_manuscript")
    sub.add_parser("rebuild_manuscript_fancy")
    p_export_pdf = sub.add_parser("export_pdf")
    p_export_pdf.add_argument("--input", default=None, help="Input markdown file path.")
    p_export_pdf.add_argument("--output", default=None, help="Output PDF file path.")
    p_export_pdf.add_argument(
        "--pdf-engine",
        default="xelatex",
        help="Pandoc PDF engine, e.g. xelatex, lualatex, pdflatex.",
    )
    p_export_pdf.add_argument(
        "--mainfont",
        default=None,
        help="Main font for PDF output, useful for Chinese text.",
    )
    sub.add_parser("restore_backup")

    p_assemble_section = sub.add_parser("assemble_section")
    p_assemble_section.add_argument("--section-id", default=None)
    
    p_proofread_section = sub.add_parser("proofread_section")
    p_proofread_section.add_argument("--section-id", default=None)
    p_proofread_section.add_argument("--auto-accept", action="store_true")
    
    p_accept_proofread = sub.add_parser("accept_proofread_section")
    p_accept_proofread.add_argument("--section-id", default=None)
    
    p_metricize = sub.add_parser("metricize_story_plan")
    p_metricize.add_argument(
        "--auto-schema",
        action="store_true",
        help="Use LLM to refine the Python-generated metric schema.",
    )
    p_metricize.add_argument(
        "--ai-envelope",
        action="store_true",
        help="Use LLM to assign section metric envelopes. Otherwise use Python fallback.",
    )
    p_metricize.add_argument(
        "--repair",
        action="store_true",
        help="Use LLM to suggest repairs for top problematic transitions only.",
    )
    p_metricize.add_argument(
        "--apply-repair",
        action="store_true",
        help="Apply safe repair patches. Inserted sections are stored as pending only.",
    )
    p_metricize.add_argument(
        "--repair-top-n",
        type=int,
        default=2,
        help="Number of problematic transitions to send to repair LLM.",
    )
    p_metricize.add_argument(
        "--overwrite-schema",
        action="store_true",
        help="Regenerate metric_schema_v1.json even if it already exists.",
    )
    p_metricize.add_argument(
        "--skip-envelope",
        action="store_true",
        help="Skip envelope assignment and only analyze existing section metric_envelopes.",
    )
    
    args = parser.parse_args()

    if args.cmd == "init":
        init_project(args.title, args.premise, args.target, args.lang)
    elif args.cmd == "plan_story":
        run_story_planner()
    elif args.cmd == "metricize_story_plan":
        metricize_story_plan(
            auto_schema=args.auto_schema,
            use_ai_envelope=args.ai_envelope,
            repair=args.repair,
            apply_repair=args.apply_repair,
            repair_top_n=args.repair_top_n,
            overwrite_schema=args.overwrite_schema,
            skip_envelope=args.skip_envelope,
        )
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
    elif args.cmd == "assemble_section":
        assemble_section_artifact(section_id=args.section_id)
    elif args.cmd == "rebuild_manuscript":
        rebuild_manuscript_artifact()
    elif args.cmd == "rebuild_manuscript_fancy":
        rebuild_manuscript_fancy_artifact()    
    elif args.cmd == "proofread_section":
        proofread_section(section_id=args.section_id, auto_accept=args.auto_accept)
    elif args.cmd == "accept_proofread_section":
        accept_proofread_section(section_id=args.section_id)   
    elif args.cmd == "restore_backup":
        restore_project_state()
    elif args.cmd == "export_pdf":
        export_pdf_artifact(
            input_path=args.input,
            output_path=args.output,
            pdf_engine=args.pdf_engine,
            mainfont=args.mainfont,
        )
    else:
        parser.print_help()


if __name__ == "__main__":
    main()