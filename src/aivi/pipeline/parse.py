import hashlib
import re
from dataclasses import dataclass

METRIC_LINE = re.compile(
    r"^METRIC\s+([a-zA-Z0-9_]+)\s+(\d{4}(?:Q[1-4])?)\s+(\S+)\s*$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class BlockDraft:
    ordinal: int
    section_path: str
    block_type: str
    text: str
    page_start: int | None = None
    page_end: int | None = None


def parse_bytes(data: bytes, suffix: str) -> list[BlockDraft]:
    if suffix == ".pdf":
        return _parse_pdf(data)
    text = data.decode("utf-8-sig")
    return _parse_text(text, page=None)


def _parse_pdf(data: bytes) -> list[BlockDraft]:
    from io import BytesIO

    from pypdf import PdfReader

    reader = PdfReader(BytesIO(data))
    drafts: list[BlockDraft] = []
    ordinal = 0
    for page_number, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        page_drafts = _parse_text(text, page=page_number, ordinal_start=ordinal)
        drafts.extend(page_drafts)
        ordinal += len(page_drafts)
    return drafts


def _parse_text(text: str, page: int | None, ordinal_start: int = 0) -> list[BlockDraft]:
    drafts: list[BlockDraft] = []
    section = ""
    ordinal = ordinal_start
    paragraph: list[str] = []

    def flush() -> None:
        nonlocal ordinal
        body = "\n".join(paragraph).strip()
        paragraph.clear()
        if not body:
            return
        drafts.append(
            BlockDraft(
                ordinal=ordinal,
                section_path=section,
                block_type="paragraph",
                text=body,
                page_start=page,
                page_end=page,
            )
        )
        ordinal += 1

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            flush()
            continue
        if line.startswith("#"):
            flush()
            section = line.lstrip("#").strip()
            drafts.append(
                BlockDraft(
                    ordinal=ordinal,
                    section_path=section,
                    block_type="heading",
                    text=section,
                    page_start=page,
                    page_end=page,
                )
            )
            ordinal += 1
            continue
        if METRIC_LINE.match(line) or _is_table_line(line):
            flush()
            drafts.append(
                BlockDraft(
                    ordinal=ordinal,
                    section_path=section,
                    block_type="metric" if METRIC_LINE.match(line) else "table",
                    text=line,
                    page_start=page,
                    page_end=page,
                )
            )
            ordinal += 1
            continue
        paragraph.append(line)
    flush()
    return drafts


def _is_table_line(line: str) -> bool:
    return line.startswith("|") and line.endswith("|")


def block_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
