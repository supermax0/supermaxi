import { z } from "zod";

export const supportIssueSchema = z.object({
  id: z.string(),
  customerName: z.string(),
  conversationId: z.string(),
  tenantSlug: z.string().nullable(),
  kind: z.string(),
  title: z.string(),
  details: z.string(),
  status: z.enum(["open", "resolved"]),
  verified: z.boolean(),
  at: z.string().datetime({ offset: true }),
});
export type SupportIssue = z.infer<typeof supportIssueSchema>;
export const accountSchema = z.object({
  customerId: z.string(),
  tenantSlug: z.string().nullable(),
  linked: z.boolean(),
  error: z.string().nullable(),
  profiles: z.array(z.object({ key: z.string(), label: z.string(), needs: z.string() })),
  permissionPresets: z.array(z.object({ key: z.string(), label: z.string() })),
  account: z
    .object({
      tenantSlug: z.string(),
      companyName: z.string(),
      businessType: z.string(),
      version: z.string(),
      features: z.array(
        z.object({
          key: z.string(),
          label: z.string(),
          enabled: z.boolean(),
          available: z.boolean(),
          protected: z.boolean(),
        }),
      ),
      employees: z.array(
        z.object({
          id: z.number().int(),
          name: z.string(),
          username: z.string(),
          owner: z.boolean(),
          active: z.boolean(),
          permissions: z.record(z.boolean()),
          roleIds: z.array(z.number().int()),
        }),
      ),
      roles: z.array(z.object({ id: z.number().int(), name: z.string(), permissions: z.array(z.string()) })),
    })
    .nullable(),
});
export type AccountView = z.infer<typeof accountSchema>;
export interface AccountProposal {
  operation: "profile" | "feature" | "permissions";
  profile?: string;
  feature?: string;
  enabled?: boolean;
  employee_id?: number;
  permission_preset?: string;
  role_ids?: number[];
  reason?: string;
}
export interface AccountLink {
  tenantSlug: string;
  ownershipVerified: boolean;
  reason: string;
}
