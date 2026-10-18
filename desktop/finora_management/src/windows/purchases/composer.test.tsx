import { QueryClient } from "@tanstack/react-query";
import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { App } from "@/app/App";
import { composerTotals, toNewPurchase, useComposer, validateComposer } from "@/features/purchases/composer";
import { useSession } from "@/stores/session";
import { useWindowManager } from "@/stores/windowManager";
import { createFinoraFixture } from "@/test/fixtures";
import { installMockBridge, removeMockBridge } from "@/test/mockBridge";

const product = (id: number, buy: number, colors: string[] = []) => ({
  id,
  name: `P${id}`,
  sku: `S${id}`,
  barcode: "",
  buy_price: buy,
  quantity: 3,
  has_colors: colors.length > 0,
  colors: colors.map((name) => ({ name, qty: 1 })),
});

afterEach(() => {
  removeMockBridge();
  useComposer.getState().reset();
  useComposer.getState().setOpen(false);
  useWindowManager.getState().reset();
  useSession.setState({ status: "unknown", session: null, reason: null });
});

describe("purchase composer store", () => {
  it("merges repeated products, mirrors FINORA's total formula and validates like FINORA", () => {
    const c = useComposer.getState();
    c.addProduct(product(1, 1000));
    c.addProduct(product(1, 1000));
    const coloured = c.addProduct(product(2, 500, ["أبيض"]));
    useComposer.getState().updateLine(coloured.key, { discount: 100 });
    useComposer.getState().patch({ discount: 200, shippingExtra: 50 });
    const state = useComposer.getState();
    expect(state.lines.map((l) => l.qty)).toEqual([2, 1]);
    expect(composerTotals(state)).toEqual({ subtotal: 2000 + 400, grand: 2400 - 200 + 50, units: 3 });

    expect(validateComposer(state)).toBe("اختر المورد أو أضف مورداً جديداً.");
    useComposer.getState().patch({ supplier: { id: 5, name: "X" } });
    expect(validateComposer(useComposer.getState())).toBe("يجب اختيار خيار للمنتج: P2");
    useComposer.getState().updateLine(coloured.key, { color: "أبيض" });
    expect(validateComposer(useComposer.getState())).toBeNull();
  });

  it("builds FINORA's payload: bank account payment, or a cash down payment on credit", () => {
    useComposer.getState().addProduct(product(1, 1000));
    useComposer.getState().patch({ supplier: { id: 5, name: "X" }, mode: "bank", bankAccountId: 9 });
    expect(toNewPurchase(useComposer.getState(), true)).toMatchObject({
      supplierId: 5,
      mode: "bank",
      confirm: true,
      lines: [{ product_id: 1, quantity: 1, unit_cost_before_discount: 1000, discount_value: 0 }],
      payments: [{ amount: 1000, payment_method: "bank", treasury_account_id: 9 }],
    });
    useComposer.getState().patch({ mode: "credit", downPayment: 300 });
    expect(toNewPurchase(useComposer.getState(), false).payments).toEqual([
      { amount: 300, payment_method: "cash" },
    ]);
  });
});

describe("purchase composer UI", () => {
  it("creates a purchase: new supplier, product search, cost edit, confirm receipt", async () => {
    const fixture = createFinoraFixture();
    installMockBridge(fixture.handler);
    render(<App queryClient={new QueryClient({ defaultOptions: { queries: { retry: false } } })} />);
    const user = userEvent.setup();
    await screen.findByRole("navigation", { name: "النوافذ" });
    act(() => useWindowManager.getState().open("purchases"));
    const win = await screen.findByRole("dialog", { name: "إدارة المشتريات" });

    await user.click(await within(win).findByRole("button", { name: /فاتورة شراء جديدة/ }));
    const composer = await screen.findByRole("dialog", { name: "فاتورة شراء جديدة" });

    await user.type(within(composer).getByLabelText("المورد"), "مورد التجربة");
    await user.click(await screen.findByRole("button", { name: /إضافة «مورد التجربة» كمورد جديد/ }));
    await user.click(await screen.findByRole("button", { name: "حفظ المورد" }));
    expect(await within(composer).findByText("مورد التجربة")).toBeInTheDocument();

    await user.type(within(composer).getByLabelText("إضافة منتج"), "شاشة");
    await user.click(await screen.findByRole("option", { name: /شاشة LG 50 بوصة/ }));
    const qty = await within(composer).findByLabelText("كمية شاشة LG 50 بوصة");
    await user.clear(qty);
    await user.type(qty, "4");
    const cost = within(composer).getByLabelText("سعر شراء شاشة LG 50 بوصة");
    await user.clear(cost);
    await user.type(cost, "265000");
    await waitFor(() =>
      expect(within(composer).getByTestId("purchase-total")).toHaveTextContent("1,060,000"),
    );

    await user.click(within(composer).getByRole("button", { name: /حفظ وتأكيد الاستلام/ }));
    await waitFor(() => expect(fixture.calls.some((c) => c.path === "/purchases/create")).toBe(true));
    expect(fixture.calls.find((c) => c.path === "/purchases/create")?.body).toMatchObject({
      supplier_id: 99,
      purchase_mode: "credit",
      status: "confirmed",
      items: [{ product_id: 11, quantity: 4, unit_cost_before_discount: 265000, discount_value: 0 }],
    });
    expect(await screen.findByText(/تم حفظ فاتورة الشراء PUR-TEST-300/)).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.queryByRole("dialog", { name: "فاتورة شراء جديدة" })).not.toBeInTheDocument(),
    );
  }, 20_000);
});
