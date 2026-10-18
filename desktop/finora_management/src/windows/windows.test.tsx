import { QueryClient } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MotionGlobalConfig } from "framer-motion";
import { App } from "@/app/App";
import { ORDER_DEFAULTS, useOrderPreferences } from "@/features/orders/orderPreferences";
import { useConnection } from "@/stores/connection";
import { useSession } from "@/stores/session";
import { useWindowManager } from "@/stores/windowManager";
import { createFinoraFixture } from "@/test/fixtures";
import { installMockBridge, removeMockBridge } from "@/test/mockBridge";

function renderWith() {
  const fixture = createFinoraFixture();
  const bridge = installMockBridge(fixture.handler);
  render(<App queryClient={new QueryClient({ defaultOptions: { queries: { retry: false } } })} />);
  return { fixture, bridge };
}

async function openWindow(id: "orders" | "products" | "purchases", title: string) {
  await screen.findByRole("navigation", { name: "النوافذ" });
  act(() => useWindowManager.getState().open(id));
  return screen.findByRole("dialog", { name: title });
}

beforeAll(() => {
  MotionGlobalConfig.skipAnimations = true;
});

afterEach(() => {
  removeMockBridge();
  useWindowManager.getState().reset();
  useSession.setState({ status: "unknown", session: null, reason: null });
  useConnection.getState().setStatus("online");
  useOrderPreferences.getState().update(ORDER_DEFAULTS);
});

/** Keyboard-wedge burst on the page (not in a field). */
function scanCode(code: string) {
  let now = performance.now();
  const spy = vi.spyOn(performance, "now").mockImplementation(() => now);
  for (const digit of code) {
    now += 8;
    fireEvent.keyDown(document.body, { key: digit, code: `Digit${digit}` });
  }
  now += 8;
  fireEvent.keyDown(document.body, { key: "Enter", code: "Enter" });
  spy.mockRestore();
}

describe("Orders window", () => {
  it("lists FINORA orders with tab counts and LTR ids/phones", async () => {
    renderWith();
    const win = await openWindow("orders", "إدارة الطلبات");
    expect(await within(win).findByText("#10045")).toBeInTheDocument();
    expect(within(win).getByText("فاطمة محمد")).toBeInTheDocument();
    expect(within(win).getAllByText("07701234567")[0]).toHaveClass("ltr-isolate");
    const tabs = within(win).getByRole("tablist", { name: "حالات الطلبات" });
    expect(within(tabs).getByRole("tab", { name: /الكل/ })).toHaveTextContent("2");
    expect(within(tabs).getByRole("tab", { name: /معبأة/ })).toHaveTextContent("1");
  });

  it("searches on the server after the debounce", async () => {
    const { fixture } = renderWith();
    const user = userEvent.setup();
    const win = await openWindow("orders", "إدارة الطلبات");
    await within(win).findByText("#10045");
    await user.type(within(win).getByRole("searchbox"), "فاطمة");
    await waitFor(() =>
      expect(fixture.calls.some((c) => c.path === "/orders/data" && c.query?.search === "فاطمة")).toBe(true),
    );
    await waitFor(() => expect(within(win).queryByText("#10045")).not.toBeInTheDocument());
  });

  it("bulk status change asks for confirmation, calls FINORA's bulk endpoint and updates rows", async () => {
    const { fixture } = renderWith();
    const user = userEvent.setup();
    const win = await openWindow("orders", "إدارة الطلبات");
    await within(win).findByText("#10045");

    const printButton = within(win).getByRole("button", { name: /طباعة المحدد/ });
    expect(printButton).toBeDisabled();
    await user.click(within(win).getByRole("checkbox", { name: "تحديد كل الصفحة" }));
    expect(printButton).toBeEnabled();

    await user.click(within(win).getByRole("button", { name: "إجراءات" }));
    await user.click(await screen.findByRole("menuitem", { name: "تغيير الحالة" }));
    const picker = await screen.findByRole("dialog", { name: "تغيير حالة 2 طلبات" });
    await user.click(within(picker).getByRole("radio", { name: "جاري شحن" }));
    await user.click(within(picker).getByRole("button", { name: "متابعة" }));
    const confirm = await screen.findByRole("dialog", { name: "تأكيد تغيير الحالة" });
    await user.click(within(confirm).getByRole("button", { name: "تغيير الحالة" }));

    await waitFor(() =>
      expect(fixture.calls).toContainEqual(
        expect.objectContaining({
          path: "/orders/bulk-status",
          body: { order_ids: [10045, 10044], status: "جاري الشحن" },
        }),
      ),
    );
    await waitFor(() => expect(within(win).getAllByText("جاري شحن").length).toBeGreaterThanOrEqual(2));
    expect(await screen.findByText('تم تغيير حالة 2 طلبات إلى "جاري شحن".')).toBeInTheDocument();
  });

  it("prints the selected orders through FINORA's print page", async () => {
    const { bridge } = renderWith();
    const user = userEvent.setup();
    const win = await openWindow("orders", "إدارة الطلبات");
    await within(win).findByText("#10045");
    await user.click(within(win).getByRole("checkbox", { name: "تحديد 10045" }));
    await user.click(within(win).getByRole("button", { name: /طباعة المحدد/ }));
    expect(bridge.print.open).toHaveBeenCalledWith({ kind: "orders", ids: [10045] });
  });

  it("opens order details from the row", async () => {
    renderWith();
    const user = userEvent.setup();
    const win = await openWindow("orders", "إدارة الطلبات");
    await user.click(await within(win).findByText("#10045"));
    expect(await screen.findByRole("complementary", { name: "الطلب #10045" })).toBeInTheDocument();
  });
});

