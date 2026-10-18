import { z } from "zod";
import { projectGraphSchema, projectConnectionSchema } from "../workspace/projectGraph";
import { liveSessionSchema, type Notice } from "../notifications/voice";
import { accountSchema, supportIssueSchema, type AccountLink, type AccountProposal } from "./accounts";
import {
  agentSettingsSchema,
  connectionTestSchema,
  knowledgeOverviewSchema,
  metaSettingsSchema,
  telegramSettingsSchema,
  replyPreviewSchema,
  type AgentConfig,
} from "./coreSettings";
import {
  activityEventSchema,
  approvalDecisionSchema,
  approvalSchema,
  conversationSchema,
  coreEventSchema,
  customerProfileSchema,
  projectSchema,
  mergeSuggestionSchema,
  messageSchema,
  shadowProposalSchema,
  systemStatusSchema,
  tokenResponseSchema,
  type ActivityCategory,
  type CoreEvent,
  type Operator,
  type TokenResponse,
} from "./schemas";
import {
  CoreError,
  type ConversationQuery,
  type DataSource,
  type ErrorCode,
  type MergeDecision,
  type ShadowReplyLink,
} from "./source";

const API_PREFIX = "/api/v1/finora-core";
const REQUEST_TIMEOUT_MS = 15_000;
const KNOWN_CODES: readonly ErrorCode[] = [
  "NETWORK_ERROR",
  "AUTH_ERROR",
  "PERMISSION_ERROR",
  "VALIDATION_ERROR",
  "NOT_FOUND",
  "CONFLICT",
  "RATE_LIMITED",
  "HOUSE_NOT_CONFIGURED",
  "META_SEND_FAILED",
  "VOICE_UNAVAILABLE",
  "UNKNOWN_ERROR",
];

const errorBodySchema = z.object({
  error: z.object({ code: z.string(), message: z.string(), retryable: z.boolean().optional() }),
});

/** Session tokens; desktop persistence is handled by the encrypted native session store. */
export interface AuthSession {
  accessToken: string;
  refreshToken: string;
  operator: Operator;
}

export function normalizeServerUrl(input: string): string | null {
  try {
    const url = new URL(input.trim());
    const local = ["localhost", "127.0.0.1", "[::1]"].includes(url.hostname);
    // Production traffic must be TLS; plain http is accepted only for a local development server.
    if (url.protocol !== "https:" && !(url.protocol === "http:" && local)) return null;
    // The apex domain 301-redirects to www; browsers refuse redirects on CORS preflights, so talk to www directly.
    if (url.hostname === "finora.company") url.hostname = "www.finora.company";
    return url.origin;
  } catch {
    return null;
  }
}

function toCoreError(status: number, body: unknown): CoreError {
  const parsed = errorBodySchema.safeParse(body);
  if (parsed.success) {
    const { code, message, retryable } = parsed.data.error;
    const known = (KNOWN_CODES as readonly string[]).includes(code) ? (code as ErrorCode) : "UNKNOWN_ERROR";
    return new CoreError(known, message, { retryable: retryable ?? status >= 500 });
  }
  return new CoreError("UNKNOWN_ERROR", "استجابة غير متوقعة من الخادم", { retryable: status >= 500 });
}

async function readJson(res: Response): Promise<unknown> {
  const text = await res.text();
  if (!text) return null;
  try {
    return JSON.parse(text) as unknown;
  } catch (err) {
    throw new CoreError("UNKNOWN_ERROR", "استجابة غير صالحة من الخادم", { cause: err, retryable: true });
  }
}

