"""Pages and JSON API for the food wholesale/retail workspace."""
from __future__ import annotations

import os
import uuid

from flask import Blueprint, current_app, g, jsonify, redirect, render_template, request
from werkzeug.utils import secure_filename

from extensions import db
from modules.food import service
from modules.food.guards import (
    can_use_food,
    current_tenant_id,
    food_guard_response,
    require_food,
)
from modules.food.models import FoodSettings
from modules.food.schema import ensure_food_schema

food_bp = Blueprint("food", __name__, url_prefix="/food")


@food_bp.before_request
def _guard_then_schema():
    denied = food_guard_response(json_mode=request.path.startswith("/food/api/"))
    if denied:
        return denied
    ensure_food_schema()


def _tid() -> int:
    return int(getattr(g, "food_tenant_id", None) or current_tenant_id())


def _employee_id():
    row = getattr(g, "food_employee", None)
    return row.id if row else None


def _ok(data=None, **extra):
    payload = {"ok": True}
    if data is not None:
        payload["data"] = data
    payload.update(extra)
    return jsonify(payload)


def _error(exc, status=400):
    db.session.rollback()
    return jsonify({"ok": False, "error": str(exc)}), status


PAGE_CONFIG = {
    "dashboard": ("لوحة المواد الغذائية", "food_reports"),
    "cashier": ("كاشير المواد الغذائية", "food_cashier"),
    "orders": ("فواتير المواد الغذائية", "food_orders"),
    "invoices": ("فواتير المواد الغذائية", "food_orders"),
    "products": ("منتجات المواد الغذائية", "food_products"),
    "purchases": ("المشتريات", "food_purchases"),
    "inventory": ("مخزن المواد الغذائية", "food_inventory"),
    "customers": ("العملاء", "food_parties"),
    "suppliers": ("الموردون", "food_parties"),
    "finance": ("الحركات المالية", "food_finance"),
    "reports": ("تقارير المواد الغذائية", "food_reports"),
    "settings": ("إعدادات النشاط", "food_settings"),
}


@food_bp.route("/")
@require_food("food_reports")
def dashboard_page():
    title, _ = PAGE_CONFIG["dashboard"]
    return render_template("food/workspace.html", food_page="dashboard", food_title=title)


@food_bp.route("/purchases/new")
@require_food("food_purchases")
def purchases_new_page():
    return render_template(
        "food/workspace.html",
        food_page="purchases_new",
        food_title="إضافة فاتورة شراء",
    )


FINANCE_SECTIONS = {
    "receipts": ("سندات قبض العملاء", "fa-arrow-down", "in"),
    "payments": ("تسديدات الموردين", "fa-arrow-up", "out"),
    "expenses": ("مصروفات التشغيل", "fa-receipt", "out"),
    "cash-sessions": ("جلسات الصندوق", "fa-vault", "in"),
}


@food_bp.route("/finance/<section>")
@require_food("food_finance")
def finance_section_page(section):
    config = FINANCE_SECTIONS.get(section)
    if not config:
        return redirect("/food/finance")
    title, icon, tone = config
    return render_template(
        "food/workspace.html",
        food_page="finance_detail",
        food_title=title,
        finance_section=section,
        finance_section_title=title,
        finance_section_icon=icon,
        finance_section_tone=tone,
    )


@food_bp.route("/<page>")
def workspace_page(page):
    config = PAGE_CONFIG.get(page)
    if not config:
        return redirect("/food/")
    title, permission = config
    # Normalize invoices alias to the orders page shell.
    food_page = "orders" if page in {"orders", "invoices"} else page

    @require_food(permission)
    def _render():
        return render_template("food/workspace.html", food_page=food_page, food_title=title)

    return _render()


@food_bp.get("/api/dashboard")
@require_food("food_reports", json_mode=True)
def api_dashboard():
    try:
        return _ok(service.dashboard(
            _tid(),
            range_key=request.args.get("range", "today"),
            start_value=request.args.get("start"),
            end_value=request.args.get("end"),
            view_profit=can_use_food("view_profit") or can_use_food("products.manage_cost"),
        ))
    except Exception as exc:
        return _error(exc)


@food_bp.get("/api/cash-session")
@require_food("food_finance", json_mode=True)
def api_cash_session_get():
    try:
        day = request.args.get("business_date")
        parsed = service._parse_date(day, "تاريخ الجلسة") if day else None
        return _ok(service.get_cash_session(_tid(), parsed, request.args.get("warehouse_id")))
    except Exception as exc:
        return _error(exc)


