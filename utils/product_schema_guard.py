from __future__ import annotations

from sqlalchemy import inspect, text

from extensions import db


def ensure_product_schema() -> None:
    """
    Ensures `product` table has required columns for the advanced product form.
    Runs against the currently-bound engine (Core or the active tenant), so it
    works in multi-tenant mode where each tenant has its own DB.
    """
    try:
        engine = db.session.get_bind()
        inspector = inspect(engine)

        if "product" not in inspector.get_table_names():
            return

        existing_cols = {col["name"] for col in inspector.get_columns("product")}

        # Columns introduced for the advanced product page.
        additions = {
            "sku": "ALTER TABLE product ADD COLUMN sku VARCHAR(100)",
            "description": "ALTER TABLE product ADD COLUMN description TEXT",
            "image_url": "ALTER TABLE product ADD COLUMN image_url VARCHAR(512)",
            "meta_json": "ALTER TABLE product ADD COLUMN meta_json TEXT",
        }

        # Also keep prior additions that some installs might miss.
        # (These are safe to run only if the column is absent.)
        additions.setdefault(
            "barcode",
            "ALTER TABLE product ADD COLUMN barcode VARCHAR(100) UNIQUE",
        )
        additions.setdefault(
            "low_stock_threshold",
            "ALTER TABLE product ADD COLUMN low_stock_threshold INTEGER DEFAULT 5",
        )

        for col_name, stmt in additions.items():
            if col_name not in existing_cols:
                db.session.execute(text(stmt))
                db.session.commit()
                existing_cols.add(col_name)
    except Exception:
        # Avoid breaking the UI if schema check fails for any reason.
        # The API/UI will show the real DB error if columns still don't exist.
        return

