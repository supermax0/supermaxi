import type { ConversationQuery, DataSource } from "./source";
import { CoreError } from "./source";
import type {
  ActivityCategory,
  ActivityEvent,
  AgentState,
  Approval,
  ApprovalDecision,
  Conversation,
  CoreEvent,
  CustomerProfile,
  Fact,
  MergeSuggestion,
  Message,
  ProfileFieldKey,
  ShadowProposal,
  SystemStatus,
} from "./schemas";

/**
 * DEVELOPMENT-ONLY data source (spec §69, Phase 5: "use local development data only until backend is connected").
 * It is never constructed in production builds (see data/index.ts) and the UI shows a visible "DEV DATA" badge.
 * The optional simulation drives the orb through realistic agent states so the motion system can be verified.
 */

export interface DevSourceOptions {
  /** Run the scripted agent cycle. Off for deterministic tests / screenshots. */
  simulate: boolean;
  /** Fixed clock for deterministic screenshots. */
  now?: Date;
  /** Artificial latency in ms (makes loading states observable). */
  latency?: number;
  /** Index of the first scripted cycle (lets tests jump straight to e.g. the approval scenario). */
  firstCycle?: number;
  /** Delay before the first cycle, ms. */
  firstCycleDelay?: number;
}

type ConvSeed = Omit<Conversation, "lastMessageText" | "lastMessageAt" | "lastActivityAt"> & {
  minutesAgo: number;
};

const fact = (value: string | number, confidence = 0.95, source = "conversation"): Fact => ({
  value,
  confidence,
  source,
});

const EMPTY_FACTS: Record<ProfileFieldKey, Fact | null> = {
  businessType: null,
  specialty: null,
  doctors: null,
  employees: null,
  branches: null,
  country: null,
  city: null,
  phone: null,
  email: null,
};

const ONBOARDING = (done: number) =>
  [
    { key: "info", label: "إكمال معلومات العميل" },
    { key: "offer", label: "إرسال عرض السعر" },
    { key: "trial", label: "إنشاء حساب تجريبي" },
    { key: "setup", label: "إعداد النظام" },
    { key: "followup", label: "متابعة التفعيل" },
  ].map((s, i) => ({ ...s, done: i < done }));

export class DevDataSource implements DataSource {
  readonly kind = "development" as const;
  private conversations = new Map<string, Conversation>();
  private messages = new Map<string, Message[]>();
  private profiles = new Map<string, CustomerProfile>();
  private activity: ActivityEvent[] = [];
  private approvals: Approval[] = [];
  private listeners = new Set<(e: CoreEvent) => void>();
  private status: SystemStatus;
  private timers: ReturnType<typeof setTimeout>[] = [];
  private seq = 1000;
  private cycle = 0;
  private readonly opts: { simulate: boolean; latency: number; now: () => Date };

  constructor(options: DevSourceOptions) {
    const fixed = options.now;
    this.opts = {
      simulate: options.simulate,
      latency: options.latency ?? 140,
      now: fixed ? () => new Date(fixed.getTime()) : () => new Date(),
    };
    this.status = {
      environment: "development",
      channels: { instagram: "connected", facebook: "connected", telegram: "disconnected" },
      automationPaused: false,
      agent: { state: "idle", label: null, conversationId: null, channel: null },
      conversationCount: 0,
    };
    this.seed();
    this.cycle = options.firstCycle ?? 0;
    if (this.opts.simulate) this.schedule(options.firstCycleDelay ?? 2600, () => this.runCycle());
  }

  dispose(): void {
    this.timers.forEach(clearTimeout);
    this.timers = [];
    this.listeners.clear();
  }

  // ───────────────────────────── DataSource ─────────────────────────────

  async getStatus(): Promise<SystemStatus> {
    await this.delay();
    return structuredClone({ ...this.status, conversationCount: this.conversations.size });
  }

