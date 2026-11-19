#!/usr/bin/env python3
"""libver inventory: walk the library, hash everything, record permissions,
damage, encryption, empty-text scans, unsupported types.

Usage: python3 lv_inventory.py --lib ROOT [ROOT...] --out /app/work/inventory.json
"""
import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import lvlib

SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", ".DS_Store"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lib", nargs="+", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    files = []
    for root in args.lib:
        root = Path(root)
        for dirpath, dirnames, filenames in os.walk(root, onerror=lambda e: None):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
            for name in sorted(filenames):
                p = Path(dirpath) / name
                rec = {"rel_path": str(p.relative_to(root)), "abs_path": str(p),
                       "ext": p.suffix.lower(), "size": p.stat().st_size,
                       "mtime": int(p.stat().st_mtime)}
                if not os.access(p, os.R_OK):
                    rec["status"] = "permission_denied"
                    files.append(rec)
                    continue
                rec["sha256"] = lvlib.sha256_file(p)
                rec["status"] = "ok"
                if rec["ext"] in (lvlib.TEXT_EXT | {".pdf", ".docx", ".pptx"}):
                    pages, err = lvlib.extract_pages(p)
                    if err:
                        rec["status"] = err
                    elif sum(len(t.strip()) for t in pages) < 20:
                        rec["status"] = "needs_ocr_or_empty"
                elif rec["ext"] == ".xlsx":
                    pass  # xlsx content handled by repair/QA on demand
                else:
                    rec["status"] = "unsupported_ext"
                files.append(rec)

    doc = {"roots": [str(r) for r in args.lib], "files": files,
           "summary": {
               "total": len(files),
               "readable": sum(1 for f in files if f["status"] != "permission_denied"),
               "problems": {s: sum(1 for f in files if f["status"] == s)
                            for s in sorted({f["status"] for f in files
                                             if f["status"] != "ok"})}}}
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(doc, ensure_ascii=False, indent=1),
                              encoding="utf-8")
    print(f"inventory: {doc['summary']} -> {args.out}")


if __name__ == "__main__":
    main()
