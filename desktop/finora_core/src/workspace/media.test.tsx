import { act, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { makeSource, renderWithSource } from "../test/render";
import type { Message } from "../data/schemas";
import { MediaComposer } from "./MediaComposer";
import { MediaMessage } from "./MediaMessage";

const message: Message = {
  id: "media-1",
  conversationId: "c6",
  sender: "human",
  authorName: "owner",
  text: "",
  at: "2026-10-04T10:00:00Z",
  delivery: "sent",
};
const revoke = vi.fn();
beforeEach(() => {
  vi.stubGlobal(
    "URL",
    Object.assign(URL, { createObjectURL: vi.fn(() => "blob:media-test"), revokeObjectURL: revoke }),
  );
  vi.spyOn(HTMLMediaElement.prototype, "pause").mockImplementation(() => {});
  revoke.mockClear();
});
afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("reviewed media composer", () => {
  it("previews without sending, reuses the key on a failed retry, and revokes the preview", async () => {
    const source = makeSource();
    const send = vi
      .spyOn(source, "sendMedia")
      .mockRejectedValueOnce(new Error("offline"))
      .mockResolvedValueOnce(message);
    renderWithSource(
      <MediaComposer conversationId="c6" textSending={false} onBusyChange={vi.fn()} />,
      source,
    );
    const file = new File(["image"], "screen.png", { type: "image/png" });
    fireEvent.change(screen.getByLabelText("اختيار صورة أو فيديو أو صوت"), { target: { files: [file] } });
    expect(await screen.findByAltText("الصورة المختارة")).toHaveAttribute("src", "blob:media-test");
    expect(send).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "إرسال المرفق" }));
    await waitFor(() => expect(send).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(screen.getByRole("button", { name: "إرسال المرفق" })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: "إرسال المرفق" }));
    await waitFor(() => expect(send).toHaveBeenCalledTimes(2));
    expect(send.mock.calls[1]?.[2]).toBe(send.mock.calls[0]?.[2]);
    expect(send.mock.calls[0]?.[1]).toBe(file);
    await waitFor(() => expect(screen.queryByAltText("الصورة المختارة")).not.toBeInTheDocument());
    expect(revoke).toHaveBeenCalledWith("blob:media-test");
  });

  it("cancels microphone capture and stops it when the conversation unmounts", async () => {
    const stopped = vi.fn();
    const stream = { getTracks: () => [{ stop: stopped }] };
    const capture = vi.fn().mockResolvedValue(stream);
    Object.defineProperty(navigator, "mediaDevices", {
      configurable: true,
      value: { getUserMedia: capture },
    });
    class Recorder {
      static isTypeSupported() {
        return true;
      }
      state = "inactive";
      onstop: (() => void) | null = null;
      ondataavailable: ((event: { data: Blob }) => void) | null = null;
      start() {
        this.state = "recording";
      }
      stop() {
        this.state = "inactive";
        this.ondataavailable?.({ data: new Blob(["voice"]) });
        this.onstop?.();
      }
    }
    vi.stubGlobal("MediaRecorder", Recorder);
    const source = makeSource();
    const send = vi.spyOn(source, "sendMedia");
    const { unmount } = renderWithSource(
      <MediaComposer conversationId="c6" textSending={false} onBusyChange={vi.fn()} />,
      source,
    );
    fireEvent.click(screen.getByRole("button", { name: "تسجيل فويز" }));
    expect(await screen.findByText("نسجل الفويز…")).toBeInTheDocument();
    expect(capture).toHaveBeenCalledWith(expect.objectContaining({ video: false }));
    fireEvent.click(screen.getByRole("button", { name: "إلغاء التسجيل" }));
    expect(stopped).toHaveBeenCalled();
    expect(screen.queryByLabelText("معاينة المرفق قبل الإرسال")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "تسجيل فويز" }));
    await screen.findByText("نسجل الفويز…");
    stopped.mockClear();
    unmount();
    expect(stopped).toHaveBeenCalled();
    expect(send).not.toHaveBeenCalled();
  });
});

describe("private message media", () => {
  it("loads through the authenticated source on demand and releases the blob on unmount", async () => {
    const source = makeSource();
    const load = vi
      .spyOn(source, "getAttachment")
      .mockResolvedValue(new Blob(["image"], { type: "image/jpeg" }));
    const { unmount } = renderWithSource(
      <MediaMessage
        conversationId="c6"
        messageId="media-1"
        item={{
          id: "0",
          kind: "image",
          name: "screen.jpg",
          mimeType: "image/jpeg",
          sizeBytes: 100,
          status: "stored",
        }}
      />,
      source,
    );
    expect(load).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "عرض الصورة" }));
    expect(await screen.findByAltText("screen.jpg")).toHaveAttribute("src", "blob:media-test");
    expect(load).toHaveBeenCalledWith("c6", "media-1", "0", expect.any(AbortSignal));
    await act(async () => unmount());
    expect(revoke).toHaveBeenCalledWith("blob:media-test");
  });
});