/** Login without an existing session. */
export async function login(baseUrl: string, username: string, password: string): Promise<TokenResponse> {
  let res: Response;
  try {
    res = await fetch(`${baseUrl}${API_PREFIX}/auth/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password }),
      signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS),
    });
  } catch (err) {
    throw new CoreError("NETWORK_ERROR", "تعذر الاتصال بالخادم", { cause: err });
  }
  const body = await readJson(res);
  if (!res.ok) throw toCoreError(res.status, body);
  return tokenResponseSchema.parse(body);
}

export class HttpDataSource implements DataSource {
  readonly kind = "http" as const;
  private refreshing: Promise<void> | null = null;
  private signedOut = false;

  constructor(
    readonly baseUrl: string,
    private session: AuthSession,
    private readonly onSessionChange: (s: AuthSession | null) => void | Promise<void>,
  ) {}

  get operator(): Operator {
    return this.session.operator;
  }

  // ───────────────────────────── transport ─────────────────────────────

  private async refresh(): Promise<void> {
    if (this.signedOut) throw new CoreError("AUTH_ERROR", "سجّل الدخول للمتابعة");
    this.refreshing ??= (async () => {
      try {
        const res = await fetch(`${this.baseUrl}${API_PREFIX}/auth/refresh`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ refreshToken: this.session.refreshToken }),
          signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS),
        });
        const body = await readJson(res);
        if (!res.ok) {
          const err = toCoreError(res.status, body);
          if (err.code === "AUTH_ERROR" && !this.signedOut) {
            this.signedOut = true;
            await this.onSessionChange(null);
          }
          throw err;
        }
        const t = tokenResponseSchema.parse(body);
        if (this.signedOut) throw new CoreError("AUTH_ERROR", "سجّل الدخول للمتابعة");
        this.session = { accessToken: t.accessToken, refreshToken: t.refreshToken, operator: t.operator };
        await this.onSessionChange(this.session);
      } finally {
        this.refreshing = null;
      }
    })();
    return this.refreshing;
  }

  private async request<T>(
    path: string,
    schema: z.ZodType<T, z.ZodTypeDef, unknown>,
    init: {
      method?: string;
      body?: unknown;
      headers?: Record<string, string>;
      timeoutMs?: number;
      blob?: boolean;
      signal?: AbortSignal;
    } = {},
    retried = false,
  ): Promise<T> {
    if (this.signedOut) throw new CoreError("AUTH_ERROR", "سجّل الدخول للمتابعة");
    const accessToken = this.session.accessToken;
    let res: Response;
    try {
      res = await fetch(`${this.baseUrl}${API_PREFIX}${path}`, {
        method: init.method ?? "GET",
        headers: {
          Authorization: `Bearer ${accessToken}`,
          ...(init.body !== undefined && !(init.body instanceof FormData)
            ? { "Content-Type": "application/json" }
            : {}),
          ...init.headers,
        },
        body:
          init.body instanceof FormData
            ? init.body
            : init.body !== undefined
              ? JSON.stringify(init.body)
              : undefined,
        signal: init.signal
          ? AbortSignal.any([init.signal, AbortSignal.timeout(init.timeoutMs ?? REQUEST_TIMEOUT_MS)])
          : AbortSignal.timeout(init.timeoutMs ?? REQUEST_TIMEOUT_MS),
      });
    } catch (err) {
      throw new CoreError("NETWORK_ERROR", "تعذر الاتصال بالخادم", { cause: err });
    }
    if (res.status === 401 && !retried) {
      if (accessToken === this.session.accessToken) await this.refresh();
      else if (this.refreshing) await this.refreshing;
      return this.request(path, schema, init, true);
    }
    const body = init.blob && res.ok ? await res.blob() : await readJson(res);
    if (!res.ok) throw toCoreError(res.status, body);
    const parsed = schema.safeParse(body);
    if (!parsed.success) {
      console.error("[finora-core] contract violation", path, parsed.error.issues);
      throw new CoreError("UNKNOWN_ERROR", "بيانات غير متوافقة من الخادم", {
        cause: parsed.error,
        retryable: false,
      });
    }
    return parsed.data;
  }

  // ───────────────────────────── DataSource ─────────────────────────────
  getAccount(conversationId: string) {
    return this.request(`/conversations/${encodeURIComponent(conversationId)}/account`, accountSchema);
  }
  linkAccount(conversationId: string, value: AccountLink) {
    return this.request(`/conversations/${encodeURIComponent(conversationId)}/account/link`, accountSchema, {
      method: "POST",
      body: value,
    });
  }
  async proposeAccount(conversationId: string, value: AccountProposal) {
    const result = await this.request(
      `/conversations/${encodeURIComponent(conversationId)}/account/propose`,
      z.object({ approval: approvalSchema }),
      { method: "POST", body: value },
    );
    return result.approval;
  }
  async listSupportIssues() {
    const result = await this.request("/support/issues", z.object({ items: z.array(supportIssueSchema) }));
    return result.items;
  }
  async resolveSupportIssue(id: string) {
    await this.request(
      `/support/issues/${encodeURIComponent(id)}/resolve`,
      z.object({ issue: supportIssueSchema }),
      { method: "POST" },
    );
  }

  getStatus() {
    return this.request("/status", systemStatusSchema);
  }

  getAgentSettings() {
    return this.request("/settings/agent", agentSettingsSchema);
  }

  getProductKnowledge(query = "", businessType = "") {
    const params = new URLSearchParams({ q: query, businessType });
    return this.request(`/settings/knowledge?${params}`, knowledgeOverviewSchema);
  }

  saveAgentSettings(config: AgentConfig) {
    return this.request("/settings/agent", agentSettingsSchema, { method: "PATCH", body: config });
  }

  saveCloudKey(apiKey: string) {
    return this.request("/settings/agent/cloud-key", agentSettingsSchema, {
      method: "POST",
      body: { apiKey },
    });
  }

  testAgentProvider() {
    return this.request("/settings/agent/test", connectionTestSchema, { method: "POST", timeoutMs: 90_000 });
  }

  previewAgentReply(text: string) {
    return this.request("/settings/agent/preview", replyPreviewSchema, {
      method: "POST",
      body: { text },
      timeoutMs: 90_000,
    });
  }

  getMetaSettings() {
    return this.request("/settings/meta", metaSettingsSchema);
  }

  getTelegramSettings() {
    return this.request("/settings/telegram", telegramSettingsSchema);
  }

  connectTelegram(botToken: string) {
    return this.request("/settings/telegram/connect", telegramSettingsSchema, {
      method: "POST",
      body: { botToken },
      timeoutMs: 120_000,
    });
  }

  checkTelegramHealth() {
    return this.request("/settings/telegram/health-check", telegramSettingsSchema, {
      method: "POST",
      timeoutMs: 90_000,
    });
  }

  disconnectTelegram() {
    return this.request("/settings/telegram/disconnect", telegramSettingsSchema, {
      method: "POST",
      timeoutMs: 90_000,
    });
  }

  provisionMetaHouse() {
    return this.request("/settings/meta/provision", metaSettingsSchema, {
      method: "POST",
      timeoutMs: 90_000,
    });
  }

  connectMeta(body: { appId: string; appSecret: string; userToken: string }) {
    return this.request(
      "/settings/meta/connect",
      z.object({ pagesFound: z.number(), warningsCount: z.number(), message: z.string() }),
      {
        method: "POST",
        body,
        timeoutMs: 180_000,
      },
    );
  }

  getMetaVerification() {
    return this.request("/settings/meta/verification", z.object({ verifyToken: z.string() }), {
      method: "POST",
    });
  }

  checkMetaHealth() {
    return this.request("/channels/health-check", z.object({ channels: z.record(z.string()) }), {
      method: "POST",
      timeoutMs: 90_000,
    });
  }

  async listConversations(q: ConversationQuery) {
    const params = new URLSearchParams({ channel: q.channel, filter: q.filter, limit: "100" });
    if (q.search.trim()) params.set("q", q.search.trim());
    const res = await this.request(
      `/conversations?${params}`,
      z.object({ items: z.array(conversationSchema) }),
    );
    return res.items;
  }

  async listMessages(conversationId: string) {
    const res = await this.request(
      `/conversations/${encodeURIComponent(conversationId)}/messages?limit=200`,
      z.object({ items: z.array(messageSchema) }),
    );
    return res.items;
  }

  getCustomer(conversationId: string) {
    return this.request(`/customers/${encodeURIComponent(conversationId)}`, customerProfileSchema);
  }

  async sendMessage(conversationId: string, text: string, idempotencyKey: string, shadow?: ShadowReplyLink) {
    const res = await this.request(
      `/conversations/${encodeURIComponent(conversationId)}/messages`,
      z.object({ message: messageSchema }),
      {
        method: "POST",
        body: shadow ? { text, proposalId: shadow.proposalId, usedProposal: shadow.usedProposal } : { text },
        headers: { "Idempotency-Key": idempotencyKey },
      },
    );
    return res.message;
  }

  async sendMedia(conversationId: string, file: File, idempotencyKey: string) {
    const body = new FormData();
    body.append("file", file, file.name);
    const result = await this.request(
      `/conversations/${encodeURIComponent(conversationId)}/media`,
      z.object({ message: messageSchema }),
      { method: "POST", body, headers: { "Idempotency-Key": idempotencyKey }, timeoutMs: 180_000 },
    );
    return result.message;
  }

  getAttachment(conversationId: string, messageId: string, attachmentId: string, signal?: AbortSignal) {
    return this.request(
      `/conversations/${encodeURIComponent(conversationId)}/messages/${encodeURIComponent(messageId)}/attachments/${encodeURIComponent(attachmentId)}`,
      z.instanceof(Blob),
      { blob: true, signal, timeoutMs: 120_000 },
    );
  }

  async analyzeAttachment(conversationId: string, messageId: string, attachmentId: string) {
    const result = await this.request(
      `/conversations/${encodeURIComponent(conversationId)}/messages/${encodeURIComponent(messageId)}/attachments/${encodeURIComponent(attachmentId)}/analyze`,
      z.object({ message: messageSchema }),
      { method: "POST", timeoutMs: 240_000 },
    );
    return result.message;
  }

  setControl(conversationId: string, control: "human" | "ai") {
    const action = control === "human" ? "takeover" : "resume";
    return this.request(
      `/conversations/${encodeURIComponent(conversationId)}/${action}`,
      conversationSchema,
      {
        method: "POST",
      },
    );
  }

  addNote(conversationId: string, body: string) {
    return this.request(`/customers/${encodeURIComponent(conversationId)}/notes`, customerProfileSchema, {
      method: "POST",
      body: { body },
    });
  }

  async markRead(conversationId: string) {
    await this.request(
      `/conversations/${encodeURIComponent(conversationId)}/read`,
      z.object({ ok: z.literal(true) }),
      {
        method: "POST",
      },
    );
  }

  async listActivity(category: ActivityCategory | "all") {
    const res = await this.request(
      `/activity?category=${category}`,
      z.object({ items: z.array(activityEventSchema) }),
    );
    return res.items;
  }

  async listApprovals() {
    const res = await this.request("/approvals", z.object({ items: z.array(approvalSchema) }));
    return res.items;
  }

  async reviseProjectApproval(
    id: string,
    planHash: string,
    review: {
      terms?: import("./schemas").ProjectTerms;
      paymentReference?: string;
      paymentVerified?: boolean;
    },
  ) {
    const result = await this.request(
      `/approvals/${encodeURIComponent(id)}/project`,
      z.object({ approval: approvalSchema }),
      {
        method: "PATCH",
        body: { planHash, ...review },
      },
    );
    return result.approval;
  }

  getProjectManifest(conversationId: string) {
    return this.request(
      `/conversations/${encodeURIComponent(conversationId)}/project/manifest`,
      z.record(z.unknown()),
    );
  }

  getProjectGraph(conversationId: string) {
    return this.request(
      `/conversations/${encodeURIComponent(conversationId)}/project/graph`,
      projectGraphSchema,
    );
  }

  analyzeProjectGraph(conversationId: string, planHash: string) {
    return this.request(
      `/conversations/${encodeURIComponent(conversationId)}/project/graph/analyze`,
      projectGraphSchema,
      { method: "POST", body: { planHash }, timeoutMs: 80_000 },
    );
  }

  async createProjectConnection(conversationId: string) {
    const connection = await this.request(
      `/conversations/${encodeURIComponent(conversationId)}/project/mcp-connection`,
      projectConnectionSchema,
      { method: "POST", body: {} },
    );
    return { ...connection, endpoint: `${this.baseUrl}${connection.endpointPath}` };
  }

  async revokeProjectConnection(conversationId: string) {
    await this.request(
      `/conversations/${encodeURIComponent(conversationId)}/project/mcp-connection/revoke`,
      z.object({ revoked: z.literal(true) }),
      { method: "POST", body: {} },
    );
  }

  async resendProjectQuote(conversationId: string) {
    const result = await this.request(
      `/conversations/${encodeURIComponent(conversationId)}/project/send-offer`,
      z.object({ project: projectSchema }),
      { method: "POST", body: {} },
    );
    return result.project;
  }

  decideApproval(id: string, decision: "approved" | "rejected", planHash: string | null) {
    return this.request(`/approvals/${encodeURIComponent(id)}/decision`, approvalDecisionSchema, {
      method: "POST",
      body: { decision, planHash },
    });
  }

  getShadow(conversationId: string) {
    return this.request(
      `/conversations/${encodeURIComponent(conversationId)}/shadow`,
      z.object({ enabled: z.boolean(), items: z.array(shadowProposalSchema) }),
    );
  }

  async listMergeSuggestions() {
    const res = await this.request("/merge-suggestions", z.object({ items: z.array(mergeSuggestionSchema) }));
    return res.items;
  }

  async decideMerge(id: string, decision: MergeDecision) {
    await this.request(
      `/merge-suggestions/${encodeURIComponent(id)}/decision`,
      z.object({ ok: z.literal(true) }).passthrough(),
      {
        method: "POST",
        body: { decision },
      },
    );
  }

  setAutomationPaused(paused: boolean, reason: string) {
    return this.request("/automation", systemStatusSchema, { method: "POST", body: { paused, reason } });
  }

  async logout(): Promise<void> {
    try {
      await this.request("/auth/logout", z.object({ ok: z.literal(true) }), { method: "POST" });
    } finally {
      this.signedOut = true;
      await this.onSessionChange(null);
    }
  }

  createNotificationSession(notice: Notice, sdp: string, signal: AbortSignal) {
    return this.request("/voice/notifications/session", liveSessionSchema, {
      method: "POST",
      body: { kind: notice.kind, ref: notice.ref, sdp },
      signal,
      timeoutMs: 25000,
    });
  }

  /**
   * Server-Sent Events over fetch (EventSource cannot send an Authorization header).
   * Reconnects with backoff, resumes from Last-Event-ID and asks the UI to resync after every reconnect.
   */
  subscribe(listener: (event: CoreEvent) => void): () => void {
    const abort = new AbortController();
    let lastId: string | null = null;
    let attempt = 0;

    const dispatch = (type: string, data: string) => {
      let payload: unknown;
      try {
        payload = JSON.parse(data) as unknown;
      } catch (err) {
        console.warn("[finora-core] malformed event dropped", type, err);
        return;
      }
      const parsed = coreEventSchema.safeParse({ type, ...(payload as Record<string, unknown>) });
      if (parsed.success) listener(parsed.data);
      else console.warn("[finora-core] unknown event dropped", type, parsed.error.issues);
    };

    const run = async () => {
      while (!abort.signal.aborted) {
        try {
          const res = await fetch(`${this.baseUrl}${API_PREFIX}/events/stream`, {
            headers: {
              Authorization: `Bearer ${this.session.accessToken}`,
              Accept: "text/event-stream",
              ...(lastId ? { "Last-Event-ID": lastId } : {}),
            },
            signal: abort.signal,
          });
          if (res.status === 401) {
            await this.refresh();
            continue;
          }
          if (!res.ok || !res.body) throw new CoreError("NETWORK_ERROR", `stream HTTP ${res.status}`);
          // Resync on EVERY successful connect (the first one too): the stream starts at "now", so anything that
          // happened between the initial REST load and this connect would otherwise never reach an open view.
          listener({ type: "resync" });
          attempt = 0;
          const reader = res.body.pipeThrough(new TextDecoderStream()).getReader();
          let buffer = "";
          for (;;) {
            const { value, done } = await reader.read();
            if (done) break;
            buffer += value;
            let sep: number;
            while ((sep = buffer.indexOf("\n\n")) !== -1) {
              const block = buffer.slice(0, sep);
              buffer = buffer.slice(sep + 2);
              let type = "message";
              const data: string[] = [];
              for (const line of block.split("\n")) {
                if (line.startsWith("id: ")) lastId = line.slice(4);
                else if (line.startsWith("event: ")) type = line.slice(7);
                else if (line.startsWith("data: ")) data.push(line.slice(6));
              }
              if (data.length) dispatch(type, data.join("\n"));
            }
          }
          attempt = 1; // server closes streams periodically; reconnect immediately and resync
        } catch (err) {
          if (abort.signal.aborted) return;
          if (err instanceof CoreError && err.code === "AUTH_ERROR") return;
          attempt += 1;
          const delay = Math.min(30_000, 500 * 2 ** attempt) * (0.75 + Math.random() * 0.5);
          console.warn(`[finora-core] event stream lost, retrying in ${Math.round(delay)}ms`, err);
          await new Promise((r) => setTimeout(r, delay));
        }
      }
    };
    void run();
    return () => abort.abort();
  }
}
