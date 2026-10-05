import logging
import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from aivi.domain.enums import Actor
from aivi.domain.models import (
    ChangeEvent,
    Extraction,
    MetricObservation,
    Thesis,
    ThesisPoint,
    utcnow,
)
from aivi.pipeline.catalog import format_ratio, parse_number, period_key, spec_for
from aivi.pipeline.parse import METRIC_LINE
from aivi.security.audit import write_audit
from aivi.security.policy import require_metrics

log = logging.getLogger(__name__)

EXTRACTOR_NAME = "metric_lines"
EXTRACTOR_VERSION = "1"
TABLE_ROW = re.compile(r"^\|\s*([a-zA-Z0-9_]+)\s*\|\s*(\d{4}(?:Q[1-4])?)\s*\|\s*([^|]+)\|")


def metrics_in_text(text: str) -> list[tuple[str, str, float]]:
    found: list[tuple[str, str, float]] = []
    for line in text.splitlines():
        stripped = line.strip()
        metric_match = METRIC_LINE.match(stripped)
        if metric_match:
            found.append(
                (
                    metric_match.group(1).lower(),
                    metric_match.group(2),
                    parse_number(metric_match.group(3)),
                )
            )
            continue
        table_match = TABLE_ROW.match(stripped)
        if table_match is None:
            continue
        key = table_match.group(1).lower()
        if key in {"metric", "---", "period"}:
            continue
        if set(key) <= {"-"}:
            continue
        found.append((key, table_match.group(2), parse_number(table_match.group(3).strip())))
    return found


def extract_block(
    session: Session,
    *,
    actor: Actor,
    company_id: str,
    document_id: str,
    block_id: str,
    block_hash: str,
    text: str,
) -> tuple[int, list[ChangeEvent]]:
    """Return how many extraction rows were created and any new change events.

    A repeated block hash reuses the extraction row and does not call a model.
    Metric lines are read by code. Identical company/period/value rows are skipped.
    """
    require_metrics(actor)
    existing = session.scalar(
        select(Extraction).where(
            Extraction.input_hash == block_hash,
            Extraction.extractor_name == EXTRACTOR_NAME,
            Extraction.extractor_version == EXTRACTOR_VERSION,
        )
    )
    created = 0
    if existing is None:
        parsed = metrics_in_text(text)
        existing = Extraction(
            block_id=block_id,
            extractor_name=EXTRACTOR_NAME,
            extractor_version=EXTRACTOR_VERSION,
            input_hash=block_hash,
            model_id=None,
            output_json={"metrics": [{"key": k, "period": p, "value": v} for k, p, v in parsed]},
        )
        session.add(existing)
        session.flush()
        created = 1
        log.info(
            "extraction cached hash=%s metrics=%s",
            block_hash[:12],
            len(parsed),
        )
    else:
        raw_metrics = existing.output_json.get("metrics", [])
        parsed = [(item["key"], item["period"], float(item["value"])) for item in raw_metrics]

    changes: list[ChangeEvent] = []
    for key, period, value in parsed:
        change = record_observation(
            session,
            actor=actor,
            company_id=company_id,
            metric_key=key,
            period=period,
            value=value,
            source_document_id=document_id,
            source_block_id=block_id,
            source_extraction_id=existing.id,
        )
        if change is not None:
            changes.append(change)
    return created, changes


def record_observation(
    session: Session,
    *,
    actor: Actor,
    company_id: str,
    metric_key: str,
    period: str,
    value: float,
    source_document_id: str | None,
    source_block_id: str | None,
    source_extraction_id: str | None,
    confidence: float = 1.0,
) -> ChangeEvent | None:
    require_metrics(actor)
    duplicate = session.scalar(
        select(MetricObservation).where(
            MetricObservation.company_id == company_id,
            MetricObservation.metric_key == metric_key,
            MetricObservation.period == period,
            MetricObservation.value == value,
        )
    )
    if duplicate is not None:
        return None

    observation = MetricObservation(
        company_id=company_id,
        metric_key=metric_key,
        period=period,
        value=value,
        unit="ratio",
        source_document_id=source_document_id,
        source_block_id=source_block_id,
        source_extraction_id=source_extraction_id,
        confidence=confidence,
        observed_at=utcnow(),
    )
    session.add(observation)
    session.flush()
    write_audit(
        session,
        actor=actor,
        action="insert_metric",
        entity_type="metric_observations",
        entity_id=observation.id,
        after={"metric_key": metric_key, "period": period, "value": value},
    )
    return _diff_against_prior(session, observation)


