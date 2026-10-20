from utils.time_format import format_timestamp
import json
import os
from io import BytesIO

from flask import Blueprint, render_template, request, redirect, url_for, session, jsonify, current_app, g, send_file, flash
from werkzeug.utils import secure_filename
from extensions import db
from utils.branch_scope import (
    active_branch_id,
    current_employee,
    is_general_admin,
    resolve_write_branch_id,
    viewing_all_branches,
)
from models.product import Product
from models.order_item import OrderItem
from models.invoice import Invoice
from models.supplier import Supplier
# من models.purchase تم نقله إلى purchases.py
from models.employee import Employee
from models.account_transaction import AccountTransaction
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.sql import func
from datetime import datetime

# دوال حركات المخزون (للعرض فقط)
from utils.inventory_movements import (
    get_product_inventory_movements,
    get_product_inventory_summary,
    get_low_stock_products,
    get_out_of_stock_products,
    validate_sale_quantity
)
from utils.permission_checks import check_permission
from utils.activity_logger import PRODUCT_SNAPSHOT_FIELDS, log_activity, log_mutation, snapshot_attrs

from utils.product_schema_guard import ensure_product_schema
from utils.order_item_schema_guard import ensure_order_item_schema
from utils.order_shipping import sync_product_name_to_order_items
from utils.tenant_feature_flags import tenant_feature_enabled
from utils.trade_in_service import employee_can_access_replacement_product
from utils.product_delivery_fees import (
    apply_delivery_fees_to_meta,
    delivery_fees_from_form,
    product_delivery_config,
)
from utils.tenant_provinces import get_tenant_provinces_config
from utils.branch_migration import ensure_branch_schema, get_default_branch
from utils.branch_context import current_branch_id, init_branch_context
from utils.branch_stock_service import (
    adjust_branch_stock,
    branch_stock_map,
    get_branch_stock,
    set_branch_stock,
    set_opening_branch_stock,
    BranchStockError,
)
from utils.branch_product_service import barcode_conflict
from utils.branch_mode import independent_branches_enabled
from utils.product_color_service import (
    ProductColorError,
    adjust_color_stock,
    color_stock_total,
    get_branch_product_colors,
    product_has_colors,
)
from utils.desktop_product_colors import append_product_colors, local_color_rows, lock_color_product
from utils.product_color_media import apply_color_images, cleanup_color_uploads
from utils.product_options import apply_product_options, option_config

inventory_bp = Blueprint("inventory", __name__)


@inventory_bp.get("/smart-audit")
def smart_audit_app():
    from pathlib import Path
    from modules.inventory_audit.common import AuditError, actor, require
    try:
        actor()
        require("inventory.audit.view")
    except AuditError as error:
        return jsonify(success=False, error=str(error)), error.status
    source = Path(current_app.static_folder) / "finora-inventory-audit" / "audit.html"
    if not source.is_file():
        return jsonify(success=False, error="واجهة الجرد تحتاج بناء أصول الويب من النسخة المحدثة"), 503
    html = source.read_text(encoding="utf-8").replace("<head>", "<head>" + render_template("partials/time_format_bootstrap.html"), 1)
    return current_app.response_class(html, mimetype="text/html")


@inventory_bp.before_request
def _inventory_branch_setup():
    if "user_id" not in session or not getattr(g, "tenant", None):
        return
    ensure_product_schema()
    ensure_order_item_schema()
    ensure_branch_schema()
    init_branch_context()


def _inventory_branch_id():
    if getattr(g, "view_all_branches", False):
        return None
    return current_branch_id() or (get_default_branch().id if get_default_branch() else None)


def _inventory_employee():
    user_id = session.get("user_id")
    return Employee.query.get(user_id) if user_id else None


def _visible_inventory_products(products):
    employee = _inventory_employee()
    return [
        product
        for product in products
        if employee_can_access_replacement_product(employee, product)
    ]


def _resolve_stock_adjust_branch_id(data) -> int:
    """Resolve the branch for BranchStock mutations.

    ``resolve_write_branch_id`` intentionally ignores an explicit branch in
    shared (non-independent) mode and always returns the company default.
    Quick-edit and similar stock screens expose a branch selector and write
    per-branch ``BranchStock`` rows, so they must honor the chosen branch.
    """
    from models.branch import Branch

    if independent_branches_enabled():
        return resolve_write_branch_id(data, allow_admin_any_branch=True)

    raw = None
    try:
        raw = data.get("branch_id")
    except AttributeError:
        raw = data

    if raw not in (None, "", 0, "0", "all"):
        try:
            branch = Branch.query.filter_by(id=int(raw), is_active=True).first()
        except (TypeError, ValueError):
            branch = None
        if not branch:
            raise ValueError("الفرع المطلوب غير موجود أو غير نشط")
        employee = current_employee()
        if employee and not is_general_admin(employee) and getattr(employee, "branch_id", None):
            if int(employee.branch_id) != int(branch.id):
                raise PermissionError("لا يمكنك تعديل مخزون فرع آخر")
        return int(branch.id)

    return resolve_write_branch_id(data)


def _branch_id_for_product_stock(form=None, meta: dict | None = None) -> int | None:
    """Use the product's selected branch for stock; fallback to current inventory branch."""
    from models.branch import Branch

    if form is not None:
        return resolve_write_branch_id(form)

    candidates: list[int] = []
    if meta is not None:
        raw = meta.get("branch_id")
        if raw is not None:
            try:
                candidates.append(int(raw))
            except (TypeError, ValueError):
                pass

    seen: set[int] = set()
    for branch_id in candidates:
        if branch_id <= 0 or branch_id in seen:
            continue
        seen.add(branch_id)
        branch = Branch.query.filter_by(id=branch_id, is_active=True).first()
        if branch and (viewing_all_branches() or branch.id == active_branch_id()):
            return branch.id

    return _inventory_branch_id()


def _edit_current_stock_for_product(product: Product, meta: dict | None = None) -> int:
    """Current on-hand quantity for the product edit form (branch-scoped when applicable)."""
    stock_branch_id = int(product.branch_id or 0) or _branch_id_for_product_stock(meta=meta)
    if stock_branch_id:
        if product_has_colors(product):
            colors = get_branch_product_colors(product.id, stock_branch_id)
            if colors:
                return sum(int(row.get("qty") or 0) for row in colors)
        return get_branch_stock(stock_branch_id, product.id)
    return int(product.quantity or 0)


def _product_display_qty(product, stock_map, view_all):
    color_total = color_stock_total(product)
    if color_total is not None:
        return color_total
    fallback = int(product.quantity or 0)
    return stock_map.get(product.id, fallback)


def _product_branch_colors_map(products, branches) -> dict[int, dict[int, list[dict]]]:
    """Color balances keyed by displayed product then branch."""
    result: dict[int, dict[int, list[dict]]] = {}
    for product in products or []:
        if not product_has_colors(product):
            continue
        by_branch: dict[int, list[dict]] = {}
        for branch in branches or []:
            colors = get_branch_product_colors(product.id, branch.id)
            if colors:
                by_branch[int(branch.id)] = colors
        result[int(product.id)] = by_branch
    return result


def _load_product_meta(product) -> dict:
    raw = ((product.meta_json if product else None) or "").strip()
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except Exception:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _split_multiline_values(raw) -> list[str]:
    items: list[str] = []
    for line in str(raw or "").splitlines():
        value = line.strip()
        if value:
            items.append(value)
    return items


def _parse_specs_text(raw) -> list[dict]:
    items: list[dict] = []
    for line in str(raw or "").splitlines():
        row = line.strip(" -\t\r\n")
        if not row:
            continue
        if ":" in row:
            label, value = row.split(":", 1)
        elif " - " in row:
            label, value = row.split(" - ", 1)
        else:
            label, value = "تفصيل", row
        value = value.strip()
        label = label.strip() or "تفصيل"
        if value:
            items.append({"label": label, "value": value})
    return items


def _parse_optional_date(raw):
    raw = (raw or "").strip()
    if not raw:
        return None
    try:
        return datetime.strptime(raw, "%Y-%m-%d").date()
    except ValueError:
        return None


def _extract_specs_items(meta: dict | None) -> list[dict]:
    meta = meta or {}
    raw_items = meta.get("specs_items")
    items: list[dict] = []
    if isinstance(raw_items, list):
        for row in raw_items:
            if not isinstance(row, dict):
                continue
            label = str(row.get("label") or "").strip() or "تفصيل"
            value = str(row.get("value") or "").strip()
            if value:
                items.append({"label": label, "value": value})
    if items:
        return items
    return _parse_specs_text(meta.get("specs_text"))


def _specs_items_from_form(form) -> list[dict]:
    labels = form.getlist("spec_label[]")
    values = form.getlist("spec_value[]")
    items: list[dict] = []
    count = max(len(labels), len(values))
    for idx in range(count):
        label = str(labels[idx] if idx < len(labels) else "").strip() or "تفصيل"
        value = str(values[idx] if idx < len(values) else "").strip()
        if value:
            items.append({"label": label, "value": value})
    if items:
        return items
    return _parse_specs_text(form.get("specs_text"))


def _save_uploaded_product_image(file_storage) -> str | None:
    """حفظ صورة منتج في static/uploads/products وإرجاع المسار العام."""
    if not file_storage or not getattr(file_storage, "filename", None):
        return None
    ext = os.path.splitext(file_storage.filename)[1].lower()
    if ext not in (".jpg", ".jpeg", ".png", ".webp", ".gif"):
        return None
    upload_folder = os.path.join(current_app.root_path, "static", "uploads", "products")
    os.makedirs(upload_folder, exist_ok=True)
    raw = secure_filename(file_storage.filename) or f"image{ext}"
    safe = f"{datetime.utcnow().strftime('%Y%m%d%H%M%S')}_{raw}"
    path = os.path.join(upload_folder, safe)
    file_storage.save(path)
    return f"/static/uploads/products/{safe}"


def _save_uploaded_product_video(file_storage) -> str | None:
    """حفظ فيديو منتج عبر خدمة الوسائط وإرجاع الرابط العام."""
    if not file_storage or not getattr(file_storage, "filename", None):
        return None
    from services.media_service import VIDEO_EXTENSIONS, detect_kind, save_uploaded_file

    ext = os.path.splitext(file_storage.filename)[1].lower()
    if detect_kind(file_storage.content_type or "") != "video" and ext not in VIDEO_EXTENSIONS:
        return None
    result = save_uploaded_file(file_storage, max_mb=500)
    if not result.get("ok"):
        return None
    return str(result.get("url") or "").strip() or None


def _apply_product_media_uploads(meta: dict, form, files) -> dict:
    """رفع فيديو وحتى 4 صور إضافية؛ الإبقاء على الحالي إن لم يُرفع جديد."""
    video_file = files.get("product_video") if files else None
    new_video = _save_uploaded_product_video(video_file)
    if new_video:
        meta["video_url"] = new_video
    else:
        keep_video = (form.get("keep_video_url") or "").strip()
        if keep_video:
            meta["video_url"] = keep_video
        else:
            meta.pop("video_url", None)

    gallery_files = files.getlist("gallery_images") if files and hasattr(files, "getlist") else []
    saved_gallery: list[str] = []
    for gallery_file in gallery_files:
        if len(saved_gallery) >= 4:
            break
        url = _save_uploaded_product_image(gallery_file)
        if url:
            saved_gallery.append(url)
    if saved_gallery:
        meta["gallery"] = saved_gallery
    else:
        keep_gallery = _split_multiline_values(form.get("keep_gallery_urls"))
        if keep_gallery:
            meta["gallery"] = keep_gallery[:4]
        else:
            meta.pop("gallery", None)
    return meta


