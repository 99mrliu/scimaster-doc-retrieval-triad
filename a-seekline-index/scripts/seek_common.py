#!/usr/bin/env python3
"""seekline shared library: file discovery, hashing, text extraction,
tokenization. Python 3.9+ standard library only. Import as a module."""
import hashlib
import html
import io
import os
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

TEXT_EXT = {".txt", ".md", ".markdown", ".rst", ".csv", ".tsv", ".json",
            ".log", ".tex", ".xml", ".html", ".htm", ".py", ".cfg", ".ini",
            ".yaml", ".yml", ".bib", ".tsv"}
OFFICE_EXT = {".docx", ".pptx", ".xlsx"}
PDF_EXT = {".pdf"}
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", ".DS_Store"}

PDFTOTEXT = shutil.which("pdftotext")
PDFTOPPM = shutil.which("pdftoppm")
TESSERACT = shutil.which("tesseract")

# ---------------------------------------------------------------- discovery

def iter_files(roots):
    """Yield file records for every reachable file under roots.
    Unreadable entries yield a record with readable=False instead of raising."""
    if isinstance(roots, (str, Path)):
        roots = [roots]
    for root in roots:
        root = Path(root)
        if root.is_file():
            yield _record(root, root.parent)
            continue
        for dirpath, dirnames, filenames in os.walk(root, onerror=lambda e: None):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
            for name in sorted(filenames):
                p = Path(dirpath) / name
                yield _record(p, root)


def _record(p, root):
    rec = {"path": str(p), "rel_path": os.path.relpath(str(p), str(root)),
           "name": p.name, "ext": p.suffix.lower(), "size": None,
           "mtime": None, "readable": True, "error": None}
    try:
        st = p.lstat()
        rec["size"], rec["mtime"] = st.st_size, int(st.st_mtime)
        if p.is_symlink():
            rec["error"] = "symlink_to:" + os.path.realpath(str(p))
        with open(p, "rb") as f:
            f.read(1)
    except PermissionError:
        rec["readable"] = False
        rec["error"] = "permission_denied"
    except OSError as e:
        rec["readable"] = False
        rec["error"] = "unreadable:" + e.__class__.__name__
    return rec


def sha256_file(path, _bufsize=1 << 20):
    h = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            while True:
                b = f.read(_bufsize)
                if not b:
                    break
                h.update(b)
        return h.hexdigest()
    except OSError:
        return None


# ---------------------------------------------------------------- extraction

class ExtractResult:
    def __init__(self):
        self.pages = []          # list[str]; one entry per page/sheet/slide
        self.page_kinds = []     # parallel labels, e.g. "page 1", "sheet 2"
        self.error = None
        self.needs_ocr = False   # pdf pages with no text layer
        self.ocr_pages = []      # page indices OCRed at ingest time


def extract_file(path, ext=None, try_ocr=True):
    """Return ExtractResult. Never raises; failures land in .error."""
    ext = (ext or Path(path).suffix.lower()).lower()
    r = ExtractResult()
    try:
        if ext in PDF_EXT:
            _extract_pdf(path, r, try_ocr)
        elif ext == ".docx":
            r.pages, r.page_kinds = [_extract_docx(path)], ["document"]
        elif ext == ".pptx":
            r.pages, r.page_kinds = _extract_pptx(path)
        elif ext == ".xlsx":
            r.pages, r.page_kinds = _extract_xlsx(path)
        elif ext in TEXT_EXT:
            r.pages = [Path(path).read_text(encoding="utf-8", errors="replace")]
            r.page_kinds = ["text"]
        else:
            r.error = "unsupported_ext:" + ext
            return r
    except PermissionError:
        r.error = "permission_denied"
        return r
    except Exception as e:  # corrupt zip, bad xml, ...
        r.error = "extract_failed:" + e.__class__.__name__
        return r
    if not any(p.strip() for p in r.pages) and r.error is None:
        if ext in PDF_EXT:
            r.needs_ocr = True
            if try_ocr:
                _try_ocr(path, r)
        else:
            r.error = "no_text_content"
    return r


