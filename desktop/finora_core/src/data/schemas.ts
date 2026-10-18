import { z } from "zod";
import { supportIssueSchema } from "./accounts";

/**
 * Wire contracts between the desktop and `/api/v1/finora-core` (see docs/finora-core-architecture.md §5).
 * Every payload crossing the DataSource boundary is parsed with these schemas; malformed data is rejected.
 */

export const channelSchema = z.enum(["instagram", "facebook", "telegram"]);
export type Channel = z.infer<typeof channelSchema>;

export const agentStateSchema = z.enum([
  "idle",
  "message_received",
  "reading",
  "thinking",
  "searching",
  "replying",
  "executing",
  "waiting_customer",
  "approval_required",
  "completed",
  "error",
  "offline",
]);
export type AgentState = z.infer<typeof agentStateSchema>;

export const leadStageSchema = z.enum([
  "new",
  "engaged",
  "qualified",
  "proposal",
  "trial",
  "account_created",
  "setup",
  "onboarding",
  "active_customer",
  "needs_human",
  "lost",
]);
export type LeadStage = z.infer<typeof leadStageSchema>;

/** Who is currently driving a conversation. */
export const controlSchema = z.enum(["ai", "human", "paused"]);
export type Control = z.infer<typeof controlSchema>;

export const isoDate = z.string().datetime({ offset: true });

export const conversationSchema = z.object({
  id: z.string(),
  customerId: z.string(),
  customerName: z.string().min(1),
  avatarUrl: z.string().url().nullable(),
  channel: channelSchema,
  lastMessageText: z.string(),
  lastMessageAt: isoDate,
  /** Last time something meaningful happened (customer/agent/human message). Drives sort order. */
  lastActivityAt: isoDate,
  unreadCount: z.number().int().nonnegative(),
  control: controlSchema,
  assignedTo: z.string().nullable(),
  leadStage: leadStageSchema,
  agentState: agentStateSchema,
  archived: z.boolean(),
  escalated: z.boolean(),
  pendingApprovals: z.number().int().nonnegative(),
});
export type Conversation = z.infer<typeof conversationSchema>;

export const deliveryStateSchema = z.enum(["sending", "sent", "delivered", "read", "failed"]);
export type DeliveryState = z.infer<typeof deliveryStateSchema>;

export const senderSchema = z.enum(["customer", "core", "human", "system"]);
export type Sender = z.infer<typeof senderSchema>;

export const messageSchema = z.object({
  id: z.string(),
  conversationId: z.string(),
  sender: senderSchema,
  authorName: z.string().nullable(),
  text: z.string(),
  at: isoDate,
  /** Only outbound messages carry delivery state, and only what the provider actually reported. */
  delivery: deliveryStateSchema.nullable(),
  /** Safe attachment view (no provider URLs). Absent for plain text and for the development source. */
  attachments: z.array(z.lazy(() => attachmentSchema)).optional(),
});

export const attachmentSchema = z.object({
  id: z.string(),
  kind: z.enum(["image", "audio", "video", "document", "sticker", "unsupported"]),
  mimeType: z.string().nullable(),
  name: z.string().nullable(),
  sizeBytes: z.number().int().nonnegative().nullable(),
  status: z.enum(["pending", "stored", "failed", "unsupported", "not_downloadable"]),
  durationSeconds: z.number().nonnegative().nullable().optional(),
  analysis: z
    .object({
      status: z.enum(["processing", "completed", "failed"]),
      summary: z.string().optional(),
      details: z.string().optional(),
      needsHuman: z.boolean().optional(),
      model: z.string().optional(),
      provider: z.string().optional(),
      frameTimes: z.array(z.number().nonnegative()).optional(),
      error: z.string().optional(),
      at: isoDate.optional(),
    })
    .optional(),
});
export type Attachment = z.infer<typeof attachmentSchema>;
export type Message = z.infer<typeof messageSchema>;

export const factSchema = z.object({
  value: z.union([z.string(), z.number()]),
  confidence: z.number().min(0).max(1),
  source: z.string(),
});
export type Fact = z.infer<typeof factSchema>;

export const profileFieldKeySchema = z.enum([
  "businessType",
  "specialty",
  "doctors",
  "employees",
  "branches",
  "country",
  "city",
  "phone",
  "email",
]);
export type ProfileFieldKey = z.infer<typeof profileFieldKeySchema>;

