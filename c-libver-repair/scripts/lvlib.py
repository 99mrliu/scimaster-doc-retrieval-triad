#!/usr/bin/env python3
"""libver shared library: hashing, text extraction, version markers,
tokenization. Python 3.9+ stdlib only. Import as module."""
import hashlib
import html
import os
import re
import shutil
import subprocess
import zipfile
from pathlib import Path

TEXT_EXT = {".txt", ".md", ".markdown", ".rst", ".csv", ".tsv", ".json",
            ".log", ".tex", ".xml", ".html", ".htm", ".py", ".cfg", ".ini",
            ".yaml", ".yml", ".bib"}
PDFTOTEXT = shutil.which("pdftotext")

VER_PATTERNS = [
    (re.compile(r"(?i)\bfinal\b|终稿|最终版"), 300, "final"),
    (re.compile(r"(?i)\bpreprint\b|预印本"), 10, "preprint"),
    (re.compile(r"(?i)\bdraft\b|初稿|草稿"), 10, "draft"),
    (re.compile(r"(?i)\brevised\b|修订|修改稿"), 20, "revised"),
    (re.compile(r"(?i)\bv(\d+)\b"), None, "vN"),   # rank = N
    (re.compile(r"(?i)\br(\d+)\b"), None, "rN"),
    (re.compile(r"(?i)\brev\s*(\d+)\b"), None, "revN"),
]
DATE_RE = re.compile(r"(20\d{2})[-_.年]?(\d{2})[-_.月]?(\d{2})")
YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")
PROJ_RE = re.compile(r"\b[A-Z]{2,10}[-_]?\d{3,}\b")


def sha256_file(path):
    h = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            for b in iter(lambda: f.read(1 << 20), b""):
                h.update(b)
        return h.hexdigest()
    except OSError:
        return None


def version_marker(name):
    """Return (rank, label) from a filename; higher rank = later version."""
    best = (0, None)
    name = name.replace("_", " ")
    for pat, fixed, label in VER_PATTERNS:
        m = pat.search(name)
        if not m:
            continue
        if label in ("vN", "rN", "revN"):
            rank = int(m.group(1)) * 10
        else:
            rank = fixed
        if rank > best[0]:
            best = (rank, label)
    return best


def date_in(name):
    m = DATE_RE.search(name)
    return "%s-%s-%s" % m.groups() if m else None


def extract_pages(path, ext=None):
    """Return (pages, error). Pages = list of page/sheet/slide texts."""
    ext = (ext or Path(path).suffix.lower()).lower()
    try:
        if ext == ".pdf":
            if not PDFTOTEXT:
                return [], "no_pdf_tool"
            p = subprocess.run([PDFTOTEXT, "-layout", str(path), "-"],
                               capture_output=True, text=True,
                               errors="replace", timeout=120)
            if p.returncode != 0:
                err = p.stderr.strip()
                return [], ("encrypted_pdf" if "password" in err.lower()
                            else "pdftotext_failed")
            pages = p.stdout.split("\f")
            if pages and not pages[-1].strip():
                pages.pop()
            if not any(t.strip() for t in pages):
                return [], "needs_ocr_or_empty"
            return pages, None
        if ext == ".docx":
            with zipfile.ZipFile(path) as z:
                raw = z.read("word/document.xml").decode("utf-8", "replace")
            raw = re.sub(r"</w:p>", "\n", raw)
            return [html.unescape(re.sub(r"<[^>]+>", "", raw))], None
        if ext == ".pptx":
            pages = []
            with zipfile.ZipFile(path) as z:
                slides = sorted((n for n in z.namelist()
                                 if re.fullmatch(r"ppt/slides/slide\d+\.xml", n)),
                                key=lambda n: int(re.search(r"(\d+)", n).group(1)))
                for n in slides:
                    raw = z.read(n).decode("utf-8", "replace")
                    raw = re.sub(r"</a:p>", "\n", raw)
                    pages.append(html.unescape(re.sub(r"<[^>]+>", "", raw)))
            return pages, None
        if ext in TEXT_EXT:
            return [Path(path).read_text(encoding="utf-8",
                                         errors="replace")], None
        return [], "unsupported_ext"
    except PermissionError:
        return [], "permission_denied"
    except Exception as e:
        return [], "extract_failed:" + e.__class__.__name__


_TOK = re.compile(r"[a-z0-9]+|[一-鿿]")


def word_shingles(text, n=5):
    toks = _TOK.findall(text.lower())
    if len(toks) < n:
        return {tuple(toks)} if toks else set()
    return {tuple(toks[i:i + n]) for i in range(len(toks) - n + 1)}


def jaccard(a, b):
    if not a or not b:
        return 0.0
    inter = len(a & b)
    return inter / (len(a) + len(b) - inter)


def norm_ws(s):
    return re.sub(r"\s+", " ", s).strip()


def title_guess(pages):
    for p in pages[:2]:
        for line in p.splitlines():
            ls = line.strip().lstrip("#").strip()
            if 4 <= len(ls) <= 80:
                return ls
    return None