@food_bp.post("/api/cash-session/open")
@require_food("food_finance", json_mode=True)
def api_cash_session_open():
    try:
        result = service.open_cash_session(_tid(), request.get_json(silent=True) or {}, _employee_id())
        db.session.commit()
        return _ok(result)
    except Exception as exc:
        return _error(exc)


@food_bp.post("/api/cash-session/close")
@require_food("food_finance", json_mode=True)
def api_cash_session_close():
    try:
        result = service.close_cash_session(_tid(), request.get_json(silent=True) or {}, _employee_id())
        db.session.commit()
        return _ok(result)
    except Exception as exc:
        return _error(exc)


@food_bp.post("/api/cash-session/reopen")
@require_food("food_finance", json_mode=True)
def api_cash_session_reopen():
    try:
        result = service.reopen_cash_session(_tid(), request.get_json(silent=True) or {}, _employee_id())
        db.session.commit()
        return _ok(result)
    except Exception as exc:
        return _error(exc)


@food_bp.route("/api/expenses", methods=["GET", "POST"])
@require_food("food_finance", json_mode=True)
def api_expenses():
    try:
        if request.method == "GET":
            start = service._parse_date(request.args.get("start"), "من تاريخ") if request.args.get("start") else None
            end = service._parse_date(request.args.get("end"), "إلى تاريخ") if request.args.get("end") else None
            return _ok(service.list_expenses(_tid(), start, end))
        result = service.create_expense(_tid(), request.get_json(silent=True) or {}, _employee_id())
        db.session.commit()
        return _ok(result)
    except Exception as exc:
        return _error(exc)


@food_bp.delete("/api/expenses/<int:expense_id>")
@require_food("food_finance", json_mode=True)
def api_expense_delete(expense_id):
    try:
        service.delete_expense(_tid(), expense_id)
        db.session.commit()
        return _ok({"deleted": expense_id})
    except Exception as exc:
        return _error(exc)


@food_bp.post("/api/customers/<int:customer_id>/payment-terms")
@require_food("food_parties", json_mode=True)
def api_customer_payment_terms(customer_id):
    try:
        data = request.get_json(silent=True) or {}
        result = service.upsert_customer_payment_terms(_tid(), customer_id, data.get("payment_term_days"))
        db.session.commit()
        return _ok(result)
    except Exception as exc:
        return _error(exc)


@food_bp.post("/api/suppliers/<int:supplier_id>/payment-terms")
@require_food("food_parties", json_mode=True)
def api_supplier_payment_terms(supplier_id):
    try:
        data = request.get_json(silent=True) or {}
        result = service.upsert_supplier_payment_terms(_tid(), supplier_id, data.get("payment_term_days"))
        db.session.commit()
        return _ok(result)
    except Exception as exc:
        return _error(exc)


@food_bp.get("/api/products")
@require_food("food_products", json_mode=True)
def api_products():
    return _ok({
        "products": service.list_products(
            _tid(), request.args.get("q"), request.args.get("category"),
            request.args.get("warehouse_id"),
        ),
        "categories": service.categories(_tid()),
    })


@food_bp.get("/api/cashier/products")
@require_food("food_cashier", json_mode=True)
def api_cashier_products():
    try:
        return _ok(service.cashier_catalog(
            _tid(), search=request.args.get("q"), category=request.args.get("category"),
            subcategory=request.args.get("subcategory"),
            warehouse_id=request.args.get("warehouse_id"), page=request.args.get("page", 1),
            per_page=request.args.get("per_page", 48), mode=request.args.get("mode", "catalog"),
        ))
    except Exception as exc:
        return _error(exc)


@food_bp.post("/api/products")
@require_food("products.create", json_mode=True)
def api_create_product():
    try:
        result = service.create_product(_tid(), request.get_json(silent=True) or {}, _employee_id())
        db.session.commit()
        return _ok(result)
    except Exception as exc:
        return _error(exc)


@food_bp.get("/api/product-form-options")
@require_food("food_products", json_mode=True)
def api_product_form_options():
    return _ok(service.product_form_options(_tid()))


@food_bp.get("/api/products/<int:profile_id>")
@require_food("food_products", json_mode=True)
def api_product_detail(profile_id):
    try:
        return _ok(service.get_product(_tid(), profile_id))
    except Exception as exc:
        return _error(exc, 404)


@food_bp.put("/api/products/<int:profile_id>")
@require_food("products.update", json_mode=True)
def api_update_product(profile_id):
    try:
        result = service.update_product(
            _tid(), profile_id, request.get_json(silent=True) or {}, _employee_id()
        )
        db.session.commit()
        return _ok(result)
    except Exception as exc:
        return _error(exc)


