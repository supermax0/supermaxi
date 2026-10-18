/**
 * Unified error layer: every failure talking to FINORA becomes a FinoraApiError
 * with a stable `kind` and an Arabic message for the user.
 */
import type { FinoraResponse } from "@shared/ipc";

export type FinoraErrorKind =
  | "not_configured"
  | "network"
  | "timeout"
  | "unauthenticated"
  | "invalid_credentials"
  | "password_change_required"
  | "forbidden"
  | "not_found"
  | "validation"
  | "conflict"
  | "rate_limited"
  | "server"
  | "invalid_response"
  | "refused";

const MESSAGES: Record<FinoraErrorKind, string> = {
  not_configured: "لم يتم تحديد عنوان خادم FINORA بعد.",
  network: "لا يوجد اتصال بـ FINORA. تحقق من الإنترنت أو عنوان الخادم.",
  timeout: "استغرق FINORA وقتاً طويلاً في الرد. أعد المحاولة.",
  unauthenticated: "انتهت الجلسة، سجّل الدخول من جديد.",
  invalid_credentials: "بيانات الدخول غير صحيحة.",
  password_change_required: "كلمة المرور مؤقتة. غيّرها من FINORA على الويب ثم سجّل الدخول.",
  forbidden: "ليست لديك صلاحية لهذه العملية.",
  not_found: "العنصر المطلوب غير موجود أو تم حذفه.",
  validation: "البيانات المدخلة غير صحيحة.",
  conflict: "تم تعديل البيانات من مستخدم آخر. حدّث الصفحة وأعد المحاولة.",
  rate_limited: "محاولات كثيرة، انتظر قليلاً ثم أعد المحاولة.",
  server: "حدث خطأ في خادم FINORA. أعد المحاولة لاحقاً.",
  invalid_response: "رد غير متوقع من FINORA.",
  refused: "تم رفض الطلب من التطبيق لأسباب أمنية.",
};

export class FinoraApiError extends Error {
  readonly kind: FinoraErrorKind;
  readonly status: number | undefined;
  readonly code: string | undefined;
  readonly detail: string | undefined;

  constructor(
    kind: FinoraErrorKind,
    options: { message?: string; status?: number; code?: string; detail?: string } = {},
  ) {
    super(options.message ?? MESSAGES[kind]);
    this.name = "FinoraApiError";
    this.kind = kind;
    this.status = options.status;
    this.code = options.code;
    this.detail = options.detail;
  }

  /** Session-level failures the whole app reacts to (sign-in screen). */
  get endsSession(): boolean {
    return this.kind === "unauthenticated" || this.kind === "password_change_required";
  }

  /** Failures that mean FINORA could not be reached at all. */
  get isConnectivity(): boolean {
    return this.kind === "network" || this.kind === "timeout";
  }
}

export function defaultMessage(kind: FinoraErrorKind): string {
  return MESSAGES[kind];
}

function kindForStatus(status: number): FinoraErrorKind {
  if (status === 400 || status === 422) return "validation";
  if (status === 401) return "unauthenticated";
  if (status === 403) return "forbidden";
  if (status === 404 || status === 410) return "not_found";
  if (status === 409) return "conflict";
  if (status === 429) return "rate_limited";
  return "server";
}

/** FINORA endpoints answer with {error}, {message} or {ok:false,error,code}. */
function serverText(data: unknown): { message?: string; code?: string } {
  if (typeof data !== "object" || data === null) return {};
  const record = data as Record<string, unknown>;
  const text = [record.error, record.message, record.msg].find(
    (value): value is string => typeof value === "string",
  );
  const code = typeof record.code === "string" ? record.code : undefined;
  // Arabic server messages are written for end users; English ones are technical and stay in logs.
  const message = text && /[\u0600-\u06FF]/.test(text) ? text : undefined;
  return { message, code };
}

export function errorFromResponse(response: Exclude<FinoraResponse, { ok: true }>): FinoraApiError {
  if (response.failure !== "http") {
    return new FinoraApiError(response.failure, { status: response.status, detail: response.detail });
  }
  const { message, code } = serverText(response.data);
  let kind = code === "rate_limited" ? "rate_limited" : kindForStatus(response.status);
  // A rejected sign-in is a 401 too, but it does not mean an existing session ended.
  if (kind === "unauthenticated" && code === "invalid_credentials") kind = "invalid_credentials";
  return new FinoraApiError(kind, {
    status: response.status,
    code,
    message: kind === "unauthenticated" ? undefined : message,
    detail: typeof response.data === "object" ? JSON.stringify(response.data).slice(0, 500) : undefined,
  });
}

export function toFinoraError(error: unknown): FinoraApiError {
  if (error instanceof FinoraApiError) return error;
  return new FinoraApiError("invalid_response", {
    detail: error instanceof Error ? error.message : String(error),
  });
}
