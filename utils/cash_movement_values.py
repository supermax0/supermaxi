"""Normalize values without rewriting legacy signed movement records."""


def movement_amount(row):
    return abs(int(row.get("amount") or 0))


def signed_movement_amount(row):
    if row.get("type") == "cash_in":
        return movement_amount(row)
    if row.get("type") == "cash_out":
        return -movement_amount(row)
    return 0
