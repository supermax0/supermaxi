import { expect, test } from "@playwright/test";
import { DevDataSource } from "../src/data/devSource";
import type { AccountView, SupportIssue } from "../src/data/accounts";
import type { Approval } from "../src/data/schemas";

test("client account setup stays in the existing design and requires a scoped review", async ({
  page,
}, testInfo) => {
  const source = new DevDataSource({ simulate: false, latency: 0 });
  const conversations = await source.listConversations({ channel: "all", filter: "all", search: "" });
  const conversation = conversations.find((row) => row.id === "c6");
  const profile = await source.getCustomer("c6");
  const operator = {
    id: 1,
    username: "owner",
    role: "super_admin",
    permissions: [
      "conversations.view",
      "messages.send",
      "ai.takeover",
      "notes.write",
      "audit.view",
      "settings.manage",
      "approvals.decide",
      "tenants.create",
    ],
  };
  const account: AccountView = {
    customerId: "7",
    tenantSlug: "flowers-a",
    linked: true,
    error: null,
    profiles: [
      { key: "general", label: "شركة عامة", needs: "البيع والطلبات والمخزون والحسابات" },
      { key: "starter_business", label: "إدارة أعمال مبسّطة", needs: "البيع السريع والطلبات والموردون" },
      { key: "beauty_center", label: "مركز تجميل", needs: "المواعيد والخدمات والجلسات والعملاء" },
      { key: "hr_management", label: "إدارة الموارد البشرية", needs: "الموظفون والحضور والإجازات والرواتب" },
      { key: "flowers", label: "محل ورد وهدايا", needs: "المناسبات والطلبات والزبائن والمخزون" },
      { key: "wholesale", label: "تاجر جملة", needs: "المخازن والموردون والديون" },
      { key: "grocery", label: "مواد غذائية", needs: "الكاشير والمشتريات والمخزون" },
      { key: "clinic", label: "عيادة", needs: "المرضى والمواعيد والفواتير" },
      { key: "dental_clinic", label: "عيادة أسنان", needs: "العيادة ومخطط الأسنان وخطط العلاج" },
    ],
    permissionPresets: [
      { key: "sales", label: "مبيعات وكاشير" },
      { key: "reception", label: "استقبال" },
    ],
    account: {
      companyName: "ورد الربيع",
      tenantSlug: "flowers-a",
      businessType: "starter_business",
      version: "v1",
      features: [
        { key: "reports", label: "التقارير", available: true, enabled: true, protected: false },
        { key: "clinics", label: "العيادات", available: true, enabled: true, protected: false },
      ],
      employees: [
        { id: 1, name: "المالك", username: "admin", owner: true, active: true, permissions: {}, roleIds: [] },
        { id: 2, name: "سارة", username: "sara", owner: false, active: true, permissions: {}, roleIds: [] },
      ],
      roles: [{ id: 1, name: "الاستقبال", permissions: ["clinics.reception.view"] }],
    },
  };
  const issues: SupportIssue[] = [
    {
      id: "issue1",
      conversationId: "c6",
      customerName: "ورد الربيع",
      tenantSlug: "flowers-a",
      kind: "bug",
      title: "العميل أبلغ عن خلل",
      details: "تحتاج مراجعة حفظ التقارير",
      verified: false,
      status: "open",
      at: new Date().toISOString(),
    },
  ];
  let approval: Approval | null = null;
  let decisions = 0;
  await page.addInitScript(
    (value) =>
      sessionStorage.setItem(
        "finora-core.session",
        JSON.stringify({ accessToken: "account-test-token", refreshToken: "fake", operator: value }),
      ),
    operator,
  );
  await page.route("http://127.0.0.1:5019/**", async (route) => {
    const request = route.request();
    const pathname = new URL(request.url()).pathname;
    const headers = {
      "Access-Control-Allow-Origin": "*",
      "Access-Control-Allow-Headers": "*",
      "Access-Control-Allow-Methods": "GET, POST, PATCH",
    };
    if (request.method() === "OPTIONS") {
      await route.fulfill({ status: 204, headers });
      return;
    }
    if (pathname.endsWith("/events/stream")) {
      await route.abort();
      return;
    }
    let body: unknown = { items: [] };
    if (pathname.endsWith("/status"))
      body = {
        ...(await source.getStatus()),
        environment: "production",
        devLoopback: false,
        conversationCount: 1,
      };
    if (pathname.endsWith("/conversations")) body = { items: [conversation] };
    if (pathname.endsWith("/customers/c6")) body = profile;
    if (pathname.endsWith("/conversations/c6/messages")) body = { items: await source.listMessages("c6") };
    if (pathname.endsWith("/conversations/c6/account")) body = account;
    if (pathname.endsWith("/support/issues")) body = { items: issues };
    if (pathname.endsWith("/support/issues/issue1/resolve")) {
      issues.splice(0);
      body = {};
    }
    if (pathname.endsWith("/approvals")) body = { items: approval ? [approval] : [] };
    if (pathname.endsWith("/account/propose")) {
      expect(pathname).toContain("/conversations/c6/");
      expect(request.postDataJSON()).toEqual({ operation: "profile", profile: "flowers" });
      approval = {
        id: "ap1",
        conversationId: "c6",
        customerName: "ورد الربيع",
        action: "ترتيب حساب العميل",
        reason: "طلبات العميل",
        oldValue: "الإعدادات الحالية",
        newValue: "محل ورد وهدايا",
        agentLimit: null,
        risk: "high",
        status: "pending",
        createdAt: new Date().toISOString(),
        planHash: "a".repeat(64),
        planVersion: 1,
        preview: {
          businessTypeChange: { before: "شركة عامة", after: "إدارة أعمال مبسّطة" },
          accountScope: { tenantSlug: "flowers-a", label: "هذا الحساب فقط؛ بقية الشركات لا تتغير" },
          changes: [
            { key: "clinics", label: "العيادات", before: true, after: false },
            {
              key: "maintenance",
              label: "الصيانة — لأنك تقدم صيانة وتحتاج تنظيم أعمالها داخل القسم الموجود",
              before: false,
              after: true,
            },
          ],
          tenantActions: [{ action: "configure_tenant", label: "محل ورد وهدايا" }],
        },
      };
      body = { approval };
    }
    if (pathname.endsWith("/approvals/ap1/decision")) {
      expect(request.postDataJSON()).toEqual({ decision: "approved", planHash: "a".repeat(64) });
      if (!approval) throw new Error("Missing scoped review");
      decisions++;
      body = { approval: { ...approval, status: "approved" }, credentials: null };
      approval = null;
    }
    await route.fulfill({ json: body, headers });
  });
  await page.goto("/?gl=0", { waitUntil: "domcontentloaded" });
  await page.locator(".orb-hit").click();
  const setup = page.getByRole("region", { name: "حساب العميل وترتيبه" });
  await setup.getByRole("button", { name: "ترتيب حساب العميل" }).click();
  await expect(setup).toContainText("ورد الربيع · flowers-a");
  for (const profile of account.profiles) {
    await expect(
      setup.getByRole("button", { name: `${profile.label} ${profile.needs}`, exact: true }),
    ).toHaveCount(1);
  }
  await expect(setup.getByRole("button", { name: /شركة عامة/ })).toBeInViewport();
  expect(await page.evaluate(() => window.scrollY)).toBe(0);
  await expect(setup.getByLabel("موظف حساب العميل").getByRole("option", { name: /المالك/ })).toHaveCount(0);
  await page.screenshot({ path: testInfo.outputPath("customer-account-tools.png") });
  await page.setViewportSize({ width: 1280, height: 720 });
  expect(await setup.evaluate((element) => element.scrollWidth <= element.clientWidth)).toBe(true);
  await page.screenshot({ path: testInfo.outputPath("customer-account-compact.png") });
  await setup.getByRole("button", { name: /محل ورد وهدايا/ }).click();
  const plan = page.getByLabel("الخطة المقترحة");
  await expect(plan).toContainText("flowers-a");
  await expect(plan).toContainText("شركة عامة ← إدارة أعمال مبسّطة");
  await expect(plan).toContainText("العيادات: ظاهرة ← إخفاء");
  await expect(plan).toContainText("لأنك تقدم صيانة");
  await expect(page.getByText("تحتاج مراجعة حفظ التقارير")).toBeVisible();
  expect(decisions).toBe(0);
  await page.screenshot({ path: testInfo.outputPath("customer-account-review.png") });
  await page.getByRole("button", { name: "موافقة", exact: true }).click();
  await expect.poll(() => decisions).toBe(1);
});
