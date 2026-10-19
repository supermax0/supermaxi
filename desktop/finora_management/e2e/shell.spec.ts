import { closeIsolatedApp } from "./closeIsolatedApp";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { _electron as electron, expect, test, type ElectronApplication, type Page } from "@playwright/test";
import type { FinoraDesktopBridge } from "../shared/ipc";
import { startFinoraStub, STUB_CREDENTIALS, type FinoraStub } from "./finoraStub";

const APP_DIR = path.resolve(__dirname, "..");

interface Box {
  x: number;
  y: number;
  width: number;
  height: number;
}

let stub: FinoraStub;
let profileDir: string;

async function launch(): Promise<{ app: ElectronApplication; page: Page }> {
  // FINORA_E2E_EXECUTABLE runs the suite against a packaged build (e.g. the Electron 22 / Windows 7 one).
  const packaged = process.env.FINORA_E2E_EXECUTABLE;
  const app = await electron.launch({
    ...(packaged ? { executablePath: packaged } : {}),
    args: packaged ? [] : [APP_DIR],
    cwd: APP_DIR,
    env: { ...process.env, FINORA_SERVER_URL: stub.url, FINORA_USER_DATA_DIR: profileDir },
  });
  const page = await app.firstWindow();
  await page.waitForLoadState("domcontentloaded");
  return { app, page };
}

async function signIn(page: Page): Promise<void> {
  const form = page.getByRole("form", { name: "تسجيل الدخول إلى FINORA" });
  await form.getByLabel("معرف الشركة").fill(STUB_CREDENTIALS.tenantSlug);
  await form.getByLabel("اسم المستخدم").fill(STUB_CREDENTIALS.username);
  await form.getByLabel("كلمة المرور").fill(STUB_CREDENTIALS.password);
  await form.getByRole("button", { name: "تسجيل الدخول" }).click();
  await expect(page.getByRole("navigation", { name: "النوافذ" })).toBeVisible();
}

/** Signs in only when the app starts on the login screen (a stored FINORA session skips it). */
async function ensureSignedIn(page: Page): Promise<void> {
  const form = page.getByRole("form", { name: "تسجيل الدخول إلى FINORA" });
  const nav = page.getByRole("navigation", { name: "النوافذ" });
  await expect(form.or(nav)).toBeVisible({ timeout: 15_000 });
  if (await form.isVisible()) await signIn(page);
}

/** Samples the morphing shell's on-screen box every frame for `ms`. */
async function sampleShell(page: Page, windowId: string, ms: number): Promise<Box[]> {
  return page.evaluate(
    ([id, duration]) =>
      new Promise<Box[]>((resolve) => {
        const samples: Box[] = [];
        const started = performance.now();
        const tick = () => {
          const shell = document.querySelector(`[data-window="${id}"] > div`);
          if (shell) {
            const r = shell.getBoundingClientRect();
            samples.push({ x: r.x, y: r.y, width: r.width, height: r.height });
          }
          if (performance.now() - started < duration) requestAnimationFrame(tick);
          else resolve(samples);
        };
        requestAnimationFrame(tick);
      }),
    [windowId, ms] as const,
  );
}

function center(box: Box) {
  return { x: box.x + box.width / 2, y: box.y + box.height / 2 };
}

test.beforeAll(async () => {
  stub = await startFinoraStub();
  profileDir = mkdtempSync(path.join(tmpdir(), "finora-mgmt-e2e-"));
});

test.afterAll(async () => {
  await stub.close();
  rmSync(profileDir, { recursive: true, force: true });
});

test.describe.configure({ mode: "serial" });

