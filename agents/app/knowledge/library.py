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

# Persisted index (Mike 2026-07-16): the tokenized index is saved next
# to the texts, so restarts load it instantly instead of re-parsing
# every book. Rebuilt automatically whenever the folder changes.
INDEX_FILE = os.path.join(LIB_DIR, "_index.json")

# Mike's DROP-FOLDERS (2026-07-16: "can I just add stuff into the quant
# folder to help with the knowledge?" -- yes). ops_watchdog sweeps these
# daily; scripts/build_library.py sweeps them on demand. Text-like files
# mirror straight in; PDFs need one run of the build script (pypdf).
SOURCE_DIRS = [
    ("qc", os.path.abspath(os.path.join(
        _here, "..", "..", "..", "..", "Quantconnect"))),
    ("research", os.path.abspath(os.path.join(
        _here, "..", "..", "..", "..", "TREZO_PROJECT",
        "06_external_research"))),
]
# Formats the sweep can READ (Mike 2026-08-03: "will the agents be able
# to review and analyze what is in the folder being a certain type of
# media or any type of media?"). Plain text is copied; the rest are
# text-EXTRACTED below. Anything not listed here is skipped -- and the
# sweep now says so out loud instead of ignoring it silently.
TEXT_EXTS = (".txt", ".md", ".py", ".cs", ".csv", ".json", ".yaml", ".yml")
DOC_EXTS = (".pdf", ".docx", ".epub", ".htm", ".html")
# Media the agents cannot read on their own. Listed so the sweep can
# REPORT them rather than pretend they do not exist -- Mike drops chart
# screenshots into the folder and deserves to know they are inert.
MEDIA_EXTS = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp",
              ".mp4", ".mov", ".avi", ".mkv", ".mp3", ".wav", ".m4a")
SKIP_DIRS = {".git", "__pycache__", ".venv", "node_modules"}


def _extract_pdf(path: str) -> str:
    try:
        from pypdf import PdfReader
        r = PdfReader(path)
        return "\n".join((pg.extract_text() or "") for pg in r.pages)
    except Exception:  # noqa: BLE001
        return ""


def _extract_docx(path: str) -> str:
    """Word files are a ZIP of XML -- no third-party package needed."""
    try:
        import zipfile
        import re as _re
        with zipfile.ZipFile(path) as z:
            xml = z.read("word/document.xml").decode("utf-8", "ignore")
        xml = _re.sub(r"</w:p>", "\n", xml)
        return _re.sub(r"<[^>]+>", "", xml)
    except Exception:  # noqa: BLE001
        return ""


def _extract_epub(path: str) -> str:
    """EPUBs are a ZIP of XHTML -- also readable without a package."""
    try:
        import zipfile
        import re as _re
        out = []
        with zipfile.ZipFile(path) as z:
            for n in z.namelist():
                if n.lower().endswith((".xhtml", ".html", ".htm")):
                    h = z.read(n).decode("utf-8", "ignore")
                    h = _re.sub(r"(?is)<(script|style).*?</\1>", " ", h)
                    out.append(_re.sub(r"<[^>]+>", " ", h))
        return "\n".join(out)
    except Exception:  # noqa: BLE001
        return ""


def _extract_html(path: str) -> str:
    try:
        import re as _re
        h = open(path, encoding="utf-8", errors="ignore").read()
        h = _re.sub(r"(?is)<(script|style).*?</\1>", " ", h)
        return _re.sub(r"<[^>]+>", " ", h)
    except Exception:  # noqa: BLE001
        return ""


_EXTRACTORS = {".pdf": _extract_pdf, ".docx": _extract_docx,
               ".epub": _extract_epub, ".htm": _extract_html,
               ".html": _extract_html}


def sweep_local_sources() -> int:
    """Mirror the drop-folders into the library. Returns files added.

    Reads plain text directly and EXTRACTS text from PDF, Word, EPUB and
    HTML (2026-08-03). Files it cannot read -- screenshots, video, audio
    -- are counted and reported through sweep_report() rather than
    ignored in silence, so Mike can see that a chart image he dropped in
    is inert. Never raises; skips oversized (>8MB) and unchanged files."""
    n, skipped = 0, []
    try:
        os.makedirs(LIB_DIR, exist_ok=True)
        for prefix, root in SOURCE_DIRS:
            if not os.path.isdir(root):
                continue
            for dirpath, dirnames, filenames in os.walk(root):
                dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
                for fn in filenames:
                    ext = os.path.splitext(fn)[1].lower()
                    src = os.path.join(dirpath, fn)
                    if ext in MEDIA_EXTS:
                        skipped.append(fn)
                        continue
                    if ext not in TEXT_EXTS and ext not in DOC_EXTS:
                        continue
                    try:
                        if os.path.getsize(src) > 8_000_000:
                            continue
                        base = (os.path.splitext(fn)[0].strip().lower()
                                .replace(" ", "-"))
                        dst = os.path.join(LIB_DIR, f"{prefix}--{base}.txt")
                        if (os.path.exists(dst)
                                and os.path.getmtime(dst)
                                >= os.path.getmtime(src)):
                            continue
                        if ext in _EXTRACTORS:
                            raw = _EXTRACTORS[ext](src)
                            if len(raw.strip()) < 200:
                                # Nothing usable came out -- a scanned
                                # PDF, or pypdf is not installed.
                                skipped.append(fn + " (no readable text)")
                                continue
                        else:
                            raw = open(src, encoding="utf-8",
                                       errors="ignore").read()
                        with open(dst, "w", encoding="utf-8") as f:
                            f.write(raw)
                        n += 1
                    except Exception:  # noqa: BLE001
                        continue
    except Exception:  # noqa: BLE001
        pass
    _LAST_SWEEP["added"] = n
    _LAST_SWEEP["unreadable"] = skipped
    return n


