from pathlib import Path

import pytest
import httpx
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from aivi.config import Settings
from aivi.domain.enums import Actor, KnowledgeSection, KnowledgeType
from aivi.domain.models import (
    ChangeEvent,
    ConversationMessage,
    Document,
    ExternalSnapshot,
    Extraction,
    KnowledgeItem,
    ThesisAssessment,
    ThesisPoint,
)
from aivi.knowledge.exporter import export_company
from aivi.knowledge.proposals import add_knowledge, approve_proposal, propose_knowledge
from aivi.knowledge.thesis import ThesisPointInput, create_thesis
from aivi.llm import LLMNotConfigured, ModelTier
from aivi.llm.gemini import DisabledProvider, GeminiProvider
from aivi.main import create_app
from aivi.memory.assemble import KNOWLEDGE_BUDGET, assemble_context
from aivi.memory.gate import close_conversation
from aivi.orchestrator.research import ask
from aivi.pipeline.ingest import ingest_bytes
from aivi.security.policy import WriteDenied
from aivi.sources.set_market import SETMarketClient, fetch_and_store
from aivi.tokens import estimate_tokens
from tests.conftest import FILING, THESIS_POINTS, RecordingLLM


def _points() -> list[ThesisPointInput]:
    return [ThesisPointInput(label=label, statement=statement) for label, statement in THESIS_POINTS]


def test_research_agent_cannot_write_thesis_or_knowledge(session: Session, company) -> None:
    with pytest.raises(WriteDenied):
        create_thesis(
            session,
            actor=Actor.RESEARCH_AGENT,
            company_id=company.id,
            summary="no",
            points=_points(),
        )
    with pytest.raises(WriteDenied):
        add_knowledge(
            session,
            actor=Actor.RESEARCH_AGENT,
            company_id=company.id,
            knowledge_type=KnowledgeType.INSIGHT,
            section=KnowledgeSection.BUSINESS_MODEL,
            statement="เอเจนต์เขียนตรงไม่ได้",
        )
    with pytest.raises(WriteDenied):
        propose_knowledge(
            session,
            actor=Actor.SANDBOX_AGENT,
            company_id=company.id,
            knowledge_type=KnowledgeType.INSIGHT,
            section=KnowledgeSection.BUSINESS_MODEL,
            statement="sandbox ยังเขียนไม่ได้",
        )


def test_owner_approves_agent_proposal(session: Session, company) -> None:
    proposal = propose_knowledge(
        session,
        actor=Actor.RESEARCH_AGENT,
        company_id=company.id,
        knowledge_type=KnowledgeType.INSIGHT,
        section=KnowledgeSection.MOAT,
        statement="โครงข่ายสาขายังเป็นข้อได้เปรียบ",
        reason="from research",
    )
    assert proposal.status == "pending"
    approve_proposal(session, proposal.id, Actor.OWNER)
    item = session.scalar(select(KnowledgeItem).where(KnowledgeItem.company_id == company.id))
    assert item is not None
    assert item.status == "active"
    assert item.statement == "โครงข่ายสาขายังเป็นข้อได้เปรียบ"


def test_duplicate_ingest_does_not_reextract(session: Session, raw_store, company) -> None:
    payload = FILING.encode("utf-8")
    first = ingest_bytes(
        session,
        raw_store,
        actor=Actor.PIPELINE,
        company_id=company.id,
        filename="cpall.txt",
        data=payload,
        doc_type="annual_report",
    )
    session.commit()
    extraction_count = session.scalar(select(func.count()).select_from(Extraction))
    second = ingest_bytes(
        session,
        raw_store,
        actor=Actor.PIPELINE,
        company_id=company.id,
        filename="cpall.txt",
        data=payload,
        doc_type="annual_report",
    )
    session.commit()
    assert first.created is True
    assert first.extractions_added > 0
    assert second.created is False
    assert second.extractions_added == 0
    assert second.change_ids == []
    assert session.scalar(select(func.count()).select_from(Document)) == 1
    assert session.scalar(select(func.count()).select_from(Extraction)) == extraction_count


