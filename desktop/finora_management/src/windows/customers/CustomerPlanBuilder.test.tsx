import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { FinoraRequest, FinoraResponse } from "@shared/ipc";
import { installMockBridge, removeMockBridge, SESSION_PAYLOAD } from "@/test/mockBridge";
import { useSession } from "@/stores/session";
import { useFinanceNavigation } from "@/stores/financeNavigation";
import { useWindowManager } from "@/stores/windowManager";
import { useConnection } from "@/stores/connection";
import { CustomerPlanBuilder, partitionPreview } from "./CustomerPlanBuilder";

const source = {
  customer_id: 8,
  invoice_id: 12,
  total: 400000,
  paid: 0,
  revision: "a".repeat(64),
  plan_id: null,
  eligible: true,
  blocked_reason: "",
};
const schedule = {
  id: 3,
  customer_id: 8,
  invoice_id: 12,
  total: 400000,
  paid: 150000,
  revision: "b".repeat(64),
  protected_ids: [10],
  history: [],
  history_total: 0,
  installments: [
    { id: 10, number: 1, date: "2026-11-01", total: 200000, paid: 150000 },
    { id: 11, number: 2, date: "2026-12-01", total: 200000, paid: 0 },
  ],
};
function setup(
  response: (request: FinoraRequest, count: number) => FinoraResponse,
  plan = false,
  blocked = false,
  opening = false,
  historical = false,
  vouchers = false,
  netZero = false,
) {
  const writes: FinoraRequest[] = [];
  let reads = 0;
  installMockBridge((request) => {
    if (request.method === "POST") {
      writes.push(structuredClone(request));
      return response(request, writes.length);
    }
    reads++;
    return {
      ok: true,
      status: 200,
      data: {
        success: true,
        data: plan
          ? schedule
          : {
              ...source,
              ...(historical
                ? {
                    paid: netZero ? 0 : 125000,
                    historical: {
                      date: "2026-10-01",
                      paid: netZero ? 0 : 125000,
                      payment_count: 3,
                      ...(vouchers
                        ? {
                            vouchers: [
                              {
                                id: 6,
                                number: "RC-000006",
                                date: "2026-10-03",
                                amount: 75000,
                                reversed: netZero,
                              },
                            ],
                          }
                        : {}),
                    },
                  }
                : {}),
              ...(opening ? { total: 0 } : {}),
              ...(blocked ? { eligible: false, blocked_reason: "حركات دفع سابقة محفوظة" } : {}),
            },
      },
    };
  });
  useConnection.getState().setStatus("online");
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const close = vi.fn(),
    saved = vi.fn();
  const view = render(
    <QueryClientProvider client={client}>
      <CustomerPlanBuilder
        customerId={8}
        {...(opening ? { openingDebt: true } : plan ? { planId: 3 } : { invoiceId: 12 })}
        onClose={close}
        onSaved={saved}
      />
    </QueryClientProvider>,
  );
  return {
    writes,
    close,
    saved,
    reads: () => reads,
    dispose: () => {
      view.unmount();
      client.clear();
    },
  };
}
afterEach(() => {
  removeMockBridge();
  useConnection.getState().setStatus("online");
  useSession.setState({ status: "unknown", session: null });
  useFinanceNavigation.getState().clear();
  useWindowManager.getState().reset();
});
it("opens the original financial source only after confirming discarded changes", async () => {
  useSession.getState().signedIn({ ...SESSION_PAYLOAD, permissions: ["finance.view"] });
  const test = setup(
    () => ({ ok: true, status: 200, data: { success: true, data: schedule } }),
    false,
    false,
    false,
    true,
    true,
  );
  const sources = await screen.findByRole("region", { name: "سندات التحصيل السابقة" });
  expect(sources).toHaveTextContent("حصة هذه الفاتورة");
  expect(sources).toHaveTextContent("75,000");
  fireEvent.change(screen.getByLabelText("سبب تقسيم الأقساط"), { target: { value: "تقسيم قيد العمل" } });
  await userEvent.click(screen.getByRole("button", { name: "فتح السند RC-000006" }));
  expect(test.close).not.toHaveBeenCalled();
  expect(useFinanceNavigation.getState().voucherId).toBeNull();
  await userEvent.click(screen.getByRole("button", { name: "تراجع" }));
  expect(screen.getByLabelText("سبب تقسيم الأقساط")).toHaveValue("تقسيم قيد العمل");
  await userEvent.click(screen.getByRole("button", { name: "فتح السند RC-000006" }));
  await userEvent.click(screen.getByRole("button", { name: "فتح السند دون حفظ" }));
  expect(test.close).toHaveBeenCalledTimes(1);
  expect(useFinanceNavigation.getState().voucherId).toBe(6);
  expect(useFinanceNavigation.getState().collection).toBeNull();
  expect(useWindowManager.getState().active).toBe("finance");
  expect(test.writes).toHaveLength(0);
  test.dispose();
});
it("preserves zero-net reversed history without offering unauthorized financial navigation", async () => {
  const test = setup(
    () => ({ ok: true, status: 200, data: { success: true, data: schedule } }),
    false,
    false,
    false,
    true,
    true,
    true,
  );
  const sources = await screen.findByRole("region", { name: "سندات التحصيل السابقة" });
  expect(sources).toHaveTextContent("معكوس");
  expect(screen.queryByRole("button", { name: "فتح السند RC-000006" })).not.toBeInTheDocument();
  expect(screen.getByText("المبلغ القابل للتقسيم").parentElement).toHaveTextContent("400,000");
  expect(screen.getByRole("row", { name: /تحصيل سابق 2026-10-01/ })).toHaveTextContent("0 د.ع");
  expect(screen.getByLabelText("عدد الأقساط المتاحة")).toHaveAttribute("max", "239");
  expect(test.writes).toHaveLength(0);
  test.dispose();
});
it("creates only the remaining installments and explains the existing direct payment summary", async () => {
  const test = setup(
    () => ({ ok: true, status: 200, data: { success: true, data: schedule } }),
    false,
    false,
    false,
    true,
  );
  const dialog = await screen.findByRole("dialog", { name: "إنشاء جدول أقساط" });
  await waitFor(() => expect(screen.getByText("محفوظ — تحصيل سابق")).toBeVisible());
  expect(dialog).toHaveTextContent("275,000");
  expect(screen.getByRole("row", { name: /تحصيل سابق 2026-10-01/ })).toHaveTextContent("125,000");
  expect(screen.getByLabelText("عدد الأقساط المتاحة")).toHaveAttribute("max", "239");
  await userEvent.click(screen.getByRole("button", { name: "شرح تقسيم الأقساط" }));
  expect(screen.getByRole("note")).toHaveTextContent("ليس استحقاقاً جديداً");
  await userEvent.keyboard("{Escape}");
  fireEvent.change(screen.getByLabelText("أول استحقاق جديد"), { target: { value: "2027-01-31" } });
  fireEvent.change(screen.getByLabelText("سبب تقسيم الأقساط"), {
    target: { value: "تقسيم باقي الفاتورة بعد التحصيل السابق" },
  });
  expect(screen.getByRole("row", { name: /#4 2027-03-31/ })).toHaveTextContent("91,668");
  await userEvent.click(screen.getByRole("button", { name: "حفظ تقسيم الأقساط" }));
  await waitFor(() => expect(test.saved).toHaveBeenCalledTimes(1));
  expect(test.writes).toHaveLength(1);
  expect(test.writes[0]?.body).toMatchObject({ count: 3, revision: source.revision });
  expect(test.writes[0]?.body).not.toHaveProperty("paid");
  expect(test.writes[0]?.body).not.toHaveProperty("amount");
  test.dispose();
});

it("previews calendar month ends, leap years, weekly dates and exact final remainder", () => {
  expect(partitionPreview(400000, 3, "2027-01-31", "monthly")).toEqual([
    { date: "2027-01-31", total: 133333 },
    { date: "2027-02-28", total: 133333 },
    { date: "2027-03-31", total: 133334 },
  ]);
  expect(partitionPreview(6, 3, "2028-01-31", "monthly").map((row) => row.date)).toEqual([
    "2028-01-31",
    "2028-02-29",
    "2028-03-31",
  ]);
  expect(partitionPreview(6, 3, "2027-01-31", "weekly").map((row) => row.date)).toEqual([
    "2027-01-31",
    "2027-02-07",
    "2027-02-14",
  ]);
  expect(partitionPreview(2, 3, "2027-01-31", "weekly")).toEqual([]);
  expect(partitionPreview(6, 3, "2027-02-30", "monthly")).toEqual([]);
  expect(partitionPreview(6, 3, "9999-12-31", "monthly")).toEqual([]);
});
it("preserves paid rows in the preview and sends only a count command without financial writes", async () => {
  const test = setup(() => ({ ok: true, status: 200, data: { success: true, data: schedule } }), true);
  await screen.findByRole("dialog", { name: "تقسيم الأقساط المتاحة" });
  await waitFor(() => expect(screen.getByText("محفوظ — مرتبط بدفعات")).toBeVisible());
  expect(screen.getByRole("row", { name: /150,000/ })).toHaveTextContent("200,000");
  fireEvent.change(screen.getByLabelText("أول استحقاق جديد"), { target: { value: "2027-01-31" } });
  fireEvent.change(screen.getByLabelText("سبب تقسيم الأقساط"), { target: { value: "طلب تقسيم المبلغ" } });
  await userEvent.click(screen.getByRole("button", { name: "حفظ تقسيم الأقساط" }));
  await waitFor(() => expect(test.saved).toHaveBeenCalledTimes(1));
  expect(test.writes[0]?.path).toBe("/api/v1/desktop/customers/8/plans/3/repartition");
  expect(test.writes[0]?.body).toMatchObject({
    count: 3,
    revision: schedule.revision,
    first_due_date: "2027-01-31",
    interval: "monthly",
  });
  expect(test.writes[0]?.body).not.toHaveProperty("amount");
  test.dispose();
});
it.each(["network", "malformed"])(
  "freezes an uncertain %s create and repeats exactly the same UUID and fields",
  async (failure) => {
    const test = setup((_request, count) =>
      count === 1
        ? failure === "network"
          ? { ok: false, failure: "network" }
          : { ok: true, status: 200, data: { success: true, data: {} } }
        : { ok: true, status: 200, data: { success: true, data: schedule } },
    );
    await screen.findByLabelText("عدد الأقساط المتاحة");
    fireEvent.change(screen.getByLabelText("سبب تقسيم الأقساط"), { target: { value: "طلب إنشاء جدول" } });
    await userEvent.click(screen.getByRole("button", { name: "حفظ تقسيم الأقساط" }));
    await screen.findByRole("button", { name: "إعادة محاولة نفس الحفظ" });
    expect(screen.getByLabelText("عدد الأقساط المتاحة")).toBeDisabled();
    expect(screen.getByRole("button", { name: "إغلاق تقسيم الأقساط" })).toBeDisabled();
    await userEvent.keyboard("{Escape}");
    expect(test.close).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: "إعادة محاولة نفس الحفظ" }));
    await waitFor(() => expect(test.saved).toHaveBeenCalled());
    expect(test.writes).toHaveLength(2);
    expect(test.writes[1]?.body).toEqual(test.writes[0]?.body);
    test.dispose();
  },
);
it("keeps a confirmed conflict draft until an explicit reload and closes help before the dirty form", async () => {
  const test = setup(() => ({
    ok: false,
    failure: "http",
    status: 409,
    data: { success: false, error: "تغيرت الفاتورة" },
  }));
  await screen.findByLabelText("سبب تقسيم الأقساط");
  await userEvent.click(screen.getByRole("button", { name: "شرح تقسيم الأقساط" }));
  await userEvent.keyboard("{Escape}");
  expect(test.close).not.toHaveBeenCalled();
  fireEvent.change(screen.getByLabelText("سبب تقسيم الأقساط"), { target: { value: "طلب تقسيم جديد" } });
  await userEvent.click(screen.getByRole("button", { name: "حفظ تقسيم الأقساط" }));
  await screen.findByText("تغيرت الفاتورة");
  expect(screen.getByLabelText("سبب تقسيم الأقساط")).toHaveValue("طلب تقسيم جديد");
  await userEvent.click(screen.getByRole("button", { name: "تحميل أحدث مصدر" }));
  expect(test.reads()).toBe(1);
  await userEvent.click(screen.getByRole("button", { name: /^تحميل المصدر$/ }));
  await waitFor(() => expect(test.reads()).toBe(2));
  expect(screen.getByLabelText("سبب تقسيم الأقساط")).toHaveValue("");
  test.dispose();
});
it("shows a blocked source without allowing schedule creation", async () => {
  const test = setup(() => ({ ok: false, failure: "network" }), false, true);
  await screen.findByText("حركات دفع سابقة محفوظة");
  expect(screen.getByRole("button", { name: "حفظ تقسيم الأقساط" })).toBeDisabled();
  expect(screen.queryByLabelText("عدد الأقساط المتاحة")).not.toBeInTheDocument();
  expect(test.writes).toHaveLength(0);
  test.dispose();
});

