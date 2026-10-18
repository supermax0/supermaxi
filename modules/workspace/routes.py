"""
HTML routes for Finora AI Workspace (LEON).
"""

from datetime import datetime

from flask import Blueprint, g, redirect, render_template, request, session

workspace_html_bp = Blueprint("workspace_html", __name__)


def _require_login():
    if "user_id" not in session:
        return redirect("/login")
    return None


@workspace_html_bp.route("/")
def workspace_home():
    denied = _require_login()
    if denied:
        return denied

    if request.args.get("dev") == "1":
        return render_template("workspace_dev/app.html")

    return render_template("workspace/app.html")


@workspace_html_bp.route("/courier-analysis/<analysis_id>/print")
def print_courier_analysis(analysis_id):
    denied = _require_login()
    if denied:
        return denied

    from models.invoice_settings import InvoiceSettings
    from modules.workspace.services.courier_settlement.courier_readonly_analysis_service import (
        CourierReadonlyAnalysisService,
    )
    from modules.workspace.services.session_service import SessionService

    analysis = CourierReadonlyAnalysisService.get_analysis(analysis_id)
    if not analysis:
        return "كشف التحليل غير موجود", 404

    user_id = session.get("user_id")
    tenant_slug = session.get("tenant_slug") or getattr(g, "tenant", None)
    workspace_session = SessionService.get_session(
        analysis.session_id,
        user_id,
        tenant_slug,
    )
    if not workspace_session:
        return "غير مصرح بعرض هذا الكشف", 403

    CourierReadonlyAnalysisService.reconcile_legacy_manual_exclusions(
        analysis,
        session=workspace_session,
        user_id=user_id,
    )
    rows_payload = CourierReadonlyAnalysisService.list_rows(
        analysis.id,
        page=1,
        page_size=5000,
    )
    print_rows = []
    total_amount = 0
    total_fees = 0
    total_net = 0
    for row in rows_payload.get("rows") or []:
        explanation = row.get("match_explanation") or {}
        candidate = explanation.get("candidate") or {}
        amount = int(row.get("collected_amount") or 0)
        fee = int(row.get("delivery_fee") or 0)
        net = (
            int(row.get("net_amount"))
            if row.get("net_amount") is not None
            else amount - fee
        )
        print_rows.append({
            "index": row.get("row_index"),
            "invoice_number": candidate.get("invoice_id") or row.get("matched_invoice_id"),
            "courier_barcode": (
                candidate.get("matched_shipping_barcode")
                or row.get("normalized_order_number")
                or row.get("raw_order_number")
            ),
            "phone": candidate.get("customer_phone") or row.get("customer_phone"),
            "amount": amount,
            "delivery_fee": fee,
            "net": net,
            "match_score": round(float(row.get("match_score") or 0)),
            "match_status": explanation.get("status_label") or row.get("match_status"),
        })
        total_amount += amount
        total_fees += fee
        total_net += net

    settings = InvoiceSettings.get_settings()
    total_net = total_amount - total_fees
    company_name = (
        getattr(settings, "report_company_name", None)
        or settings.company_name
        or tenant_slug
        or "الشركة"
    )
    show_logo = getattr(settings, "report_show_logo", True)
    report_logo = (
        getattr(settings, "report_logo_path", None)
        or settings.logo_path
    ) if show_logo else None
    summary = analysis.get_summary() or {}

    return render_template(
        "workspace/courier_analysis_print.html",
        analysis=analysis,
        rows=print_rows,
        company_name=company_name,
        company_address=(
            getattr(settings, "report_address", None)
            or settings.company_address
        ),
        company_phone=(
            getattr(settings, "report_phone", None)
            or settings.company_phone
        ),
        report_logo=report_logo,
        courier_company=analysis.courier_company_name_detected or "شركة النقل",
        generated_at=datetime.now(),
        report_number=analysis.id[:8].upper(),
        total_amount=total_amount,
        total_fees=total_fees,
        total_net=total_net,
        manual_exclusions=summary.get("excluded_rows") or [],
    )
