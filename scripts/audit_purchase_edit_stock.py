"""Audit purchase-edit stock drift in tenant SQLite databases.

The check compares documented stock with actual product/branch stock. It is
useful after editing purchase invoices, where an old invoice quantity may have
been added again instead of being reversed first.

Usage:
  .\venv\Scripts\python.exe scripts\audit_purchase_edit_stock.py --db tenants\super.db
  .\venv\Scripts\python.exe scripts\audit_purchase_edit_stock.py --all-tenants
  .\venv\Scripts\python.exe scripts\audit_purchase_edit_stock.py --db tenants\super.db --apply
"""

from __future__ import annotations

import argparse
import os
import sqlite3
from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TENANTS_DIR = ROOT / "tenants"


def _tables(cur) -> set[str]:
    return {r[0] for r in cur.execute("select name from sqlite_master where type='table'")}


def _cols(cur, table: str) -> set[str]:
    if table not in _tables(cur):
        return set()
    return {r[1] for r in cur.execute(f"pragma table_info({table})")}


def _safe_int(value) -> int:
    try:
        return int(value or 0)
    except Exception:
        return 0


def _is_active_purchase(status: str | None) -> bool:
    s = (status or "confirmed").strip().lower()
    return s not in {"draft", "cancelled", "canceled"}


def _is_reversed_invoice(status: str | None, payment_status: str | None) -> bool:
    values = {(status or "").strip(), (payment_status or "").strip()}
    return bool(values & {"ملغي", "راجع", "مرتجع", "راجعة", "راجعه", "cancelled", "canceled", "returned"})


def _default_branch_id(cur) -> int | None:
    if "branch" not in _tables(cur):
        return None
    row = cur.execute("select id from branch where coalesce(is_default, 0) = 1 order by id limit 1").fetchone()
    if row:
        return _safe_int(row[0])
    row = cur.execute("select id from branch order by id limit 1").fetchone()
    return _safe_int(row[0]) if row else None


def _branch_stock_enabled(cur) -> bool:
    return "branch_stock" in _tables(cur) and cur.execute("select count(*) from branch_stock").fetchone()[0] > 0


def _key(branch_enabled: bool, branch_id: int | None, product_id: int, default_branch: int | None):
    if branch_enabled:
        return (branch_id or default_branch, product_id)
    return (None, product_id)


