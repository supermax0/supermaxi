import type { FinoraFormRequest, FinoraRequest, FinoraResponse } from "@shared/ipc";
import type { ZodType, ZodTypeDef } from "zod";
import { desktopBridge } from "@/services/bridge";
import { errorFromResponse, FinoraApiError } from "./errors";
import { reportTransportOutcome } from "./transportEvents";
import { isCustomerCommand } from "@shared/customerRecovery";
import { isStockCommand } from "@shared/stockRecovery";
import { auditBase, isAuditCommand } from "@shared/inventoryAudit";

/**
 * Sends one request through the main-process transport and validates the
 * payload. Components never call this directly — only `finora.*` modules do.
 */
export function settle<T>(
  label: string,
  response: FinoraResponse,
  schema: ZodType<T, ZodTypeDef, unknown>,
  observeConnectivity = true,
): T {
  if (!response.ok) {
    const error = errorFromResponse(response);
    reportTransportOutcome(error);
    if (import.meta.env.DEV)
      console.debug("[finora]", label, error.kind, error.status ?? "", error.detail ?? "");
    throw error;
  }
  if (observeConnectivity)
    reportTransportOutcome(response.source === "offline" ? new FinoraApiError("network") : null);
  const parsed = schema.safeParse(response.data);
  if (!parsed.success) {
    if (import.meta.env.DEV) console.debug("[finora] schema mismatch", label, parsed.error.issues);
    throw new FinoraApiError("invalid_response", { status: response.status, detail: parsed.error.message });
  }
  return parsed.data;
}

/** Multipart POST (FINORA forms with files) — same error layer and validation as finoraCall. */
export async function finoraForm<T>(
  request: FinoraFormRequest,
  schema: ZodType<T, ZodTypeDef, unknown>,
): Promise<T> {
  return settle(`POST ${request.path}`, await desktopBridge().finora.submitForm(request), schema);
}

export async function finoraCall<T>(
  request: FinoraRequest,
  schema: ZodType<T, ZodTypeDef, unknown>,
): Promise<T> {
  if (isCustomerCommand(request) && !desktopBridge().customerRecovery)
    throw new FinoraApiError("refused", {
      message: "أعد تشغيل نسخة FINORA المحدثة لتفعيل الحفظ الآمن لطلبات العملاء",
    });
  if (isStockCommand(request) && !desktopBridge().stockRecovery)
    throw new FinoraApiError("refused", {
      message: "أعد تشغيل FINORA المحدث لتفعيل الحفظ الآمن لعمليات المخزون",
    });
  const response = await desktopBridge().finora.request(request);
  // Reading the encrypted local journal does not establish server reachability.
  // Reporting it as online would invalidate (and cancel) the same query while
  // cached audit reads report offline, producing an endless refetch cycle.
  const localOnly =
    request.path === `${auditBase}/local/status` ||
    (request.path === `${auditBase}/local/actions` &&
      request.body &&
      typeof request.body === "object" &&
      !Array.isArray(request.body) &&
      request.body.operation !== "retry");
  const result = settle(`${request.method} ${request.path}`, response, schema, !localOnly);
  if (isCustomerCommand(request)) await acknowledgeCustomerCommand(request, response);
  if (
    isAuditCommand(request) ||
    (request.path === `${auditBase}/local/actions` &&
      request.body &&
      typeof request.body === "object" &&
      !Array.isArray(request.body) &&
      request.body.operation === "retry")
  ) {
    if (response.ok && response.source !== "offline") {
      if (!response.auditCommandScope || !response.auditCommandPath)
        throw new FinoraApiError("invalid_response", {
          message: "تعذر تثبيت تأكيد الجرد محلياً؛ راجع طلبات الجرد المحفوظة",
        });
      const body = request.body as Record<string, unknown>;
      const ack = await desktopBridge().finora.request({
        method: "POST",
        path: `${auditBase}/local/actions`,
        body: {
          operation: "ack",
          key: String(body.idempotency_key ?? body.key),
          path: response.auditCommandPath,
          scope: response.auditCommandScope,
        },
      });
      if (!ack.ok)
        throw new FinoraApiError("server", {
          message: "وصل تأكيد الخادم؛ تعذر إغلاق الطلب المحلي، راجعه من سجل المزامنة",
        });
    }
  }
  return result;
}

export async function acknowledgeCustomerCommand(
  request: FinoraRequest,
  response: FinoraResponse,
): Promise<void> {
  const body = request.body;
  if (body && typeof body === "object" && !Array.isArray(body) && typeof body.idempotency_key === "string") {
    try {
      const bridge = desktopBridge().customerRecovery;
      if (bridge) {
        if (!response.ok || !response.customerCommandScope) throw Error("missing command acknowledgement");
        await bridge.acknowledge({
          key: body.idempotency_key,
          path: request.path,
          scope: response.customerCommandScope,
        });
      }
    } catch {
      throw new FinoraApiError("server", {
        message: "وصل تأكيد الخادم، وتعذّر إغلاق طلب الحفظ المحلي؛ راجعه من طلبات الحفظ المحفوظة",
      });
    }
  }
}
