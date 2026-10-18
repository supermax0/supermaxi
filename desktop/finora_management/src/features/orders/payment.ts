/**
 * Order collection rules mirrored from FINORA's POST /orders/payment so the
 * dialog can explain a problem before sending. FINORA re-validates everything.
 */
import type { PaymentAccount } from "@/api/finora/pos";

/** FINORA accepts at most 8 payment allocations per collection. */
export const MAX_ALLOCATIONS = 8;

export type PaymentMode = "full" | "partial";

export interface AllocationDraft {
  key: number;
  accountId: number | null;
  amount: number;
}

/** Amount still to collect — FINORA's `total − effective paid` (utils/cash_calculations.py). */
export function collectionDue(total: number, paidAmount: number, paymentStatus: string): number {
  const status = paymentStatus.trim();
  if (status === "مسدد") return 0;
  if (["مرتجع", "ملغي", "راجع", "راجعة"].includes(status)) return 0;
  const effective = status === "جزئي" ? Math.min(Math.max(paidAmount, 0), Math.max(total, 0)) : 0;
  return Math.max(0, total - effective);
}

/** Collections must land in an account of the order's (stock) branch. */
export function accountsForBranch(accounts: PaymentAccount[], branchId: number | null): PaymentAccount[] {
  return branchId ? accounts.filter((account) => account.branch_id === branchId) : accounts;
}

/** Same default as FINORA's web dialog: the branch's default cash box, else the first account. */
export function defaultAccount(accounts: PaymentAccount[]): PaymentAccount | null {
  return accounts.find((account) => account.type === "cash" && account.is_default) ?? accounts[0] ?? null;
}

/** Next account for a split: an unused bank account first (cash + transfer is the common case). */
export function nextAccount(accounts: PaymentAccount[], used: Array<number | null>): PaymentAccount | null {
  const taken = new Set(used);
  const free = accounts.filter((account) => !taken.has(account.id));
  return free.find((account) => account.type === "bank") ?? free[0] ?? null;
}

export function allocatedTotal(allocations: AllocationDraft[]): number {
  return allocations.reduce((sum, allocation) => sum + allocation.amount, 0);
}

export interface PaymentDraft {
  mode: PaymentMode;
  due: number;
  /** Partial amount; ignored for full collection. */
  amount: number;
  deliveryFee: number;
  allocations: AllocationDraft[];
}

export function targetAmount(draft: Pick<PaymentDraft, "mode" | "due" | "amount">): number {
  return draft.mode === "full" ? draft.due : draft.amount;
}

/** First problem that FINORA would reject, in the user's words; null when sendable. */
export function paymentProblem(draft: PaymentDraft): string | null {
  if (draft.due <= 0) return "هذا الطلب مسدد بالكامل.";
  const target = targetAmount(draft);
  if (draft.mode === "partial") {
    if (draft.amount <= 0) return "أدخل مبلغ التسديد الجزئي.";
    if (draft.amount > draft.due) return "مبلغ التسديد الجزئي يتجاوز المستحق.";
  }
  if (draft.deliveryFee < 0) return "أجرة التوصيل غير صحيحة.";
  if (draft.allocations.length === 0) return "اختر طريقة استلام المبلغ.";
  if (draft.allocations.length > MAX_ALLOCATIONS) return `الحد الأعلى ${MAX_ALLOCATIONS} دفعات.`;
  if (draft.allocations.some((a) => a.accountId === null)) return "اختر الحساب لكل دفعة.";
  if (draft.allocations.some((a) => a.amount <= 0)) return "كل دفعة تحتاج مبلغاً أكبر من صفر.";
  const sum = allocatedTotal(draft.allocations);
  if (sum !== target) {
    return sum < target ? "مجموع الدفعات أقل من المبلغ المطلوب." : "مجموع الدفعات أكبر من المبلغ المطلوب.";
  }
  return null;
}

/** Merge rows that use the same account (FINORA combines them the same way). */
export function toAllocations(
  allocations: AllocationDraft[],
): Array<{ treasury_account_id: number; amount: number }> {
  const combined = new Map<number, number>();
  for (const allocation of allocations) {
    if (allocation.accountId === null || allocation.amount <= 0) continue;
    combined.set(allocation.accountId, (combined.get(allocation.accountId) ?? 0) + allocation.amount);
  }
  return [...combined].map(([treasury_account_id, amount]) => ({ treasury_account_id, amount }));
}

/** After the target changes, a single row follows it; split rows keep what the user typed. */
export function syncSingleAllocation(allocations: AllocationDraft[], target: number): AllocationDraft[] {
  const [only] = allocations;
  if (allocations.length !== 1 || !only || only.amount === target) return allocations;
  return [{ ...only, amount: target }];
}
