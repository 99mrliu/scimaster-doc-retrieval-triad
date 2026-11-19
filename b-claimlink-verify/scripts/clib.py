#!/usr/bin/env python3
"""claimlink shared library: hashing, text extraction, verbatim location.
Python 3.9+ stdlib only. Import as module."""
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


def sha256_file(path):
    h = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            for b in iter(lambda: f.read(1 << 20), b""):
                h.update(b)
        return h.hexdigest()
    except OSError:
        return None


def extract_pages(path, ext=None):
    """Return (pages, page_kinds, error). Pages = list of page/sheet/slide
    texts. Never raises."""
    ext = (ext or Path(path).suffix.lower()).lower()
    try:
        if ext == ".pdf":
            if PDFTOTEXT:
                p = subprocess.run([PDFTOTEXT, "-layout", str(path), "-"],
                                   capture_output=True, text=True,
                                   errors="replace", timeout=120)
                if p.returncode == 0:
                    pages = p.stdout.split("\f")
                    if pages and not pages[-1].strip():
                        pages.pop()
                    return pages, [f"page {i+1}" for i in range(len(pages))], None
                err = p.stderr.strip()
                if "password" in err.lower():
                    return [], [], "encrypted_pdf"
                return [], [], "pdftotext_failed:" + err[:100]
            return [], [], "no_pdf_tool"
        if ext == ".docx":
            with zipfile.ZipFile(path) as z:
                raw = z.read("word/document.xml").decode("utf-8", "replace")
            raw = re.sub(r"</w:p>", "\n", raw)
            return [html.unescape(re.sub(r"<[^>]+>", "", raw))], ["document"], None
        if ext == ".pptx":
            pages, kinds = [], []
            with zipfile.ZipFile(path) as z:
                slides = sorted((n for n in z.namelist()
                                 if re.fullmatch(r"ppt/slides/slide\d+\.xml", n)),
                                key=lambda n: int(re.search(r"(\d+)", n).group(1)))
                for n in slides:
                    raw = z.read(n).decode("utf-8", "replace")
                    raw = re.sub(r"</a:p>", "\n", raw)
                    pages.append(html.unescape(re.sub(r"<[^>]+>", "", raw)))
                    kinds.append("slide " + re.search(r"(\d+)", n).group(1))
            return pages, kinds, None
        if ext == ".xlsx":
            return _xlsx_pages(path)
        if ext in TEXT_EXT:
            return [Path(path).read_text(encoding="utf-8", errors="replace")], \
                   ["text"], None
        return [], [], "unsupported_ext:" + ext
    except PermissionError:
        return [], [], "permission_denied"
    except Exception as e:
        return [], [], "extract_failed:" + e.__class__.__name__


def _xlsx_pages(path):
    with zipfile.ZipFile(path) as z:
        names = set(z.namelist())
        shared = []
        if "xl/sharedStrings.xml" in names:
            s = z.read("xl/sharedStrings.xml").decode("utf-8", "replace")
            shared = [html.unescape(re.sub(r"<[^>]+>", "", m))
                      for m in re.findall(r"<si>(.*?)</si>", s, re.S)]
        sheets = sorted((n for n in names
                         if re.fullmatch(r"xl/worksheets/sheet\d+\.xml", n)),
                        key=lambda n: int(re.search(r"(\d+)", n).group(1)))
        pages, kinds = [], []
        for n in sheets:
            raw = z.read(n).decode("utf-8", "replace")
            cells = []
            for m in re.finditer(r"<c\b[^>]*?(?:\s+t=\"(\w+)\")?[^>]*>(.*?)</c>",
                                 raw, re.S):
                t, body = m.group(1), m.group(2)
                v = re.search(r"<v>(.*?)</v>", body, re.S)
                isv = re.search(r"<is>(.*?)</is>", body, re.S)
                if t == "s" and v and int(v.group(1)) < len(shared):
                    cells.append(shared[int(v.group(1))])
                elif t == "inlineStr" and isv:
                    cells.append(html.unescape(re.sub(r"<[^>]+>", "", isv.group(1))))
                elif v:
                    cells.append(html.unescape(v.group(1)))
            pages.append("\n".join(cells))
            kinds.append("sheet " + re.search(r"(\d+)", n).group(1))
    return pages, kinds, None


def norm_ws(s):
    return re.sub(r"\s+", " ", s).strip()


def locate(pages, quote, page_hint=None):
    """Find normalized quote across pages (or a hinted page).
    Return (page_index_1based, char_span_in_normalized_page, context) or None."""
    needle = norm_ws(quote)
    if not needle:
        return None
    order = range(len(pages))
    if page_hint:
        order = [page_hint - 1] + [i for i in range(len(pages))
                                   if i != page_hint - 1]
    for i in order:
        if i < 0 or i >= len(pages):
            continue
        hay = norm_ws(pages[i])
        j = hay.find(needle)
        if j >= 0:
            ctx = hay[max(0, j - 60): j + len(needle) + 60]
            return (i + 1, (j, j + len(needle)), ctx)
    return None
