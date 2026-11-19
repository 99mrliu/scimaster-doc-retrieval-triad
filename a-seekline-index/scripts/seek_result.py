#!/usr/bin/env python3
"""seekline result: write /app/output/result.json mirroring EVERY field of the
case's output_contract, plus honest status/sources/uncertainty/change_log.

Two modes:
  --init-only   : write skeleton now (status=partial), contract fields as null
                  with a note (fill them later; never claim them complete)
  normal        : merge --answers JSON mapping contract-field -> value
Usage:
  python3 seek_result.py --case /input/case.json --out /app/output/result.json --init-only
  python3 seek_result.py --case /input/case.json --out /app/output/result.json \
      --answers /app/work/answers.json --status success \
      --sources /app/work/hits/q1.json /app/work/verify_report.json \
      --uncertainty "问题3 无可命中文件，已如实报告 no_match"
"""
import argparse
import json
import sys
from pathlib import Path


def contract_fields(case):
    oc = case.get("output_contract")
    if oc is None:
        return []
    if isinstance(oc, dict):
        if "fields" in oc and isinstance(oc["fields"], (list, dict)):
            oc = oc["fields"]
        else:
            return list(oc.keys())
    if isinstance(oc, list):
        out = []
        for f in oc:
            out.append(f if isinstance(f, str) else f.get("name") or f.get("field"))
        return [x for x in out if x]
    return []


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--case", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--init-only", action="store_true")
    ap.add_argument("--answers", help="JSON: {contract_field: value, ...}")
    ap.add_argument("--status", default="partial",
                    choices=["success", "complete", "partial", "degraded",
                             "unable", "no_match"])
    ap.add_argument("--sources", nargs="*", default=[])
    ap.add_argument("--uncertainty", nargs="*", default=[])
    ap.add_argument("--note", default=None)
    args = ap.parse_args()

    case = json.loads(Path(args.case).read_text(encoding="utf-8"))
    fields = contract_fields(case)

    if args.init_only and Path(args.out).exists():
        print("result.json already exists; keeping it")
        return
    answers = {}
    if args.answers:
        answers = json.loads(Path(args.answers).read_text(encoding="utf-8"))

    out = {}
    for f in fields:
        out[f] = answers.get(f)   # may be None until filled
    out["case_id"] = case.get("case_id")
    out["status"] = args.status if not args.init_only else "partial"
    out["sources"] = args.sources
    out["uncertainty"] = list(args.uncertainty)
    out["change_log"] = []
    if Path(args.out).exists():
        old = json.loads(Path(args.out).read_text(encoding="utf-8"))
        out["change_log"] = old.get("change_log", [])
        # preserve previously filled contract fields not overwritten now
        for f in fields:
            if out[f] is None and old.get(f) is not None:
                out[f] = old[f]
    import datetime
    out["change_log"].append({
        "ts": datetime.datetime.now().isoformat(timespec="seconds"),
        "action": "init_skeleton" if args.init_only else "update_result",
        "note": args.note})
    missing = [f for f in fields if out.get(f) is None]
    if missing:
        out.setdefault("uncertainty", []).append(
            "output_contract fields still unfilled: " + ", ".join(missing))
    if not fields:
        out.setdefault("uncertainty", []).append(
            "case.json has no output_contract; delivered generic structure")

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(out, ensure_ascii=False, indent=1),
                              encoding="utf-8")
    print(f"result.json: {len(fields)} contract fields "
          f"({len(missing)} unfilled) -> {args.out}")


if __name__ == "__main__":
    main()
