import { QueryClient } from "@tanstack/react-query";
import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { App } from "@/app/App";
import { useSession } from "@/stores/session";
import { useWindowManager } from "@/stores/windowManager";
import { createFinoraFixture } from "@/test/fixtures";
import { installMockBridge, removeMockBridge } from "@/test/mockBridge";
import { changedFields } from "./ProductEditor";

afterEach(() => {
  removeMockBridge();
  useWindowManager.getState().reset();
  useSession.setState({ status: "unknown", session: null, reason: null });
});

async function openProducts(missingDetails = false, colored = false) {
  const fixture = createFinoraFixture();
  const bridge = installMockBridge((request) =>
    colored && request.path === "/inventory/api/products/1"
      ? {
          ok: true,
          status: 200,
          data: {
            success: true,
            product: {
              id: 1,
              name: "شاشة LG 50 إنش 4K",
              current_stock: 28,
              has_colors: true,
              colors_supported: true,
              options_supported: true,
              color_images_supported: true,
              colors: [
                { id: 10, name: "أبيض", qty: 20, image_url: "/static/uploads/products/white.webp" },
                { id: 11, name: "أسود", qty: 8 },
              ],
            },
          },
        }
      : missingDetails && request.path === "/inventory/api/products/1"
        ? { ok: false, failure: "http", status: 404, data: "<html>Not Found</html>" }
        : fixture.handler(request),
  );
  render(<App queryClient={new QueryClient({ defaultOptions: { queries: { retry: false } } })} />);
  await screen.findByRole("navigation", { name: "النوافذ" });
  act(() => useWindowManager.getState().open("products"));
  const win = await screen.findByRole("dialog", { name: "إدارة المنتجات" });
  await within(win).findByText("TV-LG-50-2026");
  return { fixture, bridge, win };
}

describe("changedFields", () => {
  it("sends only what changed", () => {
    const base = {
      name: "A",
      sku: "S",
      barcode: "",
      buyPrice: 10,
      salePrice: 20,
      exchangePrice: 0,
      posVisible: true,
      storeVisible: true,
      lowStock: 5,
      category: "c",
      brand: "b",
      unit: "",
      description: "",
      active: true,
      openingStock: 0,
    };
    expect(changedFields(base, { ...base, salePrice: 25, brand: "" })).toEqual({ sale_price: 25, brand: "" });
    expect(changedFields(base, base)).toEqual({});
  });
});