@food_bp.delete("/api/products/<int:profile_id>")
@require_food("products.archive", json_mode=True)
def api_archive_product(profile_id):
    try:
        result = service.archive_product(_tid(), profile_id, _employee_id())
        db.session.commit()
        return _ok(result)
    except Exception as exc:
        return _error(exc)


@food_bp.get("/api/barcodes/check")
@require_food("food_products", json_mode=True)
def api_check_barcode():
    try:
        return _ok(service.check_barcode(
            _tid(), request.args.get("value", ""),
            exclude_barcode_id=request.args.get("exclude_id"),
        ))
    except Exception as exc:
        return _error(exc)


@food_bp.post("/api/product-image")
@require_food("food_products", json_mode=True)
def api_upload_product_image():
    uploaded = request.files.get("image")
    if not uploaded or not uploaded.filename:
        return _error(service.FoodError("اختر صورة للرفع"))
    extension = os.path.splitext(secure_filename(uploaded.filename))[1].lower()
    allowed = {".jpg", ".jpeg", ".png", ".webp"}
    if extension not in allowed or uploaded.mimetype not in {
        "image/jpeg", "image/png", "image/webp",
    }:
        return _error(service.FoodError("صيغة الصورة يجب أن تكون JPG أو PNG أو WEBP"))
    uploaded.stream.seek(0, os.SEEK_END)
    size = uploaded.stream.tell()
    uploaded.stream.seek(0)
    if size > 5 * 1024 * 1024:
        return _error(service.FoodError("حجم الصورة يجب ألا يتجاوز 5MB"))
    relative_dir = os.path.join("static", "uploads", "food", str(_tid()))
    target_dir = os.path.join(current_app.root_path, relative_dir)
    os.makedirs(target_dir, exist_ok=True)
    filename = f"product_{uuid.uuid4().hex}{extension}"
    uploaded.save(os.path.join(target_dir, filename))
    return _ok({"url": "/" + os.path.join(relative_dir, filename).replace("\\", "/")})


@food_bp.get("/api/barcode/<path:barcode>")
@require_food("food_cashier", json_mode=True)
def api_barcode(barcode):
    try:
        return _ok(service.lookup_barcode(_tid(), barcode, request.args.get("warehouse_id")))
    except Exception as exc:
        return _error(exc, 404)


@food_bp.get("/api/cashier-config")
@require_food("food_cashier", json_mode=True)
def api_cashier_config():
    row = FoodSettings.query.filter_by(tenant_id=_tid()).first()
    options = service.product_form_options(_tid())
    employee = getattr(g, "food_employee", None)
    return _ok({
        "default_sale_mode": (row.default_sale_mode if row else "RETAIL"),
        "cashier": {"id": employee.id if employee else None,
                    "name": employee.name if employee else "مدير النظام",
                    "register": f"POS-{employee.id if employee else 1:02d}",
                    "shift_url": "/reports/daily-closing"},
        "warehouses": options["warehouses"],
        "default_warehouse_id": next(
            (item["id"] for item in options["warehouses"] if item["is_default"]),
            options["warehouses"][0]["id"] if options["warehouses"] else None,
        ),
        "settings": {
            "hide_out_of_stock": bool(row.hide_out_of_stock) if row else False,
            "auto_print": row.auto_print if row else "ask",
            "fast_pos_mode": bool(row.fast_pos_mode) if row else False,
            "negative_stock_policy": row.negative_stock_policy if row else "prevent",
            "allow_negative_stock": service._negative_stock_allowed(_tid(), _employee_id()),
            "scale_barcode_enabled": bool(row.scale_barcode_enabled) if row else False,
        },
        "permissions": {name: can_use_food(name) for name in (
            "cashier.discount_item", "cashier.discount_invoice", "cashier.override_price",
            "cashier.sell_credit", "cashier.override_credit_limit", "cashier.return",
            "cashier.void_sale", "cashier.reprint", "cashier.open_drawer",
            "cashier.view_other_branch_stock",
            "cashier.sell_negative_stock",
        )},
        "held_count": len(service.list_held_sales(_tid(), _employee_id())),
    })


@food_bp.post("/api/cashier/validate-cart")
@require_food("food_cashier", json_mode=True)
def api_validate_cart():
    try:
        return _ok(service.validate_cart(_tid(), request.get_json(silent=True) or {}, _employee_id()))
    except Exception as exc:
        return _error(exc)


@food_bp.get("/api/cashier/stock/<int:variant_id>")
@require_food("food_cashier", json_mode=True)
def api_branch_stock(variant_id):
    try:
        return _ok(service.branch_stock(_tid(), variant_id))
    except Exception as exc:
        return _error(exc, 404)


