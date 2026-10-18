import { buildRequestUrl, classifyResponse, requestHeaders } from "./httpCore";

const json = (status: number, body: unknown) => ({
  status,
  location: null,
  contentType: "application/json; charset=utf-8",
  bodyText: JSON.stringify(body),
});

describe("FINORA transport core", () => {
  it("builds URLs with repeated query params (FINORA reads getlist('city'))", () => {
    const url = buildRequestUrl("http://localhost:5008", {
      path: "/orders/data",
      query: { page: 2, city: ["بغداد", "البصرة"], search: "0770" },
    });
    const parsed = new URL(url);
    expect(parsed.pathname).toBe("/orders/data");
    expect(parsed.searchParams.getAll("city")).toEqual(["بغداد", "البصرة"]);
    expect(parsed.searchParams.get("page")).toBe("2");
  });

  it("asks FINORA for JSON answers and labels the client", () => {
    const headers = requestHeaders({ method: "POST", path: "/orders/bulk-status", body: {} }, "1.2.3");
    expect(headers).toMatchObject({
      Accept: "application/json",
      "X-Requested-With": "XMLHttpRequest",
      "X-Finora-Client": "management-desktop/1.2.3",
      "Content-Type": "application/json",
    });
    expect(requestHeaders({ method: "GET", path: "/orders/data" }, "1")).not.toHaveProperty("Content-Type");
  });

  it("treats login redirects as an ended session and change-password redirects distinctly", () => {
    expect(
      classifyResponse({ status: 302, location: "/login", contentType: "text/html", bodyText: "" }),
    ).toMatchObject({
      ok: false,
      failure: "unauthenticated",
    });
    expect(
      classifyResponse({
        status: 302,
        location: "/account/change-password",
        contentType: null,
        bodyText: "",
      }),
    ).toMatchObject({ ok: false, failure: "password_change_required" });
    expect(
      classifyResponse({ status: 302, location: "/pos/login", contentType: null, bodyText: "" }),
    ).toMatchObject({ ok: false, failure: "unauthenticated" });
  });

  it("treats a permission redirect (still signed in) as forbidden, never as a sign-out", () => {
    for (const location of ["/pos", "/", "http://finora.test/pricing"]) {
      expect(
        classifyResponse({ status: 302, location, contentType: "text/html", bodyText: "" }),
      ).toMatchObject({
        ok: false,
        failure: "http",
        status: 403,
      });
    }
  });

  it("recognises FINORA's JSON password-change block", () => {
    expect(classifyResponse(json(403, { ok: false, error: "password_change_required" }))).toMatchObject({
      failure: "password_change_required",
    });
  });

  it("passes JSON success and HTTP errors through with their payload", () => {
    expect(classifyResponse(json(200, { ok: true }))).toEqual({ ok: true, status: 200, data: { ok: true } });
    expect(classifyResponse(json(400, { error: "x" }))).toEqual({
      ok: false,
      failure: "http",
      status: 400,
      data: { error: "x" },
    });
  });

  it("refuses HTML or malformed bodies instead of guessing", () => {
    expect(
      classifyResponse({ status: 200, location: null, contentType: "text/html", bodyText: "<html>" }),
    ).toMatchObject({
      failure: "invalid_response",
    });
    expect(
      classifyResponse({ status: 200, location: null, contentType: "application/json", bodyText: "{oops" }),
    ).toMatchObject({ failure: "invalid_response" });
  });
});
