"""Bounded local text extraction. Uploaded content is never executed or fetched."""

import base64
import binascii
import csv
import hashlib
import importlib.util
import io
import json
from pathlib import PurePosixPath
import re
import subprocess
import sys
import zipfile
import xml.etree.ElementTree as ET

MAX_UPLOAD_BYTES = 4 * 1024 * 1024
MAX_TEXT_CHARACTERS = 250_000
MAX_ZIP_EXPANSION = 16 * 1024 * 1024
PDF_MEMORY_BYTES = 256 * 1024 * 1024
PDF_TIMEOUT_SECONDS = 20


def _bounded_text(text):
    if not isinstance(text, str) or not text.strip():
        raise ValueError("No readable text was extracted; scanned documents require a separate OCR workflow")
    if len(text) > MAX_TEXT_CHARACTERS:
        raise ValueError("Extracted text exceeds 250,000 characters; split the source before importing")
    if "\x00" in text:
        raise ValueError("Text contains binary null characters")
    return text


def _docx(raw):
    try:
        archive = zipfile.ZipFile(io.BytesIO(raw))
        entries = archive.infolist()
        if len(entries) > 256 or len({entry.filename for entry in entries}) != len(entries):
            raise ValueError("DOCX archives must contain at most 256 unique entries")
        total = 0
        for entry in entries:
            path = PurePosixPath(entry.filename)
            if (path.is_absolute() or ".." in path.parts or "\\" in entry.filename or ":" in entry.filename
                    or entry.flag_bits & 1 or (entry.external_attr >> 16) & 0o170000 == 0o120000):
                raise ValueError("DOCX contains unsafe archive paths, links or encrypted entries")
            total += entry.file_size
            if total > MAX_ZIP_EXPANSION or entry.file_size > MAX_ZIP_EXPANSION:
                raise ValueError("DOCX expanded content exceeds the 16 MiB limit")
            if entry.file_size > 1_048_576 and entry.file_size > max(1, entry.compress_size) * 150:
                raise ValueError("DOCX compression ratio exceeds the safe extraction limit")
        if "word/document.xml" not in archive.namelist():
            raise ValueError("The file is not a DOCX document")
        if archive.getinfo("word/document.xml").file_size > 4 * 1024 * 1024:
            raise ValueError("DOCX main-document XML exceeds the 4 MiB limit")
        xml = archive.read("word/document.xml")
        if b"\x00" in xml:
            raise ValueError("DOCX main-document XML must use UTF-8 encoding")
        if b"<!DOCTYPE" in xml.upper() or b"<!ENTITY" in xml.upper():
            raise ValueError("DOCX entities and document type declarations are not supported")
        root = ET.fromstring(xml)
        paragraphs = []
        for paragraph in root.iter("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}p"):
            text = []
            for child in paragraph.iter():
                if child.tag.endswith("}t"):
                    text.append(child.text or "")
                elif child.tag.endswith("}tab"):
                    text.append("\t")
                elif child.tag.endswith("}br"):
                    text.append("\n")
            paragraphs.append("".join(text))
        text = _bounded_text("\n\n".join(paragraphs))
        warnings = ["Only main-document text was extracted. Headers, footers, comments, images and embedded objects are not included.",
                    "Review tables, layout and numbering before using extracted text as evidence."]
        if any("vba" in entry.filename.casefold() or entry.filename.casefold().endswith(".bin") for entry in entries):
            warnings.append("Binary or macro-like archive entries were ignored; no embedded content was executed.")
        return text, {"paragraphs": len(paragraphs), "archive_entries": len(entries)}, warnings
    except (zipfile.BadZipFile, ET.ParseError, OSError, RuntimeError) as exc:
        raise ValueError(f"DOCX extraction failed: {exc}") from exc
    finally:
        if "archive" in locals():
            archive.close()


def _limit_pdf_worker():
    """Apply a resource boundary before importing the optional PDF parser."""
    if sys.platform != "win32":
        import resource
        resource.setrlimit(resource.RLIMIT_AS, (PDF_MEMORY_BYTES, PDF_MEMORY_BYTES))
        return
    import ctypes
    from ctypes import wintypes
    class BasicLimit(ctypes.Structure):
        _fields_ = [("process_time", ctypes.c_longlong), ("job_time", ctypes.c_longlong),
                    ("flags", wintypes.DWORD), ("minimum_working", ctypes.c_size_t),
                    ("maximum_working", ctypes.c_size_t), ("active_processes", wintypes.DWORD),
                    ("affinity", ctypes.c_size_t), ("priority", wintypes.DWORD), ("scheduling", wintypes.DWORD)]
    class Counters(ctypes.Structure):
        _fields_ = [(name, ctypes.c_ulonglong) for name in ("read_ops", "write_ops", "other_ops", "read_bytes", "write_bytes", "other_bytes")]
    class ExtendedLimit(ctypes.Structure):
        _fields_ = [("basic", BasicLimit), ("io", Counters), ("process_memory", ctypes.c_size_t),
                    ("job_memory", ctypes.c_size_t), ("peak_process_memory", ctypes.c_size_t), ("peak_job_memory", ctypes.c_size_t)]
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    kernel.CreateJobObjectW.restype = wintypes.HANDLE
    kernel.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    kernel.SetInformationJobObject.restype = wintypes.BOOL
    kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    kernel.AssignProcessToJobObject.restype = wintypes.BOOL
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    job = kernel.CreateJobObjectW(None, None)
    if not job:
        raise OSError("Could not create PDF parser memory boundary")
    limits = ExtendedLimit()
    limits.basic.flags = 0x00000100  # JOB_OBJECT_LIMIT_PROCESS_MEMORY
    limits.process_memory = PDF_MEMORY_BYTES
    if not kernel.SetInformationJobObject(job, 9, ctypes.byref(limits), ctypes.sizeof(limits)) or not kernel.AssignProcessToJobObject(job, kernel.GetCurrentProcess()):
        raise OSError("Could not apply the PDF parser memory boundary")
    # Keep the job handle alive until this short-lived worker exits.
    _limit_pdf_worker.job_handle = job