@food_bp.post("/api/cashier/open-drawer")
@require_food("cashier.open_drawer", json_mode=True)
def api_open_cash_drawer():
    service._audit_pos(_tid(), _employee_id(), "cash_drawer_open", entity_type="cashier")
    db.session.commit()
    return _ok({"signal": "finora:cash-drawer-open"})


@food_bp.route("/api/cashier/holds", methods=["GET", "POST"])
@require_food("food_cashier", json_mode=True)
def api_holds():
    try:
        if request.method == "POST":
            result = service.hold_sale(_tid(), request.get_json(silent=True) or {}, _employee_id())
            db.session.commit()
            return _ok(result)
        return _ok(service.list_held_sales(_tid(), _employee_id()))
    except Exception as exc:
        return _error(exc)


@food_bp.post("/api/cashier/holds/<int:hold_id>/restore")
@require_food("food_cashier", json_mode=True)
def api_restore_hold(hold_id):
    try:
        result = service.restore_held_sale(_tid(), hold_id, _employee_id())
        db.session.commit()
        return _ok(result)
    except Exception as exc:
        return _error(exc)


@food_bp.delete("/api/cashier/holds/<int:hold_id>")
@require_food("food_cashier", json_mode=True)
def api_delete_hold(hold_id):
    try:
        service.delete_held_sale(_tid(), hold_id, _employee_id())
        db.session.commit()
        return _ok({"deleted": True})
    except Exception as exc:
        return _error(exc)


@food_bp.get("/api/cashier/returns/search")
@require_food("cashier.return", json_mode=True)
def api_return_search():
    try:
        return _ok(service.search_sales_for_return(_tid(), request.args.get("q", "")))
    except Exception as exc:
        return _error(exc)


@food_bp.post("/api/cashier/returns")
@require_food("cashier.return", json_mode=True)
def api_create_return():
    try:
        result = service.create_sale_return(_tid(), request.get_json(silent=True) or {}, _employee_id())
        db.session.commit()
        return _ok({"id": result.id, "return_no": result.return_no, "total": result.total})
    except Exception as exc:
        return _error(exc)


@food_bp.post("/api/sales")
@require_food("food_cashier", json_mode=True)
def api_create_sale():
    try:
        payload = request.get_json(silent=True) or {}
        payload.setdefault("idempotency_key", request.headers.get("Idempotency-Key"))
        invoice = service.create_sale(_tid(), payload, _employee_id())
        db.session.commit()
        return _ok({
            "id": invoice.id,
            "invoice_no": invoice.invoice_no,
            "total": int(invoice.total or 0),
            "paid": int(invoice.paid_amount or 0),
            "remaining": max(0, int(invoice.total or 0) - int(invoice.paid_amount or 0)),
            "print_url": f"/orders/invoice/{invoice.id}",
        })
    except Exception as exc:
        return _error(exc)


@food_bp.post("/api/purchases")
@require_food("food_purchases", json_mode=True)
def api_create_purchase():
    try:
        purchase = service.create_purchase(_tid(), request.get_json(silent=True) or {}, _employee_id())
        db.session.commit()
        return _ok({
            "id": purchase.id,
            "invoice_no": purchase.invoice_no,
            "total": int(purchase.grand_total or 0),
            "paid": int(purchase.paid_total or 0),
            "remaining": int(purchase.remaining_total or 0),
            "status": purchase.status,
            "is_draft": bool(purchase.is_draft),
            "stock_applied": bool(purchase.stock_applied),
        })
    except Exception as exc:
        return _error(exc)


def _purchase_filters_from_request():
    return {
        "range": request.args.get("range", "today"),
        "start": request.args.get("start"),
        "end": request.args.get("end"),
        "q": request.args.get("q", ""),
        "branch_id": request.args.get("branch_id"),
        "warehouse_id": request.args.get("warehouse_id"),
        "supplier_id": request.args.get("supplier_id"),
        "payment_method": request.args.get("payment_method"),
        "status_tab": request.args.get("status_tab") or request.args.get("tab") or "all",
        "purchase_status": request.args.get("purchase_status") or request.args.get("status") or "",
        "page": request.args.get("page", 1),
        "page_size": request.args.get("page_size") or request.args.get("per_page") or 20,
    }


