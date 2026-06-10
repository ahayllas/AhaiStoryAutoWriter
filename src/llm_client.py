from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from json_repair import repair_json
from openai import OpenAI

from config import LAST_FAILED_JSON_RAW_PATH, JSON_REPAIR_MAX_RETRIES
from model_profiles import MODEL_PROFILES


class LLMClient:
    def __init__(self) -> None:
        self._clients: dict[str, OpenAI] = {}

    def _get_profile(self, profile_name: str) -> dict[str, Any]:
        if profile_name not in MODEL_PROFILES:
            raise ValueError(f"Unknown model profile: {profile_name}")
        return MODEL_PROFILES[profile_name]

    def _get_client(self, profile_name: str) -> OpenAI:
        if profile_name not in self._clients:
            profile = self._get_profile(profile_name)
            self._clients[profile_name] = OpenAI(
                base_url=profile["base_url"],
                api_key=profile["api_key"],
            )
        return self._clients[profile_name]

    def generate_text(
        self,
        model: str,
        system_prompt: str,
        user_prompt: str,
    ) -> str:
        """Generate text with retry on incomplete/truncated responses."""
        max_retries = JSON_REPAIR_MAX_RETRIES
        last_raw = ""

        for attempt in range(1, max_retries + 1):
            print(f"[LLM] Attempt {attempt}/{max_retries} - Generating text...")

            profile = self._get_profile(model)
            client = self._get_client(model)

            response = client.chat.completions.create(
                model=profile["model"],
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ]
            )

            choice = response.choices[0]
            content = (choice.message.content or "").strip()
            finish_reason = choice.finish_reason
            last_raw = content

            if finish_reason == "stop":
                if attempt > 1:
                    print(f"[LLM] Success on retry {attempt}")
                return content

            # Not a normal completion
            print(f"[LLM] Warning: finish_reason = '{finish_reason}'. Retrying...")

            if attempt == max_retries:
                self._save_failed_raw(last_raw)
                raise ValueError(
                    f"Failed to get complete text after {max_retries} attempts "
                    f"(last finish_reason='{finish_reason}'). "
                    f"Raw output saved to {LAST_FAILED_JSON_RAW_PATH}"
                )

        raise ValueError("Unexpected error in generate_text")

    def generate_json(
        self,
        model: str,
        system_prompt: str,
        user_prompt: str,
    ) -> dict[str, Any]:
        """Generate JSON with smart truncation detection."""
        max_retries = JSON_REPAIR_MAX_RETRIES
        last_raw = ""

        for attempt in range(1, max_retries + 1):
            print(f"[LLM] Attempt {attempt}/{max_retries} - Generating JSON...")

            raw, finish_reason = self.generate_text_with_finish_reason(
                model=model, system_prompt=system_prompt, user_prompt=user_prompt
            )
            last_raw = raw

            # === Key Check: Only accept if finished properly ===
            if finish_reason != "stop":
                print(f"[LLM] Warning: finish_reason = '{finish_reason}' (not 'stop'). Skipping repair and retrying...")
                if attempt < max_retries:
                    continue
                else:
                    self._save_failed_raw(last_raw)
                    raise ValueError(
                        f"Model did not finish properly (finish_reason='{finish_reason}'). "
                        f"Possible truncation or error."
                    )

            # Normal completion → safe to try extraction and repair
            try:
                result = self._extract_json(raw)
                if attempt > 1:
                    print(f"[LLM] Success on retry {attempt}")
                return result
            except ValueError:
                pass

            # Try json-repair (only on normal completions)
            try:
                repaired = repair_json(raw)
                result = json.loads(repaired)
                print(f"[LLM] Success on retry {attempt} (after json-repair)")
                return result
            except Exception:
                pass

            if attempt < max_retries:
                print(f"[LLM] Attempt {attempt} failed. Retrying...")
            else:
                self._save_failed_raw(last_raw)
                raise ValueError(f"Failed to get valid JSON after {max_retries} attempts.")

        raise ValueError("Unexpected error in generate_json")


    def generate_text_with_finish_reason(
        self, model: str, system_prompt: str, user_prompt: str
    ) -> tuple[str, str | None]:
        """Returns (content, finish_reason)"""
        profile = self._get_profile(model)
        client = self._get_client(model)

        response = client.chat.completions.create(
            model=profile["model"],
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )

        choice = response.choices[0]
        content = (choice.message.content or "").strip()
        finish_reason = choice.finish_reason

        return content, finish_reason



    def _extract_json(self, raw: str) -> dict[str, Any]:
        raw = raw.strip()

        # Try direct JSON
        try:
            return json.loads(raw)
        except Exception:
            pass

        # Try extracting from code blocks
        for pattern in [
            r"```json\s*(.*?)```",
            r"```\s*(.*?)```",
            r"(\{.*\})",
        ]:
            match = re.search(pattern, raw, flags=re.DOTALL)
            if match:
                try:
                    return json.loads(match.group(1).strip())
                except Exception:
                    continue

        raise ValueError("Model output is not valid JSON.")

    def _save_failed_raw(self, raw: str) -> None:
        """Save the last failed raw output (overwrites previous)."""
        try:
            Path(LAST_FAILED_JSON_RAW_PATH).write_text(raw, encoding="utf-8")
        except Exception:
            pass