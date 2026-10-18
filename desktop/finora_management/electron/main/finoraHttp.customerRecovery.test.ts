import type { FinoraRequest, FinoraResponse } from "../../shared/ipc";
const mocks = vi.hoisted(() => ({ engine: vi.fn(), record: vi.fn(), network: vi.fn() }));
vi.mock("electron", () => ({ app: { getVersion: () => "0.4.0" }, session: { fromPartition: vi.fn() } }));
vi.mock("./offlineRuntime", () => ({
  getOfflineEngine: mocks.engine,
  recordOfflineIssue: mocks.record,
  deactivateOffline: vi.fn(),
  enableOfflineAccess: vi.fn(),
}));
vi.mock("./config", () => ({ getServerUrl: async () => "https://finora.test" }));
vi.mock("./netRequest", () => ({ netRequest: mocks.network, NetTimeoutError: class extends Error {} }));
import { sendFinoraRequest } from "./finoraHttp";

beforeEach(() => vi.clearAllMocks());
it.each(["commands", "1/debts", "1/invoices/2/schedule", "1/plans/3/repartition", "1/plans/3/schedule"])(
  "never bypasses a failed encrypted store to transmit a customer command (%s)",
  async (suffix) => {
    mocks.engine.mockRejectedValueOnce(Error("encryption unavailable"));
    const request: FinoraRequest = { method: "POST", path: `/api/v1/desktop/customers/${suffix}`, body: {} };
    expect(await sendFinoraRequest(request)).toMatchObject({ ok: false, failure: "http", status: 503 });
    expect(mocks.network).not.toHaveBeenCalled();
    expect(mocks.record).toHaveBeenCalledOnce();
  },
);
it("does not transmit again or treat an uncheckpointed response as acknowledged after the server committed", async () => {
  const request: FinoraRequest = { method: "POST", path: "/api/v1/desktop/customers/1/debts", body: {} };
  mocks.network.mockResolvedValueOnce({
    status: 200,
    location: null,
    contentType: "application/json",
    body: Buffer.from(JSON.stringify({ success: true, data: { id: 8 } })),
  });
  mocks.engine.mockResolvedValueOnce({
    serverUrl: "https://finora.test",
    request: async (r: FinoraRequest, sender: (r: FinoraRequest) => Promise<FinoraResponse>) => {
      await sender(r);
      throw Error("checkpoint failed after response");
    },
  });
  expect(await sendFinoraRequest(request)).toMatchObject({ ok: false, failure: "http", status: 503 });
  expect(mocks.network).toHaveBeenCalledOnce();
});
