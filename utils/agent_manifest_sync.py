"""Keep reassigned orders out of their former agent's draft reports, in the same transaction."""
import json
import re

from sqlalchemy import event, inspect
from sqlalchemy.orm import Session


def agent_key(agent):
    name = " ".join(str(agent.name or "").split()).casefold()
    phone = "".join(ch for ch in str(agent.phone or "") if ch.isdigit())[-10:]
    return f"{name}|{phone}"


def _object(value, fallback):
    try:
        parsed = json.loads(value or "null")
        return parsed if isinstance(parsed, type(fallback)) else fallback
    except (ValueError, TypeError):
        return fallback


def visible_agent_rows(report, rows):
    """Read-only reconciliation also covers drafts left stale before this feature was installed."""
    from flask import has_app_context
    if not has_app_context() or getattr(report, "is_executed", False):
        return rows
    meta = _object(getattr(report, "notes", None), {})
    match = re.match(r"^AGT-(\d+)-", getattr(report, "report_number", "") or "")
    try:
        owner = int(match[1] if match else meta.get("agent_id") or 0)
    except (TypeError, ValueError):
        return rows
    if not owner:
        return rows
    from models.delivery_agent import DeliveryAgent
    from models.invoice import Invoice
    agent = DeliveryAgent.query.get(owner)
    aliases = {owner} if agent is None else {row.id for row in DeliveryAgent.query.all() if agent_key(row) == agent_key(agent)}
    ids = {str(row.get("id") or row.get("order_id")) for row in rows if isinstance(row, dict)}
    orders = {str(row.id): row.delivery_agent_id for row in Invoice.query.filter(Invoice.id.in_([int(oid) for oid in ids if oid.isdigit()])).all()}
    return [row for row in rows if not isinstance(row, dict) or str(row.get("id") or row.get("order_id")) not in orders
            or orders[str(row.get("id") or row.get("order_id"))] in aliases]


def _sync_agent_drafts(session, flush_context, instances):
    from models.invoice import Invoice
    from models.delivery_agent import DeliveryAgent
    from models.shipping_report import ShippingReport

    changed = {order.id: order.delivery_agent_id for order in session.dirty
               if isinstance(order, Invoice) and inspect(order).attrs.delivery_agent_id.history.has_changes()}
    if not changed:
        return
    schema = inspect(session.connection(bind_arguments={"mapper": inspect(Invoice)}))
    if not schema.has_table(ShippingReport.__tablename__) or not set(ShippingReport.__table__.columns.keys()).issubset({column["name"] for column in schema.get_columns(ShippingReport.__tablename__)}):
        return
    agents = {agent.id: agent_key(agent) for agent in session.query(DeliveryAgent).all()}
    for report in session.query(ShippingReport).filter(ShippingReport.is_executed.is_(False)).with_for_update().all():
        if report.is_executed or report in session.deleted:
            continue
        meta = _object(report.notes, {})
        match = re.match(r"^AGT-(\d+)-", report.report_number or "")
        try:
            owner = int(match[1] if match else meta.get("agent_id") or 0)
        except (TypeError, ValueError):
            continue
        if not owner:
            continue  # A carrier report is independent of an order's delivery agent.
        removed = {oid for oid, agent in changed.items()
                   if agent != owner and (agent is None or owner not in agents or agents.get(agent) != agents[owner])}
        rows = _object(report.orders_data, [])
        if not removed or not all(isinstance(row, dict) for row in rows):
            continue
        removed_ids = {str(i) for i in removed}
        kept = [row for row in rows if str(row.get("id") or row.get("order_id")) not in removed_ids]
        if len(kept) == len(rows):
            continue
        selections = _object(report.order_status_selections, {})
        for oid in removed:
            selections.pop(str(oid), None)
            if isinstance(meta.get("agent_claim"), dict):
                meta["agent_claim"].pop(str(oid), None)
        report.orders_data = json.dumps(kept, ensure_ascii=False)
        report.orders_count = len(kept)
        from utils.agent_report_helpers import row_collectible_amount
        report.total_amount = sum(row_collectible_amount(row) for row in kept)
        report.order_status_selections = json.dumps(selections, ensure_ascii=False)
        if "agent_claim" in meta:
            report.notes = json.dumps(meta, ensure_ascii=False)


def install_agent_manifest_sync():
    if not event.contains(Session, "before_flush", _sync_agent_drafts):
        event.listen(Session, "before_flush", _sync_agent_drafts)
