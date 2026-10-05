import hashlib
import logging

from sqlalchemy.orm import Session

from aivi.domain.enums import Actor, KnowledgeSection, KnowledgeType
from aivi.domain.models import Company, KnowledgeItem, KnowledgeSource, Proposal, utcnow
from aivi.knowledge.thesis import ThesisPointInput, create_thesis
from aivi.security.audit import write_audit
from aivi.security.policy import (
    NotFound,
    require_active_knowledge,
    require_approve,
    require_proposal,
)

log = logging.getLogger(__name__)


def statement_hash(company_id: str, statement: str) -> str:
    normalized = " ".join(statement.split()).casefold()
    return hashlib.sha256(f"{company_id}|{normalized}".encode("utf-8")).hexdigest()


def add_knowledge(
    session: Session,
    *,
    actor: Actor,
    company_id: str,
    knowledge_type: KnowledgeType,
    section: KnowledgeSection,
    statement: str,
    confidence: float = 0.8,
    importance: str = "medium",
    document_id: str | None = None,
    block_id: str | None = None,
    related_thesis_point_id: str | None = None,
) -> KnowledgeItem:
    require_active_knowledge(actor)
    if session.get(Company, company_id) is None:
        raise NotFound("company not found")
    item = KnowledgeItem(
        company_id=company_id,
        type=knowledge_type.value,
        section=section.value,
        statement=statement.strip(),
        confidence=confidence,
        importance=importance,
        status="active",
        created_by=actor.value,
        source_date=utcnow(),
        content_hash=statement_hash(company_id, statement),
        related_thesis_point_id=related_thesis_point_id,
    )
    session.add(item)
    session.flush()
    if document_id or block_id:
        session.add(
            KnowledgeSource(
                knowledge_item_id=item.id,
                document_id=document_id,
                block_id=block_id,
            )
        )
    write_audit(
        session,
        actor=actor,
        action="insert_knowledge",
        entity_type="knowledge_items",
        entity_id=item.id,
        after={"type": item.type, "section": item.section},
    )
    return item


def propose_knowledge(
    session: Session,
    *,
    actor: Actor,
    company_id: str,
    knowledge_type: KnowledgeType,
    section: KnowledgeSection,
    statement: str,
    confidence: float = 0.5,
    importance: str = "medium",
    reason: str = "",
) -> Proposal:
    require_proposal(actor)
    proposal = Proposal(
        company_id=company_id,
        target_table="knowledge_items",
        operation="insert_knowledge",
        payload_json={
            "type": knowledge_type.value,
            "section": section.value,
            "statement": statement.strip(),
            "confidence": confidence,
            "importance": importance,
        },
        proposed_by=actor.value,
        status="pending",
        reason=reason,
    )
    session.add(proposal)
    session.flush()
    write_audit(
        session,
        actor=actor,
        action="create_proposal",
        entity_type="proposals",
        entity_id=proposal.id,
        after={"operation": proposal.operation},
    )
    log.info("proposal created id=%s operation=%s", proposal.id, proposal.operation)
    return proposal


def propose_thesis_summary(
    session: Session,
    *,
    actor: Actor,
    company_id: str,
    summary: str,
    reason: str,
) -> Proposal:
    require_proposal(actor)
    proposal = Proposal(
        company_id=company_id,
        target_table="theses",
        operation="revise_thesis_summary",
        payload_json={"summary": summary.strip()},
        proposed_by=actor.value,
        status="pending",
        reason=reason,
    )
    session.add(proposal)
    session.flush()
    write_audit(
        session,
        actor=actor,
        action="create_proposal",
        entity_type="proposals",
        entity_id=proposal.id,
        after={"operation": proposal.operation},
    )
    return proposal


def approve_proposal(session: Session, proposal_id: str, actor: Actor) -> Proposal:
    require_approve(actor)
    proposal = session.get(Proposal, proposal_id)
    if proposal is None:
        raise NotFound("proposal not found")
    if proposal.status != "pending":
        raise ValueError("proposal is already decided")
    if proposal.operation == "insert_knowledge":
        payload = proposal.payload_json
        add_knowledge(
            session,
            actor=actor,
            company_id=proposal.company_id,
            knowledge_type=KnowledgeType(payload["type"]),
            section=KnowledgeSection(payload["section"]),
            statement=payload["statement"],
            confidence=float(payload.get("confidence", 0.5)),
            importance=payload.get("importance", "medium"),
        )
    elif proposal.operation == "revise_thesis_summary":
        _apply_thesis_summary(session, proposal, actor)
    else:
        raise ValueError(f"unsupported proposal operation: {proposal.operation}")
    proposal.status = "approved"
    proposal.decided_at = utcnow()
    write_audit(
        session,
        actor=actor,
        action="approve_proposal",
        entity_type="proposals",
        entity_id=proposal.id,
        after={"operation": proposal.operation, "status": "approved"},
    )
    return proposal


def _apply_thesis_summary(session: Session, proposal: Proposal, actor: Actor) -> None:
    from aivi.knowledge.thesis import active_thesis, thesis_points

    current = active_thesis(session, proposal.company_id)
    if current is None:
        raise ValueError("no active thesis to revise")
    points = [
        ThesisPointInput(label=point.label, statement=point.statement, importance=point.importance)
        for point in thesis_points(session, current.id)
    ]
    create_thesis(
        session,
        actor=actor,
        company_id=proposal.company_id,
        summary=proposal.payload_json["summary"],
        points=points,
    )