_LAST_SWEEP: dict = {"added": 0, "unreadable": []}


def sweep_report() -> dict:
    """What the last sweep took in, and what it had to leave behind."""
    u = _LAST_SWEEP.get("unreadable") or []
    return {
        "added": _LAST_SWEEP.get("added", 0),
        "unreadable_count": len(u),
        "unreadable": u[:20],
        "note": (
            f"{len(u)} file(s) in the drop-box cannot be read by the "
            f"agents (images, video or audio). Describe them in a .md "
            f"or .txt note beside them and that text WILL be indexed."
        ) if u else "Everything in the drop-box is readable.",
    }

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
    # Fast path: load the persisted index when it matches the folder.
    try:
        import json as _j
        if os.path.exists(INDEX_FILE):
            with open(INDEX_FILE, encoding="utf-8") as f:
                data = _j.load(f)
            if (tuple(tuple(x) for x in (data.get("sig") or ())) == sig
                    and data.get("chunks")):
                _INDEX = [{"source": c["source"], "page": c["page"],
                           "text": c["text"], "toks": set(c["toks"])}
                          for c in data["chunks"]]
                _SIG, _LAST_BUILD = sig, time.time()
                return
    except Exception:  # noqa: BLE001
        pass
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
    # Persist for instant loads after restarts.
    try:
        import json as _j
        with open(INDEX_FILE, "w", encoding="utf-8") as f:
            _j.dump({"sig": [list(x) for x in sig],
                     "chunks": [{"source": c["source"], "page": c["page"],
                                 "text": c["text"],
                                 "toks": sorted(c["toks"])}
                                for c in idx]}, f)
    except Exception:  # noqa: BLE001
        pass


# Passage-quality filter (Mike 2026-07-27: "make sure the process of
# knowledge is being executed"). Audit found every approval carrying
# the SAME hit -- a figure caption ("Figure 6.41 (continued) Another
# example can be seen on Alcoa"). Book scans are full of captions,
# running heads, page numbers and index lines; they match query tokens
# but teach nothing. Score them down so real prose surfaces instead.
_NOISE_MARKERS = (
    "figure ", "fig.", "table ", "(continued)", "chapter ",
    "copyright", "all rights reserved", "www.", "http",
    "index", "contents", "isbn",
)


def _quality(text: str) -> float:
    """0.0-1.0 readability weight for a passage. Prose scores high;
    captions, headers and number-soup score low."""
    t = (text or "").strip()
    if len(t) < 80:
        return 0.15
    low = t.lower()
    q = 1.0
    for m in _NOISE_MARKERS:
        if m in low[:60]:          # marker at the START = caption/header
            q -= 0.45
            break
    words = t.split()
    if words:
        digits = sum(1 for w in words if any(ch.isdigit() for ch in w))
        if digits / len(words) > 0.30:      # number-soup / tables
            q -= 0.35
    # Real teaching prose tends to contain sentence punctuation.
    if t.count(".") < 2:
        q -= 0.2
    return max(0.05, min(1.0, q))


def search(query: str, k: int = 3) -> list[dict]:
    """Top-k passages for the query; [] when the library is empty. Never raises.

    Scoring = token overlap x passage quality, with a bonus for an exact
    phrase hit. Quality weighting keeps figure captions and page
    furniture from crowding out the craft (2026-07-27)."""
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
            score = (hit / float(len(qs))) * _quality(c.get("text", ""))
            if len(ql) > 8 and ql in c["text"].lower():
                score += 1.0
            scored.append((score, c))
        scored.sort(key=lambda x: -x[0])
        # Source diversity: don't return three passages from one book
        # when the library holds sixteen (2026-07-27).
        out, seen = [], set()
        for s_, c in scored:
            src = c["source"]
            if src in seen and len(out) < max(1, int(k)):
                continue
            seen.add(src)
            out.append({"source": src, "page": c["page"],
                        "text": c["text"][:400], "score": round(s_, 3)})
            if len(out) >= max(1, int(k)):
                break
        if not out and scored:
            s_, c = scored[0]
            out = [{"source": c["source"], "page": c["page"],
                    "text": c["text"][:400], "score": round(s_, 3)}]
        return out
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
