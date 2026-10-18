import { describe, expect, it, vi } from "vitest";
import { agentStateSchema } from "../data/schemas";
import { canTransition, isBusy, ORB_VISUALS, statusLabel, transition } from "./orbMachine";
import { orbLayout } from "./layout";

const ALL = agentStateSchema.options;

describe("orb state machine", () => {
  it.each([
    ["idle", "message_received"],
    ["message_received", "reading"],
    ["reading", "thinking"],
    ["thinking", "executing"],
    ["executing", "completed"],
    ["completed", "idle"],
    ["approval_required", "executing"],
    ["searching", "approval_required"],
    ["error", "reading"],
  ] as const)("allows %s → %s", (from, to) => {
    expect(canTransition(from, to)).toBe(true);
  });

  it("allows any state → error / offline / idle", () => {
    for (const s of ALL) {
      expect(canTransition(s, "error")).toBe(true);
      expect(canTransition(s, "offline")).toBe(true);
      expect(canTransition(s, "idle")).toBe(true);
    }
  });

  it("rejects incoherent jumps and reports them", () => {
    const onRejected = vi.fn();
    expect(transition("idle", "completed", onRejected)).toBe("idle");
    expect(onRejected).toHaveBeenCalledWith("idle", "completed");
    expect(transition("offline", "replying", onRejected)).toBe("offline");
  });

  it("has visual parameters for every state", () => {
    for (const s of ALL) expect(ORB_VISUALS[s]).toBeDefined();
  });
});

describe("status labels", () => {
  it("never exposes empty text and names the channel", () => {
    for (const s of ALL) {
      expect(
        statusLabel(s, { channel: null, serverLabel: null, hasConversations: true }).length,
      ).toBeGreaterThan(0);
    }
    expect(statusLabel("reading", { channel: "instagram", serverLabel: null, hasConversations: true })).toBe(
      "يقرأ رسالة جديدة من Instagram",
    );
  });

  it("uses the first-message empty state", () => {
    expect(statusLabel("idle", { channel: null, serverLabel: null, hasConversations: false })).toBe(
      "بإنتظار أول رسالة",
    );
  });

  it("prefers the server execution label except when idle/offline", () => {
    const opts = { channel: null, serverLabel: "يجهز إعدادات العيادة", hasConversations: true };
    expect(statusLabel("executing", opts)).toBe("يجهز إعدادات العيادة");
    expect(statusLabel("idle", opts)).toBe("بإنتظار الرسائل الجديدة");
    expect(statusLabel("offline", opts)).toBe("غير متصل");
  });

  it("only work-in-progress states animate the ellipsis", () => {
    expect(isBusy("thinking")).toBe(true);
    expect(isBusy("completed")).toBe(false);
    expect(isBusy("approval_required")).toBe(false);
  });
});

describe("orb layout", () => {
  it("keeps the orb within 220–360px", () => {
    expect(orbLayout(1440, 832).diameter).toBeLessThanOrEqual(360);
    expect(orbLayout(2560, 1370).diameter).toBe(360);
    expect(orbLayout(1280, 640).diameter).toBeGreaterThanOrEqual(220);
    expect(orbLayout(1440, 832).offsetY).toBeGreaterThan(0);
  });

  it("moves the camera back when the stage is taller relative to the orb", () => {
    expect(orbLayout(2560, 1370).cameraZ).toBeGreaterThan(orbLayout(1280, 640).cameraZ);
  });
});
