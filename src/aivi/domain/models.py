from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import (
    JSON,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def new_id() -> str:
    return str(uuid4())


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)


class Base(DeclarativeBase):
    pass


class Company(Base):
    __tablename__ = "companies"
    __table_args__ = (UniqueConstraint("ticker", "market", name="uq_company_ticker_market"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    ticker: Mapped[str] = mapped_column(String(16), nullable=False)
    market: Mapped[str] = mapped_column(String(16), nullable=False, default="SET")
    name_th: Mapped[str | None] = mapped_column(String(255))
    name_en: Mapped[str | None] = mapped_column(String(255))
    sector: Mapped[str | None] = mapped_column(String(128))
    industry: Mapped[str | None] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow)


class Alias(Base):
    __tablename__ = "aliases"
    __table_args__ = (UniqueConstraint("company_id", "alias", name="uq_alias"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.id"), nullable=False, index=True)
    alias: Mapped[str] = mapped_column(String(255), nullable=False)


class Document(Base):
    __tablename__ = "documents"
    __table_args__ = (
        UniqueConstraint("company_id", "content_hash", name="uq_document_hash"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.id"), nullable=False, index=True)
    doc_type: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    source_url: Mapped[str | None] = mapped_column(String(1000))
    source_name: Mapped[str | None] = mapped_column(String(255))
    published_at: Mapped[datetime | None] = mapped_column()
    ingested_at: Mapped[datetime] = mapped_column(default=utcnow)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    storage_uri: Mapped[str] = mapped_column(String(1000), nullable=False)
    language: Mapped[str] = mapped_column(String(16), nullable=False, default="th")
    parser_status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    byte_size: Mapped[int] = mapped_column(Integer, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text)


class DocumentBlock(Base):
    __tablename__ = "document_blocks"
    __table_args__ = (UniqueConstraint("document_id", "ordinal", name="uq_block_ordinal"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id"), nullable=False, index=True)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    section_path: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    block_type: Mapped[str] = mapped_column(String(32), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    page_start: Mapped[int | None] = mapped_column(Integer)
    page_end: Mapped[int | None] = mapped_column(Integer)
    token_estimate: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class Extraction(Base):
    __tablename__ = "extractions"
    __table_args__ = (
        UniqueConstraint(
            "input_hash",
            "extractor_name",
            "extractor_version",
            name="uq_extraction_cache",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    block_id: Mapped[str | None] = mapped_column(ForeignKey("document_blocks.id"), index=True)
    extractor_name: Mapped[str] = mapped_column(String(64), nullable=False)
    extractor_version: Mapped[str] = mapped_column(String(32), nullable=False)
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    model_id: Mapped[str | None] = mapped_column(String(128))
    output_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class MetricObservation(Base):
    __tablename__ = "metric_observations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.id"), nullable=False, index=True)
    metric_key: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    period: Mapped[str] = mapped_column(String(16), nullable=False)
    value: Mapped[float] = mapped_column(Float, nullable=False)
    unit: Mapped[str] = mapped_column(String(32), nullable=False, default="ratio")
    source_document_id: Mapped[str | None] = mapped_column(ForeignKey("documents.id"))
    source_block_id: Mapped[str | None] = mapped_column(ForeignKey("document_blocks.id"))
    source_extraction_id: Mapped[str | None] = mapped_column(ForeignKey("extractions.id"))
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    observed_at: Mapped[datetime] = mapped_column(default=utcnow)


class KnowledgeItem(Base):
    __tablename__ = "knowledge_items"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.id"), nullable=False, index=True)
    type: Mapped[str] = mapped_column(String(32), nullable=False)
    section: Mapped[str] = mapped_column(String(64), nullable=False)
    statement: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)
    importance: Mapped[str] = mapped_column(String(16), nullable=False, default="medium")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="proposed")
    created_by: Mapped[str] = mapped_column(String(32), nullable=False)
    source_date: Mapped[datetime | None] = mapped_column()
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    supersedes_id: Mapped[str | None] = mapped_column(String(36))
    related_thesis_point_id: Mapped[str | None] = mapped_column(String(36))
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class KnowledgeSource(Base):
    __tablename__ = "knowledge_sources"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    knowledge_item_id: Mapped[str] = mapped_column(
        ForeignKey("knowledge_items.id"), nullable=False, index=True
    )
    document_id: Mapped[str | None] = mapped_column(ForeignKey("documents.id"))
    block_id: Mapped[str | None] = mapped_column(ForeignKey("document_blocks.id"))


class Thesis(Base):
    __tablename__ = "theses"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.id"), nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    approved_at: Mapped[datetime | None] = mapped_column()
    approved_by: Mapped[str | None] = mapped_column(String(32))


class ThesisPoint(Base):
    __tablename__ = "thesis_points"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    thesis_id: Mapped[str] = mapped_column(ForeignKey("theses.id"), nullable=False, index=True)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    label: Mapped[str] = mapped_column(String(255), nullable=False)
    statement: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="untested")
    importance: Mapped[str] = mapped_column(String(16), nullable=False, default="high")


class ThesisAssessment(Base):
    __tablename__ = "thesis_assessments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    thesis_point_id: Mapped[str] = mapped_column(ForeignKey("thesis_points.id"), nullable=False)
    change_event_id: Mapped[str] = mapped_column(ForeignKey("change_events.id"), nullable=False)
    impact: Mapped[str] = mapped_column(String(16), nullable=False)
    materiality: Mapped[str] = mapped_column(String(16), nullable=False)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    model_id: Mapped[str | None] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="proposed")
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class Memory(Base):
    __tablename__ = "memories"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    company_id: Mapped[str | None] = mapped_column(ForeignKey("companies.id"), index=True)
    memory_type: Mapped[str] = mapped_column(String(64), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    importance: Mapped[int] = mapped_column(Integer, nullable=False, default=2)
    source_conversation_id: Mapped[str | None] = mapped_column(String(36))
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    last_retrieved_at: Mapped[datetime | None] = mapped_column()
    retrieve_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    token_estimate: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class ConversationSession(Base):
    __tablename__ = "conversation_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.id"), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    started_at: Mapped[datetime] = mapped_column(default=utcnow)
    ended_at: Mapped[datetime | None] = mapped_column()


class ConversationMessage(Base):
    __tablename__ = "conversation_messages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    session_id: Mapped[str] = mapped_column(
        ForeignKey("conversation_sessions.id"), nullable=False, index=True
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class ChangeEvent(Base):
    __tablename__ = "change_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.id"), nullable=False, index=True)
    change_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    subject: Mapped[str] = mapped_column(String(255), nullable=False)
    before_value: Mapped[str] = mapped_column(String(255), nullable=False)
    after_value: Mapped[str] = mapped_column(String(255), nullable=False)
    importance: Mapped[str] = mapped_column(String(16), nullable=False)
    materiality: Mapped[str] = mapped_column(String(16), nullable=False)
    impact_hint: Mapped[str] = mapped_column(String(16), nullable=False)
    thesis_point_id: Mapped[str | None] = mapped_column(ForeignKey("thesis_points.id"))
    source_document_id: Mapped[str | None] = mapped_column(ForeignKey("documents.id"))
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    detected_at: Mapped[datetime] = mapped_column(default=utcnow)


class Proposal(Base):
    __tablename__ = "proposals"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.id"), nullable=False, index=True)
    target_table: Mapped[str] = mapped_column(String(64), nullable=False)
    operation: Mapped[str] = mapped_column(String(64), nullable=False)
    payload_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    proposed_by: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    decided_at: Mapped[datetime | None] = mapped_column()


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    actor: Mapped[str] = mapped_column(String(32), nullable=False)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(36), nullable=False)
    before_json: Mapped[dict | None] = mapped_column(JSON)
    after_json: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class WatchlistItem(Base):
    __tablename__ = "watchlist_items"
    __table_args__ = (UniqueConstraint("company_id", name="uq_watchlist_company"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.id"), nullable=False)
    cadence: Mapped[str] = mapped_column(String(32), nullable=False, default="weekly")
    enabled: Mapped[bool] = mapped_column(nullable=False, default=True)
    last_checked_at: Mapped[datetime | None] = mapped_column()
    next_check_at: Mapped[datetime | None] = mapped_column()


class ExternalSnapshot(Base):
    __tablename__ = "external_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "company_id",
            "source",
            "data_type",
            "content_hash",
            name="uq_external_snapshot_content",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    company_id: Mapped[str] = mapped_column(
        ForeignKey("companies.id"), nullable=False, index=True
    )
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    data_type: Mapped[str] = mapped_column(String(64), nullable=False)
    source_url: Mapped[str] = mapped_column(String(1000), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    payload_json: Mapped[dict | list] = mapped_column(JSON, nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(default=utcnow)