it("requires a documented opening source and previews its exact whole-dinar schedule", async () => {
  const test = setup(
    () => ({
      ok: true,
      status: 200,
      data: { success: true, data: { ...schedule, invoice_id: null, paid: 0 } },
    }),
    false,
    false,
    true,
  );
  await screen.findByLabelText("مبلغ الدين الافتتاحي");
  const save = screen.getByRole("button", { name: "تسجيل الدين وترحيله" });
  expect(save).toBeDisabled();
  fireEvent.change(screen.getByLabelText("مبلغ الدين الافتتاحي"), { target: { value: "400000" } });
  fireEvent.change(screen.getByLabelText("وصف الدين الافتتاحي"), {
    target: { value: "رصيد متبقٍ حسب كشف خارجي" },
  });
  fireEvent.change(screen.getByLabelText("أول استحقاق جديد"), { target: { value: "2027-01-31" } });
  expect(save).toBeDisabled();
  fireEvent.change(screen.getByLabelText("مرجع مصدر الدين"), { target: { value: "EXT-2026-001" } });
  expect(screen.getByRole("cell", { name: "2027-02-28" })).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "شرح تقسيم الأقساط" }));
  expect(screen.getByRole("note")).toHaveTextContent("ذمم");
  await userEvent.keyboard("{Escape}");
  expect(test.close).not.toHaveBeenCalled();
  await userEvent.click(save);
  await waitFor(() => expect(test.saved).toHaveBeenCalled());
  expect(test.writes).toHaveLength(1);
  expect(test.writes[0]?.path).toBe("/api/v1/desktop/customers/8/debts");
  expect(test.writes[0]?.body).toMatchObject({
    amount: 400000,
    source_type: "opening",
    source_reference: "EXT-2026-001",
    count: 3,
    first_due_date: "2027-01-31",
    interval: "monthly",
  });
  test.dispose();
});