def _meta_from_inventory_add_form(form) -> dict:
    """بناء meta_json من نموذج صفحة إضافة/تعديل المنتج."""
    meta_keys = (
        "barcode_type",
        "unit",
        "brand",
        "category",
        "subcategory",
        "warranty",
        "tax_applied",
        "sales_tax_type",
        "product_type",
        "shelf",
        "shelf_row",
        "shelf_loc",
        "weight",
        "custom_field_1",
        "custom_field_2",
        "custom_field_3",
        "custom_field_4",
        "purchase_ex_tax",
        "purchase_inc_tax",
        "sale_ex_tax",
        "sale_inc_tax",
        "beauty_product_type",
        "usage_instructions",
        "warning_notes",
        "shelf_life_after_opening_days",
    )
    meta: dict = {}
    for k in meta_keys:
        v = (form.get(k) or "").strip()
        if v:
            meta[k] = v

    branch_id_raw = (form.get("branch_id") or "").strip()
    if branch_id_raw.isdigit():
        from models.branch import Branch

        branch_id = int(branch_id_raw)
        branch = Branch.query.filter_by(id=branch_id, is_active=True).first()
        if branch:
            meta["branch_id"] = branch.id
            meta["branch_name"] = branch.name
            meta["branch_note"] = branch.name
    else:
        meta.pop("branch_id", None)
        meta.pop("branch_name", None)
        meta.pop("branch_note", None)

    if form.get("enable_imei"):
        meta["enable_imei"] = True
    if bool(form.get("not_for_sale")):
        meta["not_for_sale"] = True
    specs_items = _specs_items_from_form(form)
    if specs_items:
        meta["specs_items"] = specs_items
    store_badge = (form.get("store_badge") or "").strip()
    if store_badge:
        meta["store_badge"] = store_badge
    by_province, default_fee = delivery_fees_from_form(
        form,
        get_tenant_provinces_config().get("list") or [],
    )
    meta = apply_delivery_fees_to_meta(meta, by_province, default_fee)
    if form.get("has_colors"):
        meta["has_colors"] = True
    from utils.product_region_pricing import set_dual_region_pricing_flag

    meta = set_dual_region_pricing_flag(meta, bool(form.get("dual_region_pricing")))
    return meta


def _color_rows_from_form(form) -> list[dict]:
    names = form.getlist("color_name[]")
    qtys = form.getlist("color_qty[]")
    buys = form.getlist("color_buy_price[]")
    sales = form.getlist("color_sale_price[]")
    govs = form.getlist("color_gov_sale_price[]")
    rows: list[dict] = []
    for idx, name in enumerate(names):
        color = (name or "").strip()
        if not color:
            continue
        qty = max(0, int((qtys[idx] if idx < len(qtys) else 0) or 0))
        buy_raw = buys[idx] if idx < len(buys) else ""
        sale_raw = sales[idx] if idx < len(sales) else ""
        gov_raw = govs[idx] if idx < len(govs) else ""
        row = {"name": color, "qty": qty}
        if str(buy_raw).strip() != "":
            row["buy_price"] = max(0, int(buy_raw or 0))
        if str(sale_raw).strip() != "":
            row["sale_price"] = max(0, int(sale_raw or 0))
        if str(gov_raw).strip() != "":
            row["governorate_sale_price"] = max(0, int(gov_raw or 0))
        rows.append(row)
    return rows


def _apply_product_colors_from_form(product: Product, form) -> int:
    from utils.product_color_service import save_product_colors
    from models.product_color_variant import ProductColorVariant

    if option_config(product).get("axes"):
        # The old web color fields must never replace option balances or keys.
        return int(db.session.query(db.func.coalesce(db.func.sum(ProductColorVariant.quantity), 0))
                   .filter_by(product_id=product.id).scalar() or 0)

    has_colors = bool(form.get("has_colors"))
    if not has_colors:
        ProductColorVariant.query.filter_by(product_id=product.id).delete(synchronize_session=False)
        meta = _load_product_meta(product)
        meta.pop("has_colors", None)
        product.meta_json = json.dumps(meta, ensure_ascii=False) if meta else None
        return int(product.opening_stock or product.quantity or 0)

    rows = _color_rows_from_form(form)
    if not rows:
        return 0
    save_product_colors(product.id, rows)
    return sum(int(r.get("qty") or 0) for r in rows)


def _company_branches_for_form():
    ensure_branch_schema()
    from models.branch import Branch

    return (
        Branch.query.filter_by(is_active=True)
        .order_by(Branch.is_default.desc(), Branch.name.asc())
        .all()
    )


def _inventory_add_summary():
    """إحصائيات مختصرة لشريط الملخص في صفحة إضافة المنتج."""
    products = _visible_inventory_products(Product.query.all())

    def _val(v, default=0):
        return default if v is None else v

    current_inventory_value = sum(_val(p.buy_price) * _val(p.quantity) for p in products)
    expected_profit_from_stock = sum(
        (
            _val(p.sale_price)
            - _val(p.buy_price)
            - _val(p.shipping_cost)
            - _val(p.marketing_cost)
        )
        * _val(p.quantity)
        for p in products
    )
    return {
        "products_count": len(products),
        "current_inventory_value": current_inventory_value,
        "expected_profit_from_stock": expected_profit_from_stock,
        "company_branches": _company_branches_for_form(),
    }


def _product_branch_info(product, branch_by_id: dict | None = None) -> dict:
    meta = _load_product_meta(product)
    branch_id = meta.get("branch_id")
    label = (meta.get("branch_name") or meta.get("branch_note") or "").strip()
    parsed_id = None
    if branch_id is not None and str(branch_id).strip() != "":
        try:
            parsed_id = int(branch_id)
        except (TypeError, ValueError):
            parsed_id = None
    if parsed_id and branch_by_id:
        branch = branch_by_id.get(parsed_id)
        if branch:
            label = branch.name
    if not label:
        label = "—"
    return {"branch_id": parsed_id, "branch_name": label}


def _product_branch_map(products, branches) -> dict[int, dict]:
    branch_by_id = {b.id: b for b in (branches or [])}
    return {p.id: _product_branch_info(p, branch_by_id) for p in products}


def _product_branch_stock_map(products, catalog_members: dict[int, list[int]] | None = None) -> dict[int, dict[int, int]]:
    from models.branch import BranchStock

    product_ids = [p.id for p in (products or [])]
    if not product_ids:
        return {}

    source_ids = [
        source_id
        for product_id in product_ids
        for source_id in (catalog_members or {}).get(product_id, [product_id])
    ]

    query = BranchStock.query.filter(BranchStock.product_id.in_(source_ids))
    # مدير الشركة يستطيع اختيار أي فرع من فلتر صفحة المخزون.  سابقاً كانت
    # الواجهة تعرض كل الفروع، بينما هذه الخريطة تُحمّل رصيد الفرع الحالي فقط؛
    # لذلك كان اختيار فرع آخر يُظهر كل المنتجات برصيد صفر رغم وجود أرصدة لها.
    # الموظف غير المدير يبقى محصوراً بفرعه ولا تصل إليه أرصدة الفروع الأخرى.
    # In legacy shared mode all employees intentionally work with one shared
    # catalogue, so filtering this map to the internal default branch would
    # hide the stock held by every other branch.
    if independent_branches_enabled() and not (viewing_all_branches() or is_general_admin()):
        query = query.filter(BranchStock.branch_id == int(active_branch_id() or 0))
    rows = query.all()
    representative_by_source = {
        source_id: representative_id
        for representative_id, member_ids in (catalog_members or {}).items()
        for source_id in member_ids
    }
    stock_by_product: dict[int, dict[int, int]] = {pid: {} for pid in product_ids}
    for row in rows:
        product_id = representative_by_source.get(row.product_id, row.product_id)
        branch_stock = stock_by_product.setdefault(product_id, {})
        branch_stock[row.branch_id] = branch_stock.get(row.branch_id, 0) + int(row.quantity or 0)
    return stock_by_product


def _collapse_shared_inventory_products(products) -> tuple[list[Product], dict[int, list[int]]]:
    """Return one inventory row for each product family in shared mode.

    Branch migration creates local copies. Match their stable catalog family
    and the legacy barcode/SKU identity shared with the purchase picker/POS,
    so editing one copy cannot split the family into duplicate display rows.
    """
    from services.pos_catalog import shared_catalog_groups

    representatives: list[Product] = []
    members: dict[int, list[int]] = {}
    for group in shared_catalog_groups(products):
        group.sort(key=lambda product: (int(product.branch_id or 0), int(product.id)))
        representative = group[0]
        representatives.append(representative)
        members[representative.id] = [int(product.id) for product in group]
    representatives.sort(key=lambda product: ((product.name or "").casefold(), product.id))
    return representatives, members


def _delivery_fees_context(product=None, meta: dict | None = None) -> dict:
    def _fee_int(value) -> int:
        try:
            return max(0, int(value or 0))
        except (TypeError, ValueError):
            return 0

    cfg = product_delivery_config(product) if product else {"delivery_by_province": {}, "delivery_default_fee": 0}
    if meta:
        by_province = meta.get("delivery_by_province")
        if isinstance(by_province, dict):
            cfg["delivery_by_province"] = {
                str(k).strip(): _fee_int(v)
                for k, v in by_province.items()
                if str(k).strip()
            }
        if meta.get("delivery_default_fee") is not None:
            cfg["delivery_default_fee"] = _fee_int(meta.get("delivery_default_fee"))
    return {
        "delivery_by_province": cfg.get("delivery_by_province") or {},
        "delivery_default_fee": cfg.get("delivery_default_fee") or 0,
    }


def _safe_xlsx_filename(value: str) -> str:
    clean = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in str(value or "").strip())
    return clean.strip("_") or "inventory"


def _is_shipping_fee_product(product) -> bool:
    marker_values = (product.name or "", product.sku or "", product.barcode or "")
    return any("رسوم الشحن" in str(v) or "__SF_SHIPPING__" in str(v) for v in marker_values)


