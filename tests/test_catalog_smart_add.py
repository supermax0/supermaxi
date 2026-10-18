"""Smart Commerce Sprint 4: smart add — lookup, Excel/CSV import with a preview, images. Nothing is published or
stocked by any of it, and nothing is duplicated."""
from __future__ import annotations

import io
import json

import pytest

from tests.test_branch_management_api import _client, _json, _make_ctx, app  # noqa: F401

API = "/api/v1/desktop/catalog"
CSV = (
    "الاسم,العلامة,الموديل,الباركود,القسم,الحجم,السعر\n"
    "شاشة سامسونج 55,Samsung,UA55CU7000,8806094970002,شاشات,55 بوصة,999999\n"
    "غسالة LG 9 كغم,LG,F4R5VYL0W,8806091234567,غسالات,9 كغم,450000\n"
    "شاشة مكررة,Samsung,UA55-CU7000,,شاشات,,\n"
    "منتج بلا موديل,,,,ملحقات,,\n"
    ",,,,,,\n"
    ",,,123,,,\n"
)


@pytest.fixture()
def shop(app, monkeypatch, tmp_path):  # noqa: F811
    monkeypatch.setenv("FINORA_LOCAL_WORKSPACE", "0")
    monkeypatch.setattr(app, "static_folder", str(tmp_path))  # uploaded test images never land in the repo
    ids = _make_ctx(app)
    admin = _client(ids)
    _json(admin.post(f"{API}/settings", json={"catalog_layer": True}))
    return {**ids, "admin": admin, "app": app}


def _upload(shop, body: bytes, name: str):
    return shop["admin"].post(f"{API}/imports", data={"file": (io.BytesIO(body), name)},
                              content_type="multipart/form-data")


def _png(w=640, h=640, color=(200, 30, 60)) -> bytes:
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (w, h), color).save(buf, "PNG")
    return buf.getvalue()


def test_csv_preview_classifies_every_row_and_ignores_prices(shop):
    batch = _json(_upload(shop, CSV.encode("utf-8"), "supplier.csv"))["batch"]
    by_no = {r["row_no"]: r for r in batch["rows"]}
    assert by_no[2]["status"] == "new" and by_no[2]["data"]["attributes"] == {"الحجم": "55 بوصة"}
    assert "السعر" not in json.dumps(by_no[2]["data"], ensure_ascii=False)  # prices never enter the catalogue
    assert by_no[4]["status"] == "duplicate"  # same brand + model as row 2 (spacing / dash differ)
    assert by_no[5]["status"] == "needs_review"  # no brand / model
    assert by_no[7]["status"] == "invalid"  # bad barcode and no name
    assert batch["status"] == "preview"
    from flask import g

    from modules.catalog.models import CatalogProduct

    with shop["app"].test_request_context():
        g.tenant = shop["tenant"]
        assert CatalogProduct.query.count() == 0  # a preview stores rows, not entries


def test_apply_creates_review_entries_once_never_published_and_refuses_the_same_file(shop):
    batch = _json(_upload(shop, CSV.encode("utf-8"), "supplier.csv"))["batch"]
    result = _json(shop["admin"].post(f"{API}/imports/{batch['id']}/apply", json={}))["result"]
    assert result["created"] == 2  # rows 2 and 3; the duplicate, the review and the invalid rows are skipped
    assert shop["admin"].post(f"{API}/imports/{batch['id']}/apply", json={}).status_code == 409  # once only
    again = _upload(shop, CSV.encode("utf-8"), "supplier.csv")
    assert again.status_code == 409 and again.get_json()["code"] == "duplicate_file"
    rows = _json(shop["admin"].get(f"{API}/entries"))["rows"]
    assert len(rows) == 2
    assert all(r["verification_status"] == "needs_review" and r["listing"] is None for r in rows)
    tv = next(r for r in rows if r["model_number"] == "UA55CU7000")
    assert tv["field_sources"]["brand"]["source"] == "import:supplier.csv" and tv["barcodes"] == ["8806094970002"]


def test_a_second_supplier_only_fills_empty_fields_of_existing_entries(shop):
    first = _json(shop["admin"].post(f"{API}/entries", json={
        "canonical_name": "شاشة سامسونج 55", "brand": "Samsung", "model_number": "UA55CU7000",
        "description": "وصف موثّق من الشركة", "verification_status": "verified"}))["entry"]
    other = "name,brand,model,category,description,refresh rate\nTV,SAMSUNG,ua55cu7000,شاشات,وصف المورد الآخر,60Hz\n"
    batch = _json(_upload(shop, other.encode(), "other.csv"))["batch"]
    assert batch["rows"][0]["status"] == "matched" and batch["rows"][0]["match_entry_id"] == first["id"]
    assert _json(shop["admin"].post(f"{API}/imports/{batch['id']}/apply", json={}))["result"]["updated"] == 1
    entry = _json(shop["admin"].get(f"{API}/entries/{first['id']}"))["entry"]
    assert entry["description"] == "وصف موثّق من الشركة"  # a filled value is never overwritten
    assert entry["category"] == "شاشات" and entry["attributes"]["refresh rate"] == "60Hz"  # empty ones are filled
    assert entry["verification_status"] == "verified"


