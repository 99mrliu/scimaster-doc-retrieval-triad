#!/usr/bin/env python3
"""claimlink locate: verify a quote VERBATIM against extracted sources, with
optional page hint. This is the atomic backlink check; run it for every
evidence card before it may be cited.

Single check:
  python3 locate.py --manifest /app/work/sources/sources_manifest.json \
      --file "项目ALPHA/开题报告_终稿_2023-06-15.md" \
      --page 1 \
      --quote "缓冲液配方：50 mM Tris-HCl" --json

Batch (claims file: list of {file, page?, quote, claim_id?}):
  python3 locate.py --manifest ... --claims claims.json --out located.json
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import clib


def check(manifest, item):
    rec = next((m for m in manifest["files"] if m["rel_path"] == item["file"]
                or m.get("abs_path") == item["file"]), None)
    if rec is None:
        return {"claim_id": item.get("claim_id"), "file": item["file"],
                "found": False, "problem": "file_not_in_library"}
    if rec["status"] != "ok":
        return {"claim_id": item.get("claim_id"), "file": item["file"],
                "found": False, "problem": "source_status:" + rec["status"]}
    pages = [Path(pf).read_text(encoding="utf-8", errors="replace")
             for pf in rec["page_files"]]
    hit = clib.locate(pages, item["quote"], item.get("page"))
    if not hit:
        return {"claim_id": item.get("claim_id"), "file": item["file"],
                "found": False, "problem": "quote_not_verbatim"}
    page, span, ctx = hit
    return {"claim_id": item.get("claim_id"), "file": item["file"],
            "found": True, "page_physical": page,
            "page_kind": rec["page_kinds"][page - 1]
            if page - 1 < len(rec["page_kinds"]) else None,
            "char_span": list(span), "context": ctx,
            "sha256": rec["sha256"]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--file")
    ap.add_argument("--page", type=int)
    ap.add_argument("--quote")
    ap.add_argument("--claims")
    ap.add_argument("--out")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    if args.claims:
        items = json.loads(Path(args.claims).read_text(encoding="utf-8"))
        results = [check(manifest, it) for it in items]
        ok = sum(1 for r in results if r["found"])
        report = {"total": len(results), "found": ok,
                  "failed": len(results) - ok, "results": results}
        if args.out:
            Path(args.out).parent.mkdir(parents=True, exist_ok=True)
            Path(args.out).write_text(json.dumps(report, ensure_ascii=False,
                                                 indent=1), encoding="utf-8")
        print(f"locate: {ok}/{len(results)} verbatim hits"
              + (f" -> {args.out}" if args.out else ""))
    else:
        if not (args.file and args.quote):
            ap.error("need --file and --quote, or --claims")
        r = check(manifest, {"file": args.file, "page": args.page,
                             "quote": args.quote})
        print(json.dumps(r, ensure_ascii=False, indent=1) if args.json else r)


if __name__ == "__main__":
    main()