test("sign-in, window morphs, switching, rapid switching, native controls and IPC hardening", async () => {
  const { app, page } = await launch();
  try {
    // frameless window: 1440×900 (or the work area if smaller), minimum 760×480, clamped to the work area
    const bounds = await app.evaluate(({ BrowserWindow, screen }) => {
      const win = BrowserWindow.getAllWindows()[0];
      const area = screen.getPrimaryDisplay().workAreaSize;
      return win
        ? { content: win.getContentSize(), min: win.getMinimumSize(), area: [area.width, area.height] }
        : null;
    });
    if (!bounds) throw new Error("no window");
    const [areaWidth = 0, areaHeight = 0] = bounds.area;
    expect(bounds.min).toEqual([Math.min(760, areaWidth), Math.min(480, areaHeight)]);
    expect(Math.abs((bounds.content[0] ?? 0) - Math.min(1440, areaWidth))).toBeLessThanOrEqual(2);
    expect(Math.abs((bounds.content[1] ?? 0) - Math.min(900, areaHeight))).toBeLessThanOrEqual(2);

    // wrong password → FINORA's message, no session
    const form = page.getByRole("form", { name: "تسجيل الدخول إلى FINORA" });
    await form.getByLabel("معرف الشركة").fill(STUB_CREDENTIALS.tenantSlug);
    await form.getByLabel("اسم المستخدم").fill(STUB_CREDENTIALS.username);
    await form.getByLabel("كلمة المرور").fill("wrong");
    await form.getByRole("button", { name: "تسجيل الدخول" }).click();
    await expect(page.getByRole("alert")).toHaveText("بيانات الدخول غير صحيحة");

    await signIn(page);
    const nav = page.getByRole("navigation", { name: "النوافذ" });
    await expect(nav.getByRole("button")).toHaveText(["الطلبات", "المشتريات", "المنتجات", "نقطة البيع"]);

    // ── open: the window grows out of its own button ──
    await page.waitForTimeout(2500); // windows are pre-built in idle time after sign-in
    const ordersButton = await nav.getByRole("button", { name: /الطلبات/ }).boundingBox();
    if (!ordersButton) throw new Error("orders button not measurable");
    const samplesPromise = sampleShell(page, "orders", 700);
    await nav.getByRole("button", { name: /الطلبات/ }).click();
    const samples = await samplesPromise;
    expect(samples.length).toBeGreaterThanOrEqual(6);
    const [first] = samples;
    const last = samples.at(-1);
    if (!first || !last) throw new Error("no animation samples");
    expect(first.width).toBeLessThan(last.width * 0.35);
    expect(Math.abs(center(first).x - center(ordersButton).x)).toBeLessThan(last.width * 0.2);
    expect(center(first).y).toBeLessThan(center(last).y);
    // widths grow monotonically (no jump / pop-in)
    samples.reduce((previous, sample) => {
      expect(sample.width).toBeGreaterThanOrEqual(previous.width - 0.5);
      return sample;
    });
    const stage = await page.getByTestId("window-stage").boundingBox();
    if (!stage) throw new Error("stage not measurable");
    expect(last.width).toBeCloseTo(stage.width - 44, 0);
    await expect(page.getByRole("dialog", { name: "إدارة الطلبات" })).toBeVisible();

    // ── switch: orders shrinks back while products grows; windows stay mounted (state kept) ──
    const open = page.locator('[data-state="open"]');
    for (const [from, to, label] of [
      ["orders", "products", "المنتجات"],
      ["products", "purchases", "المشتريات"],
      ["purchases", "orders", "الطلبات"],
    ] as const) {
      await nav.getByRole("button", { name: new RegExp(label) }).click();
      await page.waitForTimeout(120);
      await expect(page.locator(`[data-window="${from}"]`)).toHaveAttribute("data-state", "closing");
      await expect(page.locator(`[data-window="${to}"]`)).toHaveAttribute("data-state", "open");
      await expect(page.locator(`[data-window="${from}"]`)).toHaveAttribute("data-state", "closed", {
        timeout: 2000,
      });
      await expect(open).toHaveCount(1);
    }

    // ── smoothness: frame pacing while switching windows (morph runs on the compositor) ──
    const frameGaps = await page.evaluate(
      () =>
        new Promise<number[]>((resolve) => {
          const gaps: number[] = [];
          let last = performance.now();
          const started = last;
          const tick = (now: number) => {
            gaps.push(now - last);
            last = now;
            if (now - started < 700) requestAnimationFrame(tick);
            else resolve(gaps.slice(1));
          };
          requestAnimationFrame(tick);
          document.querySelector<HTMLButtonElement>('[data-nav="products"]')?.click();
        }),
    );
    const sorted = [...frameGaps].sort((x, y) => x - y);
    const p95 = sorted[Math.floor(sorted.length * 0.95)] ?? 0;
    console.log(
      `switch frames: ${frameGaps.length}, p95 gap ${p95.toFixed(1)}ms, max ${(sorted.at(-1) ?? 0).toFixed(1)}ms`,
    );
    expect(p95).toBeLessThan(40);

    // ── rapid switching: retargets running animations, settles on the last click ──
    const order = ["المنتجات", "المشتريات", "الطلبات", "المنتجات", "المشتريات", "الطلبات", "المنتجات"];
    for (const label of order) {
      await nav.getByRole("button", { name: new RegExp(label) }).click({ delay: 0 });
      await page.waitForTimeout(40);
      expect(await open.count()).toBeLessThanOrEqual(1);
    }
    await expect(page.locator('[data-state="closing"]')).toHaveCount(0, { timeout: 2000 });
    await expect(open).toHaveCount(1);
    await expect(page.getByRole("dialog", { name: "إدارة المنتجات" })).toBeVisible();
    const settled = await sampleShell(page, "products", 50);
    expect(settled.at(-1)?.width).toBeCloseTo(stage.width - 44, 0);

    // ── close returns into the button ──
    await page
      .getByRole("dialog", { name: "إدارة المنتجات" })
      .getByRole("button", { name: "إغلاق النافذة" })
      .click();
    await expect(page.locator('[data-window="products"]')).toHaveAttribute("data-state", "closed", {
      timeout: 2000,
    });
    await expect(open).toHaveCount(0);

    // ── native window controls ──
    const controls = page.getByRole("group", { name: "التحكم بنافذة التطبيق" });
    await controls.getByRole("button", { name: "تكبير" }).click();
    await expect
      .poll(() => app.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows()[0]?.isMaximized()))
      .toBe(true);
    await expect(controls.getByRole("button", { name: "استعادة" })).toBeVisible();
    await controls.getByRole("button", { name: "استعادة" }).click();
    await expect
      .poll(() => app.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows()[0]?.isMaximized()))
      .toBe(false);

    // ── renderer isolation and IPC validation ──
    const isolation = await page.evaluate(async () => {
      const w = window as unknown as Record<string, unknown>;
      const bridge = (window as unknown as { finoraDesktop?: FinoraDesktopBridge }).finoraDesktop;
      if (!bridge) throw new Error("bridge missing");
      const refused = await bridge.finora.request({ method: "GET", path: "/superadmin/tenants" } as never);
      const traversal = await bridge.finora.request({
        method: "GET",
        path: "/orders/../superadmin",
      } as never);
      const sessionPage = await bridge.finora.request({ method: "GET", path: "/orders/data" });
      return {
        require: typeof w.require,
        process: typeof w.process,
        refused,
        traversal,
        sessionPage,
        cookieVisible: document.cookie.includes("session="),
      };
    });
    expect(isolation.require).toBe("undefined");
    expect(isolation.process).toBe("undefined");
    expect(isolation.refused).toMatchObject({ ok: false, failure: "refused" });
    expect(isolation.traversal).toMatchObject({ ok: false, failure: "refused" });
    // the FINORA session cookie is used by main for session pages but never visible to the renderer
    expect(isolation.sessionPage).toMatchObject({ ok: true, status: 200 });
    expect(isolation.cookieVisible).toBe(false);

    // ── offline banner and automatic reconnect ──
    await page.evaluate(() => window.dispatchEvent(new Event("offline")));
    await expect(page.getByText("لا يوجد اتصال بـ FINORA")).toBeVisible();
    await page.evaluate(() => window.dispatchEvent(new Event("online")));
    await expect(page.getByText("لا يوجد اتصال بـ FINORA")).toBeHidden({ timeout: 15_000 });
  } finally {
    await closeIsolatedApp(app);
  }
});

