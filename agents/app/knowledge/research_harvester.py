"""Autonomous research harvester — open-access quant literature.

Mike 2026-08-03: he wants the agents to reach real university quant
knowledge and "find information they need and make use of it on their
own."

Source: arXiv's q-fin sections (Trading & Market Microstructure,
Portfolio Management, Statistical Finance, Risk Management,
Computational Finance) plus cross-listed CS work. Open access, a public
API, no key, and explicitly licensed for exactly this.

DESIGN — extract and attribute, never stockpile:
  * We keep the TITLE, AUTHORS, arXiv ID, DATE, LINK and the paper's own
    abstract-derived summary -- the metadata and the idea, with a full
    citation attached to every line.
  * We do NOT mirror full papers into the library. Partly that is the
    clean side of the copyright line (facts and ideas are free; the
    specific expression belongs to its authors), and partly it is just
    better engineering: the library already proved that raw book text
    floods search with figure captions and page furniture. Distilled
    findings with citations beat stockpiled prose on quality, size and
    speed.
  * Every stored note carries "Source:" so any agent quoting it quotes
    the attribution too.

GUARDRAIL — knowledge informs the THESIS, never the GATES. A paper can
explain why a setup is taken and appear in the reasoning; it can never
move a floor, a cap or a stop. Rule changes still go through
TREZO_AGENT_PROPOSALS.md with ledger evidence, for Mike to approve.
Academic work assumes institutional scale, and this account is $4.8k.
"""

from __future__ import annotations

import os
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

ARXIV_API = "https://export.arxiv.org/api/query"

# Categories worth reading for a platform that trades stocks, options,
# crypto and forex on technical + income strategies.
CATEGORIES = ("q-fin.TR", "q-fin.PM", "q-fin.ST", "q-fin.RM", "q-fin.CP")

# What Trezo actually does. A paper has to touch one of these to earn a
# place -- otherwise the library fills with derivatives-pricing algebra
# that will never inform a $5k account.
RELEVANCE = (
    "momentum", "mean revers", "volatility", "stop loss", "drawdown",
    "position siz", "risk manage", "portfolio", "execution", "slippage",
    "market microstructure", "order flow", "liquidity", "covered call",
    "option", "premium", "cryptocurrency", "crypto", "bitcoin",
    "foreign exchange", "forex", "regime", "correlation", "diversif",
    "backtest", "overfit", "sharpe", "kelly", "trend follow",
    "pairs trad", "sentiment", "market impact",
)

_NS = {"a": "http://www.w3.org/2005/Atom"}


def _lib_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "knowledge" / "library"


def _state_file() -> Path:
    return Path(__file__).with_name("_research_seen.json")


def _seen() -> set:
    import json
    try:
        return set(json.loads(_state_file().read_text(encoding="utf-8")))
    except Exception:  # noqa: BLE001
        return set()


def _remember(ids: set) -> None:
    import json
    try:
        keep = sorted(_seen() | ids)[-500:]
        _state_file().write_text(json.dumps(keep), encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip()


def _relevance_hits(text: str) -> list[str]:
    low = (text or "").lower()
    return [k for k in RELEVANCE if k in low]


def parse_feed(xml_text: str) -> list[dict]:
    """Parse an arXiv Atom response into plain dicts. Pure function --
    testable without network access."""
    out = []
    try:
        root = ET.fromstring(xml_text)
    except Exception:  # noqa: BLE001
        return out
    for e in root.findall("a:entry", _NS):
        def _t(tag: str) -> str:
            el = e.find(f"a:{tag}", _NS)
            return _clean(el.text if el is not None else "")
        aid = _t("id").rsplit("/", 1)[-1]
        if not aid:
            continue
        authors = [_clean(a.findtext("a:name", "", _NS))
                   for a in e.findall("a:author", _NS)]
        out.append({
            "id": aid,
            "title": _t("title"),
            "summary": _t("summary"),
            "published": _t("published")[:10],
            "authors": authors[:6],
            "link": f"https://arxiv.org/abs/{aid}",
            "categories": [c.get("term") for c in e.findall("a:category", _NS)],
        })
    return out


def distil(paper: dict) -> str:
    """One library note: the idea, in the agents' language, with the
    citation attached. Deliberately NOT the paper's own prose beyond the
    abstract's factual claims, and never the full text."""
    hits = _relevance_hits(paper["title"] + " " + paper["summary"])
    who = ", ".join(paper["authors"][:3]) + (
        " et al." if len(paper["authors"]) > 3 else "")
    body = paper["summary"]
    # Keep it to the substance: the first few sentences of an abstract
    # carry the finding; the rest is usually method detail.
    sentences = re.split(r"(?<=[.!?])\s+", body)
    finding = " ".join(sentences[:4])
    return (
        f"# {paper['title']}\n\n"
        f"Source: {who} ({paper['published']}), arXiv:{paper['id']}\n"
        f"Link: {paper['link']}\n"
        f"Relevant to: {', '.join(hits[:8]) or 'general quantitative finance'}\n\n"
        f"## What the paper reports\n\n{finding}\n\n"
        f"## How Trezo should treat this\n\n"
        f"Open-access academic research, retrieved automatically. It may "
        f"inform the REASONING behind a trade and should be cited when it "
        f"does. It must NOT change any rule, floor, cap or stop on its own "
        f"— academic results assume institutional scale and this account "
        f"does not. Any rule change goes through TREZO_AGENT_PROPOSALS.md "
        f"with evidence from Trezo's own ledger.\n"
    )


async def harvest(max_per_cat: int = 8, force: bool = False) -> dict:
    """Pull recent papers, keep the relevant unseen ones, write library
    notes. Returns a summary. Never raises."""
    import httpx
    out = {"checked": 0, "stored": 0, "titles": [], "error": None}
    try:
        lib = _lib_dir()
        lib.mkdir(parents=True, exist_ok=True)
        seen = set() if force else _seen()
        fresh: set = set()
        try:
            _min_hits = int(os.getenv("TREZO_RESEARCH_MIN_HITS", "2"))
        except (TypeError, ValueError):
            _min_hits = 2
        async with httpx.AsyncClient(timeout=25.0) as client:
            for cat in CATEGORIES:
                params = {
                    "search_query": f"cat:{cat}",
                    "start": 0,
                    "max_results": max_per_cat,
                    "sortBy": "submittedDate",
                    "sortOrder": "descending",
                }
                try:
                    r = await client.get(ARXIV_API, params=params)
                    if r.status_code != 200:
                        continue
                    papers = parse_feed(r.text)
                except Exception:  # noqa: BLE001
                    continue
                for p in papers:
                    out["checked"] += 1
                    if p["id"] in seen:
                        continue
                    hits = _relevance_hits(p["title"] + " " + p["summary"])
                    if len(hits) < _min_hits:
                        continue          # not close enough to what we do
                    slug = re.sub(r"[^a-z0-9]+", "-",
                                  p["title"].lower())[:60].strip("-")
                    dst = lib / f"research--arxiv-{p['id']}-{slug}.txt"
                    try:
                        dst.write_text(distil(p), encoding="utf-8")
                        fresh.add(p["id"])
                        out["stored"] += 1
                        out["titles"].append(p["title"][:90])
                    except Exception:  # noqa: BLE001
                        continue
        if fresh:
            _remember(fresh)
            try:
                from app.knowledge.library import invalidate
                invalidate()
            except Exception:  # noqa: BLE001
                pass
    except Exception as e:  # noqa: BLE001
        out["error"] = str(e)[:160]
    return out
