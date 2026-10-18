import { afterEach, describe, expect, it, vi } from "vitest";
import { HttpDataSource, normalizeServerUrl, type AuthSession } from "./http";
import type { CoreEvent } from "./schemas";

const BASE = "https://finora.test";
const session: AuthSession = {
  accessToken: "a1",
  refreshToken: "r1",
  operator: { id: 1, username: "owner", role: "super_admin", permissions: ["conversations.view"] },
};

const json = (status: number, body: unknown) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

const status = {
  environment: "production",
  channels: { instagram: "connected", facebook: "disconnected" },
  automationPaused: false,
  agent: { state: "idle", label: null, conversationId: null, channel: null },
  conversationCount: 3,
  houseConfigured: true,
  devLoopback: false,
};

afterEach(() => vi.unstubAllGlobals());

describe("server URL", () => {
  it("requires https except for local development servers", () => {
    expect(normalizeServerUrl("https://finora.company/path")).toBe("https://www.finora.company");
    expect(normalizeServerUrl("https://www.finora.company")).toBe("https://www.finora.company");
    expect(normalizeServerUrl("http://localhost:5008")).toBe("http://localhost:5008");
    expect(normalizeServerUrl("http://finora.company")).toBeNull();
    expect(normalizeServerUrl("not a url")).toBeNull();
  });
});

