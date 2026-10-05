import hashlib
import logging
import re
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from aivi.domain.enums import Actor
from aivi.domain.models import Document, DocumentBlock
from aivi.pipeline.extract import extract_block
from aivi.pipeline.parse import block_hash, parse_bytes
from aivi.security.audit import write_audit
from aivi.security.policy import require_documents
from aivi.storage.raw_store import RawStore

log = logging.getLogger(__name__)

_ALLOWED_SUFFIX = {".txt", ".md", ".pdf"}


@dataclass
class IngestResult:
    document_id: str
    created: bool
    blocks_added: int
    extractions_added: int
    change_ids: list[str]


def ingest_bytes(
    session: Session,
    raw_store: RawStore,
    *,
    actor: Actor,
    company_id: str,
    filename: str,
    data: bytes,
    doc_type: str,
    title: str | None = None,
    language: str = "th",
) -> IngestResult:
    require_documents(actor)
    suffix = Path(filename).suffix.lower()
    if suffix not in _ALLOWED_SUFFIX:
        raise ValueError("Only .txt, .md, and .pdf files can be ingested")
    digest = hashlib.sha256(data).hexdigest()
    existing = session.scalar(
        select(Document).where(
            Document.company_id == company_id,
            Document.content_hash == digest,
        )
    )
    if existing is not None:
        log.info("ingest skipped duplicate company=%s hash=%s", company_id, digest[:12])
        return IngestResult(
            document_id=existing.id,
            created=False,
            blocks_added=0,
            extractions_added=0,
            change_ids=[],
        )

    storage_uri = str(raw_store.put(digest, data, suffix))
    document = Document(
        company_id=company_id,
        doc_type=doc_type,
        title=title or Path(filename).name,
        content_hash=digest,
        storage_uri=storage_uri,
        language=language,
        parser_status="pending",
        byte_size=len(data),
    )
    session.add(document)
    session.flush()

    drafts = parse_bytes(data, suffix)
    blocks: list[DocumentBlock] = []
    for draft in drafts:
        block = DocumentBlock(
            document_id=document.id,
            ordinal=draft.ordinal,
            section_path=draft.section_path,
            block_type=draft.block_type,
            text=draft.text,
            content_hash=block_hash(draft.text),
            page_start=draft.page_start,
            page_end=draft.page_end,
            token_estimate=max(1, len(draft.text) // 4),
        )
        session.add(block)
        blocks.append(block)
    session.flush()

    extractions_added = 0
    change_ids: list[str] = []
    for block in blocks:
        if block.block_type == "heading":
            continue
        added, changes = extract_block(
            session,
            actor=Actor.PIPELINE if actor == Actor.OWNER else actor,
            company_id=company_id,
            document_id=document.id,
            block_id=block.id,
            block_hash=block.content_hash,
            text=block.text,
        )
        extractions_added += added
        change_ids.extend(change.id for change in changes)

    document.parser_status = "extracted"
    write_audit(
        session,
        actor=actor,
        action="ingest_document",
        entity_type="documents",
        entity_id=document.id,
        after={"content_hash": digest, "blocks": len(blocks), "doc_type": doc_type},
    )
    log.info(
        "ingested document=%s blocks=%s extractions=%s changes=%s",
        document.id,
        len(blocks),
        extractions_added,
        len(change_ids),
    )
    return IngestResult(
        document_id=document.id,
        created=True,
        blocks_added=len(blocks),
        extractions_added=extractions_added,
        change_ids=change_ids,
    )


def safe_filename(filename: str) -> str:
    name = Path(filename).name
    if name in {"", ".", ".."} or not re.fullmatch(r"[^\\/:*?\"<>|]+", name):
        raise ValueError("Invalid file name")
    return name
