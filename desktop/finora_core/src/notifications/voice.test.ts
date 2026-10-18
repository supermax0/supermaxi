import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { CoreEvent } from "../data/schemas";
import { useSound } from "./preferences";
import { NotificationVoice, noticeFor } from "./voice";

const tones = vi.fn();
class TestAudioContext {
  state = "running";
  currentTime = 0;
  destination = {};
  resume = async () => undefined;
  close = async () => undefined;
  createGain = () => ({
    connect: vi.fn(),
    disconnect: vi.fn(),
    gain: {
      setValueAtTime: vi.fn(),
      linearRampToValueAtTime: vi.fn(),
      exponentialRampToValueAtTime: vi.fn(),
    },
  });
  createOscillator = () => ({
    connect: vi.fn(),
    disconnect: vi.fn(),
    frequency: { setValueAtTime: vi.fn() },
    start: tones,
    stop: vi.fn(),
  });
}
const approval = (status = "pending") =>
  ({ type: "approval.required", approval: { id: "12", status } }) as CoreEvent;
function requiredNotice(event: CoreEvent) {
  const notice = noticeFor(event);
  if (!notice) throw new Error("Expected important alert");
  return notice;
}
let voice: NotificationVoice | undefined;
beforeEach(() => {
  tones.mockClear();
  useSound.setState({
    preferences: { enabled: true, mode: "chime", volume: 0.65, approvals: true, important: true },
    status: "locked",
  });
  vi.stubGlobal("AudioContext", TestAudioContext);
});
afterEach(() => {
  voice?.dispose();
  vi.unstubAllGlobals();
});

describe("important notification selection", () => {
  it("announces pending approvals and open owner reports, but skips resolved and ordinary events", () => {
    expect(noticeFor(approval())?.key).toBe("approval:12");
    expect(noticeFor(approval("executed"))).toBeNull();
    expect(noticeFor({ type: "support.issue", issue: { id: "8", status: "open" } } as CoreEvent)?.kind).toBe(
      "support",
    );
    expect(
      noticeFor({ type: "support.issue", issue: { id: "8", status: "resolved" } } as CoreEvent),
    ).toBeNull();
    expect(noticeFor({ type: "resync" })).toBeNull();
  });
  it("announces failed outbound delivery without reading customer messages aloud", () => {
    const event = {
      type: "message.updated",
      message: { id: "6", sender: "core", delivery: "failed", text: "private" },
    } as Extract<CoreEvent, { type: "message.updated" }>;
    expect(noticeFor(event)).toEqual({ kind: "delivery", ref: "6", key: "delivery:6" });
    expect(noticeFor({ ...event, message: { ...event.message, sender: "customer" } })).toBeNull();
  });
});
describe("notification playback controls", () => {
  it("deduplicates replayed events and honours muting and per-category choices", async () => {
    voice = new NotificationVoice(null);
    voice.unlock();
    await Promise.resolve();
    voice.enqueue(requiredNotice(approval()));
    voice.enqueue(requiredNotice(approval()));
    await Promise.resolve();
    expect(tones).toHaveBeenCalledTimes(1);
    useSound.getState().update({ approvals: false });
    voice.enqueue({ kind: "approval", ref: "13", key: "approval:13" });
    useSound.getState().update({ enabled: false });
    voice.preferencesChanged();
    voice.enqueue({ kind: "support", ref: "14", key: "support:14" });
    expect(tones).toHaveBeenCalledTimes(1);
  });
  it("waits for the first audio gesture, drops canceled backlog, and falls back truthfully when Live is unavailable", async () => {
    voice = new NotificationVoice(null);
    voice.enqueue(requiredNotice(approval()));
    expect(tones).not.toHaveBeenCalled();
    expect(useSound.getState().status).toBe("locked");
    useSound.getState().update({ enabled: false });
    voice.preferencesChanged();
    useSound.getState().update({ enabled: true, mode: "live" });
    voice.unlock();
    await Promise.resolve();
    expect(tones).not.toHaveBeenCalled();
    voice.enqueue({ kind: "test", key: "test:1" });
    await Promise.resolve();
    expect(useSound.getState().status).toBe("unavailable");
    expect(tones).toHaveBeenCalledTimes(1);
  });
});
