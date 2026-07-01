from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from modules.workspace.services.document_intelligence.document_normalization_service import (
    DocumentNormalizationService,
)

TEXT_SAMPLE_LEN = 500


class DocumentTextExtractionService:
    @staticmethod
    def extract_from_file(abs_path: str, mime_type: str, filename: str = "") -> Dict[str, Any]:
        mime = (mime_type or "").lower()
        name = (filename or "").lower()

        if mime == "application/pdf" or name.endswith(".pdf"):
            return DocumentTextExtractionService._extract_pdf(abs_path)
        if mime.startswith("image/") or name.endswith((".png", ".jpg", ".jpeg", ".webp", ".gif")):
            return DocumentTextExtractionService._extract_image(abs_path)
        return DocumentTextExtractionService._not_available("نوع الملف غير مدعوم لاستخراج النص")

    @staticmethod
    def _sample(text: str) -> str:
        return (text or "")[:TEXT_SAMPLE_LEN]

    @staticmethod
    def _result(
        status: str,
        text: str = "",
        pages: Optional[List[Dict[str, Any]]] = None,
        warnings: Optional[List[str]] = None,
        message: Optional[str] = None,
    ) -> Dict[str, Any]:
        pages = pages or []
        warnings = list(warnings or [])
        if message:
            warnings.append(message)
        return {
            "status": status,
            "text": text or "",
            "text_sample": DocumentTextExtractionService._sample(text),
            "pages": pages,
            "warnings": warnings,
        }

    @staticmethod
    def _not_available(message: str) -> Dict[str, Any]:
        return DocumentTextExtractionService._result(
            "not_available",
            pages=[{"page": 1, "text": "", "confidence": None, "method": "not_available"}],
            message=message,
        )

    @staticmethod
    def _extract_pdf(abs_path: str) -> Dict[str, Any]:
        # pymupdf / fitz
        try:
            import fitz  # type: ignore

            pages_out = []
            full_parts = []
            with fitz.open(abs_path) as doc:
                for i, page in enumerate(doc, start=1):
                    page_text = page.get_text("text") or ""
                    page_text = DocumentNormalizationService.normalize_text(page_text)
                    pages_out.append({
                        "page": i,
                        "text": page_text,
                        "confidence": None,
                        "method": "pdf_text",
                    })
                    full_parts.append(page_text)
            full_text = "\n".join(full_parts).strip()
            if full_text:
                return DocumentTextExtractionService._result("completed", full_text, pages_out)
            return DocumentTextExtractionService._result(
                "partial",
                "",
                pages_out,
                warnings=["لم يُعثر على طبقة نص في PDF"],
            )
        except ImportError:
            pass
        except Exception as exc:
            return DocumentTextExtractionService._result(
                "failed",
                pages=[{"page": 1, "text": "", "confidence": None, "method": "pdf_text"}],
                warnings=[str(exc)],
            )

        # pdfplumber fallback
        try:
            import pdfplumber  # type: ignore

            pages_out = []
            full_parts = []
            with pdfplumber.open(abs_path) as pdf:
                for i, page in enumerate(pdf.pages, start=1):
                    page_text = page.extract_text() or ""
                    page_text = DocumentNormalizationService.normalize_text(page_text)
                    pages_out.append({
                        "page": i,
                        "text": page_text,
                        "confidence": None,
                        "method": "pdf_text",
                    })
                    full_parts.append(page_text)
            full_text = "\n".join(full_parts).strip()
            if full_text:
                return DocumentTextExtractionService._result("completed", full_text, pages_out)
            return DocumentTextExtractionService._result(
                "partial",
                "",
                pages_out,
                warnings=["لم يُعثر على طبقة نص في PDF"],
            )
        except ImportError:
            pass
        except Exception as exc:
            return DocumentTextExtractionService._result(
                "failed",
                warnings=[str(exc)],
            )

        # PyPDF2 fallback
        try:
            from PyPDF2 import PdfReader  # type: ignore

            reader = PdfReader(abs_path)
            pages_out = []
            full_parts = []
            for i, page in enumerate(reader.pages, start=1):
                page_text = page.extract_text() or ""
                page_text = DocumentNormalizationService.normalize_text(page_text)
                pages_out.append({
                    "page": i,
                    "text": page_text,
                    "confidence": None,
                    "method": "pdf_text",
                })
                full_parts.append(page_text)
            full_text = "\n".join(full_parts).strip()
            if full_text:
                return DocumentTextExtractionService._result("completed", full_text, pages_out)
            return DocumentTextExtractionService._result("partial", "", pages_out)
        except ImportError:
            return DocumentTextExtractionService._not_available(
                "PDF text extraction dependency not installed"
            )
        except Exception as exc:
            return DocumentTextExtractionService._result("failed", warnings=[str(exc)])

    @staticmethod
    def _extract_image(abs_path: str) -> Dict[str, Any]:
        try:
            with open(abs_path, "rb") as f:
                image_bytes = f.read()
            from ai.ocr import extract_text

            text = extract_text(image_bytes) or ""
            text = DocumentNormalizationService.normalize_text(text)
            if text.strip():
                return DocumentTextExtractionService._result(
                    "completed",
                    text,
                    [{"page": 1, "text": text, "confidence": None, "method": "ocr"}],
                )
            return DocumentTextExtractionService._result(
                "partial",
                "",
                [{"page": 1, "text": "", "confidence": None, "method": "ocr"}],
                warnings=["لم يُستخرج نص من الصورة"],
            )
        except ImportError:
            return DocumentTextExtractionService._not_available("OCR dependency not available")
        except Exception as exc:
            err = str(exc).lower()
            if "tesseract" in err or "pytesseract" in err:
                return DocumentTextExtractionService._not_available("OCR not available")
            return DocumentTextExtractionService._result(
                "failed",
                warnings=[str(exc)],
                pages=[{"page": 1, "text": "", "confidence": None, "method": "ocr"}],
            )
