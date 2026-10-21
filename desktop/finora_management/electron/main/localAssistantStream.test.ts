import http from "node:http";
import type { AddressInfo } from "node:net";
import { chatLocalAssistant, warmLocalAssistant } from "./localAssistant";
import { DEFAULT_LOCAL_ASSISTANT } from "../../shared/localAssistant";

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
const readBody = (req: http.IncomingMessage) =>
  new Promise<Record<string, unknown>>((resolve) => {
    let body = "";
    req.on("data", (c) => (body += String(c)));
    req.on("end", () => resolve(body ? (JSON.parse(body) as Record<string, unknown>) : {}));
  });

it("streams Ollama NDJSON text as it arrives and keeps the model loaded", async () => {
  const bodies: Record<string, unknown>[] = [];
  let tags = 0;
  const fixture = await serve((req, res) => {
    if (req.url === "/api/tags") {
      tags++;
      res.end(JSON.stringify({ models: [{ name: "test-local" }] }));
      return;
    }
    void readBody(req).then((body) => {
      bodies.push(body);
      res.setHeader("Content-Type", "application/x-ndjson");
      // Split mid-line to prove partial chunks are reassembled.
      const lines = [
        { message: { role: "assistant", content: "مبيعات " } },
        { message: { role: "assistant", content: "اليوم" } },
        { message: { role: "assistant", content: "" }, done: true, prompt_eval_count: 40, eval_count: 2 },
      ]
        .map((l) => JSON.stringify(l))
        .join("\n");
      res.write(lines.slice(0, 20));
      setTimeout(() => res.end(lines.slice(20)), 10);
    });
  });
  try {
    const deltas: string[] = [];
    const reply = await chatLocalAssistant(
      fixture.settings,
      { messages: [{ role: "user", content: "شكد مبيعات اليوم؟" }] },
      "",
      undefined,
      (text) => deltas.push(text),
    );
    expect(deltas).toEqual(["مبيعات ", "اليوم"]);
    expect(reply.message.content).toBe("مبيعات اليوم");
    expect(reply.inputTokens).toBe(40);
    expect(bodies[0]).toMatchObject({ stream: true, keep_alive: "30m" });
    // The installed-model check is cached between tool rounds.
    await chatLocalAssistant(
      fixture.settings,
      { messages: [{ role: "user", content: "ثاني" }] },
      "",
      undefined,
      () => undefined,
    );
    expect(tags).toBe(1);
  } finally {
    await fixture.close();
  }
});

it("rebuilds LM Studio tool calls streamed in fragments", async () => {
  const fixture = await serve((req, res) => {
    void readBody(req).then(() => {
      res.setHeader("Content-Type", "text/event-stream");
      const events = [
        { choices: [{ delta: { role: "assistant" } }] },
        {
          choices: [
            {
              delta: {
                tool_calls: [{ index: 0, id: "lm-1", function: { name: "search_", arguments: '{"qu' } }],
              },
            },
          ],
        },
        {
          choices: [
            {
              delta: {
                tool_calls: [{ index: 0, function: { name: "products", arguments: 'ery":"شاشة"}' } }],
              },
            },
          ],
        },
        { choices: [], usage: { prompt_tokens: 90, completion_tokens: 7 } },
      ];
      res.end(`${events.map((e) => `data: ${JSON.stringify(e)}`).join("\n\n")}\n\ndata: [DONE]\n\n`);
    });
  });
  try {
    const reply = await chatLocalAssistant(
      { ...fixture.settings, provider: "lmstudio" },
      { messages: [{ role: "user", content: "ابحث عن شاشة" }] },
      "",
      undefined,
      () => undefined,
    );
    expect(reply.message.tool_calls).toEqual([
      { id: "lm-1", type: "function", function: { name: "search_products", arguments: '{"query":"شاشة"}' } },
    ]);
    expect(reply.outputTokens).toBe(7);
  } finally {
    await fixture.close();
  }
});

it("accepts an OpenAI-compatible server that ignores stream and replies in one body", async () => {
  const fixture = await serve((req, res) => {
    void readBody(req).then(() =>
      res.end(
        JSON.stringify({
          choices: [{ message: { role: "assistant", content: "جاهز محلياً" } }],
          usage: { prompt_tokens: 5, completion_tokens: 2 },
        }),
      ),
    );
  });
  try {
    const deltas: string[] = [];
    const reply = await chatLocalAssistant(
      { ...fixture.settings, provider: "lmstudio" },
      { messages: [{ role: "user", content: "x" }] },
      "",
      undefined,
      (text) => deltas.push(text),
    );
    expect(reply.message.content).toBe("جاهز محلياً");
    expect(deltas).toEqual(["جاهز محلياً"]);
    expect(reply.inputTokens).toBe(5);
  } finally {
    await fixture.close();
  }
});

it("reports a streaming HTTP error without leaking the provider body", async () => {
  const fixture = await serve((_req, res) => {
    res.writeHead(500);
    res.end("provider-secret-trace");
  });
  try {
    await expect(
      chatLocalAssistant(
        { ...fixture.settings, provider: "lmstudio" },
        { messages: [{ role: "user", content: "x" }] },
        "",
        undefined,
        () => undefined,
      ),
    ).rejects.toThrow(/500/);
  } finally {
    await fixture.close();
  }
});

it("warms Ollama by loading the model without generating", async () => {
  const bodies: Record<string, unknown>[] = [];
  const fixture = await serve((req, res) => {
    if (req.url === "/api/tags") {
      res.end(JSON.stringify({ models: [{ name: "test-local" }] }));
      return;
    }
    void readBody(req).then((body) => {
      bodies.push(body);
      res.end(JSON.stringify({ done: true }));
    });
  });
  try {
    await warmLocalAssistant({ ...fixture.settings, port: fixture.settings.port });
    expect(bodies).toEqual([{ model: "test-local", messages: [], keep_alive: "30m" }]);
    await warmLocalAssistant({ ...fixture.settings, enabled: false });
    expect(bodies).toHaveLength(1);
  } finally {
    await fixture.close();
  }
});
