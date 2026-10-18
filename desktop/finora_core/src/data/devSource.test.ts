import { afterEach, describe, expect, it } from "vitest";
import { DevDataSource } from "./devSource";
import {
  activityEventSchema,
  approvalSchema,
  conversationSchema,
  customerProfileSchema,
  messageSchema,
  systemStatusSchema,
} from "./schemas";
import { CoreError } from "./source";

const NOW = new Date("2026-10-03T19:44:00Z");
const all = { channel: "all", filter: "all", search: "" } as const;
let src: DevDataSource;
const make = () => (src = new DevDataSource({ simulate: false, now: NOW, latency: 0 }));

afterEach(() => src.dispose());

describe("development data source honours the wire contracts", () => {
  it("every payload parses with the Zod schemas", async () => {
    make();
    systemStatusSchema.parse(await src.getStatus());
    const convs = await src.listConversations(all);
    expect(convs.length).toBeGreaterThan(0);
    for (const c of convs) {
      conversationSchema.parse(c);
      (await src.listMessages(c.id)).forEach((m) => messageSchema.parse(m));
      customerProfileSchema.parse(await src.getCustomer(c.id));
    }
    (await src.listActivity("all")).forEach((e) => activityEventSchema.parse(e));
    (await src.listApprovals()).forEach((a) => approvalSchema.parse(a));
  });

  it("sorts by last meaningful activity and filters by channel and search", async () => {
    make();
    const convs = await src.listConversations(all);
    const sorted = [...convs].sort((a, b) => b.lastActivityAt.localeCompare(a.lastActivityAt));
    expect(convs.map((c) => c.id)).toEqual(sorted.map((c) => c.id));
    const fb = await src.listConversations({ ...all, channel: "facebook" });
    expect(fb.length).toBeGreaterThan(0);
    expect(fb.every((c) => c.channel === "facebook")).toBe(true);
    const msgHit = await src.listConversations({ ...all, search: "عيادة أسنان" });
    expect(msgHit.map((c) => c.id)).toContain("c1");
    expect(await src.listConversations({ ...all, search: "zzz-no-match" })).toHaveLength(0);
  });

  it("filters unread and human-controlled threads", async () => {
    make();
    expect((await src.listConversations({ ...all, filter: "unread" })).every((c) => c.unreadCount > 0)).toBe(
      true,
    );
    expect(
      (await src.listConversations({ ...all, filter: "human" })).every((c) => c.control === "human"),
    ).toBe(true);
  });

  it("unknown ids fail with a classified NOT_FOUND error", async () => {
    make();
    await expect(src.listMessages("nope")).rejects.toMatchObject({ code: "NOT_FOUND" });
  });
});

describe("human control", () => {
  it("refuses manual sends while FINORA CORE controls the thread", async () => {
    make();
    await expect(src.sendMessage("c1", "hi", "k1")).rejects.toMatchObject({
      code: "CONFLICT",
      retryable: false,
    });
  });

  it("takeover enables manual sends and the idempotency key prevents duplicates", async () => {
    make();
    const conv = await src.setControl("c1", "human");
    expect(conv.control).toBe("human");
    expect(conv.assignedTo).toBe("Super Admin");
    const a = await src.sendMessage("c1", "مرحبا", "same-key");
    const b = await src.sendMessage("c1", "مرحبا", "same-key");
    expect(a.id).toBe(b.id);
    const msgs = await src.listMessages("c1");
    expect(msgs.filter((m) => m.id === a.id)).toHaveLength(1);
    expect(msgs.some((m) => m.sender === "system")).toBe(true);
  });

  it("resume hands the thread back to FINORA CORE", async () => {
    make();
    await src.setControl("c6", "ai");
    expect((await src.listConversations(all)).find((c) => c.id === "c6")?.control).toBe("ai");
  });
});

describe("approvals and kill switch", () => {
  it("deciding an unknown approval fails", async () => {
    make();
    await expect(src.decideApproval("missing", "approved")).rejects.toBeInstanceOf(CoreError);
  });

  it("pausing all automation requires a reason and is audited", async () => {
    make();
    await expect(src.setAutomationPaused(true, "  ")).rejects.toMatchObject({ code: "VALIDATION_ERROR" });
    const s = await src.setAutomationPaused(true, "maintenance");
    expect(s.automationPaused).toBe(true);
    expect((await src.listActivity("ai"))[0]?.detail).toBe("maintenance");
  });
});
