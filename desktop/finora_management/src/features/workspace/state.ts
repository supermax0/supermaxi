import { z } from "zod";
import { create } from "zustand";
import type { FinoraSession } from "@/api/finora";
import { useSession } from "@/stores/session";
import { WINDOW_IDS, WINDOWS, type WindowId } from "@/windows/registry";

// Recovery stores navigation metadata only. Never persist form values or financial commands here.
export const targetSchema = z
  .object({
    window: z.enum(WINDOW_IDS),
    tab: z.string().max(30).optional(),
    entityId: z.number().int().positive().optional(),
    period: z
      .enum(["today", "yesterday", "this_month", "this_week", "this_year", "last_month", "custom"])
      .optional(),
    dateFrom: z
      .string()
      .regex(/^\d{4}-\d{2}-\d{2}$/)
      .optional(),
    dateTo: z
      .string()
      .regex(/^\d{4}-\d{2}-\d{2}$/)
      .optional(),
    page: z.number().int().min(1).max(1_000_000).optional(),
    scroll: z.number().min(0).max(10_000_000).optional(),
  })
  .strict();
export type WorkspaceTarget = z.infer<typeof targetSchema>;
export const WIDGETS = [
  "sales",
  "orders",
  "attention",
  "receivables",
  "quick",
  "tasks",
  "resume",
  "assistant",
  "activity",
] as const;
export type WidgetId = (typeof WIDGETS)[number];
export const ACTIONS = [
  "order",
  "sale",
  "expense",
  "receipt",
  "audit",
  "search",
  "product",
  "customer",
] as const;
export type ActionId = (typeof ACTIONS)[number];
const prefsSchema = z.object({
  compact: z.boolean().default(false),
  visible: z.array(z.enum(WIDGETS)).default([...WIDGETS]),
  order: z.array(z.enum(WIDGETS)).default([...WIDGETS]),
  actions: z.array(z.enum(ACTIONS)).default([...ACTIONS]),
  home: z.enum(["workspace", ...WINDOW_IDS]).default("workspace"),
  remember: z.boolean().default(true),
  suggestions: z.boolean().default(true),
});
export type WorkspacePreferences = z.infer<typeof prefsSchema>;
export const defaultPreferences = (): WorkspacePreferences => prefsSchema.parse({});
const recentSchema = z.object({ target: targetSchema, at: z.number() });
export type RecentWork = z.infer<typeof recentSchema>;
const storedSchema = z.object({
  recent: z.array(recentSchema).max(12),
  saved: z.array(targetSchema).max(WINDOW_IDS.length),
  visits: z.record(z.number().int().nonnegative()),
  dismissed: z.array(z.enum(WINDOW_IDS)),
});
const emptyHistory = () => ({
  recent: [] as RecentWork[],
  saved: [] as WorkspaceTarget[],
  visits: {} as Record<string, number>,
  dismissed: [] as WindowId[],
});
const key = (identity: string, suffix: string) => `finora:workspace:v1:${identity}:${suffix}`;
function read<T>(storageKey: string, schema: z.ZodType<T, z.ZodTypeDef, unknown>, fallback: T): T {
  try {
    const value = window.localStorage.getItem(storageKey);
    if (!value) return fallback;
    const parsed = schema.safeParse(JSON.parse(value));
    return parsed.success ? parsed.data : fallback;
  } catch {
    return fallback;
  }
}
function write(storageKey: string, value: unknown): boolean {
  try {
    window.localStorage.setItem(storageKey, JSON.stringify(value));
    return true;
  } catch {
    return false;
  }
}
export function sessionScope(session: FinoraSession | null): string {
  return session
    ? JSON.stringify([
        session.tenant.slug,
        session.tenant.id,
        session.user.id,
        session.branch_scope,
        session.branch?.id,
        [...session.permissions].sort(),
      ])
    : "";
}
export function allowedWindow(id: WindowId, session: FinoraSession | null): boolean {
  if (!session || !Object.hasOwn(WINDOWS, id)) return false;
  if (id === "products" && session.permissions.includes("inventory.audit.view")) return true;
  const permission = WINDOWS[id].permission;
  return !permission || session.permissions.includes(permission);
}
interface State {
  identity: string;
  scope: string;
  ready: boolean;
  prefs: WorkspacePreferences;
  recent: RecentWork[];
  saved: WorkspaceTarget[];
  visits: Record<string, number>;
  dismissed: WindowId[];
  requests: Partial<Record<WindowId, { target: WorkspaceTarget; action?: ActionId }>>;
  activate(server: string, session: FinoraSession): void;
  reset(): void;
  configure(prefs: WorkspacePreferences): boolean;
  record(target: WorkspaceTarget, visit?: boolean): void;
  dismiss(id: WindowId): void;
  navigate(target: WorkspaceTarget, action?: ActionId): void;
  consume(id?: WindowId): void;
}
export const useWorkspace = create<State>()((set, get) => ({
  identity: "",
  scope: "",
  ready: false,
  prefs: defaultPreferences(),
  ...emptyHistory(),
  requests: {},
  activate(server, session) {
    const identity = JSON.stringify([server, session.tenant.slug, session.tenant.id, session.user.id]);
    const scope = JSON.stringify([identity, session.branch_scope, session.branch?.id]);
    if (get().scope === scope) return;
    const prefs = read(key(identity, "preferences"), prefsSchema, defaultPreferences());
    const history = read(key(scope, "history"), storedSchema, emptyHistory());
    set({ identity, scope, prefs, ...history, requests: {}, ready: true });
  },
  reset() {
    set({
      identity: "",
      scope: "",
      ready: false,
      prefs: defaultPreferences(),
      ...emptyHistory(),
      requests: {},
    });
  },
  configure(prefs) {
    const next = prefsSchema.parse(prefs);
    if (!get().ready || !write(key(get().identity, "preferences"), next)) return false;
    set({ prefs: next });
    if (!next.remember) {
      const history = emptyHistory();
      write(key(get().scope, "history"), history);
      set(history);
    }
    return true;
  },
  record(target, visit = false) {
    const state = get();
    if (!state.ready || !state.prefs.remember) return;
    const parsed = targetSchema.safeParse(target);
    if (!parsed.success) return;
    const recent = [
      { target: parsed.data, at: Date.now() },
      ...state.recent.filter((row) => row.target.window !== target.window),
    ].slice(0, 12);
    const saved = [parsed.data, ...state.saved.filter((row) => row.window !== target.window)].slice(
      0,
      WINDOW_IDS.length,
    );
    const visits = visit
      ? { ...state.visits, [target.window]: (state.visits[target.window] ?? 0) + 1 }
      : state.visits;
    const next = { recent, saved, visits, dismissed: state.dismissed };
    // Failure never blocks navigation; customization has explicit save failure feedback.
    write(key(state.scope, "history"), next);
    set(next);
  },
  dismiss(id) {
    const state = get();
    const dismissed = [...new Set([...state.dismissed, id])];
    write(key(state.scope, "history"), {
      recent: state.recent,
      saved: state.saved,
      visits: state.visits,
      dismissed,
    });
    set({ dismissed });
  },
  navigate(target, action) {
    set({ requests: { ...get().requests, [target.window]: { target: targetSchema.parse(target), action } } });
  },
  consume(id) {
    if (!id) {
      set({ requests: {} });
      return;
    }
    const requests = Object.fromEntries(Object.entries(get().requests).filter(([window]) => window !== id));
    set({ requests });
  },
}));

// Clear the previous identity synchronously, before React paints the next account/branch.
useSession.subscribe((current, previous) => {
  if (sessionScope(current.session) === sessionScope(previous.session)) return;
  const workspace = useWorkspace.getState();
  workspace.consume();
  if (!current.session) {
    workspace.reset();
    return;
  }
  if (workspace.identity) {
    const [server] = JSON.parse(workspace.identity) as [string];
    workspace.activate(server, current.session);
  }
});
