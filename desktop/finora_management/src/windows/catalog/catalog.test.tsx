import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { FinoraRequest } from "@shared/ipc";
import { installMockBridge, removeMockBridge } from "@/test/mockBridge";
import { useWindowManager } from "@/stores/windowManager";
import { CatalogWindow } from "./CatalogWindow";

const BASE = "/api/v1/desktop/catalog";
const ok = (data: unknown) => ({
  ok: true as const,
  status: 200,
  data: { success: true, ...(data as object) },
});
const entry = {
  id: 4,
  canonical_name: "شاشة TCL 55",
  brand: "TCL",
  model_number: "55C7K",
  regional_version: "",
  category: "شاشات",
  description: "",
  attributes: { الحجم: "55 بوصة" },
  verification_status: "needs_review",
  field_sources: { brand: { source: "import:list.csv", confidence: 60 } },
  barcodes: ["6921732812345"],
  media: [],
  listing: null,
};

function mount(handler: (r: FinoraRequest) => unknown) {
  useWindowManager.setState({ active: "catalog" } as never);
  const bridge = installMockBridge((r: FinoraRequest) => {
    const res = handler(r);
    return (res ?? { ok: false, failure: "http", status: 404, data: { error: "not found" } }) as never;
  });
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <CatalogWindow />
    </QueryClientProvider>,
  );
  return bridge;
}

afterEach(removeMockBridge);

it("lists models and opens the editor with each value's source", async () => {
  mount((r) => {
    if (r.path === `${BASE}/entries`) return ok({ rows: [entry], total: 1, page: 1 });
    if (r.path === `${BASE}/entries/4`) return ok({ entry });
    if (r.path === "/api/v1/desktop/auth/session") return undefined;
    return undefined;
  });
  const user = userEvent.setup();
  await user.click(await screen.findByRole("button", { name: /شاشة TCL 55/ }));
  expect(await screen.findByDisplayValue("55C7K")).toBeInTheDocument();
  expect(screen.getByText(/المصدر: import:list.csv · ثقة 60%/)).toBeInTheDocument();
  expect(screen.getByText(/لا يُنشر موديل في المتجر قبل/)).toBeInTheDocument();
});

it("smart add looks up a barcode without saving and offers manual entry when nothing is known", async () => {
  const bridge = mount((r) => {
    if (r.path === `${BASE}/entries`) return ok({ rows: [], total: 0, page: 1 });
    if (r.path === `${BASE}/lookup`)
      return ok({ query: "6921732812345", catalog: [], inventory: null, candidates: [] });
    return undefined;
  });
  const user = userEvent.setup();
  await user.click(await screen.findByRole("tab", { name: "إضافة ذكية" }));
  await user.type(screen.getByRole("textbox", { name: "الباركود أو رقم الموديل" }), "6921732812345");
  await user.click(screen.getByRole("button", { name: "بحث" }));
  expect(await screen.findByText(/لم نجد هذا الباركود/)).toBeInTheDocument();
  expect(bridge.finora.request.mock.calls.some(([r]) => r.method === "POST")).toBe(false);
  await user.click(screen.getByRole("button", { name: "إدخال يدوي" }));
  expect(await screen.findByDisplayValue("6921732812345")).toBeInTheDocument(); // prefilled barcode, not saved yet
});

it("shows the import preview verdicts and applies the batch once", async () => {
  const bridge = mount((r) => {
    if (r.path === `${BASE}/entries`) return ok({ rows: [], total: 0, page: 1 });
    if (r.path === `${BASE}/imports/9/apply`)
      return ok({ result: { created: 1, updated: 0, linked: 0, skipped: 1 } });
    return undefined;
  });
  bridge.finora.submitForm.mockResolvedValue(
    ok({
      batch: {
        id: 9,
        filename: "list.csv",
        status: "preview",
        counts: { new: 1, duplicate: 1 },
        rows: [
          {
            id: 1,
            row_no: 2,
            status: "new",
            data: { name: "غسالة", model_number: "W9" },
            issues: [],
            match_entry_id: null,
            match_product_id: null,
            applied_entry_id: null,
          },
          {
            id: 2,
            row_no: 3,
            status: "duplicate",
            data: { name: "غسالة", model_number: "W-9" },
            issues: ["مكرر داخل نفس الملف"],
            match_entry_id: null,
            match_product_id: null,
            applied_entry_id: null,
          },
        ],
      },
    }) as never,
  );
  const user = userEvent.setup();
  await user.click(await screen.findByRole("tab", { name: "استيراد ملف" }));
  const input = document.querySelector('input[type="file"]') as HTMLInputElement;
  const csv = new File(["name,model;W9"], "list.csv", { type: "text/csv" });
  // jsdom's File has no arrayBuffer(); the real browser does
  Object.defineProperty(csv, "arrayBuffer", {
    value: async () => new TextEncoder().encode("name,model").buffer,
  });
  await user.upload(input, csv);
  expect(await screen.findByText("مكرر داخل نفس الملف")).toBeInTheDocument();
  expect(bridge.finora.submitForm.mock.calls[0]?.[0].file?.type).toBe("text/csv");
  await user.click(screen.getByRole("button", { name: "تنفيذ الاستيراد" }));
  await waitFor(() => expect(screen.getByText(/نُفّذت هذه الدفعة/)).toBeInTheDocument());
  expect(screen.queryByRole("button", { name: "تنفيذ الاستيراد" })).not.toBeInTheDocument();
});
