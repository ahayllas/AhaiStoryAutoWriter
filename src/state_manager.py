from __future__ import annotations

import json
import re
from typing import Any

from config import (
    CURRENT_FACT_BRIEF_PATH,
    CURRENT_STATE_UPDATE_PATH,
    CURRENT_STORY_STATE_PATH,
)
from io_contract import load_json, save_json
from utils import ensure_dict, ensure_list


class StateManager:
    """
    MVP strategy:
    - accept either JSON-like dict input
    - or parse lightweight tagged text from writer [STATE_UPDATE]
    """

    def load_story_state(self) -> dict[str, Any]:
        return load_json(CURRENT_STORY_STATE_PATH, {
            "known_facts": [],
            "active_threads": [],
            "character_positions": {},
            "recent_consequences": [],
        })

    def load_fact_brief(self) -> dict[str, Any]:
        return load_json(CURRENT_FACT_BRIEF_PATH, {
            "known_facts": [],
            "active_threads": [],
            "character_positions": {},
            "unresolved_questions": [],
            "recent_consequences": [],
        })

    def save_story_state(self, state: dict[str, Any]) -> None:
        save_json(CURRENT_STORY_STATE_PATH, state)

    def save_fact_brief(self, fact_brief: dict[str, Any]) -> None:
        save_json(CURRENT_FACT_BRIEF_PATH, fact_brief)

    def parse_state_update_text(self, text: str) -> dict[str, Any]:
        stripped = text.strip()

        maybe_json = self._try_extract_json(stripped)
        if maybe_json is not None:
            return self._normalize_state_patch(maybe_json)

        sections = {
            "known_facts_add": self._extract_bullets(stripped, "KNOWN_FACTS_ADD"),
            "active_threads_add": self._extract_bullets(stripped, "ACTIVE_THREADS_ADD"),
            "active_threads_resolved": self._extract_bullets(stripped, "ACTIVE_THREADS_RESOLVED"),
            "recent_consequences_add": self._extract_bullets(stripped, "RECENT_CONSEQUENCES_ADD"),
            "unresolved_questions_add": self._extract_bullets(stripped, "UNRESOLVED_QUESTIONS_ADD"),
        }

        character_positions = self._extract_key_values(stripped, "CHARACTER_POSITIONS_SET")

        payload = dict(sections)
        payload["character_positions_set"] = character_positions
        return self._normalize_state_patch(payload)

    def _try_extract_json(self, text: str) -> dict[str, Any] | None:
        try:
            data = json.loads(text)
            if isinstance(data, dict):
                return data
        except Exception:
            pass

        m = re.search(r"```json\s*(.*?)```", text, flags=re.DOTALL | re.IGNORECASE)
        if m:
            try:
                data = json.loads(m.group(1).strip())
                if isinstance(data, dict):
                    return data
            except Exception:
                return None
        return None

    def _extract_bullets(self, text: str, tag: str) -> list[str]:
        pattern = rf"\[{tag}\](.*?)(?=\n\[[A-Z0-9_]+\]|\Z)"
        m = re.search(pattern, text, flags=re.DOTALL)
        if not m:
            return []
        block = m.group(1).strip()
        result = []
        for line in block.splitlines():
            line = line.strip()
            if line.startswith("- "):
                result.append(line[2:].strip())
        return result

    def _extract_key_values(self, text: str, tag: str) -> dict[str, str]:
        pattern = rf"\[{tag}\](.*?)(?=\n\[[A-Z0-9_]+\]|\Z)"
        m = re.search(pattern, text, flags=re.DOTALL)
        if not m:
            return {}
        block = m.group(1).strip()
        result = {}
        for line in block.splitlines():
            line = line.strip().lstrip("-").strip()
            if ":" in line:
                k, v = line.split(":", 1)
                result[k.strip()] = v.strip()
        return result

    def _normalize_state_patch(self, patch: dict[str, Any]) -> dict[str, Any]:
        return {
            "known_facts_add": ensure_list(patch.get("known_facts_add")),
            "active_threads_add": ensure_list(patch.get("active_threads_add")),
            "active_threads_resolved": ensure_list(patch.get("active_threads_resolved")),
            "character_positions_set": ensure_dict(patch.get("character_positions_set")),
            "recent_consequences_add": ensure_list(patch.get("recent_consequences_add")),
            "unresolved_questions_add": ensure_list(patch.get("unresolved_questions_add")),
        }

    def apply_patch(self, patch: dict[str, Any]) -> dict[str, Any]:
        story_state = self.load_story_state()
        fact_brief = self.load_fact_brief()

        known_facts = list(dict.fromkeys(ensure_list(story_state.get("known_facts")) + patch["known_facts_add"]))
        active_threads = ensure_list(story_state.get("active_threads"))
        for item in patch["active_threads_add"]:
            if item not in active_threads:
                active_threads.append(item)
        for item in patch["active_threads_resolved"]:
            active_threads = [x for x in active_threads if x != item]

        character_positions = ensure_dict(story_state.get("character_positions"))
        character_positions.update(patch["character_positions_set"])

        recent_consequences = ensure_list(story_state.get("recent_consequences"))
        recent_consequences.extend(patch["recent_consequences_add"])
        recent_consequences = recent_consequences[-20:]

        updated_story_state = {
            "known_facts": known_facts,
            "active_threads": active_threads,
            "character_positions": character_positions,
            "recent_consequences": recent_consequences,
        }

        unresolved = ensure_list(fact_brief.get("unresolved_questions"))
        for q in patch["unresolved_questions_add"]:
            if q not in unresolved:
                unresolved.append(q)

        updated_fact_brief = {
            "known_facts": known_facts,
            "active_threads": active_threads,
            "character_positions": character_positions,
            "unresolved_questions": unresolved,
            "recent_consequences": recent_consequences,
        }

        self.save_story_state(updated_story_state)
        self.save_fact_brief(updated_fact_brief)
        save_json(CURRENT_STATE_UPDATE_PATH, patch)

        return {
            "story_state": updated_story_state,
            "fact_brief": updated_fact_brief,
        }