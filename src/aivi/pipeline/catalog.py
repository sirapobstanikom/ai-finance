import re
from dataclasses import dataclass


@dataclass(frozen=True)
class MetricSpec:
    key: str
    subject: str
    thesis_label: str
    threshold: float
    higher_is_better: bool = True


CATALOG: dict[str, MetricSpec] = {
    "revenue_growth_yoy": MetricSpec(
        key="revenue_growth_yoy",
        subject="Revenue Growth",
        thesis_label="Revenue Growth",
        threshold=0.03,
    ),
}


def spec_for(metric_key: str) -> MetricSpec:
    if metric_key in CATALOG:
        return CATALOG[metric_key]
    return MetricSpec(
        key=metric_key,
        subject=metric_key,
        thesis_label=metric_key,
        threshold=0.0,
    )


def parse_number(token: str) -> float:
    cleaned = token.strip().replace(",", "")
    if cleaned.endswith("%"):
        return float(cleaned[:-1]) / 100
    return float(cleaned)


def period_key(period: str) -> tuple[int, int]:
    match = re.fullmatch(r"(\d{4})(?:Q([1-4]))?", period)
    if match is None:
        return (0, 0)
    year = int(match.group(1))
    quarter = int(match.group(2)) if match.group(2) else 5
    return (year, quarter)


def format_ratio(value: float) -> str:
    percent = value * 100
    text = f"{percent:.2f}".rstrip("0").rstrip(".")
    return f"{text}%"
