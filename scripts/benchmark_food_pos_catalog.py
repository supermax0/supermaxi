"""Repeatable local benchmark for the POS catalogue's production query shape."""
from __future__ import annotations

import sqlite3
import time


PRODUCTS = 10_000
VARIANTS = 50_000
PAGE_SIZE = 48


def main() -> None:
    connection = sqlite3.connect(":memory:")
    connection.executescript("""
        CREATE TABLE product (id INTEGER PRIMARY KEY, tenant_id INTEGER, name TEXT, active INTEGER);
        CREATE TABLE food_product_profile (
            id INTEGER PRIMARY KEY, tenant_id INTEGER, product_id INTEGER,
            short_name TEXT, brand TEXT, category TEXT, active INTEGER
        );
        CREATE TABLE food_product_variant (
            id INTEGER PRIMARY KEY, tenant_id INTEGER, profile_id INTEGER,
            variant_name TEXT, flavor TEXT, size TEXT, sku TEXT, active INTEGER
        );
        CREATE TABLE food_product_barcode (
            id INTEGER PRIMARY KEY, tenant_id INTEGER, variant_id INTEGER,
            barcode TEXT, active INTEGER
        );
        CREATE INDEX ix_profile_tenant_category ON food_product_profile(tenant_id, category);
        CREATE INDEX ix_variant_tenant_profile ON food_product_variant(tenant_id, profile_id);
        CREATE INDEX ix_variant_tenant_sku ON food_product_variant(tenant_id, sku);
        CREATE UNIQUE INDEX ux_barcode_tenant_value ON food_product_barcode(tenant_id, barcode);
    """)
    connection.executemany(
        "INSERT INTO product VALUES (?,1,?,1)",
        ((index, f"منتج {index:05d}") for index in range(1, PRODUCTS + 1)),
    )
    connection.executemany(
        "INSERT INTO food_product_profile VALUES (?,1,?,?,?,'مشروبات',1)",
        ((index, index, f"P{index:05d}", "Finora") for index in range(1, PRODUCTS + 1)),
    )
    connection.executemany(
        "INSERT INTO food_product_variant VALUES (?,1,?,?,?,?,?,1)",
        ((index, ((index - 1) // 5) + 1, f"نوع {index:05d}", "نكهة", "330ml", f"SKU-{index:05d}")
         for index in range(1, VARIANTS + 1)),
    )
    connection.executemany(
        "INSERT INTO food_product_barcode VALUES (?,1,?,?,1)",
        ((index, index, f"629{index:010d}") for index in range(1, VARIANTS + 1)),
    )
    connection.commit()

    started = time.perf_counter()
    row = connection.execute(
        "SELECT variant_id FROM food_product_barcode WHERE tenant_id=? AND barcode=? AND active=1",
        (1, "6290000050000"),
    ).fetchone()
    barcode_ms = (time.perf_counter() - started) * 1000

    started = time.perf_counter()
    rows = connection.execute("""
        SELECT v.id, p.name, v.variant_name
        FROM food_product_variant v
        JOIN food_product_profile fp ON fp.id=v.profile_id
        JOIN product p ON p.id=fp.product_id
        WHERE v.tenant_id=1 AND v.active=1 AND fp.active=1 AND p.active=1
          AND (p.name LIKE ? OR fp.short_name LIKE ? OR fp.brand LIKE ?
               OR v.variant_name LIKE ? OR v.sku LIKE ?)
        ORDER BY CASE WHEN v.sku=? THEN 0 ELSE 1 END, p.name, v.variant_name
        LIMIT ? OFFSET 0
    """, ("%منتج 09999%",) * 4 + ("%منتج 09999%", "منتج 09999", PAGE_SIZE)).fetchall()
    search_ms = (time.perf_counter() - started) * 1000

    print({
        "products": PRODUCTS, "variants": VARIANTS,
        "barcode_found": bool(row), "barcode_ms": round(barcode_ms, 2),
        "search_rows": len(rows), "search_ms": round(search_ms, 2),
        "page_size": PAGE_SIZE,
    })


if __name__ == "__main__":
    main()
