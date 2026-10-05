import secrets
from collections.abc import Iterator
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, RedirectResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from aivi.domain.enums import Actor, KnowledgeSection, KnowledgeType
from aivi.domain.models import (
    ChangeEvent,
    Company,
    Document,
    ExternalSnapshot,
    KnowledgeItem,
    MetricObservation,
    Proposal,
)
from aivi.knowledge.exporter import export_company
from aivi.knowledge.proposals import add_knowledge, approve_proposal
from aivi.knowledge.thesis import ThesisPointInput, active_thesis, create_thesis, thesis_points
from aivi.memory.gate import close_conversation
from aivi.orchestrator.intent import detect_intent
from aivi.orchestrator.research import ask
from aivi.orchestrator.watchlist import save_watchlist
from aivi.pipeline.ingest import ingest_bytes, safe_filename
from aivi.security.session import (
    COOKIE_NAME,
    authenticate,
    issue_session,
    session_user,
)
from aivi.sources.set_market import SETMarketClient, SETSourceError, fetch_and_store
from aivi.storage.companies import get_company, upsert_company
from aivi.storage.raw_store import RawStore

router = APIRouter()


class CompanyIn(BaseModel):
    ticker: str
    market: str = "SET"
    name_th: str | None = None
    name_en: str | None = None
    sector: str | None = None
    industry: str | None = None
    aliases: list[str] = Field(default_factory=list)


class ThesisPointIn(BaseModel):
    label: str
    statement: str
    importance: str = "high"


class ThesisIn(BaseModel):
    summary: str = ""
    points: list[ThesisPointIn]


class KnowledgeIn(BaseModel):
    type: KnowledgeType
    section: KnowledgeSection
    statement: str
    confidence: float = 0.8
    importance: str = "medium"


class ChatIn(BaseModel):
    message: str
    conversation_id: str | None = None


class WatchlistIn(BaseModel):
    cadence: str = "weekly"


class LoginIn(BaseModel):
    username: str
    password: str


class SETFetchIn(BaseModel):
    ticker: str
    data_types: list[str] = Field(
        default_factory=lambda: ["security_profile", "delayed_quote"]
    )


def require_token(
    request: Request,
    authorization: str | None = Header(default=None),
) -> None:
    if session_user(
        request.cookies.get(COOKIE_NAME, ""),
        request.app.state.settings,
    ):
        return
    expected = request.app.state.settings.api_token
    if not expected:
        raise HTTPException(status_code=503, detail="API_TOKEN is not configured")
    if authorization is None or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")
    presented = authorization.removeprefix("Bearer ").strip()
    if not secrets.compare_digest(presented, expected):
        raise HTTPException(status_code=401, detail="Invalid token")


def db_session(request: Request) -> Iterator[Session]:
    session = request.app.state.session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def _page(request: Request, filename: str) -> FileResponse | RedirectResponse:
    if session_user(
        request.cookies.get(COOKIE_NAME, ""),
        request.app.state.settings,
    ) is None:
        return RedirectResponse("/login", status_code=303)
    return FileResponse(
        Path(__file__).with_name(filename),
        headers={"Cache-Control": "no-store"},
    )


@router.get("/", include_in_schema=False)
def home(request: Request) -> RedirectResponse:
    target = (
        "/chat"
        if session_user(
            request.cookies.get(COOKIE_NAME, ""),
            request.app.state.settings,
        )
        else "/login"
    )
    return RedirectResponse(target, status_code=303)


@router.get("/login", include_in_schema=False)
def login_page(request: Request) -> Response:
    if session_user(
        request.cookies.get(COOKIE_NAME, ""),
        request.app.state.settings,
    ):
        return RedirectResponse("/chat", status_code=303)
    return FileResponse(
        Path(__file__).with_name("login.html"),
        headers={"Cache-Control": "no-store"},
    )


@router.get("/chat", include_in_schema=False)
def chat_page(request: Request) -> Response:
    return _page(request, "chat.html")


@router.get("/set-fetch", include_in_schema=False)
def set_fetch_page(request: Request) -> Response:
    return _page(request, "set-fetch.html")


@router.get("/company-data", include_in_schema=False)
def company_data_page(request: Request) -> Response:
    return _page(request, "company-data.html")


@router.get("/app.css", include_in_schema=False)
def stylesheet() -> FileResponse:
    return FileResponse(
        Path(__file__).with_name("app.css"),
        media_type="text/css",
        headers={"Cache-Control": "no-cache"},
    )


