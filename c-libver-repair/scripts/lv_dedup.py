#!/usr/bin/env python3
"""libver dedup: exact duplicates (sha256), near-duplicates (word-5-gram
Jaccard), and format variants (same stem, different extension).

Usage: python3 lv_dedup.py --inventory /app/work/inventory.json \
          --out /app/work/duplicates.json [--threshold 0.5]
"""
import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import lvlib


def union_find(pairs, n):
    parent = list(range(n))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for a, b in pairs:
        parent[find(a)] = find(b)
    groups = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(i)
    return [g for g in groups.values() if len(g) > 1]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--inventory", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--threshold", type=float, default=0.5)
    args = ap.parse_args()

    inv = json.loads(Path(args.inventory).read_text(encoding="utf-8"))
    files = [f for f in inv["files"] if f.get("sha256")]

    # exact duplicates
    by_hash = {}
    for i, f in enumerate(files):
        by_hash.setdefault(f["sha256"], []).append(i)
    exact_groups = [{"sha256": h, "members": [files[i]["rel_path"] for i in idxs]}
                    for h, idxs in by_hash.items() if len(idxs) > 1]

    # near duplicates over text-extractable files
    shingles, err_status = {}, {}
    for i, f in enumerate(files):
        if f["status"] not in ("ok", "needs_ocr_or_empty"):
            continue
        if f["ext"] in (lvlib.TEXT_EXT | {".pdf", ".docx", ".pptx"}):
            pages, err = lvlib.extract_pages(f["abs_path"])
            if err:
                err_status[f["rel_path"]] = err
                continue
            sh = lvlib.word_shingles("\n".join(pages))
            if sh:
                shingles[i] = sh

    pairs, sims = [], {}
    idxs = sorted(shingles)
    for a_pos, a in enumerate(idxs):
        for b in idxs[a_pos + 1:]:
            small = min(len(shingles[a]), len(shingles[b]))
            if small < 100:
                # short documents: containment is robust to heavy edits
                inter = len(shingles[a] & shingles[b])
                s = inter / small if small else 0.0
            else:
                s = lvlib.jaccard(shingles[a], shingles[b])
            if s >= args.threshold:
                pairs.append((a, b))
                sims[(a, b)] = round(s, 3)
    near_groups = [{"members": [{"rel_path": files[i]["rel_path"],
                                 "sim_to_first": round(lvlib.jaccard(
                                     shingles[i], shingles[g[0]]), 3)}
                                for i in g]}
                   for g in union_find(pairs, len(files)) if g[0] in shingles]

    # format variants: same stem, different ext, both present
    by_stem = {}
    for f in files:
        stem = Path(f["rel_path"]).stem.lower()
        by_stem.setdefault(stem, []).append(f["rel_path"])
    variants = [{"stem": s, "files": v} for s, v in by_stem.items() if len(v) > 1]

    out = {"exact_duplicate_groups": exact_groups,
           "near_duplicate_groups": near_groups,
           "pair_similarity": [[files[a]["rel_path"], files[b]["rel_path"], s]
                               for (a, b), s in sorted(sims.items(),
                                                       key=lambda kv: -kv[1])],
           "format_variants": variants,
           "extract_errors": err_status,
           "threshold": args.threshold,
           "note": ("exact groups are byte-identical copies (aliases); "
                    "near groups share >= threshold of word shingles (versions/"
                    "redistributions). Both must not be counted as independent "
                    "evidence.")}
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(out, ensure_ascii=False, indent=1),
                              encoding="utf-8")
    print(f"dedup: {len(exact_groups)} exact groups, {len(near_groups)} near "
          f"groups, {len(variants)} format variants -> {args.out}")


if __name__ == "__main__":
    main()
