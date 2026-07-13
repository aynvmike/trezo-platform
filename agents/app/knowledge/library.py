"""Local trading-knowledge library (Mike 2026-07-13).

Mike: "resources for the agents so they do not have to try to figure out
everything on their own." The library is a folder of books and notes at
agents/knowledge/library/ (.pdf + extracted .txt). scripts/build_library.py
downloads the manifest titles (publisher-hosted copies only) and extracts
text; ANY pdf or txt Mike drops into the folder joins the library on the
next build -- that is the "keep growing the resource library" path.

Search is local, instant and free: page-tagged chunks, token-overlap
scoring with a phrase boost. Consumers: the thesis card (one cited
playbook line per approval) and GET /knowledge/search. Deliberately NOT
Mem0 -- books are static reference, not episodic memory, and they would
burn the budget.
"""

from __future__ import annotations

import os
import re
import time

_here = os.path.dirname(os.path.abspath(__file__))
LIB_DIR = os.path.abspath(os.path.join(_here, "..", "..", "knowledge", "library"))

_INDEX: list[dict] = []
_SIG: tuple = ()
_LAST_BUILD = 0.0

_word = re.compile(r"[a-z][a-z\-']+")


def _tok(s: str) -> list[str]:
    return _word.findall((s or "").lower())


def _folder_sig() -> tuple:
    try:
        fs = []
        for fn in sorted(os.listdir(LIB_DIR)):
            if fn.lower().endswith(".txt"):
                p = os.path.join(LIB_DIR, fn)
                fs.append((fn, int(os.path.getmtime(p)), os.path.getsize(p)))
        return tuple(fs)
    except Exception:  # noqa: BLE001
        return ()


def _build() -> None:
    """(Re)index when the folder changed. Cheap: seconds even for books."""
    global _INDEX, _SIG, _LAST_BUILD
    sig = _folder_sig()
    if sig == _SIG and _INDEX:
        return
    idx: list[dict] = []
    for fn, _, _ in sig:
        path = os.path.join(LIB_DIR, fn)
        try:
            text = open(path, encoding="utf-8", errors="ignore").read()
        except Exception:  # noqa: BLE001
            continue
        title = (os.path.splitext(fn)[0]
                 .replace("-", " ").replace("_", " ").strip())
        page = 1
        for block in re.split(r"\n{2,}", text):
            m = re.match(r"\s*\[\[page (\d+)\]\]", block)
            if m:
                page = int(m.group(1))
                block = block[m.end():]
            words = block.split()
            for i in range(0, max(1, len(words)), 150):
                w = words[i:i + 180]
                if len(w) < 25:
                    continue
                chunk = " ".join(w)
                idx.append({"source": title, "page": page,
                            "text": chunk, "toks": set(_tok(chunk))})
    _INDEX, _SIG, _LAST_BUILD = idx, sig, time.time()


def search(query: str, k: int = 3) -> list[dict]:
    """Top-k passages for the query; [] when the library is empty. Never raises."""
    try:
        _build()
        q = _tok(query)
        if not q or not _INDEX:
            return []
        qs = set(q)
        ql = (query or "").lower().strip()
        scored = []
        for c in _INDEX:
            hit = len(qs & c["toks"])
            if not hit:
                continue
            score = hit / float(len(qs))
            if len(ql) > 8 and ql in c["text"].lower():
                score += 1.0
            scored.append((score, c))
        scored.sort(key=lambda x: -x[0])
        return [{"source": c["source"], "page": c["page"],
                 "text": c["text"][:400], "score": round(s, 3)}
                for s, c in scored[:max(1, int(k))]]
    except Exception:  # noqa: BLE001
        return []


def stats() -> dict:
    try:
        _build()
        srcs = sorted({c["source"] for c in _INDEX})
        return {"docs": len(srcs), "chunks": len(_INDEX),
                "sources": srcs, "folder": LIB_DIR}
    except Exception:  # noqa: BLE001
        return {"docs": 0, "chunks": 0, "sources": [], "folder": LIB_DIR}
