import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApprovalBar, ApprovalCard } from "../approvals/ApprovalCard";
import { CredentialsDialog } from "../approvals/CredentialsDialog";
import { MergeSuggestions } from "../approvals/MergeSuggestions";
import type { Approval, MergeSuggestion, ShadowProposal } from "../data/schemas";
import { CoreError, type DataSource } from "../data/source";
import { useUi } from "../state/ui";
import { makeSource, renderWithSource } from "../test/render";
import { ChatPanel } from "./ChatPanel";
import { ConversationList } from "./ConversationList";
import { CustomerPanel } from "./CustomerPanel";

beforeEach(() => {
  useUi.setState({
    view: "workspace",
    selectedConversationId: null,
    channel: "all",
    filter: "all",
    search: "",
    customerPanelOpen: true,
  });
});

describe("ConversationList", () => {
  it("renders conversations, unread badges and pre-selects the most recent one", async () => {
    renderWithSource(<ConversationList />);
    const list = await screen.findByRole("list", { name: "المحادثات" });
    expect(within(list).getAllByRole("button").length).toBe(7);
    expect(screen.getByLabelText("2 غير مقروءة")).toBeInTheDocument();
    await waitFor(() => expect(useUi.getState().selectedConversationId).toBe("c1"));
    expect(within(list).getAllByRole("button")[0]).toHaveAttribute("aria-current", "true");
  });

  it("filters by channel tab", async () => {
    renderWithSource(<ConversationList />);
    await screen.findByRole("list", { name: "المحادثات" });
    fireEvent.click(screen.getByRole("tab", { name: /Facebook/ }));
    await waitFor(() => expect(screen.queryByText("أحمد علي")).not.toBeInTheDocument());
    expect(screen.getByText("د. سارة")).toBeInTheDocument();
  });

  it("shows an empty state for searches without results", async () => {
    renderWithSource(<ConversationList />);
    await screen.findByRole("list", { name: "المحادثات" });
    fireEvent.change(screen.getByLabelText("البحث في المحادثات"), { target: { value: "zzz-none" } });
    expect(await screen.findByText("لا توجد نتائج")).toBeInTheDocument();
  });

  it("shows a classified error with retry", async () => {
    const src = makeSource();
    const failing: DataSource = Object.assign(Object.create(src) as DataSource, {
      listConversations: vi.fn().mockRejectedValue(new CoreError("NETWORK_ERROR", "تعذر الاتصال بالخادم")),
    });
    renderWithSource(<ConversationList />, failing);
    expect(await screen.findByText("تعذر الاتصال بالخادم")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /إعادة المحاولة/ })).toBeInTheDocument();
  });
});

describe("ChatPanel human takeover", () => {
  it("locks the composer while FINORA CORE is active, then allows manual replies after takeover", async () => {
    useUi.setState({ selectedConversationId: "c1" });
    renderWithSource(<ChatPanel />);
    expect(await screen.findByText("FINORA CORE — Active", { selector: "strong" })).toBeInTheDocument();
    expect(screen.queryByLabelText("نص الرسالة")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /استلام المحادثة/ }));
    const box = await screen.findByLabelText("نص الرسالة");
    fireEvent.change(box, { target: { value: "أهلاً دكتور، معك فريق FINORA" } });
    fireEvent.keyDown(box, { key: "Enter" });
    expect(await screen.findByText("أهلاً دكتور، معك فريق FINORA")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /إعادة تشغيل FINORA CORE/ })).toBeInTheDocument();
  });

  it("Shift+Enter does not send", async () => {
    useUi.setState({ selectedConversationId: "c6" });
    const { source } = renderWithSource(<ChatPanel />);
    const spy = vi.spyOn(source, "sendMessage");
    const box = await screen.findByLabelText("نص الرسالة");
    fireEvent.change(box, { target: { value: "line" } });
    fireEvent.keyDown(box, { key: "Enter", shiftKey: true });
    expect(spy).not.toHaveBeenCalled();
  });

  it("renders system events as notes, not as customer messages", async () => {
    useUi.setState({ selectedConversationId: "c1" });
    renderWithSource(<ChatPanel />);
    const note = await screen.findByRole("note");
    expect(note).toHaveTextContent("أنشأ FINORA CORE ملف العميل");
  });
});

