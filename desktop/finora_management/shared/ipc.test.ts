import {
  finoraRequestSchema,
  finoraPagePathSchema,
  finoraFormSchema,
  MAX_UPLOAD_BYTES,
  printPath,
  printRequestSchema,
  rememberIdentitySchema,
  requestPathSchema,
  serverUrlSchema,
} from "./ipc";

describe("IPC validation", () => {
  it("prints only a validated customer history and explicit date range", () => {
    expect(
      printPath(
        printRequestSchema.parse({
          kind: "customer_history",
          id: 8,
          date_from: "2026-01-01",
          date_to: "2026-10-12",
        }),
      ),
    ).toBe("/api/v1/desktop/customers/8/account-history/print?date_from=2026-01-01&date_to=2026-10-12");
    expect(
      printRequestSchema.safeParse({
        kind: "customer_history",
        id: 8,
        date_from: "2026-01-01&url=https://evil.test",
      }).success,
    ).toBe(false);
    expect(
      printRequestSchema.safeParse({ kind: "customer_history", id: 8, url: "https://evil.test" }).success,
    ).toBe(false);
  });
  it("restricts audit session links to this server and one positive session parameter", () => {
    for (const path of ["/inventory/smart-audit", "/inventory/smart-audit?session=123"])
      expect(finoraPagePathSchema.safeParse(path).success).toBe(true);
    for (const path of [
      "https://evil.test/inventory/smart-audit",
      "/inventory/smart-audit?session=-1",
      "/inventory/smart-audit?session=0",
      "/inventory/smart-audit?session=1&redirect=https://evil.test",
      "/inventory/smart-audit?session=../../login",
      "/inventory/smart-audit?session=1#x",
    ])
      expect(finoraPagePathSchema.safeParse(path).success).toBe(false);
  });
  it("restricts customer statement printing to a positive source identifier", () => {
    expect(printPath(printRequestSchema.parse({ kind: "customer_statement", id: 3 }))).toBe(
      "/api/v1/desktop/customers/3/statement/print",
    );
    for (const id of [0, -1, 1.5, "../../login"]) {
      expect(printRequestSchema.safeParse({ kind: "customer_statement", id }).success).toBe(false);
    }
    expect(
      printRequestSchema.safeParse({ kind: "customer_statement", id: 3, url: "https://evil.test" }).success,
    ).toBe(false);
  });
  it("restricts collection-history printing to its authenticated source route", () => {
    expect(printPath(printRequestSchema.parse({ kind: "customer_transactions", id: 3 }))).toBe(
      "/api/v1/desktop/customers/3/transactions/print",
    );
    for (const id of [0, -1, 1.5, "../../login"])
      expect(printRequestSchema.safeParse({ kind: "customer_transactions", id }).success).toBe(false);
    expect(
      printRequestSchema.safeParse({ kind: "customer_transactions", id: 3, url: "https://evil.test" })
        .success,
    ).toBe(false);
  });
  it("limits finance printing to validated source identifiers and known reports", () => {
    expect(printPath(printRequestSchema.parse({ kind: "finance_voucher", id: 9 }))).toBe(
      "/accounts/finance/vouchers/9/print",
    );
    expect(printPath(printRequestSchema.parse({ kind: "finance_loan", id: 4 }))).toBe(
      "/accounts/finance/loans/4/print",
    );
    expect(
      printPath(
        printRequestSchema.parse({ kind: "finance_report", report: "profit-loss", date_from: "2026-10-01" }),
      ),
    ).toContain("/reports/profit-loss/print?date_from=2026-10-01");
    expect(printRequestSchema.safeParse({ kind: "finance_report", report: "../../login" }).success).toBe(
      false,
    );
    expect(
      printRequestSchema.safeParse({ kind: "finance_voucher", id: 9, url: "https://evil.test" }).success,
    ).toBe(false);
  });
  it("validates multiple photo fields, total size and duplicate fields", () => {
    const file = { field: "color_image_0", name: "white.png", type: "image/png", data: new Uint8Array(3) };
    const form = { path: "/inventory/add", fields: [], files: [file, { ...file, field: "color_image_1" }] };
    expect(finoraFormSchema.safeParse(form).success).toBe(true);
    expect(finoraFormSchema.safeParse({ ...form, file }).success).toBe(false);
    expect(finoraFormSchema.safeParse({ ...form, files: [{ ...file, field: 'bad"field' }] }).success).toBe(
      false,
    );
    expect(
      finoraFormSchema.safeParse({
        ...form,
        files: Array.from({ length: 5 }, (_, i) => ({
          ...file,
          field: `color_image_${i}`,
          data: new Uint8Array(MAX_UPLOAD_BYTES),
        })),
      }).success,
    ).toBe(false);
  });
  it("opens only validated supplier statements on the existing FINORA print route", () => {
    const request = printRequestSchema.parse({ kind: "supplier", id: 3 });
    expect(printPath(request)).toBe("/suppliers/statement/print/3");
    expect(printRequestSchema.safeParse({ kind: "supplier", id: -1 }).success).toBe(false);
    expect(printRequestSchema.safeParse({ kind: "supplier", id: 3, url: "https://evil.test" }).success).toBe(
      false,
    );
  });
  it.each([
    "/api/v1/desktop/auth/session",
    "/orders/data",
    "/orders/bulk-status",
    "/purchases/api/list",
    "/inventory/api/movements/12",
  ])("allows FINORA path %s", (path) => {
    expect(requestPathSchema.safeParse(path).success).toBe(true);
  });

  it.each([
    "https://evil.test/orders/data",
    "//evil.test/orders/data",
    "/orders/../superadmin/tenants",
    "/orders/./data",
    "/superadmin/tenants",
    "/login",
    "/orders/data?x=1",
    "/orders\\data",
    "orders/data",
  ])("refuses %s", (path) => {
    expect(requestPathSchema.safeParse(path).success).toBe(false);
  });

  it("rejects unknown fields and non-JSON bodies", () => {
    expect(
      finoraRequestSchema.safeParse({ method: "GET", path: "/orders/data", headers: { Cookie: "x" } })
        .success,
    ).toBe(false);
    expect(finoraRequestSchema.safeParse({ method: "DELETE", path: "/orders/data" }).success).toBe(false);
    expect(
      finoraRequestSchema.safeParse({
        method: "POST",
        path: "/orders/bulk-status",
        body: { order_ids: [1, 2], status: "معباة" },
      }).success,
    ).toBe(true);
  });

  it("normalizes server addresses to a bare origin", () => {
    expect(serverUrlSchema.parse(" https://finora.company/ ")).toBe("https://finora.company");
    expect(serverUrlSchema.parse("http://localhost:5008")).toBe("http://localhost:5008");
  });

  it.each([
    "file:///c:/x",
    "javascript:alert(1)",
    "https://user:pw@finora.company",
    "https://finora.company/app",
    "nope",
  ])("refuses server address %s", (value) => {
    expect(serverUrlSchema.safeParse(value).success).toBe(false);
  });

  it("validates remembered identity (no passwords)", () => {
    expect(rememberIdentitySchema.parse({ tenantSlug: " ACME ", username: "sara" })).toEqual({
      tenantSlug: "acme",
      username: "sara",
    });
    expect(
      rememberIdentitySchema.safeParse({ tenantSlug: "acme", username: "sara", password: "x" }).success,
    ).toBe(false);
  });
});
