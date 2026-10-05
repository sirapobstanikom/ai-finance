import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from aivi.domain.enums import Actor
from aivi.domain.models import Company, ConversationMessage, ConversationSession, Memory, utcnow
from aivi.knowledge.proposals import propose_thesis_summary
from aivi.security.audit import write_audit
from aivi.security.policy import NotFound, require_memory
from aivi.tokens import estimate_tokens

log = logging.getLogger(__name__)

REMEMBER_MARKERS = (
    "จำไว้",
    "สมมติว่า",
    "ฉันคิดว่า",
    "ปรับ thesis",
    "อัปเดต thesis",
    "update thesis",
)


def close_conversation(session: Session, conversation_id: str, actor: Actor) -> list[Memory]:
    """Store a one-line index and only the lines that look durable.

    Full turns stay in conversation_messages and are not copied into memory.
    """
    require_memory(actor)
    conversation = session.get(ConversationSession, conversation_id)
    if conversation is None:
        raise NotFound("conversation not found")
    if conversation.ended_at is not None:
        return list(
            session.scalars(
                select(Memory).where(Memory.source_conversation_id == conversation_id)
            )
        )
    company = session.get(Company, conversation.company_id)
    if company is None:
        raise NotFound("company not found")
    messages = list(
        session.scalars(
            select(ConversationMessage)
            .where(ConversationMessage.session_id == conversation_id)
            .order_by(ConversationMessage.created_at)
        )
    )
    user_lines: list[str] = []
    for message in messages:
        if message.role != "user":
            continue
        user_lines.extend(line.strip() for line in message.content.splitlines() if line.strip())
    first_line = user_lines[0][:120] if user_lines else conversation.title or "session"
    created: list[Memory] = [
        _memory(
            company_id=company.id,
            conversation_id=conversation.id,
            memory_type="conversation_summary",
            summary=f"{conversation.started_at.date()} {company.ticker} {first_line}",
            importance=2,
        )
    ]
    for line in user_lines:
        lowered = line.casefold()
        if not any(marker.casefold() in lowered for marker in REMEMBER_MARKERS):
            continue
        created.append(
            _memory(
                company_id=company.id,
                conversation_id=conversation.id,
                memory_type="working_context",
                summary=line[:240],
                importance=4,
            )
        )
        if "ปรับ thesis" in lowered or "อัปเดต thesis" in lowered or "update thesis" in lowered:
            propose_thesis_summary(
                session,
                actor=actor,
                company_id=company.id,
                summary=line[:1000],
                reason="conversation asked to update the thesis",
            )
    for memory in created:
        session.add(memory)
    conversation.ended_at = utcnow()
    session.flush()
    write_audit(
        session,
        actor=actor,
        action="close_conversation",
        entity_type="conversation_sessions",
        entity_id=conversation.id,
        after={"memories": len(created)},
    )
    log.info("conversation closed id=%s memories=%s", conversation.id, len(created))
    return created


def _memory(
    *,
    company_id: str,
    conversation_id: str,
    memory_type: str,
    summary: str,
    importance: int,
) -> Memory:
    return Memory(
        company_id=company_id,
        memory_type=memory_type,
        summary=summary,
        importance=importance,
        source_conversation_id=conversation_id,
        token_estimate=estimate_tokens(summary),
    )
