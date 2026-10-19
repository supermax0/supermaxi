import { updateManifest, newerVersion } from "./updates";
vi.mock("electron", () => ({ app: {} }));
vi.mock("./config", () => ({ getServerUrl: vi.fn() }));
it("compares numeric versions and never downgrades", () => {
  expect(newerVersion("0.10.0", "0.9.9")).toBe(true);
  expect(newerVersion("0.8.0", "0.8.0")).toBe(false);
  expect(newerVersion("0.7.9", "0.8.0")).toBe(false);
});
it("rejects executable paths, unexpected filenames, invalid hashes and oversized installers", () => {
  const manifest = {
    version: "0.8.0",
    filename: "FINORA-Management-Setup-0.8.0-Windows-10-11-x64.exe",
    platform: "Windows",
    size_bytes: 120000000,
    sha256: "a".repeat(64),
  };
  expect(updateManifest.safeParse(manifest).success).toBe(true);
  for (const change of [
    { filename: "../../attack.exe" },
    { filename: "https://other.test/attack.exe" },
    { sha256: "invalid" },
    { size_bytes: 600 * 1024 * 1024 },
    { version: "../x" },
  ])
    expect(updateManifest.safeParse({ ...manifest, ...change }).success).toBe(false);
});
