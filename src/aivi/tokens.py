def estimate_tokens(text: str) -> int:
    if not text:
        return 0
    return max(1, len(text) // 4)


def truncate_to_budget(text: str, budget: int) -> str:
    if estimate_tokens(text) <= budget:
        return text
    return text[: budget * 4].rstrip()


def fit_chunks(chunks: list[str], budget: int, limit: int | None = None) -> str:
    chosen: list[str] = []
    used = 0
    for chunk in chunks:
        if limit is not None and len(chosen) >= limit:
            break
        cost = estimate_tokens(chunk)
        if used + cost > budget:
            break
        chosen.append(chunk)
        used += cost
    return "\n".join(chosen)
