import http from "node:http";
import { randomBytes } from "node:crypto";
import { z } from "zod";
import {
  localAssistantSettingsSchema,
  localChatSchema,
  localMessageSchema,
  localProbeSchema,
  type LocalAssistantSettings,
  type LocalProbe,
  type LocalReply,
} from "../../shared/localAssistant";

const record = z.record(z.unknown());
export async function localJson(
  settings: LocalAssistantSettings,
  endpoint: string,
  body?: unknown,
  token = "",
  signal?: AbortSignal,
): Promise<unknown> {
  return localRequest(
    settings,
    endpoint,
    body === undefined ? undefined : Buffer.from(JSON.stringify(body)),
    "application/json",
    token,
    signal,
  );
}
export function localRequest(
  settings: LocalAssistantSettings,
  endpoint: string,
  body?: Buffer,
  contentType = "application/json",
  token = "",
  signal?: AbortSignal,
): Promise<unknown> {
  localAssistantSettingsSchema.parse(settings);
  if (!/^\/(?:api\/(?:tags|chat)|v1\/(?:models|chat\/completions)|inference)$/.test(endpoint))
    throw Error("مسار خدمة الذكاء غير مسموح");
  return new Promise((resolve, reject) => {
    let settled = false;
    const finish = (error?: Error, value?: unknown) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      signal?.removeEventListener("abort", abort);
      if (error) reject(error);
      else resolve(value);
    };
    const request = http.request(
      {
        hostname: settings.host,
        port: settings.port,
        path: endpoint,
        method: body ? "POST" : "GET",
        headers: {
          Accept: "application/json",
          ...(body ? { "Content-Type": contentType, "Content-Length": body.length } : {}),
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
      },
      (response) => {
        const chunks: Buffer[] = [];
        let size = 0;
        response.on("data", (chunk: Buffer) => {
          size += chunk.length;
          if (size > 4 * 1024 * 1024) {
            finish(Error("رد النموذج أكبر من الحد المسموح"));
            request.destroy();
          } else chunks.push(chunk);
        });
        response.on("error", () => finish(Error("انقطع اتصال خدمة الذكاء المحلية")));
        response.on("end", () => {
          if (settled) return;
          if (response.statusCode !== 200) {
            finish(
              Error(
                response.statusCode === 401 || response.statusCode === 403
                  ? "الخدمة المحلية تطلب رمز وصول. أضفه في إعدادات المساعد."
                  : `الخدمة المحلية أعادت خطأ ${response.statusCode ?? "غير معروف"}. تحقق من تحميل النموذج ودعم الأدوات والصور.`,
              ),
            );
            return;
          }
          try {
            finish(undefined, JSON.parse(Buffer.concat(chunks).toString("utf8")));
          } catch {
            finish(Error("الخدمة لم ترجع JSON صالحاً. تحقق من نوع الخدمة والمنفذ."));
          }
        });
      },
    );
    const abort = () => {
      finish(Error("تم إيقاف الإجابة"));
      request.destroy();
    };
    const timer = setTimeout(() => {
      finish(Error("انتهت مهلة النموذج المحلي. جرّب نموذجاً أخف أو زِد المهلة من الإعدادات."));
      request.destroy();
    }, settings.timeoutSeconds * 1000);
    request.on("error", () =>
      finish(Error("تعذر الاتصال بالخدمة المحلية. شغّل Ollama أو خادم LM Studio وافحص العنوان والمنفذ.")),
    );
    if (signal?.aborted) abort();
    else signal?.addEventListener("abort", abort, { once: true });
    if (!signal?.aborted) request.end(body);
  });
}
export async function probeLocalAssistant(
  input: unknown,
  savedToken = "",
  signal?: AbortSignal,
): Promise<LocalProbe> {
  const { settings, token } = localProbeSchema.parse(input);
  const result = record.parse(
    await localJson(
      { ...settings, timeoutSeconds: 30 },
      settings.provider === "ollama" ? "/api/tags" : "/v1/models",
      undefined,
      token ?? savedToken,
      signal,
    ),
  );
  const raw = settings.provider === "ollama" ? result.models : result.data;
  const models = z
    .array(record)
    .parse(raw)
    .filter((m) => !m.remote_host && !m.remote_model)
    .map((m) => m.name ?? m.id)
    .filter(
      (m): m is string => typeof m === "string" && m.length <= 200 && !/(?:[-:]cloud)(?:$|[-:])/i.test(m),
    );
  return {
    models: [...new Set(models)].slice(0, 100),
    host: settings.host,
    provider: settings.provider,
    hasToken: !!(token ?? savedToken),
  };
}
export async function chatLocalAssistant(
  settings: LocalAssistantSettings,
  input: unknown,
  token = "",
  signal?: AbortSignal,
): Promise<LocalReply> {
  const request = localChatSchema.parse(input);
  if (!settings.enabled || !settings.model) throw Error("فعّل المساعد واختر نموذجاً من الإعدادات أولاً");
  if (!settings.vision && request.messages.some((m) => m.images?.length))
    throw Error("فعّل دعم الصور واختر نموذج رؤية محلياً");
  const started = Date.now();
  if (settings.provider === "ollama") {
    const installed = await probeLocalAssistant({ settings }, token, signal);
    if (!installed.models.includes(settings.model))
      throw Error(
        "النموذج غير مثبت محلياً في Ollama أو يستخدم خدمة بعيدة. نزّل نموذجاً محلياً ثم اختره من فحص الاتصال.",
      );
  }
  const tools = settings.tools ? request.tools.map((tool) => ({ type: "function", function: tool })) : [];
  const callNames = new Map(
    request.messages.flatMap((m) => (m.tool_calls ?? []).map((c) => [c.id, c.function.name] as const)),
  );
  const messages = request.messages.map((m) =>
    settings.provider === "ollama"
      ? {
          role: m.role,
          content: m.content,
          ...(m.images ? { images: m.images } : {}),
          ...(m.tool_call_id ? { tool_name: callNames.get(m.tool_call_id) ?? m.tool_call_id } : {}),
          ...(m.tool_calls
            ? {
                tool_calls: m.tool_calls.map((c) => ({
                  function: { name: c.function.name, arguments: JSON.parse(c.function.arguments) },
                })),
              }
            : {}),
        }
      : {
          role: m.role,
          content: m.images?.length
            ? [
                { type: "text", text: m.content },
                ...m.images.map((image) => ({
                  type: "image_url",
                  image_url: { url: `data:image/jpeg;base64,${image}` },
                })),
              ]
            : m.content,
          ...(m.tool_call_id ? { tool_call_id: m.tool_call_id } : {}),
          ...(m.tool_calls ? { tool_calls: m.tool_calls } : {}),
        },
  );
  const payload = {
    model: settings.model,
    messages,
    stream: false,
    ...(tools.length ? { tools } : {}),
    ...(settings.provider === "ollama"
      ? { options: { temperature: 0.1, num_ctx: settings.contextTokens, num_predict: 1600 } }
      : { temperature: 0.1, max_tokens: 1600 }),
  };
  const data = record.parse(
    await localJson(
      settings,
      settings.provider === "ollama" ? "/api/chat" : "/v1/chat/completions",
      payload,
      token,
      signal,
    ),
  );
  const source = record.parse(
    settings.provider === "ollama"
      ? data.message
      : z
          .array(z.object({ message: record }))
          .min(1)
          .parse(data.choices)[0]?.message,
  );
  const calls =
    source.tool_calls == null
      ? []
      : z
          .array(
            z.object({
              id: z.string().optional(),
              function: z.object({ name: z.string(), arguments: z.union([z.string(), record]) }),
            }),
          )
          .max(6)
          .parse(source.tool_calls);
  const message = localMessageSchema.parse({
    role: "assistant",
    content: typeof source.content === "string" ? source.content : "",
    ...(calls.length
      ? {
          tool_calls: calls.map((c, index) => ({
            id: c.id ?? `local-${index}-${randomBytes(4).toString("hex")}`,
            type: "function",
            function: {
              name: c.function.name,
              arguments:
                typeof c.function.arguments === "string"
                  ? c.function.arguments
                  : JSON.stringify(c.function.arguments),
            },
          })),
        }
      : {}),
  });
  const usage = record.safeParse(data.usage).success ? record.parse(data.usage) : {};
  return {
    message,
    durationMs: Date.now() - started,
    inputTokens: z
      .number()
      .optional()
      .parse(data.prompt_eval_count ?? usage.prompt_tokens),
    outputTokens: z
      .number()
      .optional()
      .parse(data.eval_count ?? usage.completion_tokens),
  };
}

