import { fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ApprovalCard } from "../approvals/ApprovalCard";
import { projectSchema, type Approval } from "../data/schemas";
import fixture from "../test/project-fixture.json";
import { makeSource, renderWithSource } from "../test/render";
import { ProjectPlan } from "./ProjectPlan";

const project = projectSchema.parse(fixture);
const quote: Approval = {
  id: "project-1",
  conversationId: "1",
  customerName: "عميل مشروع",
  action: "اعتماد عرض تطوير",
  reason: "العميل وافق على النطاق",
  oldValue: "غير معتمد",
  newValue: "عرض تقديري",
  agentLimit: null,
  risk: "high",
  status: "pending",
  planHash: "a".repeat(64),
  createdAt: "2026-10-05T10:00:00Z",
  preview: { project, projectAction: "publish_project_quote", depositAmount: "200000.00" },
};

describe("custom project review", () => {
  it("shows workflow branches, actors and acceptance while retaining legacy plans", () => {
    const withFlow = projectSchema.parse({
      ...fixture,
      brief: {
        ...fixture.brief,
        workflows: [
          {
            id: "reserve",
            name: "مسار حجز الموعد",
            trigger: "اختيار موعد",
            steps: [
              {
                id: "choose",
                pageId: "venues",
                role: "زبون",
                action: "يختار ملعباً",
                result: "وقت متاح",
                next: [{ stepId: "finish", condition: "الموعد متاح" }],
              },
              {
                id: "finish",
                pageId: "booking",
                role: "مالك",
                action: "يراجع الحجز",
                result: "حجز مؤكد",
                next: [],
              },
            ],
            acceptance: ["لا يتكرر الموعد"],
          },
        ],
      },
    });
    renderWithSource(<ProjectPlan project={withFlow} />);
    expect(screen.getByText("مسارات العمل · 1")).toBeInTheDocument();
    expect(screen.getByText("الموعد متاح ← الخطوة 2")).toBeInTheDocument();
    expect(screen.getByText("قبول المسار: لا يتكرر الموعد")).toBeInTheDocument();
    expect(screen.getByText(/تفاصيل الصفحة أو الخطة كاملة تُرسل بطلبه/)).toBeInTheDocument();
    expect(project.brief.workflows).toBeUndefined();
  });
  it("shows page links and blocks approval of unsaved commercial edits", async () => {
    const revise = vi.fn().mockResolvedValue({ ...quote, id: "project-2" });
    const src = Object.assign(makeSource(), { reviseProjectApproval: revise });
    renderWithSource(<ApprovalCard approval={quote} />, src);
    expect(screen.getByText(/ترتبط بـ: الحجز/)).toBeInTheDocument();
    expect(screen.getByText(/مقترحة/)).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("المبلغ الإجمالي"), { target: { value: "1200000" } });
    await waitFor(() => expect(screen.getByRole("button", { name: "موافقة" })).toBeDisabled());
    fireEvent.click(screen.getByRole("button", { name: "حفظ المراجعة" }));
    await waitFor(() =>
      expect(revise).toHaveBeenCalledWith(quote.id, quote.planHash, {
        terms: { ...project.terms, amount: 1200000 },
      }),
    );
  });
  it("requires the owner's deposit verification and reference before approval", async () => {
    const payment: Approval = {
      ...quote,
      preview: {
        ...quote.preview,
        project: { ...project, phase: "deposit_review", paymentClaim: { messageId: "9", text: "دفعت" } },
        projectAction: "confirm_project_deposit",
      },
    };
    const revise = vi.fn().mockResolvedValue({ ...payment, id: "payment-2" });
    const src = Object.assign(makeSource(), { reviseProjectApproval: revise });
    renderWithSource(<ApprovalCard approval={payment} />, src);
    await waitFor(() => expect(screen.getByRole("button", { name: "موافقة" })).toBeDisabled());
    fireEvent.change(screen.getByLabelText("مرجع وصول الدفعة"), { target: { value: "verified-bank-ref" } });
    fireEvent.click(screen.getByRole("checkbox"));
    fireEvent.click(screen.getByRole("button", { name: "حفظ المراجعة" }));
    await waitFor(() =>
      expect(revise).toHaveBeenCalledWith(payment.id, payment.planHash, {
        paymentReference: "verified-bank-ref",
        paymentVerified: true,
      }),
    );
  });
});
