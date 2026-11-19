#!/usr/bin/env python3
"""libver repair: materialize a canonical library (aliases and superseded
versions excluded, everything else copied with identical relative paths),
emit the canonical metadata manifest, alias map and an honest recovery log
for everything skipped, unreadable, encrypted, or needing OCR.

Usage: python3 lv_repair.py --inventory /app/work/inventory.json \
          --duplicates /app/work/duplicates.json \
          --graph /app/work/version_graph.json \
          --outdir /app/output
"""
import argparse
import json
import os
import re
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import lvlib


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--inventory", required=True)
    ap.add_argument("--duplicates", required=True)
    ap.add_argument("--graph", required=True)
    ap.add_argument("--outdir", required=True)
    args = ap.parse_args()

    inv = json.loads(Path(args.inventory).read_text(encoding="utf-8"))
    dup = json.loads(Path(args.duplicates).read_text(encoding="utf-8"))
    graph = json.loads(Path(args.graph).read_text(encoding="utf-8"))
    files = {f["rel_path"]: f for f in inv["files"]}
    outdir = Path(args.outdir)
    canon_root = outdir / "canonical_library"
    canon_root.mkdir(parents=True, exist_ok=True)

    superseded = {e["from"]: e for e in graph["edges"]}
    alias_pairs = {tuple(sorted([e["from"], e["to"]]))
                   for e in graph["edges"] if e["relation"] == "alias_of"}

    manifest, recovery, alias_map = [], [], {}
    fam_canon = {nd["family_key"]: nd["rel_path"]
                 for nd in graph["nodes"] if nd["canonical"]}
    fam_key_of = {nd["rel_path"]: nd["family_key"] for nd in graph["nodes"]}
    for grp in dup["exact_duplicate_groups"]:
        key = fam_key_of.get(grp["members"][0])
        canon = fam_canon.get(key, grp["members"][0])
        for m in grp["members"]:
            if m != canon:
                alias_map[m] = canon

    for f in inv["files"]:
        rp, st = f["rel_path"], f["status"]
        if st == "permission_denied":
            recovery.append({"rel_path": rp, "action": "skipped",
                             "reason": "permission_denied",
                             "recovery": "无法读取；如需纳入，请库管理员授权后重跑"})
            continue
        if st.startswith("encrypted") or st.startswith("extract_failed") \
           or st.startswith("pdftotext_failed") or st == "no_pdf_tool":
            recovery.append({"rel_path": rp, "action": "flagged",
                             "reason": st,
                             "recovery": "保留在清单中但不参与检索；需解密/修复源文件"})
        if st == "unsupported_ext":
            recovery.append({"rel_path": rp, "action": "skipped",
                             "reason": "unsupported_ext:" + f["ext"],
                             "recovery": "不在可抽取类型内；保留原文件不动"})
            continue
        if st == "needs_ocr_or_empty":
            recovery.append({"rel_path": rp, "action": "flagged",
                             "reason": "needs_ocr_or_empty",
                             "recovery": "无文本层；OCR 可用时转文本后重跑"})
        if rp in superseded:
            recovery.append({"rel_path": rp, "action": "excluded_from_canonical",
                             "reason": superseded[rp]["relation"] + " -> " +
                                       superseded[rp]["to"],
                             "recovery": "内容已并入正式版；原文件保留在原库中"})
            continue

        dest = canon_root / rp
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(f["abs_path"], dest)
        pages, _err = lvlib.extract_pages(f["abs_path"])
        text_head = "\n".join(pages[:2])[:4000] if pages else ""
        proj = sorted(set(lvlib.PROJ_RE.findall(text_head)))
        ym = lvlib.YEAR_RE.search(text_head) or lvlib.YEAR_RE.search(rp)
        rank, label = lvlib.version_marker(rp)
        manifest.append({
            "canonical_rel_path": rp,
            "source_rel_path": rp,
            "sha256": f.get("sha256"), "size": f["size"], "ext": f["ext"],
            "file_type": f["ext"].lstrip("."),
            "version_label": label, "version_rank": rank,
            "date": lvlib.date_in(rp),
            "year": int(ym.group(0)) if ym else None,
            "project_ids": proj,
            "title_guess": lvlib.title_guess(pages),
            "status": "canonical" if not st.startswith("needs_ocr") else st,
        })

    (outdir / "canonical_manifest.json").write_text(
        json.dumps({"canonical_root": str(canon_root), "files": manifest},
                   ensure_ascii=False, indent=1), encoding="utf-8")
    (outdir / "alias_map.json").write_text(
        json.dumps({"alias_to_canonical": alias_map,
                    "note": "sha256-identical copies; not independent evidence"},
                   ensure_ascii=False, indent=1), encoding="utf-8")
    (outdir / "recovery_log.json").write_text(
        json.dumps({"entries": recovery, "n_actions": len(recovery)},
                   ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"repair: {len(manifest)} canonical files, {len(alias_map)} aliases, "
          f"{len(recovery)} recovery entries -> {outdir}")


if __name__ == "__main__":
    main()
