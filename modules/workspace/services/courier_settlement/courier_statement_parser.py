from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from modules.workspace.services.document_intelligence.document_normalization_service import (
    DocumentNormalizationService,
)

HEADER_ORDER = re.compile(
    r"رقم\s*الطلب|رقم\s*الفاتورة|الطلب|order|invoice|tracking|awb|#",
    re.IGNORECASE,
)
HEADER_CUSTOMER = re.compile(r"العميل|الزبون|الاسم|customer|name", re.IGNORECASE)
HEADER_PHONE = re.compile(r"الهاتف|الموبايل|phone|mobile", re.IGNORECASE)
HEADER_COLLECTED = re.compile(
    r"المبلغ\s*المحصل|المحصل|قيمة\s*الطلب|collected|cod|amount|total|المبلغ",
    re.IGNORECASE,
)
HEADER_FEE = re.compile(
    r"اجور\s*التوصيل|أجور\s*التوصيل|التوصيل|كلفة\s*التوصيل|delivery|shipping\s*fee|fee",
    re.IGNORECASE,
)
HEADER_NET = re.compile(r"الصافي|net", re.IGNORECASE)
HEADER_DATE = re.compile(r"التاريخ|date", re.IGNORECASE)
HEADER_ROW = re.compile(
    r"^#?\s*$|رقم\s*الطلب|العميل|المبلغ|الإجمالي|total|order|customer|المجموع|كشف",
    re.IGNORECASE,
)


