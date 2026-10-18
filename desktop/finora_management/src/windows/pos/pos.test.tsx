import { QueryClient } from "@tanstack/react-query";
import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { App } from "@/app/App";
import { useCart } from "@/features/pos/cart";
import { useConnection } from "@/stores/connection";
import { EMPTY_OFFLINE, useOffline } from "@/stores/offline";
import { useSession } from "@/stores/session";
import { useWindowManager } from "@/stores/windowManager";
import { createFinoraFixture } from "@/test/fixtures";
import { installMockBridge, removeMockBridge } from "@/test/mockBridge";

async function openPos(exchangeProductId?: number) {
  const fixture = createFinoraFixture();
  const bridge = installMockBridge((request) => {
    const response = fixture.handler(request);
    if (exchangeProductId && request.path === "/pos/api/products" && response.ok) {
      const data = response.data as {
        rows: { id: number; has_exchange_sale?: boolean; exchange_sale_price?: number }[];
      };
      const product = data.rows.find((item) => item.id === exchangeProductId);
      if (product) Object.assign(product, { has_exchange_sale: true, exchange_sale_price: 200000 });
    }
    if (exchangeProductId && request.path === "/orders/details/10045" && response.ok) {
      const data = response.data as { order: { customer_id?: number }; items: Record<string, unknown>[] };
      data.order.customer_id = 9;
      data.items = [
        { ...data.items[0], qty: 1, price: 282000, sale_mode: "normal" },
        { ...data.items[0], id: 2, qty: 1, price: 200000, sale_mode: "exchange" },
      ];
    }
    return response;
  });
  render(<App queryClient={new QueryClient({ defaultOptions: { queries: { retry: false } } })} />);
  const nav = await screen.findByRole("navigation", { name: "النوافذ" });
  expect(within(nav).getByRole("button", { name: /نقطة البيع/ })).toBeInTheDocument();
  act(() => useWindowManager.getState().open("pos"));
  const win = await screen.findByRole("dialog", { name: "نقطة البيع" });
  return { fixture, bridge, win };
}

async function chooseCustomer(win: HTMLElement, user: ReturnType<typeof userEvent.setup>) {
  await user.type(within(win).getByLabelText("البحث عن زبون"), "علي");
  await user.click(await screen.findByRole("button", { name: /علي حسين/ }));
}

afterEach(() => {
  vi.restoreAllMocks();
  useOffline.setState({ status: EMPTY_OFFLINE });
  removeMockBridge();
  useWindowManager.getState().reset();
  useCart.getState().reset("cash");
  useSession.setState({ status: "unknown", session: null, reason: null });
  useConnection.getState().setStatus("online");
});

