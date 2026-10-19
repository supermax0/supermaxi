import { act, render, screen, waitFor } from "@testing-library/react";
import { AuditCamera } from "./AuditCamera";
const mocks = vi.hoisted(() => ({ stop: vi.fn(), decode: vi.fn() }));
vi.mock("@zxing/browser", () => ({
  BrowserMultiFormatReader: class {
    decodeFromVideoElement = mocks.decode;
  },
}));
let track: { stop: ReturnType<typeof vi.fn> };
beforeEach(() => {
  vi.clearAllMocks();
  track = { stop: vi.fn() };
  vi.stubGlobal("isSecureContext", true);
  vi.stubGlobal("BarcodeDetector", undefined);
  Object.defineProperty(navigator, "mediaDevices", {
    configurable: true,
    value: { getUserMedia: vi.fn(async () => ({ getTracks: () => [track] })) },
  });
  vi.spyOn(HTMLMediaElement.prototype, "play").mockResolvedValue();
  mocks.decode.mockResolvedValue({ stop: mocks.stop });
});
afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});
it("decodes without native BarcodeDetector, suppresses continuous duplicates and releases the camera", async () => {
  const read = vi.fn();
  const rendered = render(<AuditCamera open onClose={() => undefined} onRead={read} caption="جاهز" />);
  await waitFor(() => expect(mocks.decode).toHaveBeenCalledTimes(1));
  const callback = mocks.decode.mock.calls[0]?.[1] as (result: { getText(): string }) => void;
  act(() => {
    callback({ getText: () => "6290000000011" });
    callback({ getText: () => "6290000000011" });
    callback({ getText: () => "6290000000028" });
  });
  expect(read.mock.calls).toEqual([["6290000000011"], ["6290000000028"]]);
  rendered.unmount();
  expect(track.stop).toHaveBeenCalled();
  expect(mocks.stop).toHaveBeenCalled();
});
it("handles a denied camera permission without starting a decoder", async () => {
  vi.mocked(navigator.mediaDevices.getUserMedia).mockRejectedValue(
    new DOMException("Denied", "NotAllowedError"),
  );
  render(<AuditCamera open onClose={() => undefined} onRead={() => undefined} caption="جاهز" />);
  expect(await screen.findByRole("alert")).toHaveTextContent("إذن الكاميرا مرفوض");
  expect(mocks.decode).not.toHaveBeenCalled();
});
