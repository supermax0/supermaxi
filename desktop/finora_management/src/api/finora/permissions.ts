import { z } from "zod";
import { finoraCall } from "./transport";

/** Permissions administration — modules/desktop_api/permissions.py over utils/permission_admin (general admin only). */
const BASE = "/api/v1/desktop/permissions";
const ok = <T extends z.ZodRawShape>(shape: T) => z.object({ ok: z.literal(true), ...shape });

const catalogGroup = z.object({
  key: z.string(),
  title: z.string(),
  permissions: z.array(z.object({ name: z.string(), label: z.string(), sensitive: z.boolean() })),
});
export type PermissionGroup = z.infer<typeof catalogGroup>;

const employeeRow = z.object({
  id: z.number().int(),
  name: z.string(),
  username: z.string().nullable().optional(),
  role: z.string().nullable(),
  active: z.boolean(),
  branch: z.string(),
  roles: z.array(z.string()),
  overrides: z.number().int(),
  is_admin: z.boolean(),
});
export type PermissionEmployee = z.infer<typeof employeeRow>;

const effective = z.object({
  name: z.string(),
  group: z.string(),
  allowed: z.boolean(),
  source: z.enum(["admin", "deny", "grant", "role", "none"]),
  override: z.enum(["grant", "deny"]).nullable(),
  roles: z.array(z.string()),
});
export type EffectivePermission = z.infer<typeof effective>;

const detail = ok({
  employee: z.object({
    id: z.number().int(),
    name: z.string(),
    role: z.string().nullable(),
    active: z.boolean(),
    is_admin: z.boolean(),
  }),
  role_ids: z.array(z.number().int()),
  permissions: z.array(effective),
});

const roleRow = z.object({
  id: z.number().int(),
  name: z.string(),
  description: z.string(),
  permissions: z.array(z.string()),
  employees: z.number().int(),
});
export type PermissionRole = z.infer<typeof roleRow>;
const roleTemplate = z.object({
  key: z.string(),
  name: z.string(),
  description: z.string(),
  permissions: z.array(z.string()),
  installed: z.boolean(),
});
export type RoleTemplate = z.infer<typeof roleTemplate>;
const roles = ok({ rows: z.array(roleRow) });

export type OverrideChange = "grant" | "deny" | null;

export const permissions = {
  catalog: () =>
    finoraCall({ method: "GET", path: `${BASE}/catalog` }, ok({ groups: z.array(catalogGroup) })),
  employees: () =>
    finoraCall({ method: "GET", path: `${BASE}/employees` }, ok({ rows: z.array(employeeRow) })),
  employee: (id: number) => finoraCall({ method: "GET", path: `${BASE}/employees/${id}` }, detail),
  setOverrides: (id: number, changes: Record<string, OverrideChange>, note = "") =>
    finoraCall(
      { method: "POST", path: `${BASE}/employees/${id}/overrides`, body: { changes, note } },
      detail,
    ),
  setRoles: (id: number, roleIds: number[]) =>
    finoraCall(
      { method: "POST", path: `${BASE}/employees/${id}/roles`, body: { role_ids: roleIds } },
      detail,
    ),
  roleTemplates: () =>
    finoraCall({ method: "GET", path: `${BASE}/role-templates` }, ok({ rows: z.array(roleTemplate) })),
  installTemplates: (keys: string[]) =>
    finoraCall(
      { method: "POST", path: `${BASE}/role-templates/install`, body: { keys } },
      ok({
        created: z.array(z.string()),
        skipped: z.array(z.string()),
        rows: z.array(roleRow),
        templates: z.array(roleTemplate),
      }),
    ),
  roles: () => finoraCall({ method: "GET", path: `${BASE}/roles` }, roles),
  saveRole: (id: number | null, input: { name: string; description: string; permissions: string[] }) =>
    finoraCall(
      { method: "POST", path: id ? `${BASE}/roles/${id}` : `${BASE}/roles`, body: { ...input } },
      roles,
    ),
  deleteRole: (id: number) =>
    finoraCall({ method: "POST", path: `${BASE}/roles/${id}/delete`, body: {} }, roles),
  audit: () =>
    finoraCall(
      { method: "GET", path: `${BASE}/audit` },
      ok({
        rows: z.array(
          z.object({
            id: z.number().int(),
            at: z.string(),
            by: z.string(),
            action: z.string(),
            summary: z.string(),
            payload: z.record(z.unknown()),
          }),
        ),
      }),
    ),
};
