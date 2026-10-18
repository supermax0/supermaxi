import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { FinoraRequest } from "@shared/ipc";
import { installMockBridge, removeMockBridge } from "@/test/mockBridge";
import { useSession } from "@/stores/session";
import { useWindowManager } from "@/stores/windowManager";
import { StoreAnalyticsWindow } from "./StoreAnalyticsWindow";

const BASE = "/api/v1/desktop/store-analytics";
const ok = (data: unknown) => ({
  ok: true as const,
  status: 200,
  data: { success: true, ...(data as object) },
});
const dashboard = (holdout: number) => ({
  days: 30,
  behaviour: {
    sessions: 40,
    searches: 25,
    searches_no_results: 5,
    no_result_rate: 20,
    top_searches: [{ query: "شاشة 55", count: 9 }],
    top_no_results: [{ query: "مكيف صحراوي", count: 4 }],
    product_views: 90,
    add_to_cart: 12,
    removed_from_cart: 2,
    checkout_started: 6,
    orders: 4,
    conversion_rate: 10,
    funnel: [
      { step: "زيارات (جلسات)", count: 40 },
      { step: "أكملوا الطلب", count: 4 },
    ],
  },
  sales: {
    orders: 4,
    orders_all: 5,
    revenue: 3_200_000,
    average_order_value: 800_000,
    units_per_order: 1.5,
    estimated_margin: 400_000,
    estimated_margin_pct: 12.5,
    cancel_rate: 20,
    return_rate: 0,
    top_products: [{ product_id: 1, name: "شاشة سامسونج 55", units: 3 }],
  },
  recommendations: {
    sections: [
      {
        section: "accessories",
        views: 30,
        clicks: 6,
        ctr: 20,
        attributed_sales: 2,
        attributed_value: 100_000,
      },
    ],
    attributed_value: 100_000,
    experiment: holdout
      ? {
          holdout_pct: holdout,
          holdout: { sessions: 20, orders: 1, conversion_rate: 5 },
          exposed: { sessions: 20, orders: 3, conversion_rate: 15 },
          enough_data: false,
          min_sessions_per_group: 200,
        }
      : null,
  },
  unmet_demand: {
    viewed_out_of_stock: [{ product_id: 9, name: "ثلاجة نافدة", views: 7 }],
    availability_requests: [],
  },
  vitals: [
    {
      page: "all",
      samples: 50,
      lcp_p75_ms: 2100,
      cls_p75: 0.04,
      inp_p75_ms: 260,
      passes: { lcp: true, cls: true, inp: false },
    },
  ],
  server: {
    since: 0,
    rows: [{ endpoint: "storefront.store_index", count: 30, p50_ms: 80, p95_ms: 190, max_ms: 400 }],
  },
});

function mount(role: string) {
  useWindowManager.setState({ active: "storeAnalytics" } as never);
  useSession.setState({
    session: { permissions: ["view_financial"], user: { id: 1, name: "x", username: "x", role } },
  } as never);
  let holdout = 0;
  let design = false;
  const bridge = installMockBridge((r: FinoraRequest) => {
    if (r.path.startsWith(`${BASE}?days=`)) return ok(dashboard(holdout));
    if (r.path === `${BASE}/settings`) {
      if (r.method === "POST") design = Boolean((r.body as { design_v2?: boolean }).design_v2 ?? design);
      return ok({ design_v2: design, about_text: "", returns_policy: "" });
    }
    if (r.path === `${BASE}/experiment`) {
      holdout = Number((r.body as { holdout_pct: number }).holdout_pct);
      return ok({ holdout_pct: holdout });
    }
    return { ok: false, failure: "http", status: 404, data: { error: "not found" } } as never;
  });
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <StoreAnalyticsWindow />
    </QueryClientProvider>,
  );
  return bridge;
}

afterEach(() => {
  removeMockBridge();
  useSession.setState({ session: null } as never);
});

it("shows real sales, the funnel, unmet demand, recommendation effect and speed against the targets", async () => {
  mount("sales");
  expect(await screen.findByText("3,200,000 د.ع")).toBeInTheDocument();
  expect(screen.getByText("مكيف صحراوي")).toBeInTheDocument();
  expect(screen.getByText("ثلاجة نافدة")).toBeInTheDocument();
  expect(screen.getByText("ملحقات متوافقة")).toBeInTheDocument();
  expect(screen.getByText(/النقرة ليست بيعاً/)).toBeInTheDocument();
  expect(screen.getByText("خارج الهدف")).toBeInTheDocument(); // INP 260 ms
  expect(screen.queryByRole("spinbutton", { name: "نسبة من لا يرى التوصيات" })).not.toBeInTheDocument(); // not admin
});

it("an admin turns the comparison experiment on and sees that data is not enough yet", async () => {
  const bridge = mount("admin");
  const user = userEvent.setup();
  const input = await screen.findByRole("spinbutton", { name: "نسبة من لا يرى التوصيات" });
  await user.clear(input);
  await user.type(input, "20");
  await user.click(screen.getByRole("button", { name: "حفظ" }));
  expect(await screen.findByText(/البيانات غير كافية للحكم/)).toBeInTheDocument();
  await waitFor(() =>
    expect(bridge.finora.request.mock.calls.some(([r]) => r.path === `${BASE}/experiment`)).toBe(true),
  );
});

it("an admin turns on the new store design; others do not see the switch", async () => {
  const bridge = mount("admin");
  const user = userEvent.setup();
  const sw = await screen.findByRole("switch", { name: "التصميم الجديد للمتجر" });
  expect(sw).not.toBeChecked();
  await user.click(sw);
  expect(await screen.findByText(/مفعّل: يراه كل الزبائن/)).toBeInTheDocument();
  expect(
    bridge.finora.request.mock.calls.some(([r]) => r.method === "POST" && r.path === `${BASE}/settings`),
  ).toBe(true);
});

it("a non-admin never sees the store settings", async () => {
  mount("sales");
  expect(await screen.findByText("3,200,000 د.ع")).toBeInTheDocument();
  expect(screen.queryByRole("switch", { name: "التصميم الجديد للمتجر" })).not.toBeInTheDocument();
});