describe("HttpDataSource", () => {
  it("uploads multipart without a JSON content type and fetches private bytes after token refresh", async () => {
    const outbound = {
      id: "media-1",
      conversationId: "c6",
      sender: "human",
      authorName: "owner",
      text: "",
      at: "2026-10-04T10:00:00Z",
      delivery: "sent",
    };
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(json(201, { message: outbound }))
      .mockResolvedValueOnce(json(401, { error: { code: "AUTH_ERROR", message: "expired" } }))
      .mockResolvedValueOnce(
        json(200, { accessToken: "a2", refreshToken: "r2", expiresIn: 900, operator: session.operator }),
      )
      .mockResolvedValueOnce(
        new Response("image", { status: 200, headers: { "Content-Type": "image/jpeg" } }),
      );
    vi.stubGlobal("fetch", fetchMock);
    const src = new HttpDataSource(BASE, session, vi.fn());
    const file = new File(["image"], "screen.png", { type: "image/png" });
    await src.sendMedia("c6", file, "stable-media-key");
    const upload = fetchMock.mock.calls[0]?.[1] as RequestInit;
    expect(upload.body).toBeInstanceOf(FormData);
    expect((upload.body as FormData).get("file")).toBeInstanceOf(File);
    expect(upload.headers).toMatchObject({
      Authorization: "Bearer a1",
      "Idempotency-Key": "stable-media-key",
    });
    expect(upload.headers).not.toHaveProperty("Content-Type");
    const blob = await src.getAttachment("c6", "media-1", "0");
    expect(blob.size).toBe(5);
    expect(fetchMock.mock.calls[3]?.[1]?.headers).toMatchObject({ Authorization: "Bearer a2" });
    expect(fetchMock.mock.calls[3]?.[0]).toBe(
      `${BASE}/api/v1/finora-core/conversations/c6/messages/media-1/attachments/0`,
    );
  });
  it("sends the bearer token and validates the response contract", async () => {
    const fetchMock = vi.fn().mockResolvedValue(json(200, status));
    vi.stubGlobal("fetch", fetchMock);
    const src = new HttpDataSource(BASE, session, vi.fn());
    const s = await src.getStatus();
    expect(s.channels.facebook).toBe("disconnected");
    expect(s.channels.telegram).toBe("disconnected"); // compatible with older servers lacking this channel
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe(`${BASE}/api/v1/finora-core/status`);
    expect((init.headers as Record<string, string>).Authorization).toBe("Bearer a1");
  });

  it("refreshes once on 401 for concurrent requests and retries", async () => {
    let refreshCalls = 0;
    const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
      if (url.endsWith("/auth/refresh")) {
        refreshCalls += 1;
        return json(200, {
          accessToken: "a2",
          refreshToken: "r2",
          expiresIn: 900,
          operator: session.operator,
        });
      }
      const auth = (init?.headers as Record<string, string>).Authorization;
      return auth === "Bearer a2"
        ? json(200, status)
        : json(401, { error: { code: "AUTH_ERROR", message: "x" } });
    });
    vi.stubGlobal("fetch", fetchMock);
    const onSession = vi.fn();
    const src = new HttpDataSource(BASE, session, onSession);
    await Promise.all([src.getStatus(), src.getStatus(), src.getStatus()]);
    expect(refreshCalls).toBe(1);
    expect(onSession).toHaveBeenCalledWith(
      expect.objectContaining({ accessToken: "a2", refreshToken: "r2" }),
    );
  });

  it("signs out when the refresh token is rejected", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(json(401, { error: { code: "AUTH_ERROR", message: "انتهت الجلسة" } })),
    );
    const onSession = vi.fn();
    const src = new HttpDataSource(BASE, session, onSession);
    await expect(src.getStatus()).rejects.toMatchObject({ code: "AUTH_ERROR" });
    expect(onSession).toHaveBeenCalledWith(null);
  });

  it("waits for rotated credentials to be persisted before retrying a request", async () => {
    let release!: () => void;
    const persisted = new Promise<void>((resolve) => {
      release = resolve;
    });
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(json(401, { error: { code: "AUTH_ERROR", message: "expired" } }))
      .mockResolvedValueOnce(
        json(200, { accessToken: "a2", refreshToken: "r2", expiresIn: 900, operator: session.operator }),
      )
      .mockResolvedValueOnce(json(200, status));
    vi.stubGlobal("fetch", fetchMock);
    const onSession = vi.fn(() => persisted);
    const src = new HttpDataSource(BASE, session, onSession);
    const pending = src.getStatus();
    await vi.waitFor(() => expect(onSession).toHaveBeenCalled());
    expect(fetchMock).toHaveBeenCalledTimes(2);
    release();
    await pending;
    expect(fetchMock).toHaveBeenCalledTimes(3);
  });

  it("preserves login on temporary refresh network failure", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValueOnce(json(401, { error: { code: "AUTH_ERROR", message: "expired" } }))
        .mockRejectedValueOnce(new TypeError("offline")),
    );
    const onSession = vi.fn();
    const src = new HttpDataSource(BASE, session, onSession);
    await expect(src.getStatus()).rejects.toThrow("offline");
    expect(onSession).not.toHaveBeenCalled();
  });

  it("clears saved credentials even if the logout server request fails", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("offline")));
    const onSession = vi.fn().mockResolvedValue(undefined);
    const src = new HttpDataSource(BASE, session, onSession);
    await expect(src.logout()).rejects.toMatchObject({ code: "NETWORK_ERROR" });
    expect(onSession).toHaveBeenCalledWith(null);
  });

  it("maps classified server errors and network failures", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValueOnce(
          json(409, { error: { code: "CONFLICT", message: "استلم المحادثة أولاً", retryable: false } }),
        )
        .mockRejectedValueOnce(new TypeError("Failed to fetch")),
    );
    const src = new HttpDataSource(BASE, session, vi.fn());
    await expect(src.sendMessage("1", "x", "k")).rejects.toMatchObject({
      code: "CONFLICT",
      message: "استلم المحادثة أولاً",
      retryable: false,
    });
    await expect(src.getStatus()).rejects.toMatchObject({ code: "NETWORK_ERROR", retryable: true });
  });

  it("rejects payloads that violate the contract instead of rendering them", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(json(200, { items: [{ id: 1 }] })));
    const src = new HttpDataSource(BASE, session, vi.fn());
    await expect(src.listConversations({ channel: "all", filter: "all", search: "" })).rejects.toMatchObject({
      code: "UNKNOWN_ERROR",
    });
  });

  it("sends the idempotency key with manual messages", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      json(201, {
        message: {
          id: "9",
          conversationId: "1",
          sender: "human",
          authorName: "فريق FINORA",
          text: "hi",
          at: "2026-10-03T19:44:00Z",
          delivery: "sent",
        },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const src = new HttpDataSource(BASE, session, vi.fn());
    await src.sendMessage("1", "hi", "key-1");
    const init = fetchMock.mock.calls[0]?.[1] as RequestInit;
    expect((init.headers as Record<string, string>)["Idempotency-Key"]).toBe("key-1");
  });

  it("parses the SSE stream into typed events and remembers the last id", async () => {
    const chunks = [
      ": connected 0\n\nid: 5\nevent: agent.status\ndata: ",
      '{"status":{"state":"thinking","label":null,"conversationId":"3","channel":"instagram"}}\n\n',
      'id: 6\nevent: bogus.type\ndata: {"x":1}\n\n',
    ];
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        const enc = new TextEncoder();
        chunks.forEach((c) => controller.enqueue(enc.encode(c)));
        controller.close();
      },
    });
    let calls = 0;
    const fetchMock = vi.fn<(url: string, init?: RequestInit) => Promise<Response>>(async () => {
      calls += 1;
      if (calls === 1) return new Response(body, { status: 200 });
      if (calls === 2) return new Response(new ReadableStream({ start: (c) => c.close() }), { status: 200 });
      return new Promise<Response>(() => undefined); // hold the next reconnect open
    });
    vi.stubGlobal("fetch", fetchMock);
    vi.spyOn(console, "warn").mockImplementation(() => undefined);
    const src = new HttpDataSource(BASE, session, vi.fn());
    const events: CoreEvent[] = [];
    const off = src.subscribe((e) => events.push(e));
    await vi.waitFor(() => expect(calls).toBe(3));
    off();
    const resumeHeaders = fetchMock.mock.calls[1]?.[1]?.headers as Record<string, string>;
    expect(resumeHeaders["Last-Event-ID"]).toBe("6");
    expect(events[0]).toEqual({ type: "resync" }); // every connect starts with a resync (closes the load→connect gap)
    expect(events[1]).toEqual({
      type: "agent.status",
      status: { state: "thinking", label: null, conversationId: "3", channel: "instagram" },
    });
    expect(events.some((e) => e.type === "resync")).toBe(true); // reconnect asks the UI to resync
    expect(events.find((e) => (e.type as string) === "bogus.type")).toBeUndefined();
  });
});