describe("Order payment", () => {
  it("collects an order split across cash and bank with a delivery fee", async () => {
    const { fixture } = renderWith();
    const user = userEvent.setup();
    const win = await openWindow("orders", "إدارة الطلبات");
    await user.click(await within(win).findByRole("button", { name: "تسديد الطلب 10045" }));
    const dialog = await screen.findByRole("dialog", { name: "تسديد الطلب #10045" });

    // default: the branch cash box receives the whole due
    const first = await within(dialog).findByLabelText("حساب الدفعة 1");
    expect(first).toHaveValue("4");
    expect(within(dialog).getByLabelText("مبلغ الدفعة 1")).toHaveValue("450,000");

    await user.click(within(dialog).getByRole("button", { name: /تقسيم الدفعة/ }));
    const firstAmount = within(dialog).getByLabelText("مبلغ الدفعة 1");
    await user.clear(firstAmount);
    await user.type(firstAmount, "300000");
    expect(within(dialog).getByText(/متبقٍ/)).toHaveTextContent("150,000");
    expect(within(dialog).getByRole("button", { name: /تأكيد التسديد/ })).toBeDisabled();
    expect(within(dialog).getByLabelText("حساب الدفعة 2")).toHaveValue("5");
    const second = within(dialog).getByLabelText("مبلغ الدفعة 2");
    await user.clear(second);
    await user.type(second, "150000");
    expect(within(dialog).getByText("مطابق ✓")).toBeInTheDocument();

    await user.click(within(dialog).getByRole("button", { name: /المقترح/ }));
    await waitFor(() => expect(within(dialog).getByLabelText("أجرة التوصيل")).toHaveValue("5,000"));

    await user.click(within(dialog).getByRole("button", { name: /تأكيد التسديد/ }));
    await waitFor(() =>
      expect(fixture.calls.find((c) => c.path === "/orders/payment")?.body).toEqual({
        id: 10045,
        payment: "مسدد",
        paid_amount: null,
        delivery_fee: 5000,
        branch_id: 1,
        payment_allocations: [
          { treasury_account_id: 4, amount: 300000 },
          { treasury_account_id: 5, amount: 150000 },
        ],
      }),
    );
    expect(await screen.findByText("تم تسديد الطلب #10045 بالكامل.")).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.queryByRole("dialog", { name: "تسديد الطلب #10045" })).not.toBeInTheDocument(),
    );
  }, 20_000);

  it("sends a partial collection with the amount typed", async () => {
    const { fixture } = renderWith();
    const user = userEvent.setup();
    const win = await openWindow("orders", "إدارة الطلبات");
    await user.click(await within(win).findByRole("button", { name: "تسديد الطلب 10044" }));
    const dialog = await screen.findByRole("dialog", { name: "تسديد الطلب #10044" });
    await within(dialog).findByLabelText("حساب الدفعة 1");
    await user.click(within(dialog).getByRole("radio", { name: /تسديد جزئي/ }));
    await user.type(within(dialog).getByLabelText("مبلغ التسديد الجزئي"), "50000");
    await user.keyboard("{Control>}{Enter}{/Control}");
    await waitFor(() =>
      expect(fixture.calls.find((c) => c.path === "/orders/payment")?.body).toMatchObject({
        id: 10044,
        payment: "جزئي",
        paid_amount: 50000,
        payment_allocations: [{ treasury_account_id: 4, amount: 50000 }],
      }),
    );
  }, 20_000);

  it("cancels an order after confirmation and shows its history", async () => {
    const { fixture } = renderWith();
    const user = userEvent.setup();
    const win = await openWindow("orders", "إدارة الطلبات");
    await user.click(await within(win).findByText("#10045"));
    const panel = await screen.findByRole("complementary", { name: "الطلب #10045" });
    await user.click(within(panel).getByRole("tab", { name: /سجل الحركات/ }));
    expect(await within(panel).findByText("إنشاء الطلب")).toBeInTheDocument();
    await user.click(within(panel).getByRole("button", { name: /إلغاء/ }));
    const confirm = await screen.findByRole("dialog", { name: "إلغاء الطلب #10045" });
    await user.click(within(confirm).getByRole("button", { name: "إلغاء الطلب" }));
    await waitFor(() => expect(fixture.calls.some((c) => c.path === "/orders/cancel/10045")).toBe(true));
  }, 20_000);
});

