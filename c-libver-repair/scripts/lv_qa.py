#!/usr/bin/env python3
"""libver qa: answer retrieval questions against the CANONICAL library only —
no duplicate/old-version noise. Term-matched, page-located, quote-verified.

Usage:
  python3 lv_qa.py --manifest /app/output/canonical_manifest.json \
      --canon-root /app/output/canonical_library \
      --question "缓冲液配方 终稿" --top 3 --out /app/work/qa_q1.json
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import lvlib


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--canon-root", required=True)
    ap.add_argument("--question", required=True)
    ap.add_argument("--top", type=int, default=3)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    man = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    root = Path(args.canon_root)
    terms = args.question.split()
    hits = []
    for f in man["files"]:
        p = root / f["canonical_rel_path"]
        pages, err = lvlib.extract_pages(p)
        if err:
            continue
        best = None
        for pi, ptext in enumerate(pages):
            norm = lvlib.norm_ws(ptext)
            matched = [t for t in terms if t.lower() in norm.lower()]
            if matched and (best is None or len(matched) > len(best["matched"])):
                sent = None
                for s in re_split_sent(norm):
                    if any(t.lower() in s.lower() for t in terms):
                        sent = s
                        break
                best = {"page": pi + 1, "matched": matched,
                        "quote": (sent or norm)[:240]}
        if best:
            hits.append({"canonical_rel_path": f["canonical_rel_path"],
                         "version_label": f["version_label"],
                         "year": f["year"], "project_ids": f["project_ids"],
                         **best})
    hits.sort(key=lambda h: -len(h["matched"]))
    hits = hits[:args.top]
    out = {"question": args.question, "status": "ok" if hits else "no_match",
           "hits": hits,
           "note": "answered over canonical library only; aliases and "
                   "superseded versions excluded by construction"}
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(out, ensure_ascii=False, indent=1),
                              encoding="utf-8")
    print(f"qa: {len(hits)} hits for {args.question!r} -> {args.out}")


def re_split_sent(text):
    import re
    return [p for p in re.split(r"(?<=[。！？.!?])\s+", text) if p.strip()]


if __name__ == "__main__":
    main()
