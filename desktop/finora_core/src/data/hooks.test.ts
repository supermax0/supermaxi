import { QueryClient } from "@tanstack/react-query";
import { describe, expect, it, vi } from "vitest";
import { keys, upsertMessage } from "./hooks";
import type { Message } from "./schemas";

const msg: Message = {
  id: "9",
  conversationId: "2",
  sender: "customer",
  authorName: null,
  text: "live",
  at: "2026-10-03T19:44:00Z",
  delivery: null,
};

describe("realtime message upsert", () => {
  it("appends to a loaded list without refetching", () => {
    const qc = new QueryClient();
    qc.setQueryData(keys.messages("2"), [{ ...msg, id: "1", text: "old" }]);
    const spy = vi.spyOn(qc, "invalidateQueries");
    upsertMessage(qc, msg);
    expect(qc.getQueryData<Message[]>(keys.messages("2"))?.map((m) => m.text)).toEqual(["old", "live"]);
    expect(spy).not.toHaveBeenCalled();
  });

  it("refetches instead of dropping an event that races an in-flight load", async () => {
    const qc = new QueryClient();
    let calls = 0;
    let release: (v: Message[]) => void = () => undefined;
    const pending = qc.fetchQuery({
      queryKey: keys.messages("2"),
      queryFn: () => {
        calls += 1;
        return calls === 1 ? new Promise<Message[]>((r) => (release = r)) : Promise.resolve([msg]);
      },
    });
    upsertMessage(qc, msg); // arrives while the first load (which predates it) is still running
    release([]);
    await pending.catch(() => undefined);
    await vi.waitFor(() => expect(qc.getQueryData<Message[]>(keys.messages("2"))).toEqual([msg]));
    expect(calls).toBe(2);
  });
});
