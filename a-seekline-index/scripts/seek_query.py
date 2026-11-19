#!/usr/bin/env python3
"""seekline query: execute a JSON query against the index with HARD filters.

Query file schema (see references/query-dsl.md):
{
  "query_id": "q1",                       # optional
  "must": ["缓冲液", "配方"],               # all required (AND)
  "any": [["MOF"], ["metal-organic"]],    # at least one term per group (OR groups)
  "filters": {                            # hard constraints; unsatisfiable -> no_match
    "file_type": ["pdf", "docx"],         # extensions without dot
    "year_min": 2020, "year_max": 2024, "year": 2023,
    "project_id": "NSFC-82373621",
    "version": "final",                   # matches meta.version_tag (case-insensitive)
    "path_prefix": "项目ALPHA", "path_glob": "*终稿*",
    "exclude_glob": "*副本*", "min_size": 100, "max_size": 10e6,
    "mtime_after": "2023-01-01", "mtime_before": "2024-01-01"
  },
  "top_k": 8, "section_scope": false, "expand_synonyms": true
}

Usage: python3 seek_query.py --index INDEX_DIR --query q.json --out hits.json
"""
import argparse
import fnmatch
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import seek_common as sc


def load_synonyms(skill_dir):
    p = Path(skill_dir) / "references" / "synonyms.json"
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def passes_filters(doc, inv_rec, filters):
    """Return (ok, failed_list). Filters are HARD: no relaxation."""
    failed = []
    def bad(cond, name):
        if not cond:
            failed.append(name)
    ext = doc["ext"].lstrip(".")
    if "file_type" in filters:
        want = [f.lower().lstrip(".") for f in filters["file_type"]]
        bad(ext in want, "file_type")
    y = doc["meta"].get("year")
    if "year" in filters:
        bad(y == filters["year"], "year")
    if "year_min" in filters:
        bad(y is not None and y >= filters["year_min"], "year_min")
    if "year_max" in filters:
        bad(y is not None and y <= filters["year_max"], "year_max")
    if "project_id" in filters:
        bad(str(filters["project_id"]).upper()
            in [p.upper() for p in doc["meta"].get("project_ids", [])],
            "project_id")
    if "version" in filters:
        vt = (doc["meta"].get("version_tag") or "").lower()
        bad(filters["version"].lower() in vt, "version")
    if "path_prefix" in filters:
        bad(doc["rel_path"].startswith(filters["path_prefix"]), "path_prefix")
    if "path_glob" in filters:
        bad(fnmatch.fnmatch(doc["rel_path"], filters["path_glob"]), "path_glob")
    if "exclude_glob" in filters:
        bad(not fnmatch.fnmatch(doc["rel_path"], filters["exclude_glob"]),
            "exclude_glob")
    if "min_size" in filters:
        bad(doc["size"] is not None and doc["size"] >= filters["min_size"], "min_size")
    if "max_size" in filters:
        bad(doc["size"] is not None and doc["size"] <= filters["max_size"], "max_size")
    for key, op in (("mtime_after", lambda a, b: a >= b),
                    ("mtime_before", lambda a, b: a <= b)):
        if key in filters:
            ts = sc_DATE2TS(filters[key])
            bad(doc["mtime"] is not None and op(doc["mtime"], ts), key)
    return (not failed), failed


EPOCH_HELP = None


def sc_DATE2TS(s):
    import datetime
    return int(datetime.datetime.fromisoformat(str(s).replace("/", "-")).timestamp())


def expand_terms(terms, synonyms):
    """Each term -> list of equivalent surface forms (itself + table hits)."""
    groups = []
    provenance = {}
    for t in terms:
        low = t.lower()
        forms = [t]
        for k, eqs in synonyms.items():
            if low == k.lower() or low in [e.lower() for e in eqs]:
                forms = list(dict.fromkeys(forms + eqs + [k]))
        groups.append(forms)
        if len(forms) > 1:
            provenance[t] = forms
    return groups, provenance


def bm25(doc, term_groups, index):
    idf = index["idf"]
    postings = index["postings"]
    N = index["n_docs"]
    avgdl = index["avgdl"] or 1.0
    k1, b = 1.5, 0.75
    score, matched = 0.0, []
    dl = doc["doc_len"] or 1
    for forms in term_groups:
        best = 0.0
        hit_form = None
        for f in forms:
            for tok in set(sc.token_ngrams(f)):
                p = postings.get(tok)
                if not p or doc["doc_id"] not in p:
                    continue
                tf = p[doc["doc_id"]]
                s = idf.get(tok, 0.0) * (tf * (k1 + 1)) / (
                    tf + k1 * (1 - b + b * dl / avgdl))
                if s > best:
                    best, hit_form = s, f
        if best > 0:
            score += best
            matched.append(hit_form)
    return score, matched


def best_paragraph(doc, page_texts, terms):
    """Pick the paragraph containing the most query terms; return
    dict with page, paragraph, quote, first_sentence, para_offset."""
    best = (-1, 0, None, "")
    toks = set()
    for t in terms:
        toks |= set(sc.token_ngrams(t))
    for pi, ptext in enumerate(page_texts):
        for para in sc.split_paragraphs(ptext):
            ptoks = set(sc.token_ngrams(para))
            hit = len(toks & ptoks)
            if hit > 0 and hit > best[0]:
                best = (hit, pi, para, ptext)
    if best[2] is None:
        return None
    para = sc.norm_ws(best[2])
    # quote: sentence around the first matched term, else head of paragraph
    quote = para[:300]
    best_sent, best_hits = None, 0
    for sent in sc.split_sentences(para):
        stoks = set(sc.token_ngrams(sent))
        nh = len(toks & stoks)
        if nh > best_hits and not sc.HEAD_RE.match(sent.strip()[:80]):
            best_sent, best_hits = sent, nh
    if best_sent:
        quote = best_sent[:300]
    first = sc.split_sentences(para)[0][:200]
    para_off = sc.norm_ws(best[3]).find(para[:60])
    return {"page": best[1], "paragraph": para[:500], "quote": quote,
            "first_sentence": first, "para_offset": para_off}


