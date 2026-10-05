from sqlalchemy import select
from sqlalchemy.orm import Session

from aivi.domain.enums import Actor
from aivi.domain.models import Company, WatchlistItem
from aivi.security.audit import write_audit
from aivi.security.policy import require_watchlist

ALLOWED_CADENCE = {"3d", "weekly", "monthly", "event"}


def save_watchlist(
    session: Session,
    *,
    actor: Actor,
    company: Company,
    cadence: str,
) -> WatchlistItem:
    require_watchlist(actor)
    if cadence not in ALLOWED_CADENCE:
        raise ValueError("cadence must be 3d, weekly, monthly, or event")
    existing = session.scalar(
        select(WatchlistItem).where(WatchlistItem.company_id == company.id)
    )
    if existing is None:
        existing = WatchlistItem(company_id=company.id, cadence=cadence, enabled=True)
        session.add(existing)
        session.flush()
        action = "add_watchlist"
    else:
        existing.cadence = cadence
        existing.enabled = True
        action = "update_watchlist"
    write_audit(
        session,
        actor=actor,
        action=action,
        entity_type="watchlist_items",
        entity_id=existing.id,
        after={"ticker": company.ticker, "cadence": cadence},
    )
    return existing