@router.get("/app.js", include_in_schema=False)
def javascript() -> FileResponse:
    return FileResponse(
        Path(__file__).with_name("app.js"),
        media_type="text/javascript",
        headers={"Cache-Control": "no-cache"},
    )


@router.get("/favicon.ico", include_in_schema=False)
def favicon() -> Response:
    return Response(status_code=204)


@router.post("/auth/login")
def login(body: LoginIn, request: Request) -> Response:
    settings = request.app.state.settings
    if not authenticate(body.username, body.password, settings):
        raise HTTPException(status_code=401, detail="ชื่อผู้ใช้หรือรหัสผ่านไม่ถูกต้อง")
    response = Response(status_code=204)
    response.set_cookie(
        COOKIE_NAME,
        issue_session(body.username, settings),
        httponly=True,
        samesite="strict",
        secure=False,
        max_age=settings.session_hours * 3600,
        path="/",
    )
    return response


@router.post("/auth/logout")
def logout() -> Response:
    response = Response(status_code=204)
    response.delete_cookie(COOKIE_NAME, path="/")
    return response


@router.get("/auth/me", dependencies=[Depends(require_token)])
def current_user(request: Request) -> dict[str, str]:
    user = session_user(
        request.cookies.get(COOKIE_NAME, ""),
        request.app.state.settings,
    )
    return {"username": user or request.app.state.settings.admin_username}


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/companies", dependencies=[Depends(require_token)])
def list_companies(session: Session = Depends(db_session)) -> dict:
    rows = session.scalars(select(Company).order_by(Company.ticker)).all()
    return {
        "companies": [
            {
                "id": row.id,
                "ticker": row.ticker,
                "market": row.market,
                "name_en": row.name_en,
                "name_th": row.name_th,
            }
            for row in rows
        ]
    }


@router.get("/api/set/status", dependencies=[Depends(require_token)])
def set_status(request: Request) -> dict:
    return {
        "configured": bool(request.app.state.settings.set_api_key),
        "source": "SET official data API",
        "supported_data_types": ["security_profile", "delayed_quote"],
    }


@router.post("/api/set/fetch", dependencies=[Depends(require_token)])
def fetch_set_data(
    body: SETFetchIn,
    request: Request,
    session: Session = Depends(db_session),
) -> dict:
    company = get_company(session, body.ticker)
    client = SETMarketClient(request.app.state.settings)
    results = []
    for data_type in dict.fromkeys(body.data_types):
        try:
            result = fetch_and_store(
                session,
                company=company,
                data_type=data_type,
                client=client,
            )
        except SETSourceError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        results.append(
            {
                "data_type": result.data_type,
                "created": result.created,
                "duplicate": not result.created,
                "snapshot_id": result.snapshot_id,
                "content_hash": result.content_hash,
            }
        )
    return {"ticker": company.ticker, "results": results}


@router.get("/api/company-data", dependencies=[Depends(require_token)])
def all_company_data(
    ticker: str | None = None,
    session: Session = Depends(db_session),
) -> dict:
    company_query = select(Company).order_by(Company.ticker)
    if ticker:
        company_query = company_query.where(Company.ticker == ticker.strip().upper())
    companies = list(session.scalars(company_query))
    output = []
    for company in companies:
        snapshots = list(
            session.scalars(
                select(ExternalSnapshot)
                .where(ExternalSnapshot.company_id == company.id)
                .order_by(ExternalSnapshot.fetched_at.desc())
            )
        )
        documents = list(
            session.scalars(
                select(Document)
                .where(Document.company_id == company.id)
                .order_by(Document.ingested_at.desc())
            )
        )
        knowledge = list(
            session.scalars(
                select(KnowledgeItem)
                .where(
                    KnowledgeItem.company_id == company.id,
                    KnowledgeItem.status == "active",
                )
                .order_by(KnowledgeItem.created_at.desc())
            )
        )
        metrics = list(
            session.scalars(
                select(MetricObservation)
                .where(MetricObservation.company_id == company.id)
                .order_by(MetricObservation.observed_at.desc())
            )
        )
        output.append(
            {
                "company": {
                    "id": company.id,
                    "ticker": company.ticker,
                    "market": company.market,
                    "name_th": company.name_th,
                    "name_en": company.name_en,
                    "sector": company.sector,
                    "industry": company.industry,
                },
                "snapshots": [
                    {
                        "id": row.id,
                        "source": row.source,
                        "data_type": row.data_type,
                        "source_url": row.source_url,
                        "content_hash": row.content_hash,
                        "payload": row.payload_json,
                        "fetched_at": row.fetched_at.isoformat(),
                    }
                    for row in snapshots
                ],
                "documents": [
                    {
                        "id": row.id,
                        "title": row.title,
                        "doc_type": row.doc_type,
                        "content_hash": row.content_hash,
                        "ingested_at": row.ingested_at.isoformat(),
                    }
                    for row in documents
                ],
                "knowledge": [
                    {
                        "id": row.id,
                        "type": row.type,
                        "section": row.section,
                        "statement": row.statement,
                        "importance": row.importance,
                    }
                    for row in knowledge
                ],
                "metrics": [
                    {
                        "id": row.id,
                        "metric_key": row.metric_key,
                        "period": row.period,
                        "value": row.value,
                        "unit": row.unit,
                    }
                    for row in metrics
                ],
            }
        )
    return {"companies": output}


