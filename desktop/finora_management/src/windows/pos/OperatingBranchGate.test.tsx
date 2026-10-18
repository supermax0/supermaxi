import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { FinoraRequest } from "@shared/ipc";
import { installMockBridge, removeMockBridge } from "@/test/mockBridge";
import { OperatingBranchGate } from "./OperatingBranchGate";

const BASE = "/api/v1/desktop/branches";
const ok = (data: unknown) => ({ ok: true as const, status: 200, data: { ok: true, ...(data as object) } });

const meta = (canSwitch = true, count = 2) => ({
  multi_branch: { enabled: true, explicit: true, active_branches: count },
  primary_branch_id: 1,
  can_manage: true,
  types: [],
  current_branch_id: null,
  transfer_policy: { approval_required: false },
  scope: {
    can_switch: canSwitch,
    view_all: true,
    branches: [
      { id: 1, name: "الفرع الرئيسي", code: "MAIN", is_default: true },
      { id: 2, name: "فرع المنصور", code: "MNS", is_default: false },
    ].slice(0, count),
  },
});

function mount(branchId: number | null | undefined, body = meta()) {
  const bridge = installMockBridge((request: FinoraRequest) => {
    if (request.path === `${BASE}/meta`) return ok(body);
    if (request.path === `${BASE}/switch`) return ok({});
    return { ok: false, failure: "http", status: 404, data: { error: "not found" } };
  });
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <OperatingBranchGate branchId={branchId} />
    </QueryClientProvider>,
  );
  return bridge;
}

afterEach(removeMockBridge);

it("asks for the operating branch when the POS opens in the all-branches view, and switches the session", async () => {
  const bridge = mount(null);
  const user = userEvent.setup();
  expect(await screen.findByRole("alert", { name: "اختيار فرع البيع" })).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "فرع المنصور" }));
  await waitFor(() =>
    expect(bridge.finora.request.mock.calls.find(([r]) => r.path === `${BASE}/switch`)?.[0].body).toEqual({
      branch_id: 2,
    }),
  );
});

it("stays out of the way when a branch is already selected, while loading, or with a single branch", async () => {
  mount(7);
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  removeMockBridge();
  mount(undefined);
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  removeMockBridge();
  const single = mount(null, meta(true, 1));
  await waitFor(() => expect(single.finora.request).toHaveBeenCalled());
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
});

it("explains to a user who cannot switch branches instead of offering buttons", async () => {
  mount(null, meta(false));
  expect(await screen.findByText(/لا تملك صلاحية تبديل الفرع/)).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "فرع المنصور" })).not.toBeInTheDocument();
});
