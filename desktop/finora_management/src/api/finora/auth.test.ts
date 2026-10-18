import { installMockBridge, removeMockBridge, SESSION_PAYLOAD } from "@/test/mockBridge";
import { FinoraApiError } from "./errors";
import { finora } from "./index";
import { onTransportOutcome } from "./transportEvents";

describe("finora.auth", () => {
  afterEach(() => removeMockBridge());

  it("signs in through the desktop endpoint, drops unknown permissions and remembers the identity", async () => {
    const bridge = installMockBridge(() => ({
      ok: true,
      status: 200,
      data: { ok: true, session: SESSION_PAYLOAD },
    }));
    const session = await finora.auth.signIn({ tenantSlug: "acme", username: "sara", password: "pw" });

    expect(bridge.finora.request).toHaveBeenCalledWith({
      method: "POST",
      path: "/api/v1/desktop/auth/login",
      body: { tenant_slug: "acme", username: "sara", password: "pw" },
    });
    expect(session.permissions).toEqual(["can_see_orders", "manage_orders"]);
    expect(bridge.config.rememberIdentity).toHaveBeenCalledWith({ tenantSlug: "acme", username: "sara" });
  });

  it("rejects malformed payloads as invalid_response instead of trusting them", async () => {
    installMockBridge(() => ({ ok: true, status: 200, data: { ok: true, session: { user: "nope" } } }));
    await expect(finora.auth.session()).rejects.toMatchObject({ kind: "invalid_response" });
  });

  it("surfaces FINORA's Arabic sign-in error", async () => {
    installMockBridge(() => ({
      ok: false,
      failure: "http",
      status: 401,
      data: { ok: false, error: "بيانات الدخول غير صحيحة", code: "invalid_credentials" },
    }));
    const failure = await finora.auth
      .signIn({ tenantSlug: "acme", username: "x", password: "y" })
      .catch((e: unknown) => e);
    expect(failure).toBeInstanceOf(FinoraApiError);
    expect((failure as FinoraApiError).code).toBe("invalid_credentials");
  });

  it("reports connectivity outcomes to app-level listeners", async () => {
    installMockBridge(() => ({ ok: false, failure: "network", detail: "ECONNREFUSED" }));
    const seen: Array<string | null> = [];
    const stop = onTransportOutcome((error) => seen.push(error?.kind ?? null));
    await finora.auth.session().catch(() => undefined);
    stop();
    expect(seen).toEqual(["network"]);
  });

  it("sign-out clears the local cookie jar even when the session already expired", async () => {
    const bridge = installMockBridge(() => ({ ok: false, failure: "unauthenticated", status: 302 }));
    await expect(finora.auth.signOut()).resolves.toBeUndefined();
    expect(bridge.finora.clearSession).toHaveBeenCalledTimes(1);
  });

  it("sign-out still clears locally but reports a server failure", async () => {
    const bridge = installMockBridge(() => ({ ok: false, failure: "http", status: 500, data: null }));
    await expect(finora.auth.signOut()).rejects.toMatchObject({ kind: "server" });
    expect(bridge.finora.clearSession).toHaveBeenCalledTimes(1);
  });
});
