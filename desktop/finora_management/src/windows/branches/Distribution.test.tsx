import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { FinoraRequest } from "@shared/ipc";
import { installMockBridge, removeMockBridge } from "@/test/mockBridge";
import { Distribution } from "./Distribution";

const BASE = "/api/v1/desktop/branches/distribution";
const ok = (data: unknown) => ({ ok: true as const, status: 200, data: { ok: true, ...(data as object) } });
const session = (status: string) => ({
  id: 5,
  number: "DST-1",
  title: "توزيع أولي",
  status,
  created_at: "",
  finished_at: "",
  done: 0,
  failed: 0,
  total: 1,
  items: [
    { type: "stock", state: "pending", product_id: 9, quantity: 3, from_branch_id: 1, to_branch_id: 2 },
  ],
});
const preview = (blocked: boolean) => ({
  items: [
    {
      type: "stock",
      state: "pending",
      index: 0,
      verdict: blocked ? "blocked" : "ready",
      reason: blocked ? "المتاح بالفرع المصدر 1 فقط" : "",
      product_id: 9,
      quantity: 3,
      from_branch_id: 1,
      to_branch_id: 2,
    },
  ],
  summary: { stock_units: 3, stock_value: 450, cash: 0, staff: 0, blocked: blocked ? 1 : 0, items: 1 },
  can_execute: !blocked,
});

function mount(handler: (r: FinoraRequest) => unknown) {
  const bridge = installMockBridge(
    (r: FinoraRequest) =>
      (handler(r) as never) ?? {
        ok: false,
        failure: "http",
        status: 404,
        data: { error: "not found" },
      },
  );
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <Distribution enabled />
    </QueryClientProvider>,
  );
  return bridge;
}

afterEach(removeMockBridge);

it("explains why the wizard is unavailable for a new company and offers no session button", async () => {
  mount(
    (r) =>
      r.path === BASE &&
      ok({ eligibility: { eligible: false, reasons: ["شركة جديدة بلا بيانات تشغيلية"] }, rows: [] }),
  );
  expect(await screen.findByText("شركة جديدة بلا بيانات تشغيلية")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /جلسة توزيع جديدة/ })).not.toBeInTheDocument();
});

it("keeps approval disabled while an item is blocked and shows the server reason", async () => {
  mount((r) => {
    if (r.path === BASE)
      return ok({ eligibility: { eligible: true, reasons: [] }, rows: [session("draft")] });
    if (r.path === `${BASE}/5`) return ok({ session: session("draft"), preview: preview(true) });
    return undefined;
  });
  const user = userEvent.setup();
  await user.click(await screen.findByRole("button", { name: /توزيع أولي/ }));
  expect(await screen.findByText(/محجوب: المتاح بالفرع المصدر 1 فقط/)).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "اعتماد" })).toBeDisabled();
});
