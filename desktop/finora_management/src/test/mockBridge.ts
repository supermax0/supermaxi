import type {
  DesktopConfig,
  FinoraDesktopBridge,
  FinoraFormRequest,
  FinoraRequest,
  FinoraResponse,
  WindowState,
} from "@shared/ipc";
import { vi } from "vitest";
import { isCustomerCommand } from "@shared/customerRecovery";

export const SESSION_PAYLOAD = {
  user: { id: 7, name: "سارة", username: "sara", role: "admin" },
  tenant: { id: 1, slug: "acme", name: "شركة أكمي", business_type: "general" },
  branch: { id: 2, name: "الفرع الرئيسي" },
  roles: ["admin"],
  permissions: ["can_see_orders", "manage_orders", "brand_new_permission"],
  session_max_age_seconds: 604800,
};

export type RequestHandler = (request: FinoraRequest) => FinoraResponse | Promise<FinoraResponse>;

/** Test double for the preload bridge; `handler` decides how "FINORA" answers. */
export function installMockBridge(handler: RequestHandler) {
  let autoStart = false;
  let config: DesktopConfig = {
    serverUrl: "http://finora.test",
    lastTenantSlug: null,
    lastUsername: null,
    appVersion: "0.0.0-test",
  };
  const windowState: WindowState = { maximized: false, focused: true };
  const bridge = {
    customerRecovery: {
      list: vi.fn(async () => ({ available: true, items: [] })),
      retry: vi.fn(async (): Promise<never> => {
        throw Error("Test must provide the saved request");
      }),
      acknowledge: vi.fn(async () => undefined),
    },
    window: {
      minimize: vi.fn(async () => undefined),
      toggleMaximize: vi.fn(async () => {
        windowState.maximized = !windowState.maximized;
        return { ...windowState };
      }),
      close: vi.fn(async () => undefined),
      getState: vi.fn(async () => ({ ...windowState })),
      onState: vi.fn(() => () => undefined),
    },
    finora: {
      request: vi.fn(async (request: FinoraRequest) => {
        const response = await handler(request);
        return response.ok && isCustomerCommand(request)
          ? { ...response, customerCommandScope: "a".repeat(64) }
          : response;
      }),
      submitForm: vi.fn(async (request: FinoraFormRequest) =>
        handler({ method: "POST", path: request.path, body: Object.fromEntries(request.fields) }),
      ),
      clearSession: vi.fn(async () => undefined),
    },
    print: { open: vi.fn(async () => undefined) },
    reports: { export: vi.fn(async () => ({ saved: true, path: "C:/report.xlsx" })) },
    app: {
      openInFinora: vi.fn(async () => undefined),
      getAutoStart: vi.fn(async () => autoStart),
      setAutoStart: vi.fn(async (enabled: boolean) => {
        autoStart = enabled;
        return autoStart;
      }),
    },
    config: {
      get: vi.fn(async () => config),
      setServer: vi.fn(async (serverUrl: string) => {
        config = { ...config, serverUrl };
        return config;
      }),
      rememberIdentity: vi.fn(async (identity: { tenantSlug: string; username: string }) => {
        config = { ...config, lastTenantSlug: identity.tenantSlug, lastUsername: identity.username };
        return config;
      }),
    },
  } satisfies FinoraDesktopBridge;
  window.finoraDesktop = bridge;
  return bridge;
}

export function removeMockBridge(): void {
  delete window.finoraDesktop;
}
