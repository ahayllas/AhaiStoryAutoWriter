from __future__ import annotations

from pathlib import Path

# please refer to model_profiles.py about the model profile definition
MODEL_PLANNER = "deepseekv4_flash_OR"
MODEL_CREATIVE = "gemma-local"
MODEL_METRICIZE = "gemma-local"
MODEL_EXPANDER = "deepseekv4_flash_OR"
MODEL_ANALYZER = "gemma-local"
MODEL_WRITER = "gemma-local"
MODEL_PROOFREADER = "gpt_5_4_mini_POE"
MODEL_SECTION_ARCHITECT = "deepseekv4_flash_OR"

# ==============
JSON_REPAIR_MAX_RETRIES = 3


DEFAULT_CREATIVE_SELECTED_WORDS = 50
DEFAULT_CREATIVE_RANDOM_POOL_SIZE = DEFAULT_CREATIVE_SELECTED_WORDS # == DEFAULT_CREATIVE_SELECTED_WORDS value means "full random mode"
DEFAULT_CREATIVE_SITUATION_COUNT = 6


DEFAULT_LANGUAGE_HINT = "Traditional Chinese"
DEFAULT_TARGET_TOTAL_WORDS = 40000
DEFAULT_SEGMENT_WORDS = 3000
DEFAULT_RECENT_EXCERPT_CHARS = 8000



SRC_DIR = Path(__file__).resolve().parent
BASE_DIR = SRC_DIR.parent
PROMPTS_DIR = BASE_DIR / "prompts"
METRICIZE_DIR = BASE_DIR / "metricize"
STATE_DIR = BASE_DIR / "state"
OUTPUT_DIR = BASE_DIR / "output"

BACKUP_DIR = BASE_DIR / "backup"
BACKUP_STATE_DIR = BACKUP_DIR / "state"
BACKUP_OUTPUT_DIR = BACKUP_DIR / "output"

STATE_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
BACKUP_DIR.mkdir(parents=True, exist_ok=True)


CREATIVE_WORDS_PATH = BASE_DIR / "wordlists" / "Oxford_5000.txt"

CREATIVE_WORD_SELECTOR_SYSTEM_PATH = PROMPTS_DIR / "creative_word_selector_system_prompt.txt"
CREATIVE_WORD_SELECTOR_USER_TEMPLATE_PATH = PROMPTS_DIR / "creative_word_selector_user_template.txt"

CREATIVE_SITUATION_SYSTEM_PATH = PROMPTS_DIR / "creative_situation_system_prompt.txt"
CREATIVE_SITUATION_USER_TEMPLATE_PATH = PROMPTS_DIR / "creative_situation_user_template.txt"

CREATIVE_PACKET_PATH = STATE_DIR / "creative_packet.json"


PLANNER_SYSTEM_PATH = PROMPTS_DIR / "planner_system_prompt.txt"
PLANNER_USER_TEMPLATE_PATH = PROMPTS_DIR / "planner_user_template.txt"

PLANNER_CONCEPT_SYSTEM_PATH = PROMPTS_DIR / "planner_concept_system_prompt.txt"
PLANNER_CONCEPT_USER_TEMPLATE_PATH = PROMPTS_DIR / "planner_concept_user_template.txt"

PLANNER_BIBLE_SYSTEM_PATH = PROMPTS_DIR / "planner_bible_system_prompt.txt"
PLANNER_BIBLE_USER_TEMPLATE_PATH = PROMPTS_DIR / "planner_bible_user_template.txt"

SECTION_ENTRY_PLANNER_SYSTEM_PATH = PROMPTS_DIR / "section_entry_planner_system_prompt.txt"
SECTION_ENTRY_PLANNER_USER_TEMPLATE_PATH = PROMPTS_DIR / "section_entry_planner_user_template.txt"

SECTION_ENTRY_WRITER_SYSTEM_PATH = PROMPTS_DIR / "section_entry_writer_system_prompt.txt"
SECTION_ENTRY_WRITER_USER_TEMPLATE_PATH = PROMPTS_DIR / "section_entry_writer_user_template.txt"

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

METRIC_SCHEMA_SYSTEM_PATH = PROMPTS_DIR / "metric_schema_system_prompt.txt"
METRIC_SCHEMA_USER_TEMPLATE_PATH = PROMPTS_DIR / "metric_schema_user_template.txt"

METRIC_ENVELOPE_SYSTEM_PATH = PROMPTS_DIR / "metric_envelope_system_prompt.txt"
METRIC_ENVELOPE_USER_TEMPLATE_PATH = PROMPTS_DIR / "metric_envelope_user_template.txt"

METRIC_REPAIR_SYSTEM_PATH = PROMPTS_DIR / "metric_repair_system_prompt.txt"
METRIC_REPAIR_USER_TEMPLATE_PATH = PROMPTS_DIR / "metric_repair_user_template.txt"

STORY_PLAN_METRIC_ANALYSIS_PATH = STATE_DIR / "story_plan_metric_analysis.json"
STORY_PLAN_METRIC_REPAIR_PATH = STATE_DIR / "story_plan_metric_repair.json"

SECTION_PROOFREADER_SYSTEM_PATH = PROMPTS_DIR / "section_proofreader_system_prompt.txt"
SECTION_PROOFREADER_USER_TEMPLATE_PATH = PROMPTS_DIR / "section_proofreader_user_template.txt"

# =============
LAST_FAILED_JSON_RAW_PATH = STATE_DIR / "last_failed_json_raw.txt"

PROJECT_META_PATH = STATE_DIR / "project_meta.json"
METRIC_SCHEMA_PATH = BASE_DIR / "metric_schema_v1.json"

STORY_CONCEPT_PATH = STATE_DIR / "story_concept.json"
STORY_BIBLE_PATH = STATE_DIR / "story_bible.json"
SECTION_DRAFT_PATH = STATE_DIR / "section_draft.json"

STORY_PLAN_PATH = STATE_DIR / "story_plan.json"
SECTION_INDEX_PATH = STATE_DIR / "section_index.json"

CURRENT_SECTION_ENTRY_PLAN_PATH = STATE_DIR / "current_section_entry_plan.json"

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
SECTIONS_DIR = OUTPUT_DIR / "sections"

VALIDATION_REPORTS_DIR.mkdir(parents=True, exist_ok=True)
SEGMENTS_DIR.mkdir(parents=True, exist_ok=True)
SEGMENT_LOGS_DIR.mkdir(parents=True, exist_ok=True)
SECTIONS_DIR.mkdir(parents=True, exist_ok=True)