describe("product editor", () => {
  it("edits exchange pricing and each visibility channel without submitting stock or normal prices", async () => {
    const { bridge, win } = await openProducts();
    const user = userEvent.setup();
    await user.click(within(win).getByRole("button", { name: "إجراءات شاشة LG 50 إنش 4K" }));
    await user.click(await screen.findByRole("menuitem", { name: "تعديل" }));
    const sheet = await screen.findByRole("dialog", { name: "تعديل منتج" });
    const exchange = await within(sheet).findByLabelText("سعر الاستبدال");
    await waitFor(() => expect(exchange).toHaveValue("300,000"));
    expect(within(sheet).getByRole("switch", { name: "إظهار في نقطة البيع" })).toBeChecked();
    expect(within(sheet).getByRole("switch", { name: "إظهار في المتجر" })).not.toBeChecked();
    await user.clear(exchange);
    await user.type(exchange, "310000");
    await user.click(within(sheet).getByRole("switch", { name: "إظهار في نقطة البيع" }));
    await user.click(within(sheet).getByRole("switch", { name: "إظهار في المتجر" }));
    await user.click(within(sheet).getByRole("button", { name: /حفظ التعديلات/ }));
    await waitFor(() => expect(bridge.finora.submitForm).toHaveBeenCalledTimes(1));
    expect(Object.fromEntries(bridge.finora.submitForm.mock.calls[0]?.[0].fields ?? [])).toEqual({
      exchange_sale_price: "310000",
      pos_visible: "0",
      store_visible: "1",
    });
  }, 20_000);

  it("removes only the selected color photo without submitting stock or prices", async () => {
    const { bridge, win } = await openProducts(false, true);
    const user = userEvent.setup();
    await user.click(within(win).getByRole("button", { name: "إجراءات شاشة LG 50 إنش 4K" }));
    await user.click(await screen.findByRole("menuitem", { name: "تعديل" }));
    const sheet = await screen.findByRole("dialog", { name: "تعديل منتج" });
    await within(sheet).findByAltText("صورة أبيض");
    await user.click(within(sheet).getByRole("button", { name: "إزالة صورة أبيض" }));
    await user.click(within(sheet).getByRole("button", { name: "حفظ التعديلات" }));
    await waitFor(() => expect(bridge.finora.submitForm).toHaveBeenCalledTimes(1));
    expect(bridge.finora.submitForm.mock.calls[0]?.[0]).toMatchObject({
      fields: [["color_images", '[{"name":"أبيض","remove":true}]']],
      files: [],
    });
  }, 20_000);
  it("adjusts only the selected color and keeps a stock reason", async () => {
    const { fixture, win } = await openProducts(false, true);
    const user = userEvent.setup();
    await user.click(within(win).getByRole("button", { name: "إجراءات شاشة LG 50 إنش 4K" }));
    await user.click(await screen.findByRole("menuitem", { name: "تعديل" }));
    const sheet = await screen.findByRole("dialog", { name: "تعديل منتج" });
    await user.selectOptions(await within(sheet).findByLabelText("لون تعديل المخزون"), "أسود");
    await user.click(within(sheet).getByRole("radio", { name: /خصم/ }));
    await user.click(within(sheet).getByRole("button", { name: "تلف" }));
    await user.click(within(sheet).getByRole("button", { name: /تطبيق على المخزون/ }));
    const confirm = await screen.findByRole("dialog", { name: "تأكيد تعديل المخزون" });
    expect(confirm).toHaveTextContent("أسود");
    expect(confirm).toHaveTextContent("8 ← 7");
    await user.click(within(confirm).getByRole("button", { name: "تطبيق" }));
    await waitFor(() =>
      expect(fixture.calls.find((c) => c.path === "/inventory/adjust-stock/1")?.body).toEqual({
        adjustment: -1,
        reason: "تلف",
        color_name: "أسود",
      }),
    );
  }, 20_000);
  it("adds colors without sending or overwriting existing stock balances", async () => {
    const { bridge, win } = await openProducts();
    const user = userEvent.setup();
    await user.click(within(win).getByRole("button", { name: "إجراءات شاشة LG 50 إنش 4K" }));
    await user.click(await screen.findByRole("menuitem", { name: "تعديل" }));
    const sheet = await screen.findByRole("dialog", { name: "تعديل منتج" });
    await user.click(within(sheet).getByRole("checkbox", { name: "هذا المنتج عنده خيارات" }));
    await user.type(within(sheet).getByLabelText("قيمة اللون"), "أبيض");
    await user.click(within(sheet).getByRole("button", { name: "إضافة خيار" }));
    await user.type(within(sheet).getByLabelText("قيمة اللون"), "أسود");
    await user.click(within(sheet).getByRole("button", { name: "إضافة خيار" }));
    expect(within(sheet).getByText(/المطلوب توزيع/)).toHaveTextContent("28 قطعة");
    await user.type(within(sheet).getByLabelText("قيمة اللون"), "أبيض");
    await user.click(within(sheet).getByRole("button", { name: "إضافة خيار" }));
    expect(within(sheet).getByRole("alert")).toHaveTextContent("الخيار مكرر");
    await user.click(within(sheet).getByRole("button", { name: /حفظ التعديلات/ }));
    await waitFor(() => expect(bridge.finora.submitForm).toHaveBeenCalledTimes(1));
    const fields = bridge.finora.submitForm.mock.calls[0]?.[0].fields;
    const options = JSON.parse(fields?.find(([key]) => key === "product_options")?.[1] ?? "{}");
    expect(options).toMatchObject({
      axes: ["اللون"],
      expected_stock: 28,
      rows: [
        { name: "أبيض", qty: 28 },
        { name: "أسود", qty: 0 },
      ],
    });
    expect(fields?.some(([key]) => key === "opening_stock")).toBe(false);
  }, 20_000);

  it("creates color-specific opening stock through the existing FINORA form", async () => {
    const { bridge, win } = await openProducts();
    const user = userEvent.setup();
    await user.click(within(win).getByRole("button", { name: /منتج جديد/ }));
    const sheet = await screen.findByRole("dialog", { name: "منتج جديد" });
    await user.type(within(sheet).getByLabelText("اسم المنتج"), "غسالة");
    await user.click(within(sheet).getByRole("checkbox", { name: "هذا المنتج عنده خيارات" }));
    for (const color of ["أبيض", "فضي"]) {
      await user.type(within(sheet).getByLabelText("قيمة اللون"), color);
      await user.click(within(sheet).getByRole("button", { name: "إضافة خيار" }));
    }
    await user.clear(within(sheet).getByLabelText("مخزون أبيض"));
    await user.type(within(sheet).getByLabelText("مخزون أبيض"), "4");
    await user.clear(within(sheet).getByLabelText("مخزون فضي"));
    await user.type(within(sheet).getByLabelText("مخزون فضي"), "2");
    await user.click(within(sheet).getByRole("button", { name: /حفظ المنتج/ }));
    await waitFor(() => expect(bridge.finora.submitForm).toHaveBeenCalled());
    const fields = bridge.finora.submitForm.mock.calls[0]?.[0].fields;
    expect(fields).toEqual(
      expect.arrayContaining([
        ["has_colors", "1"],
        ["opening_stock", "6"],
        ["color_name[]", "أبيض"],
        ["color_qty[]", "4"],
        ["color_name[]", "فضي"],
        ["color_qty[]", "2"],
      ]),
    );
  }, 20_000);
  it("creates a product through FINORA's add form with a generated barcode", async () => {
    const { bridge, win } = await openProducts();
    const user = userEvent.setup();
    await user.click(within(win).getByRole("button", { name: /منتج جديد/ }));
    const sheet = await screen.findByRole("dialog", { name: "منتج جديد" });
    await user.type(within(sheet).getByLabelText("اسم المنتج"), "مكيف جري 1.5 طن");
    await user.click(within(sheet).getByRole("button", { name: /توليد/ }));
    expect((within(sheet).getByLabelText("الباركود") as HTMLInputElement).value).toMatch(/^29\d{11}$/);
    await user.type(within(sheet).getByLabelText("الفئة"), "مكيفات");
    await user.type(within(sheet).getByLabelText("سعر الشراء"), "410000");
    await user.type(within(sheet).getByLabelText("سعر البيع"), "475000");
    expect(within(sheet).getByText(/الربح/)).toHaveTextContent("65,000");
    const opening = within(sheet).getByLabelText("المخزون الافتتاحي");
    await user.clear(opening);
    await user.type(opening, "6");
    await user.click(within(sheet).getByRole("button", { name: /حفظ المنتج/ }));

    await waitFor(() => expect(bridge.finora.submitForm).toHaveBeenCalled());
    const request = bridge.finora.submitForm.mock.calls[0]?.[0];
    expect(request?.path).toBe("/inventory/add");
    const fields = Object.fromEntries(request?.fields ?? []);
    expect(fields).toMatchObject({
      _response: "json",
      name: "مكيف جري 1.5 طن",
      category: "مكيفات",
      buy_price: "410000",
      sale_price: "475000",
      opening_stock: "6",
    });
    expect(fields.barcode).toMatch(/^29\d{11}$/);
    expect(await screen.findByText("تمت إضافة «مكيف جري 1.5 طن»")).toBeInTheDocument();
  }, 20_000);

  it("edits only the changed fields and adjusts stock with a reason", async () => {
    const { bridge, fixture, win } = await openProducts();
    const user = userEvent.setup();
    await user.click(within(win).getByRole("button", { name: "إجراءات شاشة LG 50 إنش 4K" }));
    await user.click(await screen.findByRole("menuitem", { name: "تعديل" }));
    const sheet = await screen.findByRole("dialog", { name: "تعديل منتج" });
    const sale = await within(sheet).findByLabelText("سعر البيع");
    await waitFor(() => expect(sale).toHaveValue("325,000"));
    await user.clear(sale);
    await user.type(sale, "335000");
    await user.click(within(sheet).getByRole("button", { name: /حفظ التعديلات/ }));
    await waitFor(() => expect(bridge.finora.submitForm).toHaveBeenCalled());
    expect(bridge.finora.submitForm.mock.calls[0]?.[0]).toMatchObject({
      path: "/inventory/api/products/1/update",
      fields: [["sale_price", "335000"]],
    });

    await user.click(within(win).getByRole("button", { name: "إجراءات شاشة LG 50 إنش 4K" }));
    await user.click(await screen.findByRole("menuitem", { name: "تعديل" }));
    const again = await screen.findByRole("dialog", { name: "تعديل منتج" });
    await user.click(await within(again).findByRole("radio", { name: /خصم/ }));
    await user.click(within(again).getByRole("button", { name: "تلف" }));
    await user.click(within(again).getByRole("button", { name: /تطبيق على المخزون/ }));
    await user.click(
      within(await screen.findByRole("dialog", { name: "تأكيد تعديل المخزون" })).getByRole("button", {
        name: "تطبيق",
      }),
    );
    await waitFor(() =>
      expect(fixture.calls.find((c) => c.path === "/inventory/adjust-stock/1")?.body).toEqual({
        adjustment: -1,
        reason: "تلف",
      }),
    );
  }, 20_000);

  it("never shows an editable blank form when FINORA cannot load the product", async () => {
    const { bridge, win } = await openProducts(true);
    const user = userEvent.setup();
    await user.click(within(win).getByRole("button", { name: "إجراءات شاشة LG 50 إنش 4K" }));
    await user.click(await screen.findByRole("menuitem", { name: "تعديل" }));
    const sheet = await screen.findByRole("dialog", { name: "تعديل منتج" });
    expect(await within(sheet).findByText("تعذر تحميل بيانات المنتج من FINORA")).toBeInTheDocument();
    expect(within(sheet).queryByLabelText("اسم المنتج")).not.toBeInTheDocument();
    expect(within(sheet).getByRole("button", { name: /حفظ التعديلات/ })).toBeDisabled();
    expect(bridge.finora.submitForm).not.toHaveBeenCalled();
  }, 20_000);
});
