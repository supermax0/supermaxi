from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional

from flask import current_app

from modules.workspace.services.document_intelligence.courier_vision_extraction_service import (
    CourierVisionExtractionService,
)
from modules.workspace.services.document_intelligence.document_image_preprocessing_service import (
    DocumentImagePreprocessingService,
)


PURCHASE_INVOICE_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "is_purchase_invoice",
        "supplier_name",
        "supplier_phone",
        "supplier_invoice_no",
        "invoice_date",
        "currency",
        "discount_value",
        "shipping_extra",
        "grand_total",
        "rows",
        "document_warnings",
    ],
    "properties": {
        "is_purchase_invoice": {"type": "boolean"},
        "supplier_name": {"type": ["string", "null"]},
        "supplier_phone": {"type": ["string", "null"]},
        "supplier_invoice_no": {"type": ["string", "null"]},
        "invoice_date": {"type": ["string", "null"]},
        "currency": {"type": ["string", "null"]},
        "discount_value": {"type": ["integer", "null"]},
        "shipping_extra": {"type": ["integer", "null"]},
        "grand_total": {"type": ["integer", "null"]},
        "document_warnings": {"type": "array", "items": {"type": "string"}},
        "rows": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "row_index",
                    "source_page",
                    "product_name",
                    "sku",
                    "barcode",
                    "quantity",
                    "unit_price",
                    "line_total",
                    "confidence",
                    "warnings",
                ],
                "properties": {
                    "row_index": {"type": "integer"},
                    "source_page": {"type": ["integer", "null"]},
                    "product_name": {"type": ["string", "null"]},
                    "sku": {"type": ["string", "null"]},
                    "barcode": {"type": ["string", "null"]},
                    "quantity": {"type": ["integer", "null"]},
                    "unit_price": {"type": ["integer", "null"]},
                    "line_total": {"type": ["integer", "null"]},
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                    "warnings": {"type": "array", "items": {"type": "string"}},
                },
            },
        },
    },
}


