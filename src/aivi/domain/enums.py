from enum import StrEnum


class Actor(StrEnum):
    PIPELINE = "pipeline"
    RESEARCH_AGENT = "research_agent"
    SANDBOX_AGENT = "sandbox_agent"
    OWNER = "owner"


class KnowledgeType(StrEnum):
    FACT = "FACT"
    INSIGHT = "INSIGHT"
    ASSUMPTION = "ASSUMPTION"
    USER_OPINION = "USER_OPINION"
    RISK = "RISK"
    NEW_INFORMATION = "NEW_INFORMATION"
    TODO = "TODO"
    OBSERVATION = "OBSERVATION"


class KnowledgeSection(StrEnum):
    PROFILE = "profile"
    BUSINESS_MODEL = "business_model"
    MANAGEMENT = "management"
    MOAT = "moat"
    INDUSTRY = "industry"
    COMPETITORS = "competitors"
    FINANCIALS = "financials"
    VALUATION = "valuation"
    RISKS = "risks"
    WATCHPOINTS = "watchpoints"
    NEWS = "news"


class RecordStatus(StrEnum):
    PROPOSED = "proposed"
    ACTIVE = "active"
    SUPERSEDED = "superseded"
    REJECTED = "rejected"


class ThesisPointStatus(StrEnum):
    INTACT = "intact"
    STRENGTHENED = "strengthened"
    WEAKENED = "weakened"
    BROKEN = "broken"
    UNTESTED = "untested"


class Impact(StrEnum):
    POSITIVE = "positive"
    NEUTRAL = "neutral"
    NEGATIVE = "negative"


class Importance(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