def _build_inventory_audit_workbook(branch=None, *, all_branches=False):
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter
    from models.branch import Branch, BranchStock

    ensure_branch_schema()
    branches = (
        Branch.query.filter_by(is_active=True).order_by(Branch.name.asc()).all()
        if all_branches
        else ([branch] if branch else [])
    )
    if not branches:
        branches = Branch.query.filter_by(is_active=True).order_by(Branch.name.asc()).all()

    products = [
        p for p in Product.query.order_by(Product.name.asc(), Product.id.asc()).all()
        if not _is_shipping_fee_product(p)
    ]
    product_ids = [p.id for p in products]
    branch_ids = [b.id for b in branches]

    stock_by_key: dict[tuple[int, int], int] = {}
    if product_ids and branch_ids:
        rows = (
            BranchStock.query
            .filter(BranchStock.product_id.in_(product_ids), BranchStock.branch_id.in_(branch_ids))
            .all()
        )
        stock_by_key = {
            (int(row.branch_id), int(row.product_id)): int(row.quantity or 0)
            for row in rows
        }

    wb = Workbook()
    ws = wb.active
    ws.title = "الجرد"
    ws.sheet_view.rightToLeft = True
    ws.freeze_panes = "A7"
    summary = wb.create_sheet("ملخص الفروع")
    summary.sheet_view.rightToLeft = True
    info = wb.create_sheet("تعليمات")
    info.sheet_view.rightToLeft = True

    title_fill = PatternFill("solid", fgColor="0F172A")
    header_fill = PatternFill("solid", fgColor="2563EB")
    note_fill = PatternFill("solid", fgColor="EFF6FF")
    input_fill = PatternFill("solid", fgColor="FEF9C3")
    light_fill = PatternFill("solid", fgColor="F8FAFC")
    total_fill = PatternFill("solid", fgColor="E0F2FE")
    border = Border(
        left=Side(style="thin", color="D9E2EC"),
        right=Side(style="thin", color="D9E2EC"),
        top=Side(style="thin", color="D9E2EC"),
        bottom=Side(style="thin", color="D9E2EC"),
    )

    headers = [
        "رقم الفرع",
        "رقم المنتج",
        "الفرع",
        "المنتج",
        "SKU",
        "الباركود",
        "الحالة",
        "كمية النظام بالفرع",
        "الكمية الفعلية",
        "الفرق",
        "ملاحظة الجرد",
        "إجمالي المنتج بالنظام",
        "سعر الشراء",
    ]
    start_row = 7
    data_rows_count = len(branches) * len(products)
    end_row = start_row + max(data_rows_count, 1) - 1
    scope = "كل الفروع" if all_branches else (branch.name if branch else "كل الفروع")

    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=len(headers))
    ws["A1"] = "قالب جرد المخزون حسب الفروع"
    ws["A1"].fill = title_fill
    ws["A1"].font = Font(color="FFFFFF", bold=True, size=18)
    ws["A1"].alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[1].height = 30

    ws.merge_cells(start_row=2, start_column=1, end_row=2, end_column=len(headers))
    ws["A2"] = f"الفرع: {scope} | تاريخ الإنشاء: {format_timestamp(datetime.utcnow())} | اكتب العدد الفعلي في العمود الأصفر."
    ws["A2"].fill = note_fill
    ws["A2"].font = Font(color="1E3A8A", bold=True)
    ws["A2"].alignment = Alignment(horizontal="center")

    for cell_range, label in (
        ("A4:B5", "إجمالي أسطر الجرد"),
        ("C4:D5", None),
        ("E4:F5", "الأسطر المدخلة"),
        ("G4:H5", None),
        ("I4:J5", "أسطر بيها فرق"),
        ("K4:M5", None),
    ):
        ws.merge_cells(cell_range)
        if label:
            ws[cell_range.split(":")[0]] = label
    ws["C4"] = f"=COUNTA(D{start_row}:D{end_row})"
    ws["G4"] = f"=COUNT(I{start_row}:I{end_row})"
    ws["K4"] = f'=SUMPRODUCT(--(I{start_row}:I{end_row}<>""),--(J{start_row}:J{end_row}<>0))'
    for row in ws.iter_rows(min_row=4, max_row=5, min_col=1, max_col=len(headers)):
        for cell in row:
            cell.fill = light_fill
            cell.border = border
            cell.alignment = Alignment(horizontal="center", vertical="center")
            cell.font = Font(bold=True, color="0F172A")
    for addr, color in (("C4", "2563EB"), ("G4", "16A34A"), ("K4", "DC2626")):
        ws[addr].font = Font(bold=True, color=color, size=16)

    for col_idx, header in enumerate(headers, 1):
        cell = ws.cell(row=6, column=col_idx, value=header)
        cell.fill = header_fill
        cell.font = Font(color="FFFFFF", bold=True)
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = border

    row_idx = start_row
    for b in branches:
        branch_label = f"{b.name} ({b.code})" if b.code else b.name
        for p in products:
            qty = stock_by_key.get((int(b.id), int(p.id)), 0)
            values = [
                b.id,
                p.id,
                branch_label,
                p.name,
                p.sku or "",
                p.barcode or "",
                "نشط" if p.active else "غير نشط",
                qty,
                None,
                f'=IF(I{row_idx}="","",I{row_idx}-H{row_idx})',
                "",
                int(p.quantity or 0),
                int(p.buy_price or 0),
            ]
            for col_idx, value in enumerate(values, 1):
                cell = ws.cell(row=row_idx, column=col_idx, value=value)
                cell.border = border
                cell.alignment = Alignment(
                    horizontal="right" if col_idx in (4, 11) else "center",
                    vertical="center",
                )
                if col_idx == 9:
                    cell.fill = input_fill
                    cell.font = Font(bold=True)
            row_idx += 1
    if data_rows_count == 0:
        ws.cell(row=start_row, column=1, value="لا توجد منتجات للجرد")

    for row_no in range(start_row, end_row + 1):
        for col_idx in (8, 9, 10, 12, 13):
            ws.cell(row=row_no, column=col_idx).number_format = "#,##0"
    for idx, width in enumerate([10, 10, 22, 34, 14, 18, 12, 16, 16, 12, 24, 16, 14], 1):
        ws.column_dimensions[get_column_letter(idx)].width = width
    ws.auto_filter.ref = f"A6:M{end_row}"

    summary_headers = ["رقم الفرع", "الفرع", "أسطر الجرد", "المدخل", "أسطر الفرق", "الزيادة", "النقص", "صافي الفرق"]
    summary.merge_cells(start_row=1, start_column=1, end_row=1, end_column=len(summary_headers))
    summary["A1"] = "ملخص الفروقات حسب الفرع"
    summary["A1"].fill = title_fill
    summary["A1"].font = Font(color="FFFFFF", bold=True, size=18)
    summary["A1"].alignment = Alignment(horizontal="center")
    for col_idx, header in enumerate(summary_headers, 1):
        cell = summary.cell(row=3, column=col_idx, value=header)
        cell.fill = header_fill
        cell.font = Font(color="FFFFFF", bold=True)
        cell.border = border
        cell.alignment = Alignment(horizontal="center")
    for idx, b in enumerate(branches, 4):
        summary.cell(row=idx, column=1, value=b.id)
        summary.cell(row=idx, column=2, value=b.name)
        summary.cell(row=idx, column=3, value=f'=COUNTIF(\'الجرد\'!$A${start_row}:$A${end_row},A{idx})')
        summary.cell(row=idx, column=4, value=f'=COUNTIFS(\'الجرد\'!$A${start_row}:$A${end_row},A{idx},\'الجرد\'!$I${start_row}:$I${end_row},"<>")')
        summary.cell(row=idx, column=5, value=f'=SUMPRODUCT(--(\'الجرد\'!$A${start_row}:$A${end_row}=A{idx}),--(\'الجرد\'!$I${start_row}:$I${end_row}<>""),--(\'الجرد\'!$J${start_row}:$J${end_row}<>0))')
        summary.cell(row=idx, column=6, value=f'=SUMIFS(\'الجرد\'!$J${start_row}:$J${end_row},\'الجرد\'!$A${start_row}:$A${end_row},A{idx},\'الجرد\'!$J${start_row}:$J${end_row},">0")')
        summary.cell(row=idx, column=7, value=f'=ABS(SUMIFS(\'الجرد\'!$J${start_row}:$J${end_row},\'الجرد\'!$A${start_row}:$A${end_row},A{idx},\'الجرد\'!$J${start_row}:$J${end_row},"<0"))')
        summary.cell(row=idx, column=8, value=f"=F{idx}-G{idx}")
    total_row = 4 + len(branches)
    summary.merge_cells(start_row=total_row, start_column=1, end_row=total_row, end_column=2)
    summary.cell(row=total_row, column=1, value="الإجمالي")
    for col_idx in range(3, 9):
        col = get_column_letter(col_idx)
        summary.cell(row=total_row, column=col_idx, value=f"=SUM({col}4:{col}{total_row - 1})")
    for row in summary.iter_rows(min_row=3, max_row=total_row, min_col=1, max_col=len(summary_headers)):
        for cell in row:
            cell.border = border
            cell.alignment = Alignment(horizontal="center", vertical="center")
    for cell in summary[total_row]:
        cell.fill = total_fill
        cell.font = Font(bold=True)
    for idx, width in enumerate([12, 26, 14, 12, 12, 12, 12, 14], 1):
        summary.column_dimensions[get_column_letter(idx)].width = width

    info.merge_cells(start_row=1, start_column=1, end_row=1, end_column=2)
    info["A1"] = "تعليمات استخدام ملف الجرد"
    info["A1"].fill = title_fill
    info["A1"].font = Font(color="FFFFFF", bold=True, size=18)
    info["A1"].alignment = Alignment(horizontal="center")
    instructions = [
        ("1", "لا تعدل الأعمدة الزرقاء أو الرمادية، اكتب فقط في عمود الكمية الفعلية الأصفر."),
        ("2", "الفرق ينحسب تلقائياً: الكمية الفعلية - كمية النظام."),
        ("3", "الفرق الموجب يعني زيادة، والفرق السالب يعني نقص."),
        ("4", "اكتب سبب الفرق أو أي ملاحظة في عمود ملاحظة الجرد."),
        ("5", "بعد إكمال الجرد، أرسل نفس الملف حتى أطلع الفروقات حسب الفرع والمنتج."),
    ]
    for row_no, (no, text) in enumerate(instructions, 3):
        info.cell(row=row_no, column=1, value=no)
        info.cell(row=row_no, column=2, value=text)
    for row in info.iter_rows(min_row=3, max_row=3 + len(instructions) - 1, min_col=1, max_col=2):
        for cell in row:
            cell.fill = light_fill
            cell.border = border
            cell.alignment = Alignment(horizontal="right", vertical="center", wrap_text=True)
    info.column_dimensions["A"].width = 10
    info.column_dimensions["B"].width = 80

    output = BytesIO()
    wb.save(output)
    output.seek(0)
    return output, scope



# ======================================
# Inventory Page
# ======================================
@inventory_bp.route("/audit-template.xlsx", methods=["GET"])
def download_inventory_audit_template():
    if not check_permission("can_manage_inventory"):
        return redirect("/pos"), 403

    ensure_product_schema()
    ensure_branch_schema()
    from models.branch import Branch

    requested_branch_raw = request.args.get("branch_id")
    branch_id_raw = (requested_branch_raw or "all").strip()
    all_branches = branch_id_raw in ("", "all")
    current_id = int(active_branch_id() or 0)
    if independent_branches_enabled() and not viewing_all_branches():
        if requested_branch_raw is not None and (
            all_branches or (branch_id_raw.isdigit() and int(branch_id_raw) != current_id)
        ):
            return jsonify({"ok": False, "error": "لا يمكنك تصدير مخزون فرع آخر."}), 403
        branch_id_raw = str(current_id)
        all_branches = False
    branch = None
    if not all_branches:
        if not branch_id_raw.isdigit():
            return jsonify({"ok": False, "error": "يرجى اختيار فرع صحيح."}), 400
        branch = Branch.query.filter_by(id=int(branch_id_raw), is_active=True).first()
        if not branch:
            return jsonify({"ok": False, "error": "الفرع غير موجود أو غير نشط."}), 404

    output, scope = _build_inventory_audit_workbook(branch, all_branches=all_branches)
    suffix = "all_branches" if all_branches else _safe_xlsx_filename(scope)
    filename = f"inventory_audit_{suffix}_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx"
    return send_file(
        output,
        as_attachment=True,
        download_name=filename,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@inventory_bp.route("/audit-ai-upload", methods=["POST"])
def upload_inventory_audit_to_ai():
    if not check_permission("can_manage_inventory"):
        return jsonify({"success": False, "error": "غير مصرح"}), 403

    try:
        from utils.ai_assistant_service import (
            build_inventory_reconcile_plan,
            ensure_ai_assistant_schema,
            save_uploaded_file,
        )

        ensure_ai_assistant_schema()
        uploaded = save_uploaded_file(
            request.files.get("file"),
            employee_id=session.get("user_id"),
            session_id=None,
        )
        if uploaded.status != "parsed":
            db.session.commit()
            return jsonify(
                {
                    "success": False,
                    "error": uploaded.error_message or "تعذر قراءة ملف الجرد",
                    "file": {
                        "id": uploaded.id,
                        "original_name": uploaded.original_name,
                        "status": uploaded.status,
                        "preview": uploaded.get_preview(),
                    },
                }
            ), 400

        plan, meta = build_inventory_reconcile_plan(
            [uploaded.id],
            employee_id=session.get("user_id"),
            session_id=None,
        )
        db.session.commit()
        return jsonify(
            {
                "success": True,
                "file": {
                    "id": uploaded.id,
                    "original_name": uploaded.original_name,
                    "status": uploaded.status,
                    "preview": uploaded.get_preview(),
                },
                "plan": plan.to_dict() if plan else None,
                "meta": meta,
                "assistant_url": "/assistant/chat",
            }
        )
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "error": str(e)}), 400