export const noteSchema = z.object({ id: z.string(), author: z.string(), body: z.string(), at: isoDate });
export type Note = z.infer<typeof noteSchema>;

export const onboardingStepSchema = z.object({ key: z.string(), label: z.string(), done: z.boolean() });
export type OnboardingStep = z.infer<typeof onboardingStepSchema>;

export const projectTermsSchema = z.object({
  amount: z.number().int().min(5),
  currency: z.enum(["IQD", "USD"]),
  days: z.number().int().positive(),
  mvpDays: z.number().int().positive(),
});
export type ProjectTerms = z.infer<typeof projectTermsSchema>;
export const projectSchema = z.object({
  revision: z.number().int(),
  phase: z.enum([
    "discovery",
    "scope_review",
    "internal_review",
    "quote_ready",
    "quote_sent",
    "quote_rejected",
    "awaiting_deposit",
    "deposit_review",
    "execution_ready",
    "cancelled",
  ]),
  brief: z.object({
    title: z.string(),
    kind: z.string(),
    goal: z.string(),
    audience: z.string(),
    platforms: z.array(z.string()),
    requirements: z.array(z.object({ text: z.string(), evidence: z.string() })),
    suggestions: z.array(z.object({ title: z.string(), benefit: z.string() })),
    pages: z.array(
      z.object({
        id: z.string(),
        name: z.string(),
        purpose: z.string(),
        features: z.array(z.string()),
        links: z.array(z.string()),
        roles: z.array(z.string()),
        phase: z.enum(["mvp", "later"]),
        acceptance: z.array(z.string()),
      }),
    ),
    roles: z.array(z.object({ name: z.string(), permissions: z.array(z.string()) })),
    entities: z.array(
      z.object({ name: z.string(), fields: z.array(z.string()), relatedTo: z.array(z.string()) }),
    ),
    integrations: z.array(
      z.object({ name: z.string(), purpose: z.string(), requiresClientAccess: z.boolean() }),
    ),
    milestones: z.array(z.object({ name: z.string(), deliverables: z.array(z.string()) })),
    workflows: z
      .array(
        z.object({
          id: z.string(),
          name: z.string(),
          trigger: z.string(),
          steps: z.array(
            z.object({
              id: z.string(),
              pageId: z.string(),
              role: z.string(),
              action: z.string(),
              result: z.string(),
              next: z.array(z.object({ stepId: z.string(), condition: z.string() })),
            }),
          ),
          acceptance: z.array(z.string()),
        }),
      )
      .optional(),
    assumptions: z.array(z.string()),
    exclusions: z.array(z.string()),
    risks: z.array(z.string()),
    questions: z.array(z.string()),
    ready: z.boolean(),
    estimate: projectTermsSchema.extend({ basis: z.string() }).nullable(),
  }),
  terms: projectTermsSchema.nullable(),
  scopeConsent: z.string().nullable(),
  customerConsent: z.object({ messageId: z.string(), quoteHash: z.string() }).nullable(),
  paymentClaim: z.object({ messageId: z.string(), text: z.string() }).nullable(),
  paymentReference: z.string().nullable(),
  depositVerified: z.boolean(),
});
export type ProjectConsultation = z.infer<typeof projectSchema>;

export const customerProfileSchema = z.object({
  customerId: z.string(),
  name: z.string(),
  avatarUrl: z.string().url().nullable(),
  channel: channelSchema,
  leadStage: leadStageSchema,
  facts: z.record(profileFieldKeySchema, factSchema.nullable()),
  recommendedPlan: z.object({ name: z.string(), tier: z.string() }).nullable(),
  finoraTenantId: z.string().nullable(),
  onboarding: z.array(onboardingStepSchema),
  notes: z.array(noteSchema),
  project: projectSchema.nullable().optional(),
});
export type CustomerProfile = z.infer<typeof customerProfileSchema>;

export const activityCategorySchema = z.enum(["messages", "ai", "finora", "errors", "approvals"]);
export type ActivityCategory = z.infer<typeof activityCategorySchema>;

export const activityEventSchema = z.object({
  id: z.string(),
  at: isoDate,
  category: activityCategorySchema,
  title: z.string(),
  detail: z.string().nullable(),
  customerName: z.string().nullable(),
  result: z.enum(["ok", "failed", "pending"]),
  correlationId: z.string(),
});
export type ActivityEvent = z.infer<typeof activityEventSchema>;

