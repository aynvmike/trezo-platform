"""Build the agents' trading-knowledge library (Mike 2026-07-13).

Downloads the manifest titles (publisher-hosted copies ONLY -- pirated
mirrors are deliberately excluded) into agents/knowledge/library/,
extracts text page-by-page with pypdf, and writes the .txt files the
library indexes. Re-run any time: it skips what is already downloaded
and ALSO extracts any pdf Mike drops into the folder himself, so the
resource library keeps growing with zero code changes.

Run from agents/:  .venv\\Scripts\\python.exe -m scripts.build_library
Requires once:     .venv\\Scripts\\pip.exe install pypdf
"""

from __future__ import annotations

import os
import sys
import urllib.request

MANIFEST = [
    ("rockwell-complete-guide-to-day-trading",
     "https://rockwell-files.s3.amazonaws.com/The-Complete-Guide-To-Day-Trading.pdf"),
    ("markettraders-ultimate-day-trading-checklist",
     "https://markettraders.com/wp-content/uploads/2025/04/UltimateDayTradingChecklistLT2025.pdf"),
    ("aziz-advanced-techniques-in-day-trading",
     "https://bearbulltraders.com/docs/Advanced-Techniques-in-Day-Trading-Full-Book.pdf"),
]

HERE = os.path.dirname(os.path.abspath(__file__))
LIB = os.path.abspath(os.path.join(HERE, "..", "knowledge", "library"))

# Local research that ALSO belongs in the library (Mike 2026-07-13 #2):
# the QuantConnect algorithm write-ups and the distilled external
# research. Every .txt/.md/.py/.cs file in these folders is mirrored
# into the library on each run (images/binaries skipped), so Mike can
# keep dropping material in either place.
EXTRA_DIRS = [
    ("qc", os.path.abspath(os.path.join(
        HERE, "..", "..", "..", "Quantconnect"))),
    ("research", os.path.abspath(os.path.join(
        HERE, "..", "..", "..", "TREZO_PROJECT", "06_external_research"))),
]
TEXT_EXTS = (".txt", ".md", ".py", ".cs")
SKIP_DIRS = {".git", "__pycache__", ".venv", "node_modules"}


def mirror_extras() -> int:
    n = 0
    for prefix, root in EXTRA_DIRS:
        if not os.path.isdir(root):
            print(f"  (extra source not found, skipping: {root})")
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
            for fn in filenames:
                ext = os.path.splitext(fn)[1].lower()
                if ext not in TEXT_EXTS:
                    continue
                src = os.path.join(dirpath, fn)
                try:
                    if os.path.getsize(src) > 3_000_000:
                        continue
                    base = (os.path.splitext(fn)[0].strip().lower()
                            .replace(" ", "-"))
                    dst = os.path.join(LIB, f"{prefix}--{base}.txt")
                    if (os.path.exists(dst) and
                            os.path.getmtime(dst) >= os.path.getmtime(src)):
                        continue
                    raw = open(src, encoding="utf-8",
                               errors="ignore").read()
                    with open(dst, "w", encoding="utf-8") as f:
                        f.write(raw)
                    n += 1
                    print(f"  mirrored [{prefix}] {fn}")
                except Exception as e:  # noqa: BLE001
                    print(f"  !! mirror failed for {fn}: {str(e)[:100]}")
    return n


def fetch(name: str, url: str) -> str:
    pdf = os.path.join(LIB, name + ".pdf")
    if os.path.exists(pdf) and os.path.getsize(pdf) > 10_000:
        print(f"  already downloaded: {name}.pdf")
        return pdf
    print(f"  downloading {name} ...")
    req = urllib.request.Request(
        url, headers={"User-Agent": "Mozilla/5.0 (Trezo library builder)"})
    data = urllib.request.urlopen(req, timeout=180).read()
    with open(pdf, "wb") as f:
        f.write(data)
    print(f"    {len(data) / 1e6:.1f} MB")
    return pdf


def extract(pdf: str) -> None:
    txt = os.path.splitext(pdf)[0] + ".txt"
    if os.path.exists(txt) and os.path.getsize(txt) > 1_000:
        print(f"  text ready: {os.path.basename(txt)}")
        return
    from pypdf import PdfReader
    r = PdfReader(pdf)
    out = []
    for i, pg in enumerate(r.pages, 1):
        try:
            t = pg.extract_text() or ""
        except Exception:  # noqa: BLE001
            t = ""
        if t.strip():
            out.append(f"[[page {i}]]\n{t.strip()}")
    with open(txt, "w", encoding="utf-8") as f:
        f.write("\n\n".join(out))
    print(f"  extracted {len(r.pages)} pages -> {os.path.basename(txt)}")


def main() -> None:
    os.makedirs(LIB, exist_ok=True)
    print(f"Library folder: {LIB}")
    for name, url in MANIFEST:
        try:
            fetch(name, url)
        except Exception as e:  # noqa: BLE001
            print(f"  !! download failed for {name}: {str(e)[:140]}")
    mirrored = mirror_extras()
    if mirrored:
        print(f"  {mirrored} local research file(s) joined the library")
    for fn in sorted(os.listdir(LIB)):
        if fn.lower().endswith(".pdf"):
            try:
                extract(os.path.join(LIB, fn))
            except Exception as e:  # noqa: BLE001
                print(f"  !! extract failed for {fn}: {str(e)[:140]}")
    sys.path.insert(0, os.path.abspath(os.path.join(HERE, "..")))
    from app.knowledge.library import stats
    st = stats()
    print(f"Indexed: {st['docs']} docs, {st['chunks']} searchable passages")
    for s in st["sources"]:
        print(f"   - {s}")
    print("Done. The agents can now cite the library on every thesis card.")


if __name__ == "__main__":
    main()
