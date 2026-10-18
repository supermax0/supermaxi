import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { FinoraRequest } from "@shared/ipc";
import type { PosProductsPage } from "@/api/finora/pos";
import { installMockBridge, removeMockBridge } from "@/test/mockBridge";
import { ProductsPanel } from "./ProductsPanel";

const product = (id: number, name: string, quantity: number) => ({
  id,
  name,
  sku: "",
  barcode: "",
  price: 1000,
  quantity,
  image_url: "",
  category: "",
  has_colors: false,
  colors: [],
});
const page = {
  success: true,
  rows: [product(1, "متوفر", 5), product(2, "ناقص", 0)],
  page: 1,
  page_size: 20,
  total: 2,
  total_pages: 1,
  categories: [],
} as unknown as PosProductsPage;

afterEach(removeMockBridge);

it("shows other branches' stock only for out-of-stock products, on demand", async () => {
  const bridge = installMockBridge((request: FinoraRequest) => {
    if (request.path === "/api/v1/desktop/branches/availability") {
      return {
        ok: true as const,
        status: 200,
        data: {
          ok: true,
          total: 7,
          rows: [
            { id: 1, name: "الفرع الرئيسي", code: "MAIN", quantity: 0, is_current: true },
            { id: 2, name: "فرع المنصور", code: "MNS", quantity: 7, is_current: false },
          ],
        },
      };
    }
    return { ok: false, failure: "http", status: 404, data: { error: "not found" } };
  });
  render(
    <QueryClientProvider client={new QueryClient()}>
      <ProductsPanel
        page={page}
        loading={false}
        error={null}
        category=""
        serverUrl={null}
        onCategory={() => {}}
        onPage={() => {}}
        onAdd={() => {}}
      />
    </QueryClientProvider>,
  );
  const links = screen.getAllByRole("button", { name: /توفره بالفروع الأخرى/ });
  expect(links).toHaveLength(1); // only the out-of-stock product
  expect(bridge.finora.request).not.toHaveBeenCalled(); // nothing is fetched until asked
  await userEvent.setup().click(links[0] as HTMLElement);
  expect(await screen.findByText("فرع المنصور")).toBeInTheDocument();
  expect(screen.queryByText("الفرع الرئيسي")).not.toBeInTheDocument(); // the current branch is not "another"
});
