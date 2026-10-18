import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { FinoraRequest, FinoraResponse } from "@shared/ipc";
import { useConnection } from "@/stores/connection";
import { useSession } from "@/stores/session";
import { installMockBridge, removeMockBridge, SESSION_PAYLOAD } from "@/test/mockBridge";
import { QuickOrderEditor } from "./QuickOrderEditor";

function setup(
  options: { editable?: boolean; customer?: boolean; price?: boolean; rejected?: boolean } = {},
) {
  const detail = {
    order: {
      id: 12,
      customer_id: 8,
      customer: "علي",
      phone: "07701234567",
      phone2: "07801234567",
      city: "بغداد",
      address: "المنصور",
      employee: "سارة",
      total: 105000,
      discount_amount: 0,
      paid_amount: 0,
      status: "تم الطلب",
      payment: "غير مسدد",
      created_at: "2026-10-10 09:00:00",
      shipping_company: null,
      note: "ملاحظة قديمة",
      can_edit_invoice: options.editable ?? true,
      can_edit_customer: options.customer ?? true,
      can_edit_price: options.price ?? true,
    },
    items: [
      {
        id: 1,
        product_id: 2,
        name: "شاشة",
        qty: 1,
        price: 100000,
        total: 100000,
        variant_color: "أسود",
        sale_mode: "normal",
      },
    ],
  };
  const writes: FinoraRequest[] = [];
  const handler = (request: FinoraRequest): FinoraResponse => {
    if (request.method === "POST") {
      writes.push(request);
      return options.rejected
        ? { ok: false, failure: "http", status: 409, data: { error: "المخزون غير كافٍ" } }
        : { ok: true, status: 200, data: { success: true } };
    }
    if (request.path === "/pos/api/products")
      return {
        ok: true,
        status: 200,
        data: {
          success: true,
          rows: [
            {
              id: 9,
              name: "شاشة بديلة",
              price: 200000,
              quantity: 3,
              colors: [
                { name: "أبيض", qty: 1, sale_price: 210000 },
                { name: "أسود", qty: 2, sale_price: 220000 },
              ],
            },
          ],
          page: 1,
          page_size: 12,
          total: 1,
          total_pages: 1,
          categories: [],
        },
      };
    return { ok: true, status: 200, data: detail };
  };
  installMockBridge(handler);
  useSession.getState().signedIn({ ...SESSION_PAYLOAD, permissions: ["manage_orders", "view_pos"] });
  useConnection.getState().setStatus("online");
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const close = vi.fn();
  render(
    <QueryClientProvider client={client}>
      <QuickOrderEditor orderId={12} onClose={close} />
    </QueryClientProvider>,
  );
  return { writes, close };
}

afterEach(() => {
  removeMockBridge();
  useSession.setState({ status: "unknown", session: null });
  useConnection.getState().setStatus("online");
});

it("replaces a product, preserves its selected color, previews fees and saves once with Ctrl+Enter", async () => {
  const { writes, close } = setup();
  const user = userEvent.setup();
  await user.click(await screen.findByRole("button", { name: "تبديل شاشة" }));
  await user.type(screen.getByLabelText("إضافة منتج للطلب"), "شاشة");
  await user.click(await screen.findByRole("button", { name: /شاشة بديلة.*المتوفر/ }));
  await user.selectOptions(screen.getByLabelText("لون شاشة بديلة"), "أسود");
  fireEvent.change(screen.getByLabelText("كمية شاشة بديلة"), { target: { value: "2" } });
  fireEvent.change(screen.getByLabelText("خصم الطلب"), { target: { value: "10000" } });
  fireEvent.change(screen.getByLabelText("ملاحظات الطلب"), { target: { value: "توصيل مساءً" } });
  expect(screen.getByText("435,000 د.ع")).toBeVisible();
  await act(async () => {
    fireEvent.keyDown(window, { key: "Enter", ctrlKey: true });
    fireEvent.keyDown(window, { key: "Enter", ctrlKey: true });
  });
  await waitFor(() => expect(close).toHaveBeenCalledTimes(1));
  expect(writes).toHaveLength(1);
  expect(writes[0]).toMatchObject({
    path: "/orders/quick-edit/12",
    body: {
      discount_amount: 10000,
      note: "توصيل مساءً",
      items: [{ product_id: 9, qty: 2, price: 220000, color: "أسود", sale_mode: "normal" }],
      customer: { name: "علي", phone2: "07801234567" },
    },
  });
});

