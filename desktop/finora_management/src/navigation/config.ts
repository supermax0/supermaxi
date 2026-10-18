import type { NavGroup } from "./types";
import {
  UsersRound,
  ContactRound,
  LibraryBig,
  Receipt,
  ShieldCheck,
  Store,
  Tags,
  LineChart,
  Link2,
  Truck,
  Wallet,
} from "lucide-react";

/**
 * Pages offered by «المزيد» and the Ctrl+K palette — the single navigation source of truth.
 *
 * Groups and pages are added here one by one. The menu, search, favorites, recent pages,
 * permissions and the palette all pick a new entry up automatically; no component needs to change. Example shape:
 *
 *   {
 *     id: "group-id",                 // stable
 *     title: "عنوان المجموعة",
 *     icon: SomeLucideIcon,           // optional
 *     items: [
 *       {
 *         id: "page-id",              // stable — favorites / recent are stored by it
 *         label: "اسم الصفحة",
 *         description: "وصف قصير",     // optional
 *         icon: SomeLucideIcon,
 *         keywords: ["اسم بديل", "english name"],  // optional synonyms for search
 *         permission: "view_reports",            // optional — hidden without it
 *         target: { kind: "window", window: "reports" },   // or { kind: "run", run() { … } }
 *       },
 *     ],
 *   }
 *
 * Empty groups are never shown.
 */
export const NAV_GROUPS: readonly NavGroup[] = [
  {
    id: "finance",
    title: "الحسابات والمالية",
    icon: Wallet,
    items: [
      {
        id: "customers",
        label: "العملاء",
        description: "ملفات العملاء والديون والفواتير والأقساط وكشوف الحساب",
        icon: UsersRound,
        keywords: ["زبائن", "زبون", "عميل", "ديون", "أقساط", "customer", "customers"],
        permission: "manage_customers",
        target: { kind: "window", window: "customers" },
      },
      {
        id: "finance",
        label: "الحسابات",
        description: "القبض والصرف والقروض والسلف والصناديق",
        icon: Wallet,
        keywords: ["قبض", "صرف", "قرض", "سلف", "صندوق", "finance"],
        permission: "finance.view",
        target: { kind: "window", window: "finance" },
      },
      {
        id: "expenses",
        label: "المصاريف",
        description: "مصاريف الشركة اليومية والمتكررة والمجدولة",
        icon: Receipt,
        keywords: ["مصروف", "مصاريف", "نفقات", "ايجار", "رواتب", "كهرباء", "expenses", "expense"],
        permission: "view_expenses",
        target: { kind: "window", window: "expenses" },
      },
    ],
  },
  {
    id: "pricing",
    title: "التسعير",
    icon: Tags,
    items: [
      {
        id: "pricing-center",
        label: "التسعير",
        description: "قواعد هامش الربح، تحديث الأسعار جماعياً بالموافقة، والعروض بتاريخ",
        icon: Tags,
        keywords: ["تسعير", "اسعار", "سعر", "هامش", "ربح", "عرض", "تخفيض", "خصم", "pricing"],
        target: { kind: "window", window: "pricing" },
      },
    ],
  },
  {
    id: "store-analytics",
    title: "تحليلات المتجر",
    icon: LineChart,
    items: [
      {
        id: "store-analytics-center",
        label: "تحليلات المتجر الإلكتروني",
        description: "الزيارات والبحث بلا نتائج، مسار الشراء، المبيعات الفعلية، أثر التوصيات، وسرعة المتجر",
        icon: LineChart,
        keywords: ["تحليلات", "احصائيات", "متجر", "زيارات", "بحث", "تحويل", "توصيات", "سرعة", "analytics"],
        target: { kind: "window", window: "storeAnalytics" },
      },
      {
        id: "store-product-links",
        label: "توصيات المتجر",
        description: "تأكيد الملحقات المتوافقة، الترقيات، الباقات، ومعاينة ما يراه الزبون في صفحة المنتج",
        icon: Link2,
        keywords: [
          "توصيات",
          "ملحقات",
          "متوافق",
          "باقة",
          "باقات",
          "ترقية",
          "حامل",
          "recommendations",
          "bundle",
        ],
        target: { kind: "window", window: "productLinks" },
      },
    ],
  },
  {
    id: "catalog",
    title: "الكتالوج",
    icon: LibraryBig,
    items: [
      {
        id: "catalog-center",
        label: "الكتالوج الرئيسي",
        description: "موديلات ومواصفات وصور للمتجر، إضافة ذكية واستيراد قوائم الموردين",
        icon: LibraryBig,
        keywords: ["كتالوج", "موديل", "باركود", "استيراد", "مواصفات", "صور", "مورد", "catalog"],
        target: { kind: "window", window: "catalog" },
      },
    ],
  },
  {
    id: "permissions",
    title: "الصلاحيات",
    icon: ShieldCheck,
    items: [
      {
        id: "permissions-center",
        label: "الصلاحيات والأدوار",
        description: "صلاحيات كل موظف وأدواره واستثناءاته الفردية",
        icon: ShieldCheck,
        keywords: ["صلاحيات", "صلاحية", "دور", "ادوار", "موظف", "منع", "سماح", "permissions", "roles"],
        target: { kind: "window", window: "permissions" },
      },
    ],
  },
  {
    id: "branches",
    title: "الفروع والمخازن",
    icon: Store,
    items: [
      {
        id: "branches-center",
        label: "الفروع والمخازن",
        description: "إدارة فروع الشركة ومخازنها وصناديقها ونطاق العمل",
        icon: Store,
        keywords: ["فرع", "فروع", "مخزن", "مخازن", "فرع جديد", "branch", "branches"],
        target: { kind: "window", window: "branches" },
      },
    ],
  },
  {
    id: "shipping",
    title: "الشحن والتوصيل",
    icon: Truck,
    items: [
      {
        id: "shipping-center",
        label: "مركز الشحن والتسويات",
        description: "شركات النقل والمندوبون وكشوف التسليم والتسوية والمرتجعات",
        icon: Truck,
        keywords: ["شحن", "توصيل", "مندوب", "كشف", "تسوية", "بوليصة", "مرتجع", "shipping", "courier"],
        permission: "can_see_shipping",
        target: { kind: "window", window: "shipping" },
      },
    ],
  },
  {
    id: "human-resources",
    title: "الموظفون والموارد البشرية",
    icon: ContactRound,
    items: [
      {
        id: "employees",
        label: "الموظفون",
        description: "الدوام والرواتب والسلف والإجازات والتوظيف",
        icon: ContactRound,
        keywords: ["موظفين", "موظف", "رواتب", "دوام", "HR", "HRM", "payroll", "employees"],
        permission: "hr.view",
        target: { kind: "window", window: "employees" },
      },
    ],
  },
  {
    id: "purchasing",
    title: "المشتريات والموردين",
    icon: UsersRound,
    items: [
      {
        id: "suppliers",
        label: "الموردين",
        description: "حسابات الموردين والمشتريات والدفعات",
        icon: UsersRound,
        keywords: ["supplier", "suppliers", "مورد", "المجهزين"],
        permission: "can_manage_suppliers",
        target: { kind: "window", window: "suppliers" },
      },
    ],
  },
];
