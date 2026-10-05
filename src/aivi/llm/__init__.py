from enum import StrEnum
from typing import Protocol


class ModelTier(StrEnum):
    CHEAP = "cheap"
    STRONG = "strong"


class LLMNotConfigured(RuntimeError):
    pass


class LLMProvider(Protocol):
    def complete_text(self, *, system: str, user: str, tier: ModelTier) -> str: ...

    def complete_json(self, *, system: str, user: str, tier: ModelTier) -> dict: ...

    def model_name(self, tier: ModelTier) -> str: ...
