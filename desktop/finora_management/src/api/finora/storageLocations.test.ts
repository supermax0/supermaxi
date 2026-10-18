import { vi } from "vitest";
import { installMockBridge, removeMockBridge } from "@/test/mockBridge";
import { storageLocations } from "./storageLocations";
import { stockOperations } from "./stockOperations";

afterEach(removeMockBridge);
const root = "/api/v1/desktop/stock-operations/storage";
const state = {
  product_id: 1,
  variant_name: "أسود · L",
  location_id: null,
  quantity: 6,
  available: 4,
  movable: 4,
  basis_valid: true,
  cost: null,
  revision: "revision",
};
const body = { operation_id: "0dd34551-6f1a-4500-8aef-21a7415ad7c3", branch_id: 2 };
const place = {
  id: 7,
  key: "storage:2:7",
  branch_id: 2,
  branch_name: "الفرع الرئيسي",
  code: "BACK",
  name: "المخزن الخلفي",
  kind: "storage",
  is_active: true,
  revision: "revision",
};
const success = {
  ok: true as const,
  status: 200,
  data: { success: true, data: { id: 7, type: "storage_location", location: place } },
  customerCommandScope: "scope",
};

it("reads the primary site and exact variant without a mutation or assumed cost", async () => {
  const bridge = installMockBridge(() => ({ ok: true, status: 200, data: { success: true, data: state } }));
  expect(await storageLocations.item(2, 1, state.variant_name, null)).toEqual(state);
  expect(bridge.finora.request).toHaveBeenCalledWith({
    method: "GET",
    path: `${root}/item`,
    query: { branch_id: 2, product_id: 1, variant_name: state.variant_name },
  });
});

it("rejects an unsafe cost rather than accepting a rounded inventory value", async () => {
  installMockBridge(() => ({
    ok: true,
    status: 200,
    data: { success: true, data: { ...state, cost: 9007199254740992 } },
  }));
  await expect(storageLocations.item(2, 1, "", 7)).rejects.toMatchObject({ kind: "invalid_response" });
});

it("refuses every mutation before sending when encrypted recovery is unavailable", async () => {
  const bridge = installMockBridge(() => success);
  await expect(storageLocations.createLocation(body)).rejects.toMatchObject({ kind: "refused" });
  expect(bridge.finora.request).not.toHaveBeenCalled();
});

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

it("acknowledges the original UUID and exact location path after validated success", async () => {
  const bridge = installMockBridge(() => success);
  const acknowledge = recovery();
  expect(await storageLocations.updateLocation(7, body)).toMatchObject({ id: 7 });
  expect(bridge.finora.request).toHaveBeenCalledWith({
    method: "POST",
    path: `${root}/locations/7`,
    body,
    timeoutMs: 30000,
  });
  expect(acknowledge).toHaveBeenCalledWith({
    key: body.operation_id,
    path: `${root}/locations/7`,
    scope: "scope",
  });
});

it("keeps an unacknowledged request visible if the main process scope is absent", async () => {
  installMockBridge(() => ({ ...success, customerCommandScope: undefined }));
  const acknowledge = recovery();
  await expect(storageLocations.createLocation(body)).rejects.toMatchObject({ kind: "invalid_response" });
  expect(acknowledge).not.toHaveBeenCalled();
});

it("does not acknowledge a malformed success payload", async () => {
  installMockBridge(() => ({
    ...success,
    data: { success: true, data: { id: 0, type: "storage_location" } },
  }));
  const acknowledge = recovery();
  await expect(storageLocations.createLocation(body)).rejects.toMatchObject({ kind: "invalid_response" });
  expect(acknowledge).not.toHaveBeenCalled();
});

it("the existing inventory recovery list can resolve a storage request without treating it as a branch transfer", async () => {
  installMockBridge(() => success);
  const acknowledge = recovery();
  const bridge = window.finoraDesktop?.stockRecovery;
  if (!bridge) throw Error("missing test recovery");
  bridge.retry = vi.fn(async () => ({
    request: { method: "POST" as const, path: `${root}/locations/7`, body },
    response: success,
  }));
  expect(await stockOperations.retry(body.operation_id)).toMatchObject({
    id: 7,
    type: "storage_location",
    location: place,
  });
  expect(acknowledge).toHaveBeenCalledWith({
    key: body.operation_id,
    path: `${root}/locations/7`,
    scope: "scope",
  });
});