export const riskSchema = z.enum(["low", "medium", "high"]);
export type Risk = z.infer<typeof riskSchema>;

/** Exact, immutable action plan shown before approval (server-built; no secrets, contact data as presence only). */
export const approvalPreviewSchema = z
  .object({
    project: projectSchema,
    projectAction: z.enum(["publish_project_quote", "confirm_project_deposit"]),
    depositAmount: z.string(),
    accountScope: z.object({ tenantSlug: z.string(), label: z.string() }),
    changes: z.array(
      z.object({ key: z.string(), label: z.string(), before: z.boolean(), after: z.boolean() }),
    ),
    permissionChanges: z.record(z.boolean()),
    employeeId: z.number().int().nullable(),
    employeeName: z.string().nullable(),
    businessTypeChange: z.object({ before: z.string(), after: z.string() }).nullable(),
    permissionDiff: z.array(z.object({ key: z.string(), before: z.boolean(), after: z.boolean() })),
    unavailableFeatures: z.array(z.object({ key: z.string(), label: z.string() })),
    roleChanges: z.object({ before: z.array(z.string()), after: z.array(z.string()) }).nullable(),
    roleIds: z.array(z.number().int()).nullable(),
    customer: z.object({ id: z.number(), name: z.string() }).partial(),
    businessType: z.object({ key: z.string(), label: z.string() }).nullable(),
    specialty: z.string().nullable(),
    plan: z.object({
      key: z.string().optional(),
      name: z.string().nullable(),
      priceMonthly: z.number().nullable().optional(),
    }),
    size: z.object({
      doctors: z.number().nullable(),
      employees: z.number().nullable(),
      branches: z.number().nullable(),
    }),
    modules: z.array(
      z.object({ key: z.string(), label: z.string(), enabled: z.number(), total: z.number() }),
    ),
    tenantActions: z.array(z.object({ action: z.string(), label: z.string() })),
    users: z.array(
      z.object({
        username: z.string(),
        role: z.string(),
        credentials: z.string(),
        mustChangePassword: z.boolean(),
      }),
    ),
    subscription: z.object({ change: z.string(), trialDays: z.number().optional(), billing: z.string() }),
    discount: z.object({ percent: z.number(), agentLimit: z.string().nullable() }),
    contact: z.object({ phone: z.boolean(), email: z.boolean() }),
  })
  .partial();
export type ApprovalPreview = z.infer<typeof approvalPreviewSchema>;

export const approvalSchema = z.object({
  id: z.string(),
  conversationId: z.string().nullable(),
  customerName: z.string(),
  action: z.string(),
  reason: z.string(),
  oldValue: z.string().nullable(),
  newValue: z.string(),
  agentLimit: z.string().nullable(),
  risk: riskSchema,
  status: z.enum(["pending", "approved", "rejected", "superseded"]),
  /** Approval authorizes exactly this plan: the decision quotes its hash (Phase 9). */
  riskClass: z.string().nullable().optional(),
  planHash: z.string().nullable().optional(),
  planVersion: z.number().int().optional(),
  preview: approvalPreviewSchema.nullable().optional(),
  createdAt: isoDate,
});
export type Approval = z.infer<typeof approvalSchema>;

/** Shadow Mode: what FINORA CORE would have answered/done — never sent or executed. */
export const shadowProposalSchema = z.object({
  id: z.string(),
  conversationId: z.string(),
  status: z.enum(["pending", "answered", "superseded"]),
  proposedReply: z.string(),
  confidence: z.number().nullable(),
  intents: z.array(z.object({ name: z.string(), confidence: z.number() })),
  actions: z.array(
    z.object({
      action: z.string().nullable(),
      tool: z.string().nullable(),
      riskClass: z.string(),
      verdict: z.string(),
      note: z.string(),
    }),
  ),
  approvals: z.array(z.object({ kind: z.string() }).passthrough()),
  cited: z.array(z.string()),
  escalation: z.object({
    proposed: z.boolean(),
    reason: z.string().nullable(),
    decision: z.string().nullable(),
  }),
  human: z
    .object({
      reply: z.string(),
      actor: z.string().nullable(),
      at: isoDate.nullable(),
      usedProposal: z.boolean().nullable(),
      accepted: z.boolean().nullable(),
      edited: z.boolean().nullable(),
      similarity: z.number().nullable(),
    })
    .nullable(),
  createdAt: isoDate,
});
export type ShadowProposal = z.infer<typeof shadowProposalSchema>;

