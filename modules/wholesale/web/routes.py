"""Jinja pages for wholesale Operations Center and supporting lists."""
from __future__ import annotations

from flask import Blueprint, render_template, request

from modules.wholesale.guards import require_wholesale
from modules.wholesale.schema_guard import ensure_wholesale_schema

wholesale_web_bp = Blueprint("wholesale", __name__, url_prefix="/wholesale")


@wholesale_web_bp.before_request
def _web_schema():
    ensure_wholesale_schema()


@wholesale_web_bp.route("/")
@wholesale_web_bp.route("/ops")
@require_wholesale("wholesale_ops")
def operations_center():
    op = (request.args.get("op") or "sale").strip()
    if op not in ("sale", "receipt", "purchase", "payment"):
        op = "sale"
    return render_template(
        "wholesale/operations_center.html",
        initial_op=op,
        ws_page="ops",
    )


@wholesale_web_bp.route("/sales")
@require_wholesale("wholesale_sales")
def sales_list():
    return render_template(
        "wholesale/list_page.html",
        page_key="sales",
        page_title="المبيعات",
        ws_page="sales",
    )


@wholesale_web_bp.route("/purchases")
@require_wholesale("wholesale_purchases")
def purchases_list():
    return render_template(
        "wholesale/list_page.html",
        page_key="purchases",
        page_title="المشتريات",
        ws_page="purchases",
    )


@wholesale_web_bp.route("/receipts")
@require_wholesale("wholesale_receipts")
def receipts_page():
    return render_template(
        "wholesale/operations_center.html",
        initial_op="receipt",
        ws_page="ops",
    )


@wholesale_web_bp.route("/payments")
@require_wholesale("wholesale_payments")
def payments_page():
    return render_template(
        "wholesale/operations_center.html",
        initial_op="payment",
        ws_page="ops",
    )


@wholesale_web_bp.route("/customers")
@require_wholesale("wholesale_ops")
def customers_page():
    return render_template(
        "wholesale/list_page.html",
        page_key="customers",
        page_title="العملاء",
        ws_page="customers",
    )


@wholesale_web_bp.route("/suppliers")
@require_wholesale("wholesale_ops")
def suppliers_page():
    return render_template(
        "wholesale/list_page.html",
        page_key="suppliers",
        page_title="الموردون",
        ws_page="suppliers",
    )


@wholesale_web_bp.route("/products")
@require_wholesale("wholesale_ops")
def products_page():
    return render_template(
        "wholesale/list_page.html",
        page_key="products",
        page_title="المنتجات",
        ws_page="products",
    )


@wholesale_web_bp.route("/warehouses")
@require_wholesale("wholesale_warehouses")
def warehouses_page():
    return render_template("wholesale/warehouses.html", ws_page="warehouses")


@wholesale_web_bp.route("/transfers")
@require_wholesale("wholesale_warehouses")
def transfers_page():
    return render_template(
        "wholesale/warehouses.html",
        focus="transfers",
        ws_page="transfers",
    )


@wholesale_web_bp.route("/accounts")
@require_wholesale("wholesale_ops")
def accounts_page():
    return render_template(
        "wholesale/list_page.html",
        page_key="accounts",
        page_title="الحسابات والصناديق",
        ws_page="accounts",
    )


@wholesale_web_bp.route("/statement")
@require_wholesale("wholesale_statement")
def statement_page():
    return render_template("wholesale/statement.html", ws_page="statement")


@wholesale_web_bp.route("/expenses")
@require_wholesale("wholesale_ops")
def expenses_page():
    return render_template(
        "wholesale/list_page.html",
        page_key="expenses",
        page_title="المصروفات",
        ws_page="expenses",
    )


@wholesale_web_bp.route("/reports")
@require_wholesale("wholesale_reports")
def reports_page():
    return render_template("wholesale/reports.html", ws_page="reports")


@wholesale_web_bp.route("/settings")
@require_wholesale("wholesale_settings")
def settings_page():
    return render_template("wholesale/settings.html", ws_page="settings")
