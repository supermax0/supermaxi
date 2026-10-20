import { promises as fs } from "node:fs";
import os from "node:os";
import path from "node:path";
import { vi } from "vitest";
import { DEFAULT_LOCAL_ASSISTANT } from "../../shared/localAssistant";
const fixture = vi.hoisted(() => ({
  directory: "",
  encryption: true,
  session: {
    tenant: { id: 1, slug: "one" },
    user: { id: 7 },
    branch: { id: 1 },
    branch_scope: "branch",
    permissions: ["view_pos", "manage_customers"],
  },
}));
vi.mock("electron", () => ({
  app: { getPath: () => fixture.directory },
  safeStorage: {
    isEncryptionAvailable: () => fixture.encryption,
    encryptString: (text: string) => Buffer.from(`sealed:${Buffer.from(text).toString("base64")}`),
    decryptString: (buffer: Buffer) =>
      Buffer.from(buffer.toString().replace(/^sealed:/, ""), "base64").toString(),
  },
}));
vi.mock("./offlineDatabase", () => ({
  atomicWrite: async (file: string, data: Buffer) => {
    await fs.writeFile(file, data);
  },
}));
vi.mock("./config", () => ({ getServerUrl: async () => "https://finora.test" }));
vi.mock("./finoraHttp", () => ({
  sendFinoraNetworkRequest: vi.fn(async () => ({ ok: true, data: { session: fixture.session } })),
}));
import {
  assistantHistoryScope,
  assistantPublicSettings,
  assistantToken,
  configureAssistant,
  loadAssistantHistory,
  saveAssistantHistory,
} from "./localAssistantRuntime";
beforeEach(async () => {
  fixture.directory = await fs.mkdtemp(path.join(os.tmpdir(), "finora-ai-vault-"));
  fixture.encryption = true;
  fixture.session.branch.id = 1;
});
afterEach(async () => {
  if (
    path.dirname(fixture.directory) !== os.tmpdir() ||
    !path.basename(fixture.directory).startsWith("finora-ai-vault-")
  )
    throw Error("Unsafe cleanup");
  await fs.rm(fixture.directory, { recursive: true, force: true });
});
it("defaults to no history and never returns a plaintext token", async () => {
  expect((await assistantPublicSettings()).settings.remember).toBe(false);
  await configureAssistant({ settings: DEFAULT_LOCAL_ASSISTANT, token: "local-private-key" });
  expect(await assistantToken(DEFAULT_LOCAL_ASSISTANT)).toBe("local-private-key");
  expect(await assistantPublicSettings()).toEqual({ settings: DEFAULT_LOCAL_ASSISTANT, hasToken: true });
  const files = await fs.readdir(fixture.directory);
  for (const file of files)
    expect(await fs.readFile(path.join(fixture.directory, file), "utf8")).not.toContain("local-private-key");
  expect(await assistantToken({ ...DEFAULT_LOCAL_ASSISTANT, port: 1234 })).toBe("");
});
it("isolates encrypted history by authoritative tenant, user, permissions and branch", async () => {
  await configureAssistant({ settings: { ...DEFAULT_LOCAL_ASSISTANT, remember: true } });
  const scope = await assistantHistoryScope(),
    rows = [{ role: "user" as const, text: "private financial question", at: 1 }];
  await saveAssistantHistory({ expectedScope: scope, rows });
  expect((await loadAssistantHistory()).rows).toEqual(rows);
  const content = await fs.readFile(path.join(fixture.directory, `assistant-history-${scope}.bin`), "utf8");
  expect(content).not.toContain(rows[0]?.text);
  fixture.session.branch.id = 2;
  expect((await loadAssistantHistory()).rows).toEqual([]);
  await expect(saveAssistantHistory({ expectedScope: scope, rows })).rejects.toThrow("تغير");
  fixture.session.branch.id = 1;
  await saveAssistantHistory({ expectedScope: scope, rows: [] });
  expect((await loadAssistantHistory()).rows).toEqual([]);
});
it("fails closed when Windows encryption is unavailable and never falls back to plaintext", async () => {
  fixture.encryption = false;
  await expect(
    configureAssistant({ settings: DEFAULT_LOCAL_ASSISTANT, token: "private-key" }),
  ).rejects.toThrow("التشفير");
  expect(await fs.readdir(fixture.directory)).toEqual([]);
});
it("does not save chat when remembering is disabled", async () => {
  const scope = await assistantHistoryScope();
  await saveAssistantHistory({ expectedScope: scope, rows: [{ role: "user", text: "private", at: 1 }] });
  expect(await fs.readdir(fixture.directory)).toEqual([]);
});
