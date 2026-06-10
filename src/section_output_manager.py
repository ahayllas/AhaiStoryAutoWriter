from __future__ import annotations

from pathlib import Path
from typing import Any

from config import MANUSCRIPT_PATH, SECTION_INDEX_PATH, SECTIONS_DIR, STORY_PLAN_PATH
from io_contract import load_json, load_text, save_json, save_text



def _section_dir(section_id: str) -> Path:
    return SECTIONS_DIR / section_id


def _section_index_path(section_id: str) -> Path:
    return _section_dir(section_id) / "index.json"


def _default_section_index(section_id: str) -> dict[str, Any]:
    return {
        "section_id": section_id,
        "entry_id": "",
        "entry_file": "entry.md",
        "segments": [],
        "assembled_file": "assembled.md",
        "proofread_file": "proofread.md",
        "final_file": "final.md",
        "proofreading_status": "not_started",
    }


def _ensure_section_dirs(section_id: str) -> Path:
    section_dir = _section_dir(section_id)
    (section_dir / "segments").mkdir(parents=True, exist_ok=True)
    return section_dir


def _load_section_index(section_id: str) -> dict[str, Any]:
    path = _section_index_path(section_id)
    raw = load_json(path, {})
    base = _default_section_index(section_id)
    if isinstance(raw, dict):
        base.update(raw)

    if not isinstance(base.get("segments"), list):
        base["segments"] = []

    return base


def _save_section_index(section_id: str, payload: dict[str, Any]) -> None:
    _ensure_section_dirs(section_id)
    save_json(_section_index_path(section_id), payload)


def _normalize_positive_int(value: Any) -> int | None:
    try:
        ivalue = int(value)
    except Exception:
        return None
    if ivalue <= 0:
        return None
    return ivalue


def _next_segment_order(index_payload: dict[str, Any]) -> int:
    max_order = 0
    for item in index_payload.get("segments", []):
        order = _normalize_positive_int(item.get("order"))
        if order and order > max_order:
            max_order = order
    return max_order + 1


def _segment_rel_path(order: int, segment_id: str) -> str:
    return f"segments/{order:04d}_{segment_id}.md"


