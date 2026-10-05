import logging
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from aivi.domain.enums import Actor, ThesisPointStatus
from aivi.domain.models import Company, Thesis, ThesisPoint, utcnow
from aivi.pipeline.extract import relink_changes
from aivi.security.audit import write_audit
from aivi.security.policy import NotFound, require_thesis

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class ThesisPointInput:
    label: str
    statement: str
    importance: str = "high"


def create_thesis(
    session: Session,
    *,
    actor: Actor,
    company_id: str,
    summary: str,
    points: list[ThesisPointInput],
) -> Thesis:
    require_thesis(actor)
    if not points:
        raise ValueError("A thesis needs at least one point")
    company = session.get(Company, company_id)
    if company is None:
        raise NotFound("company not found")
    current = session.scalar(
        select(Thesis).where(Thesis.company_id == company_id, Thesis.status == "active")
    )
    version = 1 if current is None else current.version + 1
    if current is not None:
        current.status = "superseded"
    thesis = Thesis(
        company_id=company_id,
        version=version,
        status="active",
        summary=summary,
        approved_at=utcnow(),
        approved_by=actor.value,
    )
    session.add(thesis)
    session.flush()
    for index, point in enumerate(points, start=1):
        session.add(
            ThesisPoint(
                thesis_id=thesis.id,
                ordinal=index,
                label=point.label.strip(),
                statement=point.statement.strip(),
                status=ThesisPointStatus.UNTESTED.value,
                importance=point.importance,
            )
        )
    session.flush()
    relink_changes(session, company_id)
    write_audit(
        session,
        actor=actor,
        action="create_thesis",
        entity_type="theses",
        entity_id=thesis.id,
        before={"previous_id": current.id} if current is not None else None,
        after={"version": version, "points": [point.label for point in points]},
    )
    log.info("thesis saved company=%s version=%s", company.ticker, version)
    return thesis


def active_thesis(session: Session, company_id: str) -> Thesis | None:
    return session.scalar(
        select(Thesis).where(Thesis.company_id == company_id, Thesis.status == "active")
    )


def thesis_points(session: Session, thesis_id: str) -> list[ThesisPoint]:
    return list(
        session.scalars(
            select(ThesisPoint)
            .where(ThesisPoint.thesis_id == thesis_id)
            .order_by(ThesisPoint.ordinal)
        )
    )
