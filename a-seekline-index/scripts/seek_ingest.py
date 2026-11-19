#!/usr/bin/env python3
"""seekline ingest: walk the document library, extract text per page/sheet/
slide, detect sections and printed-page offsets, build the BM25 token index.

Usage:
  python3 seek_ingest.py --lib ROOT [ROOT...] --out INDEX_DIR [--no-ocr]

Outputs under INDEX_DIR:
  inventory.json   every file with hash, size, permissions, extraction status
  pages/doc_XX/    extracted text, one .txt per page
  index.json       token postings + corpus stats + per-doc sections/meta
"""
import argparse
import json
import math
import os
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import seek_common as sc


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lib", nargs="+", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--no-ocr", action="store_true")
    args = ap.parse_args()

    out = Path(args.out)
    pages_dir = out / "pages"
    pages_dir.mkdir(parents=True, exist_ok=True)

    inventory, docs = [], []
    postings = {}          # token -> {doc_id: tf}
    df = Counter()
    N = 0
    for rec in sc.iter_files(args.lib):
        inv = dict(rec)
        inv["sha256"] = sc.sha256_file(rec["path"]) if rec["readable"] else None
        if not rec["readable"]:
            inv["note"] = rec.get("error") or "unreadable"
        if not rec["readable"] or rec["ext"] not in (sc.TEXT_EXT | sc.OFFICE_EXT | sc.PDF_EXT):
            inv["extracted"] = False
            if rec["readable"] and rec["ext"] not in (sc.TEXT_EXT | sc.OFFICE_EXT | sc.PDF_EXT):
                inv["note"] = "unsupported_ext"
            inventory.append(inv)
            continue
        r = sc.extract_file(rec["path"], rec["ext"], try_ocr=not args.no_ocr)
        inv["extracted"] = r.error is None
        if r.error:
            inv["note"] = r.error
        if r.needs_ocr and not r.ocr_pages:
            inv["note"] = (inv.get("note") or "ok") + ";needs_ocr"
        elif r.needs_ocr and r.ocr_pages:
            inv["note"] = (inv.get("note") or "ok") + f";ocr_pages:{r.ocr_pages}"
        if not r.pages:
            inventory.append(inv)
            continue

        doc_id = len(docs)
        ddir = pages_dir / ("doc_%03d" % doc_id)
        ddir.mkdir(exist_ok=True)
        page_files = []
        for i, ptext in enumerate(r.pages):
            pf = ddir / ("page_%03d.txt" % (i + 1))
            pf.write_text(ptext, encoding="utf-8")
            page_files.append(str(pf))
        sections = sc.find_sections(r.pages)
        printed = sc.printed_page_offset(r.pages)
        meta = sc.guess_meta(rec["name"], r.pages)
        tf_total = 0
        tok_freq = Counter()
        for ptext in r.pages:
            for tok in sc.token_ngrams(ptext):
                tok_freq[tok] += 1
        tf_total = sum(tok_freq.values())
        for tok, tf in tok_freq.items():
            postings.setdefault(tok, {})[doc_id] = tf
            df[tok] += 1
        docs.append({
            "doc_id": doc_id, "rel_path": rec["rel_path"], "name": rec["name"],
            "ext": rec["ext"], "size": rec["size"], "mtime": rec["mtime"],
            "sha256": inv["sha256"], "n_pages": len(r.pages),
            "page_files": page_files, "page_kinds": r.page_kinds,
            "sections": sections, "printed_pages": printed, "meta": meta,
            "doc_len": tf_total,
        })
        N += 1
        inventory.append(inv)

    avgdl = (sum(d["doc_len"] for d in docs) / N) if N else 0.0
    index = {
        "n_docs": N, "avgdl": avgdl,
        "idf": {t: math.log(1 + (N - df[t] + 0.5) / (df[t] + 0.5))
                for t in df},
        "postings": postings,
    }
    (out / "inventory.json").write_text(
        json.dumps({"roots": [str(p) for p in args.lib], "files": inventory},
                   ensure_ascii=False, indent=1), encoding="utf-8")
    (out / "index.json").write_text(
        json.dumps({"index": index, "docs": docs}, ensure_ascii=False), encoding="utf-8")
    ok = sum(1 for i in inventory if i.get("extracted"))
    print(f"ingest: {len(inventory)} files, {ok} extracted, {N} indexed docs -> {out}")


if __name__ == "__main__":
    main()