const maskedIdentifierSchema = z.object({ kind: z.string(), masked: z.string(), verified: z.boolean() });
const mergeSideSchema = z.object({
  id: z.number(),
  name: z.string().nullable(),
  stage: z.string().nullable(),
  identifiers: z.array(maskedIdentifierSchema),
  hasTenant: z.boolean(),
});
export const mergeSuggestionSchema = z.object({
  id: z.string(),
  status: z.string(),
  reason: z.string(),
  confidence: z.number(),
  customer: mergeSideSchema,
  candidate: mergeSideSchema,
  matched: z.array(z.object({ kind: z.string().nullable(), masked: z.string().nullable() })),
  mergeId: z.number().nullable(),
  decidedBy: z.string().nullable(),
});
export type MergeSuggestion = z.infer<typeof mergeSuggestionSchema>;

/** Returned ONCE to the approving operator when a trial account is created. Never stored by the desktop. */
export const credentialsSchema = z.object({
  tenantSlug: z.string(),
  username: z.string(),
  password: z.string(),
  loginUrl: z.string().nullable(),
});
export type Credentials = z.infer<typeof credentialsSchema>;

export const approvalDecisionSchema = z.object({
  approval: approvalSchema,
  credentials: credentialsSchema.nullable(),
});
export type ApprovalDecision = z.infer<typeof approvalDecisionSchema>;

export const connectionSchema = z.enum([
  "connected",
  "token_expired",
  "permission_missing",
  "webhook_invalid",
  "disconnected",
  "unknown",
]);
export type Connection = z.infer<typeof connectionSchema>;

export const systemStatusSchema = z.object({
  environment: z.enum(["development", "staging", "production"]),
  channels: z.object({
    instagram: connectionSchema,
    facebook: connectionSchema,
    telegram: connectionSchema.default("disconnected"),
  }),
  automationPaused: z.boolean(),
  agent: z.object({
    state: agentStateSchema,
    /** Short, user-safe execution label. Never model reasoning. */
    label: z.string().nullable(),
    conversationId: z.string().nullable(),
    channel: channelSchema.nullable(),
  }),
  conversationCount: z.number().int().nonnegative(),
  /** Server-only facts; absent for the development source. */
  houseConfigured: z.boolean().optional(),
  devLoopback: z.boolean().optional(),
  /** Shadow Mode: FINORA CORE proposes, humans answer; nothing is sent or executed automatically. */
  shadowMode: z.boolean().optional(),
});
export type SystemStatus = z.infer<typeof systemStatusSchema>;

export const coreEventSchema = z.discriminatedUnion("type", [
  z.object({ type: z.literal("support.issue"), issue: supportIssueSchema }),
  z.object({ type: z.literal("agent.status"), status: systemStatusSchema.shape.agent }),
  z.object({ type: z.literal("conversation.updated"), conversation: conversationSchema }),
  z.object({ type: z.literal("message.received"), message: messageSchema }),
  z.object({ type: z.literal("message.sent"), message: messageSchema }),
  z.object({ type: z.literal("message.updated"), message: messageSchema }),
  z.object({ type: z.literal("customer.updated"), customerId: z.string() }),
  z.object({ type: z.literal("approval.required"), approval: approvalSchema }),
  z.object({ type: z.literal("approval.resolved"), approval: approvalSchema }),
  z.object({ type: z.literal("activity"), event: activityEventSchema }),
  z.object({ type: z.literal("status"), status: systemStatusSchema }),
  z.object({ type: z.literal("shadow.proposal"), proposal: shadowProposalSchema }),
  /** Emitted by the transport after a reconnect: the client must resync from REST. */
  z.object({ type: z.literal("resync") }),
]);

export const operatorSchema = z.object({
  id: z.number().int(),
  username: z.string(),
  role: z.enum(["super_admin", "admin", "sales", "support", "read_only"]),
  permissions: z.array(z.string()),
});
export type Operator = z.infer<typeof operatorSchema>;

export const tokenResponseSchema = z.object({
  accessToken: z.string().min(1),
  refreshToken: z.string().min(1),
  expiresIn: z.number().int().positive(),
  operator: operatorSchema,
});
export type TokenResponse = z.infer<typeof tokenResponseSchema>;
export type CoreEvent = z.infer<typeof coreEventSchema>;
