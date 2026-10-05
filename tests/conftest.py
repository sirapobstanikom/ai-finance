from pathlib import Path

import pytest
from sqlalchemy.orm import Session, sessionmaker

from aivi.db import make_engine
from aivi.domain.models import Base
from aivi.llm import ModelTier
from aivi.storage.companies import upsert_company
from aivi.storage.raw_store import RawStore


class RecordingLLM:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def complete_text(self, *, system: str, user: str, tier: ModelTier) -> str:
        self.calls.append({"system": system, "user": user, "tier": tier})
        return "การเติบโตยังอิงการเปิดสาขา ตาม knowledge และ thesis ที่ให้มา"

    def complete_json(self, *, system: str, user: str, tier: ModelTier) -> dict:
        self.calls.append({"system": system, "user": user, "tier": tier, "json": True})
        return {}

    def model_name(self, tier: ModelTier) -> str:
        return "fake-strong"


FILING = """# MD&A

Revenue growth comes from new stores in Thailand.

METRIC revenue_growth_yoy 2024 0.10

METRIC revenue_growth_yoy 2025 0.04

# Appendix

RAW_SENTINEL_DO_NOT_PROMPT
this paragraph is boilerplate and should stay out of the prompt.
"""

THESIS_POINTS = [
    ("Revenue Growth", "ยอดขายยังโตจากการเปิดสาขา"),
    ("Margin Expansion", "อัตรากำไรมีทางขยายจากสัดส่วนสินค้าสูงขึ้น"),
    ("Store Expansion", "จำนวนสาขาใหม่ยังเป็นตัวขับดันหลัก"),
    ("Strong Competitive Advantage", "โครงข่ายร้านสะดวกซื้อยังกีดกันคู่แข่ง"),
    ("Cash Flow Growth", "กระแสเงินสดจากการดำเนินงานยังโต"),
]


@pytest.fixture
def session(tmp_path: Path):
    engine = make_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    db: Session = factory()
    try:
        yield db
    finally:
        db.close()
        engine.dispose()


@pytest.fixture
def raw_store(tmp_path: Path) -> RawStore:
    return RawStore(tmp_path / "raw")


@pytest.fixture
def company(session: Session):
    created = upsert_company(
        session,
        ticker="CPALL",
        market="SET",
        name_en="CP All",
        name_th="ซีพี ออลล์",
        aliases=["ซีพีออลล์", "CP All"],
    )
    session.commit()
    return created
