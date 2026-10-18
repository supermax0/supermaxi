import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { FinoraRequest, FinoraResponse } from "@shared/ipc";
import type { CustomerSchedule } from "@/api/finora/customers";
import { useConnection } from "@/stores/connection";
import { installMockBridge, removeMockBridge } from "@/test/mockBridge";
import { CustomerScheduleEditor } from "./CustomerScheduleEditor";

const schedule: CustomerSchedule = {
  id: 3,
  customer_id: 8,
  invoice_id: 12,
  total: 400000,
  paid: 150000,
  revision: "a".repeat(64),
  history: [],
  history_total: 0,
  installments: [
    { id: 10, number: 1, date: "2026-11-01", total: 200000, paid: 150000 },
    { id: 11, number: 2, date: "2026-12-01", total: 200000, paid: 0 },
  ],
};

function setup(post: (request: FinoraRequest, count: number) => FinoraResponse, initial = schedule) {
  const writes: FinoraRequest[] = [];
  let reads = 0;
  installMockBridge((request) => {
    if (request.method === "POST") {
      writes.push(structuredClone(request));
      return post(request, writes.length);
    }
    reads++;
    return { ok: true, status: 200, data: { success: true, data: initial } };
  });
  useConnection.getState().setStatus("online");
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const close = vi.fn();
  const view = render(
    <QueryClientProvider client={client}>
      <CustomerScheduleEditor customerId={8} planId={3} onClose={close} />
    </QueryClientProvider>,
  );
  return {
    writes,
    close,
    client,
    reads: () => reads,
    dispose: () => {
      view.unmount();
      client.clear();
    },
  };
}

async function changeSchedule() {
  await screen.findByLabelText("استحقاق القسط 1");
  fireEvent.change(screen.getByLabelText("استحقاق القسط 1"), { target: { value: "2026-11-20" } });
  fireEvent.change(screen.getByLabelText("سبب إعادة الجدولة"), { target: { value: "طلب تأجيل موعد القسط" } });
}

afterEach(() => {
  removeMockBridge();
  useConnection.getState().setStatus("online");
});

it("edits future dates while preserving an immutable zero-net historical row", async () => {
  const initial: CustomerSchedule = {
    ...schedule,
    paid: 0,
    protected_ids: [10],
    installments: [
      { id: 10, number: 1, date: "2026-11-01", total: 0, paid: 0 },
      { id: 11, number: 2, date: "2026-12-01", total: 400000, paid: 0 },
    ],
  };
  const test = setup(
    () => ({
      ok: true,
      status: 200,
      data: {
        success: true,
        data: {
          ...initial,
          revision: "b".repeat(64),
          installments: initial.installments.map((row) =>
            row.id === 11 ? { ...row, date: "2026-12-15" } : row,
          ),
        },
      },
    }),
    initial,
  );
  await screen.findByLabelText("استحقاق القسط 1");
  expect(screen.getByLabelText("استحقاق القسط 1")).toBeDisabled();
  expect(screen.getByLabelText("قيمة القسط 1")).toBeDisabled();
  fireEvent.change(screen.getByLabelText("استحقاق القسط 2"), { target: { value: "2026-12-15" } });
  fireEvent.change(screen.getByLabelText("سبب إعادة الجدولة"), {
    target: { value: "تأجيل القسط المستقبلي" },
  });
  await userEvent.click(screen.getByRole("button", { name: "حفظ الجدولة" }));
  await waitFor(() => expect(test.writes).toHaveLength(1));
  expect(test.writes[0]?.body).toMatchObject({
    installments: [
      { id: 10, total: 0, date: "2026-11-01" },
      { id: 11, total: 400000, date: "2026-12-15" },
    ],
  });
  test.dispose();
});