def _extract_pdf(path, r, try_ocr):
    if PDFTOTEXT:
        proc = subprocess.run([PDFTOTEXT, "-layout", str(path), "-"],
                              capture_output=True, text=True, errors="replace",
                              timeout=120)
        if proc.returncode == 0:
            r.pages = proc.stdout.split("\f")
            if r.pages and not r.pages[-1].strip():
                r.pages.pop()
            r.page_kinds = [f"page {i+1}" for i in range(len(r.pages))]
            low = [i for i, p in enumerate(r.pages) if len(p.strip()) < 20]
            if low:
                r.needs_ocr = True
                if try_ocr:
                    _try_ocr(path, r, only=low)
            return
        err = proc.stderr.strip()
        if "password" in err.lower() or "encrypted" in err.lower():
            r.error = "encrypted_pdf"
            return
        r.error = "pdftotext_failed:" + err[:120]
        return
    # fallback: PyMuPDF if present
    try:
        import fitz  # type: ignore
    except ImportError:
        r.error = "no_pdf_tool:install pdftotext (poppler)"
        return
    doc = fitz.open(str(path))
    r.pages = [pg.get_text() for pg in doc]
    r.page_kinds = [f"page {i+1}" for i in range(len(r.pages))]
    r.needs_ocr = any(len(p.strip()) < 20 for p in r.pages)


def _try_ocr(path, r, only=None):
    """OCR no-text-layer pdf pages with tesseract when available."""
    if not (TESSERACT and PDFTOPPM and Path(path).suffix.lower() == ".pdf"):
        return
    only = only or list(range(len(r.pages)))
    try:
        out_prefix = os.path.join("/tmp", "seekline_ocr_%d" % os.getpid())
        subprocess.run([PDFTOPPM, "-r", "200", "-png", "-f", "1", "-l",
                        str(max(only) + 1), str(path), out_prefix],
                       capture_output=True, timeout=180)
        for i in only:
            img = f"{out_prefix}-{i+1:02d}.png"
            if not os.path.exists(img):
                img = f"{out_prefix}-{i+1}.png"
            if not os.path.exists(img):
                continue
            o = subprocess.run([TESSERACT, img, "-", "-l", "eng+chi_sim"],
                               capture_output=True, text=True,
                               errors="replace", timeout=120)
            if o.returncode == 0 and o.stdout.strip():
                r.pages[i] = o.stdout
                r.ocr_pages.append(i)
    except Exception:
        pass
    finally:
        for f in Path("/tmp").glob("seekline_ocr_%d*" % os.getpid()):
            try:
                f.unlink()
            except OSError:
                pass


_TAG = re.compile(r"<[^>]+>")


def _xml_text(raw):
    raw = re.sub(r"<w:tab[^>]*/>", "\t", raw)
    raw = re.sub(r"</w:p>|</a:p>|</row>|</w:tr>", "\n", raw)
    raw = _TAG.sub("", raw)
    return html.unescape(raw)


def _extract_docx(path):
    with zipfile.ZipFile(path) as z:
        try:
            raw = z.read("word/document.xml").decode("utf-8", "replace")
        except KeyError:
            raise ValueError("not a docx: missing word/document.xml")
    return _xml_text(raw)


def _extract_pptx(path):
    pages, kinds = [], []
    with zipfile.ZipFile(path) as z:
        slides = sorted((n for n in z.namelist()
                         if re.fullmatch(r"ppt/slides/slide\d+\.xml", n)),
                        key=lambda n: int(re.search(r"(\d+)", n).group(1)))
        for n in slides:
            raw = z.read(n).decode("utf-8", "replace")
            pages.append(_xml_text(raw))
            kinds.append("slide " + re.search(r"(\d+)", n).group(1))
    return pages, kinds


def _extract_xlsx(path):
    with zipfile.ZipFile(path) as z:
        names = set(z.namelist())
        shared = []
        if "xl/sharedStrings.xml" in names:
            sraw = z.read("xl/sharedStrings.xml").decode("utf-8", "replace")
            shared = [_TAG.sub("", m) for m in
                      re.findall(r"<si>(.*?)</si>", sraw, re.S)]
            shared = [html.unescape(re.sub(r"<[^>]+>", "", s)) for s in shared]
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
                if t == "s" and v:
                    cells.append(shared[int(v.group(1))] if v and int(v.group(1)) < len(shared) else "")
                elif t == "inlineStr" and isv:
                    cells.append(html.unescape(_TAG.sub("", isv.group(1))))
                elif v:
                    cells.append(html.unescape(v.group(1)))
                elif isv:
                    cells.append(html.unescape(_TAG.sub("", isv.group(1))))
            pages.append("\n".join(cells))
            kinds.append("sheet " + re.search(r"(\d+)", n).group(1))
    return pages, kinds


# ---------------------------------------------------------------- tokenize / normalize

_TOKEN = re.compile(r"[a-z0-9]+|[一-鿿]")


def tokens(text):
    """Lowercase alnum runs plus CJK unigrams; CJK bigrams added by index."""
    return _TOKEN.findall(text.lower())


def token_ngrams(text, cjk_bigrams=True):
    toks = tokens(text)
    out = list(toks)
    if cjk_bigrams:
        cjk = re.compile(r"^[一-鿿]$")
        prev = None
        for t in toks:
            if prev and cjk.match(prev) and cjk.match(t):
                out.append(prev + t)
            prev = t
    return out