  async listConversations(q: ConversationQuery): Promise<Conversation[]> {
    await this.delay();
    const needle = q.search.trim().toLowerCase();
    return [...this.conversations.values()]
      .filter((c) => !c.archived)
      .filter((c) => q.channel === "all" || c.channel === q.channel)
      .filter((c) => {
        switch (q.filter) {
          case "all":
            return true;
          case "unread":
            return c.unreadCount > 0;
          case "ai_active":
            return c.control === "ai";
          case "human":
            return c.control === "human";
          case "qualified":
            return c.leadStage === "qualified";
          case "needs_approval":
            return c.pendingApprovals > 0;
          case "onboarding":
            return c.leadStage === "onboarding" || c.leadStage === "setup";
        }
      })
      .filter((c) => {
        if (!needle) return true;
        if (c.customerName.toLowerCase().includes(needle)) return true;
        return (this.messages.get(c.id) ?? []).some((m) => m.text.toLowerCase().includes(needle));
      })
      .sort((a, b) => b.lastActivityAt.localeCompare(a.lastActivityAt))
      .map((c) => structuredClone(c));
  }

  async listMessages(conversationId: string): Promise<Message[]> {
    await this.delay();
    const list = this.messages.get(conversationId);
    if (!list) throw new CoreError("NOT_FOUND", "المحادثة غير موجودة");
    return structuredClone(list);
  }

  async getCustomer(conversationId: string): Promise<CustomerProfile> {
    await this.delay();
    const p = this.profiles.get(conversationId);
    if (!p) throw new CoreError("NOT_FOUND", "ملف العميل غير موجود");
    return structuredClone(p);
  }

  async sendMessage(conversationId: string, text: string, idempotencyKey: string): Promise<Message> {
    await this.delay();
    const conv = this.mustConv(conversationId);
    if (conv.control === "ai") {
      throw new CoreError("CONFLICT", "استلم المحادثة أولاً قبل الإرسال اليدوي", { retryable: false });
    }
    const list = this.messages.get(conversationId) ?? [];
    const existing = list.find((m) => m.id === `h-${idempotencyKey}`);
    if (existing) return structuredClone(existing);
    const msg: Message = {
      id: `h-${idempotencyKey}`,
      conversationId,
      sender: "human",
      authorName: "Super Admin",
      text,
      at: this.iso(),
      delivery: "sent",
    };
    list.push(msg);
    this.touch(conv, text);
    this.emit({ type: "message.sent", message: msg });
    this.log("messages", "تم إرسال رد يدوي", conv.customerName);
    this.schedule(1200, () => this.updateDelivery(conversationId, msg.id, "delivered"));
    return structuredClone(msg);
  }

  sendMedia: DataSource["sendMedia"] = async () => {
    throw new CoreError("VALIDATION_ERROR", "إرسال الوسائط يحتاج اتصالاً بخادم FINORA");
  };
  getAccount: DataSource["getAccount"] = async () => {
    throw new CoreError("VALIDATION_ERROR", "ترتيب حساب العميل يحتاج خادم FINORA");
  };
  linkAccount: DataSource["linkAccount"] = async () => {
    throw new CoreError("VALIDATION_ERROR", "ربط الحساب يحتاج خادم FINORA");
  };
  proposeAccount: DataSource["proposeAccount"] = async () => {
    throw new CoreError("VALIDATION_ERROR", "إعداد الحساب يحتاج خادم FINORA");
  };
  listSupportIssues: DataSource["listSupportIssues"] = async () => [];
  resolveSupportIssue: DataSource["resolveSupportIssue"] = async () => {
    throw new CoreError("VALIDATION_ERROR", "التنبيهات تحتاج خادم FINORA");
  };
  getAttachment: DataSource["getAttachment"] = async () => {
    throw new CoreError("NOT_FOUND", "المرفق غير متاح في بيانات التطوير");
  };
  analyzeAttachment: DataSource["analyzeAttachment"] = async () => {
    throw new CoreError("VALIDATION_ERROR", "تحليل الوسائط يحتاج اتصالاً بخادم FINORA");
  };

  async setControl(conversationId: string, control: "human" | "ai"): Promise<Conversation> {
    await this.delay();
    const conv = this.mustConv(conversationId);
    conv.control = control;
    conv.assignedTo = control === "human" ? "Super Admin" : null;
    this.pushSystem(
      conversationId,
      control === "human"
        ? "استلم Super Admin المحادثة — تم إيقاف الردود التلقائية"
        : "تمت إعادة تشغيل FINORA CORE",
    );
    this.log(
      "ai",
      control === "human" ? "استلام المحادثة يدوياً" : "إعادة تشغيل FINORA CORE",
      conv.customerName,
    );
    this.emit({ type: "conversation.updated", conversation: structuredClone(conv) });
    return structuredClone(conv);
  }

