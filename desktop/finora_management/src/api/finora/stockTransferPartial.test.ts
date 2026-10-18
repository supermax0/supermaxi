import { vi } from "vitest";
import { finoraRequestSchema } from "@shared/ipc";
import { installMockBridge, removeMockBridge } from "@/test/mockBridge";
import { stockOperations } from "./stockOperations";

afterEach(removeMockBridge);
const root = "/api/v1/desktop/stock-operations/branch/transfers";

const detail = {
  id: 9,
  ledger_kind: "branch",
  number: "TR-9",
  from_location: "branch:1",
  to_location: "branch:2",
  from_name: "الرئيسي",
  to_name: "المنصور",
  status: "partially_received",
  quantity: 3,
  note: "",
  created_at: null,
  revision: "rev-1",
  can_send: false,
  can_receive: false,
  can_cancel: false,
  approval_required: true,
  can_approve: false,
  can_reject: false,
  can_receive_partial: false,
  can_resolve: true,
  lines: [
    {
      id: 51,
      product_id: 7,
      name: "سماعة",
      variant_name: "",
      quantity: 3,
      received: 2,
      sent: 3,
      residual: 1,
      cost: null,
    },
  ],
};

function recovery() {
  const acknowledge = vi.fn(async () => undefined);
  const bridge = window.finoraDesktop;
  if (!bridge) throw Error("missing test bridge");
  bridge.stockRecovery = {
    list: vi.fn(async () => ({ available: true, items: [] })),
    retry: vi.fn(async (): Promise<never> => {
      throw Error("not requested");
    }),
    acknowledge,
  };
  return acknowledge;
}

it("reads the partially-received state with what is still on the road", async () => {
  installMockBridge(() => ({ ok: true, status: 200, data: { success: true, data: detail } }));
  const result = await stockOperations.transfer("branch", 9);
  expect(result.status).toBe("partially_received");
  expect(result.can_resolve).toBe(true);
  expect(result.lines[0]).toMatchObject({ received: 2, residual: 1 });
});

it("still reads a warehouse-ledger transfer that carries none of the new fields", async () => {
  const { approval_required, can_approve, can_reject, can_receive_partial, can_resolve, ...legacy } = detail;
  void [approval_required, can_approve, can_reject, can_receive_partial, can_resolve];
  installMockBridge(() => ({
    ok: true,
    status: 200,
    data: {
      success: true,
      data: {
        ...legacy,
        status: "sent",
        lines: [{ id: 51, product_id: 7, name: "س", variant_name: "", quantity: 3, received: 0, cost: null }],
      },
    },
  }));
  const result = await stockOperations.transfer("warehouse", 9);
  expect(result.status).toBe("sent");
});

const phases: Array<
  ["receive_partial" | "resolve" | "reject" | "approve", { lines?: Array<Record<string, string | number>> }]
> = [
  ["receive_partial", { lines: [{ line_id: 51, received: 2 }] }],
  ["resolve", { lines: [{ line_id: 51, action: "return" }] }],
  ["reject", {}],
  ["approve", {}],
];

it.each(phases)(
  "%s posts to its own transfer action with a valid, acknowledged request",
  async (phase, extra) => {
    const bridge = installMockBridge(() => ({
      ok: true,
      status: 200,
      data: {
        success: true,
        data: { id: 9, type: "stock_transfer", ledger_kind: "branch", status: "received" },
        operation_id: "0dd34551-6f1a-4500-8aef-21a7415ad7c3",
      },
      customerCommandScope: "scope",
    }));
    const acknowledge = recovery();
    const body = {
      operation_id: "0dd34551-6f1a-4500-8aef-21a7415ad7c3",
      revision: "rev-1",
      reason: "اختبار",
      ...extra,
    };
    await stockOperations.transferPhase("branch", 9, phase, body);
    const [request] = bridge.finora.request.mock.calls[0] ?? [];
    expect(request).toMatchObject({ method: "POST", path: `${root}/9/${phase}`, body });
    expect(finoraRequestSchema.safeParse(request).success).toBe(true);
    expect(acknowledge).toHaveBeenCalledWith({
      key: body.operation_id,
      path: `${root}/9/${phase}`,
      scope: "scope",
    });
  },
);
