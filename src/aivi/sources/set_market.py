import hashlib
import json
import logging
from dataclasses import dataclass
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from aivi.config import Settings
from aivi.domain.enums import Actor
from aivi.domain.models import Company, ExternalSnapshot
from aivi.security.audit import write_audit

log = logging.getLogger(__name__)


class SETSourceError(RuntimeError):
    pass


@dataclass(frozen=True)
class FetchResult:
    data_type: str
    created: bool
    snapshot_id: str
    content_hash: str


class SETMarketClient:
    """Client for SET's documented API products.

    SET requires a subscribed API key. This adapter does not scrape private
    endpoints or attempt to bypass access controls.
    """

    def __init__(self, settings: Settings, transport: httpx.BaseTransport | None = None) -> None:
        self.api_key = settings.set_api_key
        self.base_url = settings.set_api_base_url.rstrip("/")
        self.transport = transport

    def fetch(self, ticker: str, data_type: str) -> tuple[str, dict | list]:
        if not self.api_key:
            raise SETSourceError(
                "SET_API_KEY is not configured. Subscribe to a SET data API and add the key to .env."
            )
        routes = {
            "security_profile": (
                "/reference-data/security-profile",
                {"symbol": ticker},
            ),
            "delayed_quote": (
                "/delay-data/stock",
                {"stockSymbol": ticker, "oddLotFlag": "false"},
            ),
        }
        if data_type not in routes:
            raise SETSourceError(f"Unsupported SET data type: {data_type}")
        path, params = routes[data_type]
        url = f"{self.base_url}{path}"
        try:
            with httpx.Client(transport=self.transport, timeout=20, follow_redirects=False) as client:
                response = client.get(
                    url,
                    params=params,
                    headers={
                        "api-key": self.api_key,
                        "Accept": "application/json",
                        "User-Agent": "AI_VI/0.1 personal research",
                    },
                )
                response.raise_for_status()
                payload = response.json()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in {401, 403}:
                raise SETSourceError("SET rejected SET_API_KEY or this data product is not subscribed.") from exc
            raise SETSourceError(f"SET returned HTTP {exc.response.status_code}.") from exc
        except (httpx.HTTPError, ValueError) as exc:
            raise SETSourceError(f"Could not fetch or parse SET data: {exc}") from exc
        return str(response.url), payload


def fetch_and_store(
    session: Session,
    *,
    company: Company,
    data_type: str,
    client: SETMarketClient,
) -> FetchResult:
    source_url, payload = client.fetch(company.ticker, data_type)
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    existing = session.scalar(
        select(ExternalSnapshot).where(
            ExternalSnapshot.company_id == company.id,
            ExternalSnapshot.source == "set.or.th",
            ExternalSnapshot.data_type == data_type,
            ExternalSnapshot.content_hash == digest,
        )
    )
    if existing is not None:
        log.info(
            "SET snapshot duplicate ticker=%s type=%s hash=%s",
            company.ticker,
            data_type,
            digest[:12],
        )
        return FetchResult(data_type, False, existing.id, digest)
    snapshot = ExternalSnapshot(
        company_id=company.id,
        source="set.or.th",
        data_type=data_type,
        source_url=source_url,
        content_hash=digest,
        payload_json=payload,
    )
    session.add(snapshot)
    session.flush()
    write_audit(
        session,
        actor=Actor.PIPELINE,
        action="fetch_set_snapshot",
        entity_type="external_snapshots",
        entity_id=snapshot.id,
        after={
            "ticker": company.ticker,
            "data_type": data_type,
            "content_hash": digest,
        },
    )
    return FetchResult(data_type, True, snapshot.id, digest)


def flatten_payload(payload: Any, prefix: str = "") -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    if isinstance(payload, dict):
        for key, value in payload.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            rows.extend(flatten_payload(value, path))
    elif isinstance(payload, list):
        for index, value in enumerate(payload):
            path = f"{prefix}[{index}]"
            rows.extend(flatten_payload(value, path))
    else:
        rows.append((prefix, "" if payload is None else str(payload)))
    return rows
