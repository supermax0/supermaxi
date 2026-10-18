from __future__ import annotations

import base64
import json
import mimetypes
import os
from typing import Any, Dict, List, Optional

from flask import current_app

from modules.workspace.services.document_intelligence.document_image_preprocessing_service import (
    DocumentImagePreprocessingService,
)


COURIER_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "is_courier_statement",
        "company_name",
        "statement_date",
        "row_count",
        "total_collected_amount",
        "total_delivery_fees",
        "expected_net_amount",
        "rows",
        "document_warnings",
    ],
    "properties": {
        "is_courier_statement": {"type": "boolean"},
        "company_name": {"type": ["string", "null"]},
        "statement_date": {"type": ["string", "null"]},
        "row_count": {"type": ["integer", "null"]},
        "total_collected_amount": {"type": ["integer", "null"]},
        "total_delivery_fees": {"type": ["integer", "null"]},
        "expected_net_amount": {"type": ["integer", "null"]},
        "document_warnings": {
            "type": "array",
            "items": {"type": "string"},
        },
        "rows": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "row_index",
                    "source_page",
                    "order_number",
                    "customer_name",
                    "customer_phone",
                    "collected_amount",
                    "delivery_fee",
                    "net_amount",
                    "statement_date",
                    "confidence",
                    "warnings",
                ],
                "properties": {
                    "row_index": {"type": "integer"},
                    "source_page": {"type": ["integer", "null"]},
                    "order_number": {"type": ["string", "null"]},
                    "customer_name": {"type": ["string", "null"]},
                    "customer_phone": {"type": ["string", "null"]},
                    "collected_amount": {"type": ["integer", "null"]},
                    "delivery_fee": {"type": ["integer", "null"]},
                    "net_amount": {"type": ["integer", "null"]},
                    "statement_date": {"type": ["string", "null"]},
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                    "warnings": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
            },
        },
    },
}


