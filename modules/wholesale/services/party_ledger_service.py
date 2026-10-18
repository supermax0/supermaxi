"""Unified customer/supplier ledger + statement builder."""
from __future__ import annotations

from datetime import date
from io import BytesIO, StringIO

from sqlalchemy import or_

from extensions import db
from modules.wholesale.models.party_ledger import PartyLedgerEntry
from modules.wholesale.services.helpers import (
    WholesaleError,
    normalize_currency,
    parse_date,
    to_base_amount,
)


def _base_query(tenant_id: int | None, party_type: str, party_id: int):
    q = PartyLedgerEntry.query.filter(
        PartyLedgerEntry.party_type == party_type,
        PartyLedgerEntry.party_id == party_id,
        PartyLedgerEntry.deleted_at.is_(None),
    )
    if tenant_id is not None:
        q = q.filter(or_(PartyLedgerEntry.tenant_id == tenant_id, PartyLedgerEntry.tenant_id.is_(None)))
    return q


def party_balance(tenant_id: int | None, party_type: str, party_id: int, currency: str | None = None) -> int:
    """Balance = debit - credit (AR for customer, AP for supplier)."""
    q = _base_query(tenant_id, party_type, party_id)
    if currency:
        q = q.filter(PartyLedgerEntry.currency == normalize_currency(currency))
    debit = credit = 0
    for row in q.all():
        debit += int(row.debit or 0)
        credit += int(row.credit or 0)
    return debit - credit


def add_entry(
    tenant_id: int | None,
    *,
    party_type: str,
    party_id: int,
    entry_date: date,
    entry_type: str,
    debit: int = 0,
    credit: int = 0,
    currency: str = "IQD",
    exchange_rate: float = 1.0,
    doc_no: str | None = None,
    description: str | None = None,
    reference_type: str | None = None,
    reference_id: int | None = None,
    created_by: int | None = None,
) -> PartyLedgerEntry:
    if party_type not in ("customer", "supplier"):
        raise WholesaleError("نوع الطرف غير صالح")
    currency = normalize_currency(currency)
    amount = abs(int(debit or 0) - int(credit or 0))
    bal = party_balance(tenant_id, party_type, party_id, currency) + int(debit or 0) - int(credit or 0)
    entry = PartyLedgerEntry(
        tenant_id=tenant_id,
        party_type=party_type,
        party_id=party_id,
        entry_date=entry_date,
        doc_no=doc_no,
        entry_type=entry_type,
        description=description,
        debit=int(debit or 0),
        credit=int(credit or 0),
        balance_after=bal,
        currency=currency,
        exchange_rate=float(exchange_rate or 1),
        amount_base=to_base_amount(amount, currency, exchange_rate),
        reference_type=reference_type,
        reference_id=reference_id,
        created_by=created_by,
    )
    db.session.add(entry)
    db.session.flush()
    return entry


def soft_delete_by_reference(
    tenant_id: int | None,
    reference_type: str,
    reference_id: int,
) -> int:
    q = PartyLedgerEntry.query.filter(
        PartyLedgerEntry.reference_type == reference_type,
        PartyLedgerEntry.reference_id == reference_id,
        PartyLedgerEntry.deleted_at.is_(None),
    )
    if tenant_id is not None:
        q = q.filter(or_(PartyLedgerEntry.tenant_id == tenant_id, PartyLedgerEntry.tenant_id.is_(None)))
    count = 0
    now = date.today()
    from datetime import datetime

    for row in q.all():
        row.deleted_at = datetime.utcnow()
        count += 1
    return count


def build_statement(
    tenant_id: int | None,
    *,
    party_type: str,
    party_id: int,
    date_from: date | str | None = None,
    date_to: date | str | None = None,
    currency: str | None = None,
) -> dict:
    d_from = parse_date(date_from, date(1970, 1, 1)) if date_from else date(1970, 1, 1)
    d_to = parse_date(date_to, date.today()) if date_to else date.today()
    currency = normalize_currency(currency) if currency else None

    q = _base_query(tenant_id, party_type, party_id).order_by(
        PartyLedgerEntry.entry_date.asc(), PartyLedgerEntry.id.asc()
    )
    if currency:
        q = q.filter(PartyLedgerEntry.currency == currency)

    opening_debit = opening_credit = 0
    rows = []
    period_debit = period_credit = 0
    running = 0

    for entry in q.all():
        if entry.entry_date < d_from:
            opening_debit += int(entry.debit or 0)
            opening_credit += int(entry.credit or 0)
            continue
        if entry.entry_date > d_to:
            continue
        if not rows:
            running = opening_debit - opening_credit
        running += int(entry.debit or 0) - int(entry.credit or 0)
        period_debit += int(entry.debit or 0)
        period_credit += int(entry.credit or 0)
        item = entry.to_dict()
        item["balance_after"] = running
        rows.append(item)

    opening = opening_debit - opening_credit
    if not rows:
        running = opening

    return {
        "party_type": party_type,
        "party_id": party_id,
        "date_from": d_from.isoformat(),
        "date_to": d_to.isoformat(),
        "currency": currency or "ALL",
        "opening_balance": opening,
        "total_debit": period_debit,
        "total_credit": period_credit,
        "closing_balance": running,
        "rows": rows,
    }


def statement_to_csv(statement: dict) -> str:
    buf = StringIO()
    buf.write("التاريخ,الرقم,النوع,البيان,مدين,دائن,الرصيد\n")
    for r in statement.get("rows") or []:
        desc = (r.get("description") or "").replace('"', "")
        buf.write(
            f"{r.get('entry_date')},{r.get('doc_no') or ''},{r.get('entry_type') or ''},"
            f'"{desc}",'
            f"{r.get('debit') or 0},{r.get('credit') or 0},{r.get('balance_after') or 0}\n"
        )
    return buf.getvalue()


def statement_to_xlsx_bytes(statement: dict) -> bytes:
    """Minimal XLSX-compatible TSV fallback if openpyxl unavailable."""
    try:
        from openpyxl import Workbook

        wb = Workbook()
        ws = wb.active
        ws.title = "Statement"
        ws.append(["التاريخ", "الرقم", "النوع", "البيان", "مدين", "دائن", "الرصيد"])
        for r in statement.get("rows") or []:
            ws.append(
                [
                    r.get("entry_date"),
                    r.get("doc_no"),
                    r.get("entry_type"),
                    r.get("description"),
                    r.get("debit") or 0,
                    r.get("credit") or 0,
                    r.get("balance_after") or 0,
                ]
            )
        ws.append([])
        ws.append(["رصيد أول المدة", statement.get("opening_balance")])
        ws.append(["إجمالي المدين", statement.get("total_debit")])
        ws.append(["إجمالي الدائن", statement.get("total_credit")])
        ws.append(["الرصيد النهائي", statement.get("closing_balance")])
        out = BytesIO()
        wb.save(out)
        return out.getvalue()
    except Exception:
        return statement_to_csv(statement).encode("utf-8-sig")