class PurchaseInvoiceVisionService:
    """Structured, read-only vision extraction for supplier purchase invoices."""

    @staticmethod
    def is_supported(mime_type: str, filename: str = "") -> bool:
        return CourierVisionExtractionService.is_supported(mime_type, filename)

    @staticmethod
    def should_try(
        mime_type: str,
        filename: str,
        tables: Optional[List[Dict[str, Any]]] = None,
    ) -> bool:
        return CourierVisionExtractionService.should_try(mime_type, filename, tables)

    @staticmethod
    def _enabled() -> bool:
        return CourierVisionExtractionService._enabled()

    @staticmethod
    def extract(
        abs_path: str,
        mime_type: str,
        filename: str = "",
        *,
        additional_files: Optional[List[Dict[str, str]]] = None,
        client=None,
        model: Optional[str] = None,
    ) -> Dict[str, Any]:
        if not PurchaseInvoiceVisionService.is_supported(mime_type, filename):
            return {"status": "not_available", "tables": [], "warnings": []}

        prepared_files: List[Dict[str, Any]] = []
        preprocessing: List[Dict[str, Any]] = []
        try:
            if client is None:
                from modules.ai_sales.openai_service import get_openai_api_key, get_openai_client

                if not get_openai_api_key():
                    return {
                        "status": "not_available",
                        "tables": [],
                        "warnings": ["مفتاح OpenAI غير مضبوط؛ تعذر تشغيل قارئ فاتورة الشراء المتقدم."],
                    }
                client = get_openai_client()

            selected_model = (
                model
                or current_app.config.get("WORKSPACE_DOCUMENT_VISION_MODEL")
                or current_app.config.get("OPENAI_VISION_MODEL")
                or "gpt-5.4"
            )
            content: List[Dict[str, Any]] = [{
                "type": "input_text",
                "text": PurchaseInvoiceVisionService._prompt(),
            }]
            all_files = [
                *(additional_files or []),
                {"abs_path": abs_path, "mime_type": mime_type, "filename": filename},
            ]
            for index, item in enumerate(all_files, start=1):
                prepared = DocumentImagePreprocessingService.prepare_for_analysis(
                    item["abs_path"], item.get("mime_type") or "", item.get("filename") or ""
                )
                prepared_files.append(prepared)
                preprocessing.append(dict(prepared.get("metadata") or {}))
                content.append({
                    "type": "input_text",
                    "text": f"صفحة/ملف فاتورة الشراء رقم {index}: {item.get('filename') or ''}",
                })
                content.append(
                    CourierVisionExtractionService._file_content(
                        prepared["abs_path"],
                        prepared.get("mime_type") or item.get("mime_type") or "",
                        prepared.get("filename") or item.get("filename") or "",
                    )
                )

            kwargs: Dict[str, Any] = {
                "model": selected_model,
                "instructions": (
                    "أنت مدقق فواتير شراء ومخزون. اقرأ القيم المطبوعة فقط، ولا تخمن اسماً أو رقماً غير واضح. "
                    "لا تنشئ مورداً أو منتجاً ولا تنفذ أي حركة؛ المطلوب استخراج منظم للمراجعة."
                ),
                "input": [{"role": "user", "content": content}],
                "text": {
                    "format": {
                        "type": "json_schema",
                        "name": "purchase_invoice",
                        "strict": True,
                        "schema": PURCHASE_INVOICE_SCHEMA,
                    }
                },
                "max_output_tokens": int(
                    current_app.config.get(
                        "WORKSPACE_DOCUMENT_MAX_OUTPUT_TOKENS",
                        os.environ.get("WORKSPACE_DOCUMENT_MAX_OUTPUT_TOKENS", 20000),
                    )
                ),
                "store": False,
                "timeout": int(
                    current_app.config.get(
                        "WORKSPACE_DOCUMENT_AI_TIMEOUT",
                        os.environ.get("WORKSPACE_DOCUMENT_AI_TIMEOUT", 300),
                    )
                ),
            }
            if str(selected_model).startswith("gpt-5"):
                kwargs["reasoning"] = {
                    "effort": str(
                        current_app.config.get(
                            "WORKSPACE_DOCUMENT_REASONING_EFFORT",
                            os.environ.get("WORKSPACE_DOCUMENT_REASONING_EFFORT", "medium"),
                        )
                    )
                }

            response = client.responses.create(**kwargs)
            raw = str(getattr(response, "output_text", "") or "").strip()
            if not raw:
                raise ValueError("لم يرجع نموذج الرؤية نتيجة لفاتورة الشراء")
            result = PurchaseInvoiceVisionService._to_extraction_payload(
                json.loads(raw), selected_model
            )
            result["preprocessing"] = preprocessing
            return result
        except Exception as exc:
            return {
                "status": "failed",
                "tables": [],
                "preprocessing": preprocessing,
                "warnings": [f"تعذر التحليل البصري لفاتورة الشراء: {exc}"],
            }
        finally:
            for prepared in prepared_files:
                DocumentImagePreprocessingService.cleanup(prepared)

    @staticmethod
    def _prompt() -> str:
        return (
            "حلل جميع الصفحات كفاتورة شراء واحدة. استخرج اسم المورد وهاتفه ورقم فاتورته وتاريخها والعملة. "
            "استخرج كل سطر منتج مرة واحدة: الاسم التجاري كما هو، SKU أو الموديل، الباركود، الكمية، "
            "سعر شراء الوحدة النهائي وإجمالي السطر. الأرقام مبالغ صحيحة بلا فواصل. "
            "لا تعتبر تسلسل الصف باركوداً ولا تعتبر خطوط الجدول أرقاماً. إذا كان SKU أو الباركود غير موجود "
            "اجعله null. إذا كانت قيمة غير واضحة اجعلها null وأضف تحذيراً. تحقق أن الكمية × سعر الوحدة يساوي "
            "إجمالي السطر، وأن مجموع السطور ناقص الخصم زائد الشحن يساوي الإجمالي النهائي إن كان مطبوعاً. "
            "إذا لم يكن المستند فاتورة شراء اجعل is_purchase_invoice=false واترك rows فارغة."
        )

    @staticmethod
    def _to_extraction_payload(payload: Dict[str, Any], model: str) -> Dict[str, Any]:
        if not payload.get("is_purchase_invoice"):
            return {
                "status": "not_purchase_invoice",
                "tables": [],
                "warnings": list(payload.get("document_warnings") or []),
                "provider": "openai",
                "model": model,
            }

        headers = ["product_name", "sku", "barcode", "quantity", "unit_price", "line_total"]
        rows_out: List[List[Any]] = []
        row_metadata: List[Dict[str, Any]] = []
        for index, row in enumerate(payload.get("rows") or [], start=1):
            rows_out.append([row.get(key) for key in headers])
            row_metadata.append({
                "row_index": row.get("row_index") or index,
                "source_page": row.get("source_page"),
                "confidence": float(row.get("confidence") or 0),
                "warnings": list(row.get("warnings") or []),
            })

        validation = PurchaseInvoiceVisionService.validate_payload(payload)
        table = {
            "page": 1,
            "index": 0,
            "confidence": round(
                min((item["confidence"] for item in row_metadata), default=0.0), 4
            ),
            "method": "openai_purchase_vision_structured",
            "headers": headers,
            "rows": rows_out,
            "row_metadata": row_metadata,
            "supplier_name": payload.get("supplier_name"),
            "supplier_phone": payload.get("supplier_phone"),
            "supplier_invoice_no": payload.get("supplier_invoice_no"),
            "invoice_date": payload.get("invoice_date"),
            "currency": payload.get("currency") or "IQD",
            "purchase_totals": {
                "discount_value": payload.get("discount_value"),
                "shipping_extra": payload.get("shipping_extra"),
                "grand_total": payload.get("grand_total"),
            },
        }
        text_lines = [
            "فاتورة شراء",
            f"المورد: {payload.get('supplier_name') or ''}",
            f"رقم فاتورة المورد: {payload.get('supplier_invoice_no') or ''}",
        ]
        text_lines.extend(
            " | ".join("" if value is None else str(value) for value in row)
            for row in rows_out
        )
        warnings = list(payload.get("document_warnings") or []) + validation["warnings"]
        return {
            "status": "completed",
            "text": "\n".join(text_lines),
            "text_sample": "\n".join(text_lines)[:500],
            "pages": [{
                "page": 1,
                "text": "\n".join(text_lines),
                "confidence": table["confidence"],
                "method": "openai_purchase_vision_structured",
            }],
            "tables": [table],
            "warnings": warnings,
            "provider": "openai",
            "model": model,
            "validation": validation,
        }

    @staticmethod
    def validate_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
        warnings: List[str] = []
        blocking: List[str] = []
        rows = list(payload.get("rows") or [])
        calculated_subtotal = 0
        for index, row in enumerate(rows, start=1):
            name = str(row.get("product_name") or "").strip()
            quantity = int(row.get("quantity") or 0)
            unit_price = int(row.get("unit_price") or 0)
            line_total = int(row.get("line_total") or 0)
            if not name:
                blocking.append(f"الصف {index}: اسم المنتج غير مقروء")
            if quantity <= 0:
                blocking.append(f"الصف {index}: الكمية غير صحيحة")
            if unit_price <= 0:
                blocking.append(f"الصف {index}: سعر الوحدة غير صحيح")
            expected = quantity * unit_price
            if line_total and expected != line_total:
                blocking.append(
                    f"الصف {index}: الكمية × السعر ({expected:,}) لا تساوي إجمالي السطر ({line_total:,})"
                )
            calculated_subtotal += line_total or expected
            if float(row.get("confidence") or 0) < 0.85:
                warnings.append(f"الصف {index}: ثقة القراءة أقل من 85% ويحتاج مراجعة")

        discount = int(payload.get("discount_value") or 0)
        shipping = int(payload.get("shipping_extra") or 0)
        calculated_grand = max(calculated_subtotal - discount + shipping, 0)
        declared_grand = payload.get("grand_total")
        if declared_grand is not None and int(declared_grand) != calculated_grand:
            blocking.append(
                f"إجمالي الفاتورة المطبوع ({int(declared_grand):,}) لا يساوي المحسوب ({calculated_grand:,})"
            )
        return {
            "ok": bool(rows) and not blocking,
            "blocking": blocking,
            "warnings": warnings,
            "calculated": {
                "row_count": len(rows),
                "sub_total": calculated_subtotal,
                "grand_total": calculated_grand,
            },
        }