def _inventory_snapshot():
    """Products visible in the current branch scope with their displayed quantities.

    Single source for the inventory page and the JSON product list (same branch,
    shared-catalog and colour-stock rules)."""
    products = _visible_inventory_products(Product.query.all())
    shared_catalog_members: dict[int, list[int]] = {}
    if not independent_branches_enabled():
        products, shared_catalog_members = _collapse_shared_inventory_products(products)
    # Shared-mode companies have one catalogue, but their physical stock may
    # be distributed across several branches.  The default dashboard branch
    # must not make those other quantities disappear from the inventory page.
    view_all = getattr(g, "view_all_branches", False) or not independent_branches_enabled()
    branch_id = _inventory_branch_id()
    product_branch_stock_map = _product_branch_stock_map(products, shared_catalog_members)
    if not independent_branches_enabled():
        stock_map = {
            product.id: sum(product_branch_stock_map.get(product.id, {}).values())
            for product in products
        }
    else:
        stock_map = branch_stock_map(None if view_all else branch_id)
    branch_scope_label = (
        "كل الفروع (نظام مشترك)"
        if not independent_branches_enabled()
        else ("كل الفروع" if view_all else (g.branch.name if getattr(g, "branch", None) else "—"))
    )

    # إحصائيات محسّنة (معالجة آمنة لـ None)
    def _val(v, default=0):
        return default if v is None else v

    def _qty(p):
        return _product_display_qty(p, stock_map, view_all)

    product_display_qty_map = {int(p.id): _qty(p) for p in products}
    base_stock_map = dict(stock_map)  # quantities before colour balances (page totals use these)
    company_branches = _company_branches_for_form()
    product_branch_map = _product_branch_map(products, company_branches)
    product_branch_colors_map = _product_branch_colors_map(products, company_branches)
    # Color rows are authoritative for color-managed products.  Feed their
    # totals to the table and quick editor so a stale BranchStock row cannot
    # produce two different quantities on the same page.
    for product in products:
        color_by_branch = product_branch_colors_map.get(int(product.id), {})
        if not color_by_branch:
            continue
        branch_totals = {
            int(bid): sum(int(row.get("qty") or 0) for row in rows)
            for bid, rows in color_by_branch.items()
        }
        product_branch_stock_map[int(product.id)] = branch_totals
        effective_qty = (
            sum(branch_totals.values())
            if view_all
            else int(branch_totals.get(int(branch_id or 0), 0))
        )
        stock_map[int(product.id)] = effective_qty
        product_display_qty_map[int(product.id)] = effective_qty
    return {
        "products": products,
        "stock_map": stock_map,
        "base_stock_map": base_stock_map,
        "product_display_qty_map": product_display_qty_map,
        "product_branch_stock_map": product_branch_stock_map,
        "product_branch_map": product_branch_map,
        "product_branch_colors_map": product_branch_colors_map,
        "company_branches": company_branches,
        "view_all": view_all,
        "branch_scope_label": branch_scope_label,
    }


@inventory_bp.route("/", methods=["GET", "POST"])
def inventory():
    # فحص الصلاحية
    if not check_permission("can_manage_inventory"):
        return redirect("/pos"), 403

    ensure_product_schema()

    # ==========================
    # ADD PRODUCT (NO SUPPLIER)
    # ==========================
    if request.method == "POST" and request.form.get("form_type") == "add_product":
        write_branch_id = resolve_write_branch_id(request.form)
        opening_stock = int(request.form.get("opening_stock", 0) or 0)
        buy_price = int(request.form.get("buy_price", 0) or 0)
        barcode = request.form.get("barcode", "").strip() or None
        if barcode_conflict(write_branch_id, barcode):
            flash("الباركود مستخدم لمنتج آخر في هذا الفرع.", "error")
            return redirect(url_for("inventory.inventory"))
        opening_stock_value = opening_stock * buy_price  # قيمة المخزون الافتتاحي
        
        p = Product(
            branch_id=write_branch_id,
            name=request.form["name"],
            barcode=barcode,
            buy_price=buy_price,
            sale_price=int(request.form["sale_price"]),
            exchange_sale_price=(
                max(0, int(request.form.get("exchange_sale_price") or 0)) or None
                if tenant_feature_enabled("trade_in_sales", default=False)
                else None
            ),
            shipping_cost=0,  # إلغاء الحقل
            marketing_cost=0,  # إلغاء الحقل
            opening_stock=opening_stock,
            quantity=opening_stock,  # الكمية تساوي المخزون الافتتاحي بالبداية
            active=True
        )
        db.session.add(p)
        db.session.flush()
        branch_id = write_branch_id
        if branch_id:
            set_opening_branch_stock(branch_id, p.id, opening_stock)
        
        # ==========================
        # تصحيح محاسبي: المخزون الافتtاحي لا يُسجل كحركة مالية
        # السبب المحاسبي:
        # - المخزون الافتتاحي يُعتبر قيمة مخزون فقط (Asset)
        # - لا يؤثر على الرصيد المالي (Cash/Balance)
        # - لا يظهر في صفحة الحسابات أو سجل الحركات المالية
        # - لا يُعتبر إيداع مالي أو حركة حسابات
        # ==========================
        # تم إزالة إنشاء AccountTransaction للمخزون الافتتاحي
        # المخزون الافتتاحي يُسجل في Product.opening_stock و Product.quantity فقط
        
        db.session.commit()
        return redirect(url_for("inventory.inventory"))

    # ==========================
    # PURCHASE - تم نقله إلى /purchases
    # تم نقل منطق الشراء إلى صفحة purchases منفصلة
    # ==========================

    # ==============================
    # DISPLAY DATA
    # ==============================
    snapshot = _inventory_snapshot()
    products = snapshot["products"]
    stock_map = snapshot["stock_map"]
    product_display_qty_map = snapshot["product_display_qty_map"]
    product_branch_stock_map = snapshot["product_branch_stock_map"]
    product_branch_map = snapshot["product_branch_map"]
    product_branch_colors_map = snapshot["product_branch_colors_map"]
    company_branches = snapshot["company_branches"]
    view_all = snapshot["view_all"]
    branch_scope_label = snapshot["branch_scope_label"]

    def _val(v, default=0):
        return default if v is None else v

    def _qty(p):
        return _product_display_qty(p, snapshot["base_stock_map"], view_all)

    total_purchase = sum(_val(p.buy_price) * _qty(p) for p in products)
    total_sale = sum(_val(p.sale_price) * _qty(p) for p in products)
    total_profit = total_sale - total_purchase

    current_inventory_value = sum(_val(p.buy_price) * _qty(p) for p in products)

    expected_profit_from_stock = sum(
        (_val(p.sale_price) - _val(p.buy_price)) * _qty(p)
        for p in products
    )
    
    low_stock_products = [p for p in products if _qty(p) <= _val(p.low_stock_threshold, 5)]
    low_stock_count = len(low_stock_products)
    
    # المنتجات غير المباعة (quantity > 0 لكن لم تُباع)
    products_with_sales = set()
    from models.order_item import OrderItem
    sold_products = db.session.query(OrderItem.product_id).distinct().all()
    products_with_sales = {p[0] for p in sold_products}
    unsold_products = [p for p in products if _qty(p) > 0 and p.id not in products_with_sales]
    unsold_count = len(unsold_products)
    
    # المنتجات النشطة وغير النشطة
    active_count = sum(1 for p in products if p.active)
    inactive_count = len(products) - active_count
    return render_template(
        "inventory.html",
        products=products,
        total_purchase=total_purchase,
        total_sale=total_sale,
        total_profit=total_profit,
        current_inventory_value=current_inventory_value,
        expected_profit_from_stock=expected_profit_from_stock,
        low_stock_count=low_stock_count,
        low_stock_products=low_stock_products,
        unsold_count=unsold_count,
        unsold_products=unsold_products[:10],  # أول 10 منتجات غير مباعة
        active_count=active_count,
        inactive_count=inactive_count,
        branch_scope_label=branch_scope_label,
        branch_stock_map=stock_map,
        product_display_qty_map=product_display_qty_map,
        view_all_branches=view_all,
        company_branches=company_branches,
        product_branch_map=product_branch_map,
        product_branch_stock_map=product_branch_stock_map,
        product_branch_colors_map=product_branch_colors_map,
        inventory_edit_prices=check_permission("edit_price"),
        inventory_trade_in=tenant_feature_enabled("trade_in_sales", default=False),
    )


