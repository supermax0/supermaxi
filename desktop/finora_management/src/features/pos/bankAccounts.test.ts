import type { PaymentAccount } from "@/api/finora/pos";
import { bankAccountsFor } from "./bankAccounts";

const acc = (
  id: number,
  name: string,
  type: string,
  branch_id: number | null,
  branch_name: string | null,
): PaymentAccount => ({
  id,
  name,
  type,
  is_default: false,
  branch_id,
  branch_name,
  label: "",
});

describe("bankAccountsFor", () => {
  const accounts = [
    acc(1, "Cash", "cash", 1, "B1"),
    acc(2, "Master", "bank", 1, "B1"),
    acc(3, "Master", "bank", 2, "B2"),
    acc(4, "KiCard", "bank", 2, "B2"),
    acc(5, "Shared", "bank", null, null),
    acc(2, "Master", "bank", 1, "B1"),
  ];

  it("keeps only this branch's (and unassigned) non-cash accounts, without duplicates", () => {
    expect(bankAccountsFor(accounts, 1).map((a) => a.id)).toEqual([2, 5]);
  });

  it("labels the branch when several branches are listed (admin without a branch)", () => {
    const all = bankAccountsFor(accounts, null);
    expect(all).toHaveLength(4);
    expect(all.find((a) => a.id === 3)?.branch).toBe("B2");
  });

  it("falls back to every branch when this branch has no bank account", () => {
    expect(
      bankAccountsFor([acc(9, "Cash", "cash", 7, "B7"), acc(3, "Master", "bank", 2, "B2")], 7).map(
        (a) => a.id,
      ),
    ).toEqual([3]);
  });
});
