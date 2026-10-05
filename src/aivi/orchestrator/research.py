import logging
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from aivi.domain.enums import Actor
from aivi.domain.models import (
    ChangeEvent,
    Company,
    ConversationMessage,
    ConversationSession,
    ThesisAssessment,
    ThesisPoint,
    utcnow,
)
from aivi.knowledge.proposals import propose_thesis_summary
from aivi.llm import LLMProvider, ModelTier
from aivi.memory.assemble import assemble_context
from aivi.orchestrator.intent import detect_intent
from aivi.security.policy import require_conversation

log = logging.getLogger(__name__)

SYSTEM_PROMPT = """คุณเป็นผู้ช่วยวิจัยปัจจัยพื้นฐานของ AI_VI
ตอบจากแพ็กข้อมูลที่ให้มาเท่านั้น ถ้าข้อมูลไม่มีในแพ็กให้บอกว่าไม่มีในคลัง
อ้างรหัสของ thesis point, knowledge หรือ change ที่ใช้ประกอบคำตอบ
คุณไม่ได้รับอนุญาตให้สั่งซื้อหรือขายหลักทรัพย์
อย่าเปลี่ยน investment thesis ในการตอบ การเปลี่ยนต้องผ่าน proposal และการอนุมัติ"""


@dataclass
class AnswerResult:
    conversation_id: str
    intent: str
    answer: str
    llm_calls: int


def ask(
    session: Session,
    *,
    actor: Actor,
    company: Company,
    message: str,
    conversation_id: str | None,
    llm: LLMProvider,
) -> AnswerResult:
    require_conversation(actor)
    intent = detect_intent(message)
    conversation = _conversation(session, company.id, conversation_id, message)
    pack = assemble_context(
        session,
        company=company,
        question=message,
        conversation_id=conversation.id,
    )
    llm_calls = 0
    if intent == "recall":
        answer = pack.memory_text or "ยังไม่มีบันทึกการสนทนาของบริษัทนี้"
    elif intent == "news_delta" and not pack.has_high_importance_change:
        answer = pack.changes_text or "ไม่มีสาระสำคัญในช่วงนี้"
    elif intent == "thesis_check" and not pack.has_material_change:
        answer = "ไม่มีสาระสำคัญที่ทำให้ investment thesis เปลี่ยน"
    elif intent == "update_thesis":
        propose_thesis_summary(
            session,
            actor=actor,
            company_id=company.id,
            summary=message.strip(),
            reason="user asked to update the thesis",
        )
        answer = "บันทึกคำขอแก้ thesis เป็น proposal แล้ว ยังไม่เปลี่ยน thesis ที่ใช้งานอยู่"
    elif intent == "add_watchlist":
        answer = "ใช้คำสั่ง watchlist เพื่อเพิ่มบริษัท ระบบไม่ได้เรียกโมเดลสำหรับคำสั่งนี้"
    else:
        answer = llm.complete_text(system=SYSTEM_PROMPT, user=pack.render(), tier=ModelTier.STRONG)
        llm_calls = 1
        if intent == "thesis_check":
            _propose_assessments(
                session,
                company_id=company.id,
                rationale=answer,
                model_id=llm.model_name(ModelTier.STRONG),
            )
    session.add(
        ConversationMessage(
            session_id=conversation.id,
            role="user",
            content=message,
            created_at=utcnow(),
        )
    )
    session.add(
        ConversationMessage(
            session_id=conversation.id,
            role="assistant",
            content=answer,
            created_at=utcnow(),
        )
    )
    log.info(
        "research intent=%s llm_calls=%s chars=%s",
        intent,
        llm_calls,
        len(message),
    )
    return AnswerResult(
        conversation_id=conversation.id,
        intent=intent,
        answer=answer,
        llm_calls=llm_calls,
    )


def _conversation(
    session: Session,
    company_id: str,
    conversation_id: str | None,
    message: str,
) -> ConversationSession:
    if conversation_id is not None:
        conversation = session.get(ConversationSession, conversation_id)
        if conversation is None or conversation.company_id != company_id:
            raise ValueError("conversation not found for this company")
        if conversation.ended_at is not None:
            raise ValueError("conversation is closed")
        return conversation
    title = message.strip().splitlines()[0][:120]
    conversation = ConversationSession(company_id=company_id, title=title, started_at=utcnow())
    session.add(conversation)
    session.flush()
    return conversation


def _propose_assessments(
    session: Session,
    *,
    company_id: str,
    rationale: str,
    model_id: str,
) -> None:
    events = list(
        session.scalars(
            select(ChangeEvent).where(
                ChangeEvent.company_id == company_id,
                ChangeEvent.importance == "high",
                ChangeEvent.thesis_point_id.is_not(None),
            )
        )
    )
    for event in events:
        point = session.get(ThesisPoint, event.thesis_point_id)
        if point is None:
            continue
        session.add(
            ThesisAssessment(
                thesis_point_id=point.id,
                change_event_id=event.id,
                impact=event.impact_hint,
                materiality=event.materiality,
                rationale=rationale,
                model_id=model_id,
                status="proposed",
            )
        )
