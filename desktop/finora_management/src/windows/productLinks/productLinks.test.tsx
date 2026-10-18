import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { FinoraRequest } from "@shared/ipc";
import { installMockBridge, removeMockBridge } from "@/test/mockBridge";
import { useSession } from "@/stores/session";
import { useWindowManager } from "@/stores/windowManager";
import { ProductLinksWindow } from "./ProductLinksWindow";

const BASE = "/api/v1/desktop/recommendations";
const ok = (data: unknown) => ({
  ok: true as const,
  status: 200,
  data: { success: true, ...(data as object) },
});
const product = (id: number, name: string, sku: string) => ({
  id,
  name,
  sku,
  barcode: "",
  category: "شاشات",
  brand: "",
  buy_price: 1,
  sale_price: 2,
  quantity: 3,
  image_url: "",
  low_stock_threshold: 1,
  stock_state: "available",
  active: true,
});
const PRODUCTS = [product(1, "شاشة سامسونج 55", "UA55"), product(2, "حامل شاشة جداري", "WM400")];

function mount() {
  useWindowManager.setState({ active: "productLinks" } as never);
  useSession.setState({
    session: {
      permissions: ["can_manage_inventory"],
      user: { id: 1, name: "x", username: "x", role: "sales" },
    },
  } as never);
  const relations: unknown[] = [];
  const bridge = installMockBridge((r: FinoraRequest) => {
    if (r.path === "/inventory/api/products") {
      const q = String((r.query as Record<string, string>)?.search ?? "");
      const rows = PRODUCTS.filter((p) => p.name.includes(q) || p.sku.includes(q));
      return ok({
        rows,
        page: 1,
        page_size: 8,
        total: rows.length,
        total_pages: 1,
        branch_scope_label: "",
        stats: { total: 2, available: 2, low: 0, out: 0 },
        categories: [],
      });
    }
    if (r.path === `${BASE}/relations` && r.method === "GET") return ok({ rows: relations });
    if (r.path === `${BASE}/relations` && r.method === "POST") {
      const b = r.body as Record<string, unknown>;
      const row = {
        id: 9,
        source_name: "شاشة سامسونج 55",
        target_name: "حامل شاشة جداري",
        priority: 50,
        ...b,
      };
      relations.splice(0, relations.length, row);
      return ok({ relation: row });
    }
    if (r.path === `${BASE}/bundles`) return ok({ rows: [] });
    return { ok: false, failure: "http", status: 404, data: { error: "not found" } } as never;
  });
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <ProductLinksWindow />
    </QueryClientProvider>,
  );
  return bridge;
}

afterEach(() => {
  removeMockBridge();
  useSession.setState({ session: null } as never);
});

it("links an accessory to a screen by searching both products and shows it as confirmed", async () => {
  const bridge = mount();
  const user = userEvent.setup();
  await user.type(screen.getByRole("textbox", { name: "المنتج الأساسي" }), "سامسونج");
  await user.click(await screen.findByRole("option", { name: /شاشة سامسونج 55/ }));
  await user.type(screen.getByRole("textbox", { name: "المنتج المقترح" }), "WM4");
  await user.click(await screen.findByRole("option", { name: /حامل شاشة جداري/ }));
  await user.type(screen.getByRole("textbox", { name: "ملاحظة التوافق" }), "VESA 400");
  await user.click(screen.getByRole("button", { name: "حفظ العلاقة" }));
  expect(await screen.findByText("مؤكدة — تظهر للزبون")).toBeInTheDocument();
  const sent = bridge.finora.request.mock.calls
    .map(([r]) => r)
    .find((r) => r.method === "POST" && r.path === `${BASE}/relations`);
  expect(sent?.body).toMatchObject({
    source_product_id: 1,
    target_product_id: 2,
    relation_type: "accessory",
    compatibility_note: "VESA 400",
    verified: true,
  });
});

it("a bundle needs a title and at least two products before it can be saved", async () => {
  mount();
  const user = userEvent.setup();
  await user.click(screen.getByRole("tab", { name: "الباقات" }));
  await user.click(await screen.findByRole("button", { name: "باقة جديدة" }));
  const saveBtn = screen.getByRole("button", { name: "حفظ الباقة" });
  await user.type(screen.getByRole("textbox", { name: "عنوان الباقة" }), "جهّز صالتك");
  await user.type(screen.getByRole("textbox", { name: "أضف منتجاً للباقة" }), "سامسونج");
  await user.click(await screen.findByRole("option", { name: /شاشة سامسونج 55/ }));
  expect(saveBtn).toBeDisabled();
  await user.type(screen.getByRole("textbox", { name: "أضف منتجاً للباقة" }), "حامل");
  await user.click(await screen.findByRole("option", { name: /حامل شاشة جداري/ }));
  await waitFor(() => expect(screen.getByRole("button", { name: "حفظ الباقة" })).toBeEnabled());
});