@food_bp.get("/api/purchases/meta")
@require_food("food_purchases", json_mode=True)
def api_purchases_meta():
    from modules.food import purchase_service
    from modules.food.guards import can_use_food

    try:
        data = purchase_service.purchase_filter_options(_tid())
        data["permissions"] = {
            "view": True,
            "create": can_use_food("food_purchases"),
            "pay": can_use_food("food_purchases") or can_use_food("food_finance"),
            "cancel": can_use_food("food_purchases"),
            "export": can_use_food("food_purchases") or can_use_food("food_reports"),
            "view_cost": can_use_food("products.manage_cost") or can_use_food("food_products"),
        }
        return _ok(data)
    except Exception as exc:
        return _error(exc)


@food_bp.get("/api/purchases")
@require_food("food_purchases", json_mode=True)
def api_purchases_list():
    from modules.food import purchase_service

    try:
        return _ok(purchase_service.list_purchases(_tid(), _purchase_filters_from_request()))
    except Exception as exc:
        return _error(exc)


@food_bp.get("/api/purchases/export")
@require_food("food_purchases", json_mode=True)
def api_purchases_export():
    from modules.food import purchase_service

    try:
        rows = purchase_service.export_purchases_rows(_tid(), _purchase_filters_from_request())
        return _ok({"rows": rows, "count": len(rows)})
    except Exception as exc:
        return _error(exc)


@food_bp.get("/api/purchases/supplier-summary/<int:supplier_id>")
@require_food("food_purchases", json_mode=True)
def api_purchase_supplier_summary(supplier_id):
    from modules.food import purchase_service

    try:
        return _ok(purchase_service.supplier_summary(_tid(), supplier_id))
    except Exception as exc:
        return _error(exc)


@food_bp.get("/api/purchases/check-duplicate")
@require_food("food_purchases", json_mode=True)
def api_purchase_check_duplicate():
    from modules.food import purchase_service

    try:
        supplier_id = int(request.args.get("supplier_id") or 0)
        exclude = request.args.get("exclude_id")
        dup = purchase_service.check_duplicate_supplier_invoice(
            _tid(),
            supplier_id,
            request.args.get("supplier_invoice_no") or "",
            exclude_id=int(exclude) if exclude else None,
        )
        return _ok({"duplicate": dup})
    except Exception as exc:
        return _error(exc)


@food_bp.get("/api/purchases/<int:purchase_id>")
@require_food("food_purchases", json_mode=True)
def api_purchase_detail(purchase_id):
    from modules.food import purchase_service
    from modules.food.guards import can_use_food

    try:
        view_cost = can_use_food("products.manage_cost") or can_use_food("food_products")
        return _ok(purchase_service.get_purchase_detail(_tid(), purchase_id, view_cost=view_cost))
    except Exception as exc:
        return _error(exc, 404)


@food_bp.post("/api/purchases/<int:purchase_id>/payments")
@require_food("food_purchases", json_mode=True)
def api_purchase_payment(purchase_id):
    from modules.food import purchase_service

    try:
        result = purchase_service.register_purchase_payment(
            _tid(), purchase_id, request.get_json(silent=True) or {}, _employee_id()
        )
        db.session.commit()
        return _ok(result)
    except Exception as exc:
        return _error(exc)


@food_bp.post("/api/purchases/<int:purchase_id>/cancel")
@require_food("food_purchases", json_mode=True)
def api_purchase_cancel(purchase_id):
    from modules.food import purchase_service

    try:
        payload = request.get_json(silent=True) or {}
        result = purchase_service.cancel_purchase(
            _tid(), purchase_id, reason=payload.get("reason") or ""
        )
        db.session.commit()
        return _ok(result)
    except Exception as exc:
        return _error(exc)


@food_bp.post("/api/purchases/<int:purchase_id>/confirm")
@require_food("food_purchases", json_mode=True)
def api_purchase_confirm(purchase_id):
    from modules.food import purchase_service

    try:
        result = purchase_service.confirm_purchase(_tid(), purchase_id, _employee_id())
        db.session.commit()
        return _ok(result)
    except Exception as exc:
        return _error(exc)


@food_bp.post("/api/purchases/<int:purchase_id>/returns")
@require_food("food_purchases", json_mode=True)
def api_purchase_return(purchase_id):
    from modules.food import purchase_service

    try:
        result = purchase_service.create_purchase_return(
            _tid(), purchase_id, request.get_json(silent=True) or {}, _employee_id()
        )
        db.session.commit()
        return _ok(result)
    except Exception as exc:
        return _error(exc)


@food_bp.get("/api/inventory")
@require_food("food_inventory", json_mode=True)
def api_inventory():
    return _ok(service.inventory(_tid()))