def audit_db(db_path: Path, apply: bool = False) -> list[dict]:
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    cur = con.cursor()
    tables = _tables(cur)
    if "product" not in tables or "purchase" not in tables:
        con.close()
        return []

    branch_enabled = _branch_stock_enabled(cur)
    default_branch = _default_branch_id(cur)
    expected = defaultdict(int)
    actual = {}
    labels = {}

    for p in cur.execute("select id, name, opening_stock, quantity from product"):
        pid = _safe_int(p["id"])
        labels[(None, pid)] = p["name"]
        if not branch_enabled:
            expected[(None, pid)] += _safe_int(p["opening_stock"])
            actual[(None, pid)] = _safe_int(p["quantity"])

    if branch_enabled:
        q = (
            "select bs.branch_id, bs.product_id, bs.opening_stock, bs.quantity, p.name "
            "from branch_stock bs join product p on p.id = bs.product_id"
        )
        for row in cur.execute(q):
            key = (_safe_int(row["branch_id"]), _safe_int(row["product_id"]))
            expected[key] += _safe_int(row["opening_stock"])
            actual[key] = _safe_int(row["quantity"])
            labels[key] = row["name"]

    purchase_cols = _cols(cur, "purchase")
    has_items = "purchase_item" in tables
    item_purchase_ids: set[int] = set()
    if has_items:
        status_expr = "p.status" if "status" in purchase_cols else "'confirmed'"
        branch_expr = "p.branch_id" if "branch_id" in purchase_cols else "null"
        q = (
            f"select pi.purchase_id, pi.product_id, pi.quantity, {status_expr} as status, {branch_expr} as branch_id "
            "from purchase_item pi join purchase p on p.id = pi.purchase_id"
        )
        for row in cur.execute(q):
            if not _is_active_purchase(row["status"]):
                continue
            pid = _safe_int(row["product_id"])
            item_purchase_ids.add(_safe_int(row["purchase_id"]))
            expected[_key(branch_enabled, row["branch_id"], pid, default_branch)] += _safe_int(row["quantity"])

    status_col = "status" if "status" in purchase_cols else "'confirmed' as status"
    legacy_select = f"id, product_id, quantity, {status_col}"
    if "branch_id" in purchase_cols:
        legacy_select += ", branch_id"
    else:
        legacy_select += ", null as branch_id"
    for row in cur.execute(f"select {legacy_select} from purchase"):
        if _safe_int(row["id"]) in item_purchase_ids:
            continue
        if not _is_active_purchase(row["status"]):
            continue
        pid = _safe_int(row["product_id"])
        expected[_key(branch_enabled, row["branch_id"], pid, default_branch)] += _safe_int(row["quantity"])

    if "order_item" in tables and "invoice" in tables:
        order_cols = _cols(cur, "order_item")
        invoice_cols = _cols(cur, "invoice")
        if "fulfillment_branch_id" in order_cols:
            branch_expr = "oi.fulfillment_branch_id"
        elif "branch_id" in invoice_cols:
            branch_expr = "i.branch_id"
        else:
            branch_expr = "null"
        q = (
            f"select oi.product_id, oi.quantity, {branch_expr} as branch_id, i.status, i.payment_status "
            "from order_item oi join invoice i on i.id = oi.invoice_id"
        )
        for row in cur.execute(q):
            if _is_reversed_invoice(row["status"], row["payment_status"]):
                continue
            pid = _safe_int(row["product_id"])
            expected[_key(branch_enabled, row["branch_id"], pid, default_branch)] -= _safe_int(row["quantity"])

    if branch_enabled and "stock_transfer" in tables and "stock_transfer_line" in tables:
        q = (
            "select st.from_branch_id, st.to_branch_id, st.status, stl.product_id, stl.quantity "
            "from stock_transfer_line stl join stock_transfer st on st.id = stl.transfer_id "
            "where st.status in ('sent', 'received')"
        )
        for row in cur.execute(q):
            pid = _safe_int(row["product_id"])
            qty = _safe_int(row["quantity"])
            if row["status"] in ("sent", "received"):
                expected[(_safe_int(row["from_branch_id"]), pid)] -= qty
            if row["status"] == "received":
                expected[(_safe_int(row["to_branch_id"]), pid)] += qty

    for key in expected:
        actual.setdefault(key, 0)

    mismatches = []
    for key in sorted(actual.keys() | expected.keys()):
        exp = expected.get(key, 0)
        act = actual.get(key, 0)
        diff = act - exp
        if diff == 0:
            continue
        branch_id, product_id = key
        mismatches.append(
            {
                "db": str(db_path),
                "branch_id": branch_id,
                "product_id": product_id,
                "product": labels.get(key) or labels.get((None, product_id)) or "",
                "expected": exp,
                "actual": act,
                "diff": diff,
            }
        )
        if apply:
            if branch_enabled and branch_id is not None:
                cur.execute(
                    "update branch_stock set quantity = ? where branch_id = ? and product_id = ?",
                    (exp, branch_id, product_id),
                )
            else:
                cur.execute("update product set quantity = ? where id = ?", (exp, product_id))

    if apply and mismatches:
        con.commit()
    con.close()
    return mismatches


def _db_paths(args) -> list[Path]:
    if args.all_tenants:
        return sorted(TENANTS_DIR.glob("*.db"))
    if args.db:
        return [Path(args.db)]
    raise SystemExit("Pass --db PATH or --all-tenants")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", help="Tenant SQLite database path")
    parser.add_argument("--all-tenants", action="store_true", help="Audit all tenants/*.db")
    parser.add_argument("--apply", action="store_true", help="Set actual stock to documented stock")
    args = parser.parse_args()

    all_mismatches = []
    for db_path in _db_paths(args):
        if not db_path.is_absolute():
            db_path = ROOT / db_path
        if not db_path.exists():
            print(f"missing: {db_path}")
            continue
        mismatches = audit_db(db_path, apply=args.apply)
        all_mismatches.extend(mismatches)
        print(f"{db_path}: {len(mismatches)} mismatch(es)")
        for m in mismatches:
            branch = f"branch={m['branch_id']}" if m["branch_id"] is not None else "all-branches"
            print(
                f"  product#{m['product_id']} {m['product']} {branch}: "
                f"actual={m['actual']} expected={m['expected']} diff={m['diff']}"
            )

    if args.apply:
        print("Applied stock corrections." if all_mismatches else "No corrections needed.")
    return 1 if all_mismatches and not args.apply else 0


if __name__ == "__main__":
    raise SystemExit(main())