  async addNote(conversationId: string, body: string): Promise<CustomerProfile> {
    await this.delay();
    const p = this.profiles.get(conversationId);
    if (!p) throw new CoreError("NOT_FOUND", "ملف العميل غير موجود");
    p.notes.unshift({ id: `n-${this.seq++}`, author: "Super Admin", body, at: this.iso() });
    return structuredClone(p);
  }

  async markRead(conversationId: string): Promise<void> {
    await this.delay(40);
    const conv = this.mustConv(conversationId);
    if (conv.unreadCount === 0) return;
    conv.unreadCount = 0;
    this.emit({ type: "conversation.updated", conversation: structuredClone(conv) });
  }

  async listActivity(category: ActivityCategory | "all"): Promise<ActivityEvent[]> {
    await this.delay();
    return structuredClone(this.activity.filter((e) => category === "all" || e.category === category));
  }

  async listApprovals(): Promise<Approval[]> {
    await this.delay();
    return structuredClone(this.approvals.filter((a) => a.status === "pending"));
  }

  // The development source has no Shadow Mode and no duplicate customers: the server owns both (Phase 9).
  async getShadow(): Promise<{ enabled: boolean; items: ShadowProposal[] }> {
    await this.delay(80);
    return { enabled: false, items: [] };
  }

  async listMergeSuggestions(): Promise<MergeSuggestion[]> {
    await this.delay(80);
    return [];
  }

  async decideMerge(): Promise<void> {
    throw new CoreError("NOT_FOUND", "الاقتراح غير موجود");
  }

  async decideApproval(id: string, decision: "approved" | "rejected"): Promise<ApprovalDecision> {
    await this.delay(260);
    const a = this.approvals.find((x) => x.id === id);
    if (!a) throw new CoreError("NOT_FOUND", "طلب الموافقة غير موجود");
    if (a.status !== "pending") throw new CoreError("CONFLICT", "تم البت في هذا الطلب مسبقاً");
    a.status = decision;
    if (a.conversationId) {
      const conv = this.conversations.get(a.conversationId);
      if (conv) {
        conv.pendingApprovals = Math.max(0, conv.pendingApprovals - 1);
        this.emit({ type: "conversation.updated", conversation: structuredClone(conv) });
      }
    }
    this.log("approvals", decision === "approved" ? "تمت الموافقة" : "تم الرفض", a.customerName, a.action);
    this.emit({ type: "approval.resolved", approval: structuredClone(a) });
    if (this.status.agent.state === "approval_required") {
      if (decision === "approved") {
        this.agent("executing", "يطبق الخصم المعتمد", a.conversationId);
        this.schedule(1600, () => this.agent("completed", "تم التنفيذ ✓", a.conversationId));
      } else {
        this.agent("replying", "يبلغ العميل بالقرار", a.conversationId);
        this.schedule(1500, () => this.agent("completed", null, a.conversationId));
      }
      this.schedule(3400, () => this.agent("idle", null, null));
    }
    return { approval: structuredClone(a), credentials: null };
  }

  async setAutomationPaused(paused: boolean, reason: string): Promise<SystemStatus> {
    await this.delay();
    if (paused && !reason.trim()) throw new CoreError("VALIDATION_ERROR", "سبب الإيقاف مطلوب");
    this.status.automationPaused = paused;
    this.log("ai", paused ? "تم إيقاف كل الأتمتة" : "تم استئناف الأتمتة", null, reason || null);
    const s = await this.getStatus();
    this.emit({ type: "status", status: s });
    return s;
  }

  subscribe(listener: (event: CoreEvent) => void): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  // ───────────────────────────── internals ─────────────────────────────

  private delay(ms = this.opts.latency): Promise<void> {
    return new Promise((r) => setTimeout(r, ms));
  }

  private schedule(ms: number, fn: () => void): void {
    this.timers.push(setTimeout(fn, ms));
  }

  private iso(offsetMin = 0): string {
    return new Date(this.opts.now().getTime() - offsetMin * 60_000).toISOString();
  }

  private emit(e: CoreEvent): void {
    this.listeners.forEach((l) => l(e));
  }

  private mustConv(id: string): Conversation {
    const c = this.conversations.get(id);
    if (!c) throw new CoreError("NOT_FOUND", "المحادثة غير موجودة");
    return c;
  }

