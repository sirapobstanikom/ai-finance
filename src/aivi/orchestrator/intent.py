def detect_intent(text: str) -> str:
    lowered = text.casefold()
    if "watchlist" in lowered or "เฝ้าดู" in lowered or "เพิ่มเข้า" in lowered:
        return "add_watchlist"
    if any(marker in lowered for marker in ("เคยคุย", "คุยอะไร", "เคยพูด")):
        return "recall"
    if any(marker in lowered for marker in ("ปรับ thesis", "อัปเดต thesis", "update thesis")):
        return "update_thesis"
    if any(marker in lowered for marker in ("วิเคราะห์งบ", "งบล่าสุด", "56-1", "one report")):
        return "analyze_filing"
    if any(marker in lowered for marker in ("investment thesis", "thesis", "อ่อนแอ", "ผิดหรือ")):
        return "thesis_check"
    if any(marker in lowered for marker in ("ข่าว", "มีอะไรใหม่", "สามวัน")):
        return "news_delta"
    return "explain"
