import { defaultMessage, errorFromResponse, FinoraApiError, toFinoraError } from "./errors";

describe("error layer", () => {
  it.each([
    [400, "validation"],
    [401, "unauthenticated"],
    [403, "forbidden"],
    [404, "not_found"],
    [409, "conflict"],
    [429, "rate_limited"],
    [500, "server"],
    [502, "server"],
  ] as const)("HTTP %i → %s", (status, kind) => {
    expect(errorFromResponse({ ok: false, failure: "http", status, data: null }).kind).toBe(kind);
  });

  it("keeps FINORA's Arabic message for the user and hides English technical text", () => {
    const arabic = errorFromResponse({
      ok: false,
      failure: "http",
      status: 400,
      data: { error: "حالة التحويل الجماعي غير صالحة" },
    });
    expect(arabic.message).toBe("حالة التحويل الجماعي غير صالحة");
    const english = errorFromResponse({
      ok: false,
      failure: "http",
      status: 403,
      data: { error: "Unauthorized" },
    });
    expect(english.message).toBe(defaultMessage("forbidden"));
  });

  it("a rejected sign-in (401 invalid_credentials) is not an ended session", () => {
    const error = errorFromResponse({
      ok: false,
      failure: "http",
      status: 401,
      data: { ok: false, error: "بيانات الدخول غير صحيحة", code: "invalid_credentials" },
    });
    expect(error.kind).toBe("invalid_credentials");
    expect(error.endsSession).toBe(false);
    expect(error.message).toBe("بيانات الدخول غير صحيحة");
  });

  it("reads the typed code from {ok:false, code} payloads", () => {
    const error = errorFromResponse({
      ok: false,
      failure: "http",
      status: 429,
      data: { ok: false, code: "rate_limited" },
    });
    expect(error).toMatchObject({ kind: "rate_limited", code: "rate_limited", status: 429 });
  });

  it("maps transport failures and classifies session/connectivity errors", () => {
    expect(errorFromResponse({ ok: false, failure: "timeout" }).isConnectivity).toBe(true);
    expect(errorFromResponse({ ok: false, failure: "network" }).isConnectivity).toBe(true);
    expect(errorFromResponse({ ok: false, failure: "unauthenticated", status: 302 }).endsSession).toBe(true);
    expect(errorFromResponse({ ok: false, failure: "password_change_required" }).endsSession).toBe(true);
    expect(errorFromResponse({ ok: false, failure: "http", status: 500, data: null }).endsSession).toBe(
      false,
    );
  });

  it("wraps unknown errors without losing the technical detail", () => {
    const wrapped = toFinoraError(new TypeError("boom"));
    expect(wrapped).toBeInstanceOf(FinoraApiError);
    expect(wrapped.kind).toBe("invalid_response");
    expect(wrapped.detail).toBe("boom");
    expect(wrapped.message).toMatch(/[؀-ۿ]/);
  });
});
