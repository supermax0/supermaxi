import { QueryClient } from "@tanstack/react-query";
import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { App } from "@/app/App";
import { useComposer } from "@/features/purchases/composer";
import { useSession } from "@/stores/session";
import { useWindowManager } from "@/stores/windowManager";
import { usePurchaseNavigation } from "@/stores/purchaseNavigation";
import { createFinoraFixture, purchaseRow } from "@/test/fixtures";
import { installMockBridge, removeMockBridge } from "@/test/mockBridge";

afterEach(() => {
  cleanup();
  usePurchaseNavigation.getState().clear();
  useComposer.getState().reset();
  useComposer.getState().setOpen(false);
  useWindowManager.getState().reset();
  useSession.setState({ status: "unknown", session: null, reason: null });
  removeMockBridge();
});

test("off-page purchase source waits for the open composer and preserves the draft", async () => {
  const user = userEvent.setup();
  const fixture = createFinoraFixture();
  const fetched: string[] = [];
  installMockBridge((request) => {
    fetched.push(request.path);
    return request.path === "/purchases/api/901"
      ? { ok: true, status: 200, data: purchaseRow(901, { invoice_no: "PUR-OLD-901" }) }
      : fixture.handler(request);
  });
  render(<App queryClient={new QueryClient({ defaultOptions: { queries: { retry: false } } })} />);
  await screen.findByRole("navigation", { name: "النوافذ" });
  act(() => {
    useComposer.getState().addProduct({
      id: 99,
      name: "مسودة محفوظة",
      sku: "draft",
      barcode: "",
      buy_price: 100,
      quantity: 5,
      has_colors: false,
      colors: [],
    });
    useComposer.getState().setOpen(true);
    usePurchaseNavigation.getState().open(901);
    useWindowManager.getState().open("purchases");
  });
  await screen.findByRole("dialog", { name: "فاتورة شراء جديدة" });
  expect(fetched).not.toContain("/purchases/api/901");
  expect(usePurchaseNavigation.getState().target?.id).toBe(901);
  const draft = structuredClone(useComposer.getState().lines);
  await user.click(screen.getByRole("button", { name: "إغلاق فاتورة الشراء" }));
  await screen.findByRole("complementary", { name: "PUR-OLD-901" });
  await waitFor(() => expect(usePurchaseNavigation.getState().target).toBeNull());
  expect(fetched.filter((path) => path === "/purchases/api/901")).toHaveLength(1);
  expect(useComposer.getState().lines).toEqual(draft);
});