def test_revenue_growth_change_is_deterministic(session: Session, raw_store, company) -> None:
    thesis = create_thesis(
        session,
        actor=Actor.OWNER,
        company_id=company.id,
        summary="CPALL ยังน่าสนใจถ้าการเติบโตและการเปิดสาขาไปด้วยกัน",
        points=_points(),
    )
    result = ingest_bytes(
        session,
        raw_store,
        actor=Actor.PIPELINE,
        company_id=company.id,
        filename="cpall.txt",
        data=FILING.encode("utf-8"),
        doc_type="annual_report",
    )
    session.commit()
    assert len(result.change_ids) == 1
    event = session.get(ChangeEvent, result.change_ids[0])
    assert event is not None
    assert event.before_value == "10%"
    assert event.after_value == "4%"
    assert "CHANGE DETECTED" in event.summary
    assert "10% → 4%" in event.summary
    assert "Potential Impact: Negative" in event.summary
    assert "Related Thesis: Revenue Growth" in event.summary
    assert "Importance: High" in event.summary
    point = session.get(ThesisPoint, event.thesis_point_id)
    assert point is not None
    assert point.label == "Revenue Growth"
    assert point.status == "untested"
    exported = export_company(session, company.id, Path(raw_store.root).parent / "exports")
    text = exported.read_text(encoding="utf-8")
    for label, _statement in THESIS_POINTS:
        assert label in text
    assert f"Version: {thesis.version}" in text


def test_explain_reads_thesis_not_the_whole_file(session: Session, raw_store, company) -> None:
    create_thesis(
        session,
        actor=Actor.OWNER,
        company_id=company.id,
        summary="โตจากการเปิดสาขา",
        points=_points(),
    )
    ingest_bytes(
        session,
        raw_store,
        actor=Actor.PIPELINE,
        company_id=company.id,
        filename="cpall.txt",
        data=FILING.encode("utf-8"),
        doc_type="annual_report",
    )
    add_knowledge(
        session,
        actor=Actor.OWNER,
        company_id=company.id,
        knowledge_type=KnowledgeType.FACT,
        section=KnowledgeSection.BUSINESS_MODEL,
        statement="การเติบโตมาจากการเปิดสาขา (growth from new stores)",
    )
    llm = RecordingLLM()
    result = ask(
        session,
        actor=Actor.RESEARCH_AGENT,
        company=company,
        message="ทำไมเราถึงคิดว่า CPALL ยังมี Growth?",
        conversation_id=None,
        llm=llm,
    )
    assert result.intent == "explain"
    assert result.llm_calls == 1
    prompt = llm.calls[0]["user"]
    assert "Revenue Growth" in prompt
    assert "growth from new stores" in prompt
    assert "RAW_SENTINEL_DO_NOT_PROMPT" not in prompt
    assert "boilerplate" not in prompt
    assert session.scalar(select(func.count()).select_from(ThesisAssessment)) == 0


def test_thesis_check_proposes_impact_without_rewriting_status(
    session: Session, raw_store, company
) -> None:
    create_thesis(
        session,
        actor=Actor.OWNER,
        company_id=company.id,
        summary="โตจากการเปิดสาขา",
        points=_points(),
    )
    ingest_bytes(
        session,
        raw_store,
        actor=Actor.PIPELINE,
        company_id=company.id,
        filename="cpall.txt",
        data=FILING.encode("utf-8"),
        doc_type="annual_report",
    )
    llm = RecordingLLM()
    result = ask(
        session,
        actor=Actor.RESEARCH_AGENT,
        company=company,
        message="มีอะไรเกิดขึ้นที่ทำให้ Investment Thesis เดิมอ่อนแอลงหรือไม่",
        conversation_id=None,
        llm=llm,
    )
    assert result.intent == "thesis_check"
    assert result.llm_calls == 1
    assessment = session.scalar(select(ThesisAssessment))
    assert assessment is not None
    assert assessment.impact == "negative"
    assert assessment.status == "proposed"
    point = session.get(ThesisPoint, assessment.thesis_point_id)
    assert point is not None
    assert point.status == "untested"


