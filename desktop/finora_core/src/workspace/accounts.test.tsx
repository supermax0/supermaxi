import { fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { makeSource, renderWithSource } from "../test/render";
import type { AccountView, SupportIssue } from "../data/accounts";
import type { Approval } from "../data/schemas";
import { useUi } from "../state/ui";
import { AccountSetup } from "./AccountSetup";
import { SupportIssues } from "../activity/SupportIssues";
import { ApprovalCard } from "../approvals/ApprovalCard";

const account: AccountView = {
  customerId: "7",
  tenantSlug: "flowers-a",
  linked: true,
  error: null,
  profiles: [{ key: "flowers", label: "محل ورد وهدايا", needs: "طلبات المناسبات والمخزون" }],
  permissionPresets: [{ key: "sales", label: "مبيعات" }],
  account: {
    tenantSlug: "flowers-a",
    companyName: "ورد الربيع",
    businessType: "starter_business",
    version: "v1",
    features: [{ key: "reports", label: "التقارير", available: true, enabled: true, protected: false }],
    employees: [
      { id: 1, name: "المالك", username: "admin", owner: true, active: true, permissions: {}, roleIds: [] },
      { id: 2, name: "سارة", username: "sara", owner: false, active: true, permissions: {}, roleIds: [] },
    ],
    roles: [{ id: 1, name: "الاستقبال", permissions: ["clinics.reception.view"] }],
  },
};
const approval: Approval = {
  id: "ap-setup",
  conversationId: "c6",
  customerName: "ورد الربيع",
  action: "ترتيب حساب العميل",
  reason: "حسب طلب العميل",
  oldValue: "الإعدادات الحالية",
  newValue: "محل ورد",
  agentLimit: null,
  risk: "high",
  status: "pending",
  createdAt: "2026-10-04T13:00:00Z",
  planHash: "a".repeat(64),
  preview: {
    accountScope: { tenantSlug: "flowers-a", label: "هذا الحساب فقط" },
    employeeId: 2,
    employeeName: "سارة",
    permissionDiff: [{ key: "can_see_financial", before: true, after: false }],
    roleChanges: { before: [], after: ["الاستقبال"] },
  },
};

describe("customer-bound setup", () => {
  it("requests review using only the conversation, excluding the owner from staff choices", async () => {
    const src = makeSource();
    vi.spyOn(src, "getAccount").mockResolvedValue(account);
    const propose = vi.spyOn(src, "proposeAccount").mockResolvedValue(approval);
    const link = vi.spyOn(src, "linkAccount");
    renderWithSource(<AccountSetup conversationId="c6" tenantSlug="flowers-a" />, src);
    fireEvent.click(screen.getByRole("button", { name: "ترتيب حساب العميل" }));
    fireEvent.click(await screen.findByRole("button", { name: /محل ورد وهدايا/ }));
    await waitFor(() =>
      expect(propose).toHaveBeenCalledWith("c6", { operation: "profile", profile: "flowers" }),
    );
    expect(useUi.getState().overlay).toBe("activity");
    expect(link).not.toHaveBeenCalled();
    expect(screen.queryByRole("option", { name: /المالك/ })).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("موظف حساب العميل"), { target: { value: "2" } });
    fireEvent.change(screen.getByLabelText("الدور التفصيلي للموظف"), { target: { value: "1" } });
    fireEvent.click(screen.getByRole("button", { name: "مراجعة صلاحيات الموظف" }));
    await waitFor(() =>
      expect(propose).toHaveBeenCalledWith("c6", {
        operation: "permissions",
        employee_id: 2,
        permission_preset: "sales",
        role_ids: [1],
      }),
    );
  });

  it("does not link a client-claimed account until ownership evidence is confirmed", async () => {
    const src = makeSource();
    vi.spyOn(src, "getAccount").mockResolvedValue({
      ...account,
      account: null,
      linked: false,
      tenantSlug: null,
    });
    const link = vi.spyOn(src, "linkAccount").mockResolvedValue(account);
    renderWithSource(<AccountSetup conversationId="c6" tenantSlug={null} />, src);
    fireEvent.click(screen.getByRole("button", { name: "ترتيب حساب العميل" }));
    fireEvent.change(await screen.findByLabelText("معرّف شركة العميل"), { target: { value: "flowers-a" } });
    fireEvent.change(screen.getByLabelText("دليل التحقق من الملكية"), {
      target: { value: "verified via registered company channel" },
    });
    const button = screen.getByRole("button", { name: /ربط الحساب/ });
    expect(button).toBeDisabled();
    fireEvent.click(screen.getByRole("checkbox"));
    fireEvent.click(button);
    await waitFor(() =>
      expect(link).toHaveBeenCalledWith("c6", {
        tenantSlug: "flowers-a",
        ownershipVerified: true,
        reason: "verified via registered company channel",
      }),
    );
  });

  it("shows actual employee, roles and before/after permissions in the signed approval", async () => {
    const src = makeSource();
    const decide = vi
      .spyOn(src, "decideApproval")
      .mockResolvedValue({ approval: { ...approval, status: "approved" }, credentials: null });
    renderWithSource(<ApprovalCard approval={approval} />, src);
    const plan = screen.getByLabelText("الخطة المقترحة");
    expect(plan).toHaveTextContent("flowers-a");
    expect(plan).toHaveTextContent("سارة");
    expect(plan).toHaveTextContent("البيانات المالية: مسموح ← غير مسموح");
    expect(plan).toHaveTextContent("الاستقبال");
    fireEvent.click(screen.getByRole("button", { name: "موافقة" }));
    await waitFor(() => expect(decide).toHaveBeenCalledWith("ap-setup", "approved", approval.planHash));
  });

  it("opens the affected conversation from a reported issue and records resolution", async () => {
    const issue: SupportIssue = {
      id: "issue-1",
      customerName: "ورد الربيع",
      conversationId: "c6",
      tenantSlug: "flowers-a",
      kind: "bug",
      title: "العميل أبلغ عن خلل",
      details: "التقارير ما تشتغل",
      status: "open",
      verified: false,
      at: "2026-10-04T13:00:00Z",
    };
    const src = makeSource();
    vi.spyOn(src, "listSupportIssues").mockResolvedValue([issue]);
    const resolve = vi.spyOn(src, "resolveSupportIssue").mockResolvedValue(undefined);
    renderWithSource(<SupportIssues />, src);
    expect(await screen.findByText("التقارير ما تشتغل")).toBeInTheDocument();
    expect(screen.getByText(/بلاغ أو طلب يحتاج تحققاً/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "محادثة العميل" }));
    expect(useUi.getState().selectedConversationId).toBe("c6");
    fireEvent.click(screen.getByRole("button", { name: "تمت المعالجة" }));
    await waitFor(() => expect(resolve).toHaveBeenCalledWith("issue-1"));
  });
});