class CourierStatementParser:
    @staticmethod
    def parse(extraction_result) -> Dict[str, Any]:
        tables = extraction_result.get_tables() if extraction_result else []
        text = (extraction_result.extracted_text or extraction_result.text_sample or "") if extraction_result else ""
        warnings: List[str] = []
        rows: List[Dict[str, Any]] = []

        if tables:
            for tbl in tables:
                parsed, w = CourierStatementParser._parse_table(tbl)
                rows.extend(parsed)
                warnings.extend(w)
        if not rows and text:
            parsed, w = CourierStatementParser._parse_text_lines(text)
            rows.extend(parsed)
            warnings.extend(w)

        return {"rows": rows, "warnings": warnings}

    @staticmethod
    def _parse_table(table: Dict[str, Any]) -> Tuple[List[Dict], List[str]]:
        warnings: List[str] = []
        raw_rows = list(table.get("rows") or [])
        headers = list(table.get("headers") or [])
        page = table.get("page")
        tidx = table.get("index", 0)

        if headers:
            col_map = CourierStatementParser._map_columns(headers, raw_rows)
        elif raw_rows and CourierStatementParser._looks_like_header(raw_rows[0]):
            col_map = CourierStatementParser._map_columns(raw_rows[0], raw_rows)
        else:
            col_map = CourierStatementParser._infer_columns_from_data(raw_rows) if raw_rows else {}

        out: List[Dict] = []
        start = 1 if headers else 0
        for i, raw in enumerate(raw_rows):
            if not raw or not any(str(c or "").strip() for c in raw):
                continue
            line = " ".join(str(c) for c in raw)
            if HEADER_ROW.search(line) and CourierStatementParser._looks_like_header(raw):
                continue
            row = CourierStatementParser._build_row(
                raw, col_map, row_index=len(out) + 1, page=page, tidx=tidx
            )
            if row:
                out.append(row)
            elif raw:
                warnings.append(f"صف غير واضح في الجدول {tidx}: {line[:60]}")
        return out, warnings

    @staticmethod
    def _looks_like_header(cells: List) -> bool:
        joined = " ".join(str(c) for c in cells).lower()
        hits = sum(
            1
            for pat in (HEADER_ORDER, HEADER_CUSTOMER, HEADER_COLLECTED, HEADER_FEE)
            if pat.search(joined)
        )
        return hits >= 2

    @staticmethod
    def _map_columns(headers: List, sample_rows: List) -> Dict[str, int]:
        col_map: Dict[str, int] = {}
        header_row = list(headers or [])
        if not header_row:
            return {}
        for idx, cell in enumerate(header_row):
            text = DocumentNormalizationService.normalize_text(str(cell or ""))
            if HEADER_ORDER.search(text):
                col_map.setdefault("order", idx)
            elif HEADER_CUSTOMER.search(text):
                col_map.setdefault("customer", idx)
            elif HEADER_PHONE.search(text):
                col_map.setdefault("phone", idx)
            elif HEADER_COLLECTED.search(text):
                col_map.setdefault("collected", idx)
            elif HEADER_FEE.search(text):
                col_map.setdefault("fee", idx)
            elif HEADER_NET.search(text):
                col_map.setdefault("net", idx)
            elif HEADER_DATE.search(text):
                col_map.setdefault("date", idx)
        return col_map

    @staticmethod
    def _looks_like_order_cell(text: str) -> bool:
        if "#" in text or re.search(r"\bORD[\s\-]?", text, re.IGNORECASE):
            return True
        if re.search(r"[,،]", text) or text.count(".") >= 2:
            return False
        order = DocumentNormalizationService.normalize_order_number(text)
        if order.get("kind") not in ("numeric", "prefixed"):
            return False
        norm = order.get("normalized") or ""
        digits_only = re.sub(r"\D", "", text)
        return digits_only == norm and len(norm) <= 8

    @staticmethod
    def _looks_like_amount_cell(text: str) -> bool:
        if re.search(r"[,،]", text) or text.count(".") >= 2:
            return True
        if re.search(r"د\.?ع|iqd", text, re.IGNORECASE):
            return True
        parsed = DocumentNormalizationService.parse_iqd_amount(text)
        if not parsed.get("valid"):
            return False
        if "#" in text or re.search(r"\bORD[\s\-]?", text, re.IGNORECASE):
            return False
        return (parsed.get("value") or 0) >= 1000

    @staticmethod
    def _infer_columns_from_data(rows: List[List]) -> Dict[str, int]:
        if not rows:
            return {}
        sample = rows[0]
        col_map: Dict[str, int] = {}
        for idx, cell in enumerate(sample):
            text = str(cell or "").strip()
            if CourierStatementParser._looks_like_order_cell(text):
                col_map.setdefault("order", idx)
                continue
            if CourierStatementParser._looks_like_amount_cell(text):
                if "collected" not in col_map:
                    col_map["collected"] = idx
                elif "fee" not in col_map:
                    col_map["fee"] = idx
                elif "net" not in col_map:
                    col_map["net"] = idx
                continue
            if re.search(r"[\u0600-\u06FFa-zA-Z]{2,}", text):
                col_map.setdefault("customer", idx)
        return col_map

    @staticmethod
    def _build_row(
        raw: List,
        col_map: Dict[str, int],
        row_index: int,
        page: Optional[int],
        tidx: int,
    ) -> Optional[Dict[str, Any]]:
        cells = [DocumentNormalizationService.normalize_text(str(c or "")) for c in raw]
        warnings: List[str] = []

        def cell(key: str) -> str:
            idx = col_map.get(key)
            if idx is not None and idx < len(cells):
                return cells[idx]
            return ""

        raw_order = cell("order") or (cells[0] if cells else "")
        if not raw_order and len(cells) > 0 and cells[0].startswith("#"):
            raw_order = cells[0]

        order_info = DocumentNormalizationService.normalize_order_number(raw_order)
        norm_order = order_info.get("normalized") or ""

        customer = cell("customer")
        if not customer and len(cells) > 1 and not DocumentNormalizationService.parse_iqd_amount(cells[1]).get("valid"):
            for c in cells[1:]:
                if re.search(r"[\u0600-\u06FF]{2,}", c) and not DocumentNormalizationService.parse_iqd_amount(c).get("valid"):
                    customer = c
                    break

        phone_cell = cell("phone")
        phone_info = DocumentNormalizationService.normalize_phone(phone_cell) if phone_cell else {"valid": False}

        collected = CourierStatementParser._parse_amount(cell("collected"))
        fee = CourierStatementParser._parse_amount(cell("fee"))
        net = CourierStatementParser._parse_amount(cell("net"))

        if collected is None:
            for c in cells:
                if CourierStatementParser._looks_like_order_cell(c):
                    continue
                amt = CourierStatementParser._parse_amount(c)
                if amt is not None:
                    if collected is None:
                        collected = amt
                    elif fee is None:
                        fee = amt
                    elif net is None:
                        net = amt

        if fee is None and collected is not None and net is not None and net <= collected:
            fee = collected - net

        if net is None and collected is not None and fee is not None:
            net = collected - fee

        if not norm_order and not phone_info.get("valid") and collected is None:
            return None

        if not norm_order and (phone_info.get("valid") or customer):
            warnings.append("رقم الطلب مفقود — يحتاج مراجعة")

        date_raw = cell("date")
        date_info = DocumentNormalizationService.normalize_date(date_raw) if date_raw else {"valid": False}

        confidence = 0.78 if norm_order and collected is not None else 0.45

        return {
            "row_index": row_index,
            "source_table_index": tidx,
            "source_page": page,
            "raw_row": list(raw),
            "raw_order_number": raw_order or None,
            "normalized_order_number": norm_order or None,
            "customer_name": customer or None,
            "customer_phone": phone_info.get("local") if phone_info.get("valid") else None,
            "collected_amount": collected,
            "delivery_fee": fee,
            "net_amount": net,
            "statement_date": date_info.get("iso") if date_info.get("valid") else None,
            "confidence": confidence,
            "warnings": warnings,
        }

    @staticmethod
    def _parse_amount(value: str) -> Optional[int]:
        if not value:
            return None
        parsed = DocumentNormalizationService.parse_iqd_amount(value)
        if parsed.get("valid"):
            return int(parsed["value"])
        return None

    @staticmethod
    def _parse_text_lines(text: str) -> Tuple[List[Dict], List[str]]:
        warnings: List[str] = []
        out: List[Dict] = []
        for line in text.splitlines():
            line = line.strip()
            if not line or HEADER_ROW.search(line):
                continue
            parts = re.split(r"\s{2,}|\t|،|,|\|", line)
            parts = [p.strip() for p in parts if p.strip()]
            if len(parts) < 2:
                continue
            row = CourierStatementParser._build_row(
                parts, CourierStatementParser._infer_columns_from_data([parts]),
                row_index=len(out) + 1, page=1, tidx=0,
            )
            if row:
                out.append(row)
        if not out:
            warnings.append("لم تُستخرج صفوف من النص")
        return out, warnings