it("freezes an uncertain opening receivable and repeats its source reference, amount and UUID", async () => {
  const test = setup(
    (_request, count) =>
      count === 1
        ? { ok: false, failure: "network" }
        : { ok: true, status: 200, data: { success: true, data: { ...schedule, invoice_id: null } } },
    false,
    false,
    true,
  );
  await screen.findByLabelText("مبلغ الدين الافتتاحي");
  fireEvent.change(screen.getByLabelText("مبلغ الدين الافتتاحي"), { target: { value: "400000" } });
  fireEvent.change(screen.getByLabelText("وصف الدين الافتتاحي"), { target: { value: "رصيد خارجي موثق" } });
  fireEvent.change(screen.getByLabelText("مرجع مصدر الدين"), { target: { value: "EXT-01" } });
  useConnection.getState().setStatus("offline");
  await waitFor(() => expect(screen.getByRole("button", { name: "تسجيل الدين وترحيله" })).toBeDisabled());
  expect(test.writes).toHaveLength(0);
  useConnection.getState().setStatus("online");
  await waitFor(() => expect(screen.getByRole("button", { name: "تسجيل الدين وترحيله" })).toBeEnabled());
  await userEvent.click(screen.getByRole("button", { name: "تسجيل الدين وترحيله" }));
  await screen.findByRole("button", { name: "إعادة محاولة نفس الحفظ" });
  expect(screen.getByLabelText("مبلغ الدين الافتتاحي")).toBeDisabled();
  expect(screen.getByLabelText("مرجع مصدر الدين")).toBeDisabled();
  expect(screen.getByRole("button", { name: "تحميل أحدث مصدر" })).toBeDisabled();
  await userEvent.click(screen.getByRole("button", { name: "إعادة محاولة نفس الحفظ" }));
  await waitFor(() => expect(test.saved).toHaveBeenCalled());
  expect(test.writes[1]?.body).toEqual(test.writes[0]?.body);
  test.dispose();
});
