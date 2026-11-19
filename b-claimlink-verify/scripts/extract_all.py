#!/usr/bin/env python3
"""claimlink extract_all: extract every extractable file in the library into
/app/work/sources/ and record a manifest with hashes. This is the fact layer:
every later quote must verbatim-hit one of these files.

Usage: python3 extract_all.py --lib ROOT [ROOT...] --out /app/work/sources
"""
import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import clib

ALL_EXT = clib.TEXT_EXT | {".pdf", ".docx", ".pptx", ".xlsx"}
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", ".DS_Store"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lib", nargs="+", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    manifest = []
    for root in args.lib:
        root = Path(root)
        for dirpath, dirnames, filenames in os.walk(root, onerror=lambda e: None):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
            for name in sorted(filenames):
                p = Path(dirpath) / name
                rec = {"rel_path": str(p.relative_to(root)),
                       "abs_path": str(p), "ext": p.suffix.lower()}
                if not os.access(p, os.R_OK):
                    rec["status"] = "permission_denied"
                    manifest.append(rec)
                    continue
                if rec["ext"] not in ALL_EXT:
                    rec["status"] = "unsupported_ext"
                    rec["sha256"] = clib.sha256_file(p)
                    manifest.append(rec)
                    continue
                rec["sha256"] = clib.sha256_file(p)
                pages, kinds, err = clib.extract_pages(p)
                if err:
                    rec["status"] = err
                    manifest.append(rec)
                    continue
                safe = "src_%03d" % len([m for m in manifest if m.get("status") == "ok"])
                sub = out / safe
                sub.mkdir(exist_ok=True)
                page_files = []
                for i, ptext in enumerate(pages):
                    pf = sub / ("page_%03d.txt" % (i + 1))
                    pf.write_text(ptext, encoding="utf-8")
                    page_files.append(str(pf))
                rec["status"] = "ok"
                rec["n_pages"] = len(pages)
                rec["page_files"] = page_files
                rec["page_kinds"] = kinds
                if sum(len(t.strip()) for t in pages) < 20:
                    rec["status"] = "needs_ocr_or_empty"
                manifest.append(rec)
    (out / "sources_manifest.json").write_text(
        json.dumps({"roots": [str(r) for r in args.lib], "files": manifest},
                   ensure_ascii=False, indent=1), encoding="utf-8")
    ok = sum(1 for m in manifest if m["status"] == "ok")
    print(f"extract: {ok}/{len(manifest)} files extracted -> {out}")


if __name__ == "__main__":
    main()