@food_bp.post("/api/inventory/count")
@require_food("food_inventory", json_mode=True)
def api_inventory_count():
    try:
        result = service.apply_inventory_count(
            _tid(), request.get_json(silent=True) or {}, _employee_id()
        )
        db.session.commit()
        return _ok(result)
    except Exception as exc:
        return _error(exc)


@food_bp.get("/api/customers")
@require_food("food_parties", json_mode=True)
def api_customers():
    try:
        result = service.list_customers(
            _tid(),
            q=request.args.get("q"),
            tab=request.args.get("tab", "all"),
            limit=request.args.get("limit", 300),
        )
        # POS / finance expect a plain array; manage UI asks for summary=1.
        if str(request.args.get("summary") or "").strip() in {"1", "true", "yes"}:
            return _ok(result)
        return _ok(result["rows"])
    except Exception as exc:
        return _error(exc)


@food_bp.get("/api/customers/<int:customer_id>")
@require_food("food_parties", json_mode=True)
def api_customer_detail(customer_id):
    try:
        return _ok(service.get_customer_detail(_tid(), customer_id))
    except Exception as exc:
        return _error(exc)


@food_bp.post("/api/customers")
@require_food("food_parties", json_mode=True)
def api_create_customer():
    try:
        result = service.create_customer(_tid(), request.get_json(silent=True) or {})
        db.session.commit()
        return _ok(result)
    except Exception as exc:
        return _error(exc)


@food_bp.patch("/api/customers/<int:customer_id>")
@require_food("food_parties", json_mode=True)
def api_update_customer(customer_id):
    try:
        result = service.update_customer(_tid(), customer_id, request.get_json(silent=True) or {})
        db.session.commit()
        return _ok(result)
    except Exception as exc:
        return _error(exc)


@food_bp.get("/api/suppliers")
@require_food("food_parties", json_mode=True)
def api_suppliers():
    try:
        result = service.list_suppliers(
            _tid(),
            q=request.args.get("q"),
            tab=request.args.get("tab", "all"),
            limit=request.args.get("limit", 300),
        )
        if str(request.args.get("summary") or "").strip() in {"1", "true", "yes"}:
            return _ok(result)
        return _ok(result["rows"])
    except Exception as exc:
        return _error(exc)


@food_bp.get("/api/suppliers/<int:supplier_id>")
@require_food("food_parties", json_mode=True)
def api_supplier_detail(supplier_id):
    try:
        return _ok(service.get_supplier_detail(_tid(), supplier_id))
    except Exception as exc:
        return _error(exc)


@food_bp.post("/api/suppliers")
@require_food("food_parties", json_mode=True)
def api_create_supplier():
    try:
        result = service.create_supplier(_tid(), request.get_json(silent=True) or {})
        db.session.commit()
        return _ok(result)
    except Exception as exc:
        return _error(exc)


@food_bp.patch("/api/suppliers/<int:supplier_id>")
@require_food("food_parties", json_mode=True)
def api_update_supplier(supplier_id):
    try:
        result = service.update_supplier(_tid(), supplier_id, request.get_json(silent=True) or {})
        db.session.commit()
        return _ok(result)
    except Exception as exc:
        return _error(exc)


@food_bp.post("/api/finance/customer-receipt")
@require_food("food_finance", json_mode=True)
def api_customer_receipt():
    data = request.get_json(silent=True) or {}
    try:
        result = service.record_customer_receipt(
            _tid(), service.as_int(data.get("customer_id")), data.get("amount"),
            document_number=data.get("document_number"), note=data.get("note"),
        )
        db.session.commit()
        return _ok(result)
    except Exception as exc:
        return _error(exc)


@food_bp.post("/api/finance/supplier-payment")
@require_food("food_finance", json_mode=True)
def api_supplier_payment():
    data = request.get_json(silent=True) or {}
    try:
        result = service.record_supplier_payment(
            _tid(), service.as_int(data.get("supplier_id")), data.get("amount"),
            document_number=data.get("document_number"), note=data.get("note"),
        )
        db.session.commit()
        return _ok(result)
    except Exception as exc:
        return _error(exc)


@food_bp.get("/api/finance/overview")
@require_food("food_finance", json_mode=True)
def api_finance_overview():
    try:
        return _ok(service.finance_movement_overview(_tid()))
    except Exception as exc:
        return _error(exc)


@food_bp.get("/api/finance/movements/<section>")
@require_food("food_finance", json_mode=True)
def api_finance_movements(section):
    if section not in FINANCE_SECTIONS:
        return _error(service.FoodError("نوع الحركة المالية غير صالح"), 404)
    try:
        return _ok(service.list_finance_movements(_tid(), section))
    except Exception as exc:
        return _error(exc)


