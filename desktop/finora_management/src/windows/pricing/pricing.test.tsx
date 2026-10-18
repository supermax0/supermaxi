import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { FinoraRequest } from "@shared/ipc";
import { installMockBridge, removeMockBridge } from "@/test/mockBridge";
import { useSession } from "@/stores/session";
import { useWindowManager } from "@/stores/windowManager";
import { PricingWindow } from "./PricingWindow";

const BASE = "/api/v1/desktop/pricing";
const ok = (data: unknown) => ({
  ok: true as const,
  status: 200,
  data: { success: true, ...(data as object) },
});
const batch = {
  id: 3,
  label: "اقتراحات القواعد",
  source: "rules",
  status: "draft",
  counts: { up: 1, below_minimum: 1 },
  net_change_per_unit: 63000,
  rows: [
    {
      id: 1,
      product_id: 7,
      name: "شاشة LG",
      ref: "55UR80",
      old_price: 500000,
      new_price: 563000,
      cost_basis: 450000,
      minimum_price: 474000,
      verdict: "up",
      note: "",
      applied: false,
    },
    {
      id: 2,
      product_id: 8,
      name: "غسالة",
      ref: "WW90",
      old_price: 420000,
      new_price: 320000,
      cost_basis: 300000,
      minimum_price: 333334,
      verdict: "below_minimum",
      note: "",
      applied: false,
    },
  ],
};

function mount(permissions: string[]) {
  useWindowManager.setState({ active: "pricing" } as never);
  useSession.setState({
    session: { permissions, user: { id: 1, name: "x", username: "x", role: "sales" } },
  } as never);
  const bridge = installMockBridge((r: FinoraRequest) => {
    if (r.path === `${BASE}/rules`) return ok({ rows: [] });
    if (r.path === `${BASE}/batches/from-rules`) return ok({ batch });
    if (r.path === `${BASE}/batches/3/approve`) return ok({ result: { applied: 1, stale: 0, skipped: 1 } });
    return { ok: false, failure: "http", status: 404, data: { error: "not found" } } as never;
  });
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <PricingWindow />
    </QueryClientProvider>,
  );
  return bridge;
}

afterEach(() => {
  removeMockBridge();
  useSession.setState({ session: null } as never);
});

it("previews proposals with the safe-minimum verdict and lets an approver apply them", async () => {
  const bridge = mount(["pricing.view", "pricing.manage", "pricing.approve"]);
  const user = userEvent.setup();
  await user.click(screen.getByRole("tab", { name: "تحديث جماعي" }));
  await user.click(screen.getByRole("button", { name: "اقترح من قواعد الهامش" }));
  expect(await screen.findByText("أقل من الحد الآمن — لن يُطبَّق")).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "اعتماد وتطبيق" }));
  await waitFor(() => expect(screen.getByText("طُبّقت هذه الدفعة.")).toBeInTheDocument());
  expect(bridge.finora.request.mock.calls.some(([r]) => r.path === `${BASE}/batches/3/approve`)).toBe(true);
});

it("a proposer without the approval right cannot apply", async () => {
  mount(["pricing.view", "pricing.manage"]);
  const user = userEvent.setup();
  await user.click(screen.getByRole("tab", { name: "تحديث جماعي" }));
  await user.click(screen.getByRole("button", { name: "اقترح من قواعد الهامش" }));
  expect(await screen.findByText(/يعتمدها من يملك صلاحية/)).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "اعتماد وتطبيق" })).not.toBeInTheDocument();
});

it("a promotion picks its product by name instead of typing an id", async () => {
  removeMockBridge();
  useWindowManager.setState({ active: "pricing" } as never);
  useSession.setState({
    session: {
      permissions: ["pricing.view", "pricing.manage"],
      user: { id: 1, name: "x", username: "x", role: "sales" },
    },
  } as never);
  const row = {
    id: 7,
    name: "شاشة LG 55",
    sku: "55UR80",
    barcode: "",
    category: "شاشات",
    brand: "",
    image_url: "",
    buy_price: 1,
    sale_price: 600000,
    quantity: 2,
    low_stock_threshold: 1,
    stock_state: "available",
    active: true,
  };
  const bridge = installMockBridge((r: FinoraRequest) => {
    if (r.path === "/inventory/api/products")
      return ok({
        rows: [row],
        page: 1,
        page_size: 8,
        total: 1,
        total_pages: 1,
        branch_scope_label: "",
        stats: { total: 1, available: 1, low: 0, out: 0 },
        categories: [],
      });
    if (r.path === `${BASE}/promotions` && r.method === "GET") return ok({ rows: [] });
    if (r.path === `${BASE}/promotions` && r.method === "POST") return ok({ id: 1, status: "scheduled" });
    return ok({ rows: [] });
  });
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <PricingWindow />
    </QueryClientProvider>,
  );
  const user = userEvent.setup();
  await user.click(screen.getByRole("tab", { name: "العروض" }));
  await user.type(screen.getByRole("textbox", { name: "المنتج" }), "55UR");
  await user.click(await screen.findByRole("option", { name: /شاشة LG 55/ }));
  expect(screen.getByText("السعر الحالي: 600,000 د.ع")).toBeInTheDocument();
  const post = () => bridge.finora.request.mock.calls.find(([r]) => r.method === "POST")?.[0];
  expect(post()).toBeUndefined();
});