class CourierVisionExtractionService:
    """Extract a courier statement with vision; never performs business writes."""

    @staticmethod
    def is_supported(mime_type: str, filename: str = "") -> bool:
        mime = (mime_type or "").lower()
        name = (filename or "").lower()
        return (
            mime == "application/pdf"
            or mime.startswith("image/")
            or name.endswith((".pdf", ".png", ".jpg", ".jpeg", ".webp"))
        )

    @staticmethod
    def should_try(
        mime_type: str,
        filename: str,
        tables: Optional[List[Dict[str, Any]]] = None,
    ) -> bool:
        if not CourierVisionExtractionService.is_supported(mime_type, filename):
            return False
        if not CourierVisionExtractionService._enabled():
            return False

        mime = (mime_type or "").lower()
        if mime.startswith("image/"):
            return True

        # Native PDF tables are usually more reliable and cheaper than a vision call.
        reliable_methods = {"fitz_tables", "pdfplumber"}
        return not any(
            (table.get("method") in reliable_methods)
            and float(table.get("confidence") or 0) >= 0.65
            for table in (tables or [])
        )

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
        if not CourierVisionExtractionService.is_supported(mime_type, filename):
            return {"status": "not_available", "tables": [], "warnings": []}

        prepared_files: List[Dict[str, Any]] = []
        preprocessing: List[Dict[str, Any]] = []
        try:
            if client is None:
                from modules.ai_sales.openai_service import (
                    get_openai_api_key,
                    get_openai_client,
                )

                if not get_openai_api_key():
                    return {
                        "status": "not_available",
                        "tables": [],
                        "warnings": ["مفتاح OpenAI غير مضبوط؛ تم استخدام الاستخراج المحلي فقط."],
                    }
                client = get_openai_client()

            selected_model = (
                model
                or current_app.config.get("WORKSPACE_DOCUMENT_VISION_MODEL")
                or current_app.config.get("OPENAI_VISION_MODEL")
                or "gpt-5.4"
            )
            content = [{
                "type": "input_text",
                "text": CourierVisionExtractionService._prompt(),
            }]
            all_files = [
                *(additional_files or []),
                {
                    "abs_path": abs_path,
                    "mime_type": mime_type,
                    "filename": filename,
                },
            ]
            for index, item in enumerate(all_files, start=1):
                prepared = DocumentImagePreprocessingService.prepare_for_analysis(
                    item["abs_path"],
                    item.get("mime_type") or "",
                    item.get("filename") or "",
                )
                prepared_files.append(prepared)
                preprocessing.append(dict(prepared.get("metadata") or {}))
                content.append({
                    "type": "input_text",
                    "text": (
                        f"الملف/الصفحة المرفوعة رقم {index}: "
                        f"{item.get('filename') or ''}. "
                        "هذه نسخة محسّنة آلياً من الصفحة الأصلية ومخصصة للقراءة فقط."
                    ),
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
                    "أنت مدقق كشوف تسديد لشركات النقل العراقية. "
                    "استخرج ما تراه فقط ولا تخمّن أي رقم غير واضح."
                ),
                "input": [{"role": "user", "content": content}],
                "text": {
                    "format": {
                        "type": "json_schema",
                        "name": "courier_statement",
                        "strict": True,
                        "schema": COURIER_SCHEMA,
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
                            os.environ.get(
                                "WORKSPACE_DOCUMENT_REASONING_EFFORT",
                                "medium",
                            ),
                        )
                    )
                }

            response = client.responses.create(**kwargs)
            raw = str(getattr(response, "output_text", "") or "").strip()
            if not raw:
                raise ValueError("لم يرجع نموذج الرؤية نتيجة")
            payload = json.loads(raw)
            result = CourierVisionExtractionService._to_extraction_payload(
                payload, selected_model
            )
            result["preprocessing"] = preprocessing
            return result
        except Exception as exc:
            return {
                "status": "failed",
                "tables": [],
                "preprocessing": preprocessing,
                "warnings": [
                    f"تعذر تحليل المستند بالرؤية الذكية؛ تم استخدام الاستخراج المحلي: {exc}"
                ],
            }
        finally:
            for prepared in prepared_files:
                DocumentImagePreprocessingService.cleanup(prepared)

    @staticmethod
    def _enabled() -> bool:
        raw = current_app.config.get(
            "WORKSPACE_DOCUMENT_AI_ENABLED",
            os.environ.get("WORKSPACE_DOCUMENT_AI_ENABLED", "1"),
        )
        return str(raw).strip().lower() not in {"0", "false", "off", "no"}

    @staticmethod
    def _file_content(abs_path: str, mime_type: str, filename: str) -> Dict[str, Any]:
        with open(abs_path, "rb") as source:
            encoded = base64.b64encode(source.read()).decode("ascii")

        detected_mime = (
            mime_type
            or mimetypes.guess_type(filename or abs_path)[0]
            or "application/octet-stream"
        )
        data_url = f"data:{detected_mime};base64,{encoded}"
        if detected_mime == "application/pdf" or (filename or "").lower().endswith(".pdf"):
            return {
                "type": "input_file",
                "filename": filename or os.path.basename(abs_path),
                "file_data": data_url,
                "detail": "high",
            }
        return {
            "type": "input_image",
            "image_url": data_url,
            "detail": "high",
        }

    @staticmethod
    def _prompt() -> str:
        return (
            "حلل كل صفحات هذا المستند. إذا لم يكن كشف تسديد شركة نقل، اجعل "
            "is_courier_statement=false واترك rows فارغة. في كشف النقل استخرج كل صف مرة واحدة. "
            "order_number هو رقم الطلب/الباركود المطبوع وليس رقم تسلسل الصف. "
            "collected_amount هو إجمالي قيمة الطلب قبل أجرة التوصيل، delivery_fee هي الأجرة، "
            "وnet_amount هو الصافي المستحق (collected_amount - delivery_fee). "
            "اقرأ الأرقام كدنانير عراقية صحيحة بلا فواصل. النسخ المرسلة محسنة للتباين والحدة "
            "وقد دُوّرت آلياً؛ تحقق من اتجاه النص ولا تعتبر خطوط الجدول أو الباركود أرقاماً. "
            "قد تكون صفحات الكشف ملفات صور منفصلة؛ اعتبر كل الملفات المرفوعة كشفاً واحداً "
            "وحافظ على ترتيبها. لا تُسقط آخر صف من أي صفحة ولا تُزح أرقام الطلبات أو الهواتف إلى الصف التالي عند حدود الصفحات. "
            "عدّ صفوف كل صفحة منفردة أولاً، ثم اجمعها، وراجع أول وآخر صف في كل صفحة مرة ثانية. "
            "استخرج المجاميع المطبوعة أسفل الكشف وعدد الصفوف المطبوع إن وجد. "
            "قبل الإخراج النهائي تحقق أن مجموع كل عمود يساوي الإجمالي المطبوع وأن إجمالي التحصيل ناقص الأجور يساوي الصافي؛ "
            "إذا لم تتطابق الأرقام فأعد قراءة الصف المختلف بصرياً ولا تغيّر الإجمالي المطبوع ليتوافق مع تخمين الصفوف. "
            "لا تستنتج رقماً مطموساً: اجعله null وأضف تحذيراً. "
            "الثقة أقل من 0.98 عند أي التباس بصري. لا تنفذ أي عملية مالية."
        )

    @staticmethod
    def _to_extraction_payload(payload: Dict[str, Any], model: str) -> Dict[str, Any]:
        if not payload.get("is_courier_statement"):
            return {
                "status": "not_courier_statement",
                "tables": [],
                "warnings": list(payload.get("document_warnings") or []),
                "provider": "openai",
                "model": model,
            }

        headers = [
            "order_number",
            "customer_name",
            "customer_phone",
            "collected_amount",
            "delivery_fee",
            "net_amount",
            "statement_date",
        ]
        rows_out: List[List[Any]] = []
        row_metadata: List[Dict[str, Any]] = []
        for index, row in enumerate(payload.get("rows") or [], start=1):
            rows_out.append(
                [
                    row.get("order_number"),
                    row.get("customer_name"),
                    row.get("customer_phone"),
                    row.get("collected_amount"),
                    row.get("delivery_fee"),
                    row.get("net_amount"),
                    row.get("statement_date"),
                ]
            )
            row_metadata.append(
                {
                    "row_index": row.get("row_index") or index,
                    "source_page": row.get("source_page"),
                    "confidence": float(row.get("confidence") or 0),
                    "warnings": list(row.get("warnings") or []),
                }
            )

        totals = {
            "row_count": payload.get("row_count"),
            "total_collected_amount": payload.get("total_collected_amount"),
            "total_delivery_fees": payload.get("total_delivery_fees"),
            "expected_net_amount": payload.get("expected_net_amount"),
        }
        table = {
            "page": 1,
            "index": 0,
            "confidence": CourierVisionExtractionService._aggregate_confidence(
                row_metadata
            ),
            "method": "openai_vision_structured",
            "headers": headers,
            "rows": rows_out,
            "row_metadata": row_metadata,
            "statement_totals": totals,
            "company_name": payload.get("company_name"),
            "statement_date": payload.get("statement_date"),
        }
        text_lines = [
            "كشف تسديد شركة نقل",
            f"شركة النقل: {payload.get('company_name') or ''}",
        ]
        text_lines.extend(
            " | ".join("" if value is None else str(value) for value in row)
            for row in rows_out
        )
        warnings = list(payload.get("document_warnings") or [])
        validation = CourierVisionExtractionService.validate_payload(payload)
        warnings.extend(validation["warnings"])
        return {
            "status": "completed",
            "text": "\n".join(text_lines),
            "text_sample": "\n".join(text_lines)[:500],
            "pages": [
                {
                    "page": 1,
                    "text": "\n".join(text_lines),
                    "confidence": table["confidence"],
                    "method": "openai_vision_structured",
                }
            ],
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

        seen = set()
        low_confidence_rows: List[int] = []
        for index, row in enumerate(rows, start=1):
            order_number = str(row.get("order_number") or "").strip()
            if not order_number:
                blocking.append(f"الصف {index}: رقم الطلب غير مقروء")
            elif order_number in seen:
                blocking.append(f"رقم الطلب {order_number} مكرر في الاستخراج")
            seen.add(order_number)

            gross = row.get("collected_amount")
            fee = row.get("delivery_fee")
            net = row.get("net_amount")
            if gross is None or fee is None or net is None:
                blocking.append(f"الصف {index}: أحد مبالغ التحصيل/الأجرة/الصافي مفقود")
            elif int(gross) - int(fee) != int(net):
                blocking.append(f"الصف {index}: الإجمالي ناقص الأجرة لا يساوي الصافي")
            if float(row.get("confidence") or 0) < 0.98:
                low_confidence_rows.append(index)

        if low_confidence_rows:
            warnings.append(
                f"الثقة البصرية أقل من 98% في {len(low_confidence_rows)} صف؛ "
                "ستُحسم السلامة بمطابقة الطلبات والمجاميع."
            )

        calculated = {
            "row_count": len(rows),
            "total_collected_amount": sum(
                int(row.get("collected_amount") or 0) for row in rows
            ),
            "total_delivery_fees": sum(
                int(row.get("delivery_fee") or 0) for row in rows
            ),
            "expected_net_amount": sum(
                int(row.get("net_amount") or 0) for row in rows
            ),
        }
        for key, calculated_value in calculated.items():
            declared = payload.get(key)
            if declared is None:
                blocking.append(f"المجموع المطبوع {key} غير مقروء")
            elif int(declared) != int(calculated_value):
                blocking.append(
                    f"عدم تطابق {key}: المطبوع {int(declared):,} والمحسوب {int(calculated_value):,}"
                )

        return {
            "ok": not blocking,
            "blocking": blocking,
            "warnings": warnings,
            "declared": {
                key: payload.get(key)
                for key in (
                    "row_count",
                    "total_collected_amount",
                    "total_delivery_fees",
                    "expected_net_amount",
                )
            },
            "calculated": calculated,
        }

    @staticmethod
    def _aggregate_confidence(row_metadata: List[Dict[str, Any]]) -> float:
        values = [float(row.get("confidence") or 0) for row in row_metadata]
        return round(min(values), 4) if values else 0.0