# ======================================
# Add Product — صفحة مخصصة (نموذج متقدم)
# ======================================
@inventory_bp.route("/add", methods=["GET", "POST"])
@inventory_bp.route("/add/", methods=["GET", "POST"])
def add_product_page():
    if not check_permission("can_manage_inventory"):
        return redirect("/pos"), 403
    ensure_product_schema()
    # API clients (desktop) post the same form and get JSON instead of a page/redirect.
    json_reply = request.method == "POST" and request.form.get("_response") == "json"
    if request.method == "POST":
        name = (request.form.get("name") or "").strip()
        if json_reply and (request.form.get("edit_product_id") or "").strip():
            return jsonify({"success": False, "error": "التعديل يتم عبر /inventory/api/products/<id>/update"}), 400
        if not name and json_reply:
            return jsonify({"success": False, "error": "يرجى إدخال اسم المنتج."}), 400
        if not name:
            ctx = _inventory_add_summary()
            ctx["error"] = "يرجى إدخال اسم المنتج."
            ctx["edit_product"] = None
            ctx["product_meta"] = {}
            ctx["product_specs_items"] = []
            by_prov, def_fee = delivery_fees_from_form(request.form)
            ctx.update({"delivery_by_province": by_prov, "delivery_default_fee": def_fee})
            eid = (request.form.get("edit_product_id") or "").strip()
            if eid.isdigit():
                ep = Product.query.get(int(eid))
                if ep:
                    ctx["edit_product"] = ep
                    ctx["product_meta"] = _load_product_meta(ep)
                    ctx["product_specs_items"] = _extract_specs_items(ctx["product_meta"])
            return render_template("inventory_add_product.html", **ctx), 400

        if json_reply:
            try:
                for field in ("opening_stock", "buy_price", "sale_price", "low_stock_threshold"):
                    raw_number = request.form.get(field)
                    if raw_number is not None and int(raw_number or 0) < 0:
                        raise ValueError(field)
                for field in ("color_qty[]", "color_buy_price[]", "color_sale_price[]"):
                    for raw_number in request.form.getlist(field):
                        if int(raw_number or 0) < 0:
                            raise ValueError(field)
                if request.form.get("has_colors"):
                    names = [name.strip().casefold() for name in request.form.getlist("color_name[]")]
                    if not names or len(names) > 40 or any(not name or len(name) > 80 for name in names) or len(set(names)) != len(names):
                        return jsonify(success=False, error="راجع أسماء الألوان؛ لا يمكن ترك الاسم فارغاً أو تكراره"), 400
                for field in ("pos_visible", "store_visible"):
                    if field in request.form and request.form.get(field) not in {"0", "1"}:
                        raise ValueError(field)
                raw_exchange_price = int(request.form.get("exchange_sale_price") or 0)
                if raw_exchange_price < 0:
                    raise ValueError("exchange_sale_price")
            except ValueError:
                return jsonify(success=False, error="الأسعار والكميات يجب أن تكون أعداداً صحيحة غير سالبة، وإعداد الظهور يجب أن يكون صحيحاً"), 400
            if raw_exchange_price and not tenant_feature_enabled("trade_in_sales", default=False):
                return jsonify(success=False, error="ميزة الاستبدال غير مفعّلة لهذه الشركة"), 400

        opening_stock = int(request.form.get("opening_stock", 0) or 0)
        has_colors_flag = bool(request.form.get("has_colors"))
        if has_colors_flag:
            opening_stock = sum(int(r.get("qty") or 0) for r in _color_rows_from_form(request.form))
        buy_price = int(request.form.get("buy_price", 0) or 0)
        sale_price = int(request.form.get("sale_price", 0) or 0)
        trade_in_enabled = tenant_feature_enabled("trade_in_sales", default=False)
        exchange_sale_price = (
            max(0, int(request.form.get("exchange_sale_price", 0) or 0)) or None
            if trade_in_enabled
            else None
        )
        dual_region = bool(request.form.get("dual_region_pricing"))
        governorate_sale_price = None
        if dual_region:
            gov_raw = (request.form.get("governorate_sale_price") or "").strip()
            if gov_raw != "":
                governorate_sale_price = max(0, int(gov_raw or 0)) or None
        barcode = (request.form.get("barcode") or "").strip() or None
        sku = (request.form.get("sku") or "").strip() or None
        not_for_sale_flag = bool(request.form.get("not_for_sale"))
        low_stock_threshold = int(request.form.get("low_stock_threshold", 5) or 5)
        description = (request.form.get("description") or "").strip() or None
        skin_type = (request.form.get("skin_type") or "").strip() or None
        usage_type = (request.form.get("usage_type") or "").strip() or None
        requires_patch_test = bool(request.form.get("requires_patch_test"))
        expiry_date = _parse_optional_date(request.form.get("expiry_date"))
        opened_date = _parse_optional_date(request.form.get("opened_date"))
        batch_number = (request.form.get("batch_number") or "").strip() or None

        meta = _meta_from_inventory_add_form(request.form)
        meta = _apply_product_media_uploads(meta, request.form, request.files)

        edit_raw = (request.form.get("edit_product_id") or "").strip()
        edit_id = int(edit_raw) if edit_raw.isdigit() else None

        image_url = _save_uploaded_product_image(request.files.get("product_image"))

        if edit_id:
            p = Product.query.get(edit_id)
            if not p:
                ctx = _inventory_add_summary()
                ctx["error"] = "المنتج غير موجود للتعديل."
                ctx["edit_product"] = None
                ctx["product_meta"] = {}
                ctx["product_specs_items"] = []
                return render_template("inventory_add_product.html", **ctx), 404

            before_product = snapshot_attrs(p, *PRODUCT_SNAPSHOT_FIELDS)
            if barcode_conflict(p.branch_id, barcode, exclude_product_id=p.id):
                flash("الباركود مستخدم لمنتج آخر في هذا الفرع.", "error")
                return redirect(url_for("inventory.add_product_page", edit=p.id))
            old_buy_price = p.buy_price
            old_name = p.name
            if "product_options" in request.form:
                lock_color_product(p)
                has_colors_flag = True
            original_current_stock = _edit_current_stock_for_product(p, _load_product_meta(p))
            previous_options = option_config(p)
            if previous_options.get("axes"):
                meta["product_options"] = previous_options
                meta["has_colors"] = True
                has_colors_flag = True

            p.name = name
            p.sku = sku
            p.barcode = barcode
            p.buy_price = buy_price
            p.sale_price = sale_price
            if trade_in_enabled:
                p.exchange_sale_price = exchange_sale_price
            p.governorate_sale_price = governorate_sale_price
            p.low_stock_threshold = max(0, low_stock_threshold)
            p.description = description
            p.skin_type = skin_type
            p.usage_type = usage_type
            p.requires_patch_test = requires_patch_test
            p.expiry_date = expiry_date
            p.opened_date = opened_date
            p.batch_number = batch_number
            p.shipping_cost = max(0, int(meta.get("delivery_default_fee") or 0))
            p.marketing_cost = 0
            p.active = not not_for_sale_flag
            # لا تلمس الظهور في المتجر عند حفظ الوسائط/التعديل — يُغيَّر فقط من زر العين
            if getattr(p, "store_visible", None) is None:
                p.store_visible = True
            if getattr(p, "pos_visible", None) is None:
                p.pos_visible = True

            if image_url:
                p.image_url = image_url

            if "current_stock" in request.form and not has_colors_flag:
                new_qty = max(0, int(request.form.get("current_stock") or 0))
                stock_branch_id = _branch_id_for_product_stock(request.form, meta)
                if stock_branch_id:
                    set_branch_stock(stock_branch_id, p.id, new_qty)
                else:
                    p.quantity = new_qty

            p.meta_json = json.dumps(meta, ensure_ascii=False) if meta else None
            db.session.flush()
            if "product_options" in request.form:
                try:
                    lock_color_product(p)
                    apply_product_options(p, request.form.get("product_options"),
                                          current_stock=original_current_stock,
                                          can_edit_price=check_permission("edit_price"))
                    has_colors_flag = True
                except (ProductColorError, IntegrityError) as exc:
                    db.session.rollback()
                    flash(str(exc) if isinstance(exc, ProductColorError) else "المخزون محجوز للأوفلاين؛ أعد تحميل المنتج", "error")
                    return redirect(url_for("inventory.add_product_page", edit=p.id))
            color_total = _apply_product_colors_from_form(p, request.form)
            if has_colors_flag:
                p.quantity = color_total
                stock_branch_id = _branch_id_for_product_stock(request.form, meta)
                if stock_branch_id:
                    set_branch_stock(stock_branch_id, p.id, color_total)
            if name != old_name:
                sync_product_name_to_order_items(p.id, name)
            created_color_files = []
            try:
                if "color_images" in request.form:
                    apply_color_images(p, request.form.get("color_images"), request.files, created_color_files)
                db.session.commit()
            except (ProductColorError, OSError, SQLAlchemyError) as exc:
                db.session.rollback()
                cleanup_color_uploads(created_color_files)
                current_app.logger.exception("web product options save failed")
                flash(str(exc) if isinstance(exc, ProductColorError) else "تعذّر حفظ الخيارات؛ لم تُحفظ التعديلات", "error")
                return redirect(url_for("inventory.add_product_page", edit=p.id))
            try:
                log_mutation(
                    "update",
                    "inventory",
                    "product",
                    p.id,
                    before_product,
                    snapshot_attrs(p, *PRODUCT_SNAPSHOT_FIELDS),
                    f"تعديل منتج: {p.name}",
                )
            except Exception:
                pass

            action = (request.form.get("submit_action") or "save").strip()
            if action == "add_another":
                return redirect(url_for("inventory.add_product_page"))
            return redirect(url_for("inventory.inventory"))

        write_branch_id = resolve_write_branch_id(request.form)
        if barcode_conflict(write_branch_id, barcode):
            if json_reply:
                return jsonify({"success": False, "error": "الباركود مستخدم لمنتج آخر في هذا الفرع."}), 409
            flash("الباركود مستخدم لمنتج آخر في هذا الفرع.", "error")
            return redirect(url_for("inventory.add_product_page"))
        p = Product(
            branch_id=write_branch_id,
            name=name,
            sku=sku,
            barcode=barcode,
            buy_price=buy_price,
            sale_price=sale_price,
            exchange_sale_price=exchange_sale_price,
            governorate_sale_price=governorate_sale_price,
            shipping_cost=max(0, int(meta.get("delivery_default_fee") or 0)),
            marketing_cost=0,
            opening_stock=opening_stock,
            quantity=opening_stock,
            active=not not_for_sale_flag,
            pos_visible=request.form.get("pos_visible", "1") != "0" if json_reply else True,
            store_visible=request.form.get("store_visible", "1") != "0" if json_reply else True,
            low_stock_threshold=max(0, low_stock_threshold),
            description=description,
            image_url=image_url,
            skin_type=skin_type,
            usage_type=usage_type,
            requires_patch_test=requires_patch_test,
            expiry_date=expiry_date,
            opened_date=opened_date,
            batch_number=batch_number,
            meta_json=json.dumps(meta, ensure_ascii=False) if meta else None,
        )
        db.session.add(p)
        db.session.flush()
        stock_branch_id = _branch_id_for_product_stock(request.form, meta)
        if has_colors_flag:
            color_total = _apply_product_colors_from_form(p, request.form)
            p.opening_stock = color_total
            p.quantity = color_total
            if stock_branch_id:
                set_opening_branch_stock(stock_branch_id, p.id, color_total)
        elif stock_branch_id:
            set_opening_branch_stock(stock_branch_id, p.id, opening_stock)
        created_color_files = []
        try:
            if "product_options" in request.form:
                apply_product_options(p, request.form.get("product_options"), creating=True)
                p.opening_stock = int(p.quantity or 0)
                if stock_branch_id:
                    set_opening_branch_stock(stock_branch_id, p.id, p.opening_stock)
            if "color_images" in request.form:
                apply_color_images(p, request.form.get("color_images"), request.files, created_color_files)
            if json_reply and request.form.get("store_visible") == "1":
                _sync_inventory_storefront([p.id], True)
            db.session.commit()
            _refresh_storefront()
        except (ProductColorError, OSError, SQLAlchemyError) as exc:
            db.session.rollback()
            cleanup_color_uploads(created_color_files)
            if isinstance(exc, ProductColorError):
                return jsonify(success=False, error=str(exc)), 400
            current_app.logger.exception("product color photo save failed")
            return jsonify(success=False, error="تعذّر حفظ المنتج؛ لم تُحفظ التعديلات. حاول مجدداً"), 500
        try:
            log_activity(
                "create",
                "inventory",
                f"إضافة منتج: {p.name}",
                entity_type="product",
                entity_id=p.id,
                payload={"product": snapshot_attrs(p, *PRODUCT_SNAPSHOT_FIELDS)},
            )
        except Exception:
            pass
        if json_reply:
            return jsonify({"success": True, "product_id": p.id, "name": p.name})
        action = (request.form.get("submit_action") or "save").strip()
        if action == "add_another":
            return redirect(url_for("inventory.add_product_page"))
        # save | opening | group_prices → العودة لقائمة المخزون
        return redirect(url_for("inventory.inventory"))

    ctx = _inventory_add_summary()
    ctx["edit_product"] = None
    ctx["edit_current_stock"] = 0
    ctx["product_meta"] = {}
    ctx["product_specs_items"] = []
    ctx["product_color_rows"] = []
    ctx["product_option_rows"] = []
    ctx.update(_delivery_fees_context())
    edit_arg = request.args.get("edit", type=int)
    if edit_arg:
        ep = Product.query.get(edit_arg)
        if ep:
            ctx["edit_product"] = ep
            ctx["product_meta"] = _load_product_meta(ep)
            ctx["edit_current_stock"] = _edit_current_stock_for_product(ep, ctx["product_meta"])
            ctx["product_option_rows"] = local_color_rows(ep.id)
            ctx["product_specs_items"] = _extract_specs_items(ctx["product_meta"])
            color_branch_id = int(ep.branch_id or 0) or _branch_id_for_product_stock(
                meta=ctx["product_meta"]
            )
            ctx["product_color_rows"] = (
                get_branch_product_colors(ep.id, color_branch_id)
                if color_branch_id
                else []
            )
            ctx.update(_delivery_fees_context(ep, ctx["product_meta"]))
        else:
            ctx["error"] = "المنتج غير موجود."
    return render_template("inventory_add_product.html", **ctx)