def norm_ws(s):
    return re.sub(r"\s+", " ", s).strip()


def locate_quote(page_text, quote):
    """Find normalized quote in normalized page text. Return (start,end) char
    span on the normalized text, or None."""
    hay, needle = norm_ws(page_text), norm_ws(quote)
    if not needle:
        return None
    i = hay.find(needle)
    if i < 0:
        return None
    return (i, i + len(needle))


# ---------------------------------------------------------------- metadata heuristics

YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")
PROJ_RE = re.compile(r"\b[A-Z]{2,10}[-_]?\d{3,}\b")
VER_RE = re.compile(r"(?i)(v\d+|rev\s*\d+|r\d+|draft|final|revised|preprint"
                    r"|初稿|草稿|修订|修改稿|终稿|最终版|预印本)")
DATE_RE = re.compile(r"(20\d{2})[-_.年]?(\d{2})[-_.月]?(\d{2})")

HEAD_RE = re.compile(
    r"^(#{1,4}\s+.{1,70}"
    r"|第[0-9一二三四五六七八九十百]+[章节篇部分][\s:：、.．-]?.*"
    r"|摘要|Abstract|References?|参考文献|附录.*|Appendix.*"
    r"|[0-9]+(\.[0-9]+){0,3}[\s、.．]+.{1,60}"
    r"|[一二三四五六七八九十]+、.{1,60}"
    r"|[A-Z][A-Za-z &/-]{2,40})$")


def split_paragraphs(page_text):
    """Split page text into paragraphs. Prefer blank-line blocks; when the
    page is dense (few blocks, many lines) treat lines as paragraphs, gluing
    short continuation lines (<25 chars) onto the previous one."""
    blocks = [b.strip() for b in re.split(r"\n\s*\n", page_text) if b.strip()]
    lines = [l.strip() for l in page_text.splitlines() if l.strip()]
    if len(blocks) > 2 or len(lines) <= 3:
        return blocks if blocks else lines
    return lines


def find_sections(page_texts):
    """Detect section headings across pages. Returns list of dicts:
    {heading, page (0-based physical), para_index, snippet}."""
    secs = []
    seen = set()
    for pi, ptext in enumerate(page_texts):
        page_norm = norm_ws(ptext)
        candidates = []
        for block in split_paragraphs(ptext):
            first = block.splitlines()[0].strip() if block else ""
            off = page_norm.find(norm_ws(first)[:40]) if first else -1
            candidates.append((first, norm_ws(block)[:160], off))
        for line in ptext.splitlines():
            ls = line.strip()
            candidates.append((ls, ls[:160], page_norm.find(norm_ws(ls)[:40])))
        for cand, snippet, off in candidates:
            cand = cand[:80]
            key = (pi, cand)
            if len(cand) >= 2 and HEAD_RE.match(cand) and key not in seen:
                seen.add(key)
                secs.append({"heading": cand, "page": pi, "offset": off,
                             "snippet": snippet})
    secs.sort(key=lambda s: (s["page"], s["offset"] if s["offset"] >= 0 else 0))
    return secs


def printed_page_offset(page_texts):
    """Detect printed-vs-physical page offset from '第 N 页' / 'Page N' markers
    in page head/tour. Returns dict {physical_index: printed} when consistent."""
    mapping = {}
    for i, p in enumerate(page_texts):
        head = p[:300] + p[-300:]
        m = re.search(r"第\s*(\d{1,4})\s*页", head) or \
            re.search(r"(?i)page\s+(\d{1,4})\b", head)
        if m:
            mapping[i] = int(m.group(1))
    if len(mapping) >= 2:
        offsets = {v - k for k, v in mapping.items()}
        if len(offsets) == 1:
            off = offsets.pop()
            return {k: k + off for k in range(len(page_texts))}
        return dict(mapping)
    return mapping


def guess_meta(name, page_texts):
    """Cheap metadata guesses: year, project ids, version tag, date."""
    head = "\n".join(page_texts[:2])[:4000]
    year = None
    m = YEAR_RE.search(head) or YEAR_RE.search(name)
    if m:
        year = int(m.group(0))
    projs = sorted(set(PROJ_RE.findall(head)))
    vm = VER_RE.search(name)
    ver = vm.group(1) if vm else None
    date = None
    dm = DATE_RE.search(name) or DATE_RE.search(head[:1000])
    if dm:
        date = "%s-%s-%s" % dm.groups()
    return {"year": year, "project_ids": projs, "version_tag": ver,
            "date": date}