def snippet_boost(doc, terms):
    low = (doc["rel_path"] + " " + doc["name"]).lower()
    boost = 1.0
    for t in terms:
        if t.lower() in low:
            boost *= 1.4
    for s in doc["sections"]:
        for t in terms:
            if t.lower() in s["heading"].lower():
                boost *= 1.1
                break
    return boost


ALIAS_HINT = re.compile(r"(副本|备份|copy\b|backup|\(1\)|duplicate)", re.I)


def alias_demote(doc):
    """Exact-alias heuristics: same content lives under 副本/备份/copy paths.
    Demote so canonical copies rank first; the hit still exists."""
    rel = doc["rel_path"]
    return 0.75 if ALIAS_HINT.search(rel) or ALIAS_HINT.search(doc["name"]) else 1.0


# attach sentence splitter to sc namespace usage
def _split_sentences(text):
    import re
    parts = re.split(r"(?<=[。！？.!?])\s+", text)
    return [p for p in parts if p.strip()] or [text]
sc.split_sentences = _split_sentences


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--index", required=True)
    ap.add_argument("--query", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--skill-dir", default=str(Path(__file__).resolve().parent.parent))
    args = ap.parse_args()

    idx_dir = Path(args.index)
    blob = json.loads((idx_dir / "index.json").read_text(encoding="utf-8"))
    index, docs = blob["index"], blob["docs"]
    # JSON round-trip turns int keys into str; restore for postings
    index["postings"] = {t: {int(k): v for k, v in p.items()}
                         for t, p in index["postings"].items()}
    q = json.loads(Path(args.query).read_text(encoding="utf-8"))
    synonyms = load_synonyms(args.skill_dir) if q.get("expand_synonyms", True) else {}

    terms = list(q.get("must", []))
    must_groups, prov_must = expand_terms(terms, synonyms)
    any_groups, prov_any = [], {}
    for g in q.get("any", []):
        eg, ep = expand_terms(g, synonyms)
        any_groups.append([f for forms in eg for f in forms])
        prov_any.update(ep)

    top_k = int(q.get("top_k", 8))
    filters = q.get("filters", {})

    # score all docs
    scored = []
    for doc in docs:
        s1, m1 = bm25(doc, must_groups, index)
        if terms and not m1:
            continue                      # must-terms are mandatory
        s2, m2 = 0.0, []
        if any_groups:
            per_group = []
            all_ok = True
            for forms in any_groups:
                gs, gm = bm25(doc, [forms], index)
                per_group.append(gs)
                if not gm:
                    all_ok = False
            if not all_ok:
                continue                  # every OR-group needs >=1 hit
            s2, m2 = sum(per_group), []
        ok, failed = passes_filters(doc, None, filters)
        total_terms = terms + [t for g in any_groups for t in g]
        scored.append((doc, (s1 + s2) * snippet_boost(doc, total_terms)
                       * alias_demote(doc),
                       m1 + m2, ok, failed))
    scored.sort(key=lambda x: -x[1])

    hits, rejected = [], []
    for doc, score, matched, ok, failed in scored:
        if not ok:
            rejected.append({"rel_path": doc["rel_path"], "failed_filters": failed})
            continue
        if len(hits) >= top_k:
            break
        page_texts = [Path(pf).read_text(encoding="utf-8", errors="replace")
                      for pf in doc["page_files"]]
        snippet_forms = ([f for forms in must_groups for f in forms]
                         + [f for forms in any_groups for f in forms])
        bp = best_paragraph(doc, page_texts, snippet_forms) or {}
        pi = bp.get("page", 0)
        printed = doc["printed_pages"].get(str(pi)) or doc["printed_pages"].get(pi)
        para_off = bp.get("para_offset", 0)
        if para_off < 0:
            para_off = 0
        section = None
        for s in doc["sections"]:
            if s["page"] < pi or (s["page"] == pi
                                  and (s.get("offset", 0) <= para_off)):
                section = s["heading"]
            else:
                break
        hits.append({
            "rank": len(hits) + 1,
            "doc": {"rel_path": doc["rel_path"], "name": doc["name"],
                    "ext": doc["ext"], "sha256": doc["sha256"],
                    "size": doc["size"], "meta": doc["meta"]},
            "location": {"page_physical": pi + 1,
                         "page_printed": printed,
                         "page_kind": doc["page_kinds"][pi] if pi < len(doc["page_kinds"]) else None,
                         "section_heading": section,
                         "paragraph_first_sentence": bp.get("first_sentence"),
                         "quote": bp.get("quote"),
                         "paragraph": bp.get("paragraph")},
            "score": round(score, 4),
            "matched_terms": matched,
            "expanded_from": {**prov_must, **prov_any},
        })

    result = {
        "query_id": q.get("query_id"),
        "status": "ok" if hits else "no_match",
        "filter_report": {"filters": filters,
                          "n_scored": len(scored),
                          "n_rejected_by_filters": len(rejected),
                          "rejected": rejected[:50]},
        "hits": hits,
        "note": ("filters are hard constraints; no_match means the library has "
                 "no document satisfying all of them, not a relaxed best-effort")
        if not hits else None,
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(result, ensure_ascii=False, indent=1),
                              encoding="utf-8")
    print(f"query {q.get('query_id')}: {len(hits)} hits "
          f"({len(rejected)} rejected by filters) -> {args.out}")


if __name__ == "__main__":
    main()