@food_bp.get("/api/reports")
@require_food("food_reports", json_mode=True)
def api_reports():
    try:
        return _ok(service.reports(
            _tid(),
            request.args.get("range", "today"),
            request.args.get("start"),
            request.args.get("end"),
            view_profit=can_use_food("view_profit") or can_use_food("products.manage_cost"),
        ))
    except Exception as exc:
        return _error(exc)


def _invoice_filters_from_request():
    return {
        "range": request.args.get("range", "today"),
        "start": request.args.get("start"),
        "end": request.args.get("end"),
        "q": request.args.get("q", ""),
        "branch_id": request.args.get("branch_id"),
        "cashier_id": request.args.get("cashier_id"),
        "sale_type": request.args.get("sale_type"),
        "payment_method": request.args.get("payment_method"),
        "status_tab": request.args.get("status_tab") or request.args.get("tab") or "all",
        "invoice_status": request.args.get("invoice_status") or request.args.get("status") or "",
        "page": request.args.get("page", 1),
        "page_size": request.args.get("page_size") or request.args.get("per_page") or 20,
    }


@food_bp.get("/api/invoices/meta")
@require_food("food_orders", json_mode=True)
def api_invoices_meta():
    from modules.food.guards import can_use_food

    try:
        data = service.invoice_filter_options(_tid())
        emp = _employee_id()
        data["permissions"] = {
            "view": True,
            "create": can_use_food("cashier.sell") or can_use_food("food_cashier"),
            "receive_payment": can_use_food("food_finance") or can_use_food("food_orders"),
            "return": can_use_food("cashier.return"),
            "void": can_use_food("cashier.void_sale"),
            "reprint": can_use_food("cashier.reprint") or can_use_food("food_orders"),
            "view_cost": can_use_food("products.manage_cost"),
            "view_profit": can_use_food("products.manage_cost"),
            "export": can_use_food("food_orders") or can_use_food("food_reports"),
        }
        data["employee_id"] = emp
        return _ok(data)
    except Exception as exc:
        return _error(exc)


@food_bp.get("/api/invoices")
@require_food("food_orders", json_mode=True)
def api_invoices_list():
    try:
        return _ok(service.list_invoices(_tid(), _invoice_filters_from_request()))
    except Exception as exc:
        return _error(exc)


@food_bp.get("/api/invoices/export")
@require_food("food_orders", json_mode=True)
def api_invoices_export():
    try:
        rows = service.export_invoices_rows(_tid(), _invoice_filters_from_request())
        return _ok({"rows": rows, "count": len(rows)})
    except Exception as exc:
        return _error(exc)


@food_bp.get("/api/invoices/<int:invoice_id>")
@require_food("food_orders", json_mode=True)
def api_invoice_detail(invoice_id):
    from modules.food.guards import can_use_food

    try:
        view_cost = can_use_food("products.manage_cost")
        return _ok(service.get_invoice_detail(
            _tid(), invoice_id, view_cost=view_cost, view_profit=view_cost,
        ))
    except Exception as exc:
        return _error(exc, 404)


@food_bp.post("/api/invoices/<int:invoice_id>/payments")
@require_food("food_orders", json_mode=True)
def api_invoice_payment(invoice_id):
    try:
        result = service.register_invoice_payment(
            _tid(), invoice_id, request.get_json(silent=True) or {}, _employee_id()
        )
        db.session.commit()
        return _ok(result)
    except Exception as exc:
        return _error(exc)


@food_bp.post("/api/invoices/<int:invoice_id>/void")
@require_food("cashier.void_sale", json_mode=True)
def api_invoice_void(invoice_id):
    try:
        payload = request.get_json(silent=True) or {}
        result = service.void_invoice(
            _tid(), invoice_id, _employee_id(), reason=payload.get("reason") or ""
        )
        db.session.commit()
        return _ok(result)
    except Exception as exc:
        return _error(exc)


@food_bp.post("/api/invoices/<int:invoice_id>/reprint")
@require_food("food_orders", json_mode=True)
def api_invoice_reprint(invoice_id):
    try:
        result = service.mark_invoice_reprinted(_tid(), invoice_id, _employee_id())
        db.session.commit()
        return _ok(result)
    except Exception as exc:
        return _error(exc)


