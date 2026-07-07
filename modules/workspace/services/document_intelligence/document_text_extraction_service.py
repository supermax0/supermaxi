from __future__ import annotations

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
        warnings: List[str] = []
        partial_pages: List[Dict[str, Any]] = []

        for extractor in (
            DocumentTextExtractionService._try_fitz_text,
            DocumentTextExtractionService._try_pypdf_text,
            DocumentTextExtractionService._try_pdfplumber_text,
        ):
            try:
                payload = extractor(abs_path)
            except Exception as exc:
                warnings.append(str(exc))
                continue
            if not payload:
                continue
            partial_pages = payload.get("pages") or partial_pages
            text = (payload.get("text") or "").strip()
            if text:
                return DocumentTextExtractionService._result(
                    "completed",
                    text,
                    payload.get("pages") or [],
                    warnings=warnings,
                )
            if payload.get("image_only_pdf"):
                warnings.append("PDF لا يحتوي طبقة نص ويبدو أنه صور ممسوحة")
                break

        ocr_payload = DocumentTextExtractionService._try_fitz_ocr(abs_path)
        if ocr_payload and (ocr_payload.get("text") or "").strip():
            warnings.append("تم استخدام OCR لأن PDF لا يحتوي طبقة نص قابلة للقراءة")
            warnings.extend(ocr_payload.get("warnings") or [])
            return DocumentTextExtractionService._result(
                "completed",
                ocr_payload.get("text") or "",
                ocr_payload.get("pages") or [],
                warnings=warnings,
            )
        if ocr_payload:
            warnings.extend(ocr_payload.get("warnings") or [])

        if partial_pages:
            return DocumentTextExtractionService._result(
                "partial",
                "",
                partial_pages,
                warnings=warnings + ["لم يُعثر على طبقة نص في PDF"],
            )

        if warnings:
            return DocumentTextExtractionService._result("failed", warnings=warnings)

        return DocumentTextExtractionService._not_available(
            "تعذّر قراءة PDF — ثبّت pypdf أو pymupdf، أو تأكد من توفر Tesseract للملفات الممسوحة"
        )

    @staticmethod
    def _try_fitz_text(abs_path: str) -> Optional[Dict[str, Any]]:
        try:
            import fitz  # type: ignore
        except ImportError:
            return None

        pages_out: List[Dict[str, Any]] = []
        full_parts: List[str] = []
        with fitz.open(abs_path) as doc:
            image_pages = 0
            for i, page in enumerate(doc, start=1):
                page_text = DocumentNormalizationService.normalize_text(page.get_text("text") or "")
                if not page_text and page.get_images(full=True):
                    image_pages += 1
                pages_out.append({
                    "page": i,
                    "text": page_text,
                    "confidence": None,
                    "method": "pdf_text",
                })
                full_parts.append(page_text)
        full_text = "\n".join(full_parts).strip()
        return {
            "text": full_text,
            "pages": pages_out,
            "image_only_pdf": bool(pages_out) and not full_text and image_pages == len(pages_out),
        }

    @staticmethod
    def _try_pypdf_text(abs_path: str) -> Optional[Dict[str, Any]]:
        try:
            from pypdf import PdfReader  # type: ignore
        except ImportError:
            try:
                from PyPDF2 import PdfReader  # type: ignore
            except ImportError:
                return None

        reader = PdfReader(abs_path)
        pages_out: List[Dict[str, Any]] = []
        full_parts: List[str] = []
        for i, page in enumerate(reader.pages, start=1):
            page_text = DocumentNormalizationService.normalize_text(page.extract_text() or "")
            pages_out.append({
                "page": i,
                "text": page_text,
                "confidence": None,
                "method": "pdf_text",
            })
            full_parts.append(page_text)
        return {"text": "\n".join(full_parts).strip(), "pages": pages_out}

    @staticmethod
    def _try_pdfplumber_text(abs_path: str) -> Optional[Dict[str, Any]]:
        try:
            import pdfplumber  # type: ignore
        except ImportError:
            return None

        pages_out: List[Dict[str, Any]] = []
        full_parts: List[str] = []
        with pdfplumber.open(abs_path) as pdf:
            for i, page in enumerate(pdf.pages, start=1):
                page_text = DocumentNormalizationService.normalize_text(page.extract_text() or "")
                pages_out.append({
                    "page": i,
                    "text": page_text,
                    "confidence": None,
                    "method": "pdf_text",
                })
                full_parts.append(page_text)
        return {"text": "\n".join(full_parts).strip(), "pages": pages_out}

    @staticmethod
    def _try_fitz_ocr(abs_path: str) -> Optional[Dict[str, Any]]:
        try:
            import pytesseract  # type: ignore
        except ImportError:
            return None

        pages_out: List[Dict[str, Any]] = []
        full_parts: List[str] = []
        warnings: List[str] = []

        try:
            pytesseract.get_tesseract_version()
        except Exception:
            warnings.append("OCR غير متوفر — ثبّت Tesseract مع اللغة العربية لقراءة PDF الممسوح")
            return {"text": "", "pages": pages_out, "warnings": warnings}

        try:
            import fitz  # type: ignore
            from ai.ocr import extract_text
        except ImportError:
            return None

        try:
            with fitz.open(abs_path) as doc:
                for i, page in enumerate(doc, start=1):
                    pix = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
                    page_text = extract_text(pix.tobytes("png")) or ""
                    page_text = DocumentNormalizationService.normalize_text(page_text)
                    pages_out.append({
                        "page": i,
                        "text": page_text,
                        "confidence": None,
                        "method": "pdf_ocr",
                    })
                    full_parts.append(page_text)
        except Exception as exc:
            err = str(exc).lower()
            if "tesseract" in err or "pytesseract" in err:
                warnings.append("OCR غير متوفر — ثبّت Tesseract لقراءة PDF الممسوح")
                return {"text": "", "pages": pages_out, "warnings": warnings}
            warnings.append(str(exc))
            return {"text": "", "pages": pages_out, "warnings": warnings}

        return {"text": "\n".join(full_parts).strip(), "pages": pages_out, "warnings": warnings}

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
