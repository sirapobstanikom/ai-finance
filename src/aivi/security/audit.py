from sqlalchemy.orm import Session

from aivi.domain.enums import Actor
from aivi.domain.models import AuditLog


def write_audit(
    session: Session,
    *,
    actor: Actor,
    action: str,
    entity_type: str,
    entity_id: str,
    before: dict | None = None,
    after: dict | None = None,
) -> None:
    session.add(
        AuditLog(
            actor=actor.value,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            before_json=before,
            after_json=after,
        )
    )
