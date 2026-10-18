from __future__ import annotations

import json
import re
import uuid
from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from difflib import SequenceMatcher
from typing import Any, Dict, Iterable, List, Optional, Tuple

from extensions import db
from models.product import Product
from models.purchase import Purchase
from models.supplier import Supplier
from modules.workspace.models.document_extraction_result import DocumentExtractionResult
from modules.workspace.models.workspace_session import WorkspaceSession
from modules.workspace.services import event_bus
from modules.workspace.services.window_orchestrator import WindowOrchestrator


class PurchaseInvoiceError(Exception):
    pass


class PurchaseInvoiceService:
    """Match an extracted purchase invoice and post it only after approval."""

    MATCH_THRESHOLD = 0.90
    REVIEW_THRESHOLD = 0.72
    SUPPLIER_MATCH_THRESHOLD = 0.88
    USD_TO_IQD_RATE = 1350

    HEADER_ALIASES = {
        "product_name": {"product_name", "product", "item", "name", "اسم المنتج", "الصنف", "المادة"},
        "sku": {"sku", "code", "model", "رمز", "كود", "موديل"},
        "barcode": {"barcode", "باركود"},
        "quantity": {"quantity", "qty", "الكمية", "عدد"},
        "unit_price": {"unit_price", "price", "unit cost", "سعر", "سعر الوحدة", "سعر الشراء"},
        "line_total": {"line_total", "total", "amount", "الإجمالي", "المجموع"},
    }

    @staticmethod
    def _normalize(value: Any) -> str:
        text = str(value or "").strip().lower().replace("ـ", "")
        text = re.sub(r"[\u064b-\u065f\u0670]", "", text)
        text = text.translate(str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا", "ى": "ي", "ة": "ه"}))
        text = re.sub(r"[^0-9a-z\u0600-\u06ff]+", " ", text)
        return " ".join(text.split())

    @staticmethod
    def _digits(value: Any) -> str:
        return str(value or "").translate(str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789"))

    @staticmethod
    def _number(value: Any, default: int = 0) -> int:
        if value is None or value == "":
            return default
        raw = PurchaseInvoiceService._digits(value).replace(",", "").replace("٬", "").strip()
        raw = re.sub(r"[^0-9.\-]", "", raw)
        try:
            return int(round(float(raw)))
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _usd_to_iqd(value: Any) -> int:
        """Convert a manually entered USD unit price to IQD at the fixed shop rate."""
        raw = PurchaseInvoiceService._digits(value).replace(",", "").replace("٬", "").strip()
        raw = re.sub(r"[^0-9.\-]", "", raw)
        try:
            dollars = Decimal(raw)
        except (InvalidOperation, TypeError, ValueError):
            return 0
        if dollars <= 0:
            return 0
        return int(
            (dollars * Decimal(PurchaseInvoiceService.USD_TO_IQD_RATE)).quantize(
                Decimal("1"), rounding=ROUND_HALF_UP
            )
        )

    @staticmethod
    def _header_key(value: Any) -> Optional[str]:
        normalized = PurchaseInvoiceService._normalize(value)
        for key, aliases in PurchaseInvoiceService.HEADER_ALIASES.items():
            if normalized in {PurchaseInvoiceService._normalize(alias) for alias in aliases}:
                return key
        return None

    @staticmethod
    def _latest_extraction(session: WorkspaceSession, document_id: Optional[str] = None):
        meta = session.get_metadata() or {}
        document_id = document_id or meta.get("active_document_id")
        query = DocumentExtractionResult.query.filter_by(session_id=session.id)
        if document_id:
            query = query.filter_by(document_id=document_id)
        extraction = query.order_by(DocumentExtractionResult.updated_at.desc()).first()
        if not extraction or extraction.status != "completed":
            raise PurchaseInvoiceError("يجب إكمال قراءة فاتورة الشراء أولاً.")
        return extraction

    @staticmethod
    def _structured_table(tables: Iterable[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        tables = list(tables or [])
        for table in tables:
            if table.get("method") == "openai_purchase_vision_structured":
                return table
        return tables[0] if tables else None

    @staticmethod
    def _parse_table(table: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        headers = list(table.get("headers") or [])
        mapped = [PurchaseInvoiceService._header_key(item) for item in headers]
        row_meta = list(table.get("row_metadata") or [])
        rows: List[Dict[str, Any]] = []
        for index, values in enumerate(table.get("rows") or []):
            if isinstance(values, dict):
                source = values
            else:
                source = {
                    key: values[column]
                    for column, key in enumerate(mapped)
                    if key and column < len(values)
                }
            metadata = row_meta[index] if index < len(row_meta) else {}
            name = str(source.get("product_name") or "").strip()
            quantity = PurchaseInvoiceService._number(source.get("quantity"))
            unit_price = PurchaseInvoiceService._number(source.get("unit_price"))
            line_total = PurchaseInvoiceService._number(source.get("line_total")) or quantity * unit_price
            if not any((name, quantity, unit_price, line_total)):
                continue
            rows.append({
                "row_index": len(rows) + 1,
                "source_page": metadata.get("source_page") or table.get("page"),
                "product_name": name,
                "sku": str(source.get("sku") or "").strip() or None,
                "barcode": str(source.get("barcode") or "").strip() or None,
                "quantity": quantity,
                "unit_price": unit_price,
                "line_total": line_total,
                "confidence": float(metadata.get("confidence") or table.get("confidence") or 0),
                "warnings": list(metadata.get("warnings") or []),
            })
        totals = dict(table.get("purchase_totals") or {})
        return rows, {
            "supplier_name": str(table.get("supplier_name") or "").strip() or None,
            "supplier_phone": str(table.get("supplier_phone") or "").strip() or None,
            "supplier_invoice_no": str(table.get("supplier_invoice_no") or "").strip() or None,
            "invoice_date": str(table.get("invoice_date") or "").strip() or None,
            "currency": str(table.get("currency") or "IQD").strip() or "IQD",
            "discount_value": PurchaseInvoiceService._number(totals.get("discount_value")),
            "shipping_extra": PurchaseInvoiceService._number(totals.get("shipping_extra")),
            "grand_total": PurchaseInvoiceService._number(totals.get("grand_total")),
        }

    @staticmethod
    def _product_candidates(row: Dict[str, Any], products: List[Product]) -> List[Dict[str, Any]]:
        barcode = PurchaseInvoiceService._normalize(row.get("barcode"))
        sku = PurchaseInvoiceService._normalize(row.get("sku"))
        name = PurchaseInvoiceService._normalize(row.get("product_name"))
        candidates = []
        for product in products:
            score = 0.0
            reason = "name"
            if barcode and barcode == PurchaseInvoiceService._normalize(product.barcode):
                score, reason = 1.0, "barcode"
            elif sku and sku == PurchaseInvoiceService._normalize(product.sku):
                score, reason = 0.99, "sku"
            else:
                product_name = PurchaseInvoiceService._normalize(product.name)
                if name and name == product_name:
                    score, reason = 0.97, "exact_name"
                elif name and product_name:
                    score = SequenceMatcher(None, name, product_name).ratio()
            if score > 0:
                candidates.append({
                    "id": int(product.id),
                    "name": product.name,
                    "sku": product.sku,
                    "barcode": product.barcode,
                    "buy_price": int(product.buy_price or 0),
                    "score": round(score, 4),
                    "reason": reason,
                })
        return sorted(candidates, key=lambda item: item["score"], reverse=True)[:5]

    @staticmethod
    def _match_supplier(name: Optional[str], phone: Optional[str]) -> Dict[str, Any]:
        suppliers = Supplier.query.order_by(Supplier.name.asc()).all()
        norm_name = PurchaseInvoiceService._normalize(name)
        norm_phone = re.sub(r"\D", "", PurchaseInvoiceService._digits(phone))
        candidates = []
        for supplier in suppliers:
            supplier_phone = re.sub(r"\D", "", PurchaseInvoiceService._digits(supplier.phone))
            score = 0.0
            reason = "name"
            if norm_phone and supplier_phone and norm_phone == supplier_phone:
                score, reason = 1.0, "phone"
            elif norm_name:
                other = PurchaseInvoiceService._normalize(supplier.name)
                score = 0.98 if other == norm_name else SequenceMatcher(None, norm_name, other).ratio()
            if score > 0:
                candidates.append({"id": int(supplier.id), "name": supplier.name, "phone": supplier.phone, "score": round(score, 4), "reason": reason})
        candidates.sort(key=lambda item: item["score"], reverse=True)
        best = candidates[0] if candidates else None
        matched = bool(best and best["score"] >= PurchaseInvoiceService.SUPPLIER_MATCH_THRESHOLD)
        return {
            "source_name": name,
            "source_phone": phone,
            "status": "matched" if matched else "new_supplier",
            "decision": "use_existing" if matched else "create_new",
            "matched": best if matched else None,
            "suggestion": best if not matched else None,
            "candidates": candidates[:5],
        }

    @staticmethod
    def _summarize(analysis: Dict[str, Any]) -> Dict[str, Any]:
        rows = list(analysis.get("rows") or [])
        active = [row for row in rows if row.get("decision") != "exclude"]
        blocking = list(analysis.get("validation", {}).get("invoice_blocking") or [])
        for row in active:
            blocking.extend(
                f"السطر {row.get('row_index')}: {message}"
                for message in (row.get("validation") or [])
            )
        review = [row for row in active if row.get("decision") == "review"]
        if review:
            blocking.append(f"توجد {len(review)} أصناف تحتاج قرار مطابقة.")
        supplier = analysis.get("supplier") or {}
        if not supplier.get("source_name") and supplier.get("decision") == "create_new":
            blocking.append("اسم المورد غير مقروء؛ لا يمكن إنشاء مورد بلا اسم.")
        currency = str(analysis.get("invoice", {}).get("currency") or "IQD").strip().upper()
        if currency not in {"IQD", "د.ع", "د ع", "دينار", "IRAQI DINAR"}:
            blocking.append(f"عملة الفاتورة ({currency}) تحتاج سعر صرف ومراجعة محاسبية قبل الإدخال.")
        if not active:
            blocking.append("لا توجد أصناف قابلة للإدخال.")
        subtotal = sum(int(row.get("line_total") or 0) for row in active)
        discount = int(analysis.get("invoice", {}).get("discount_value") or 0)
        shipping = int(analysis.get("invoice", {}).get("shipping_extra") or 0)
        calculated = max(subtotal - discount + shipping, 0)
        declared = int(analysis.get("invoice", {}).get("declared_grand_total") or 0)
        if declared and declared != calculated:
            blocking.append(f"الإجمالي المطبوع ({declared:,}) لا يساوي الإجمالي المحسوب ({calculated:,}).")
        summary = {
            "total_rows": len(rows),
            "active_rows": len(active),
            "matched_rows": sum(row.get("decision") == "use_existing" for row in active),
            "new_product_rows": sum(row.get("decision") == "create_new" for row in active),
            "review_rows": len(review),
            "excluded_rows": len(rows) - len(active),
            "total_units": sum(int(row.get("quantity") or 0) for row in active),
            "sub_total": subtotal,
            "discount_value": discount,
            "shipping_extra": shipping,
            "grand_total": calculated,
            "blocking": list(dict.fromkeys(blocking)),
            "ready": not blocking and bool(active),
        }
        analysis["summary"] = summary
        return summary

    @staticmethod
    def analyze(session: WorkspaceSession, document_id: Optional[str] = None, user_id: Optional[int] = None) -> Dict[str, Any]:
        extraction = PurchaseInvoiceService._latest_extraction(session, document_id)
        table = PurchaseInvoiceService._structured_table(extraction.get_tables())
        if not table:
            raise PurchaseInvoiceError("لم يتم العثور على جدول أصناف واضح في فاتورة الشراء.")
        raw_rows, invoice = PurchaseInvoiceService._parse_table(table)
        if not raw_rows:
            raise PurchaseInvoiceError("لم يتم استخراج أصناف قابلة للمراجعة من الفاتورة.")

        products = Product.query.filter_by(active=True).order_by(Product.name.asc()).all()
        rows = []
        for raw in raw_rows:
            row_blocking = []
            if not raw["product_name"]:
                row_blocking.append("اسم المنتج غير مقروء")
            if raw["quantity"] <= 0:
                row_blocking.append("الكمية غير صحيحة")
            if raw["unit_price"] <= 0:
                row_blocking.append("سعر الشراء غير صحيح")
            expected = raw["quantity"] * raw["unit_price"]
            if raw["line_total"] != expected:
                row_blocking.append("إجمالي السطر لا يساوي الكمية × السعر")
            candidates = PurchaseInvoiceService._product_candidates(raw, products)
            best = candidates[0] if candidates else None
            score = float(best.get("score") or 0) if best else 0.0
            if score >= PurchaseInvoiceService.MATCH_THRESHOLD:
                status, decision, matched = "matched", "use_existing", best
            elif score >= PurchaseInvoiceService.REVIEW_THRESHOLD:
                status, decision, matched = "review", "review", None
            else:
                status, decision, matched = "new_product", "create_new", None
            if row_blocking:
                status, decision = "invalid", "review"
            rows.append({**raw, "status": status, "decision": decision, "matched_product": matched, "suggestion": best if not matched else None, "candidates": candidates, "match_score": score, "validation": row_blocking})

        analysis = {
            "id": str(uuid.uuid4()),
            "session_id": session.id,
            "document_id": extraction.document_id,
            "extraction_id": extraction.id,
            "status": "review",
            "created_at": datetime.utcnow().isoformat(),
            "supplier": PurchaseInvoiceService._match_supplier(invoice.get("supplier_name"), invoice.get("supplier_phone")),
            "invoice": {
                "supplier_invoice_no": invoice.get("supplier_invoice_no"),
                "invoice_date": invoice.get("invoice_date"),
                "currency": invoice.get("currency") or "IQD",
                "discount_value": invoice.get("discount_value") or 0,
                "shipping_extra": invoice.get("shipping_extra") or 0,
                "declared_grand_total": invoice.get("grand_total") or 0,
            },
            "rows": rows,
            "validation": {"invoice_blocking": [], "warnings": []},
            "posting": {"status": "not_posted"},
        }
        PurchaseInvoiceService._summarize(analysis)
        PurchaseInvoiceService._save(session, analysis)
        PurchaseInvoiceService._open_analysis_window(session, analysis)
        db.session.commit()
        event_bus.emit_event(session.id, "purchase.analysis.completed", {"analysis": analysis}, message="اكتملت مطابقة فاتورة الشراء مع الموردين والمنتجات", user_id=user_id)
        event_bus.emit_event(session.id, "window.updated", {"windows": session.get_windows()}, user_id=user_id)
        return analysis

    @staticmethod
    def _save(session: WorkspaceSession, analysis: Dict[str, Any]) -> None:
        meta = session.get_metadata() or {}
        meta["purchase_invoice_analysis"] = analysis
        session.set_metadata(meta)

    @staticmethod
    def get(session: WorkspaceSession, analysis_id: Optional[str] = None) -> Dict[str, Any]:
        analysis = (session.get_metadata() or {}).get("purchase_invoice_analysis") or {}
        if not analysis or (analysis_id and analysis.get("id") != analysis_id):
            raise PurchaseInvoiceError("تحليل فاتورة الشراء غير موجود.")
        return analysis

    @staticmethod
    def catalog(query: str = "", limit: int = 120) -> Dict[str, Any]:
        """Return a compact correction catalog for the purchase review UI."""
        safe_limit = max(10, min(int(limit or 120), 300))
        text = str(query or "").strip()
        product_query = Product.query.filter_by(active=True)
        supplier_query = Supplier.query
        if text:
            like = f"%{text}%"
            product_query = product_query.filter(
                db.or_(Product.name.ilike(like), Product.sku.ilike(like), Product.barcode.ilike(like))
            )
            supplier_query = supplier_query.filter(
                db.or_(Supplier.name.ilike(like), Supplier.phone.ilike(like))
            )
        products = product_query.order_by(Product.name.asc()).limit(safe_limit).all()
        suppliers = supplier_query.order_by(Supplier.name.asc()).limit(safe_limit).all()
        return {
            "products": [{
                "id": int(item.id),
                "name": item.name,
                "sku": item.sku,
                "barcode": item.barcode,
                "buy_price": int(item.buy_price or 0),
                "sale_price": int(item.sale_price or 0),
                "quantity": int(item.quantity or 0),
            } for item in products],
            "suppliers": [{
                "id": int(item.id),
                "name": item.name,
                "phone": item.phone,
            } for item in suppliers],
        }

    @staticmethod
    def set_supplier(
        session: WorkspaceSession,
        analysis_id: str,
        *,
        supplier_id: Optional[int] = None,
        supplier_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        analysis = PurchaseInvoiceService.get(session, analysis_id)
        if analysis.get("posting", {}).get("status") == "posted":
            raise PurchaseInvoiceError("تم تنفيذ هذه الفاتورة مسبقاً.")
        current = dict(analysis.get("supplier") or {})
        current.setdefault("original_source_name", current.get("source_name"))
        if supplier_id:
            supplier = Supplier.query.get(int(supplier_id))
            if not supplier:
                raise PurchaseInvoiceError("المورد المختار غير موجود.")
            current.update({
                "source_name": supplier.name,
                "source_phone": supplier.phone,
                "status": "matched",
                "decision": "use_existing",
                "matched": {
                    "id": int(supplier.id),
                    "name": supplier.name,
                    "phone": supplier.phone,
                    "score": 1.0,
                    "reason": "manual",
                },
                "suggestion": None,
            })
        else:
            clean_name = str(supplier_name or "").strip()
            if not clean_name:
                raise PurchaseInvoiceError("اكتب اسم المورد الجديد.")
            current.update({
                "source_name": clean_name[:150],
                "status": "new_supplier",
                "decision": "create_new",
                "matched": None,
                "suggestion": None,
            })
        analysis["supplier"] = current
        PurchaseInvoiceService._summarize(analysis)
        PurchaseInvoiceService._save(session, analysis)
        PurchaseInvoiceService._open_analysis_window(session, analysis)
        db.session.commit()
        event_bus.emit_event(session.id, "purchase.analysis.updated", {"analysis": analysis})
        event_bus.emit_event(session.id, "window.updated", {"windows": session.get_windows()})
        return analysis

    @staticmethod
    def _open_analysis_window(session: WorkspaceSession, analysis: Dict[str, Any]) -> None:
        WindowOrchestrator.ensure_window(session, {
            "id": f"win_purchase_{analysis['id'][:8]}",
            "type": "purchase_invoice_analysis",
            "title": "مطابقة فاتورة الشراء",
            "status": "ready" if analysis.get("summary", {}).get("ready") else "review",
            "placement": "left",
            "props": {"analysisId": analysis["id"], "analysis": analysis},
            "interactive": True,
        }, "purchase_analysis")

    @staticmethod
    def set_row_decision(session: WorkspaceSession, analysis_id: str, row_index: int, decision: str, product_id: Optional[int] = None) -> Dict[str, Any]:
        analysis = PurchaseInvoiceService.get(session, analysis_id)
        if analysis.get("posting", {}).get("status") == "posted":
            raise PurchaseInvoiceError("تم تنفيذ هذه الفاتورة مسبقاً.")
        row = next((item for item in analysis.get("rows") or [] if int(item.get("row_index") or 0) == int(row_index)), None)
        if not row:
            raise PurchaseInvoiceError("السطر المطلوب غير موجود.")
        if decision == "use_existing":
            product = Product.query.get(int(product_id or 0))
            if not product:
                raise PurchaseInvoiceError("المنتج المختار غير موجود.")
            row["decision"], row["status"] = "use_existing", "matched"
            row["matched_product"] = {"id": product.id, "name": product.name, "sku": product.sku, "barcode": product.barcode, "buy_price": int(product.buy_price or 0), "score": 1.0, "reason": "manual"}
        elif decision == "create_new":
            row["decision"], row["status"], row["matched_product"] = "create_new", "new_product", None
        elif decision == "exclude":
            row["decision"], row["status"], row["matched_product"] = "exclude", "excluded", None
        else:
            raise PurchaseInvoiceError("قرار السطر غير مدعوم.")
        PurchaseInvoiceService._summarize(analysis)
        PurchaseInvoiceService._save(session, analysis)
        PurchaseInvoiceService._open_analysis_window(session, analysis)
        db.session.commit()
        event_bus.emit_event(session.id, "purchase.analysis.updated", {"analysis": analysis})
        event_bus.emit_event(session.id, "window.updated", {"windows": session.get_windows()})
        return analysis

    @staticmethod
    def update_row_values(
        session: WorkspaceSession,
        analysis_id: str,
        row_index: int,
        quantity: Any,
        unit_price: Any,
        product_name: Optional[str] = None,
        unit_price_usd: Any = None,
    ) -> Dict[str, Any]:
        analysis = PurchaseInvoiceService.get(session, analysis_id)
        if analysis.get("posting", {}).get("status") == "posted":
            raise PurchaseInvoiceError("تم تنفيذ هذه الفاتورة مسبقاً.")
        row = next(
            (item for item in analysis.get("rows") or [] if int(item.get("row_index") or 0) == int(row_index)),
            None,
        )
        if not row:
            raise PurchaseInvoiceError("السطر المطلوب غير موجود.")
        parsed_quantity = PurchaseInvoiceService._number(quantity)
        has_usd_price = unit_price_usd is not None and str(unit_price_usd).strip() != ""
        parsed_price = (
            PurchaseInvoiceService._usd_to_iqd(unit_price_usd)
            if has_usd_price
            else PurchaseInvoiceService._number(unit_price)
        )
        if parsed_quantity <= 0 or parsed_price <= 0:
            raise PurchaseInvoiceError("الكمية وسعر الشراء يجب أن يكونا أكبر من صفر.")
        if product_name is not None:
            clean_name = str(product_name or "").strip()
            if not clean_name:
                raise PurchaseInvoiceError("اسم المنتج مطلوب.")
            row["product_name"] = clean_name[:150]
        row["quantity"] = parsed_quantity
        row["unit_price"] = parsed_price
        row["line_total"] = parsed_quantity * parsed_price
        if has_usd_price:
            row["unit_price_usd"] = str(unit_price_usd).strip()
            row["price_currency"] = "USD"
            row["exchange_rate"] = PurchaseInvoiceService.USD_TO_IQD_RATE
        else:
            row.pop("unit_price_usd", None)
            row.pop("exchange_rate", None)
            row["price_currency"] = "IQD"
        row["validation"] = []
        if row.get("decision") == "review" and row.get("suggestion"):
            row["status"] = "review"
        elif row.get("decision") == "create_new":
            row["status"] = "new_product"
        elif row.get("decision") == "use_existing":
            row["status"] = "matched"
        PurchaseInvoiceService._summarize(analysis)
        PurchaseInvoiceService._save(session, analysis)
        PurchaseInvoiceService._open_analysis_window(session, analysis)
        db.session.commit()
        event_bus.emit_event(session.id, "purchase.analysis.updated", {"analysis": analysis})
        event_bus.emit_event(session.id, "window.updated", {"windows": session.get_windows()})
        return analysis

    @staticmethod
    def build_preview(session: WorkspaceSession, analysis_id: str) -> Dict[str, Any]:
        analysis = PurchaseInvoiceService.get(session, analysis_id)
        summary = PurchaseInvoiceService._summarize(analysis)
        return {
            "kind": "purchase",
            "analysis_id": analysis_id,
            "supplier": analysis.get("supplier"),
            "matched_products": summary["matched_rows"],
            "new_products": summary["new_product_rows"],
            "excluded_products": summary["excluded_rows"],
            "total_rows": summary["active_rows"],
            "total_units": summary["total_units"],
            "grand_total": summary["grand_total"],
            "blocking": summary["blocking"],
            "ready": summary["ready"],
            "status": analysis.get("posting", {}).get("status") or "not_posted",
        }

    @staticmethod
    def request_approval(session: WorkspaceSession, analysis_id: str, user_id: Optional[int] = None) -> Dict[str, Any]:
        preview = PurchaseInvoiceService.build_preview(session, analysis_id)
        if not preview["ready"]:
            raise PurchaseInvoiceError("أكمل قرارات المطابقة وصحح القيم المتعارضة قبل التنفيذ.")
        if preview["status"] == "posted":
            raise PurchaseInvoiceError("تم تنفيذ فاتورة الشراء مسبقاً.")
        supplier = preview.get("supplier") or {}
        supplier_label = (supplier.get("matched") or {}).get("name") or supplier.get("source_name") or "مورد جديد"
        WindowOrchestrator.ensure_window(session, {
            "id": f"win_approval_purchase_{analysis_id[:8]}",
            "type": "approval_panel",
            "title": "موافقة إدخال فاتورة الشراء",
            "status": "waiting",
            "placement": "center",
            "props": {
                "action": "purchase_posting",
                "analysisId": analysis_id,
                "step_id": "purchase_posting_approval",
                "message": f"اعتماد فاتورة المورد {supplier_label} وإضافة {preview['total_units']} قطعة إلى المخزون؟",
                "hint": "سيتم إنشاء المورد أو المنتجات الجديدة الموضحة فقط، ثم تسجيل شراء آجل وإضافة الكميات للمخزون مرة واحدة.",
                "acceptText": "اعتماد وإضافة للمخزون",
                "rejectText": "إلغاء",
                "preview": preview,
            },
            "interactive": True,
        }, "purchase_posting_approval")
        db.session.commit()
        event_bus.emit_event(session.id, "purchase.posting.approval_required", {"analysisId": analysis_id, "preview": preview}, message="موافقة مطلوبة لإدخال فاتورة الشراء", user_id=user_id)
        event_bus.emit_event(session.id, "window.updated", {"windows": session.get_windows()}, user_id=user_id)
        return preview

    @staticmethod
    def cancel_approval(session: WorkspaceSession, analysis_id: str, user_id: Optional[int] = None) -> None:
        PurchaseInvoiceService.get(session, analysis_id)
        WindowOrchestrator.close_window_types(session, ["approval_panel"])
        db.session.commit()
        event_bus.emit_event(session.id, "purchase.posting.cancelled", {"analysisId": analysis_id}, message="تم إلغاء تنفيذ فاتورة الشراء", user_id=user_id)
        event_bus.emit_event(session.id, "window.updated", {"windows": session.get_windows()}, user_id=user_id)

    @staticmethod
    def _purchase_date(value: Optional[str]) -> str:
        if value:
            try:
                return datetime.fromisoformat(str(value).replace("Z", "+00:00")).date().isoformat()
            except ValueError:
                pass
        return date.today().isoformat()

    @staticmethod
    def execute_approved(session: WorkspaceSession, analysis_id: str, user_id: Optional[int] = None) -> Dict[str, Any]:
        analysis = PurchaseInvoiceService.get(session, analysis_id)
        preview = PurchaseInvoiceService.build_preview(session, analysis_id)
        if not preview["ready"]:
            raise PurchaseInvoiceError("لا يمكن التنفيذ قبل اكتمال المراجعة.")
        reference_no = f"workspace:{analysis_id}"
        existing = Purchase.query.filter_by(reference_no=reference_no).first()
        if existing:
            analysis["status"] = "posted"
            analysis["posting"] = {
                "status": "posted",
                "purchase_id": int(existing.id),
                "reference_no": reference_no,
                "supplier_id": int(existing.supplier_id),
                "created_products": list((analysis.get("posting") or {}).get("created_products") or []),
                "posted_at": (existing.created_at or datetime.utcnow()).isoformat(),
                "already_posted": True,
            }
            PurchaseInvoiceService._save(session, analysis)
            PurchaseInvoiceService._open_analysis_window(session, analysis)
            WindowOrchestrator.close_window_types(session, ["approval_panel"])
            db.session.commit()
            return analysis["posting"]

        try:
            from routes.purchases import _create_purchase_from_payload, _ensure_purchase_schema

            # Schema guards may commit one-time DDL, so run them before creating
            # the supplier/products that must remain atomic with the purchase.
            _ensure_purchase_schema()
            supplier_info = analysis.get("supplier") or {}
            supplier = None
            if supplier_info.get("decision") == "use_existing":
                supplier = Supplier.query.get(int((supplier_info.get("matched") or {}).get("id") or 0))
            if not supplier:
                name = str(supplier_info.get("source_name") or "").strip()
                if not name:
                    raise PurchaseInvoiceError("اسم المورد مطلوب لإنشاء المورد الجديد.")
                supplier = Supplier(name=name, phone=supplier_info.get("source_phone"), opening_balance=0, total_debt=0, total_paid=0)
                db.session.add(supplier)
                db.session.flush()

            supplier_invoice_no = str(
                (analysis.get("invoice") or {}).get("supplier_invoice_no") or ""
            ).strip()
            if supplier_invoice_no:
                duplicate = Purchase.query.filter_by(
                    supplier_id=int(supplier.id),
                    supplier_invoice_no=supplier_invoice_no,
                ).first()
                if duplicate:
                    raise PurchaseInvoiceError(
                        f"فاتورة المورد رقم {supplier_invoice_no} مسجلة مسبقاً بعملية الشراء #{duplicate.id}."
                    )

            purchase_items = []
            created_products = []
            for row in analysis.get("rows") or []:
                if row.get("decision") == "exclude":
                    continue
                product = None
                if row.get("decision") == "use_existing":
                    product = Product.query.get(int((row.get("matched_product") or {}).get("id") or 0))
                if not product and row.get("decision") == "create_new":
                    product = Product(
                        name=str(row.get("product_name") or "").strip(),
                        sku=row.get("sku"),
                        barcode=row.get("barcode"),
                        buy_price=int(row.get("unit_price") or 0),
                        sale_price=int(row.get("unit_price") or 0),
                        opening_stock=0,
                        quantity=0,
                        active=True,
                        store_visible=False,
                        meta_json=json.dumps({"source": "workspace_purchase_invoice", "analysis_id": analysis_id, "sale_price_needs_review": True}, ensure_ascii=False),
                    )
                    db.session.add(product)
                    db.session.flush()
                    created_products.append({"id": product.id, "name": product.name})
                if not product:
                    raise PurchaseInvoiceError(f"تعذر تحديد منتج السطر {row.get('row_index')}.")
                purchase_items.append({
                    "product_id": int(product.id),
                    "quantity": int(row.get("quantity") or 0),
                    "unit_cost": int(row.get("unit_price") or 0),
                    "line_total": int(row.get("line_total") or 0),
                })

            invoice = analysis.get("invoice") or {}
            purchase, error = _create_purchase_from_payload({
                "supplier_id": supplier.id,
                "items": purchase_items,
                "purchase_date": PurchaseInvoiceService._purchase_date(invoice.get("invoice_date")),
                "discount_value": int(invoice.get("discount_value") or 0),
                "shipping_extra": int(invoice.get("shipping_extra") or 0),
                "purchase_mode": "credit",
                "status": "confirmed",
                "reference_no": reference_no,
                "supplier_invoice_no": invoice.get("supplier_invoice_no"),
                "notes": f"أُنشئت بعد مراجعة وموافقة LEON — تحليل {analysis_id}",
            }, [])
            if error or not purchase:
                raise PurchaseInvoiceError(error or "تعذر إنشاء عملية الشراء.")
            purchase.source_module = "ai_workspace"
            purchase.currency = str(invoice.get("currency") or "IQD")[:10]

            analysis["status"] = "posted"
            analysis["posting"] = {
                "status": "posted",
                "purchase_id": int(purchase.id),
                "reference_no": reference_no,
                "supplier_id": int(supplier.id),
                "created_products": created_products,
                "posted_at": datetime.utcnow().isoformat(),
            }
            PurchaseInvoiceService._save(session, analysis)
            PurchaseInvoiceService._open_analysis_window(session, analysis)
            WindowOrchestrator.close_window_types(session, ["approval_panel"])
            db.session.commit()
            try:
                from utils.activity_logger import log_activity

                log_activity(
                    "create",
                    "purchases",
                    f"فاتورة شراء ذكية {purchase.invoice_no or purchase.id}",
                    entity_type="purchase",
                    entity_id=purchase.id,
                    payload={
                        "source": "ai_workspace",
                        "analysis_id": analysis_id,
                        "supplier_id": supplier.id,
                        "grand_total": int(purchase.grand_total or purchase.total or 0),
                        "created_product_ids": [item["id"] for item in created_products],
                    },
                )
            except Exception:
                pass
            event_bus.emit_event(session.id, "purchase.posting.completed", {"analysisId": analysis_id, "posting": analysis["posting"], "analysis": analysis}, message="تم تسجيل فاتورة الشراء وإضافة الكميات للمخزون", user_id=user_id)
            event_bus.emit_event(session.id, "window.updated", {"windows": session.get_windows()}, user_id=user_id)
            return analysis["posting"]
        except Exception:
            db.session.rollback()
            raise