export async function transcribeLocal(
  settings: LocalAssistantSettings,
  input: { data: Uint8Array; type: "audio/wav" | "audio/webm" },
  token: string,
  signal?: AbortSignal,
): Promise<string> {
  if (!settings.enabled || !settings.speech) throw Error("فعّل خدمة التفريغ الصوتي المحلية من الإعدادات");
  const boundary = `finora-${randomBytes(12).toString("hex")}`;
  const extension = input.type === "audio/wav" ? "wav" : "webm";
  const body = Buffer.concat([
    Buffer.from(
      `--${boundary}\r\nContent-Disposition: form-data; name="file"; filename="recording.${extension}"\r\nContent-Type: ${input.type}\r\n\r\n`,
    ),
    Buffer.from(input.data),
    Buffer.from(
      `\r\n--${boundary}\r\nContent-Disposition: form-data; name="response_format"\r\n\r\njson\r\n--${boundary}\r\nContent-Disposition: form-data; name="language"\r\n\r\nar\r\n--${boundary}--\r\n`,
    ),
  ]);
  const result = z
    .object({ text: z.string().max(16000) })
    .parse(
      await localRequest(
        { ...settings, port: settings.speechPort },
        "/inference",
        body,
        `multipart/form-data; boundary=${boundary}`,
        "",
        signal,
      ),
    );
  return result.text.trim();
}