  private touch(conv: Conversation, text: string): void {
    conv.lastMessageText = text;
    conv.lastMessageAt = this.iso();
    conv.lastActivityAt = conv.lastMessageAt;
    this.emit({ type: "conversation.updated", conversation: structuredClone(conv) });
  }

  private pushSystem(conversationId: string, text: string): void {
    const list = this.messages.get(conversationId);
    if (!list) return;
    const msg: Message = {
      id: `s-${this.seq++}`,
      conversationId,
      sender: "system",
      authorName: null,
      text,
      at: this.iso(),
      delivery: null,
    };
    list.push(msg);
    this.emit({ type: "message.received", message: msg });
  }

  private updateDelivery(conversationId: string, messageId: string, delivery: Message["delivery"]): void {
    const m = this.messages.get(conversationId)?.find((x) => x.id === messageId);
    if (!m) return;
    m.delivery = delivery;
    this.emit({ type: "message.sent", message: structuredClone(m) });
  }

  private log(
    category: ActivityCategory,
    title: string,
    customerName: string | null,
    detail: string | null = null,
    result: ActivityEvent["result"] = "ok",
  ): void {
    const e: ActivityEvent = {
      id: `a-${this.seq++}`,
      at: this.iso(),
      category,
      title,
      detail,
      customerName,
      result,
      correlationId: `corr-${(this.seq * 7919).toString(36)}`,
    };
    this.activity.unshift(e);
    if (this.activity.length > 400) this.activity.length = 400;
    this.emit({ type: "activity", event: e });
  }

  private agent(state: AgentState, label: string | null, conversationId: string | null): void {
    const conv = conversationId ? this.conversations.get(conversationId) : undefined;
    this.status.agent = { state, label, conversationId, channel: conv?.channel ?? null };
    if (conv) {
      conv.agentState = state;
      this.emit({ type: "conversation.updated", conversation: structuredClone(conv) });
    }
    this.emit({ type: "agent.status", status: structuredClone(this.status.agent) });
  }

  /** Scripted agent cycle: one realistic inbound → reply round trip, or an approval request. */
  private runCycle(): void {
    if (this.status.automationPaused || this.status.agent.state === "approval_required") {
      this.schedule(6000, () => this.runCycle());
      return;
    }
    const script = DEV_SCRIPT[this.cycle % DEV_SCRIPT.length];
    this.cycle += 1;
    if (!script) return;
    const conv = this.conversations.get(script.conversationId);
    if (!conv) return;
    const list = this.messages.get(conv.id) ?? [];

    const inbound: Message = {
      id: `m-${this.seq++}`,
      conversationId: conv.id,
      sender: "customer",
      authorName: null,
      text: script.customer,
      at: this.iso(),
      delivery: null,
    };
    list.push(inbound);
    conv.unreadCount += 1;
    this.touch(conv, inbound.text);
    this.emit({ type: "message.received", message: inbound });
    this.log(
      "messages",
      `رسالة جديدة من ${{ instagram: "Instagram", facebook: "Facebook", telegram: "Telegram" }[conv.channel]}`,
      conv.customerName,
    );

    if (conv.control !== "ai") {
      this.schedule(20000, () => this.runCycle());
      return;
    }

    this.agent("message_received", null, conv.id);
    this.schedule(900, () => this.agent("reading", null, conv.id));
    this.schedule(2300, () => this.agent("thinking", script.thinkingLabel, conv.id));
    this.schedule(3800, () => {
      this.agent("searching", null, conv.id);
      this.log("ai", "تصنيف النشاط", conv.customerName, script.classified);
    });

    if (script.approval) {
      const approval = script.approval;
      this.schedule(5200, () => {
        const a: Approval = {
          id: `ap-${this.seq++}`,
          conversationId: conv.id,
          customerName: conv.customerName,
          createdAt: this.iso(),
          status: "pending",
          ...approval,
        };
        this.approvals.unshift(a);
        conv.pendingApprovals += 1;
        this.emit({ type: "approval.required", approval: structuredClone(a) });
        this.log("approvals", "طلب موافقة", conv.customerName, a.action, "pending");
        this.agent("approval_required", null, conv.id);
      });
      this.schedule(26000, () => this.runCycle());
      return;
    }

    this.schedule(5000, () => this.agent("replying", null, conv.id));
    this.schedule(6600, () => {
      const reply: Message = {
        id: `m-${this.seq++}`,
        conversationId: conv.id,
        sender: "core",
        authorName: "Finora Core",
        text: script.reply,
        at: this.iso(),
        delivery: "sent",
      };
      list.push(reply);
      this.touch(conv, reply.text);
      this.emit({ type: "message.sent", message: reply });
      this.log("messages", "تم إرسال الرد", conv.customerName);
      this.agent("completed", null, conv.id);
      this.schedule(1100, () => this.updateDelivery(conv.id, reply.id, "delivered"));
    });
    this.schedule(8600, () => this.agent("idle", null, null));
    this.schedule(24000, () => this.runCycle());
  }