# ======================================
# Add Supplier
# ======================================
@inventory_bp.route("/audit", methods=["GET"])
def audit():
    return redirect(url_for("inventory.smart_audit_app"))


@inventory_bp.route("/save-audit", methods=["POST"])
def save_audit():
    # A stale browser tab must not bypass review/approval or turn a non-cash
    # inventory variance into an old deposit/withdrawal transaction.
    if not check_permission("can_manage_inventory"):
        return jsonify(success=False,error="ليست لديك صلاحية الجرد"),403
    return jsonify(success=False,code="audit_workflow_required",
        error="الجرد يحتاج جلسة ومراجعة واعتماد؛ افتح صفحة الجرد المحدثة",next_url=url_for("inventory.smart_audit_app")),409

# ======================================
@inventory_bp.route("/add-supplier", methods=["POST"])
def add_supplier():
    supplier = Supplier(
        name=request.form["name"],
        phone=request.form.get("phone"),
        address=request.form.get("address")
    )
    db.session.add(supplier)
    db.session.commit()
    return redirect(url_for("inventory.inventory"))


# ======================================
# Toggle Product
# ======================================
@inventory_bp.route("/toggle/<int:id>", methods=["POST", "GET"])
def toggle_product(id):
    if not check_permission("can_manage_inventory"):
        return redirect("/pos"), 403
    # ارفض GET القادم من prefetch/الزواحف حتى لا يُقلَب الحالة بالخطأ
    if request.method != "POST":
        flash("لتغيير حالة المنتج استخدم زر القائمة (POST).", "warning")
        return redirect(url_for("inventory.inventory"))

    p = Product.query.get_or_404(id)
    p.active = not p.active
    db.session.commit()
    return redirect(url_for("inventory.inventory"))


@inventory_bp.route("/toggle-store/<int:id>", methods=["POST", "GET"])
def toggle_product_store_visibility(id):
    if not check_permission("can_manage_inventory"):
        return redirect("/pos"), 403
    # GET على روابط العين كان يقلّب الظهور بعد حفظ الصور بسبب prefetch المتصفح
    if request.method != "POST":
        flash("لإظهار/إخفاء المنتج من المتجر استخدم زر العين في القائمة.", "warning")
        return redirect(url_for("inventory.inventory"))

    p = Product.query.get_or_404(id)
    targets = _apply_catalog_visibility(p, "store_visible", not bool(p.store_visible))
    _sync_inventory_storefront(targets, bool(p.store_visible))
    db.session.commit()
    _refresh_storefront()
    flash(
        "تم إظهار المنتج في المتجر." if p.store_visible else "تم إخفاء المنتج من المتجر.",
        "success",
    )
    return redirect(url_for("inventory.inventory"))


def _apply_pos_visible(product: Product, visible: bool) -> list[int]:
    """Set POS visibility on the product and any shared-catalog siblings."""
    return _apply_catalog_visibility(product, "pos_visible", visible)


def _refresh_storefront() -> None:
    """A product edit (visibility, price, name…) shows in the online store at once, not after its caches expire."""
    try:
        from modules.search import engine
        from modules.storefront.services.catalog_service import invalidate_catalog_cache
        from routes import storefront as storefront_routes

        slug = str(getattr(g, "tenant", "") or "")
        invalidate_catalog_cache(slug or None)
        engine.invalidate(slug or None)
        storefront_routes._PAGE_CACHE.clear()
    except Exception:
        current_app.logger.exception("storefront cache refresh failed")


def _sync_inventory_storefront(product_ids: list[int], visible: bool) -> None:
    from modules.store_api.services.control import sync_product_publication

    for product_id in product_ids:
        product = db.session.get(Product, product_id)
        if product is not None:
            sync_product_publication(product, visible=visible)


def _inventory_storefront_state(product: Product) -> dict:
    """Report effective public visibility, rather than only the inventory flag."""
    from modules.storefront.services.catalog_service import cash_store_product_is_visible
    from modules.installments.models import InstallmentProduct

    linked = InstallmentProduct.query.filter_by(product_id=product.id).first()
    default = get_default_branch()
    other_branch = bool(independent_branches_enabled() and default and product.branch_id != default.id)
    can_publish = bool(product.active and product.store_visible is not False and not other_branch
                       and not cash_store_product_is_visible(product))
    if not product.active:
        status, message = "inactive", "غير ظاهر فعلياً: المنتج غير متاح للبيع."
    elif product.store_visible is False:
        status, message = "hidden", "المنتج مخفي من المتجر."
    elif other_branch:
        status, message = "other_branch", "غير ظاهر في المتجر العام: المنتج تابع لفرع آخر؛ المتجر يعرض الفرع الرئيسي."
    elif not cash_store_product_is_visible(product):
        status, message = "unpublished", "غير منشور فعلياً: تفعيل الظهور وحده لم يربط المنتج بكاتالوگ المتجر. اضغط نشر ثم احفظ."
    else:
        status, message = "published", "ظاهر فعلياً في المتجر."
    return {"status": status, "message": message, "can_publish": can_publish,
            "catalog_status": linked.status if linked else None}


def _apply_catalog_visibility(product: Product, field: str, visible: bool) -> list[int]:
    assert field in {"pos_visible", "store_visible"}
    targets = [product]
    group_id = str(getattr(product, "catalog_group_id", "") or "").strip()
    if group_id and not independent_branches_enabled():
        siblings = (
            Product.query.filter(Product.catalog_group_id == group_id)
            .execution_options(skip_branch_scope=True)
            .all()
        )
        if siblings:
            targets = siblings
    updated_ids: list[int] = []
    for row in targets:
        setattr(row, field, bool(visible))
        updated_ids.append(int(row.id))
    return updated_ids


@inventory_bp.route("/toggle-pos/<int:id>", methods=["POST", "GET"])
def toggle_product_pos_visibility(id):
    if not check_permission("can_manage_inventory"):
        return redirect("/pos"), 403
    if request.method != "POST":
        flash("لإظهار/إخفاء المنتج من نقطة البيع استخدم زر القائمة.", "warning")
        return redirect(url_for("inventory.inventory"))

    p = Product.query.get_or_404(id)
    new_visible = not bool(getattr(p, "pos_visible", True))
    _apply_pos_visible(p, new_visible)
    db.session.commit()
    flash(
        "تم إظهار المنتج في نقطة البيع." if new_visible else "تم إخفاء المنتج من نقطة البيع.",
        "success",
    )
    return redirect(url_for("inventory.inventory"))


@inventory_bp.route("/bulk-pos-visibility", methods=["POST"])
def bulk_pos_visibility():
    """إخفاء/إظهار منتجات متعددة من نقطة البيع (تحديد الكل أو تحديد جزئي)."""
    if not check_permission("can_manage_inventory"):
        return jsonify({"success": False, "error": "غير مصرح"}), 403

    payload = request.get_json(silent=True) or {}
    raw_ids = payload.get("ids") if "ids" in payload else payload.get("product_ids")
    if not isinstance(raw_ids, list) or not raw_ids:
        return jsonify({"success": False, "error": "أرسل قائمة ids"}), 400

    visible = bool(payload.get("pos_visible", payload.get("visible", True)))
    updated: list[int] = []
    seen: set[int] = set()
    for raw in raw_ids[:500]:
        try:
            product_id = int(raw)
        except (TypeError, ValueError):
            continue
        if product_id <= 0 or product_id in seen:
            continue
        product = Product.query.get(product_id)
        if not product:
            continue
        for touched_id in _apply_pos_visible(product, visible):
            if touched_id not in seen:
                seen.add(touched_id)
                updated.append(touched_id)

    db.session.commit()
    return jsonify({
        "success": True,
        "updated": updated,
        "count": len(updated),
        "pos_visible": visible,
    })


# ======================================
# Delete Product
# ======================================
@inventory_bp.route("/delete/<int:id>")
def delete_product(id):
    if not check_permission("can_manage_inventory"):
        return redirect("/pos"), 403

    p = Product.query.get(id)
    if not p:
        flash("المنتج غير موجود أو تم حذفه مسبقاً.", "warning")
        return redirect(url_for("inventory.inventory"))

    try:
        from models.branch import BranchStock, StockTransferLine
        from models.beauty_service_product import BeautyServiceProduct
        from models.maintenance_record import MaintenanceRecord
        from models.purchase import Purchase
        from models.purchase_item import PurchaseItem

        product_id = p.id

        def has_product_link(model):
            try:
                return (
                    db.session.query(model.id)
                    .filter(model.product_id == product_id)
                    .first()
                    is not None
                )
            except SQLAlchemyError:
                db.session.rollback()
                current_app.logger.warning(
                    "Skipping product link check for %s",
                    getattr(model, "__tablename__", model.__name__),
                    exc_info=True,
                )
                return False

        linked_models = (
            OrderItem,
            Purchase,
            PurchaseItem,
            StockTransferLine,
            MaintenanceRecord,
            BeautyServiceProduct,
        )
        has_history = any(has_product_link(model) for model in linked_models)

        if has_history:
            p.active = False
            flash_message = "تم إخفاء المنتج من البيع والمتجر بدلاً من حذفه لأنه مرتبط بسجلات سابقة."
            flash_category = "warning"
        else:
            BranchStock.query.filter_by(product_id=product_id).delete(synchronize_session=False)
            db.session.delete(p)
            flash_message = "تم حذف المنتج بنجاح."
            flash_category = "success"
        try:
            db.session.commit()
            flash(flash_message, flash_category)
        except IntegrityError:
            db.session.rollback()
            p = Product.query.get_or_404(id)
            p.active = False
            db.session.commit()
            flash("تم إخفاء المنتج من البيع والمتجر لأنه مرتبط بسجلات أخرى.", "warning")
    except Exception as exc:
        db.session.rollback()
        current_app.logger.exception("delete_product failed")
        flash(f"تعذر حذف المنتج: {exc}", "error")
    return redirect(url_for("inventory.inventory"))


