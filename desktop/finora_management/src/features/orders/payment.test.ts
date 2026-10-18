import type { PaymentAccount } from "@/api/finora/pos";
import {
  accountsForBranch,
  collectionDue,
  defaultAccount,
  nextAccount,
  paymentProblem,
  syncSingleAllocation,
  toAllocations,
} from "./payment";

const account = (id: number, type: string, branch: number | null, isDefault = false): PaymentAccount => ({
  id,
  name: `acc ${id}`,
  type,
  is_default: isDefault,
  branch_id: branch,
  branch_name: null,
  label: `acc ${id}`,
});

const accounts = [
  account(1, "bank", 1),
  account(2, "cash", 1, true),
  account(3, "cash", 2, true),
  account(4, "bank", 1),
];

describe("collectionDue", () => {
  it("follows FINORA's effective paid amount", () => {
    expect(collectionDue(100_000, 0, "غير مسدد")).toBe(100_000);
    expect(collectionDue(100_000, 30_000, "جزئي")).toBe(70_000);
    // paid_amount on an unpaid order is not counted by FINORA
    expect(collectionDue(100_000, 30_000, "غير مسدد")).toBe(100_000);
    expect(collectionDue(100_000, 100_000, "مسدد")).toBe(0);
    expect(collectionDue(100_000, 0, "مرتجع")).toBe(0);
  });
});

describe("accounts", () => {
  it("keeps only the order branch and defaults to its cash box", () => {
    const branch1 = accountsForBranch(accounts, 1);
    expect(branch1.map((a) => a.id)).toEqual([1, 2, 4]);
    expect(defaultAccount(branch1)?.id).toBe(2);
    expect(accountsForBranch(accounts, null)).toHaveLength(4);
  });

  it("suggests an unused bank account for a split", () => {
    expect(nextAccount(accounts, [2])?.id).toBe(1);
    expect(nextAccount(accounts, [2, 1])?.id).toBe(4);
    expect(nextAccount([account(9, "cash", 1)], [9])).toBeNull();
  });
});

describe("paymentProblem", () => {
  const base = { mode: "full" as const, due: 100_000, amount: 0, deliveryFee: 0 };

  it("accepts a split whose sum equals the due", () => {
    expect(
      paymentProblem({
        ...base,
        allocations: [
          { key: 1, accountId: 2, amount: 60_000 },
          { key: 2, accountId: 1, amount: 40_000 },
        ],
      }),
    ).toBeNull();
  });

  it("explains every rejection FINORA would make", () => {
    expect(paymentProblem({ ...base, due: 0, allocations: [] })).toMatch(/مسدد بالكامل/);
    expect(paymentProblem({ ...base, allocations: [{ key: 1, accountId: 2, amount: 90_000 }] })).toMatch(
      /أقل/,
    );
    expect(paymentProblem({ ...base, allocations: [{ key: 1, accountId: null, amount: 100_000 }] })).toMatch(
      /اختر الحساب/,
    );
    expect(
      paymentProblem({
        ...base,
        mode: "partial",
        amount: 120_000,
        allocations: [{ key: 1, accountId: 2, amount: 120_000 }],
      }),
    ).toMatch(/يتجاوز/);
    expect(paymentProblem({ ...base, mode: "partial", amount: 0, allocations: [] })).toMatch(/الجزئي/);
    expect(
      paymentProblem({
        ...base,
        mode: "partial",
        amount: 25_000,
        allocations: [{ key: 1, accountId: 2, amount: 25_000 }],
      }),
    ).toBeNull();
  });
});

describe("allocations", () => {
  it("merges rows on the same account and drops empty rows", () => {
    expect(
      toAllocations([
        { key: 1, accountId: 2, amount: 10 },
        { key: 2, accountId: 2, amount: 5 },
        { key: 3, accountId: 1, amount: 0 },
      ]),
    ).toEqual([{ treasury_account_id: 2, amount: 15 }]);
  });

  it("lets a single row follow the amount but leaves splits alone", () => {
    expect(syncSingleAllocation([{ key: 1, accountId: 2, amount: 10 }], 30)).toEqual([
      { key: 1, accountId: 2, amount: 30 },
    ]);
    const split = [
      { key: 1, accountId: 2, amount: 10 },
      { key: 2, accountId: 1, amount: 5 },
    ];
    expect(syncSingleAllocation(split, 30)).toBe(split);
  });
});