  private seed(): void {
    for (const s of SEEDS) {
      const { minutesAgo, ...rest } = s;
      const msgs = (SEED_MESSAGES[s.id] ?? []).map((m, i): Message => ({
        id: `${s.id}-m${i}`,
        conversationId: s.id,
        sender: m.sender,
        authorName: m.sender === "core" ? "Finora Core" : m.sender === "human" ? "Super Admin" : null,
        text: m.text,
        at: this.iso(minutesAgo + m.minutesBefore),
        delivery: m.sender === "core" || m.sender === "human" ? (m.delivery ?? "read") : null,
      }));
      const last = msgs[msgs.length - 1];
      this.conversations.set(s.id, {
        ...rest,
        lastMessageText: last?.text ?? "",
        lastMessageAt: last?.at ?? this.iso(minutesAgo),
        lastActivityAt: last?.at ?? this.iso(minutesAgo),
      });
      this.messages.set(s.id, msgs);
      this.profiles.set(s.id, {
        customerId: s.customerId,
        name: s.customerName,
        avatarUrl: null,
        channel: s.channel,
        leadStage: s.leadStage,
        facts: { ...EMPTY_FACTS, ...(SEED_FACTS[s.id] ?? {}) },
        recommendedPlan: SEED_PLANS[s.id] ?? null,
        finoraTenantId: s.leadStage === "setup" ? "tenant-al-noor" : null,
        onboarding: ONBOARDING(SEED_ONBOARDING[s.id] ?? 1),
        notes: SEED_NOTES[s.id]
          ? [{ id: `${s.id}-n0`, author: "Super Admin", body: SEED_NOTES[s.id] ?? "", at: this.iso(30) }]
          : [],
      });
    }
    const seedLog: [ActivityCategory, string, string | null, string | null, number][] = [
      ["messages", "رسالة جديدة من Instagram", "أحمد علي", null, 4],
      ["ai", "تصنيف النشاط", "أحمد علي", "عيادة أسنان", 4],
      ["ai", "تحديث ملف العميل", "أحمد علي", "3 أطباء، 2 موظفين، فرع واحد", 3],
      ["finora", "اقتراح باقة Finora Clinics", "أحمد علي", "احترافي", 3],
      ["messages", "تم إرسال الرد", "أحمد علي", null, 2],
      ["finora", "إنشاء حساب تجريبي", "شركة النور", "tenant-al-noor", 45],
    ];
    for (const [cat, title, cust, detail, mins] of seedLog.reverse()) {
      this.activity.unshift({
        id: `a-${this.seq++}`,
        at: this.iso(mins),
        category: cat,
        title,
        detail,
        customerName: cust,
        result: "ok",
        correlationId: `corr-${(this.seq * 7919).toString(36)}`,
      });
    }
  }
}

// ───────────────────────────── development fixtures ─────────────────────────────

