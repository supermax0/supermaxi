import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { AgentSettings } from "../data/coreSettings";
import { HttpDataSource } from "../data/http";
import { renderWithSource } from "../test/render";
import { IntegrationSettings } from "./IntegrationSettings";
import { SettingsPanel } from "./SettingsPanel";

const settings: AgentSettings = {
  config: {
    provider: "cloud",
    cloudModel: "",
    localUrl: "http://127.0.0.1:11434",
    localModel: "",
    timeoutSeconds: 15,
    replyMode: "automatic",
    language: "auto",
    tone: "friendly",
    replyLength: "short",
    minimumConfidence: 0.7,
    instructions: "",
  },
  cloudKeyConfigured: true,
  cloudKeySource: "server",
  resolvedCloudModel: "server-model",
};
function source() {
  const src = new HttpDataSource(
    "https://finora.test",
    {
      accessToken: "test",
      refreshToken: "test",
      operator: { id: 1, username: "owner", role: "super_admin", permissions: ["settings.manage"] },
    },
    vi.fn(),
  );
  let stored = structuredClone(settings);
  vi.spyOn(src, "getAgentSettings").mockImplementation(async () => structuredClone(stored));
  vi.spyOn(src, "saveAgentSettings").mockImplementation(async (config) => {
    stored = { ...stored, config };
    return structuredClone(stored);
  });
  vi.spyOn(src, "getStatus").mockResolvedValue({
    environment: "production",
    channels: { instagram: "connected", facebook: "disconnected", telegram: "disconnected" },
    automationPaused: false,
    shadowMode: false,
    agent: { state: "idle", label: null, conversationId: null, channel: null },
    conversationCount: 0,
    houseConfigured: true,
    devLoopback: false,
  });
  return src;
}
afterEach(() => vi.restoreAllMocks());

