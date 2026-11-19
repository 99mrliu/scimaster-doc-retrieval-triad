#!/usr/bin/env python3
"""claimlink audit_claims: audit the evidence ledger against the extracted
fact layer. Every claim must carry at least one evidence card whose quote is
verbatim-located in the named file, whose hash still matches, and whose file
is not a known duplicate/旧版本 unless the claim is ABOUT that version.

Usage:
  python3 audit_claims.py --ledger /app/work/evidence_ledger.json \
      --manifest /app/work/sources/sources_manifest.json \
      --case /input/case.json \
      [--duplicates /app/work/duplicates.json] \
      --out /app/output/verification_report.json

Ledger schema: references/evidence-schema.md
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import clib
from locate import check


def questions_from_case(case_path):
    if not case_path:
        return []
    case = json.loads(Path(case_path).read_text(encoding="utf-8"))
    for k in ("questions", "searches", "queries", "tasks"):
        v = case.get(k)
        if isinstance(v, list):
            return [q if isinstance(q, str) else q.get("id") or q.get("qid")
                    or q.get("question") for q in v]
    return []


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ledger", required=True)
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--case")
    ap.add_argument("--duplicates")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    ledger = json.loads(Path(args.ledger).read_text(encoding="utf-8"))
    manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    dup_rel = set()
    if args.duplicates and Path(args.duplicates).exists():
        d = json.loads(Path(args.duplicates).read_text(encoding="utf-8"))
        for grp in d.get("duplicate_groups", []):
            for m in grp.get("members", []):
                if m.get("role") in ("alias", "superseded"):
                    dup_rel.add(m["rel_path"])

    checks, n_pass = [], 0
    for claim in ledger.get("claims", []):
        problems, good = [], []
        if not claim.get("claim_text"):
            problems.append("empty_claim_text")
        evid = claim.get("evidence") or []
        if not evid:
            problems.append("no_evidence")
        for ev in evid:
            r = check(manifest, {"file": ev.get("source_file"),
                                 "page": ev.get("page"),
                                 "quote": ev.get("quote", "")})
            if not r["found"]:
                problems.append("evidence_not_verbatim:" + r["problem"] +
                                ":" + ev.get("source_file", "?"))
                continue
            if ev.get("source_sha256") and r["sha256"] != ev["source_sha256"]:
                problems.append("sha256_mismatch:" + ev.get("source_file", "?"))
            if ev["source_file"] in dup_rel and not claim.get("about_version"):
                problems.append("cites_duplicate_or_old_version:" +
                                ev["source_file"])
            good.append(r)
        status = "pass" if not problems else "fail"
        if status == "pass":
            n_pass += 1
        checks.append({"claim_id": claim.get("claim_id"),
                       "question_id": claim.get("question_id"),
                       "status": status, "problems": problems,
                       "verified_evidence": good})

    qids = {c.get("question_id") for c in ledger.get("claims", [])}
    asked = questions_from_case(args.case)
    uncovered = [q for q in asked if q and q not in qids]
    conflicts = ledger.get("conflicts", [])
    not_found = ledger.get("not_found", [])

    report = {
        "n_claims": len(ledger.get("claims", [])),
        "n_pass": n_pass,
        "n_fail": len(ledger.get("claims", [])) - n_pass,
        "coverage": {"questions_asked": asked, "covered": sorted(q for q in qids if q),
                     "uncovered": uncovered},
        "n_conflicts_recorded": len(conflicts),
        "n_not_found_recorded": len(not_found),
        "checks": checks,
        "rule": ("fail 的 claim 不得进入 result.json 的确定性答案；"
                 "uncovered 问题必须给 not_found 说明而不是留空"),
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=1),
                              encoding="utf-8")
    print(f"audit: {n_pass}/{len(ledger.get('claims', []))} claims pass, "
          f"{len(conflicts)} conflicts, {len(not_found)} not_found, "
          f"{len(uncovered)} uncovered questions -> {args.out}")


if __name__ == "__main__":
    main()