describe("CustomerPanel", () => {
  it("shows known facts and 'غير محدد' for unknown ones instead of guessing", async () => {
    useUi.setState({ selectedConversationId: "c2" });
    renderWithSource(<CustomerPanel />);
    expect(await screen.findByText("عيادة جلدية")).toBeInTheDocument();
    // doctors / employees / country are unknown for c2
    expect(screen.getAllByText("غير محدد").length).toBeGreaterThanOrEqual(3);
  });

  it("adds an internal note", async () => {
    useUi.setState({ selectedConversationId: "c3" });
    renderWithSource(<CustomerPanel />);
    fireEvent.click(await screen.findByRole("button", { name: "إضافة ملاحظة" }));
    fireEvent.change(screen.getByLabelText("ملاحظة داخلية"), { target: { value: "اتصل صباحاً" } });
    fireEvent.click(screen.getByRole("button", { name: "حفظ" }));
    await waitFor(() => expect(screen.getByText("اتصل صباحاً")).toBeInTheDocument());
    expect(screen.getByText("داخلية")).toBeInTheDocument();
  });
});

describe("ApprovalCard", () => {
  const approval: Approval = {
    id: "ap-1",
    conversationId: null,
    customerName: "عيادة الأمل",
    action: "خصم 30%",
    reason: "طلب العميل",
    oldValue: "0%",
    newValue: "30%",
    agentLimit: "15%",
    risk: "high",
    status: "pending",
    createdAt: "2026-10-03T19:40:00Z",
  };

  it("persists the decision through the data source", async () => {
    const src = makeSource();
    const decide = vi
      .spyOn(src, "decideApproval")
      .mockResolvedValue({ approval: { ...approval, status: "approved" }, credentials: null });
    renderWithSource(<ApprovalCard approval={approval} />, src);
    expect(screen.getByText("15%")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "موافقة" }));
    await waitFor(() => expect(decide).toHaveBeenCalledWith("ap-1", "approved", null));
  });

  const trial: Approval = {
    ...approval,
    id: "ap-2",
    action: "إنشاء حساب FINORA تجريبي",
    oldValue: null,
    newValue: "حساب تجريبي 14 يوم",
    agentLimit: null,
    riskClass: "HIGH_RISK",
    planHash: "a".repeat(64),
    planVersion: 2,
    preview: {
      customer: { id: 7, name: "عيادة الأمل" },
      businessType: { key: "clinics", label: "عيادات Finora" },
      specialty: "dentistry",
      plan: { key: "basic", name: "الأساسية", priceMonthly: 25000 },
      size: { doctors: 3, employees: null, branches: 1 },
      modules: [{ key: "main", label: "الرئيسية والبيع", enabled: 12, total: 14 }],
      tenantActions: [{ action: "create_tenant", label: "إنشاء شركة جديدة «عيادة الأمل»" }],
      users: [{ username: "admin", role: "admin", credentials: "كلمة مرور مؤقتة", mustChangePassword: true }],
      subscription: { change: "trial", trialDays: 14, billing: "لا توجد فوترة أثناء التجربة" },
      contact: { phone: true, email: false },
    },
  };

  it("shows the exact account plan and approves that plan's hash", async () => {
    const src = makeSource();
    const decide = vi
      .spyOn(src, "decideApproval")
      .mockResolvedValue({ approval: { ...trial, status: "approved" }, credentials: null });
    renderWithSource(<ApprovalCard approval={trial} />, src);
    const plan = screen.getByLabelText("الخطة المقترحة");
    for (const text of [
      "عيادات Finora",
      "أسنان",
      "الأساسية",
      "3 أطباء · 1 فروع",
      "الرئيسية والبيع",
      "تجربة 14 يوم",
    ]) {
      expect(plan).toHaveTextContent(text);
    }
    expect(plan).toHaveTextContent("يغيّرها عند أول دخول");
    expect(screen.getByText("خطة محدّثة v2")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "موافقة" }));
    await waitFor(() => expect(decide).toHaveBeenCalledWith("ap-2", "approved", "a".repeat(64)));
  });

  it("never approves a detailed plan from the one-line bar", () => {
    const onDetails = vi.fn();
    renderWithSource(<ApprovalBar approval={trial} onDetails={onDetails} />);
    expect(screen.queryByRole("button", { name: "موافقة" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "مراجعة الخطة" }));
    expect(onDetails).toHaveBeenCalled();
  });

  it("shows trial credentials once and forgets them when dismissed", async () => {
    const src = makeSource();
    vi.spyOn(src, "decideApproval").mockResolvedValue({
      approval: { ...approval, status: "approved" },
      credentials: { tenantSlug: "fc7-ab12", username: "admin", password: "S3cret-once", loginUrl: null },
    });
    renderWithSource(
      <>
        <ApprovalCard approval={approval} />
        <CredentialsDialog />
      </>,
      src,
    );
    fireEvent.click(screen.getByRole("button", { name: "موافقة" }));
    expect(await screen.findByText("S3cret-once")).toBeInTheDocument();
    expect(screen.getByRole("alertdialog")).toHaveTextContent("مرة واحدة فقط");
    fireEvent.click(screen.getByRole("button", { name: /إخفاء نهائياً/ }));
    await waitFor(() => expect(screen.queryByText("S3cret-once")).not.toBeInTheDocument());
    expect(JSON.stringify(localStorage)).not.toContain("S3cret-once");
    expect(JSON.stringify(sessionStorage)).not.toContain("S3cret-once");
  });
});