describe("IntegrationSettings", () => {
  it("shows knowledge coverage, searches reviewed guides and filters the business type", async () => {
    const src = source();
    vi.spyOn(src, "getProductKnowledge").mockImplementation(async (query) => ({
      featureCount: 162,
      guideCount: 44,
      publishedCount: 0,
      categories: [],
      note: "شرح موثق حسب النشاط",
      results: query
        ? [
            {
              id: "guide:inventory.add",
              title: "إضافة منتج للمخزون",
              text: "1. افتح المخزون\n2. احفظ المنتج",
              kind: "guide",
              businessType: null,
              source: "reviewed",
            },
          ]
        : [],
    }));
    renderWithSource(<IntegrationSettings src={src} section="knowledge" />, src);
    await screen.findByText(/162 ميزة/);
    fireEvent.change(screen.getByLabelText("نوع النشاط للشرح"), { target: { value: "general" } });
    await waitFor(() => expect(screen.getByRole("button", { name: "بحث في معرفة النظام" })).toBeEnabled());
    fireEvent.change(screen.getByLabelText("ابحث عن ميزة أو طريقة استخدامها"), {
      target: { value: "شلون اضيف منتج؟" },
    });
    fireEvent.click(screen.getByRole("button", { name: "بحث في معرفة النظام" }));
    await screen.findByText("إضافة منتج للمخزون");
    expect(src.getProductKnowledge).toHaveBeenCalledWith("شلون اضيف منتج؟", "general");
  });
  it("saves recommended review mode and requires saving before preview", async () => {
    const src = source();
    renderWithSource(<IntegrationSettings src={src} section="replies" />, src);
    await screen.findByLabelText("طريقة الرد");
    fireEvent.click(screen.getByText("تجربة الرد قبل الإرسال"));
    fireEvent.click(screen.getByRole("button", { name: "إعدادات فينورا المقترحة" }));
    expect(screen.getByLabelText("طريقة الرد")).toHaveValue("review");
    expect(screen.getByRole("button", { name: "تجربة الرد" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "حفظ إعدادات الرد" }));
    await waitFor(() =>
      expect(src.saveAgentSettings).toHaveBeenCalledWith(
        expect.objectContaining({ replyMode: "review", minimumConfidence: 0.7 }),
      ),
    );
    await waitFor(() => expect(screen.getByRole("button", { name: "تجربة الرد" })).toBeEnabled());
  });

  it("shows server-local guidance and explains safe rules fallback in preview", async () => {
    const src = source();
    vi.spyOn(src, "previewAgentReply").mockResolvedValue({
      text: "راح أتأكد ويا الفريق",
      source: "rules",
      model: "rules",
      needsHuman: true,
      reason: "unavailable",
      fallback: "local_unreachable",
    });
    renderWithSource(<SettingsPanel />, src);
    expect(src.getAgentSettings).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "الذكاء الاصطناعي" }));
    await screen.findByLabelText("مصدر الذكاء");
    fireEvent.change(screen.getByLabelText("مصدر الذكاء"), { target: { value: "local" } });
    expect(screen.getByText(/وليس حاسوبك/)).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("اسم النموذج المحلي المثبت"), {
      target: { value: "installed-model" },
    });
    expect(screen.getByLabelText("طريقة الرد")).not.toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "كل الإعدادات" }));
    fireEvent.click(screen.getByRole("button", { name: "ردود العملاء" }));
    expect(screen.getByLabelText("مصدر الذكاء")).not.toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "كل الإعدادات" }));
    fireEvent.click(screen.getByRole("button", { name: "الذكاء الاصطناعي" }));
    expect(screen.getByLabelText("اسم النموذج المحلي المثبت")).toHaveValue("installed-model");
    fireEvent.click(screen.getByRole("button", { name: "حفظ إعدادات الذكاء" }));
    await waitFor(() =>
      expect(src.saveAgentSettings).toHaveBeenCalledWith(
        expect.objectContaining({ provider: "local", localModel: "installed-model" }),
      ),
    );
    await waitFor(() => expect(screen.getByRole("button", { name: "حفظ إعدادات الذكاء" })).toBeDisabled());
    fireEvent.click(screen.getByRole("button", { name: "كل الإعدادات" }));
    fireEvent.click(screen.getByRole("button", { name: "ردود العملاء" }));
    fireEvent.click(screen.getByText("تجربة الرد قبل الإرسال"));
    await waitFor(() => expect(screen.getByRole("button", { name: "تجربة الرد" })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: "تجربة الرد" }));
    expect(await screen.findByText("يحتاج موظفاً")).toBeInTheDocument();
    expect(screen.getByText(/رد بالقواعد الآمنة/)).toBeInTheDocument();
  });

  it("retains Meta App ID and clears submitted secrets after connecting", async () => {
    const src = source();
    vi.spyOn(src, "getMetaSettings").mockResolvedValue({
      houseConfigured: true,
      appId: "12345",
      secretConfigured: true,
      webhookUrl: "https://finora.test/webhook",
      channels: [],
    });
    vi.spyOn(src, "connectMeta").mockResolvedValue({ pagesFound: 1, warningsCount: 0, message: "تم الربط" });
    renderWithSource(<IntegrationSettings src={src} section="meta" />, src);
    await waitFor(() => expect(screen.getByLabelText("Meta App ID")).toHaveValue("12345"));
    fireEvent.change(screen.getByLabelText("Meta User Access Token"), {
      target: { value: "temporary-token" },
    });
    fireEvent.change(screen.getByLabelText("Meta App Secret"), { target: { value: "temporary-secret" } });
    fireEvent.click(screen.getByRole("button", { name: "ربط ومزامنة الصفحات" }));
    await waitFor(() =>
      expect(src.connectMeta).toHaveBeenCalledWith({
        appId: "12345",
        appSecret: "temporary-secret",
        userToken: "temporary-token",
      }),
    );
    await waitFor(() => expect(screen.getByLabelText("Meta User Access Token")).toHaveValue(""));
    expect(screen.getByLabelText("Meta App Secret")).toHaveValue("");
  });
  it("keeps account and appearance accessible without integration permissions", async () => {
    const src = source();
    src.operator.permissions = [];
    renderWithSource(<SettingsPanel />, src);
    expect(screen.queryByRole("button", { name: "الذكاء الاصطناعي" })).not.toBeInTheDocument();
    expect(src.getAgentSettings).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "الحساب" }));
    expect(screen.getByRole("button", { name: /تسجيل الخروج/ })).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "كل الإعدادات" }));
    fireEvent.click(screen.getByRole("button", { name: "المظهر" }));
    expect(screen.getByRole("radiogroup", { name: "جودة الحركة" })).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "كل الإعدادات" }));
    fireEvent.click(screen.getByRole("button", { name: "النظام والأتمتة" }));
    expect(await screen.findByText(/التغيير يتطلب صلاحية/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "إيقاف كل الأتمتة" })).not.toBeInTheDocument();
  });
});
