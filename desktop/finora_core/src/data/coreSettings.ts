import { z } from "zod";

export const agentConfigSchema = z.object({
  provider: z.enum(["cloud", "local", "hybrid", "off"]),
  cloudModel: z.string(),
  localUrl: z.string(),
  localModel: z.string(),
  timeoutSeconds: z.number(),
  replyMode: z.enum(["automatic", "review", "manual"]),
  language: z.enum(["auto", "ar-iq", "ar", "en"]),
  tone: z.enum(["friendly", "professional"]),
  replyLength: z.enum(["short", "balanced"]),
  minimumConfidence: z.number(),
  instructions: z.string(),
});
export type AgentConfig = z.infer<typeof agentConfigSchema>;
export const agentSettingsSchema = z.object({
  config: agentConfigSchema,
  cloudKeyConfigured: z.boolean(),
  cloudKeySource: z.enum(["core", "server"]),
  resolvedCloudModel: z.string(),
});
export type AgentSettings = z.infer<typeof agentSettingsSchema>;
export const metaSettingsSchema = z.object({
  houseConfigured: z.boolean(),
  appId: z.string(),
  secretConfigured: z.boolean(),
  webhookUrl: z.string(),
  channels: z.array(
    z.object({ type: z.string(), name: z.string(), accountId: z.string(), status: z.string() }),
  ),
});
export const telegramSettingsSchema = z.object({
  houseConfigured: z.boolean(),
  tokenConfigured: z.boolean(),
  botId: z.string(),
  username: z.string(),
  name: z.string(),
  active: z.boolean(),
  status: z.string(),
  webhookUrl: z.string(),
  botUrl: z.string(),
  lastError: z.string().nullable(),
});
export const connectionTestSchema = z.object({
  ok: z.boolean(),
  message: z.string(),
  provider: z.string(),
  model: z.string(),
});
export const replyPreviewSchema = z.object({
  text: z.string(),
  source: z.string(),
  model: z.string(),
  needsHuman: z.boolean(),
  reason: z.string().nullable(),
  fallback: z.string().nullable(),
  knowledgeSources: z.array(z.object({ id: z.string(), title: z.string() })).optional(),
});
export type ReplyPreview = z.infer<typeof replyPreviewSchema>;

export const knowledgeOverviewSchema = z.object({
  featureCount: z.number().int(),
  guideCount: z.number().int(),
  publishedCount: z.number().int(),
  note: z.string(),
  categories: z.array(z.object({ name: z.string(), count: z.number().int() })),
  results: z.array(
    z.object({
      id: z.string(),
      title: z.string(),
      text: z.string(),
      kind: z.enum(["guide", "feature", "document"]),
      businessType: z.string().nullable(),
      source: z.string(),
    }),
  ),
});
