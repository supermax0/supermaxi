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
it.each(["", "/1/commands", "/local/actions"])(
  "does not bypass failed encrypted storage for inventory audit writes (%s)",
  async (suffix) => {
    mocks.engine.mockRejectedValueOnce(Error("encryption unavailable"));
    expect(
      await sendFinoraRequest({
        method: "POST",
        path: `/api/v1/desktop/inventory-audits${suffix}`,
        body: {},
      }),
    ).toMatchObject({ ok: false, failure: "http", status: 503 });
    expect(mocks.network).not.toHaveBeenCalled();
  },
);
it("does not transmit a second audit settlement when checkpointing fails after server commit", async () => {
  const request: FinoraRequest = {
    method: "POST",
    path: "/api/v1/desktop/inventory-audits/1/commands",
    body: { action: "post" },
  };
  mocks.network.mockResolvedValueOnce({
    status: 200,
    location: null,
    contentType: "application/json",
    body: Buffer.from(JSON.stringify({ success: true, data: { session_id: 1 } })),
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
