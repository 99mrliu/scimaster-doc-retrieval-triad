#!/usr/bin/env python3
"""seekline verify: re-check every hit's quote, location and identity against
the extracted text. A hit that fails is downgraded to verified=false and must
not be cited as evidence.

Usage: python3 seek_verify.py --index INDEX_DIR --hits hits.json [more.json...]
       --out verify_report.json
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import seek_common as sc


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--index", required=True)
    ap.add_argument("--hits", nargs="+", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    idx_dir = Path(args.index)
    blob = json.loads((idx_dir / "index.json").read_text(encoding="utf-8"))
    docs = {d["rel_path"]: d for d in blob["docs"]}

    report = {"total": 0, "verified": 0, "failed": 0, "checks": []}
    for hf in args.hits:
        data = json.loads(Path(hf).read_text(encoding="utf-8"))
        qid = data.get("query_id")
        for hit in data.get("hits", []):
            report["total"] += 1
            problems = []
            rel = hit["doc"]["rel_path"]
            doc = docs.get(rel)
            if doc is None:
                problems.append("doc_not_in_index")
            else:
                if doc["sha256"] != hit["doc"]["sha256"]:
                    problems.append("sha256_mismatch")
                pi = (hit["location"]["page_physical"] or 1) - 1
                if pi >= len(doc["page_files"]):
                    problems.append("page_out_of_range")
                else:
                    ptext = Path(doc["page_files"][pi]).read_text(
                        encoding="utf-8", errors="replace")
                    quote = hit["location"].get("quote")
                    span = sc.locate_quote(ptext, quote or "")
                    if span is None:
                        problems.append("quote_not_verbatim")
                    first = hit["location"].get("paragraph_first_sentence")
                    if first and sc.locate_quote(ptext, first[:80]) is None:
                        problems.append("first_sentence_not_on_page")
                    sec = hit["location"].get("section_heading")
                    if sec and sec not in [s["heading"] for s in doc["sections"]]:
                        problems.append("section_heading_unknown")
            hit["verified"] = not problems
            report["checks"].append({
                "query_id": qid, "rel_path": rel,
                "page_physical": hit["location"].get("page_physical"),
                "verified": not problems, "problems": problems})
            if problems:
                report["failed"] += 1
            else:
                report["verified"] += 1
        Path(hf).write_text(json.dumps(data, ensure_ascii=False, indent=1),
                            encoding="utf-8")
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=1),
                              encoding="utf-8")
    print(f"verify: {report['verified']}/{report['total']} verified, "
          f"{report['failed']} failed -> {args.out}")


if __name__ == "__main__":
    main()
