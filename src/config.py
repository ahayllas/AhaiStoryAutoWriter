from __future__ import annotations

from pathlib import Path

SRC_DIR = Path(__file__).resolve().parent
BASE_DIR = SRC_DIR.parent
PROMPTS_DIR = BASE_DIR / "prompts"
STATE_DIR = BASE_DIR / "state"
OUTPUT_DIR = BASE_DIR / "output"

STATE_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

LM_STUDIO_BASE_URL = "http://localhost:1234/v1"
LM_STUDIO_API_KEY = "lm-studio"
LM_STUDIO_TEMPERATURE = 0.7
LM_STUDIO_MAX_TOKENS = 16384

MODEL_PLANNER = "gemma-4"
MODEL_EXPANDER = "gemma-4"
MODEL_ANALYZER = "gemma-4"
MODEL_WRITER = "gemma-4"
MODEL_SECTION_ARCHITECT = MODEL_EXPANDER

DEFAULT_LANGUAGE_HINT = "Traditional Chinese"
DEFAULT_TARGET_TOTAL_WORDS = 40000
DEFAULT_SEGMENT_WORDS = 3000
DEFAULT_RECENT_EXCERPT_CHARS = 8000

PLANNER_SYSTEM_PATH = PROMPTS_DIR / "planner_system_prompt.txt"
PLANNER_USER_TEMPLATE_PATH = PROMPTS_DIR / "planner_user_template.txt"

PLANNER_CONCEPT_SYSTEM_PATH = PROMPTS_DIR / "planner_concept_system_prompt.txt"
PLANNER_CONCEPT_USER_TEMPLATE_PATH = PROMPTS_DIR / "planner_concept_user_template.txt"

PLANNER_BIBLE_SYSTEM_PATH = PROMPTS_DIR / "planner_bible_system_prompt.txt"
PLANNER_BIBLE_USER_TEMPLATE_PATH = PROMPTS_DIR / "planner_bible_user_template.txt"

PLANNER_SECTIONS_SYSTEM_PATH = PROMPTS_DIR / "planner_sections_system_prompt.txt"
PLANNER_SECTIONS_USER_TEMPLATE_PATH = PROMPTS_DIR / "planner_sections_user_template.txt"

EXPANDER_SYSTEM_PATH = PROMPTS_DIR / "expander_system_prompt.txt"
EXPANDER_USER_TEMPLATE_PATH = PROMPTS_DIR / "expander_user_template.txt"

ANALYZER_SYSTEM_PATH = PROMPTS_DIR / "analyzer_system_prompt.txt"
ANALYZER_USER_TEMPLATE_PATH = PROMPTS_DIR / "analyzer_user_template.txt"

WRITER_SYSTEM_PATH = PROMPTS_DIR / "writer_system_prompt.txt"
WRITER_USER_TEMPLATE_PATH = PROMPTS_DIR / "writer_user_template.txt"

SECTION_ARCHITECT_SYSTEM_PATH = PROMPTS_DIR / "section_architect_system_prompt.txt"
SECTION_ARCHITECT_USER_TEMPLATE_PATH = PROMPTS_DIR / "section_architect_user_template.txt"

PROJECT_META_PATH = STATE_DIR / "project_meta.json"
METRIC_SCHEMA_PATH = BASE_DIR / "metric_schema_v1.json"

STORY_CONCEPT_PATH = STATE_DIR / "story_concept.json"
STORY_BIBLE_PATH = STATE_DIR / "story_bible.json"
SECTION_DRAFT_PATH = STATE_DIR / "section_draft.json"

STORY_PLAN_PATH = STATE_DIR / "story_plan.json"
SECTION_INDEX_PATH = STATE_DIR / "section_index.json"

SEGMENT_QUEUE_PATH = STATE_DIR / "segment_queue.json"
ACTIVE_SEGMENT_PATH = STATE_DIR / "active_segment.json"
COMPLETED_SEGMENTS_PATH = STATE_DIR / "completed_segments.json"

CURRENT_SECTION_PLAN_PATH = STATE_DIR / "current_section_plan.json"

CURRENT_SEGMENT_PLAN_PATH = STATE_DIR / "current_segment_plan.json"
CURRENT_RECONCILED_SEGMENT_PLAN_PATH = STATE_DIR / "current_reconciled_segment_plan.json"
CURRENT_SITUATION_BRIEF_PATH = STATE_DIR / "current_situation_brief.json"
CURRENT_STORY_STATE_PATH = STATE_DIR / "current_story_state.json"
CURRENT_FACT_BRIEF_PATH = STATE_DIR / "current_fact_brief.json"
CURRENT_STATE_UPDATE_PATH = STATE_DIR / "current_state_update.json"
REVEAL_GUARD_PACKAGE_PATH = STATE_DIR / "reveal_guard_package.json"
LAST_VALIDATION_REPORT_PATH = STATE_DIR / "last_validation_report.json"

CURRENT_SECTION_STATUS_PATH = STATE_DIR / "current_section_status.json"

PROJECT_STATUS_PATH = STATE_DIR / "project_status.json"
VALIDATION_REPORTS_DIR = STATE_DIR / "validation_reports"
METRICS_HISTORY_PATH = STATE_DIR / "metrics_history.jsonl"

MANUSCRIPT_PATH = OUTPUT_DIR / "manuscript.md"
SEGMENTS_DIR = OUTPUT_DIR / "segments"
SEGMENT_LOGS_DIR = OUTPUT_DIR / "segment_logs"

VALIDATION_REPORTS_DIR.mkdir(parents=True, exist_ok=True)
SEGMENTS_DIR.mkdir(parents=True, exist_ok=True)
SEGMENT_LOGS_DIR.mkdir(parents=True, exist_ok=True)