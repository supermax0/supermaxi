import type { PaymentAccount } from "@/api/finora/pos";

export interface BankOption {
  id: number;
  name: string;
  /** Shown only when accounts from several branches are listed. */
  branch: string | null;
}

/**
 * Non-cash treasury accounts the cashier can collect into. FINORA lists every
 * branch's accounts for a general admin, so the same names repeat per branch:
 * keep this branch's accounts (plus unassigned ones) and only fall back to all
 * branches — labelled — when this branch has none.
 */
export function bankAccountsFor(accounts: PaymentAccount[], branchId: number | null): BankOption[] {
  const seen = new Set<number>();
  const banks = accounts.filter((a) => a.type.toLowerCase() !== "cash" && !seen.has(a.id) && seen.add(a.id));
  const local = branchId ? banks.filter((a) => a.branch_id === branchId || a.branch_id === null) : banks;
  const list = local.length > 0 ? local : banks;
  const multiBranch = new Set(list.map((a) => a.branch_id).filter((id) => id !== null)).size > 1;
  return list
    .map((a) => ({ id: a.id, name: a.name, branch: multiBranch ? (a.branch_name ?? null) : null }))
    .sort(
      (a, b) => (a.branch ?? "").localeCompare(b.branch ?? "", "ar") || a.name.localeCompare(b.name, "ar"),
    );
}