# ======================================
# Edit Product
# ======================================
@inventory_bp.route("/edit/<int:id>", methods=["POST"])
def edit_product(id):
    p = Product.query.get_or_404(id)
    meta = _load_product_meta(p)

    # حفظ القيم القديمة قبل التحديث
    old_name = p.name

    p.name = request.form["name"]
    p.sku = request.form.get("sku", "").strip() or None
    new_barcode = request.form.get("barcode", "").strip() or None
    if barcode_conflict(p.branch_id, new_barcode, exclude_product_id=p.id):
        flash("الباركود مستخدم لمنتج آخر في هذا الفرع.", "error")
        return redirect(url_for("inventory.inventory"))
    p.barcode = new_barcode
    p.buy_price = int(request.form["buy_price"])
    p.sale_price = int(request.form["sale_price"])
    if tenant_feature_enabled("trade_in_sales", default=False):
        p.exchange_sale_price = (
            max(0, int(request.form.get("exchange_sale_price") or 0)) or None
        )
    dual_region = bool(request.form.get("dual_region_pricing"))
    from utils.product_region_pricing import set_dual_region_pricing_flag

    meta = set_dual_region_pricing_flag(meta, dual_region)
    if dual_region:
        gov_raw = (request.form.get("governorate_sale_price") or "").strip()
        p.governorate_sale_price = max(0, int(gov_raw or 0)) or None if gov_raw != "" else None
    else:
        p.governorate_sale_price = None
    p.low_stock_threshold = int(request.form.get("low_stock_threshold", 5) or 5)
    p.shipping_cost = 0  # إلغاء الحقل
    p.marketing_cost = 0  # إلغاء الحقل
    p.description = request.form.get("description", "").strip() or None
    p.image_url = request.form.get("image_url", "").strip() or None

    video_url = request.form.get("video_url", "").strip()
    gallery_urls = _split_multiline_values(request.form.get("gallery_urls"))
    specs_items = _specs_items_from_form(request.form)
    store_badge = request.form.get("store_badge", "").strip()

    for key, value in (
        ("video_url", video_url),
        ("store_badge", store_badge),
    ):
        if value:
            meta[key] = value
        else:
            meta.pop(key, None)
    if specs_items:
        meta["specs_items"] = specs_items
    else:
        meta.pop("specs_items", None)
        meta.pop("specs_text", None)
    if gallery_urls:
        meta["gallery"] = gallery_urls
    else:
        meta.pop("gallery", None)
    p.meta_json = json.dumps(meta, ensure_ascii=False) if meta else None
    
    # تحديث المخزون الحالي إذا تم توفيره (لا نعدّل المخزون الافتتاحي)
    if "current_stock" in request.form:
        if product_has_colors(p):
            flash("مخزون المنتج الملوّن يُعدّل حسب اللون من التعديل السريع أو صفحة المنتج.", "warning")
        else:
            new_qty = max(0, int(request.form["current_stock"]) if request.form["current_stock"] else 0)
            branch_id = int(p.branch_id or 0) or resolve_write_branch_id(request.form)
            if branch_id:
                set_branch_stock(branch_id, p.id, new_qty)
            else:
                p.quantity = new_qty

    if p.name != old_name:
        sync_product_name_to_order_items(p.id, p.name)
        
    db.session.commit()
    return redirect(url_for("inventory.inventory"))


# ======================================
# Update Opening Stock
# ======================================
@inventory_bp.route("/update-opening-stock/<int:id>", methods=["POST"])
def update_opening_stock(id):
    """تحديث المخزون الافتتاحي"""
    if not check_permission("can_manage_inventory"):
        return redirect("/pos"), 403
    
    product = Product.query.get_or_404(id)
    data = request.get_json() or request.form
    
    try:
        opening_stock = int(data.get("opening_stock", 0))
        product.opening_stock = opening_stock
        db.session.commit()
        return jsonify({"success": True, "message": "تم تحديث المخزون الافتتاحي بنجاح"})
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "error": str(e)}), 400


# ======================================
# Adjust Stock / Quick Edit (تعديل سريع)
# ======================================
@inventory_bp.route("/adjust-stock/<int:id>", methods=["POST"])
def adjust_stock(id):
    """
    تعديل سريع: مخزون الفرع و/أو سعر البيع
    
    السبب المحاسبي:
    - كل حركة مخزون يجب أن تكون مرتبطة بسبب واضح
    - التعديل اليدوي يحتاج سبب لتتبع التغييرات
    - منع أي تغيير مباشر بدون تسجيل حركة
    """
    if not check_permission("can_manage_inventory"):
        return redirect("/pos"), 403
    
    product = Product.query.get_or_404(id)
    
    # الحصول على البيانات (JSON أو Form)
    if request.is_json:
        data = request.get_json()
    else:
        data = request.form.to_dict()
    
    try:
        adjustment_raw = str(data.get("adjustment", "") or "").strip()
        adjustment = int(adjustment_raw or 0)  # يمكن أن يكون موجب أو سالب
        reason = data.get("reason", "").strip()
        try:
            branch_id = _resolve_stock_adjust_branch_id(data)
        except PermissionError as exc:
            if request.is_json:
                return jsonify({"success": False, "error": str(exc)}), 403
            flash(str(exc), "error")
            return redirect(url_for("inventory.inventory"))
        except ValueError as exc:
            if request.is_json:
                return jsonify({"success": False, "error": str(exc)}), 400
            flash(str(exc), "error")
            return redirect(url_for("inventory.inventory"))

        # في الوضع المستقل كل منتج يتبع فرعاً واحداً. في الوضع المشترك
        # المخزون يُحفظ لكل فرع عبر BranchStock حتى لو كان المنتج على الفرع الرئيسي.
        if independent_branches_enabled() and int(product.branch_id or 0) != int(branch_id):
            return jsonify({"success": False, "error": "المنتج لا يتبع الفرع المختار"}), 403

        sale_price_raw = data.get("sale_price", None)
        price_changed = False
        old_sale_price = int(product.sale_price or 0)
        new_sale_price = old_sale_price
        if sale_price_raw is not None and str(sale_price_raw).strip() != "":
            new_sale_price = int(sale_price_raw)
            if new_sale_price < 0:
                raise ValueError("sale_price_negative")
            if new_sale_price != old_sale_price:
                product.sale_price = new_sale_price
                price_changed = True

        if adjustment == 0 and not price_changed:
            if request.is_json:
                return jsonify({
                    "success": False,
                    "error": "لم يتم إجراء أي تعديل. غيّر المخزون أو سعر البيع ثم احفظ.",
                }), 400
            from flask import flash
            flash("لم يتم إجراء أي تعديل. غيّر المخزون أو سعر البيع ثم احفظ.", "error")
            return redirect(url_for("inventory.inventory"))
        
        # التحقق من وجود السبب عند تغيير المخزون
        if adjustment != 0 and not reason:
            if request.is_json:
                return jsonify({
                    "success": False, 
                    "error": "يجب إدخال سبب التعديل (مثال: فحص جرد، تلف، خطأ في الإدخال)"
                }), 400
            else:
                # Form submission - redirect with error
                from flask import flash
                flash("يجب إدخال سبب التعديل", "error")
                return redirect(url_for("inventory.inventory"))
        
        current_qty = get_branch_stock(branch_id, product.id) if branch_id else (product.quantity or 0)
        color_name = str(data.get("color_name", "") or "").strip()
        color_managed = product_has_colors(product)
        local_colors = (
            get_branch_product_colors(product.id, branch_id)
            if branch_id and color_managed
            else []
        )
        if color_managed and adjustment != 0:
            if not local_colors:
                raise ProductColorError("لا توجد أرصدة ألوان لهذا المنتج في الفرع المختار. عرّف الألوان أولاً من تعديل المنتج")
            if adjustment != 0 and not color_name:
                raise ProductColorError("يجب اختيار اللون عند تعديل مخزون منتج ملوّن")
            selected_color = next((row for row in local_colors if row["name"] == color_name), None)
            if adjustment != 0 and not selected_color:
                raise ProductColorError("اللون المختار غير موجود في هذا الفرع")
            if selected_color:
                current_qty = int(selected_color.get("qty") or 0)
        if current_qty + adjustment < 0:
            if request.is_json:
                return jsonify({
                    "success": False, 
                    "error": f"المخزون لا يمكن أن يكون سالباً. المخزون الحالي: {current_qty}"
                }), 400
            else:
                from flask import flash
                flash(f"المخزون لا يمكن أن يكون سالباً. المخزون الحالي: {current_qty}", "error")
                return redirect(url_for("inventory.inventory"))
        
        # تطبيق التعديل
        old_quantity = current_qty
        new_quantity = current_qty
        if adjustment != 0:
            if color_managed:
                old_quantity, new_quantity, _branch_total = adjust_color_stock(
                    product.id,
                    color_name,
                    adjustment,
                    branch_id=branch_id,
                )
            elif branch_id:
                adjust_branch_stock(
                    branch_id,
                    product.id,
                    adjustment,
                    audit_context={
                        "source_type": "manual_adjustment",
                        "source_id": product.id,
                        "reason": reason,
                        "unit_cost": int(product.buy_price or 0),
                    },
                )
                new_quantity = get_branch_stock(branch_id, product.id)
            else:
                product.quantity += adjustment
                new_quantity = product.quantity
        
        db.session.commit()
        
        # تسجيل الحركة (للعرض فقط - لا نحفظها في قاعدة بيانات)
        # يمكن إضافة سجل حركات في المستقبل إذا لزم الأمر

        parts = []
        if adjustment != 0:
            parts.append(f"المخزون {old_quantity} → {new_quantity}")
        if price_changed:
            parts.append(f"سعر البيع {old_sale_price} → {new_sale_price}")
        message = "تم الحفظ بنجاح: " + " | ".join(parts)
        if reason:
            message += f". السبب: {reason}"
        
        if request.is_json:
            return jsonify({
                "success": True, 
                "message": message,
                "old_quantity": old_quantity,
                "new_quantity": new_quantity,
                "adjustment": adjustment,
                "old_sale_price": old_sale_price,
                "new_sale_price": new_sale_price,
                "price_changed": price_changed,
            })
        else:
            from flask import flash
            flash(message, "success")
            return redirect(url_for("inventory.inventory"))
    except ValueError:
        if request.is_json:
            return jsonify({"success": False, "error": "قيمة التعديل أو سعر البيع غير صحيحة"}), 400
        else:
            from flask import flash
            flash("قيمة التعديل أو سعر البيع غير صحيحة", "error")
            return redirect(url_for("inventory.inventory"))
    except Exception as e:
        db.session.rollback()
        if request.is_json:
            return jsonify({"success": False, "error": str(e)}), 400
        else:
            from flask import flash
            flash(f"حدث خطأ: {str(e)}", "error")
            return redirect(url_for("inventory.inventory"))


# ======================================
# Get Product Inventory Movements (API)
# ======================================
@inventory_bp.route("/api/movements/<int:product_id>")
def get_product_movements_api(product_id):
    """API للحصول على حركات مخزون منتج محدد"""
    if not check_permission("can_manage_inventory"):
        return jsonify({"error": "Unauthorized"}), 403
    
    movements = get_product_inventory_movements(product_id)
    summary = get_product_inventory_summary(product_id)
    
    return jsonify({
        "summary": summary,
        "movements": movements[:50]  # آخر 50 حركة
    })


# ======================================
# Product Report
# ======================================
@inventory_bp.route("/report/<int:id>")
def product_report(id):
    product = Product.query.get_or_404(id)

    stats = (
        db.session.query(
            Invoice.status,
            func.count(Invoice.id),
            func.sum(OrderItem.total)
        )
        .join(OrderItem, OrderItem.invoice_id == Invoice.id)
        .filter(OrderItem.product_id == id)
        .group_by(Invoice.status)
        .all()
    )

    report = {
        s[0]: {
            "count": s[1],
            "total": s[2] or 0
        }
        for s in stats
    }

    return render_template(
        "inventory_report.html",
        product=product,
        report=report
    )


