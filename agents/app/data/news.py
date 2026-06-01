"""Company news + lightweight sentiment / event classification.

Phase 7.5. Pulls company headlines from Finnhub's free /company-news
endpoint and tags each with:
  - an event type (earnings, m_and_a, guidance, leadership, legal,
    analyst, product, general)
  - a sentiment label + score (-1..1) from a finance keyword lexicon
  - a severity and a materiality flag

No LLM is used — this is a fast, deterministic keyword pass so the
Market Sentiment agent can run every few minutes cheaply. Material
events feed the Adaptive Scope engine.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import date, datetime, timedelta, timezone

from app.config import get_settings


FINNHUB_NEWS_URL = "https://finnhub.io/api/v1/company-news"


@dataclass
class NewsItem:
    symbol: str
    headline: str
    summary: str
    source: str
    url: str
    published: str   # ISO date/time, or "" if unknown
    category: str


async def fetch_company_news(symbol: str, days: int = 2) -> list[NewsItem]:
    """Fetch recent company news for `symbol`. Returns [] with no key
    configured or on any error — news is best-effort, never fatal."""
    key = get_settings().finnhub_api_key
    if not key:
        return []
    today = date.today()
    params = {
        "symbol": symbol.upper(),
        "from": (today - timedelta(days=days)).isoformat(),
        "to": today.isoformat(),
        "token": key,
    }
    try:
        import httpx
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(FINNHUB_NEWS_URL, params=params)
            resp.raise_for_status()
            rows = resp.json()
    except Exception:  # noqa: BLE001
        return []
    if not isinstance(rows, list):
        return []

    out: list[NewsItem] = []
    for r in rows:
        try:
            ts = r.get("datetime")
            published = (
                datetime.fromtimestamp(int(ts), tz=timezone.utc).isoformat()
                if ts else ""
            )
            out.append(NewsItem(
                symbol=symbol.upper(),
                headline=str(r.get("headline") or "").strip(),
                summary=str(r.get("summary") or "").strip(),
                source=str(r.get("source") or "").strip(),
                url=str(r.get("url") or "").strip(),
                published=published,
                category=str(r.get("category") or "").strip(),
            ))
        except Exception:  # noqa: BLE001
            continue
    return out


# --- Sentiment lexicon ------------------------------------------------

_POSITIVE = {
    "beat", "beats", "surge", "surges", "soar", "soars", "rally", "rallies",
    "upgrade", "upgraded", "outperform", "record", "jumps", "jump", "gains",
    "gain", "profit", "profits", "strong", "growth", "raises", "tops",
    "approval", "approved", "wins", "win", "partnership", "expansion",
    "buyback", "bullish", "breakout", "optimistic", "milestone", "rebound",
    "boosts", "boost", "higher", "rises", "rise", "exceeds", "accelerates",
}
_NEGATIVE = {
    "miss", "misses", "plunge", "plunges", "fall", "falls", "drop", "drops",
    "sinks", "sink", "downgrade", "downgraded", "underperform", "loss",
    "losses", "weak", "decline", "declines", "cuts", "lawsuit", "sued",
    "investigation", "probe", "recall", "bankruptcy", "layoffs", "resign",
    "resigns", "warning", "warns", "bearish", "selloff", "crash", "fraud",
    "halt", "halted", "default", "slump", "disappointing", "lower",
    "tumbles", "tumble", "slashes", "slash", "concerns", "fears",
}

# --- Event-type keywords (substring match, first hit wins) ------------

_EVENT_KEYWORDS: dict[str, tuple[str, ...]] = {
    "earnings": ("earnings", "quarterly", "quarter", " eps", "revenue",
                 "results", "q1 ", "q2 ", "q3 ", "q4 "),
    "m_and_a": ("acquire", "acquires", "acquisition", "merger", "merges",
                "buyout", "takeover", "to buy", "stake in"),
    "guidance": ("guidance", "forecast", "outlook", "projects",
                 "raises full-year", "cuts forecast"),
    "leadership": ("ceo", "cfo", "executive", "appoints", "names new",
                   "steps down", "resign", "resigns", "to retire"),
    "legal": ("lawsuit", "sued", "settlement", "investigation", "probe",
              "sec ", "antitrust", "fine", "regulatory", "fraud"),
    "analyst": ("upgrade", "downgrade", "price target", "rating",
                "initiated", "analyst", "overweight", "underweight"),
    "product": ("launch", "launches", "unveils", "fda", "approval",
                "recall", "contract win", "new product"),
}

_HIGH_SEVERITY_EVENTS = {"m_and_a", "legal", "leadership", "guidance"}


def _tokens(text: str) -> list[str]:
    return [t.strip(".,!?:;()'\"-").lower() for t in text.split()]


def score_sentiment(text: str) -> tuple[str, float]:
    """Return (label, score in -1..1) from the finance keyword lexicon."""
    toks = _tokens(text)
    if not toks:
        return "neutral", 0.0
    pos = sum(1 for t in toks if t in _POSITIVE)
    neg = sum(1 for t in toks if t in _NEGATIVE)
    if pos == 0 and neg == 0:
        return "neutral", 0.0
    raw = (pos - neg) / (pos + neg)
    label = "positive" if raw > 0.15 else "negative" if raw < -0.15 else "neutral"
    return label, round(raw, 2)


def classify_event(text: str) -> str:
    """Best-guess event type from headline + summary text."""
    low = " " + text.lower() + " "
    for event_type, words in _EVENT_KEYWORDS.items():
        if any(w in low for w in words):
            return event_type
    return "general"


@dataclass
class NewsAssessment:
    symbol: str
    headline: str
    url: str
    published: str
    event_type: str
    sentiment: str
    sentiment_score: float
    severity: str          # low | medium | high
    is_material: bool

    def to_dict(self) -> dict:
        return asdict(self)


def assess(item: NewsItem) -> NewsAssessment:
    """Classify one news item: event type, sentiment, severity, materiality."""
    text = f"{item.headline}. {item.summary}"
    sentiment, score = score_sentiment(text)
    event_type = classify_event(text)

    if event_type in _HIGH_SEVERITY_EVENTS and abs(score) >= 0.34:
        severity = "high"
    elif event_type in _HIGH_SEVERITY_EVENTS:
        # Structural events (M&A, legal, leadership, guidance) raise
        # uncertainty even when the headline itself reads neutral.
        severity = "medium"
    elif event_type != "general" and sentiment != "neutral":
        severity = "medium"
    elif abs(score) >= 0.6:
        severity = "medium"
    else:
        severity = "low"

    return NewsAssessment(
        symbol=item.symbol,
        headline=item.headline,
        url=item.url,
        published=item.published,
        event_type=event_type,
        sentiment=sentiment,
        sentiment_score=score,
        severity=severity,
        is_material=severity in ("medium", "high"),
    )


async def assess_llm(item: NewsItem):
    """LLM-backed classification of a news item, guarded end to end.

    Returns a NewsAssessment, or None when the LLM is unavailable or a
    guardrail rejects the output - the caller then falls back to the
    deterministic keyword assess().
    """
    from app.llm.client import classify_news_llm
    result = await classify_news_llm(item.headline, item.summary)
    if result is None:
        return None
    return NewsAssessment(
        symbol=item.symbol,
        headline=item.headline,
        url=item.url,
        published=item.published,
        event_type=result["event_type"],
        sentiment=result["sentiment"],
        sentiment_score=result["sentiment_score"],
        severity=result["severity"],
        is_material=result["severity"] in ("medium", "high"),
    )
