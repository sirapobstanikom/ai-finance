import json
import re
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from aivi.domain.models import (
    ChangeEvent,
    Company,
    ConversationMessage,
    Document,
    DocumentBlock,
    ExternalSnapshot,
    KnowledgeItem,
    Memory,
    utcnow,
)
from aivi.knowledge.thesis import active_thesis, thesis_points
from aivi.tokens import estimate_tokens, fit_chunks, truncate_to_budget

COMPANY_BUDGET = 400
THESIS_BUDGET = 500
MEMORY_BUDGET = 800
KNOWLEDGE_BUDGET = 1200
EXTERNAL_DATA_BUDGET = 1000
CHANGES_BUDGET = 600
PASSAGES_BUDGET = 1500
RECENT_BUDGET = 800
MAX_MEMORIES = 5
MAX_KNOWLEDGE = 8
MAX_PASSAGES = 3

_LATIN = re.compile(r"[A-Za-z][A-Za-z0-9_]{2,}")


@dataclass
class ContextPack:
    company_text: str
    thesis_text: str
    memory_text: str
    knowledge_text: str
    external_data_text: str
    changes_text: str
    passages_text: str
    recent_text: str
    question: str
    has_material_change: bool
    has_high_importance_change: bool

    def render(self) -> str:
        sections = [
            ("COMPANY", self.company_text),
            ("THESIS", self.thesis_text),
            ("MEMORY", self.memory_text),
            ("KNOWLEDGE", self.knowledge_text),
            ("EXTERNAL DATA", self.external_data_text),
            ("CHANGES", self.changes_text),
            ("PASSAGES", self.passages_text),
            ("RECENT", self.recent_text),
            ("QUESTION", self.question),
        ]
        return "\n\n".join(f"{name}\n{body}".rstrip() for name, body in sections if body)


def keywords(text: str) -> set[str]:
    return {match.group(0).casefold() for match in _LATIN.finditer(text)}


def assemble_context(
    session: Session,
    *,
    company: Company,
    question: str,
    conversation_id: str | None,
) -> ContextPack:
    keys = keywords(question)
    company_text = truncate_to_budget(_company_card(company), COMPANY_BUDGET)
    thesis_text = truncate_to_budget(_thesis_card(session, company.id), THESIS_BUDGET)
    memory_text = _memories(session, company.id)
    knowledge_text = _knowledge(session, company.id, keys)
    external_data_text = _external_data(session, company.id)
    changes, changes_text = _changes(session, company.id)
    passages_text = _passages(session, company.id, keys)
    recent_text = _recent(session, conversation_id)
    high = [event for event in changes if event.importance == "high"]
    return ContextPack(
        company_text=company_text,
        thesis_text=thesis_text,
        memory_text=memory_text,
        knowledge_text=knowledge_text,
        external_data_text=external_data_text,
        changes_text=changes_text,
        passages_text=passages_text,
        recent_text=recent_text,
        question=question,
        has_material_change=bool(high),
        has_high_importance_change=bool(high),
    )


def _company_card(company: Company) -> str:
    return " | ".join(
        part
        for part in (
            company.ticker,
            company.market,
            company.name_en,
            company.name_th,
            company.sector,
        )
        if part
    )


def _thesis_card(session: Session, company_id: str) -> str:
    thesis = active_thesis(session, company_id)
    if thesis is None:
        return ""
    lines = [f"version {thesis.version}"]
    if thesis.summary:
        lines.append(thesis.summary)
    for point in thesis_points(session, thesis.id):
        lines.append(
            f"{point.id} | {point.ordinal}. {point.label} | {point.status} | {point.statement}"
        )
    return "\n".join(lines)


def _memories(session: Session, company_id: str) -> str:
    rows = list(
        session.scalars(
            select(Memory)
            .where(Memory.company_id == company_id, Memory.status == "active")
            .order_by(Memory.importance.desc(), Memory.created_at.desc())
        )
    )
    chunks = [f"{row.id} | {row.memory_type} | {row.summary}" for row in rows]
    text = fit_chunks(chunks, MEMORY_BUDGET, limit=MAX_MEMORIES)
    kept = {line.split(" | ", 1)[0] for line in text.splitlines() if line}
    now = utcnow()
    for row in rows:
        if row.id in kept:
            row.retrieve_count += 1
            row.last_retrieved_at = now
    return text


