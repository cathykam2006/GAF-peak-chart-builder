"""
Fast, cached PDF text extraction shared by both pages.  Created by Cathy Kam.

pypdfium2 reads a 250-page filing in ~2 s (pdfplumber takes ~35 s).  Results
are cached by file content, so a file is read once per session no matter how
many times the page reruns.
"""

import hashlib
import io
import re

import streamlit as st

# Titles such as "Typical Residential Heating (R-3)" or "Proposed ... Compared
# to ..." are often stored last in the PDF's text stream; move them to the top
# so the parsers see them where they appear on the printed page.
TITLE_RE = re.compile(r"^\s*typical\b|compared to|\bvs\.?\s", re.I)


def normalize(lines):
    lines = [l.rstrip() for l in lines]
    titles = [l for l in lines if TITLE_RE.search(l) and not re.match(r"^\s*\d", l)]
    if not titles:
        return lines
    rest = [l for l in lines if l not in titles]
    # keep the company / docket header first, then the titles
    head = rest[:6]
    return head + titles + rest[6:]


def file_id(data):
    return hashlib.sha1(data).hexdigest()


@st.cache_data(show_spinner=False, max_entries=64)
def pdf_pages(data):
    """bytes -> list of pages, each a list of text lines."""
    try:
        import pypdfium2 as pdfium
        doc = pdfium.PdfDocument(data)
        pages = []
        for i in range(len(doc)):
            page = doc[i]
            tp = page.get_textpage()
            pages.append(normalize(tp.get_text_range().splitlines()))
            tp.close()
            page.close()
        doc.close()
        return pages
    except Exception:  # noqa: BLE001 - fall back to the slower reader
        import pdfplumber
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            return [normalize((p.extract_text() or "").splitlines()) for p in pdf.pages]
