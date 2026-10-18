import { sessionSchema } from "@/api/finora/schemas";
import { SESSION_PAYLOAD } from "@/test/mockBridge";
import { useSession } from "./session";
import { useFinanceNavigation } from "./financeNavigation";

const collection = { customerId: 1, customerName: "عميل", branchId: 1, invoiceId: 10, remaining: 200000 };
const session = () =>
  sessionSchema.parse({ ...SESSION_PAYLOAD, permissions: ["finance.view", "finance.create"] });

beforeEach(() => {
  useSession.getState().signedOut(null);
  useFinanceNavigation.getState().clear();
});

it("keeps collection context during same-user session verification and consumes it once", () => {
  const current = session();
  useSession.getState().signedIn(current);
  useFinanceNavigation.getState().collect(collection);
  useSession.getState().signedIn({ ...current, user: { ...current.user, name: "اسم محدث" } });
  expect(useFinanceNavigation.getState().collection).toEqual(collection);
  useFinanceNavigation.getState().clear();
  expect(useFinanceNavigation.getState().collection).toBeNull();
});

it.each(["tenant", "user", "branch", "logout"] as const)(
  "clears financial context when %s changes",
  (kind) => {
    const current = session();
    useSession.getState().signedIn(current);
    useFinanceNavigation.getState().collect(collection);
    if (kind === "logout") useSession.getState().signedOut("expired");
    else
      useSession.getState().signedIn({
        ...current,
        ...(kind === "tenant" ? { tenant: { ...current.tenant, slug: "another" } } : {}),
        ...(kind === "user" ? { user: { ...current.user, id: 99 } } : {}),
        ...(kind === "branch" ? { branch: { id: 99, name: "فرع آخر" } } : {}),
      });
    expect(useFinanceNavigation.getState().collection).toBeNull();
  },
);
