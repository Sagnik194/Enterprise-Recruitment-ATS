"""Strict-ish structural validation; not a replacement for malware scanning."""
from __future__ import annotations
import io
import re
from pathlib import Path

MAX_PDF_BYTES = 5 * 1024 * 1024

class InvalidResume(ValueError):
    pass


def validate_resume_pdf(data: bytes, filename: str, max_bytes: int = MAX_PDF_BYTES) -> bytes:
    if not filename or Path(filename.replace('\\', '/')).name != filename.replace('\\', '/'):
        raise InvalidResume("Invalid filename")
    if not filename.lower().endswith('.pdf'):
        raise InvalidResume("Only .pdf resumes are accepted")
    if not data or len(data) > max_bytes:
        raise InvalidResume("PDF is empty or exceeds the 5 MB limit")
    if not re.match(rb'^%PDF-1\.[0-7]\b|^%PDF-2\.0\b', data):
        raise InvalidResume("Invalid PDF header")
    if b'%%EOF' not in data[-2048:]:
        raise InvalidResume("Missing PDF end marker")
    # Use pypdf to parse the cross-reference and page tree.
    try:
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(data), strict=True)
        if reader.is_encrypted:
            raise InvalidResume("Password-protected PDFs are not supported")
        if len(reader.pages) < 1 or len(reader.pages) > 30:
            raise InvalidResume("Resume must contain 1 to 30 pages")
        for page in reader.pages:
            _ = page.mediabox
    except InvalidResume:
        raise
    except Exception as exc:
        raise InvalidResume("Malformed or unsupported PDF") from exc
    return data


def read_resume_upload(upload, max_bytes: int = MAX_PDF_BYTES) -> bytes:
    """Read at most max+1 bytes; never trust client Content-Type."""
    data = upload.file.read(max_bytes + 1)
    return validate_resume_pdf(data, upload.filename or '', max_bytes)
