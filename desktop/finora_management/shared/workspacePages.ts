export const WORKSPACE_PAGES = {
  assets: { title: "الأصول الثابتة", path: "/assets/dashboard" },
  maintenance: { title: "الصيانة", path: "/maintenance" },
  notes: { title: "الملاحظات", path: "/notes" },
  messages: { title: "المراسلات", path: "/messages" },
  workspace: { title: "مساحة عمل الذكاء الاصطناعي", path: "/workspace/" },
  storeSettings: { title: "إعدادات المتجر", path: "/settings/storefront" },
  cameraAudit: { title: "الجرد ومسح الكاميرا", path: "/inventory/smart-audit" },
} as const;
export type WorkspacePageId = keyof typeof WORKSPACE_PAGES;
