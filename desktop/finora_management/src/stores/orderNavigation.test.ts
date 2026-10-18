import { sessionSchema } from "@/api/finora/schemas";
import { SESSION_PAYLOAD } from "@/test/mockBridge";
import { useSession } from "./session";
import { useOrderNavigation } from "./orderNavigation";

const session = () => sessionSchema.parse({ ...SESSION_PAYLOAD, permissions: ["can_see_orders"] });

describe("source-document navigation scope", () => {
  beforeEach(() => {
    useSession.getState().signedOut(null);
    useOrderNavigation.getState().clear();
  });
  it("keeps a pending invoice during same-session revalidation and clears it on logout", () => {
    const active = session();
    useSession.getState().signedIn(active);
    useOrderNavigation.getState().open(10);
    useSession.getState().signedIn({ ...active, user: { ...active.user, name: "اسم محدث" } });
    expect(useOrderNavigation.getState().invoiceId).toBe(10);
    useSession.getState().signedOut("expired");
    expect(useOrderNavigation.getState().invoiceId).toBeNull();
  });
  it.each(["tenant", "user", "branch"] as const)(
    "does not carry a previous invoice into another %s",
    (kind) => {
      const active = session();
      useSession.getState().signedIn(active);
      useOrderNavigation.getState().open(10);
      useSession.getState().signedIn({
        ...active,
        ...(kind === "tenant" ? { tenant: { ...active.tenant, slug: "another" } } : {}),
        ...(kind === "user" ? { user: { ...active.user, id: 99 } } : {}),
        ...(kind === "branch" ? { branch: { id: 99, name: "فرع آخر" } } : {}),
      });
      expect(useOrderNavigation.getState().invoiceId).toBeNull();
    },
  );
});
