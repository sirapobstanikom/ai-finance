from sqlalchemy import select
from sqlalchemy.orm import Session

from aivi.domain.models import Alias, Company, utcnow
from aivi.security.policy import NotFound


def upsert_company(
    session: Session,
    *,
    ticker: str,
    market: str = "SET",
    name_th: str | None = None,
    name_en: str | None = None,
    sector: str | None = None,
    industry: str | None = None,
    aliases: list[str] | None = None,
) -> Company:
    normalized = ticker.strip().upper()
    existing = session.scalar(
        select(Company).where(Company.ticker == normalized, Company.market == market)
    )
    if existing is not None:
        return existing
    company = Company(
        ticker=normalized,
        market=market,
        name_th=name_th,
        name_en=name_en,
        sector=sector,
        industry=industry,
        created_at=utcnow(),
        updated_at=utcnow(),
    )
    session.add(company)
    session.flush()
    names = [normalized, *(aliases or [])]
    seen: set[str] = set()
    for name in names:
        cleaned = name.strip()
        if not cleaned or cleaned.casefold() in seen:
            continue
        seen.add(cleaned.casefold())
        session.add(Alias(company_id=company.id, alias=cleaned))
    return company


def get_company(session: Session, ticker: str, market: str = "SET") -> Company:
    company = session.scalar(
        select(Company).where(Company.ticker == ticker.strip().upper(), Company.market == market)
    )
    if company is None:
        raise NotFound(f"company {ticker} not found")
    return company