@food_bp.route("/api/settings", methods=["GET", "POST"])
@require_food("food_settings", json_mode=True)
def api_settings():
    tid = _tid()
    row = FoodSettings.query.filter_by(tenant_id=tid).first()
    if not row:
        row = FoodSettings(tenant_id=tid)
        db.session.add(row)
        db.session.flush()
    if request.method == "POST":
        data = request.get_json(silent=True) or {}
        row.allow_negative_stock = bool(data.get("allow_negative_stock", False))
        mode = str(data.get("default_sale_mode") or "RETAIL").upper()
        row.default_sale_mode = mode if mode in {"RETAIL", "WHOLESALE"} else "RETAIL"
        row.expiry_warning_days = max(1, service.as_int(data.get("expiry_warning_days"), 30))
        policy = str(data.get("negative_stock_policy") or "prevent").lower()
        row.negative_stock_policy = policy if policy in {"prevent", "permission", "allow"} else "prevent"
        row.allow_negative_stock = row.negative_stock_policy == "allow"
        row.hide_out_of_stock = bool(data.get("hide_out_of_stock", False))
        auto_print = str(data.get("auto_print") or "ask").lower()
        row.auto_print = auto_print if auto_print in {"always", "never", "ask"} else "ask"
        row.fast_pos_mode = bool(data.get("fast_pos_mode", False))
        row.scale_barcode_enabled = bool(data.get("scale_barcode_enabled", False))
        prefix = str(data.get("scale_barcode_prefix") or "20").strip()
        if not prefix.isdigit() or len(prefix) > 4:
            raise service.FoodError("بادئة باركود الميزان يجب أن تكون أرقاماً وبحد أقصى 4 خانات")
        row.scale_barcode_prefix = prefix
        row.scale_barcode_product_digits = min(8, service.as_int(data.get("scale_barcode_product_digits"), 5, minimum=1))
        row.scale_barcode_value_digits = min(8, service.as_int(data.get("scale_barcode_value_digits"), 5, minimum=1))
        row.scale_barcode_divisor = service.as_int(data.get("scale_barcode_divisor"), 1000, minimum=1)
        row.default_receivable_days = service.as_int(data.get("default_receivable_days"), 30, minimum=0)
        row.default_payable_days = service.as_int(data.get("default_payable_days"), 30, minimum=0)
        issue_policy = str(data.get("default_issue_policy") or "FEFO").upper()
        row.default_issue_policy = issue_policy if issue_policy in {"FIFO", "FEFO"} else "FEFO"
        footer = str(data.get("receipt_footer") or "").strip()[:255]
        row.receipt_footer = footer or None
        db.session.commit()
    return _ok({
        "allow_negative_stock": bool(row.allow_negative_stock),
        "default_sale_mode": row.default_sale_mode,
        "expiry_warning_days": row.expiry_warning_days,
        "negative_stock_policy": row.negative_stock_policy,
        "hide_out_of_stock": bool(row.hide_out_of_stock),
        "auto_print": row.auto_print,
        "fast_pos_mode": bool(row.fast_pos_mode),
        "scale_barcode_enabled": bool(row.scale_barcode_enabled),
        "scale_barcode_prefix": row.scale_barcode_prefix,
        "scale_barcode_product_digits": row.scale_barcode_product_digits,
        "scale_barcode_value_digits": row.scale_barcode_value_digits,
        "scale_barcode_divisor": row.scale_barcode_divisor,
        "default_receivable_days": int(getattr(row, "default_receivable_days", None) or 30),
        "default_payable_days": int(getattr(row, "default_payable_days", None) or 30),
        "default_issue_policy": str(getattr(row, "default_issue_policy", None) or "FEFO"),
        "receipt_footer": getattr(row, "receipt_footer", None) or "",
    })


@food_bp.route("/api/promotions", methods=["GET", "POST"])
@require_food("food_settings", json_mode=True)
def api_promotions():
    try:
        if request.method == "GET":
            return _ok(service.list_promotions(_tid()))
        result = service.save_promotion(_tid(), request.get_json(silent=True) or {})
        db.session.commit()
        return _ok(result)
    except Exception as exc:
        return _error(exc)


@food_bp.route("/api/promotions/<int:promotion_id>", methods=["PUT", "DELETE"])
@require_food("food_settings", json_mode=True)
def api_promotion_detail(promotion_id):
    try:
        if request.method == "DELETE":
            from modules.food.models import FoodPromotion
            row = FoodPromotion.query.filter_by(tenant_id=_tid(), id=promotion_id).first()
            if not row:
                raise service.FoodError("العرض غير موجود")
            db.session.delete(row)
            db.session.commit()
            return _ok({"deleted": True})
        result = service.save_promotion(_tid(), request.get_json(silent=True) or {}, promotion_id)
        db.session.commit()
        return _ok(result)
    except Exception as exc:
        return _error(exc)