const SEEDS: ConvSeed[] = [
  {
    id: "c1",
    customerId: "cu1",
    customerName: "أحمد علي",
    avatarUrl: null,
    channel: "instagram",
    unreadCount: 0,
    control: "ai",
    assignedTo: null,
    leadStage: "qualified",
    agentState: "idle",
    archived: false,
    escalated: false,
    pendingApprovals: 0,
    minutesAgo: 1,
  },
  {
    id: "c2",
    customerId: "cu2",
    customerName: "د. سارة",
    avatarUrl: null,
    channel: "facebook",
    unreadCount: 2,
    control: "ai",
    assignedTo: null,
    leadStage: "qualified",
    agentState: "idle",
    archived: false,
    escalated: false,
    pendingApprovals: 0,
    minutesAgo: 7,
  },
  {
    id: "c3",
    customerId: "cu3",
    customerName: "عيادة الحياة",
    avatarUrl: null,
    channel: "instagram",
    unreadCount: 1,
    control: "ai",
    assignedTo: null,
    leadStage: "engaged",
    agentState: "waiting_customer",
    archived: false,
    escalated: false,
    pendingApprovals: 0,
    minutesAgo: 22,
  },
  {
    id: "c4",
    customerId: "cu4",
    customerName: "شركة النور",
    avatarUrl: null,
    channel: "facebook",
    unreadCount: 0,
    control: "ai",
    assignedTo: null,
    leadStage: "setup",
    agentState: "idle",
    archived: false,
    escalated: false,
    pendingApprovals: 0,
    minutesAgo: 44,
  },
  {
    id: "c5",
    customerId: "cu5",
    customerName: "محمد خالد",
    avatarUrl: null,
    channel: "instagram",
    unreadCount: 0,
    control: "ai",
    assignedTo: null,
    leadStage: "engaged",
    agentState: "idle",
    archived: false,
    escalated: false,
    pendingApprovals: 0,
    minutesAgo: 62,
  },
  {
    id: "c6",
    customerId: "cu6",
    customerName: "سارة أحمد",
    avatarUrl: null,
    channel: "facebook",
    unreadCount: 1,
    control: "human",
    assignedTo: "Super Admin",
    leadStage: "needs_human",
    agentState: "idle",
    archived: false,
    escalated: true,
    pendingApprovals: 0,
    minutesAgo: 147,
  },
  {
    id: "c7",
    customerId: "cu7",
    customerName: "Al-Rashed Co.",
    avatarUrl: null,
    channel: "instagram",
    unreadCount: 0,
    control: "ai",
    assignedTo: null,
    leadStage: "proposal",
    agentState: "waiting_customer",
    archived: false,
    escalated: false,
    pendingApprovals: 0,
    minutesAgo: 200,
  },
];

type SeedMsg = {
  sender: Message["sender"];
  text: string;
  minutesBefore: number;
  delivery?: Message["delivery"];
};

const SEED_MESSAGES: Record<string, SeedMsg[]> = {
  c1: [
    { sender: "customer", text: "السلام عليكم\nعندي عيادة أسنان وأريد نظام\nكم يكلفني؟", minutesBefore: 3 },
    { sender: "system", text: "أنشأ FINORA CORE ملف العميل", minutesBefore: 3 },
    {
      sender: "core",
      text: "أهلاً دكتور أحمد\nنظام Finora Clinics مخصص لإدارة العيادات السنية ويشمل:\n✓ إدارة المرضى والمواعيد\n✓ الأطباء والفرق\n✓ الملفات العلاجية\n✓ الفواتير والمحاسبة\n✓ المخزون والصيدلية\n\nحتى أجهز لك عرض مناسب، كم عدد الأطباء في العيادة؟",
      minutesBefore: 2,
    },
    { sender: "customer", text: "لدينا 3 أطباء و 2 موظفين\nوفرع واحد حالياً", minutesBefore: 1 },
    {
      sender: "core",
      text: "ممتاز 👌\nسأجهز لك عرض سعر مخصص لعيادتكم خلال دقائق،\nوأتضمن الباقات المناسبة لعدد 3 أطباء و 2 موظفين.",
      minutesBefore: 0,
      delivery: "delivered",
    },
  ],
  c2: [
    { sender: "customer", text: "مرحباً، عندي عيادة جلدية", minutesBefore: 4 },
    { sender: "core", text: "أهلاً دكتورة سارة 🌿 هل العيادة فرع واحد أو أكثر؟", minutesBefore: 3 },
    { sender: "customer", text: "فرعين", minutesBefore: 1 },
    { sender: "customer", text: "كم سعر الباقات؟", minutesBefore: 0 },
  ],
  c3: [
    { sender: "customer", text: "السلام عليكم هل النظام يدعم الحجز الإلكتروني؟", minutesBefore: 2 },
    {
      sender: "core",
      text: "وعليكم السلام، نعم يدعم إدارة المواعيد بالكامل. هل عيادتكم أسنان أو تخصص آخر؟",
      minutesBefore: 0,
    },
  ],
  c4: [
    { sender: "customer", text: "نريد نظام المخزون وإدارة العيادات", minutesBefore: 6 },
    { sender: "core", text: "تم إنشاء حسابكم التجريبي وتفعيل وحدات المخزون والعيادات ✓", minutesBefore: 2 },
    { sender: "system", text: "تمت جدولة مكالمة إعداد", minutesBefore: 0 },
  ],
  c5: [{ sender: "customer", text: "هل يمكن إضافة المزيد من الموظفين لاحقاً؟", minutesBefore: 0 }],
  c6: [
    { sender: "customer", text: "متى يتوفر البرنامج على الموبايل؟", minutesBefore: 5 },
    { sender: "system", text: "استلم Super Admin المحادثة", minutesBefore: 4 },
    { sender: "human", text: "أهلاً سارة، سأتحقق من الموعد وأرجع لك اليوم.", minutesBefore: 3 },
    { sender: "customer", text: "شكراً، بانتظارك", minutesBefore: 0 },
  ],
  c7: [
    { sender: "customer", text: "We need a detailed quote for 4 branches", minutesBefore: 3 },
    {
      sender: "core",
      text: "Sure — could you share how many employees work at each branch?",
      minutesBefore: 0,
    },
  ],
};