# ======================================
# Products JSON (desktop / API clients)
# ======================================
def _stock_state(qty: int, threshold: int) -> str:
    if qty <= 0:
        return "out"
    if qty <= threshold:
        return "low"
    return "available"


def _product_api_row(product, qty: int) -> dict:
    threshold = int(product.low_stock_threshold if product.low_stock_threshold is not None else 5)
    return {
        "id": product.id,
        "name": product.name,
        "sku": product.sku or "",
        "barcode": product.barcode or "",
        "category": product.catalog_category or "",
        "brand": str(_load_product_meta(product).get("brand") or ""),
        "image_url": product.image_url or "",
        "buy_price": int(product.buy_price or 0),
        "sale_price": int(product.sale_price or 0),
        "quantity": int(qty),
        "low_stock_threshold": threshold,
        "stock_state": _stock_state(int(qty), threshold),
        "active": bool(product.active),
    }


@inventory_bp.route("/api/products")
def products_api(*, _snapshot=False):
    """Paginated product list with stock stats — same scope and quantities as the inventory page."""
    if not check_permission("can_manage_inventory"):
        return jsonify({"success": False, "error": "غير مصرح"}), 403
    ensure_product_schema()

    snapshot = _inventory_snapshot()
    qty_map = snapshot["product_display_qty_map"]
    rows = [_product_api_row(p, qty_map.get(int(p.id), 0)) for p in snapshot["products"]]

    stats = {
        "total": len(rows),
        "available": sum(1 for r in rows if r["stock_state"] == "available"),
        "low": sum(1 for r in rows if r["stock_state"] == "low"),
        "out": sum(1 for r in rows if r["stock_state"] == "out"),
    }
    categories = sorted({r["category"] for r in rows if r["category"]})
    brands = sorted({r["brand"] for r in rows if r["brand"]})

    search = (request.args.get("search") or "").strip().lower()
    if search:
        rows = [
            r for r in rows
            if search in r["name"].lower() or search in r["sku"].lower() or search == r["barcode"].lower()
            or (len(search) >= 4 and search in r["barcode"].lower())
        ]
    category = (request.args.get("category") or "").strip()
    if category:
        rows = [r for r in rows if r["category"] == category]
    stock = (request.args.get("stock") or "").strip()
    if stock in {"available", "low", "out"}:
        rows = [r for r in rows if r["stock_state"] == stock]

    sort_field = request.args.get("sort_field") or "name"
    if sort_field not in {"name", "sku", "category", "buy_price", "sale_price", "quantity"}:
        sort_field = "name"
    rows.sort(key=lambda r: (r[sort_field] if not isinstance(r[sort_field], str) else r[sort_field].lower()),
              reverse=request.args.get("sort_dir") == "desc")

    page_size = (len(rows) or 1) if _snapshot else min(100, max(1, request.args.get("page_size", 25, type=int) or 25))
    total = len(rows)
    total_pages = max(1, (total + page_size - 1) // page_size)
    page = min(max(1, request.args.get("page", 1, type=int) or 1), total_pages)
    start = (page - 1) * page_size
    return jsonify({
        "success": True,
        "rows": rows[start:start + page_size],
        "page": page,
        "page_size": page_size,
        "total": total,
        "total_pages": total_pages,
        "stats": stats,
        "categories": categories,
        "brands": brands,
        "branch_scope_label": snapshot["branch_scope_label"],
    })


# Fields the desktop editor owns. Everything else on the product (specs,
# gallery, video, delivery fees, region pricing, colours, custom fields) is
# left exactly as it is - unlike the full web form, which rebuilds meta.
_DESKTOP_META_KEYS = ("category", "brand", "unit")


@inventory_bp.route("/api/products/<int:product_id>")
def product_api_details(product_id):
    if not check_permission("can_manage_inventory"):
        return jsonify({"success": False, "error": "غير مصرح"}), 403
    product = Product.query.get(product_id)
    if not product:
        return jsonify({"success": False, "error": "المنتج غير موجود أو تم حذفه"}), 404
    meta = _load_product_meta(product)
    return jsonify({
        "success": True,
        "product": {
            "id": product.id,
            "name": product.name or "",
            "sku": product.sku or "",
            "barcode": product.barcode or "",
            "buy_price": int(product.buy_price or 0),
            "sale_price": int(product.sale_price or 0),
            "exchange_sale_price": product.exchange_sale_price,
            "trade_in_sales_enabled": tenant_feature_enabled("trade_in_sales", default=False),
            "editor_settings_supported": True,
            "pos_visible": product.pos_visible is not False,
            "store_visible": product.store_visible is not False,
            "storefront_publication": _inventory_storefront_state(product),
            "low_stock_threshold": int(product.low_stock_threshold if product.low_stock_threshold is not None else 5),
            "description": product.description or "",
            "image_url": product.image_url or "",
            "active": bool(product.active),
            "has_colors": product_has_colors(product),
            "colors_supported": True,
            "color_images_supported": True,
            "options_supported": True,
            "option_axes": option_config(product)["axes"],
            "colors": local_color_rows(product.id),
            "current_stock": _edit_current_stock_for_product(product, meta),
            **{key: str(meta.get(key) or "") for key in _DESKTOP_META_KEYS},
        },
    })


@inventory_bp.route("/api/products/<int:product_id>/update", methods=["POST"])
def product_api_update(product_id):
    """Update only the fields an API client sends (multipart form, optional product_image)."""
    if not check_permission("can_manage_inventory"):
        return jsonify({"success": False, "error": "غير مصرح"}), 403
    ensure_product_schema()
    product = Product.query.filter_by(id=product_id).with_for_update().first()
    if not product:
        return jsonify({"success": False, "error": "المنتج غير موجود أو تم حذفه"}), 404
    form = request.form
    if "add_colors" in form or "color_images" in form or "product_options" in form:
        lock_color_product(product)

    def as_int(key):
        raw = (form.get(key) or "").strip()
        if raw == "":
            return None
        value = int(raw)
        if value < 0:
            raise ValueError(key)
        return value

    try:
        buy_price = as_int("buy_price")
        sale_price = as_int("sale_price")
        exchange_sale_price = as_int("exchange_sale_price") or None
        low_stock = as_int("low_stock_threshold")
        for field in ("pos_visible", "store_visible"):
            if field in form and form.get(field) not in {"0", "1"}:
                raise ValueError(field)
    except ValueError:
        return jsonify({"success": False, "error": "قيمة رقمية غير صحيحة"}), 400

    price_changed = (buy_price is not None and buy_price != int(product.buy_price or 0)) or (
        sale_price is not None and sale_price != int(product.sale_price or 0)
    ) or ("exchange_sale_price" in form and exchange_sale_price != product.exchange_sale_price)
    if price_changed and not check_permission("edit_price"):
        return jsonify({"success": False, "error": "ليست لديك صلاحية تعديل الأسعار"}), 403
    if "exchange_sale_price" in form and exchange_sale_price and not tenant_feature_enabled("trade_in_sales", default=False):
        return jsonify(success=False, error="ميزة الاستبدال غير مفعّلة لهذه الشركة"), 400

    editor_snapshot_fields = (*PRODUCT_SNAPSHOT_FIELDS, "buy_price", "sale_price", "exchange_sale_price", "pos_visible", "store_visible")
    before = snapshot_attrs(product, *editor_snapshot_fields)
    old_name = product.name
    if "add_colors" in form or "color_images" in form or "product_options" in form:
        before["colors"] = local_color_rows(product.id)
    if "name" in form:
        name = (form.get("name") or "").strip()
        if not name:
            return jsonify({"success": False, "error": "يرجى إدخال اسم المنتج."}), 400
        product.name = name
    if "sku" in form:
        product.sku = (form.get("sku") or "").strip() or None
    if "barcode" in form:
        barcode = (form.get("barcode") or "").strip() or None
        if barcode_conflict(product.branch_id, barcode, exclude_product_id=product.id):
            return jsonify({"success": False, "error": "الباركود مستخدم لمنتج آخر في هذا الفرع."}), 409
        product.barcode = barcode
    if buy_price is not None:
        product.buy_price = buy_price
    if sale_price is not None:
        product.sale_price = sale_price
    if "exchange_sale_price" in form:
        product.exchange_sale_price = exchange_sale_price
    visibility_changes = {}
    for field in ("pos_visible", "store_visible"):
        if field in form:
            visibility_changes[field] = _apply_catalog_visibility(product, field, form.get(field) == "1")
    if low_stock is not None:
        product.low_stock_threshold = low_stock
    if "description" in form:
        product.description = (form.get("description") or "").strip() or None
    if "active" in form:
        product.active = form.get("active") == "1"
    meta = _load_product_meta(product)
    meta_changed = False
    for key in _DESKTOP_META_KEYS:
        if key in form:
            value = (form.get(key) or "").strip()
            if value:
                meta[key] = value
            else:
                meta.pop(key, None)
            meta_changed = True
    if meta_changed:
        product.meta_json = json.dumps(meta, ensure_ascii=False) if meta else None
    image_url = _save_uploaded_product_image(request.files.get("product_image"))
    if image_url:
        product.image_url = image_url
    created_color_files = []
    try:
        if product.name != old_name:
            sync_product_name_to_order_items(product.id, product.name)
        if "add_colors" in form:
            append_product_colors(product, form.get("add_colors"), form.get("color_stock"),
                                  _edit_current_stock_for_product(product, _load_product_meta(product)))
        if "product_options" in form:
            apply_product_options(product, form.get("product_options"),
                                  current_stock=_edit_current_stock_for_product(product, _load_product_meta(product)),
                                  can_edit_price=check_permission("edit_price"))
        if "color_images" in form:
            apply_color_images(product, form.get("color_images"), request.files, created_color_files)
        if "store_visible" in visibility_changes:
            _sync_inventory_storefront(visibility_changes["store_visible"], form.get("store_visible") == "1")
        db.session.commit()
        _refresh_storefront()
    except ProductColorError as exc:
        db.session.rollback()
        cleanup_color_uploads(created_color_files)
        return jsonify({"success": False, "error": str(exc)}), 409
    except IntegrityError as exc:
        db.session.rollback()
        cleanup_color_uploads(created_color_files)
        from utils.desktop_stock_reservations import GUARD_ERROR, GUARD_MESSAGE
        if GUARD_ERROR in str(exc):
            return jsonify({"success": False, "error": GUARD_MESSAGE}), 409
        current_app.logger.exception("product update conflict")
        return jsonify({"success": False, "error": "تعارض أثناء الحفظ؛ أعد تحميل المنتج وحاول مجدداً"}), 409
    except (OSError, SQLAlchemyError):
        db.session.rollback()
        cleanup_color_uploads(created_color_files)
        current_app.logger.exception("product color photo update failed")
        return jsonify(success=False, error="تعذّر حفظ الصور؛ لم تُحفظ التعديلات. حاول مجدداً"), 500
    try:
        log_mutation(
            "update",
            "inventory",
            "product",
            product.id,
            before,
            {**snapshot_attrs(product, *editor_snapshot_fields),
             **({"visibility_targets": visibility_changes} if visibility_changes else {}),
             **({"colors": local_color_rows(product.id)} if "add_colors" in form or "color_images" in form or "product_options" in form else {})},
            f"تعديل منتج: {product.name}",
        )
    except Exception:
        current_app.logger.exception("product update audit failed")
    return jsonify({"success": True, "product_id": product.id, "image_url": product.image_url or ""})