test("the FINORA session survives a restart and sign-out ends it", async () => {
  const first = await launch();
  try {
    await expect(first.page.getByRole("navigation", { name: "النوافذ" })).toBeVisible();
    await first.page.getByRole("button", { name: "الإعدادات" }).click();
    await first.page.getByRole("button", { name: "تسجيل الخروج" }).click();
    await expect(first.page.getByRole("form", { name: "تسجيل الدخول إلى FINORA" })).toBeVisible();
    await expect(first.page.getByText("تم تسجيل الخروج.")).toBeVisible();
    // tenant and username are remembered, the password never is
    const form = first.page.getByRole("form", { name: "تسجيل الدخول إلى FINORA" });
    await expect(form.getByLabel("معرف الشركة")).toHaveValue(STUB_CREDENTIALS.tenantSlug);
    await expect(form.getByLabel("كلمة المرور")).toHaveValue("");
  } finally {
    await closeIsolatedApp(first.app);
  }

  const second = await launch();
  try {
    await expect(second.page.getByRole("form", { name: "تسجيل الدخول إلى FINORA" })).toBeVisible();
  } finally {
    await closeIsolatedApp(second.app);
  }
  expect(stub.requests).toContain("POST /api/v1/desktop/auth/logout");
});

test("windows show FINORA data: orders bulk status + print, product images, purchases", async () => {
  const { app, page } = await launch();
  try {
    // the previous test signed out
    await signIn(page);
    const nav = page.getByRole("navigation", { name: "النوافذ" });

    // Orders
    await nav.getByRole("button", { name: /الطلبات/ }).click();
    const orders = page.getByRole("dialog", { name: "إدارة الطلبات" });
    await expect(orders.getByText("#10045")).toBeVisible();
    await expect(orders.getByRole("tab", { name: /الكل/ })).toContainText("3");
    await orders.getByRole("checkbox", { name: "تحديد 10045" }).click();
    await orders.getByRole("checkbox", { name: "تحديد 10044" }).click();
    await orders.getByRole("button", { name: "إجراءات", exact: true }).click();
    await page.getByRole("menuitem", { name: "تغيير الحالة" }).click();
    const picker = page.getByRole("dialog", { name: "تغيير حالة 2 طلبات" });
    await picker.getByRole("radio", { name: "تم التوصيل" }).click();
    await picker.getByRole("button", { name: "متابعة" }).click();
    await page
      .getByRole("dialog", { name: "تأكيد تغيير الحالة" })
      .getByRole("button", { name: "تغيير الحالة" })
      .click();
    await expect(page.getByText('تم تغيير حالة 2 طلبات إلى "تم التوصيل".', { exact: true })).toBeVisible();
    expect(stub.bodies).toContainEqual({
      path: "/orders/bulk-status",
      body: { order_ids: [10045, 10044], status: "تم التوصيل" },
    });

    // Print opens FINORA's print page in its own window on the same session
    await orders.getByRole("checkbox", { name: "تحديد 10043" }).click();
    const printWindow = app.waitForEvent("window");
    await orders.getByRole("button", { name: /طباعة المحدد/ }).click();
    const printPage = await printWindow;
    await expect(printPage.locator("h1")).toContainText("10043");

    // Products: stats + image through the finora-media proxy (uses the session cookie)
    await nav.getByRole("button", { name: /المنتجات/ }).click();
    const products = page.getByRole("dialog", { name: "إدارة المنتجات" });
    await expect(products.getByText("542")).toBeVisible();
    await expect(products.getByText("TV-LG-50-2026")).toBeVisible();
    await expect
      .poll(() =>
        products
          .locator("img")
          .first()
          .evaluate((img: HTMLImageElement) => img.naturalWidth),
      )
      .toBeGreaterThan(0);

    // Purchases
    await nav.getByRole("button", { name: /المشتريات/ }).click();
    const purchases = page.getByRole("dialog", { name: "إدارة المشتريات" });
    await expect(purchases.getByText("158,750,000")).toBeVisible();
    await purchases.getByRole("tab", { name: /مسودات/ }).click();
    await expect(purchases.getByText("P-2026-0047")).toBeVisible();
    await expect(purchases.getByText("P-2026-0048")).toBeHidden();
  } finally {
    await closeIsolatedApp(app);
  }
});

