/**
 * Pure request/response helpers for the FINORA transport (no Electron imports,
 * so they are unit-tested directly).
 */
import type { FinoraRequest, FinoraResponse } from "../../shared/ipc";

export const DEFAULT_TIMEOUT_MS = 20_000;

export function buildRequestUrl(serverUrl: string, request: Pick<FinoraRequest, "path" | "query">): string {
  const url = new URL(request.path, `${serverUrl}/`);
  for (const [key, value] of Object.entries(request.query ?? {})) {
    for (const item of Array.isArray(value) ? value : [value]) {
      url.searchParams.append(key, String(item));
    }
  }
  return url.toString();
}

/** Headers FINORA uses to answer with JSON (403/401) instead of HTML redirects. */
export function requestHeaders(request: FinoraRequest, appVersion: string): Record<string, string> {
  const headers: Record<string, string> = {
    Accept: "application/json",
    "X-Requested-With": "XMLHttpRequest",
    "X-Finora-Client": `management-desktop/${appVersion}`,
  };
  if (request.body !== undefined) headers["Content-Type"] = "application/json";
  return headers;
}

interface RawResponse {
  status: number;
  location: string | null;
  contentType: string | null;
  bodyText: string;
}

/**
 * FINORA's session pages redirect to a login page when the session is gone
 * and to the change-password page while a one-time password is active.
 */
export function classifyResponse(raw: RawResponse): FinoraResponse {
  const { status } = raw;
  if (status === 0 || (status >= 300 && status < 400)) {
    const location = (raw.location ?? "").toLowerCase();
    if (location.includes("change-password"))
      return { ok: false, failure: "password_change_required", status };
    // A signed-in user without a page permission is sent elsewhere (/pos, /) — that is "no access", not an
    // ended session. Treating it as a sign-out logged cashiers out right after sign-in.
    if (location && !location.includes("login")) {
      return {
        ok: false,
        failure: "http",
        status: 403,
        data: { success: false, error: "ليست لديك صلاحية لهذه الصفحة" },
      };
    }
    return { ok: false, failure: "unauthenticated", status };
  }

  const isJson = (raw.contentType ?? "").toLowerCase().includes("application/json");
  let data: unknown = null;
  if (raw.bodyText.length > 0) {
    if (!isJson && status >= 400) {
      // e.g. Flask's HTML 404 for a deleted order — keep the HTTP status meaningful
      return { ok: false, failure: "http", status, data: null };
    }
    if (!isJson) {
      return {
        ok: false,
        failure: "invalid_response",
        status,
        detail: `content-type ${raw.contentType ?? "none"}`,
      };
    }
    try {
      data = JSON.parse(raw.bodyText);
    } catch {
      return { ok: false, failure: "invalid_response", status, detail: "malformed json" };
    }
  }

  if (status === 403 && isPasswordChangeBody(data)) {
    return { ok: false, failure: "password_change_required", status };
  }
  if (status >= 200 && status < 300) return { ok: true, status, data };
  return { ok: false, failure: "http", status, data };
}

function isPasswordChangeBody(data: unknown): boolean {
  if (typeof data !== "object" || data === null) return false;
  const record = data as Record<string, unknown>;
  return record.error === "password_change_required" || record.code === "password_change_required";
}
