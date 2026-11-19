#!/usr/bin/env python3
"""libver version: build version chains and pick canonical files.

Inputs: inventory + duplicates. Version evidence, in precedence order:
  1. administrative notes (README/版本说明/version*/changelog*) that name files
  2. filename markers (final > revised > draft; vN as number; 终稿 > 修订 > 初稿)
  3. dates in filenames, then mtime

Usage: python3 lv_version.py --inventory /app/work/inventory.json \
          --duplicates /app/work/duplicates.json \
          --out /app/work/version_graph.json
"""
import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import lvlib

ADMIN_NAME = re.compile(r"(?i)readme|版本|version|changelog|更新记录|说明")


def read_admin_notes(files):
    """Extract quoted statements from administrative note files that mention
    other library filenames or directories."""
    notes = []
    base = {Path(f["rel_path"]).name: f["rel_path"] for f in files}
    dirs = sorted({str(Path(f["rel_path"]).parent) for f in files
                   if str(Path(f["rel_path"]).parent) != "."}, key=len,
                  reverse=True)
    for f in files:
        if f["status"] != "ok" or not ADMIN_NAME.search(f["rel_path"]):
            continue
        pages, err = lvlib.extract_pages(f["abs_path"])
        if err:
            continue
        text = "\n".join(pages)
        for line in text.splitlines():
            line = line.strip().lstrip("-*• ").strip()
            if len(line) < 6:
                continue
            mentioned = [rp for n, rp in base.items() if n in line]
            mentioned += [d for d in dirs if d in line and d != "."]
            if mentioned:
                notes.append({"note_file": f["rel_path"],
                              "quote": lvlib.norm_ws(line)[:240],
                              "mentions": mentioned})
    return notes


ALIAS_HINT = re.compile(r"副本|备份|copy\b|backup|duplicate|\(1\)", re.I)


def score_file(rel_path, mtime):
    rank, label = lvlib.version_marker(rel_path)
    date = lvlib.date_in(rel_path)
    # alias-looking paths lose tiebreaks: identical content under 副本/备份
    # names must not beat the real file
    if ALIAS_HINT.search(rel_path):
        rank -= 0.5
    return {"rank": rank, "label": label, "date": date or "",
            "mtime": mtime or 0}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--inventory", required=True)
    ap.add_argument("--duplicates", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    inv = json.loads(Path(args.inventory).read_text(encoding="utf-8"))
    dup = json.loads(Path(args.duplicates).read_text(encoding="utf-8"))
    files = {f["rel_path"]: f for f in inv["files"]}

    notes = read_admin_notes(list(files.values()))

    # union-find over duplicate relationships to form version families
    parent = {rp: rp for rp in files}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        parent[find(a)] = find(b)

    for grp in dup["exact_duplicate_groups"]:
        for m in grp["members"][1:]:
            union(grp["members"][0], m)
    for grp in dup["near_duplicate_groups"]:
        for m in grp["members"][1:]:
            union(grp["members"][0]["rel_path"], m["rel_path"])

    # same normalized base name in the same directory = version family
    STRIP_TOK = re.compile(
        r"(?i)\b(draft|final|revised|preprint|v\d+|rev\s*\d+|r\d+)\b"
        r"|初稿|草稿|修订|修改稿|终稿|最终版|预印本"
        r"|20\d{2}[-_.]?\d{2}[-_.]?\d{2}|20\d{6}")
    base_key = {}
    for rp in files:
        stem = Path(rp).stem.lower().replace("_", " ")
        stem = STRIP_TOK.sub("", stem)
        stem = re.sub(r"[-_.\s()（）]+", "", stem)
        key = (str(Path(rp).parent), stem)
        if len(stem) >= 3:
            base_key.setdefault(key, []).append(rp)
    for key, members in base_key.items():
        for m in members[1:]:
            union(members[0], m)

    families = {}
    for rp in files:
        families.setdefault(find(rp), []).append(rp)

    # members explicitly demoted by admin notes (e.g. "备份副本中的文件均为副本")
    demoted = set()
    for n in notes:
        if re.search(r"副本|copy|alias|只读", n["quote"]):
            for m in n["mentions"]:
                if m in files:
                    demoted.add(m)

    nodes, edges, canonical_map = [], [], {}
    for fam in families.values():
        candidates = [rp for rp in fam if rp not in demoted] or fam
        scored = sorted(candidates, key=lambda rp: (
            score_file(rp, files[rp].get("mtime"))["rank"],
            score_file(rp, files[rp].get("mtime"))["date"],
            files[rp].get("mtime") or 0), reverse=True)
        canonical = scored[0]
        # admin-note override: a note explicitly naming one member as the
        # official/canonical file wins over filename heuristics
        for n in notes:
            named = [m for m in n["mentions"] if m in fam]
            if named and re.search(r"正式|终稿|为准|canonical", n["quote"]) \
               and not re.search(r"取代|覆盖|已被|副本", n["quote"]):
                canonical = named[0]
                break
        canonical_map[fam[0]] = canonical
        for rp in fam:
            sc = score_file(rp, files[rp].get("mtime"))
            nodes.append({"rel_path": rp, **sc,
                          "sha256": files[rp].get("sha256"),
                          "canonical": rp == canonical,
                          "family_key": fam[0]})
            if rp != canonical:
                rel = ("alias_of"
                       if files[rp].get("sha256") == files[canonical].get("sha256")
                       else "superseded_by")
                edges.append({"from": rp, "to": canonical, "relation": rel,
                              "basis": "filename_marker+date+mtime"})

    graph = {"nodes": nodes, "edges": edges,
             "canonical_map": canonical_map,
             "admin_notes": notes,
             "rules": ["行政备注显式指定 > 文件名版本标记 > 文件名日期 > mtime",
                       "exact duplicates are aliases: same rank, newest mtime "
                       "wins; alias_of edges recorded in duplicates.json"]}
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(graph, ensure_ascii=False, indent=1),
                              encoding="utf-8")
    n_fam = len([f for f in families.values() if len(f) > 1])
    print(f"version: {len(nodes)} nodes, {len(edges)} superseded edges, "
          f"{n_fam} multi-file families -> {args.out}")


if __name__ == "__main__":
    main()