it.each(["network", "malformed"])(
  "locks an uncertain %s result and retries the identical body and UUID",
  async (failure) => {
    const test = setup((_request, count) =>
      count === 1
        ? failure === "network"
          ? { ok: false, failure: "network" }
          : { ok: true, status: 200, data: { success: true, data: {} } }
        : {
            ok: true,
            status: 200,
            data: {
              success: true,
              data: {
                ...schedule,
                revision: "b".repeat(64),
                installments: schedule.installments.map((row) =>
                  row.id === 10 ? { ...row, date: "2026-11-20" } : row,
                ),
              },
            },
          },
    );
    await changeSchedule();
    await userEvent.click(screen.getByRole("button", { name: "حفظ الجدولة" }));
    await screen.findByRole("button", { name: "إعادة محاولة نفس الحفظ" });
    expect(screen.getByLabelText("استحقاق القسط 1")).toBeDisabled();
    expect(screen.getByLabelText("سبب إعادة الجدولة")).toBeDisabled();
    expect(screen.getByRole("button", { name: "إغلاق الجدولة" })).toBeDisabled();
    fireEvent.keyDown(window, { key: "Escape" });
    expect(test.close).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: "إعادة محاولة نفس الحفظ" }));
    await waitFor(() => expect(screen.getByLabelText("استحقاق القسط 1")).toBeEnabled());
    expect(test.writes).toHaveLength(2);
    expect(test.writes[1]?.body).toEqual(test.writes[0]?.body);
    expect(test.writes[0]?.body).toMatchObject({
      revision: schedule.revision,
      reason: "طلب تأجيل موعد القسط",
    });
    expect(screen.getByLabelText("سبب إعادة الجدولة")).toHaveValue("");
    test.dispose();
  },
);

it("preserves a conflicted draft until an explicit confirmed reload", async () => {
  const test = setup(() => ({
    ok: false,
    failure: "http",
    status: 409,
    data: { error: "تغير الرصيد أو الجدول" },
  }));
  await changeSchedule();
  await userEvent.click(screen.getByRole("button", { name: "حفظ الجدولة" }));
  await screen.findByText("تغير الرصيد أو الجدول");
  expect(screen.getByLabelText("استحقاق القسط 1")).toHaveValue("2026-11-20");
  await userEvent.click(screen.getByRole("button", { name: "تحميل أحدث جدول" }));
  await screen.findByRole("dialog", { name: "تعديلات غير محفوظة" });
  expect(test.reads()).toBe(1);
  await userEvent.click(screen.getByRole("button", { name: /^تحميل الجدول$/ }));
  await waitFor(() => expect(screen.getByLabelText("استحقاق القسط 1")).toHaveValue("2026-11-01"));
  expect(test.reads()).toBe(2);
  expect(test.writes).toHaveLength(1);
  test.dispose();
});

it("keeps fully paid rows locked and rejects a changed principal before sending", async () => {
  const test = setup(
    () => {
      throw new Error("Invalid schedule must not be sent");
    },
    {
      ...schedule,
      paid: 200000,
      installments: schedule.installments.map((row) => (row.id === 10 ? { ...row, paid: 200000 } : row)),
    },
  );
  await screen.findByLabelText("استحقاق القسط 1");
  expect(screen.getByLabelText("استحقاق القسط 1")).toBeDisabled();
  expect(screen.getByLabelText("قيمة القسط 1")).toBeDisabled();
  fireEvent.change(screen.getByLabelText("قيمة القسط 2"), { target: { value: "150000" } });
  fireEvent.change(screen.getByLabelText("سبب إعادة الجدولة"), { target: { value: "تغيير غير صالح" } });
  expect(screen.getByRole("button", { name: "حفظ الجدولة" })).toBeDisabled();
  fireEvent.keyDown(window, { key: "Enter", ctrlKey: true });
  expect(test.writes).toHaveLength(0);
  test.dispose();
});

it("closes help first and asks before discarding unsaved dates", async () => {
  const test = setup(() => {
    throw new Error("No save requested");
  });
  await changeSchedule();
  await userEvent.click(screen.getByRole("button", { name: "شرح إعادة الجدولة" }));
  fireEvent.keyDown(window, { key: "Escape" });
  expect(test.close).not.toHaveBeenCalled();
  expect(screen.queryByRole("dialog", { name: "تعديلات غير محفوظة" })).not.toBeInTheDocument();
  await waitFor(() => expect(document.querySelector("[data-popover]")).toBeNull());
  fireEvent.keyDown(window, { key: "Escape" });
  await screen.findByRole("dialog", { name: "تعديلات غير محفوظة" });
  await userEvent.click(screen.getByRole("button", { name: "إغلاق دون حفظ" }));
  expect(test.close).toHaveBeenCalledOnce();
  expect(test.writes).toHaveLength(0);
  test.dispose();
});
