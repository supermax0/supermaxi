import { EventEmitter } from "node:events";
import type { BrowserWindow } from "electron";
import { protectWindow, mayLeave } from "./lifecycle";
const mocks = vi.hoisted(() => ({
  ask: vi.fn(),
  askSync: vi.fn(),
  flush: vi.fn(),
}));
vi.mock("electron", () => ({ dialog: { showMessageBox: mocks.ask, showMessageBoxSync: mocks.askSync } }));
vi.mock("./offlineRuntime", () => ({ flushOfflineWrites: mocks.flush }));
function windowFixture() {
  const win = Object.assign(new EventEmitter(), {
    isDestroyed: () => false,
    webContents: new EventEmitter(),
    close: vi.fn(),
    reload: vi.fn(),
  });
  return win;
}
beforeEach(() => {
  vi.clearAllMocks();
  mocks.flush.mockResolvedValue(undefined);
  mocks.ask.mockResolvedValue({ response: 1 });
  mocks.askSync.mockReturnValue(0);
});
it("never asks to discard an in-flight save", () => {
  const decide = vi.fn(() => true);
  expect(mayLeave({ dirty: true, saving: true }, decide)).toBe(false);
  expect(decide).not.toHaveBeenCalled();
});
it("protects native X/Alt+F4 and refuses to close with unsaved work", async () => {
  const win = windowFixture(),
    guard = protectWindow(win as unknown as BrowserWindow);
  guard.update({ dirty: true, saving: false });
  const event = { preventDefault: vi.fn() };
  win.emit("close", event);
  await vi.waitFor(() => expect(mocks.askSync).toHaveBeenCalled());
  expect(event.preventDefault).toHaveBeenCalled();
  expect(win.close).not.toHaveBeenCalled();
});
it("waits for durable writes before closing or starting an installer", async () => {
  const win = windowFixture(),
    guard = protectWindow(win as unknown as BrowserWindow),
    launch = vi.fn(async () => undefined);
  mocks.askSync.mockReturnValue(1);
  guard.update({ dirty: true, saving: false });
  expect(await guard.exit(launch)).toBe(true);
  expect(mocks.flush.mock.invocationCallOrder[0]).toBeLessThan(launch.mock.invocationCallOrder[0] ?? 0);
  expect(launch.mock.invocationCallOrder[0]).toBeLessThan(win.close.mock.invocationCallOrder[0] ?? 0);
});
it("keeps the app open if flushing or launching the installer fails", async () => {
  const win = windowFixture(),
    guard = protectWindow(win as unknown as BrowserWindow);
  mocks.flush.mockRejectedValue(Error("disk full"));
  expect(await guard.exit()).toBe(false);
  expect(win.close).not.toHaveBeenCalled();
  expect(mocks.ask).toHaveBeenCalled();
});
it("checks main-process saves before logout or restore", async () => {
  const win = windowFixture(),
    guard = protectWindow(win as unknown as BrowserWindow, () => true);
  expect(await guard.permit()).toBe(false);
  expect(mocks.askSync).not.toHaveBeenCalled();
  const other = protectWindow(windowFixture() as unknown as BrowserWindow);
  expect(await other.permit()).toBe(true);
});