describe("Order barcode scan", () => {
  it("scanning an order number asks for the shipping company's barcode and saves it", async () => {
    const { fixture } = renderWith();
    const win = await openWindow("orders", "إدارة الطلبات");
    await within(win).findByText("#10045");
    scanCode("10045");

    const dialog = await screen.findByRole("dialog", { name: "باركود شركة النقل — الطلب #10045" });
    // the only shipping company is chosen; the single piece gets one field
    await waitFor(() => expect(within(dialog).getByLabelText("شركة النقل")).toHaveValue("1"));
    const field = within(dialog).getByLabelText("باركود الشحن 1");
    await waitFor(() => expect(field).toHaveFocus());
    // scanner on an Arabic layout: physical keys are used, not the Arabic letters
    for (const [key, code] of [
      ["ش", "KeyA"],
      ["ل", "KeyG"],
      ["١", "Digit1"],
      ["٢", "Digit2"],
    ] as const) {
      fireEvent.keyDown(field, { key, code });
    }
    expect(field).toHaveValue("ag12");
    expect(within(dialog).getByText(/جاري الشحن/)).toBeInTheDocument();
    fireEvent.keyDown(field, { key: "Enter", code: "Enter" });
    await waitFor(() =>
      expect(fixture.calls.find((c) => c.path === "/orders/update-shipping-barcode/10045")?.body).toEqual({
        shipping_company_id: 1,
        shipping_barcodes: ["ag12"],
      }),
    );
    expect(
      await screen.findByText("الطلب #10045: تم حفظ وصل شركة النقل وتحويله إلى جاري الشحن."),
    ).toBeInTheDocument();
    // the order was in the table: no barcode lookup round trip
    expect(fixture.calls.some((c) => c.path === "/orders/search-by-barcode")).toBe(false);
  }, 20_000);

  it("looks up a barcode that is not in the table and says when nothing matches", async () => {
    const { fixture } = renderWith();
    const win = await openWindow("orders", "إدارة الطلبات");
    await within(win).findByText("#10045");
    scanCode("777777");
    const dialog = await screen.findByRole("dialog", { name: "باركود شركة النقل — الطلب 777777" });
    expect(await within(dialog).findByText("لا يوجد طلب بالباركود 777777")).toBeInTheDocument();
    expect(fixture.calls.some((c) => c.path === "/orders/search-by-barcode")).toBe(true);
  });

  it("follows Settings → الطلبات: details instead, off, and no auto-save", async () => {
    const { fixture } = renderWith();
    const win = await openWindow("orders", "إدارة الطلبات");
    await within(win).findByText("#10045");

    act(() => useOrderPreferences.getState().update({ scanAction: "details" }));
    scanCode("10045");
    expect(await screen.findByRole("complementary", { name: "الطلب #10045" })).toBeInTheDocument();
    expect(screen.queryByRole("dialog", { name: /باركود شركة النقل/ })).not.toBeInTheDocument();

    act(() => useOrderPreferences.getState().update({ scanAction: "off" }));
    scanCode("10044");
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(screen.queryByRole("complementary", { name: "الطلب #10044" })).not.toBeInTheDocument();

    act(() => useOrderPreferences.getState().update({ scanAction: "shipping", autoSaveShipping: false }));
    scanCode("10044");
    const dialog = await screen.findByRole("dialog", { name: "باركود شركة النقل — الطلب #10044" });
    const field = within(dialog).getByLabelText("باركود الشحن 1");
    await waitFor(() => expect(within(dialog).getByLabelText("شركة النقل")).toHaveValue("1"));
    fireEvent.change(field, { target: { value: "XY99" } });
    fireEvent.keyDown(field, { key: "Enter", code: "Enter" });
    await waitFor(() =>
      expect(within(dialog).getByRole("button", { name: /حفظ باركود الشحن/ })).toHaveFocus(),
    );
    expect(fixture.calls.some((c) => c.path.startsWith("/orders/update-shipping-barcode/"))).toBe(false);
  }, 20_000);
});