def _diff_against_prior(session: Session, observation: MetricObservation) -> ChangeEvent | None:
    others = list(
        session.scalars(
            select(MetricObservation).where(
                MetricObservation.company_id == observation.company_id,
                MetricObservation.metric_key == observation.metric_key,
                MetricObservation.id != observation.id,
            )
        )
    )
    same_period = [row for row in others if row.period == observation.period]
    if same_period:
        prior = max(same_period, key=lambda row: row.observed_at)
        if abs(prior.value - observation.value) < 1e-9:
            return None
        return _create_change(session, observation, prior, "restatement")

    earlier = [row for row in others if period_key(row.period) < period_key(observation.period)]
    if not earlier:
        return None
    prior = max(earlier, key=lambda row: (period_key(row.period), row.observed_at))
    if abs(prior.value - observation.value) < 1e-9:
        return None
    return _create_change(session, observation, prior, "new_period")


def _create_change(
    session: Session,
    current: MetricObservation,
    prior: MetricObservation,
    change_kind: str,
) -> ChangeEvent:
    spec = spec_for(current.metric_key)
    delta = abs(current.value - prior.value)
    importance = "high" if delta >= spec.threshold else "low"
    if spec.higher_is_better:
        if current.value < prior.value:
            impact = "negative"
        elif current.value > prior.value:
            impact = "positive"
        else:
            impact = "neutral"
    else:
        if current.value < prior.value:
            impact = "positive"
        elif current.value > prior.value:
            impact = "negative"
        else:
            impact = "neutral"
    point = _matching_thesis_point(session, current.company_id, spec.thesis_label)
    before = format_ratio(prior.value)
    after = format_ratio(current.value)
    event = ChangeEvent(
        company_id=current.company_id,
        change_kind=change_kind,
        subject=spec.subject,
        before_value=before,
        after_value=after,
        importance=importance,
        materiality=importance,
        impact_hint=impact,
        thesis_point_id=point.id if point is not None else None,
        source_document_id=current.source_document_id,
        summary=format_change_summary(
            subject=spec.subject,
            before=before,
            after=after,
            impact=impact,
            thesis_label=point.label if point is not None else None,
            importance=importance,
        ),
        detected_at=utcnow(),
    )
    session.add(event)
    session.flush()
    log.info(
        "change detected subject=%s %s -> %s importance=%s",
        spec.subject,
        before,
        after,
        importance,
    )
    return event


def format_change_summary(
    *,
    subject: str,
    before: str,
    after: str,
    impact: str,
    thesis_label: str | None,
    importance: str,
) -> str:
    related = thesis_label or "none"
    return "\n".join(
        [
            "CHANGE DETECTED",
            subject,
            f"{before} → {after}",
            f"Potential Impact: {impact.capitalize()}",
            f"Related Thesis: {related}",
            f"Importance: {importance.capitalize()}",
        ]
    )


def _matching_thesis_point(session: Session, company_id: str, label: str) -> ThesisPoint | None:
    thesis = session.scalar(
        select(Thesis).where(Thesis.company_id == company_id, Thesis.status == "active")
    )
    if thesis is None:
        return None
    return session.scalar(
        select(ThesisPoint).where(ThesisPoint.thesis_id == thesis.id, ThesisPoint.label == label)
    )


def relink_changes(session: Session, company_id: str) -> None:
    thesis = session.scalar(
        select(Thesis).where(Thesis.company_id == company_id, Thesis.status == "active")
    )
    if thesis is None:
        return
    points = list(session.scalars(select(ThesisPoint).where(ThesisPoint.thesis_id == thesis.id)))
    by_label = {point.label: point for point in points}
    events = list(
        session.scalars(
            select(ChangeEvent).where(
                ChangeEvent.company_id == company_id,
                ChangeEvent.thesis_point_id.is_(None),
            )
        )
    )
    for event in events:
        point = by_label.get(event.subject)
        if point is None:
            continue
        event.thesis_point_id = point.id
        event.summary = format_change_summary(
            subject=event.subject,
            before=event.before_value,
            after=event.after_value,
            impact=event.impact_hint,
            thesis_label=point.label,
            importance=event.importance,
        )
