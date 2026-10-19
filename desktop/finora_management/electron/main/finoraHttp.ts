/**
 * All traffic to FINORA leaves from here. The session cookie lives only in the
 * dedicated Chromium partition (encrypted at rest by the OS on Windows) and is
 * never exposed to the renderer.
 */
import { app, session, type Session } from "electron";
import { isCustomerCommand } from "../../shared/customerRecovery";
import { isStockCommand } from "../../shared/stockRecovery";
import { auditPath } from "../../shared/inventoryAudit";
import type { FinoraFormRequest, FinoraRequest, FinoraResponse } from "../../shared/ipc";
import { getServerUrl } from "./config";
import { buildRequestUrl, classifyResponse, DEFAULT_TIMEOUT_MS, requestHeaders } from "./httpCore";
import { encodeMultipart, netRequest, NetTimeoutError, type NetResponse } from "./netRequest";
import {
  deactivateOffline,
  enableOfflineAccess,
  getOfflineEngine,
  recordOfflineIssue,
} from "./offlineRuntime";

export const FINORA_PARTITION = "persist:finora-management";

export function finoraSession(): Session {
  return session.fromPartition(FINORA_PARTITION);
}

function classify(response: NetResponse): FinoraResponse {
  return classifyResponse({
    status: response.status,
    location: response.location,
    contentType: response.contentType,
    bodyText: response.body.toString("utf8"),
  });
}

function failure(error: unknown): FinoraResponse {
  return {
    ok: false,
    failure: error instanceof NetTimeoutError ? "timeout" : "network",
    detail: error instanceof Error ? error.message : String(error),
  };
}

export async function sendFinoraRequest(request: FinoraRequest): Promise<FinoraResponse> {
  let received: FinoraResponse | undefined;
  try {
    const engine = await getOfflineEngine(sendFinoraNetworkRequest);
    const result = await engine.request(request, async (r) => {
      received = await sendFinoraNetworkRequest(r, engine.serverUrl);
      return received;
    });
    if (
      result.ok &&
      !result.source &&
      request.path.startsWith("/api/v1/desktop/auth/") &&
      engine.status().available
    )
      await enableOfflineAccess();
    return result;
  } catch (error) {
    recordOfflineIssue(error);
    if (request.method === "POST" && auditPath.test(request.path))
      return {
        ok: false,
        failure: "http",
        status: 503,
        data: { success: false, error: "تعذّر تثبيت الحفظ الآمن للجرد؛ راجع الطلب المحفوظ وأعد نفس الطلب" },
      };
    if (isCustomerCommand(request) || isStockCommand(request))
      return {
        ok: false,
        failure: "http",
        status: 503,
        data: { error: "تعذّر تأكيد التخزين الآمن للعملية؛ راجع طلبات الحفظ المحفوظة وأعد نفس الطلب" },
      };
    // A failed local checkpoint must never cause a second transmission of a write.
    return received ?? sendFinoraNetworkRequest(request);
  }
}

export async function sendFinoraNetworkRequest(
  request: FinoraRequest,
  expectedServer?: string,
): Promise<FinoraResponse> {
  const serverUrl = await getServerUrl();
  if (!serverUrl) return { ok: false, failure: "not_configured" };
  if (expectedServer && serverUrl !== expectedServer)
    return { ok: false, failure: "unauthenticated", detail: "تغيّر خادم FINORA؛ لم تُرسل العملية." };
  const started = Date.now();
  let result: FinoraResponse;
  try {
    const response = await netRequest(finoraSession(), buildRequestUrl(serverUrl, request), {
      method: request.method,
      headers: requestHeaders(request, app.getVersion()),
      body: request.body === undefined ? undefined : Buffer.from(JSON.stringify(request.body), "utf8"),
      timeoutMs: request.timeoutMs ?? DEFAULT_TIMEOUT_MS,
    });
    result = classify(response);
  } catch (error) {
    result = failure(error);
  }
  logRequest(request, result, started);
  return result;
}

/** Multipart POST (fields + optional image) through the same session and response rules. */
export async function sendFinoraForm(request: FinoraFormRequest): Promise<FinoraResponse> {
  const serverUrl = await getServerUrl();
  if (!serverUrl) return { ok: false, failure: "not_configured" };
  const { body, contentType } = encodeMultipart(request.fields, request.file, request.files);
  const logInfo: FinoraRequest = { method: "POST", path: request.path };
  const started = Date.now();
  let result: FinoraResponse;
  try {
    const response = await netRequest(finoraSession(), buildRequestUrl(serverUrl, { path: request.path }), {
      method: "POST",
      headers: {
        Accept: "application/json",
        "X-Requested-With": "XMLHttpRequest",
        "X-Finora-Client": `management-desktop/${app.getVersion()}`,
        "Content-Type": contentType,
      },
      body,
      timeoutMs: request.timeoutMs ?? 60_000,
    });
    result = classify(response);
  } catch (error) {
    result = failure(error);
  }
  logRequest(logInfo, result, started);
  return result;
}

/** Same-server image bytes for the finora-media protocol (null when not an image). */
export async function fetchFinoraImage(path: string): Promise<{ type: string; data: Buffer } | null> {
  const serverUrl = await getServerUrl();
  if (!serverUrl) return null;
  const response = await netRequest(finoraSession(), new URL(path, `${serverUrl}/`).toString(), {
    method: "GET",
    headers: {},
    timeoutMs: 20_000,
  });
  const type = response.contentType ?? "";
  if (response.status !== 200 || !type.startsWith("image/")) return null;
  return { type, data: response.body };
}

export async function clearFinoraSession(): Promise<void> {
  (await import("./connectedPages")).closeWorkspaces();
  try {
    await deactivateOffline();
  } finally {
    await finoraSession().clearStorageData({ storages: ["cookies"] });
  }
}

/** Development-only technical log: method, path, outcome, timing. Never headers, cookies or bodies. */
function logRequest(request: FinoraRequest, result: FinoraResponse, started: number): void {
  if (app.isPackaged) return;
  const outcome = result.ok
    ? String(result.status)
    : `${result.failure}${"status" in result && result.status ? ` ${result.status}` : ""}`;
  console.info(`[finora] ${request.method} ${request.path} → ${outcome} (${Date.now() - started}ms)`);
}
