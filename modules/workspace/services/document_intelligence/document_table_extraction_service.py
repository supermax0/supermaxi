from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from modules.workspace.services.document_intelligence.document_normalization_service import (
    DocumentNormalizationService,
)

LINE_SPLIT = re.compile(r"[\t|؛]+| {2,}")
USEFUL_TOKEN = re.compile(r"[\w\u0600-\u06FF#]+", re.UNICODE)
PHONE_IN_LINE = re.compile(r"0?7[0-9]{9}")


class DocumentTableExtractionService:
    @staticmethod
    def extract_tables(
        abs_path: str,
        mime_type: str,
        extracted_text: str,
        pages: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        mime = (mime_type or "").lower()
        warnings: List[str] = []

        if mime == "application/pdf":
            has_text = bool((extracted_text or "").strip()) or any(
                (page.get("text") or "").strip() for page in (pages or [])
            )
            if not has_text:
                return {
                    "status": "not_available",
                    "tables": [],
                    "warnings": ["لا يوجد نص لاستخراج الجداول من PDF"],
                }
            for extractor in (
                DocumentTableExtractionService._try_fitz_tables,
                DocumentTableExtractionService._try_pdfplumber,
            ):
                pdf_tables = extractor(abs_path)
                if pdf_tables is not None:
                    if pdf_tables:
                        return {"status": "completed", "tables": pdf_tables, "warnings": warnings}
                    warnings.append("لم تُستخرج جداول من PDF — استخدام heuristic")
                    break

        text = extracted_text or ""
        if not text.strip():
            for page in pages or []:
                text += "\n" + (page.get("text") or "")
        text = text.strip()
        if not text:
            return {
                "status": "not_available",
                "tables": [],
                "warnings": ["لا يوجد نص لاستخراج الجداول"],
            }

        tables = DocumentTableExtractionService._heuristic_from_text(text)
        status = "completed" if tables else "partial"
        if not tables:
            warnings.append("لم تُكتشف صفوف جدول من النص")
        return {"status": status, "tables": tables, "warnings": warnings}

    @staticmethod
    def _try_fitz_tables(abs_path: str) -> Optional[List[Dict[str, Any]]]:
        try:
            import fitz  # type: ignore
        except ImportError:
            return None

        tables_out: List[Dict[str, Any]] = []
        try:
            with fitz.open(abs_path) as pdf:
                idx = 0
                for page_num, page in enumerate(pdf, start=1):
                    finder = getattr(page, "find_tables", None)
                    if not callable(finder):
                        continue
                    try:
                        discovered = finder()
                    except Exception:
                        continue
                    raw_tables = getattr(discovered, "tables", None) or []
                    for tbl in raw_tables:
                        data = tbl.extract() if hasattr(tbl, "extract") else None
                        if not data:
                            continue
                        rows = [
                            [DocumentNormalizationService.normalize_text(str(c or "")) for c in row]
                            for row in data
                            if row and any(str(c or "").strip() for c in row)
                        ]
                        if len(rows) < 1:
                            continue
                        tables_out.append({
                            "page": page_num,
                            "index": idx,
                            "confidence": 0.75,
                            "method": "fitz_tables",
                            "headers": rows[0] if rows else [],
                            "rows": rows[1:] if len(rows) > 1 else rows,
                        })
                        idx += 1
            return tables_out
        except Exception:
            return None

    @staticmethod
    def _try_pdfplumber(abs_path: str) -> Optional[List[Dict[str, Any]]]:
        try:
            import pdfplumber  # type: ignore
        except ImportError:
            return None

        tables_out: List[Dict[str, Any]] = []
        try:
            with pdfplumber.open(abs_path) as pdf:
                idx = 0
                for page_num, page in enumerate(pdf.pages, start=1):
                    raw_tables = page.extract_tables() or []
                    for tbl in raw_tables:
                        rows = [
                            [DocumentNormalizationService.normalize_text(str(c or "")) for c in row]
                            for row in tbl
                            if row and any(str(c or "").strip() for c in row)
                        ]
                        if len(rows) < 1:
                            continue
                        tables_out.append({
                            "page": page_num,
                            "index": idx,
                            "confidence": 0.7,
                            "method": "pdfplumber",
                            "headers": rows[0] if rows else [],
                            "rows": rows[1:] if len(rows) > 1 else rows,
                        })
                        idx += 1
            return tables_out
        except Exception:
            return None

    @staticmethod
    def _heuristic_from_text(text: str) -> List[Dict[str, Any]]:
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        rows: List[List[str]] = []
        for line in lines:
            if not DocumentTableExtractionService._line_looks_like_row(line):
                continue
            cells = DocumentTableExtractionService._split_line(line)
            if len(cells) >= 2:
                rows.append(cells)

        if not rows:
            return []

        return [{
            "page": 1,
            "index": 0,
            "confidence": 0.45,
            "method": "text_heuristic",
            "headers": [],
            "rows": rows[:200],
        }]

    @staticmethod
    def _line_looks_like_row(line: str) -> bool:
        if PHONE_IN_LINE.search(line):
            return True
        tokens = USEFUL_TOKEN.findall(line)
        return len(tokens) >= 2

    @staticmethod
    def _split_line(line: str) -> List[str]:
        parts = LINE_SPLIT.split(line)
        if len(parts) < 2:
            parts = re.split(r"\s{2,}", line)
        if len(parts) < 2:
            parts = line.split()
        return [DocumentNormalizationService.normalize_text(p) for p in parts if p.strip()]
