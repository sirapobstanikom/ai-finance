from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from aivi.domain.models import Company, KnowledgeItem
from aivi.knowledge.thesis import active_thesis, thesis_points
from aivi.security.policy import NotFound

SECTION_FILES = {
    "profile": "company-profile.md",
    "business_model": "business-model.md",
    "management": "management.md",
    "moat": "competitive-advantage.md",
    "industry": "industry.md",
    "competitors": "competitors.md",
    "financials": "financial-history.md",
    "valuation": "valuation.md",
    "risks": "risks.md",
    "watchpoints": "watchpoints.md",
    "news": "news.md",
}


def export_company(session: Session, company_id: str, export_root: Path) -> Path:
    company = session.get(Company, company_id)
    if company is None:
        raise NotFound("company not found")
    folder = export_root / "companies" / company.ticker
    folder.mkdir(parents=True, exist_ok=True)
    thesis = active_thesis(session, company_id)
    thesis_path = folder / "investment-thesis.md"
    lines = [f"# Investment thesis — {company.ticker}", ""]
    if thesis is None:
        lines.append("No active thesis.")
    else:
        lines.append(f"Version: {thesis.version}")
        lines.append("")
        if thesis.summary:
            lines.append(thesis.summary)
            lines.append("")
        for point in thesis_points(session, thesis.id):
            lines.append(f"{point.ordinal}. {point.label}")
            lines.append("")
            lines.append(point.statement)
            lines.append("")
            lines.append(f"status: {point.status}")
            lines.append("")
    thesis_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")

    items = list(
        session.scalars(
            select(KnowledgeItem).where(
                KnowledgeItem.company_id == company_id,
                KnowledgeItem.status == "active",
            )
        )
    )
    grouped: dict[str, list[KnowledgeItem]] = {}
    for item in items:
        grouped.setdefault(item.section, []).append(item)
    for section, filename in SECTION_FILES.items():
        section_items = grouped.get(section, [])
        if not section_items:
            continue
        body = [f"# {company.ticker} — {section}", ""]
        for item in section_items:
            body.append(f"- ({item.type}) {item.statement}")
        (folder / filename).write_text("\n".join(body) + "\n", encoding="utf-8")
    return thesis_path