def _knowledge(session: Session, company_id: str, keys: set[str]) -> str:
    rows = list(
        session.scalars(
            select(KnowledgeItem).where(
                KnowledgeItem.company_id == company_id,
                KnowledgeItem.status == "active",
            )
        )
    )

    def score(item: KnowledgeItem) -> tuple[int, int]:
        overlap = sum(1 for key in keys if key in item.statement.casefold())
        importance = {"high": 3, "medium": 2, "low": 1}.get(item.importance, 1)
        return (overlap, importance)

    matched = [item for item in rows if score(item)[0] > 0]
    matched.sort(key=score, reverse=True)
    if not matched:
        matched = sorted(rows, key=score, reverse=True)
    chunks = [
        f"{item.id} | {item.type} | {item.section} | {item.statement}" for item in matched
    ]
    return fit_chunks(chunks, KNOWLEDGE_BUDGET, limit=MAX_KNOWLEDGE)


def _external_data(session: Session, company_id: str) -> str:
    rows = list(
        session.scalars(
            select(ExternalSnapshot)
            .where(ExternalSnapshot.company_id == company_id)
            .order_by(ExternalSnapshot.fetched_at.desc())
        )
    )
    latest: dict[str, ExternalSnapshot] = {}
    for row in rows:
        latest.setdefault(row.data_type, row)
    chunks = [
        f"{row.id} | {row.source} | {row.data_type} | "
        + json.dumps(row.payload_json, ensure_ascii=False, sort_keys=True)
        for row in latest.values()
    ]
    return fit_chunks(chunks, EXTERNAL_DATA_BUDGET)


def _changes(session: Session, company_id: str) -> tuple[list[ChangeEvent], str]:
    cutoff = utcnow() - timedelta(days=90)
    rows = list(
        session.scalars(
            select(ChangeEvent)
            .where(ChangeEvent.company_id == company_id, ChangeEvent.detected_at >= cutoff)
            .order_by(ChangeEvent.detected_at.desc())
        )
    )
    chunks = [f"{event.id}\n{event.summary}" for event in rows]
    return rows, fit_chunks(chunks, CHANGES_BUDGET)


def _passages(session: Session, company_id: str, keys: set[str]) -> str:
    if not keys:
        return ""
    blocks = list(
        session.scalars(
            select(DocumentBlock)
            .join(Document, Document.id == DocumentBlock.document_id)
            .where(Document.company_id == company_id, DocumentBlock.block_type != "heading")
        )
    )
    scored: list[tuple[int, DocumentBlock]] = []
    for block in blocks:
        haystack = block.text.casefold()
        overlap = sum(1 for key in keys if key in haystack)
        if overlap > 0:
            scored.append((overlap, block))
    scored.sort(key=lambda item: item[0], reverse=True)
    chunks = [
        f"{block.id} | {block.section_path} | {block.text}" for _, block in scored
    ]
    return fit_chunks(chunks, PASSAGES_BUDGET, limit=MAX_PASSAGES)


def _recent(session: Session, conversation_id: str | None) -> str:
    if conversation_id is None:
        return ""
    messages = list(
        session.scalars(
            select(ConversationMessage)
            .where(ConversationMessage.session_id == conversation_id)
            .order_by(ConversationMessage.created_at.desc())
        )
    )
    prior = list(reversed(messages[:2]))
    chunks = [f"{message.role}: {message.content}" for message in prior]
    text = fit_chunks(chunks, RECENT_BUDGET, limit=2)
    return text


def pack_tokens(pack: ContextPack) -> dict[str, int]:
    return {
        "company": estimate_tokens(pack.company_text),
        "thesis": estimate_tokens(pack.thesis_text),
        "memory": estimate_tokens(pack.memory_text),
        "knowledge": estimate_tokens(pack.knowledge_text),
        "external_data": estimate_tokens(pack.external_data_text),
        "changes": estimate_tokens(pack.changes_text),
        "passages": estimate_tokens(pack.passages_text),
        "recent": estimate_tokens(pack.recent_text),
    }
