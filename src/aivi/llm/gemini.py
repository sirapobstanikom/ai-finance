import json
import logging

import httpx

from aivi.config import Settings
from aivi.llm import LLMNotConfigured, ModelTier

log = logging.getLogger(__name__)


class GeminiProvider:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def model_name(self, tier: ModelTier) -> str:
        if tier == ModelTier.CHEAP:
            return self.settings.llm_cheap_model
        return self.settings.llm_strong_model

    def complete_text(self, *, system: str, user: str, tier: ModelTier) -> str:
        data = self._generate(system=system, user=user, tier=tier, json_mode=False)
        return _response_text(data)

    def complete_json(self, *, system: str, user: str, tier: ModelTier) -> dict:
        data = self._generate(
            system=system + "\nRespond with a JSON object only.",
            user=user,
            tier=tier,
            json_mode=True,
        )
        text = _response_text(data).strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[-1]
            text = text.removesuffix("```").strip()
        return json.loads(text)

    def _generate(self, *, system: str, user: str, tier: ModelTier, json_mode: bool) -> dict:
        if not self.settings.gemini_api_key:
            raise LLMNotConfigured("GEMINI_API_KEY is not set")
        model = self.model_name(tier)
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        body: dict = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": {"temperature": 0.2},
        }
        if json_mode:
            body["generationConfig"]["responseMimeType"] = "application/json"
        log.info("gemini request model=%s chars=%s", model, len(user))
        response = httpx.post(
            url,
            params={"key": self.settings.gemini_api_key},
            json=body,
            timeout=60,
        )
        response.raise_for_status()
        return response.json()


def _response_text(data: dict) -> str:
    try:
        return data["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError, TypeError) as exc:
        raise LLMNotConfigured("Gemini response did not include text") from exc


class DisabledProvider:
    def __init__(self, name: str) -> None:
        self.name = name

    def model_name(self, tier: ModelTier) -> str:
        return self.name

    def complete_text(self, *, system: str, user: str, tier: ModelTier) -> str:
        raise LLMNotConfigured(f"{self.name} adapter is not enabled")

    def complete_json(self, *, system: str, user: str, tier: ModelTier) -> dict:
        raise LLMNotConfigured(f"{self.name} adapter is not enabled")
