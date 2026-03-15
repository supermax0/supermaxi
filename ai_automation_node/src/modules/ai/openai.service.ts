import OpenAI from "openai";
import { env } from "../../config/env.js";

let client: OpenAI | null = null;

function getClient() {
  if (!env.OPENAI_API_KEY) return null;
  if (!client) {
    client = new OpenAI({ apiKey: env.OPENAI_API_KEY });
  }
  return client;
}

export async function generateText(messages: OpenAI.Chat.Completions.ChatCompletionMessageParam[], maxTokens = 500) {
  const api = getClient();
  if (!api) {
    throw new Error("OPENAI_API_KEY is not configured");
  }
  const response = await api.chat.completions.create({
    model: env.OPENAI_MODEL,
    messages,
    max_tokens: maxTokens,
    temperature: 0.5,
  });
  return response.choices[0]?.message?.content?.trim() ?? "";
}

export async function createEmbedding(input: string): Promise<number[] | null> {
  const api = getClient();
  if (!api) return null;
  const emb = await api.embeddings.create({
    model: "text-embedding-3-small",
    input,
  });
  return emb.data?.[0]?.embedding ?? null;
}