def _pdf_worker_main():
    try:
        _limit_pdf_worker()
        from pypdf import PdfReader
        raw = sys.stdin.buffer.read(MAX_UPLOAD_BYTES + 1)
        if len(raw) > MAX_UPLOAD_BYTES:
            raise ValueError("PDF exceeds the upload limit")
        reader = PdfReader(io.BytesIO(raw), strict=True)
        if reader.is_encrypted:
            raise ValueError("Encrypted PDFs are not supported")
        if len(reader.pages) > 100:
            raise ValueError("PDF extraction is limited to 100 pages")
        pages, blank = [], 0
        characters = 0
        for index, page in enumerate(reader.pages, 1):
            text = page.extract_text() or ""
            blank += not bool(text.strip())
            characters += len(text)
            if characters > MAX_TEXT_CHARACTERS:
                raise ValueError("Extracted PDF text exceeds 250,000 characters")
            pages.append(f"[Page {index}]\n{text}" if text.strip() else "")
        text = _bounded_text("\n\n".join(pages))
        warnings = ["PDF text order and table layout may differ from the visual document; review the extracted evidence."]
        if blank:
            warnings.append(f"{blank} page(s) had no extractable text. No OCR was performed.")
        result = {"text": text, "metadata": {"pages": len(pages), "pages_without_text": blank}, "warnings": warnings}
    except Exception as exc:
        result = {"error": f"PDF extraction failed: {type(exc).__name__}: {str(exc)[:500]}"}
    sys.stdout.write(json.dumps(result, ensure_ascii=True))


def _pdf(raw):
    if not raw.startswith(b"%PDF-"):
        raise ValueError("The file does not have a PDF header")
    if importlib.util.find_spec("pypdf") is None:
        raise ValueError("PDF extraction requires the optional pypdf dependency; install it before importing PDFs")
    try:
        result = subprocess.run([sys.executable, "-c", "from spades.ingestion import _pdf_worker_main; _pdf_worker_main()"],
                                input=raw, capture_output=True, timeout=PDF_TIMEOUT_SECONDS, check=False)
    except (subprocess.TimeoutExpired, OSError) as exc:
        raise ValueError("PDF extraction exceeded its 20-second processing limit or the isolated parser could not start") from exc
    if result.returncode != 0 or len(result.stdout) > 2_000_000:
        raise ValueError("The isolated PDF parser failed or exceeded its 256 MiB memory limit")
    try:
        data = json.loads(result.stdout)
    except (ValueError, UnicodeError) as exc:
        raise ValueError("The isolated PDF parser returned invalid extraction data") from exc
    if data.get("error"):
        raise ValueError(data["error"])
    return _bounded_text(data["text"]), data["metadata"], data["warnings"]


def extract_document(filename, base64_data):
    """Extract a bounded uploaded document, returning text and byte provenance.

    ``filename`` is a display basename, never a local path. ``base64_data`` must
    be strict base64 without a data-URL prefix. No extraction writes files.
    """
    if (not isinstance(filename, str) or not 1 <= len(filename) <= 255
            or any(character in filename for character in "/\\:\x00\r\n") or filename in (".", "..")):
        raise ValueError("Provide a filename only, not a filesystem path or URL")
    extension = "." + filename.rsplit(".", 1)[-1].casefold() if "." in filename else ""
    if extension not in (".txt", ".md", ".markdown", ".csv", ".docx", ".pdf"):
        raise ValueError("Supported uploads are TXT, Markdown, CSV, DOCX and PDF")
    if not isinstance(base64_data, str) or len(base64_data) > ((MAX_UPLOAD_BYTES + 2) // 3) * 4:
        raise ValueError("Uploaded document exceeds the 4 MiB limit")
    try:
        raw = base64.b64decode(base64_data, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("Document data must be strict base64") from exc
    if not raw or len(raw) > MAX_UPLOAD_BYTES:
        raise ValueError("Uploaded document must contain 1 byte to 4 MiB")
    digest = hashlib.sha256(raw).hexdigest()
    metadata, warnings = {}, []
    if extension == ".docx":
        text, metadata, warnings = _docx(raw)
    elif extension == ".pdf":
        text, metadata, warnings = _pdf(raw)
    else:
        try:
            text = _bounded_text(raw.decode("utf-8-sig"))
        except UnicodeError as exc:
            raise ValueError("Text and CSV documents must be UTF-8 encoded") from exc
        if extension == ".csv":
            try:
                reader = csv.reader(io.StringIO(text), strict=True)
                rows = list(reader)
            except csv.Error as exc:
                raise ValueError(f"CSV extraction failed: {exc}") from exc
            if len(rows) > 10_000 or any(len(row) > 100 for row in rows):
                raise ValueError("CSV extraction is limited to 10,000 rows and 100 columns")
            # Preserve the original textual CSV evidence rather than silently
            # interpreting formulas, numeric types, dates or missing cells.
            metadata = {"rows": len(rows), "maximum_columns": max((len(row) for row in rows), default=0)}
            warnings.append("CSV cells remain text. Formulas were not evaluated, and numeric/date types were not inferred.")
    return {"filename": filename, "format": extension.removeprefix("."), "sha256": digest,
            "byte_count": len(raw), "characters": len(text), "text": text,
            "warnings": warnings, "metadata": metadata}