it("retains a rejected draft and respects customer and price permissions", async () => {
  const { writes, close } = setup({ customer: false, price: false, rejected: true });
  await screen.findByRole("dialog", { name: "تعديل سريع للطلب #12" });
  expect(screen.getByLabelText("اسم الزبون")).toBeDisabled();
  expect(screen.queryByLabelText("سعر شاشة")).not.toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("ملاحظات الطلب"), { target: { value: "احتفظ بالتعديل" } });
  await act(async () => {
    fireEvent.click(screen.getByRole("button", { name: "حفظ التعديلات" }));
  });
  expect(await screen.findByRole("alert")).toHaveTextContent("المخزون غير كافٍ");
  expect(screen.getByLabelText("ملاحظات الطلب")).toHaveValue("احتفظ بالتعديل");
  expect(writes).toHaveLength(1);
  expect(writes[0]?.body).not.toHaveProperty("customer");
  expect(close).not.toHaveBeenCalled();
});

it("blocks invalid quantities, excessive discounts and offline saves", async () => {
  const { writes } = setup();
  await screen.findByRole("dialog", { name: "تعديل سريع للطلب #12" });
  fireEvent.change(screen.getByLabelText("كمية شاشة"), { target: { value: "0" } });
  fireEvent.keyDown(window, { key: "Enter", ctrlKey: true });
  expect(await screen.findByRole("alert")).toHaveTextContent("تحقق من الكمية والسعر");
  fireEvent.change(screen.getByLabelText("كمية شاشة"), { target: { value: "1" } });
  fireEvent.change(screen.getByLabelText("خصم الطلب"), { target: { value: "100001" } });
  fireEvent.keyDown(window, { key: "Enter", ctrlKey: true });
  expect(await screen.findByRole("alert")).toHaveTextContent("الخصم يجب");
  act(() => useConnection.getState().setStatus("offline"));
  expect(screen.getByRole("button", { name: "حفظ التعديلات" })).toBeDisabled();
  expect(writes).toHaveLength(0);
});

it("blocks centrally locked orders and closes an unchanged draft", async () => {
  const { close } = setup({ editable: false });
  await screen.findByRole("dialog", { name: "تعديل سريع للطلب #12" });
  expect(screen.getByLabelText("كمية شاشة")).toBeDisabled();
  expect(screen.getByRole("button", { name: "حفظ التعديلات" })).toBeDisabled();
  fireEvent.keyDown(window, { key: "Escape" });
  expect(close).toHaveBeenCalledTimes(1);
});

it("keeps unsaved changes when Escape is pressed until discard is explicitly selected", async () => {
  const { close, writes } = setup();
  await screen.findByRole("dialog", { name: "تعديل سريع للطلب #12" });
  fireEvent.change(screen.getByLabelText("ملاحظات الطلب"), { target: { value: "لا تضيع" } });
  fireEvent.keyDown(window, { key: "Escape" });
  expect(close).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "متابعة التعديل" }));
  expect(screen.getByLabelText("ملاحظات الطلب")).toHaveValue("لا تضيع");
  fireEvent.keyDown(window, { key: "Escape" });
  fireEvent.click(screen.getByRole("button", { name: "ترك التعديلات" }));
  expect(close).toHaveBeenCalledTimes(1);
  expect(writes).toHaveLength(0);
});