test("POS: scan, customer, cash checkout through FINORA, payment and print", async () => {
  const { app, page } = await launch();
  try {
    await expect(page.getByRole("navigation", { name: "النوافذ" })).toBeVisible();
    await page.keyboard.press("Control+4");
    const pos = page.getByRole("dialog", { name: "نقطة البيع" });
    await expect(pos.getByRole("button", { name: "إضافة شاشة LG 50 بوصة" })).toBeVisible();

    // keyboard-wedge scanner adds the matching product straight to the cart
    // Dispatch one scanner burst; timer stalls on a busy Windows host must not split its barcode.
    await page.evaluate((code) => {
      const fire = (key: string, keyCode: string) =>
        window.dispatchEvent(new KeyboardEvent("keydown", { key, code: keyCode, bubbles: true }));
      for (const digit of code) {
        fire(digit, `Digit${digit}`);
      }
      fire("Enter", "Enter");
    }, "6290000000035");
    await expect(pos.getByLabel("كمية مكيف جنرال 1 طن")).toHaveValue("1");
    await pos.getByRole("button", { name: "إضافة شاشة LG 50 بوصة" }).click();
    await pos.getByRole("button", { name: "إضافة Samsung A55" }).click();
    await expect(pos.getByTestId("pos-total")).toContainText("1,017,000");

    await pos.getByLabel("البحث عن زبون").fill("علي");
    await page.getByRole("button", { name: /علي حسين/ }).click();
    await page.screenshot({ path: "test-results/pos.png" });

    const printWindow = app.waitForEvent("window");
    await page.keyboard.press("F9"); // cashier shortcut
    await printWindow;
    await expect(page.getByText(/تم تنفيذ الطلب #10046/)).toBeVisible();
    expect(stub.bodies.find((b) => b.path === "/orders/payment")?.body).toEqual({
      id: 10046,
      payment: "مسدد",
      payment_allocations: [{ treasury_account_id: 4, amount: 1017000 }],
    });
    await expect(pos.getByTestId("pos-total")).toContainText("0");
  } finally {
    await closeIsolatedApp(app);
  }
});

test("bank sale type lists only this branch's accounts; settings dialog has the POS section", async () => {
  const { app, page } = await launch();
  try {
    await expect(page.getByRole("navigation", { name: "النوافذ" })).toBeVisible();
    await page.keyboard.press("Control+4");
    const pos = page.getByRole("dialog", { name: "نقطة البيع" });
    await pos.getByRole("radio", { name: /بنك/ }).click();
    await pos.getByRole("button", { name: "الحساب البنكي" }).click();
    const list = page.getByRole("listbox", { name: "الحسابات البنكية" });
    await expect(list.getByRole("option")).toHaveText([/أقساط كي كارد/, /بطاقة ماستر/]);
    await page.screenshot({ path: "test-results/pos-bank.png" });
    await list.getByRole("option", { name: /بطاقة ماستر/ }).click();
    await expect(pos.getByRole("button", { name: "الحساب البنكي" })).toContainText("بطاقة ماستر");
    await expect(pos.getByRole("button", { name: /تخصيص نقطة البيع/ })).toHaveCount(0);

    await page.getByRole("button", { name: "الإعدادات" }).click();
    const settings = page.getByRole("dialog", { name: "الإعدادات" });
    await settings.getByRole("button", { name: "نقطة البيع" }).click();
    await expect(settings.getByRole("radiogroup", { name: "نوع البيع الافتراضي" })).toBeVisible();
    await settings.getByRole("radio", { name: "48" }).click();
    await page.screenshot({ path: "test-results/settings-pos.png" });
    await page.keyboard.press("Escape");
    await expect(settings).toBeHidden();
  } finally {
    await closeIsolatedApp(app);
  }
});

test("new purchase composer: supplier, scanned + searched products, colour, confirm receipt", async () => {
  const { app, page } = await launch();
  try {
    const nav = page.getByRole("navigation", { name: "النوافذ" });
    const form = page.getByRole("form", { name: "تسجيل الدخول إلى FINORA" });
    await expect(nav.or(form)).toBeVisible();
    if (await form.isVisible()) await signIn(page);
    await page.keyboard.press("Control+2");
    const purchases = page.getByRole("dialog", { name: "إدارة المشتريات" });
    await expect(purchases.getByText("P-2026-0048")).toBeVisible();
    await page.keyboard.press("Control+n");
    const composer = page.getByRole("dialog", { name: "فاتورة شراء جديدة" });
    await expect(composer).toBeVisible();

    await composer.getByLabel("المورد", { exact: true }).fill("الرافدين");
    await page.getByRole("option", { name: /شركة الرافدين/ }).click();

    await composer.getByLabel("إضافة منتج").fill("شاشة");
    await page.getByRole("option", { name: /شاشة LG 50 بوصة/ }).click();
    await composer.getByLabel("إضافة منتج").fill("ثلاجة");
    await page.getByRole("option", { name: /ثلاجة ايفولي/ }).click();
    await composer.getByLabel("خيار ثلاجة ايفولي 7 قدم").selectOption("فضي");
    await composer.getByLabel("كمية شاشة LG 50 بوصة").fill("10");
    await expect(composer.getByTestId("purchase-total")).toContainText("3,037,500");
    await page.screenshot({ path: "test-results/purchase-composer.png" });

    await page.keyboard.press("Control+Enter");
    await expect(page.getByText(/تم حفظ فاتورة الشراء PUR-20261007-E2E/)).toBeVisible();
    await expect(composer).toBeHidden();
    expect(stub.bodies.find((b) => b.path === "/purchases/create")?.body).toMatchObject({
      supplier_id: 3,
      status: "confirmed",
      items: [
        { product_id: 1, quantity: 10, unit_cost_before_discount: 270000 },
        { product_id: 2, quantity: 1, unit_cost_before_discount: 337500, color: "فضي" },
      ],
    });
  } finally {
    await closeIsolatedApp(app);
  }
});

test("product editor: create through FINORA's form (multipart) and edit only changed fields", async () => {
  const { app, page } = await launch();
  try {
    const nav = page.getByRole("navigation", { name: "النوافذ" });
    const form = page.getByRole("form", { name: "تسجيل الدخول إلى FINORA" });
    await expect(nav.or(form)).toBeVisible();
    if (await form.isVisible()) await signIn(page);
    await page.keyboard.press("Control+3");
    const products = page.getByRole("dialog", { name: "إدارة المنتجات" });
    await expect(products.getByText("TV-LG-50-2026")).toBeVisible();

    await products.getByRole("button", { name: /منتج جديد/ }).click();
    const sheet = page.getByRole("dialog", { name: "منتج جديد" });
    await sheet.getByLabel("اسم المنتج").fill("مكيف جري 1.5 طن انفرتر");
    await sheet.getByRole("button", { name: /توليد/ }).click();
    await sheet.getByLabel("الفئة").fill("مكيفات");
    await sheet.getByLabel("الماركة").fill("Gree");
    await sheet.getByLabel("سعر الشراء").fill("410000");
    await sheet.getByLabel("سعر البيع").fill("475000");
    await sheet.getByLabel("المخزون الافتتاحي").fill("6");
    await expect(sheet.getByText(/الربح/)).toContainText("65,000");
    await page.screenshot({ path: "test-results/product-create.png" });
    await page.keyboard.press("Control+s");
    await expect(page.getByText("تمت إضافة «مكيف جري 1.5 طن انفرتر»")).toBeVisible();
    const created = stub.bodies.find((b) => b.path === "/inventory/add")?.body as {
      contentType: string;
      raw: string;
    };
    expect(created.contentType).toContain("multipart/form-data");
    expect(created.raw).toContain('name="_response"');
    expect(created.raw).toContain("مكيف جري 1.5 طن انفرتر");

    await products.getByRole("button", { name: "إجراءات شاشة LG 50 إنش" }).click();
    await page.getByRole("menuitem", { name: "تعديل" }).click();
    const edit = page.getByRole("dialog", { name: "تعديل منتج" });
    await expect(edit.getByLabel("سعر البيع")).toHaveValue("325,000");
    await page.screenshot({ path: "test-results/product-edit.png" });
    await edit.getByLabel("سعر البيع").fill("339000");
    await edit.getByRole("button", { name: /حفظ التعديلات/ }).click();
    await expect(page.getByText(/تم حفظ تعديلات/)).toBeVisible();
    const updated = stub.bodies.find((b) => b.path === "/inventory/api/products/1/update")?.body as {
      raw: string;
    };
    expect(updated.raw).toContain('name="sale_price"');
    expect(updated.raw).not.toContain('name="name"');
  } finally {
    await closeIsolatedApp(app);
  }
});

test("«المزيد» grows out of the top bar, owns the keyboard and yields to Ctrl+K", async () => {
  const { app, page } = await launch();
  try {
    await ensureSignedIn(page);
    await expect(page.getByRole("navigation", { name: "النوافذ" })).toBeVisible();
    // open a window first: the menu must float above it
    await page.locator('[data-nav="orders"]').click();
    await page.waitForTimeout(500);

    const trigger = page.getByRole("button", { name: "المزيد", exact: true });
    const started = Date.now();
    await trigger.click();
    const panel = page.getByRole("dialog", { name: "المزيد" });
    await expect(panel).toBeVisible();
    await expect(trigger).toHaveAttribute("aria-expanded", "true");
    await expect(panel.getByRole("combobox")).toBeFocused();
    // the morph settles in ~200ms (opacity reaches 1, transform back to identity)
    await expect
      .poll(() => panel.evaluate((el) => getComputedStyle(el).opacity), { timeout: 1500 })
      .toBe("1");
    expect(Date.now() - started).toBeLessThan(1500);
    expect(await panel.evaluate((el) => getComputedStyle(el).transform)).toMatch(
      /none|matrix\(1, 0, 0, 1, 0, 0\)/,
    );
    // The authorized supplier workspace is now registered in More.
    await expect(panel.getByRole("option", { name: /^الموردين/ })).toBeVisible();
    await expect(panel.getByText("حسابات الموردين والمشتريات والدفعات", { exact: true })).toBeVisible();

    // just below the top bar, inside the window, never covered by the open window
    const box = await panel.boundingBox();
    const viewport =
      page.viewportSize() ?? (await page.evaluate(() => ({ width: innerWidth, height: innerHeight })));
    expect(box).not.toBeNull();
    if (box) {
      expect(box.y).toBeGreaterThan(40);
      expect(box.x + box.width).toBeLessThanOrEqual(viewport.width);
      const onTop = await page.evaluate(
        ([x, y]) => !!document.elementFromPoint(x, y)?.closest('[role="dialog"][aria-label="المزيد"]'),
        [box.x + box.width / 2, box.y + 40] as const,
      );
      expect(onTop).toBe(true);
    }
    await page.screenshot({ path: test.info().outputPath("more-menu.png") });

    // no results state
    await panel.getByRole("combobox").fill("أي شيء");
    await expect(panel.getByText("لا توجد نتائج لـ «أي شيء»")).toBeVisible();

    // Ctrl+K closes «المزيد» and opens the palette (and the other way round)
    await page.keyboard.press("Control+k");
    await expect(page.getByRole("dialog", { name: "بحث سريع" })).toBeVisible();
    await expect(panel).toBeHidden();
    await page.keyboard.press("Escape");
    await trigger.click();
    await expect(panel).toBeVisible();
    await expect(page.getByRole("dialog", { name: "بحث سريع" })).toBeHidden();

    // Escape closes the menu only (the open window stays) and focus goes back to the button
    await page.keyboard.press("Escape");
    await expect(panel).toBeHidden();
    await expect(trigger).toBeFocused();
    await expect(page.locator('[data-nav="orders"]')).toHaveAttribute("aria-pressed", "true");
  } finally {
    await closeIsolatedApp(app);
  }
});

test("report print opens a real page preview (PDF viewer) instead of the preview-less system dialog", async () => {
  const { app, page } = await launch();
  try {
    await ensureSignedIn(page);
    await expect(page.getByRole("navigation", { name: "النوافذ" })).toBeVisible();
    await page.evaluate(() =>
      (
        window as unknown as {
          finoraDesktop: { reports: { export(r: unknown): Promise<unknown> } };
        }
      ).finoraDesktop.reports.export({
        section: "customers",
        format: "print",
        title: "العملاء",
        query: { period: "this_month" },
      }),
    );
    // the hidden render window comes and goes; the preview is the window showing the PDF
    await expect
      .poll(() => app.windows().some((w) => /^file:.*finora-print-.*\.pdf$/.test(w.url())), {
        timeout: 20_000,
      })
      .toBe(true);
    const preview = app.windows().find((w) => /finora-print-.*\.pdf$/.test(w.url()));
    if (!preview) throw new Error("preview window missing");
    const title = await app.evaluate(({ BrowserWindow }) =>
      BrowserWindow.getAllWindows().map((w) => w.getTitle()),
    );
    expect(title).toContain("معاينة الطباعة — العملاء");
    await preview.waitForTimeout(1200);
    await preview.screenshot({ path: test.info().outputPath("print-preview.png") });
    expect(stub.requests.some((r) => r.startsWith("GET /reports/api/v2/print/customers"))).toBe(true);
  } finally {
    await closeIsolatedApp(app);
  }
});

test("expenses page opens from «المزيد» with totals, table, breakdown and the add-expense form", async () => {
  const { app, page } = await launch();
  try {
    await ensureSignedIn(page);
    await page.getByRole("button", { name: "المزيد", exact: true }).click();
    await page
      .getByRole("dialog", { name: "المزيد" })
      .getByRole("option", { name: /المصاريف/ })
      .click();
    const win = page.getByRole("dialog", { name: "المصاريف" });
    await expect(win.getByText("إيجار المحل — تشرين الأول")).toBeVisible();
    await expect(win.getByText("2,235,000")).toBeVisible();
    await page.waitForTimeout(600);
    await page.screenshot({ path: test.info().outputPath("expenses.png") });
    await win.getByRole("button", { name: "إضافة مصروف" }).click();
    const form = page.getByRole("dialog", { name: "إضافة مصروف" });
    await form.getByPlaceholder(/مثال/).fill("اشتراك برنامج المحاسبة");
    await form.getByLabel("مبلغ المصروف").fill("45000");
    await form.getByRole("checkbox").check();
    await page.waitForTimeout(400);
    await page.screenshot({ path: test.info().outputPath("expense-form.png") });
    await page.keyboard.press("Escape");
  } finally {
    await closeIsolatedApp(app);
  }
});

test("shipping center: overview, carrier profile and a keyboard-driven settlement manifest", async () => {
  const { app, page } = await launch();
  try {
    await ensureSignedIn(page);
    await page.getByRole("button", { name: "المزيد", exact: true }).click();
    await page
      .getByRole("dialog", { name: "المزيد" })
      .getByRole("option", { name: /مركز الشحن/ })
      .click();
    const win = page.getByRole("dialog", { name: "مركز الشحن والتسويات" });
    await expect(win.getByText("4,815,000")).toBeVisible();
    await page.waitForTimeout(600);
    await page.screenshot({ path: test.info().outputPath("shipping-overview.png") });

    await win.getByRole("tab", { name: "شركات النقل" }).click();
    await win.getByText("النقل السريع").first().click();
    await expect(win.getByRole("complementary", { name: "الملف التفصيلي" })).toBeVisible();
    await page.waitForTimeout(500);
    await page.screenshot({ path: test.info().outputPath("shipping-carrier.png") });

    await win.getByRole("button", { name: /كشف تسوية جديد/ }).click();
    const form = page.getByRole("dialog", { name: "كشف تسوية جديد" });
    await form.getByPlaceholder(/2026-1145/).fill("NQ-7781");
    await form.getByRole("button", { name: /إنشاء وفتح الكشف/ }).click();
    const entry = win.getByLabel("رقم الطلب أو البوليصة");
    await entry.fill(Array.from({ length: 12 }, (_, i) => 1201 + i).join(" ") + " 9999");
    await entry.press("Enter");
    await expect(win.getByText("لم يُعثر على")).toBeVisible();
    for (const key of ["F2", "F2", "F3", "F2", "F4", "F2", "F2", "F2", "F2", "F3", "F2"])
      await page.keyboard.press(key);
    await page.keyboard.press("Control+s");
    await page.waitForTimeout(900);
    await page.screenshot({ path: test.info().outputPath("shipping-manifest.png") });
    await expect(win.getByRole("button", { name: /اعتماد التسوية/ })).toBeDisabled();
  } finally {
    await closeIsolatedApp(app);
  }
});

test("shipping center phase 2: partial settlement, receipts, statement and returns inspection", async () => {
  const { app, page } = await launch();
  try {
    await ensureSignedIn(page);
    await page.getByRole("button", { name: "المزيد", exact: true }).click();
    await page
      .getByRole("dialog", { name: "المزيد" })
      .getByRole("option", { name: /مركز الشحن/ })
      .click();
    const win = page.getByRole("dialog", { name: "مركز الشحن والتسويات" });
    await expect(win.getByText("4,815,000")).toBeVisible();
    await expect(win.getByText("طلبات متأخرة")).toBeVisible();
    await page.waitForTimeout(500);
    await page.screenshot({ path: test.info().outputPath("phase3-overview-overdue.png") });

    await win.getByRole("button", { name: /كشف تسوية جديد/ }).click();
    const form = page.getByRole("dialog", { name: "كشف تسوية جديد" });
    await form.getByRole("button", { name: /إنشاء وفتح الكشف/ }).click();
    const entry = win.getByLabel("رقم الطلب أو البوليصة");
    await entry.fill(Array.from({ length: 8 }, (_, i) => 1201 + i).join(" "));
    await entry.press("Enter");
    await expect(win.getByText("#1208")).toBeVisible();
    await win.getByRole("button", { name: /طلب لدى الجهة لم يرد في الكشف/ }).click();
    const missing = page.getByRole("dialog", { name: "طلبات لدى الجهة ولم ترد في الكشف" });
    await missing.getByLabel("تحديد 1209").check();
    await page.waitForTimeout(400);
    await page.screenshot({ path: test.info().outputPath("phase3-missing.png") });
    await missing.getByRole("button", { name: "إغلاق", exact: true }).click();
    for (const key of ["F2", "F2", "F2", "F2", "F3", "F2", "F2", "F2"]) await page.keyboard.press(key);
    await page.keyboard.press("Control+s");
    const analysis = win.getByRole("complementary", { name: "لوحة التحليل" });
    await analysis.getByText(/تسديد جزئي/).click();
    await analysis.getByLabel("المبلغ المستلم فعلياً").fill("250000");
    await analysis.getByRole("button", { name: "توزيع تلقائي على الأقدم" }).click();
    await expect(analysis.getByText(/التسوية متطابقة/)).toBeVisible();
    await page.waitForTimeout(500);
    await page.screenshot({ path: test.info().outputPath("phase2-partial.png") });
    await win.getByRole("button", { name: /اعتماد التسوية/ }).click();
    await page
      .getByRole("dialog", { name: "اعتماد كشف التسوية" })
      .getByRole("button", { name: "اعتماد وترحيل" })
      .click();
    await expect(win.getByText("مسوى جزئياً").or(win.getByText("معتمد")).first()).toBeVisible();
    await win.getByRole("button", { name: /كل الكشوف/ }).click();

    await win.getByRole("tab", { name: "التسويات المالية" }).click();
    await expect(win.getByText("RCV-SHP-20261008-0001")).toBeVisible();
    await page.waitForTimeout(400);
    await page.screenshot({ path: test.info().outputPath("phase2-receipts.png") });

    await win.getByRole("tab", { name: "شركات النقل" }).click();
    await win.getByText("شركة البرق").first().click();
    const profile = win.getByRole("complementary", { name: "الملف التفصيلي" });
    await profile.getByRole("tab", { name: "كشف الحساب" }).click();
    await expect(profile.getByText("300,000").first()).toBeVisible();
    await page.waitForTimeout(400);
    await page.screenshot({ path: test.info().outputPath("phase2-statement.png") });
    await profile.getByRole("tab", { name: "الإعدادات" }).click();
    await expect(profile.getByText("ملاحظات العقد")).toBeVisible();
    await page.waitForTimeout(300);
    await page.screenshot({ path: test.info().outputPath("phase2-settings.png") });

    await win.getByRole("tab", { name: "المندوبون" }).click();
    await win.getByText("مندوب علي").first().click();
    await expect(win.getByText("العهدة المالية لدى المندوب")).toBeVisible();
    await page.waitForTimeout(300);
    await page.screenshot({ path: test.info().outputPath("phase2-agent.png") });

    await win.getByRole("tab", { name: "المرتجعات" }).click();
    await win.getByLabel("استلام مرتجع بالباركود").fill("1219");
    await win.getByLabel("استلام مرتجع بالباركود").press("Enter");
    await win.getByRole("tab", { name: /بانتظار الفحص/ }).click();
    await win.getByRole("button", { name: "فحص وإغلاق" }).first().click();
    const inspect = page.getByRole("dialog", { name: /فحص مرتجع الطلب/ });
    await inspect.getByLabel("الكمية التالفة من سماعة لاسلكية").fill("1");
    await page.waitForTimeout(400);
    await page.screenshot({ path: test.info().outputPath("phase2-inspection.png") });
    await inspect.getByRole("button", { name: /إغلاق المرتجع/ }).click();
    await expect(inspect).toBeHidden();
  } finally {
    await closeIsolatedApp(app);
  }
});

test("orders page: scan to select, then hand the selection to an agent manifest", async () => {
  const { app, page } = await launch();
  try {
    await ensureSignedIn(page);
    await page.getByRole("button", { name: "الطلبات", exact: true }).click();
    const win = page.getByRole("dialog", { name: "الطلبات" });
    await expect(win.getByText("حسن علاء")).toBeVisible();
    await win.getByRole("button", { name: "مسح للتحديد" }).click();
    for (const code of ["10045", "10043"])
      await page.evaluate((value) => {
        const fire = (key: string, keyCode: string) =>
          window.dispatchEvent(new KeyboardEvent("keydown", { key, code: keyCode, bubbles: true }));
        for (const digit of value) fire(digit, `Digit${digit}`);
        fire("Enter", "Enter");
      }, code);
    await expect(win.getByRole("button", { name: /تسليم وإسناد/ })).toContainText("2");
    await page.waitForTimeout(400);
    await page.screenshot({ path: test.info().outputPath("orders-scan-select.png") });
    await win.getByRole("button", { name: /تسليم وإسناد/ }).click();
    const dialog = page.getByRole("dialog", { name: "تسليم وإسناد الطلبات" });
    await expect(dialog.getByText("#10045")).toBeVisible();
    await expect(dialog.getByText("#10043")).toBeVisible();
    await page.waitForTimeout(300);
    await page.screenshot({ path: test.info().outputPath("dispatch-dialog.png") });
    await dialog.getByRole("button", { name: "إنشاء كشف المندوب" }).click();
    await expect(page.getByText(/AGT-2-20261015-0001/).first()).toBeVisible();
    await expect(dialog).toBeHidden();
  } finally {
    await closeIsolatedApp(app);
  }
});

test("branches: top-bar scope selector, branches window, create an empty branch and archive it", async () => {
  const { app, page } = await launch();
  try {
    await ensureSignedIn(page);
    // the selector appears only because multi-branch is on and the user can see several branches
    const scope = page.getByRole("button", { name: /نطاق العمل/ });
    await expect(scope).toContainText("جميع الفروع");
    await scope.click();
    await page.getByRole("option", { name: /فرع المنصور/ }).click();
    await expect(page.getByRole("button", { name: /نطاق العمل: فرع المنصور/ })).toBeVisible();

    await page.getByRole("button", { name: "المزيد", exact: true }).click();
    await page
      .getByRole("dialog", { name: "المزيد" })
      .getByRole("option", { name: /الفروع والمخازن/ })
      .click();
    const win = page.getByRole("dialog", { name: "الفروع والمخازن" });
    await expect(win.getByText("فرع البصرة")).toBeVisible();
    await expect(win.getByText("غير متاح").first()).toBeVisible(); // a balance that could not be computed is never faked
    await page.waitForTimeout(500);
    await page.screenshot({ path: test.info().outputPath("branches-list.png") });

    await win.getByText("فرع المنصور").first().click();
    await expect(win.getByRole("complementary", { name: "تفاصيل الفرع" })).toBeVisible();
    await page.waitForTimeout(300);
    await page.screenshot({ path: test.info().outputPath("branches-detail.png") });

    await win.getByRole("button", { name: "فرع جديد" }).click();
    const form = page.getByRole("dialog", { name: "فرع جديد" });
    await form.getByRole("textbox").first().fill("فرع الموصل");
    await form.getByPlaceholder("KRD").fill("mos");
    await page.waitForTimeout(300);
    await page.screenshot({ path: test.info().outputPath("branch-form.png") });
    await form.getByRole("button", { name: "إنشاء الفرع" }).click();
    await expect(win.getByRole("complementary", { name: "تفاصيل الفرع" })).toContainText("فرع الموصل");
    await expect(win.getByRole("complementary", { name: "تفاصيل الفرع" })).toContainText("MOS");

    await win.getByRole("button", { name: "أرشفة" }).click();
    await page.getByRole("dialog", { name: "أرشفة الفرع" }).getByRole("button", { name: "أرشفة" }).click();
    // archived branches leave the default list; they come back with «إظهار المؤرشفة» and can be restored
    await expect(win.getByRole("complementary", { name: "تفاصيل الفرع" })).toBeHidden();
    await expect(win.getByText("فرع الموصل")).toHaveCount(0);
    await win.getByLabel("إظهار المؤرشفة").check();
    await win.getByText("فرع الموصل").first().click();
    await expect(win.getByRole("button", { name: "استعادة" })).toBeVisible();
    await page.waitForTimeout(300);
    await page.screenshot({ path: test.info().outputPath("branch-archived.png") });
    await win.getByRole("button", { name: "استعادة" }).click();
    await expect(win.getByRole("button", { name: "أرشفة" })).toBeVisible();

    // cash transfers between branches: request → confirm receipt (the stub plays the server's rules)
    await win.getByRole("tab", { name: "التحويلات النقدية" }).click();
    await expect(win.getByText("BCT-20261016-0001")).toBeVisible();
    await page.waitForTimeout(400);
    await page.screenshot({ path: test.info().outputPath("cash-transfers.png") });
    await win.getByRole("button", { name: /تأكيد الاستلام/ }).click();
    await expect(win.getByText("BCT-20261016-0001")).toBeHidden(); // left the «waiting» list: posted
    await win.getByRole("button", { name: "تحويل أموال" }).click();
    const cash = page.getByRole("dialog", { name: "تحويل أموال بين الفروع" });
    await cash.getByLabel("مبلغ التحويل").fill("300000");
    await cash.getByRole("textbox", { name: "السبب" }).fill("تغذية الصندوق");
    await page.waitForTimeout(300);
    await page.screenshot({ path: test.info().outputPath("cash-transfer-form.png") });
    await cash
      .getByRole("button", { name: "تحويل وترحيل" })
      .or(cash.getByRole("button", { name: "إرسال الطلب" }))
      .click();
    await expect(win.getByText("تغذية الصندوق").first()).toBeVisible();
  } finally {
    await closeIsolatedApp(app);
  }
});