describe("Products window", () => {
  it("shows FINORA stock statistics and categories", async () => {
    renderWith();
    const win = await openWindow("products", "إدارة المنتجات");
    expect(await within(win).findByText("542")).toBeInTheDocument();
    expect(within(win).getByText("418")).toBeInTheDocument();
    expect(within(win).getByRole("tab", { name: "مكيفات" })).toBeInTheDocument();
    expect(await within(win).findByText("TV-LG-50-2026")).toBeInTheDocument();
    // stat card + row badge
    expect(within(win).getAllByText("نفذ المخزون").length).toBeGreaterThanOrEqual(2);
  });

  it("a keyboard-wedge barcode scan searches immediately (works on an Arabic layout)", async () => {
    const { fixture } = renderWith();
    const win = await openWindow("products", "إدارة المنتجات");
    await within(win).findByText("TV-LG-50-2026");
    const code = "6290000000035";
    const start = performance.now();
    let now = start;
    const spy = vi.spyOn(performance, "now").mockImplementation(() => now);
    for (const digit of code) {
      now += 8;
      // Arabic layout: `key` is an Arabic-Indic digit, `code` is the physical key
      fireEvent.keyDown(document.body, { key: "٠", code: `Digit${digit}` });
    }
    now += 8;
    fireEvent.keyDown(document.body, { key: "Enter", code: "Enter" });
    spy.mockRestore();
    await waitFor(() =>
      expect(
        fixture.calls.some((c) => c.path === "/inventory/api/products" && c.query?.search === code),
      ).toBe(true),
    );
    expect(await within(win).findByText("AC-GEN-1")).toBeInTheDocument();
  });
});

describe("Purchases window", () => {
  it("shows the summary, FINORA-state tabs and cancels with confirmation", async () => {
    const { fixture } = renderWith();
    const user = userEvent.setup();
    const win = await openWindow("purchases", "إدارة المشتريات");
    expect(await within(win).findByText("158,750,000")).toBeInTheDocument();
    expect(within(win).getByText("P-2026-0048")).toBeInTheDocument();
    // stat card, tab and the row's status badge
    expect(within(win).getAllByText("بانتظار الدفع").length).toBeGreaterThanOrEqual(3);

    await user.click(within(win).getByRole("button", { name: "إجراءات P-2026-0048" }));
    await user.click(await screen.findByRole("menuitem", { name: "إلغاء" }));
    const confirm = await screen.findByRole("dialog", { name: "إلغاء طلب الشراء" });
    await user.click(within(confirm).getByRole("button", { name: "إلغاء الطلب" }));
    await waitFor(() => expect(fixture.calls.some((c) => c.path === "/purchases/api/48/cancel")).toBe(true));
    expect(await screen.findByText("تم إلغاء الفاتورة P-2026-0048")).toBeInTheDocument();
  });
});

describe("Window persistence", () => {
  it("keeps a window's state when switching away and back (no remount)", async () => {
    renderWith();
    const user = userEvent.setup();
    const win = await openWindow("orders", "إدارة الطلبات");
    await within(win).findByText("#10045");
    await user.type(within(win).getByRole("searchbox"), "10045");
    act(() => useWindowManager.getState().open("products"));
    await screen.findByRole("dialog", { name: "إدارة المنتجات" });
    act(() => useWindowManager.getState().open("orders"));
    const again = await screen.findByRole("dialog", { name: "إدارة الطلبات" });
    expect(within(again).getByRole("searchbox")).toHaveValue("10045");
    expect(document.querySelectorAll('[data-state="open"]')).toHaveLength(1);
  });
});
