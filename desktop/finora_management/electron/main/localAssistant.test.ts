import http from "node:http";
import type { AddressInfo } from "node:net";
import { chatLocalAssistant, localRequest, probeLocalAssistant, transcribeLocal } from "./localAssistant";
import {
  DEFAULT_LOCAL_ASSISTANT,
  localAssistantSettingsSchema,
  localChatSchema,
  localSaveSchema,
} from "../../shared/localAssistant";

async function serve(handler: http.RequestListener) {
  const server = http.createServer(handler);
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  return {
    settings: {
      ...DEFAULT_LOCAL_ASSISTANT,
      enabled: true,
      model: "test-local",
      port: (server.address() as AddressInfo).port,
    },
    close: () => new Promise<void>((resolve, reject) => server.close((e) => (e ? reject(e) : resolve()))),
  };
}
it("permits only canonical loopback/private IPv4 endpoints and bounded settings", () => {
  for (const host of ["127.0.0.1", "10.0.0.2", "192.168.1.4", "172.16.0.8"])
    expect(localAssistantSettingsSchema.safeParse({ host }).success).toBe(true);
  for (const host of [
    "localhost",
    "127.1",
    "127.0.0.01",
    "2130706433",
    "0x7f000001",
    "8.8.8.8",
    "169.254.169.254",
    "172.32.0.1",
    "https://127.0.0.1",
    "127.0.0.1/path",
  ])
    expect(localAssistantSettingsSchema.safeParse({ host }).success).toBe(false);
  expect(localAssistantSettingsSchema.safeParse({ model: "test:cloud" }).success).toBe(false);
  expect(
    localSaveSchema.safeParse({ settings: DEFAULT_LOCAL_ASSISTANT, token: "secret\r\nX: injected" }).success,
  ).toBe(false);
  expect(
    localChatSchema.safeParse({ messages: [{ role: "user", content: "x".repeat(50001) }] }).success,
  ).toBe(false);
});
it("uses the native Ollama protocol, filters remote models and matches tool result names", async () => {
  const bodies: Record<string, unknown>[] = [];
  const fixture = await serve((req, res) => {
    res.setHeader("Content-Type", "application/json");
    if (req.url === "/api/tags") {
      res.end(
        JSON.stringify({
          models: [
            { name: "test-local" },
            { name: "remote:cloud" },
            { name: "remote", remote_host: "https://cloud.test" },
          ],
        }),
      );
      return;
    }
    let body = "";
    req.on("data", (c) => (body += String(c)));
    req.on("end", () => {
      bodies.push(JSON.parse(body));
      res.end(
        JSON.stringify({
          message: {
            role: "assistant",
            content: "جاهز",
            tool_calls: [{ function: { name: "finora_help", arguments: { query: "منتج" } } }],
          },
          prompt_eval_count: 12,
          eval_count: 3,
        }),
      );
    });
  });
  try {
    expect((await probeLocalAssistant({ settings: fixture.settings })).models).toEqual(["test-local"]);
    const reply = await chatLocalAssistant(fixture.settings, {
      messages: [
        { role: "user", content: "اشرح" },
        {
          role: "assistant",
          content: "",
          tool_calls: [
            {
              id: "call-1",
              type: "function",
              function: { name: "finora_help", arguments: '{"query":"منتج"}' },
            },
          ],
        },
        { role: "tool", tool_call_id: "call-1", content: '{"ok":true}' },
      ],
    });
    expect(reply.message.tool_calls?.[0]?.function.arguments).toBe('{"query":"منتج"}');
    expect(reply.inputTokens).toBe(12);
    expect(bodies[0]).toMatchObject({ stream: false, options: { num_ctx: 8192 } });
    expect((bodies[0]?.messages as Record<string, unknown>[])[2]).toMatchObject({ tool_name: "finora_help" });
  } finally {
    await fixture.close();
  }
});
it("uses LM Studio tool IDs, vision format and optional bearer token", async () => {
  let payload: Record<string, unknown> = {};
  let authorization: string | undefined;
  const fixture = await serve((req, res) => {
    authorization = req.headers.authorization;
    let body = "";
    req.on("data", (c) => (body += String(c)));
    req.on("end", () => {
      payload = JSON.parse(body);
      res.end(
        JSON.stringify({
          choices: [
            {
              message: {
                role: "assistant",
                content: null,
                tool_calls: [
                  { id: "lm-1", function: { name: "search_products", arguments: '{"query":"شاشة"}' } },
                ],
              },
            },
          ],
          usage: { prompt_tokens: 100, completion_tokens: 8 },
        }),
      );
    });
  });
  try {
    const reply = await chatLocalAssistant(
      { ...fixture.settings, provider: "lmstudio", vision: true },
      { messages: [{ role: "user", content: "صورة", images: ["aGVsbG8="] }] },
      "local-secret",
    );
    expect(authorization).toBe("Bearer local-secret");
    expect(reply.message.tool_calls?.[0]?.id).toBe("lm-1");
    expect(payload).toMatchObject({
      stream: false,
      max_tokens: 1600,
      messages: [
        {
          content: [
            { type: "text" },
            { type: "image_url", image_url: { url: "data:image/jpeg;base64,aGVsbG8=" } },
          ],
        },
      ],
    });
  } finally {
    await fixture.close();
  }
});
it("does not follow redirects, execute arbitrary paths, expose response secrets or accept unbounded output", async () => {
  const fixture = await serve((_req, res) => {
    res.writeHead(302, { Location: "https://external.invalid/private" });
    res.end("private-provider-secret");
  });
  try {
    await expect(localRequest(fixture.settings, "/api/chat")).rejects.toThrow("302");
    expect(() => localRequest(fixture.settings, "/load")).toThrow();
  } finally {
    await fixture.close();
  }
  const oversized = await serve((_req, res) => res.end("x".repeat(4 * 1024 * 1024 + 1)));
  try {
    await expect(localRequest(oversized.settings, "/api/tags")).rejects.toThrow("أكبر");
  } finally {
    await oversized.close();
  }
});
it("cancels a pending local inference request", async () => {
  const fixture = await serve(() => undefined);
  const controller = new AbortController();
  try {
    const pending = chatLocalAssistant(
      fixture.settings,
      { messages: [{ role: "user", content: "test" }] },
      "",
      controller.signal,
    );
    controller.abort();
    await expect(pending).rejects.toThrow("إيقاف");
  } finally {
    await fixture.close();
  }
});
it("posts local mono WAV transcription without forwarding the model token to the speech service", async () => {
  let body = "",
    authorization: string | undefined;
  const fixture = await serve((req, res) => {
    authorization = req.headers.authorization;
    req.on("data", (c) => (body += String(c)));
    req.on("end", () => res.end(JSON.stringify({ text: "  أضف منتجاً  " })));
  });
  try {
    expect(
      await transcribeLocal(
        { ...fixture.settings, speech: true, speechPort: fixture.settings.port },
        { data: new Uint8Array([82, 73, 70, 70]), type: "audio/wav" },
        "model-token",
      ),
    ).toBe("أضف منتجاً");
    expect(authorization).toBeUndefined();
    expect(body).toContain('name="language"\r\n\r\nar');
    expect(body).toContain('filename="recording.wav"');
  } finally {
    await fixture.close();
  }
});