describe("MergeSuggestions", () => {
  const suggestion: MergeSuggestion = {
    id: "5",
    status: "pending",
    reason: "same phone mentioned by both",
    confidence: 0.8,
    customer: {
      id: 2,
      name: "أحمد",
      stage: "new",
      identifiers: [{ kind: "facebook_psid", masked: "…1234", verified: true }],
      hasTenant: false,
    },
    candidate: {
      id: 1,
      name: "Ahmed",
      stage: "engaged",
      identifiers: [{ kind: "phone", masked: "+964*******567", verified: false }],
      hasTenant: true,
    },
    matched: [{ kind: "phone", masked: "+964*******567" }],
    mergeId: null,
    decidedBy: null,
  };

  it("shows masked identifiers and sends Merge / Keep separate / Dismiss", async () => {
    const src = makeSource();
    vi.spyOn(src, "listMergeSuggestions").mockResolvedValue([suggestion]);
    const decide = vi.spyOn(src, "decideMerge").mockResolvedValue();
    renderWithSource(<MergeSuggestions />, src);
    const card = await screen.findByRole("article", { name: /اقتراح دمج/ });
    expect(card).toHaveTextContent("+964*******567");
    expect(card).toHaveTextContent("لديه حساب FINORA");
    expect(card).not.toHaveTextContent("07701234567");
    fireEvent.click(within(card).getByRole("button", { name: "إبقاء منفصلين" }));
    await waitFor(() => expect(decide).toHaveBeenCalledWith("5", "separate"));
    fireEvent.click(within(card).getByRole("button", { name: "دمج" }));
    await waitFor(() => expect(decide).toHaveBeenCalledWith("5", "merge"));
  });
});

describe("Shadow Mode composer", () => {
  const proposal: ShadowProposal = {
    id: "p1",
    conversationId: "c1",
    status: "pending",
    proposedReply: "هلا بيك! شنو اختصاص العيادة؟",
    confidence: 0.82,
    intents: [{ name: "clinic_setup", confidence: 0.82 }],
    actions: [
      { action: "start_trial", tool: "start_trial", riskClass: "HIGH_RISK", verdict: "approval", note: "" },
    ],
    approvals: [{ kind: "start_trial" }],
    cited: [],
    escalation: { proposed: false, reason: null, decision: null },
    human: null,
    createdAt: "2026-10-03T10:00:00Z",
  };

  it("shows the proposal beside the composer and links the human reply to it", async () => {
    const src = makeSource();
    const status = await src.getStatus();
    vi.spyOn(src, "getStatus").mockResolvedValue({ ...status, shadowMode: true });
    vi.spyOn(src, "getShadow").mockResolvedValue({ enabled: true, items: [proposal] });
    const send = vi.spyOn(src, "sendMessage");
    useUi.setState({ selectedConversationId: "c1" });
    renderWithSource(<ChatPanel />, src);
    const strip = await screen.findByRole("region", { name: /اقتراح FINORA CORE/ });
    expect(strip).toHaveTextContent("وضع الظل — لا يُرسل");
    expect(strip).toHaveTextContent("يطلب موافقة");
    // AI-controlled conversation: in Shadow Mode the human still answers
    fireEvent.click(within(strip).getByRole("button", { name: "استخدام الاقتراح" }));
    expect(screen.getByLabelText("نص الرسالة")).toHaveValue(proposal.proposedReply);
    fireEvent.click(screen.getByRole("button", { name: "إرسال" }));
    await waitFor(() =>
      expect(send).toHaveBeenCalledWith("c1", proposal.proposedReply, expect.any(String), {
        proposalId: "p1",
        usedProposal: true,
      }),
    );
  });
});