def test_rows_matching_an_inventory_product_are_linked_not_duplicated(shop):
    from flask import g

    from extensions import db
    from models.product import Product
    from utils.branch_migration import get_default_branch

    with shop["app"].test_request_context():
        g.tenant = shop["tenant"]
        p = Product(name="غسالة LG", sku="F4R5VYL0W", barcode="8806091234567", buy_price=1, sale_price=2, quantity=4,
                    active=True, branch_id=get_default_branch().id)
        db.session.add(p)
        db.session.commit()
        pid, products_before = p.id, Product.query.execution_options(skip_branch_scope=True).count()
    batch = _json(_upload(shop, CSV.encode(), "supplier.csv"))["batch"]
    washer = next(r for r in batch["rows"] if r["row_no"] == 3)
    assert washer["status"] == "linked" and washer["match_product_id"] == pid
    result = _json(shop["admin"].post(f"{API}/imports/{batch['id']}/apply", json={}))["result"]
    assert result["linked"] == 1
    with shop["app"].test_request_context():
        g.tenant = shop["tenant"]
        assert Product.query.execution_options(skip_branch_scope=True).count() == products_before  # no new product
        assert Product.query.execution_options(skip_branch_scope=True).get(pid).quantity == 4  # stock untouched


def test_xlsx_import_and_bad_files(shop):
    from openpyxl import Workbook

    book = Workbook()
    sheet = book.active
    sheet.append(["Product Name", "Brand", "Model No", "EAN", "Category"])
    sheet.append(["Gree Split 1.5 Ton", "Gree", "GWH18", "6975351234561", "سبالت"])
    buf = io.BytesIO()
    book.save(buf)
    batch = _json(_upload(shop, buf.getvalue(), "gree.xlsx"))["batch"]
    assert batch["rows"][0]["status"] == "new" and batch["rows"][0]["data"]["barcode"] == "6975351234561"
    assert _upload(shop, b"not,a,catalog\n1,2,3\n", "x.csv").status_code == 400  # no name / model column
    assert _upload(shop, b"\x00\x01", "x.pdf").status_code == 400
    assert _upload(shop, b"", "x.csv").status_code == 400


def test_lookup_reports_catalog_inventory_and_provider_candidates_without_saving(shop):
    from modules.catalog import providers

    class Fake:
        name = "test-manufacturer"

        def lookup(self, query):
            return [{"canonical_name": "TCL 55C7K", "brand": "TCL", "model_number": "55C7K",
                     "source_url": "https://example.test/55c7k", "confidence": 90}]

    class Broken:
        name = "broken"

        def lookup(self, query):
            raise RuntimeError("down")

    providers.register(Fake())
    providers.register(Broken())
    try:
        out = _json(shop["admin"].get(f"{API}/lookup?q=55C7K"))
    finally:
        providers.unregister("test-manufacturer")
        providers.unregister("broken")
    assert out["catalog"] == [] and out["inventory"] is None
    assert out["candidates"] == [{"canonical_name": "TCL 55C7K", "brand": "TCL", "model_number": "55C7K",
                                  "source_url": "https://example.test/55c7k", "confidence": 90,
                                  "provider": "test-manufacturer"}]  # a failing source does not break the lookup
    assert _json(shop["admin"].get(f"{API}/entries"))["total"] == 0
    assert shop["admin"].get(f"{API}/lookup?q=a").status_code == 400


def test_image_pipeline_validates_keeps_original_and_protects_verified_photos(shop):
    entry = _json(shop["admin"].post(f"{API}/entries", json={"canonical_name": "ثلاجة اختبار", "brand": "X",
                                                             "model_number": "R1"}))["entry"]

    def up(raw, **form):
        return shop["admin"].post(f"{API}/entries/{entry['id']}/media",
                                  data={"file": (io.BytesIO(raw), "p.png"), **form}, content_type="multipart/form-data")

    assert up(b"not an image").status_code == 400
    assert up(_png(100, 100)).status_code == 400  # too small to look right in the shop
    ok = _json(up(_png(), role="front"))["entry"]
    media = ok["media"][0]
    assert media["url"].endswith(".webp") and media["rights"] == "own_photo" and not media["verified"]
    from pathlib import Path

    folder = Path(shop["app"].static_folder) / media["url"].removeprefix("/static/")
    assert folder.is_file() and any(p.name.endswith(".orig.png") for p in folder.parent.iterdir())
    assert any(p.name.endswith(".thumb.webp") for p in folder.parent.iterdir())
    assert up(_png()).status_code == 409  # the same picture twice
    assert _json(shop["admin"].post(f"{API}/entries/{entry['id']}/media/{media['id']}/verify"))["entry"]["media"][0]["verified"]
    assert shop["admin"].post(f"{API}/entries/{entry['id']}/media/{media['id']}/remove").status_code == 409
    imported = _json(shop["admin"].post(f"{API}/entries/{entry['id']}", json={
        "canonical_name": "ثلاجة اختبار", "brand": "X", "model_number": "R1",
        "media": [{"url": "https://cdn.example.test/r1.jpg", "usage_rights": "unverified"}]}))["entry"]
    assert len(imported["media"]) == 2  # editing adds, never wipes the verified photo
    link = next(m for m in imported["media"] if m["url"].startswith("https://"))
    assert shop["admin"].post(f"{API}/entries/{entry['id']}/media/{link['id']}/verify").status_code == 409  # no rights
