import logging

from aivi.config import Settings
from aivi.llm import LLMNotConfigured, LLMProvider, ModelTier
from aivi.llm.gemini import DisabledProvider, GeminiProvider

log = logging.getLogger(__name__)


def build_provider(name: str, settings: Settings) -> LLMProvider:
    if name == "gemini":
        return GeminiProvider(settings)
    if name in {"openai", "anthropic"}:
        return DisabledProvider(name)
    raise LLMNotConfigured(f"unknown LLM provider: {name}")


class LLMRouter:
    def __init__(self, settings: Settings) -> None:
        self.cheap = build_provider(settings.llm_cheap_provider, settings)
        self.strong = build_provider(settings.llm_strong_provider, settings)

    def _provider(self, tier: ModelTier) -> LLMProvider:
        if tier == ModelTier.CHEAP:
            return self.cheap
        return self.strong

    def model_name(self, tier: ModelTier) -> str:
        return self._provider(tier).model_name(tier)

    def complete_text(self, *, system: str, user: str, tier: ModelTier) -> str:
        log.info("llm_call tier=%s model=%s chars=%s", tier.value, self.model_name(tier), len(user))
        return self._provider(tier).complete_text(system=system, user=user, tier=tier)

    def complete_json(self, *, system: str, user: str, tier: ModelTier) -> dict:
        log.info("llm_call tier=%s model=%s chars=%s json=1", tier.value, self.model_name(tier), len(user))
        return self._provider(tier).complete_json(system=system, user=user, tier=tier)