def save_section_entry(
    section_id: str,
    entry_id: str,
    narrative: str,
    meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    section_dir = _ensure_section_dirs(section_id)
    save_text(section_dir / "entry.md", narrative.strip())

    index_payload = _load_section_index(section_id)
    index_payload["section_id"] = section_id
    index_payload["entry_id"] = entry_id
    index_payload["entry_file"] = "entry.md"

    if isinstance(meta, dict):
        for key, value in meta.items():
            if key not in {"segments"}:
                index_payload[key] = value

    _save_section_index(section_id, index_payload)
    return index_payload


def save_section_segment(
    section_id: str,
    segment_id: str,
    narrative: str,
    segment_order: int | None = None,
    meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    section_dir = _ensure_section_dirs(section_id)
    index_payload = _load_section_index(section_id)
    segments = list(index_payload.get("segments", []))

    existing_idx = None
    existing_item = None
    for i, item in enumerate(segments):
        if item.get("segment_id") == segment_id:
            existing_idx = i
            existing_item = item
            break

    resolved_order = _normalize_positive_int(segment_order)
    if resolved_order is None and existing_item is not None:
        resolved_order = _normalize_positive_int(existing_item.get("order"))
    if resolved_order is None:
        resolved_order = _next_segment_order(index_payload)

    rel_path = _segment_rel_path(resolved_order, segment_id)
    abs_path = section_dir / rel_path
    abs_path.parent.mkdir(parents=True, exist_ok=True)

    if existing_item is not None:
        old_file = existing_item.get("file")
        if old_file and old_file != rel_path:
            old_path = section_dir / old_file
            if old_path.exists():
                old_path.unlink()

    save_text(abs_path, narrative.strip())

    new_item: dict[str, Any] = {
        "order": resolved_order,
        "segment_id": segment_id,
        "file": rel_path,
        "completed": True,
    }
    if isinstance(meta, dict):
        new_item.update(meta)

    if existing_idx is None:
        segments.append(new_item)
    else:
        segments[existing_idx] = new_item

    segments.sort(key=lambda x: (_normalize_positive_int(x.get("order")) or 999999, x.get("segment_id", "")))
    index_payload["segments"] = segments

    _save_section_index(section_id, index_payload)
    return index_payload


def assemble_section(section_id: str) -> str:
    section_dir = _section_dir(section_id)
    if not section_dir.exists():
        return ""

    index_payload = _load_section_index(section_id)
    parts: list[str] = []

    entry_file = index_payload.get("entry_file") or "entry.md"
    entry_path = section_dir / entry_file
    if entry_path.exists():
        entry_text = load_text(entry_path, "").strip()
        if entry_text:
            parts.append(entry_text)

    segments = list(index_payload.get("segments", []))
    segments.sort(key=lambda x: (_normalize_positive_int(x.get("order")) or 999999, x.get("segment_id", "")))

    for item in segments:
        rel_path = item.get("file")
        if not rel_path:
            continue
        seg_path = section_dir / rel_path
        if not seg_path.exists():
            continue
        seg_text = load_text(seg_path, "").strip()
        if seg_text:
            parts.append(seg_text)

    assembled = "\n\n".join(parts).strip()
    assembled_file = index_payload.get("assembled_file") or "assembled.md"
    save_text(section_dir / assembled_file, assembled)
    return assembled


def _ordered_section_ids() -> list[str]:
    ordered_ids: list[str] = []

    state_index = load_json(SECTION_INDEX_PATH, [])
    if isinstance(state_index, list):
        for item in state_index:
            section_id = None
            if isinstance(item, dict):
                section_id = item.get("section_id")
            elif isinstance(item, str):
                section_id = item

            if section_id and section_id not in ordered_ids:
                ordered_ids.append(section_id)

    if SECTIONS_DIR.exists():
        for child in sorted(SECTIONS_DIR.iterdir(), key=lambda p: p.name):
            if child.is_dir() and child.name not in ordered_ids:
                ordered_ids.append(child.name)

    return ordered_ids


def _best_section_text(section_id: str) -> str:
    section_dir = _section_dir(section_id)
    if not section_dir.exists():
        return ""

    index_payload = _load_section_index(section_id)
    candidate_files = [
        index_payload.get("final_file") or "final.md",
        index_payload.get("proofread_file") or "proofread.md",
        index_payload.get("assembled_file") or "assembled.md",
    ]

    for rel_path in candidate_files:
        path = section_dir / rel_path
        if path.exists():
            text = load_text(path, "").strip()
            if text:
                return text

    return assemble_section(section_id).strip()


def rebuild_manuscript() -> str:
    parts: list[str] = []

    for section_id in _ordered_section_ids():
        section_text = _best_section_text(section_id)
        if section_text:
            parts.append(section_text)

    manuscript = "\n\n".join(parts).strip()
    save_text(MANUSCRIPT_PATH, manuscript)
    return manuscript
    
    
def rebuild_manuscript_fancy() -> str:
    story_plan = load_json(STORY_PLAN_PATH, {})
    title = ""
    section_title_map: dict[str, str] = {}

    if isinstance(story_plan, dict):
        title = str(story_plan.get("title") or "").strip()
        sections = story_plan.get("sections", [])
        if isinstance(sections, list):
            for section in sections:
                if not isinstance(section, dict):
                    continue
                section_id = str(section.get("section_id") or "").strip()
                section_title = str(section.get("title") or "").strip()
                if section_id:
                    section_title_map[section_id] = section_title

    parts: list[str] = []

    if title:
        parts.append(f"# {title}")
        parts.append("")

    section_ids = _ordered_section_ids()

    for idx, section_id in enumerate(section_ids, start=1):
        section_text = _best_section_text(section_id)
        if not section_text:
            continue

        section_title = section_title_map.get(section_id, "").strip()

        parts.append("---")
        parts.append("")
        heading = f"## Chapter {idx}"
        if section_title:
            heading += f"｜{section_title}"
        parts.append(heading)
        parts.append("")
        parts.append(section_text)

    manuscript = "\n".join(parts).strip()
    save_text(MANUSCRIPT_PATH, manuscript)
    return manuscript