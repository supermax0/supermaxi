import type { FastifyPluginAsync } from "fastify";
import { z } from "zod";
import { env } from "../../config/env.js";
import { runWorkflowById } from "../workflows/workflow-runner.js";

const telegramUpdateSchema = z.object({
  update_id: z.number().optional(),
  message: z
    .object({
      text: z.string().optional(),
      chat: z.object({ id: z.union([z.string(), z.number()]) }),
      from: z.object({ id: z.union([z.string(), z.number()]).optional() }).optional(),
    })
    .optional(),
});

async function sendTelegramMessage(chatId: string, text: string) {
  if (!env.TELEGRAM_BOT_TOKEN) return false;
  const url = `https://api.telegram.org/bot${env.TELEGRAM_BOT_TOKEN}/sendMessage`;
  const response = await fetch(url, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ chat_id: chatId, text }),
  });
  return response.ok;
}

export const telegramWebhookRoutes: FastifyPluginAsync = async (app) => {
  app.post("/telegram/:workflowId", async (request, reply) => {
    const workflowId = Number((request.params as Record<string, unknown>).workflowId);
    if (!Number.isFinite(workflowId)) {
      return reply.code(400).send({ success: false, error: "invalid_workflow_id" });
    }

    const parsed = telegramUpdateSchema.safeParse(request.body);
    if (!parsed.success) {
      return reply.code(400).send({ success: false, error: "invalid_telegram_payload" });
    }

    const message = parsed.data.message;
    const messageText = message?.text || "";
    const chatId = message?.chat?.id ? String(message.chat.id) : "";
    const fromId = message?.from?.id ? String(message.from.id) : "unknown";

    const runResult = await runWorkflowById(workflowId, "default", fromId, {
      channel: "telegram",
      user_id: fromId,
      chat_id: chatId,
      message_text: messageText,
    });

    const replyText = String(runResult.context.reply_text || runResult.context.ai_output || "").trim();
    if (chatId && replyText) {
      await sendTelegramMessage(chatId, replyText);
    }

    return reply.code(202).send({
      success: true,
      execution_id: runResult.executionId,
      status: runResult.status,
      replied: Boolean(replyText),
    });
  });
};
