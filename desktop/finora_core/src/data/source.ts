import type {
  ActivityCategory,
  ActivityEvent,
  Approval,
  ApprovalDecision,
  Conversation,
  CoreEvent,
  CustomerProfile,
  MergeSuggestion,
  Message,
  ShadowProposal,
  SystemStatus,
} from "./schemas";
import type { AccountLink, AccountProposal, AccountView, SupportIssue } from "./accounts";

/** Links a manual reply to the Shadow Mode proposal it was based on (accepted / edited tracking). */
export interface ShadowReplyLink {
  proposalId: string;
  usedProposal: boolean;
}

export type MergeDecision = "merge" | "separate" | "dismiss";

export type ErrorCode =
  | "NETWORK_ERROR"
  | "AUTH_ERROR"
  | "PERMISSION_ERROR"
  | "VALIDATION_ERROR"
  | "NOT_FOUND"
  | "CONFLICT"
  | "RATE_LIMITED"
  | "HOUSE_NOT_CONFIGURED"
  | "META_SEND_FAILED"
  | "VOICE_UNAVAILABLE"
  | "UNKNOWN_ERROR";

/** Classified error. `message` is user-safe Arabic text; technical detail stays in `cause`. */
export class CoreError extends Error {
  readonly code: ErrorCode;
  readonly retryable: boolean;

  constructor(code: ErrorCode, message: string, options?: { cause?: unknown; retryable?: boolean }) {
    super(message, { cause: options?.cause });
    this.name = "CoreError";
    this.code = code;
    this.retryable = options?.retryable ?? code === "NETWORK_ERROR";
  }
}

export interface ConversationQuery {
  channel: "all" | "instagram" | "facebook" | "telegram";
  filter: ConversationFilter;
  search: string;
}

export type ConversationFilter =
  "all" | "unread" | "ai_active" | "human" | "qualified" | "needs_approval" | "onboarding";

/**
 * Port between the UI and FINORA CORE's backend. The UI depends only on this interface.
 * Implementations: DevDataSource (development only) and the HTTP source (Phase 6).
 */
export interface DataSource {
  getAccount(conversationId: string): Promise<AccountView>;
  linkAccount(conversationId: string, value: AccountLink): Promise<AccountView>;
  proposeAccount(conversationId: string, value: AccountProposal): Promise<Approval>;
  listSupportIssues(): Promise<SupportIssue[]>;
  resolveSupportIssue(id: string): Promise<void>;
  readonly kind: "development" | "http";
  getStatus(): Promise<SystemStatus>;
  listConversations(query: ConversationQuery): Promise<Conversation[]>;
  listMessages(conversationId: string): Promise<Message[]>;
  getCustomer(conversationId: string): Promise<CustomerProfile>;
  sendMessage(
    conversationId: string,
    text: string,
    idempotencyKey: string,
    shadow?: ShadowReplyLink,
  ): Promise<Message>;
  sendMedia(conversationId: string, file: File, idempotencyKey: string): Promise<Message>;
  getAttachment(
    conversationId: string,
    messageId: string,
    attachmentId: string,
    signal?: AbortSignal,
  ): Promise<Blob>;
  analyzeAttachment(conversationId: string, messageId: string, attachmentId: string): Promise<Message>;
  setControl(conversationId: string, control: "human" | "ai"): Promise<Conversation>;
  addNote(conversationId: string, body: string): Promise<CustomerProfile>;
  markRead(conversationId: string): Promise<void>;
  listActivity(category: ActivityCategory | "all"): Promise<ActivityEvent[]>;
  listApprovals(): Promise<Approval[]>;
  reviseProjectApproval?(
    id: string,
    planHash: string,
    review: {
      terms?: import("./schemas").ProjectTerms;
      paymentReference?: string;
      paymentVerified?: boolean;
    },
  ): Promise<Approval>;
  getProjectManifest?(conversationId: string): Promise<Record<string, unknown>>;
  getProjectGraph?(conversationId: string): Promise<import("../workspace/projectGraph").ProjectGraph>;
  analyzeProjectGraph?(
    conversationId: string,
    planHash: string,
  ): Promise<import("../workspace/projectGraph").ProjectGraph>;
  createProjectConnection?(
    conversationId: string,
  ): Promise<import("../workspace/projectGraph").ProjectConnection>;
  revokeProjectConnection?(conversationId: string): Promise<void>;
  resendProjectQuote?(conversationId: string): Promise<import("./schemas").ProjectConsultation>;
  /** `planHash` is the hash of the plan the operator reviewed; a changed plan is refused by the server. */
  decideApproval(
    id: string,
    decision: "approved" | "rejected",
    planHash: string | null,
  ): Promise<ApprovalDecision>;
  getShadow(conversationId: string): Promise<{ enabled: boolean; items: ShadowProposal[] }>;
  listMergeSuggestions(): Promise<MergeSuggestion[]>;
  decideMerge(id: string, decision: MergeDecision): Promise<void>;
  setAutomationPaused(paused: boolean, reason: string): Promise<SystemStatus>;
  /** Realtime hints. The UI refetches from REST on each event; events are never the source of truth. */
  subscribe(listener: (event: CoreEvent) => void): () => void;
}