const SEED_FACTS: Record<string, Partial<Record<ProfileFieldKey, Fact>>> = {
  c1: {
    businessType: fact("عيادة أسنان", 0.98),
    doctors: fact(3, 0.99),
    employees: fact(2, 0.99),
    branches: fact(1, 0.97),
    country: fact("السعودية - الرياض", 0.8, "instagram_profile"),
  },
  c2: { businessType: fact("عيادة جلدية", 0.96), branches: fact(2, 0.95) },
  c4: { businessType: fact("عيادة", 0.9), employees: fact(8, 0.85), city: fact("بغداد", 0.9) },
  c7: { businessType: fact("Commerce", 0.7), branches: fact(4, 0.95) },
};

const SEED_PLANS: Record<string, { name: string; tier: string }> = {
  c1: { name: "Finora Clinics", tier: "احترافي" },
  c2: { name: "Finora Clinics", tier: "متعدد الفروع" },
  c4: { name: "Finora Clinics", tier: "أساسي" },
};

const SEED_ONBOARDING: Record<string, number> = { c1: 2, c2: 1, c4: 4, c7: 2 };

const SEED_NOTES: Record<string, string> = {
  c1: "مهتم بالنظام ويريد عرض سعر تفصيلي مع المزايا المناسبة لعيادته.",
};

interface ScriptStep {
  conversationId: string;
  customer: string;
  thinkingLabel: string | null;
  classified: string;
  reply: string;
  approval?: Pick<Approval, "action" | "reason" | "oldValue" | "newValue" | "agentLimit" | "risk">;
}

const DEV_SCRIPT: ScriptStep[] = [
  {
    conversationId: "c5",
    customer: "عندنا محل مواد غذائية، هل النظام يناسبنا؟",
    thinkingLabel: "يحلل احتياجات المتجر",
    classified: "مواد غذائية",
    reply: "أكيد 👌 FINORA يدعم نقاط البيع والمخزون والطلبات للمواد الغذائية. كم فرع عندكم؟",
  },
  {
    conversationId: "c2",
    customer: "نحتاج حساب لكل طبيب",
    thinkingLabel: "يحلل احتياجات العيادة",
    classified: "عيادة جلدية — فرعين",
    reply: "ممكن طبعاً، كل طبيب يحصل على حساب وصلاحيات خاصة. كم عدد الأطباء في الفرعين؟",
  },
  {
    conversationId: "c3",
    customer: "عيادة أسنان، 2 أطباء. ممكن خصم 30%؟",
    thinkingLabel: "يراجع سياسة الخصومات",
    classified: "عيادة أسنان",
    reply: "",
    approval: {
      action: "خصم 30% على الاشتراك السنوي",
      reason: "العميل طلب خصماً أعلى من حد صلاحية الوكيل",
      oldValue: "0%",
      newValue: "30%",
      agentLimit: "15%",
      risk: "high",
    },
  },
];

let devInstance: DevDataSource | null = null;

/** Single shared instance for the app lifetime (HMR-safe). */
export function getDevSource(options: DevSourceOptions): DevDataSource {
  if (!devInstance) devInstance = new DevDataSource(options);
  return devInstance;
}
