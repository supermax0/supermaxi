import { desktopBridge } from "@/services/bridge";
import { toFinoraError } from "./errors";
import { sessionEnvelopeSchema, signOutSchema, type FinoraSession } from "./schemas";
import { finoraCall } from "./transport";

export interface SignInInput {
  tenantSlug: string;
  username: string;
  password: string;
}

export const auth = {
  /** POST /api/v1/desktop/auth/login — establishes the FINORA staff session (cookie stays in main). */
  async signIn(input: SignInInput): Promise<FinoraSession> {
    const session = await finoraCall(
      {
        method: "POST",
        path: "/api/v1/desktop/auth/login",
        body: { tenant_slug: input.tenantSlug, username: input.username, password: input.password },
      },
      sessionEnvelopeSchema,
    );
    await desktopBridge().config.rememberIdentity({
      tenantSlug: session.tenant.slug,
      username: session.user.username,
    });
    return session;
  },

  /** GET /api/v1/desktop/auth/session — current user, tenant, branch, roles and permissions. */
  session(): Promise<FinoraSession> {
    return finoraCall(
      { method: "GET", path: "/api/v1/desktop/auth/session", timeoutMs: 10_000 },
      sessionEnvelopeSchema,
    );
  },

  /** POST /api/v1/desktop/auth/logout, then drop the local cookie jar even if the server was unreachable. */
  async signOut(): Promise<void> {
    try {
      await finoraCall({ method: "POST", path: "/api/v1/desktop/auth/logout" }, signOutSchema);
    } catch (error) {
      // An expired session or an unreachable server still ends in a local sign-out.
      const failure = toFinoraError(error);
      if (!failure.endsSession && !failure.isConnectivity) throw failure;
    } finally {
      await desktopBridge().finora.clearSession();
    }
  },
};