@router.post("/companies", dependencies=[Depends(require_token)])
def post_company(body: CompanyIn, session: Session = Depends(db_session)) -> dict:
    company = upsert_company(session, **body.model_dump())
    return {"id": company.id, "ticker": company.ticker, "market": company.market}


@router.get("/companies/{ticker}", dependencies=[Depends(require_token)])
def read_company(ticker: str, market: str = "SET", session: Session = Depends(db_session)) -> dict:
    company = get_company(session, ticker, market)
    return {
        "id": company.id,
        "ticker": company.ticker,
        "market": company.market,
        "name_th": company.name_th,
        "name_en": company.name_en,
        "sector": company.sector,
        "industry": company.industry,
    }


@router.post("/companies/{ticker}/documents", dependencies=[Depends(require_token)])
def post_document(
    ticker: str,
    request: Request,
    file: UploadFile = File(...),
    doc_type: str = Form("research_note"),
    market: str = Form("SET"),
    session: Session = Depends(db_session),
) -> dict:
    company = get_company(session, ticker, market)
    filename = safe_filename(file.filename or "notes.txt")
    data = file.file.read()
    result = ingest_bytes(
        session,
        RawStore(request.app.state.settings.raw_dir),
        actor=Actor.OWNER,
        company_id=company.id,
        filename=filename,
        data=data,
        doc_type=doc_type,
        title=filename,
    )
    return {
        "document_id": result.document_id,
        "created": result.created,
        "blocks_added": result.blocks_added,
        "extractions_added": result.extractions_added,
        "change_ids": result.change_ids,
    }


@router.post("/companies/{ticker}/thesis", dependencies=[Depends(require_token)])
def post_thesis(
    ticker: str,
    body: ThesisIn,
    market: str = "SET",
    session: Session = Depends(db_session),
) -> dict:
    company = get_company(session, ticker, market)
    thesis = create_thesis(
        session,
        actor=Actor.OWNER,
        company_id=company.id,
        summary=body.summary,
        points=[
            ThesisPointInput(
                label=point.label,
                statement=point.statement,
                importance=point.importance,
            )
            for point in body.points
        ],
    )
    return {"id": thesis.id, "version": thesis.version}


@router.get("/companies/{ticker}/thesis", dependencies=[Depends(require_token)])
def read_thesis(ticker: str, market: str = "SET", session: Session = Depends(db_session)) -> dict:
    company = get_company(session, ticker, market)
    thesis = active_thesis(session, company.id)
    if thesis is None:
        return {"thesis": None}
    return {
        "id": thesis.id,
        "version": thesis.version,
        "summary": thesis.summary,
        "points": [
            {
                "id": point.id,
                "ordinal": point.ordinal,
                "label": point.label,
                "statement": point.statement,
                "status": point.status,
            }
            for point in thesis_points(session, thesis.id)
        ],
    }


@router.post("/companies/{ticker}/knowledge", dependencies=[Depends(require_token)])
def post_knowledge(
    ticker: str,
    body: KnowledgeIn,
    market: str = "SET",
    session: Session = Depends(db_session),
) -> dict:
    company = get_company(session, ticker, market)
    item = add_knowledge(
        session,
        actor=Actor.OWNER,
        company_id=company.id,
        knowledge_type=body.type,
        section=body.section,
        statement=body.statement,
        confidence=body.confidence,
        importance=body.importance,
    )
    return {"id": item.id, "status": item.status}


