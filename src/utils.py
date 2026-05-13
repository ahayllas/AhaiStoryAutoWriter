from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any


def count_words_approx(text: str) -> int:
    stripped = text.strip()
    if not stripped:
        return 0

    cjk_chars = re.findall(r"[\u4e00-\u9fff]", stripped)
    if len(cjk_chars) > max(100, int(len(stripped) * 0.2)):
        return max(1, int(len(cjk_chars) / 1.6))

    return len(re.findall(r"\S+", stripped))


def extract_recent_excerpt(text: str, max_chars: int = 8000) -> str:
    stripped = text.strip()
    if not stripped:
        return ""
    if len(stripped) <= max_chars:
        return stripped
    return stripped[-max_chars:]


def normalize_ws(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip())


def estimate_next_segment_words(current_words: int, target_total_words: int) -> int:
    remaining = max(0, target_total_words - current_words)
    if remaining <= 0:
        return 0

    progress = current_words / max(1, target_total_words)

    if progress < 0.1:
        base = 2200
    elif progress < 0.3:
        base = 2600
    elif progress < 0.65:
        base = 3000
    elif progress < 0.9:
        base = 2600
    else:
        base = 2200

    return min(base, remaining)


def infer_phase_by_progress(progress: float) -> str:
    if progress < 0.1:
        return "opening"
    if progress < 0.3:
        return "early"
    if progress < 0.65:
        return "middle"
    if progress < 0.9:
        return "late"
    return "final"


def expected_min_segments(target_total_words: int, segment_words: int = 2500) -> int:
    total = max(1, math.ceil(target_total_words / max(1, segment_words)))
    return max(12, total // 2)


def fill_template(template: str, mapping: dict[str, Any]) -> str:
    result = template
    for key, value in mapping.items():
        if not isinstance(value, str):
            value = json.dumps(value, ensure_ascii=False, indent=2)
        result = result.replace(f"{{{{{key}}}}}", value)
    return result


def safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def ensure_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if value is None:
        return []
    return [value]


def ensure_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    return {}


def append_markdown_section(original: str, new_text: str) -> str:
    original = original.strip()
    new_text = new_text.strip()
    if not original:
        return new_text
    if not new_text:
        return original
    return f"{original}\n\n{new_text}"


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except Exception:
            continue
    return rows