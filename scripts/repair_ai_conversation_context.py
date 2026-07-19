"""Repair stale product/order state for one AI Sales conversation."""
from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("database", type=Path)
    parser.add_argument("conversation_id", type=int)
    parser.add_argument("product_id", type=int)
    parser.add_argument("product_family")
    parser.add_argument("--stage", default="objection")
    args = parser.parse_args()

    connection = sqlite3.connect(args.database)
    connection.row_factory = sqlite3.Row
    table = next(
        (
            name
            for name in ("ai_sales_conversation", "ai_conversations", "ai_sales_conversations")
            if connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
                (name,),
            ).fetchone()
        ),
        None,
    )
    if not table:
        raise SystemExit("AI conversations table was not found")

    row = connection.execute(
        f"SELECT id, sales_stage, context_json FROM {table} WHERE id = ?",
        (args.conversation_id,),
    ).fetchone()
    if not row:
        raise SystemExit(f"Conversation {args.conversation_id} was not found")

    context = json.loads(row["context_json"] or "{}")
    removed = []
    for key in (
        "pending_order",
        "purchase_selection",
        "created_order_id",
        "recommendation_snapshot",
        "primary_objection",
    ):
        if key in context:
            removed.append(key)
            context.pop(key, None)
    context["last_product_ids"] = [args.product_id]
    context["focus_product_id"] = args.product_id
    context["product_family"] = args.product_family
    context["last_intent"] = "price_objection"
    context["detected_objection"] = "price"

    connection.execute(
        f"UPDATE {table} SET sales_stage = ?, context_json = ? WHERE id = ?",
        (args.stage, json.dumps(context, ensure_ascii=False), args.conversation_id),
    )
    connection.commit()
    print(json.dumps({
        "conversation_id": args.conversation_id,
        "stage_before": row["sales_stage"],
        "stage_after": args.stage,
        "focus_product_id": args.product_id,
        "product_family": args.product_family,
        "removed": removed,
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