describe("POS window", () => {
  it("preserves exchange when editing an invoice containing both modes of the same product", async () => {
    const { fixture, win } = await openPos(1);
    const user = userEvent.setup();
    await user.click(within(win).getByRole("button", { name: "تعديل فاتورة" }));
    const dialog = await screen.findByRole("dialog", { name: "تعديل فاتورة" });
    await user.type(within(dialog).getByRole("textbox", { name: "رقم الطلب" }), "10045");
    await user.click(within(dialog).getByRole("button", { name: "تحميل" }));
    await waitFor(() => expect(useCart.getState().editingOrderId).toBe(10045));
    const lines = useCart.getState().lines;
    expect(lines.map((line) => line.saleMode)).toEqual(["normal", "exchange"]);
    expect(lines[0]?.key).not.toBe(lines[1]?.key);
    await user.click(within(win).getByRole("button", { name: "حفظ التعديل" }));
    await waitFor(() =>
      expect(fixture.calls.find((call) => call.path === "/pos/create-order")).toBeDefined(),
    );
    expect(fixture.calls.find((call) => call.path === "/pos/create-order")?.body).toMatchObject({
      order_id: 10045,
      items: [
        { product_id: 1, qty: 1, price: 282000 },
        { product_id: 1, qty: 1, price: 200000, sale_mode: "exchange" },
      ],
    });
    expect(fixture.calls.some((call) => call.path === "/orders/payment")).toBe(false);
  }, 15000);

  it("chooses sale or exchange, keeps separate lines, and submits the chosen mode", async () => {
    const { fixture, win } = await openPos(1);
    const user = userEvent.setup();
    const add = await within(win).findByRole("button", { name: "إضافة شاشة LG 50 بوصة" });
    await user.click(add);
    let picker = await screen.findByRole("dialog", { name: "بيع أو استبدال — شاشة LG 50 بوصة" });
    await user.click(within(picker).getByRole("button", { name: "تراجع" }));
    expect(useCart.getState().lines).toHaveLength(0);
    await waitFor(() =>
      expect(
        screen.queryByRole("dialog", { name: "بيع أو استبدال — شاشة LG 50 بوصة" }),
      ).not.toBeInTheDocument(),
    );
    await user.click(add);
    picker = await screen.findByRole("dialog", { name: "بيع أو استبدال — شاشة LG 50 بوصة" });
    await user.click(within(picker).getByRole("radio", { name: /^بيع/ }));
    await user.click(within(picker).getByRole("button", { name: "إضافة للسلة" }));
    await waitFor(() => expect(useCart.getState().lines).toHaveLength(1));
    await waitFor(() =>
      expect(
        screen.queryByRole("dialog", { name: "بيع أو استبدال — شاشة LG 50 بوصة" }),
      ).not.toBeInTheDocument(),
    );
    await user.click(add);
    picker = await screen.findByRole("dialog", { name: "بيع أو استبدال — شاشة LG 50 بوصة" });
    await user.click(within(picker).getByRole("radio", { name: /^استبدال/ }));
    await user.click(within(picker).getByRole("button", { name: "إضافة للسلة" }));
    await waitFor(() => expect(useCart.getState().lines).toHaveLength(2));
    expect(useCart.getState().lines.map((line) => [line.saleMode, line.unitPrice])).toEqual([
      ["normal", 282000],
      ["exchange", 200000],
    ]);
    await chooseCustomer(win, user);
    await user.click(within(win).getByRole("button", { name: "تنفيذ و طباعة" }));
    await waitFor(() =>
      expect(fixture.calls.find((call) => call.path === "/pos/create-order")).toBeDefined(),
    );
    expect(fixture.calls.find((call) => call.path === "/pos/create-order")?.body).toMatchObject({
      items: [
        { product_id: 1, qty: 1, price: 282000 },
        { product_id: 1, qty: 1, price: 200000, sale_mode: "exchange" },
      ],
    });
  }, 15000);

  it("selects a colour before exchange and blocks local checkout without losing that choice", async () => {
    const { fixture, win } = await openPos(2);
    const user = userEvent.setup();
    await user.click(await within(win).findByRole("button", { name: "إضافة Samsung A55" }));
    let picker = await screen.findByRole("dialog", { name: "اختر اللون — Samsung A55" });
    await user.click(within(picker).getByRole("radio", { name: /أزرق/ }));
    await user.click(within(picker).getByRole("button", { name: "إضافة للسلة" }));
    picker = await screen.findByRole("dialog", { name: "بيع أو استبدال — Samsung A55" });
    await user.click(within(picker).getByRole("radio", { name: /^استبدال/ }));
    await user.click(within(picker).getByRole("button", { name: "إضافة للسلة" }));
    await waitFor(() =>
      expect(useCart.getState().lines[0]).toMatchObject({
        saleMode: "exchange",
        color: "أزرق",
        unitPrice: 200000,
      }),
    );
    await chooseCustomer(win, user);
    act(() => useConnection.getState().setStatus("offline"));
    await user.click(within(win).getByRole("button", { name: "تنفيذ و طباعة" }));
    expect(await screen.findByText(/الاستبدال يحتاج اتصالاً بالإنترنت/)).toBeInTheDocument();
    expect(fixture.calls.some((call) => ["/pos/create-order", "/orders/payment"].includes(call.path))).toBe(
      false,
    );
    expect(useCart.getState().lines[0]?.saleMode).toBe("exchange");
  }, 15000);

  it("offline cash checkout saves one local operation and prints its receipt without separate network writes", async () => {
    const { fixture, bridge, win } = await openPos();
    const status = { ...EMPTY_OFFLINE, available: true };
    const offlineBridge = {
      status: vi.fn().mockResolvedValue(status),
      synchronize: vi.fn().mockResolvedValue(status),
      reserveStock: vi.fn().mockResolvedValue(status),
      returnStock: vi.fn().mockResolvedValue(status),
      resumeStockRequest: vi.fn().mockResolvedValue(status),
      downloadSnapshot: vi.fn().mockResolvedValue(status),
      saveSupplierDraft: vi.fn(),
      retry: vi.fn().mockResolvedValue(status),
      savePosSale: vi
        .fn()
        .mockResolvedValue({ id: "operation", localInvoiceNo: "OFF-LOCAL-000001", total: 282000 }),
      printPosSale: vi.fn().mockResolvedValue(undefined),
    };
    Object.assign(bridge, { offline: offlineBridge });
    const user = userEvent.setup();
    await user.click(await within(win).findByRole("button", { name: "إضافة شاشة LG 50 بوصة" }));
    await chooseCustomer(win, user);
    vi.spyOn(window.navigator, "onLine", "get").mockReturnValue(false);
    act(() => {
      useOffline.setState({ status });
      useConnection.getState().setStatus("offline");
    });
    await user.click(within(win).getByRole("button", { name: "تنفيذ و طباعة" }));
    await waitFor(() => expect(offlineBridge.savePosSale).toHaveBeenCalled());
    expect(offlineBridge.savePosSale).toHaveBeenCalledWith(expect.stringMatching(/^[a-f0-9-]{36}$/), {
      kind: "pos",
      customerId: 9,
      customerName: "علي حسين",
      items: [{ product_id: 1, qty: 1, price: 282000 }],
      discount: 0,
      total: 282000,
      payment: "cash",
      accountId: 4,
    });
    await waitFor(() => expect(offlineBridge.printPosSale).toHaveBeenCalledWith("operation"));
    expect(fixture.calls.some((c) => ["/pos/create-order", "/orders/payment"].includes(c.path))).toBe(false);
    expect(bridge.print.open).not.toHaveBeenCalled();
    expect(await screen.findByText(/تم اعتماد البيع المحلي #000001/)).toBeInTheDocument();
    await waitFor(() => expect(useCart.getState().lines).toHaveLength(0));
  }, 15_000);
  it("cash sale: cart, colour, discount, customer, FINORA checkout, payment to the cash drawer, print", async () => {
    const { fixture, bridge, win } = await openPos();
    const user = userEvent.setup();

    await user.click(await within(win).findByRole("button", { name: "إضافة شاشة LG 50 بوصة" }));
    await user.click(within(win).getByRole("button", { name: "إضافة شاشة LG 50 بوصة" }));
    await user.click(within(win).getByRole("button", { name: "إضافة Samsung A55" }));
    const picker = await screen.findByRole("dialog", { name: "اختر اللون — Samsung A55" });
    await user.click(within(picker).getByRole("radio", { name: /أزرق/ }));
    await user.click(within(picker).getByRole("button", { name: "إضافة للسلة" }));

    await user.type(within(win).getByLabelText("قيمة الخصم"), "4000");
    await waitFor(() => expect(within(win).getByTestId("pos-total")).toHaveTextContent("880,000"));

    await chooseCustomer(win, user);
    expect(
      within(within(win).getByRole("region", { name: "الزبون" })).getByText("07705556633"),
    ).toBeInTheDocument();

    await user.click(within(win).getByRole("button", { name: "تنفيذ و طباعة" }));
    await waitFor(() => expect(fixture.calls.some((c) => c.path === "/orders/payment")).toBe(true));

    expect(fixture.calls.find((c) => c.path === "/pos/create-order")?.body).toMatchObject({
      customer_id: 9,
      discount_amount: 4000,
      items: [
        { product_id: 1, qty: 2, price: 282000 },
        { product_id: 2, qty: 1, price: 320000, color: "أزرق" },
      ],
    });
    expect(fixture.calls.find((c) => c.path === "/orders/payment")?.body).toEqual({
      id: 10046,
      payment: "مسدد",
      payment_allocations: [{ treasury_account_id: 4, amount: 880000 }],
    });
    expect(bridge.print.open).toHaveBeenCalledWith({ kind: "orders", ids: [10046] });
    expect(await screen.findByText(/تم تنفيذ الطلب #10046/)).toBeInTheDocument();
    await waitFor(() => expect(useCart.getState().lines).toHaveLength(0));
  }, 15_000);

  it("credit (أجل) sale creates the order without a payment and without printing", async () => {
    const { fixture, bridge, win } = await openPos();
    const user = userEvent.setup();
    await user.click(within(win).getByRole("radio", { name: "أجل" }));
    await user.click(await within(win).findByRole("button", { name: "إضافة شاشة LG 50 بوصة" }));
    await chooseCustomer(win, user);
    await user.click(within(win).getByRole("button", { name: "خيارات التنفيذ" }));
    await user.click(await screen.findByRole("menuitem", { name: "تنفيذ بدون طباعة" }));
    await waitFor(() => expect(fixture.calls.some((c) => c.path === "/pos/create-order")).toBe(true));
    expect(fixture.calls.some((c) => c.path === "/orders/payment")).toBe(false);
    expect(bridge.print.open).not.toHaveBeenCalled();
  });

  it("adds a new customer with FINORA's required fields", async () => {
    const { fixture, win } = await openPos();
    const user = userEvent.setup();
    await user.click(within(win).getAllByRole("button", { name: "إضافة زبون" })[0] as HTMLElement);
    const form = within(win).getByRole("form", { name: "إضافة زبون جديد" });
    await user.type(within(form).getByPlaceholderText("اسم الزبون الكامل"), "سارة ناصر");
    await user.type(within(form).getByPlaceholderText("07701234567"), "0781999");
    await user.click(within(form).getByRole("button", { name: "حفظ العميل" }));
    expect(within(form).getByRole("alert")).toHaveTextContent("11 رقم");

    await user.type(within(form).getByPlaceholderText("07701234567"), "8877");
    await user.selectOptions(within(form).getByRole("combobox"), "البصرة");
    await user.type(within(form).getByPlaceholderText("العنوان التفصيلي"), "حي النصر");
    await user.click(within(form).getByRole("button", { name: "حفظ العميل" }));
    await waitFor(() =>
      expect(fixture.calls.find((c) => c.path === "/pos/add-customer")?.body).toMatchObject({
        name: "سارة ناصر",
        phone: "07819998877",
        city: "البصرة",
        address: "حي النصر",
        branch_id: 1,
      }),
    );
    expect(await within(win).findByText("سارة ناصر")).toBeInTheDocument();
  });

  it("checkout without a customer is blocked locally", async () => {
    const { fixture, win } = await openPos();
    const user = userEvent.setup();
    await user.click(await within(win).findByRole("button", { name: "إضافة شاشة LG 50 بوصة" }));
    await user.click(within(win).getByRole("button", { name: "تنفيذ و طباعة" }));
    expect(await screen.findByText("اختر زبوناً أو أضف زبوناً جديداً.")).toBeInTheDocument();
    expect(fixture.calls.some((c) => c.path === "/pos/create-order")).toBe(false);
  });
});
