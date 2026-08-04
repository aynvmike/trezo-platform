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


# --- Mike's own feeds ------------------------------------------------
# He asked "do I just add the rss code here?" -- no code. He drops feed
# URLs into a plain text file in the SAME drop-box folder he already
# uses for books, one per line. The agents read whatever is listed.
FEEDS_FILENAME = "feeds.txt"

_FEEDS_TEMPLATE = """# Trezo — news & research feeds
#
# Paste one feed address (RSS or Atom) per line. Lines starting with #
# are notes and are ignored. The agents read these on their weekly pass,
# keep only items that touch how Trezo actually trades, and file each
# one with a link back to the original source.
#
# To add a feed: paste the address on its own line and save. Nothing
# else to do — no restart needed.
# To pause a feed: put a # in front of it.
#
# --- starter set (delete any you don't want) ---

# US Federal Reserve — policy statements and speeches
https://www.federalreserve.gov/feeds/press_all.xml

# SEC — press releases and enforcement
https://www.sec.gov/news/pressreleases.rss

# arXiv quantitative finance — trading & market microstructure
https://rss.arxiv.org/rss/q-fin.TR

# arXiv quantitative finance — portfolio management
https://rss.arxiv.org/rss/q-fin.PM
"""


def feeds_path() -> Path:
    """The drop-box file Mike edits. Created with a starter set and
    instructions the first time the harvester runs."""
    qc = Path(__file__).resolve().parents[3] / ".." / "Quantconnect"
    qc = qc.resolve()
    f = qc / FEEDS_FILENAME
    try:
        qc.mkdir(parents=True, exist_ok=True)
        if not f.exists():
            f.write_text(_FEEDS_TEMPLATE, encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass
    return f


def read_feeds() -> list[str]:
    try:
        lines = feeds_path().read_text(encoding="utf-8").splitlines()
    except Exception:  # noqa: BLE001
        return []
    out = []
    for ln in lines:
        ln = ln.strip()
        if ln and not ln.startswith("#") and ln.lower().startswith("http"):
            out.append(ln)
    return out


def parse_rss(xml_text: str) -> list[dict]:
    """Parse RSS 2.0 or Atom into the same shape as the arXiv parser, so
    both kinds of source flow through one pipeline."""
    out = []
    try:
        root = ET.fromstring(xml_text)
    except Exception:  # noqa: BLE001
        return out
    # RSS 2.0
    for it in root.findall(".//item"):
        title = _clean(it.findtext("title", ""))
        desc = _clean(re.sub(r"<[^>]+>", " ", it.findtext("description", "") or ""))
        link = _clean(it.findtext("link", ""))
        date = _clean(it.findtext("pubDate", ""))[:16]
        if title:
            out.append({"id": link or title[:40], "title": title,
                        "summary": desc, "published": date,
                        "authors": [], "link": link, "categories": []})
    # Atom
    if not out:
        for e in root.findall("a:entry", _NS):
            title = _clean(e.findtext("a:title", "", _NS))
            summ = _clean(re.sub(r"<[^>]+>", " ",
                                 e.findtext("a:summary", "", _NS)
                                 or e.findtext("a:content", "", _NS) or ""))
            lk = e.find("a:link", _NS)
            link = lk.get("href") if lk is not None else ""
            date = _clean(e.findtext("a:updated", "", _NS))[:10]
            if title:
                out.append({"id": link or title[:40], "title": title,
                            "summary": summ, "published": date,
                            "authors": [], "link": link, "categories": []})
    return out


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
            # --- Mike's own feeds, from the drop-box file -----------
            for url in read_feeds():
                try:
                    r = await client.get(url, headers={
                        "User-Agent": "Trezo/1.0 (personal research reader)"})
                    if r.status_code != 200:
                        continue
                    items = parse_rss(r.text)
                except Exception:  # noqa: BLE001
                    continue
                for p_ in items[:12]:
                    out["checked"] += 1
                    key = "feed:" + p_["id"][:60]
                    if key in seen:
                        continue
                    hits = _relevance_hits(p_["title"] + " " + p_["summary"])
                    if len(hits) < _min_hits:
                        continue
                    slug = re.sub(r"[^a-z0-9]+", "-",
                                  p_["title"].lower())[:60].strip("-")
                    dst = lib / f"research--feed-{abs(hash(key)) % 10**8}-{slug}.txt"
                    try:
                        dst.write_text(distil(p_), encoding="utf-8")
                        fresh.add(key)
                        out["stored"] += 1
                        out["titles"].append(p_["title"][:90])
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