@router.post("/companies/{ticker}/chat", dependencies=[Depends(require_token)])
def post_chat(
    ticker: str,
    body: ChatIn,
    request: Request,
    market: str = "SET",
    session: Session = Depends(db_session),
) -> dict:
    company = get_company(session, ticker, market)
    if detect_intent(body.message) == "add_watchlist":
        item = save_watchlist(
            session,
            actor=Actor.OWNER,
            company=company,
            cadence=_cadence_from_text(body.message),
        )
        return {
            "conversation_id": None,
            "intent": "add_watchlist",
            "answer": f"เพิ่ม {company.ticker} เข้า watchlist แล้ว cadence {item.cadence}",
            "llm_calls": 0,
        }
    result = ask(
        session,
        actor=Actor.RESEARCH_AGENT,
        company=company,
        message=body.message,
        conversation_id=body.conversation_id,
        llm=request.app.state.llm,
    )
    return {
        "conversation_id": result.conversation_id,
        "intent": result.intent,
        "answer": result.answer,
        "llm_calls": result.llm_calls,
    }


@router.post("/conversations/{conversation_id}/close", dependencies=[Depends(require_token)])
def post_close(conversation_id: str, session: Session = Depends(db_session)) -> dict:
    memories = close_conversation(session, conversation_id, Actor.RESEARCH_AGENT)
    return {
        "memories": [
            {"id": memory.id, "type": memory.memory_type, "summary": memory.summary}
            for memory in memories
        ]
    }


@router.get("/companies/{ticker}/changes", dependencies=[Depends(require_token)])
def read_changes(ticker: str, market: str = "SET", session: Session = Depends(db_session)) -> dict:
    company = get_company(session, ticker, market)
    events = list(
        session.scalars(
            select(ChangeEvent)
            .where(ChangeEvent.company_id == company.id)
            .order_by(ChangeEvent.detected_at.desc())
        )
    )
    return {
        "changes": [
            {
                "id": event.id,
                "subject": event.subject,
                "before": event.before_value,
                "after": event.after_value,
                "importance": event.importance,
                "impact_hint": event.impact_hint,
                "summary": event.summary,
                "thesis_point_id": event.thesis_point_id,
            }
            for event in events
        ]
    }


@router.post("/companies/{ticker}/watchlist", dependencies=[Depends(require_token)])
def post_watchlist(
    ticker: str,
    body: WatchlistIn,
    market: str = "SET",
    session: Session = Depends(db_session),
) -> dict:
    company = get_company(session, ticker, market)
    item = save_watchlist(session, actor=Actor.OWNER, company=company, cadence=body.cadence)
    return {"id": item.id, "cadence": item.cadence, "enabled": item.enabled}


@router.get("/proposals", dependencies=[Depends(require_token)])
def list_proposals(status: str = "pending", session: Session = Depends(db_session)) -> dict:
    rows = session.execute(
        select(Proposal, Company.ticker)
        .join(Company, Company.id == Proposal.company_id)
        .where(Proposal.status == status)
        .order_by(Proposal.created_at.desc())
    ).all()
    return {
        "proposals": [
            {
                "id": proposal.id,
                "ticker": ticker,
                "operation": proposal.operation,
                "status": proposal.status,
                "reason": proposal.reason,
                "payload": proposal.payload_json,
                "proposed_by": proposal.proposed_by,
            }
            for proposal, ticker in rows
        ]
    }


@router.post("/proposals/{proposal_id}/approve", dependencies=[Depends(require_token)])
def post_approve(proposal_id: str, session: Session = Depends(db_session)) -> dict:
    proposal = approve_proposal(session, proposal_id, Actor.OWNER)
    return {"id": proposal.id, "status": proposal.status}


@router.post("/companies/{ticker}/export", dependencies=[Depends(require_token)])
def post_export(
    ticker: str,
    request: Request,
    market: str = "SET",
    session: Session = Depends(db_session),
) -> dict:
    company = get_company(session, ticker, market)
    path = export_company(session, company.id, request.app.state.settings.export_dir)
    return {"path": str(path)}


def _cadence_from_text(text: str) -> str:
    lowered = text.casefold()
    if "3" in lowered and "วัน" in lowered:
        return "3d"
    if "เดือน" in lowered or "monthly" in lowered:
        return "monthly"
    if "event" in lowered or "เหตุการณ์" in lowered:
        return "event"
    return "weekly"
