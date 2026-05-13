from __future__ import annotations

import json
import re
from typing import Any

from openai import OpenAI

from config import (
    LM_STUDIO_API_KEY,
    LM_STUDIO_BASE_URL,
    LM_STUDIO_MAX_TOKENS,
    LM_STUDIO_TEMPERATURE,
)


class LLMClient:
    def __init__(self) -> None:
        self.client = OpenAI(
            base_url=LM_STUDIO_BASE_URL,
            api_key=LM_STUDIO_API_KEY,
        )

    def generate_text(self, model: str, system_prompt: str, user_prompt: str) -> str:
        response = self.client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=LM_STUDIO_TEMPERATURE,
            max_tokens=LM_STUDIO_MAX_TOKENS,
        )
        return (response.choices[0].message.content or "").strip()

    def generate_json(self, model: str, system_prompt: str, user_prompt: str) -> dict[str, Any]:
        raw = self.generate_text(model=model, system_prompt=system_prompt, user_prompt=user_prompt)
        return self._extract_json(raw)

    def _extract_json(self, raw: str) -> dict[str, Any]:
        raw = raw.strip()

        try:
            return json.loads(raw)
        except Exception:
            pass

        m = re.search(r"```json\s*(.*?)```", raw, flags=re.DOTALL | re.IGNORECASE)
        if m:
            try:
                return json.loads(m.group(1).strip())
            except Exception:
                pass

        m = re.search(r"```\s*(.*?)```", raw, flags=re.DOTALL)
        if m:
            try:
                return json.loads(m.group(1).strip())
            except Exception:
                pass

        m = re.search(r"(\{.*\})", raw, flags=re.DOTALL)
        if m:
            try:
                return json.loads(m.group(1))
            except Exception:
                pass

        raise ValueError("Model output is not valid JSON.")