import base64
import hashlib
import importlib.util
import io
import json
import subprocess
import unittest
from unittest.mock import patch
import zipfile

from spades.ingestion import extract_document


def encoded(raw):return base64.b64encode(raw).decode("ascii")


def docx(xml,extra=None):
    buffer=io.BytesIO()
    with zipfile.ZipFile(buffer,"w",zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("word/document.xml",xml)
        for name,value in (extra or {}).items():archive.writestr(name,value)
    return buffer.getvalue()


def small_pdf():
    stream=b"BT /F1 12 Tf 40 700 Td (Revenue is 100 EUR.) Tj ET"
    objects=[b"<< /Type /Catalog /Pages 2 0 R >>",b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",b"<< /Length "+str(len(stream)).encode()+b" >>\nstream\n"+stream+b"\nendstream"]
    result=b"%PDF-1.4\n";offsets=[0]
    for index,obj in enumerate(objects,1):offsets.append(len(result));result+=f"{index} 0 obj\n".encode()+obj+b"\nendobj\n"
    xref=len(result);result+=f"xref\n0 {len(objects)+1}\n0000000000 65535 f \n".encode()
    result+=b"".join(f"{offset:010d} 00000 n \n".encode() for offset in offsets[1:])
    return result+f"trailer\n<< /Size {len(objects)+1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()


class IngestionTests(unittest.TestCase):
    def test_utf8_markdown_and_original_bytes_are_preserved(self):
        raw=b"\xef\xbb\xbf# Approved order\nAnnual budget: 3000 EUR.\n"
        result=extract_document("order.md",encoded(raw))
        self.assertTrue(result["text"].startswith("# Approved"))
        self.assertEqual(result["sha256"],hashlib.sha256(raw).hexdigest())
        self.assertEqual(result["byte_count"],len(raw))

    def test_csv_is_preserved_as_text_without_formula_execution_or_type_coercion(self):
        raw=b'account,budget\n"0007","=2+2"\n'
        result=extract_document("budget.csv",encoded(raw))
        self.assertEqual(result["text"],raw.decode())
        self.assertEqual(result["metadata"],{"rows":2,"maximum_columns":2})
        self.assertIn("not evaluated",result["warnings"][0])

    def test_main_docx_paragraph_text_and_tabs_are_extracted(self):
        xml=b'<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>Approved</w:t><w:tab/><w:t>budget</w:t></w:r></w:p><w:p><w:r><w:t>3000 EUR</w:t></w:r></w:p></w:body></w:document>'
        result=extract_document("order.docx",encoded(docx(xml,{"word/vbaProject.bin":b"never executed"})))
        self.assertEqual(result["text"],"Approved\tbudget\n\n3000 EUR")
        self.assertTrue(any("ignored" in warning for warning in result["warnings"]))

    def test_paths_urls_formats_and_malformed_base64_are_rejected(self):
        for name in ("../secret.txt","C:\\secret.txt","https://site/file.txt","file.docm","file.exe"):
            with self.assertRaises(ValueError):extract_document(name,encoded(b"text"))
        for value in ("not base64!","data:text/plain;base64,dGV4dA==",""):
            with self.assertRaises(ValueError):extract_document("file.txt",value)
        with self.assertRaises(ValueError):extract_document("file.txt",encoded(b"\xff"))
        with self.assertRaises(ValueError):extract_document("file.txt",encoded(b"binary\x00text"))

    def test_unsafe_docx_archives_entities_and_extraction_limits_are_rejected(self):
        xml=b'<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:p><w:r><w:t>text</w:t></w:r></w:p></w:document>'
        for extra in ({"../outside.txt":b"bad"},{"/absolute":b"bad"}):
            with self.assertRaises(ValueError):extract_document("file.docx",encoded(docx(xml,extra)))
        with self.assertRaises(ValueError):extract_document("file.docx",encoded(docx(b'<!DOCTYPE x [<!ENTITY a "bad">]><x>&a;</x>')))
        with self.assertRaises(ValueError):extract_document("file.docx",encoded(docx(xml.decode().encode("utf-16"))))
        with self.assertRaises(ValueError):extract_document("large.txt",encoded(b"x"*250001))

    def test_missing_pdf_capability_reports_a_clear_error(self):
        with patch("spades.ingestion.importlib.util.find_spec",return_value=None):
            with self.assertRaisesRegex(ValueError,"pypdf"):extract_document("file.pdf",encoded(small_pdf()))

    def test_pdf_worker_timeout_and_failure_are_bounded(self):
        with patch("spades.ingestion.importlib.util.find_spec",return_value=object()),patch("spades.ingestion.subprocess.run",side_effect=subprocess.TimeoutExpired("python",20)):
            with self.assertRaisesRegex(ValueError,"20-second"):extract_document("file.pdf",encoded(small_pdf()))
        result=subprocess.CompletedProcess([],1,b"",b"")
        with patch("spades.ingestion.importlib.util.find_spec",return_value=object()),patch("spades.ingestion.subprocess.run",return_value=result):
            with self.assertRaisesRegex(ValueError,"256 MiB"):extract_document("file.pdf",encoded(small_pdf()))

    @unittest.skipUnless(importlib.util.find_spec("pypdf"),"optional pypdf dependency is not installed")
    def test_real_pdf_text_is_extracted_in_the_resource_limited_worker(self):
        result=extract_document("revenue.pdf",encoded(small_pdf()))
        self.assertIn("Revenue is 100 EUR",result["text"])
        self.assertEqual(result["metadata"]["pages"],1)