def test_news_and_recall_skip_the_model(session: Session, company) -> None:
    llm = RecordingLLM()
    news = ask(
        session,
        actor=Actor.RESEARCH_AGENT,
        company=company,
        message="สรุปข่าว CPALL สามวันที่ผ่านมา",
        conversation_id=None,
        llm=llm,
    )
    assert news.intent == "news_delta"
    assert news.llm_calls == 0
    assert "ไม่มีสาระสำคัญ" in news.answer
    assert llm.calls == []


def test_closed_conversation_does_not_replay_the_transcript(session: Session, company) -> None:
    llm = RecordingLLM()
    first = ask(
        session,
        actor=Actor.RESEARCH_AGENT,
        company=company,
        message="จำไว้ว่าสมมติฐานการเติบโตยังอยู่\nRAW_BULK_NOT_IN_MEMORY " + ("x" * 2000),
        conversation_id=None,
        llm=llm,
    )
    close_conversation(session, first.conversation_id, Actor.RESEARCH_AGENT)
    recall = ask(
        session,
        actor=Actor.RESEARCH_AGENT,
        company=company,
        message="เราเคยคุยอะไรไว้บ้าง",
        conversation_id=None,
        llm=llm,
    )
    assert recall.llm_calls == 0
    assert "RAW_BULK_NOT_IN_MEMORY" not in recall.answer
    assert "สมมติฐานการเติบโตยังอยู่" in recall.answer
    stored = session.scalars(select(ConversationMessage)).all()
    assert any("RAW_BULK_NOT_IN_MEMORY" in message.content for message in stored)
    pack = assemble_context(
        session,
        company=company,
        question="ทำไมยังมองว่าโต",
        conversation_id=None,
    )
    assert "RAW_BULK_NOT_IN_MEMORY" not in pack.render()


def test_knowledge_context_stays_inside_budget(session: Session, company) -> None:
    for index in range(40):
        add_knowledge(
            session,
            actor=Actor.OWNER,
            company_id=company.id,
            knowledge_type=KnowledgeType.OBSERVATION,
            section=KnowledgeSection.FINANCIALS,
            statement=("รายละเอียดยาว " + str(index) + " ") * 80,
            importance="low",
        )
    pack = assemble_context(
        session,
        company=company,
        question="ภาพรวมการเงินเป็นอย่างไร",
        conversation_id=None,
    )
    assert estimate_tokens(pack.knowledge_text) <= KNOWLEDGE_BUDGET
    assert len([line for line in pack.knowledge_text.splitlines() if line]) <= 8


def test_disabled_provider_does_not_pretend_to_call() -> None:
    with pytest.raises(LLMNotConfigured):
        DisabledProvider("openai").complete_text(system="s", user="u", tier=ModelTier.STRONG)
    with pytest.raises(LLMNotConfigured):
        GeminiProvider(Settings(gemini_api_key="")).complete_text(
            system="s",
            user="u",
            tier=ModelTier.CHEAP,
        )


def test_set_fetch_stores_only_changed_payload(session: Session, company) -> None:
    payload = {
        "symbol": "CPALL",
        "longName": "CP ALL PUBLIC COMPANY LIMITED",
        "sectorCode": "COMM",
    }

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["api-key"] == "set-test-key"
        assert request.url.params["symbol"] == "CPALL"
        return httpx.Response(200, json=payload)

    settings = Settings(set_api_key="set-test-key")
    client = SETMarketClient(settings, transport=httpx.MockTransport(handler))
    first = fetch_and_store(
        session,
        company=company,
        data_type="security_profile",
        client=client,
    )
    second = fetch_and_store(
        session,
        company=company,
        data_type="security_profile",
        client=client,
    )
    assert first.created is True
    assert second.created is False
    assert second.snapshot_id == first.snapshot_id
    assert session.scalar(select(func.count()).select_from(ExternalSnapshot)) == 1


