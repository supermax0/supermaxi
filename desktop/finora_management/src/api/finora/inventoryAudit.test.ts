import { installMockBridge, removeMockBridge } from "@/test/mockBridge";
import { finora } from "./index";
import { onTransportOutcome } from "./transportEvents";

afterEach(removeMockBridge);
it("reading the local inventory journal does not announce server recovery or cancel offline query updates", async () => {
  installMockBridge(() => ({
    ok: true,
    status: 200,
    data: { success: true, data: { available: true, offline: true, prepared_records: 2, items: [] } },
  }));
  const seen: Array<string | null> = [];
  const stop = onTransportOutcome((error) => seen.push(error?.kind ?? null));
  try {
    expect((await finora.inventoryAudit.localStatus()).offline).toBe(true);
    expect(seen).toEqual([]);
  } finally {
    stop();
  }
});
it("a local journal's expired actor still reports session expiry", async () => {
  installMockBridge(() => ({ ok: false, failure: "unauthenticated" }));
  const seen: Array<string | null> = [];
  const stop = onTransportOutcome((error) => seen.push(error?.kind ?? null));
  try {
    await expect(finora.inventoryAudit.localStatus()).rejects.toMatchObject({ kind: "unauthenticated" });
    expect(seen).toEqual(["unauthenticated"]);
  } finally {
    stop();
  }
});
