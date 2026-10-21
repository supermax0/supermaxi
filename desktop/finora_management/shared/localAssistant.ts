import { z } from "zod";

export const localHostSchema = z
  .string()
  .trim()
  .refine((host) => {
    const parts = host.split(".");
    if (
      parts.length !== 4 ||
      parts.some((v) => !/^\d{1,3}$/.test(v) || Number(v) > 255 || String(Number(v)) !== v)
    )
      return false;
    const [a, b] = parts.map(Number);
    return (
      host === "127.0.0.1" ||
      a === 10 ||
      (a === 172 && b !== undefined && b >= 16 && b <= 31) ||
      (a === 192 && b === 168)
    );
  }, "استخدم 127.0.0.1 أو عنوان IPv4 داخل الشبكة المحلية");
export const localAssistantSettingsSchema = z
  .object({
    enabled: z.boolean().default(false),
    provider: z.enum(["ollama", "lmstudio"]).default("ollama"),
    host: localHostSchema.default("127.0.0.1"),
    port: z.number().int().min(1024).max(65535).default(11434),
    model: z
      .string()
      .trim()
      .max(200)
      .refine((v) => !/(?:[-:]cloud)(?:$|[-:])/i.test(v), "اختر نموذجاً محلياً")
      .default(""),
    contextTokens: z.number().int().min(2048).max(32768).default(8192),
    timeoutSeconds: z.number().int().min(30).max(300).default(120),
    maxRounds: z.number().int().min(1).max(8).default(4),
    tools: z.boolean().default(true),
    vision: z.boolean().default(false),
    remember: z.boolean().default(false),
    instructions: z.string().trim().max(6000).default(""),
    speech: z.boolean().default(false),
    speechPort: z.number().int().min(1024).max(65535).default(8080),
    /** Ask FINORA's server assistant when the local model is off or unreachable. */
    serverFallback: z.boolean().default(false),
  })
  .strict();
export type LocalAssistantSettings = z.infer<typeof localAssistantSettingsSchema>;
export const DEFAULT_LOCAL_ASSISTANT = localAssistantSettingsSchema.parse({});
export const localToolSchema = z
  .object({
    name: z.string().regex(/^[a-z][a-z0-9_]{0,79}$/),
    description: z.string().max(2500),
    parameters: z.record(z.unknown()),
  })
  .strict();
export const localMessageSchema = z
  .object({
    role: z.enum(["system", "user", "assistant", "tool"]),
    content: z.string().max(50000),
    tool_call_id: z.string().max(150).optional(),
    images: z
      .array(
        z
          .string()
          .max(3_000_000)
          .regex(/^[A-Za-z0-9+/=]+$/),
      )
      .max(1)
      .optional(),
    tool_calls: z
      .array(
        z.object({
          id: z.string().max(150),
          type: z.literal("function"),
          function: z.object({ name: z.string().max(80), arguments: z.string().max(12000) }),
        }),
      )
      .max(6)
      .optional(),
  })
  .strict();
export type LocalMessage = z.infer<typeof localMessageSchema>;
export type LocalTool = z.infer<typeof localToolSchema>;
export const localChatSchema = z
  .object({
    messages: z.array(localMessageSchema).min(1).max(48),
    tools: z.array(localToolSchema).max(16).default([]),
  })
  .strict()
  .refine((v) => JSON.stringify(v).length <= 4_000_000, "المحادثة أكبر من الحد المسموح");
export const localProbeSchema = z
  .object({
    settings: localAssistantSettingsSchema,
    token: z
      .string()
      .max(512)
      .regex(/^[\x21-\x7e]*$/)
      .optional(),
  })
  .strict();
export const localSaveSchema = localProbeSchema.extend({ clearToken: z.boolean().optional() });
export type LocalReply = {
  message: LocalMessage;
  inputTokens?: number;
  outputTokens?: number;
  durationMs: number;
};
export type LocalProbe = {
  models: string[];
  host: string;
  provider: LocalAssistantSettings["provider"];
  hasToken: boolean;
};
export const historyRowSchema = z
  .object({
    role: z.enum(["user", "assistant"]),
    text: z.string().max(16000),
    at: z.number().finite(),
  })
  .strict();
export const localHistorySchema = z
  .object({ expectedScope: z.string().regex(/^[a-f0-9]{64}$/), rows: z.array(historyRowSchema).max(40) })
  .strict();
export type HistoryRow = z.infer<typeof historyRowSchema>;
export interface LocalAssistantBridge {
  settings(): Promise<{ settings: LocalAssistantSettings; hasToken: boolean }>;
  configure(
    input: z.infer<typeof localSaveSchema>,
  ): Promise<{ settings: LocalAssistantSettings; hasToken: boolean }>;
  probe(input: z.infer<typeof localProbeSchema>): Promise<LocalProbe>;
  chat(input: z.infer<typeof localChatSchema>): Promise<LocalReply>;
  /** Text of the in-flight chat call as it streams; returns an unsubscribe function. */
  onDelta?(listener: (text: string) => void): () => void;
  warm?(): Promise<void>;
  cancel(): Promise<void>;
  historyLoad(): Promise<{ scope: string; rows: HistoryRow[] }>;
  historySave(input: z.infer<typeof localHistorySchema>): Promise<void>;
  transcribe(input: { data: Uint8Array; type: "audio/wav" | "audio/webm" }): Promise<string>;
}