def test_api_flow(tmp_path: Path) -> None:
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'api.db'}",
        api_token="secret",
        data_dir=tmp_path / "data",
        export_dir=tmp_path / "exports",
        gemini_api_key="",
    )
    llm = RecordingLLM()
    client = TestClient(create_app(settings, llm=llm))
    assert client.get("/health").status_code == 200
    home = client.get("/", follow_redirects=False)
    assert home.status_code == 303
    assert home.headers["location"] == "/login"
    login_page = client.get("/login")
    assert login_page.status_code == 200
    assert 'id="login-form"' in login_page.text
    assert client.get("/chat", follow_redirects=False).headers["location"] == "/login"
    stylesheet = client.get("/app.css")
    assert stylesheet.status_code == 200
    assert "text/css" in stylesheet.headers["content-type"]
    assert client.get("/app.js").status_code == 200
    assert client.get("/favicon.ico").status_code == 204
    denied = client.post("/companies", json={"ticker": "CPALL", "name_en": "CP All"})
    assert denied.status_code == 401
    wrong = client.post(
        "/auth/login",
        json={"username": "admin", "password": "wrong"},
    )
    assert wrong.status_code == 401
    signed_in = client.post(
        "/auth/login",
        json={"username": "admin", "password": "1234"},
    )
    assert signed_in.status_code == 204
    assert client.get("/chat").status_code == 200
    assert 'data-page="chat"' in client.get("/chat").text
    assert 'class="chat-shell"' in client.get("/chat").text
    assert client.get("/set-fetch").status_code == 200
    assert client.get("/company-data").status_code == 200
    headers = {"Authorization": "Bearer secret"}
    created = client.post(
        "/companies",
        headers=headers,
        json={"ticker": "CPALL", "name_en": "CP All", "aliases": ["ซีพีออลล์"]},
    )
    assert created.status_code == 200
    listing = client.get("/companies", headers=headers)
    assert any(item["ticker"] == "CPALL" for item in listing.json()["companies"])
    thesis = client.post(
        "/companies/CPALL/thesis",
        headers=headers,
        json={
            "summary": "โตจากการเปิดสาขา",
            "points": [{"label": label, "statement": statement} for label, statement in THESIS_POINTS],
        },
    )
    assert thesis.status_code == 200
    upload = client.post(
        "/companies/CPALL/documents",
        headers=headers,
        files={"file": ("cpall.txt", FILING.encode("utf-8"), "text/plain")},
        data={"doc_type": "annual_report"},
    )
    assert upload.status_code == 200
    assert upload.json()["created"] is True
    assert upload.json()["change_ids"]
    again = client.post(
        "/companies/CPALL/documents",
        headers=headers,
        files={"file": ("cpall.txt", FILING.encode("utf-8"), "text/plain")},
        data={"doc_type": "annual_report"},
    )
    assert again.json()["created"] is False
    changes = client.get("/companies/CPALL/changes", headers=headers)
    assert changes.json()["changes"][0]["before"] == "10%"
    assert changes.json()["changes"][0]["after"] == "4%"
    knowledge = client.post(
        "/companies/CPALL/knowledge",
        headers=headers,
        json={
            "type": "FACT",
            "section": "business_model",
            "statement": "การเติบโตมาจากการเปิดสาขา (growth from new stores)",
        },
    )
    assert knowledge.status_code == 200
    chat = client.post(
        "/companies/CPALL/chat",
        headers=headers,
        json={"message": "ทำไมเราถึงคิดว่า CPALL ยังมี Growth?"},
    )
    assert chat.status_code == 200
    body = chat.json()
    assert body["llm_calls"] == 1
    assert "RAW_SENTINEL_DO_NOT_PROMPT" not in llm.calls[0]["user"]
    watch = client.post(
        "/companies/CPALL/chat",
        headers=headers,
        json={"message": "เพิ่ม CPALL เข้า watchlist"},
    )
    assert watch.json()["llm_calls"] == 0
    assert "watchlist" in watch.json()["answer"]
    revise = client.post(
        "/companies/CPALL/chat",
        headers=headers,
        json={"message": "อัปเดต thesis ให้เน้นกระแสเงินสด"},
    )
    assert revise.json()["llm_calls"] == 0
    pending = client.get("/proposals", headers=headers)
    assert pending.status_code == 200
    assert pending.json()["proposals"][0]["operation"] == "revise_thesis_summary"
    exported = client.post("/companies/CPALL/export", headers=headers)
    text = Path(exported.json()["path"]).read_text(encoding="utf-8")
    assert "Cash Flow Growth" in text
