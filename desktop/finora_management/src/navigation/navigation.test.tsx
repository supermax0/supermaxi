import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { Boxes, FileText, Truck } from "lucide-react";
import { useRef } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MoreMenu } from "@/components/more/MoreMenu";
import { useNavigationPrefs } from "@/stores/navigationPrefs";
import { useSession } from "@/stores/session";
import { useUi } from "@/stores/ui";
import { useWindowManager } from "@/stores/windowManager";
import { NAV_GROUPS } from "./config";
import { normalizeSearchText, searchItems } from "./search";
import type { NavGroup } from "./types";
import { NavigationConfigContext } from "./useNavigation";

// Test-only navigation data for search and permissions.
const runInvoices = vi.fn();
const GROUPS: NavGroup[] = [
  {
    id: "sales",
    title: "المبيعات",
    items: [
      {
        id: "invoices",
        label: "الفواتير",
        description: "كل فواتير البيع",
        icon: FileText,
        keywords: ["invoices", "bills"],
        target: { kind: "run", run: runInvoices },
      },
      {
        id: "shipping",
        label: "شركات الشحن",
        icon: Truck,
        keywords: ["delivery", "توصيل"],
        target: { kind: "run", run: vi.fn() },
      },
    ],
  },
  { id: "empty", title: "مجموعة فارغة", items: [] },
  {
    id: "secret",
    title: "مخفية",
    items: [{ id: "reports", label: "التقارير", icon: Boxes, target: { kind: "window", window: "reports" } }],
  },
];

function signIn(permissions: string[]) {
  useSession.setState({
    status: "signed_in",
    session: { user: { id: 1, name: "سارة" }, permissions } as never,
  } as never);
}

function Harness({ groups = GROUPS }: { groups?: readonly NavGroup[] }) {
  const ref = useRef<HTMLButtonElement>(null);
  const panel = useUi((s) => s.panel);
  return (
    <NavigationConfigContext.Provider value={groups}>
      <button
        ref={ref}
        type="button"
        aria-expanded={panel === "more"}
        onClick={() => useUi.getState().togglePanel("more")}
      >
        المزيد
      </button>
      <MoreMenu open={panel === "more"} anchor={ref} onClose={() => useUi.getState().closePanel()} />
    </NavigationConfigContext.Provider>
  );
}

function openMenu() {
  fireEvent.click(screen.getByRole("button", { name: "المزيد" }));
  return screen.getByRole("dialog", { name: "المزيد" });
}

beforeEach(() => {
  localStorage.clear();
  useNavigationPrefs.setState({ favorites: [], recent: [] });
  useUi.setState({ panel: null, paletteOpen: false });
  useWindowManager.setState({ active: null });
  runInvoices.mockReset();
  signIn([]);
});

describe("navigation search engine", () => {
  const items = GROUPS.flatMap((g) => g.items);

  it("normalizes Arabic letter variants, diacritics and digits", () => {
    expect(normalizeSearchText("الفَواتِيـر ١٢")).toBe("الفواتير 12");
    expect(normalizeSearchText("إدارة المكتبة")).toBe("اداره المكتبه");
  });

  it("matches Arabic, English, partial words, synonyms and the optional ال", () => {
    const ids = (q: string) => searchItems(items, q).map((i) => i.id);
    expect(ids("فواتير")).toEqual(["invoices"]);
    expect(ids("فوا")).toEqual(["invoices"]);
    expect(ids("invoice")).toEqual(["invoices"]);
    expect(ids("توصيل")).toEqual(["shipping"]);
    expect(ids("شركات شحن")).toEqual(["shipping"]);
    expect(ids("شحن فواتير")).toEqual([]); // every word must match the same item
    expect(ids("")).toEqual([]);
  });

  it("ranks label matches above synonym and description matches", () => {
    const ranked = searchItems(
      [
        { id: "a", label: "تقارير", keywords: ["بيع"] },
        { id: "b", label: "البيع السريع" },
      ],
      "بيع",
    );
    expect(ranked.map((r) => r.id)).toEqual(["b", "a"]);
  });
});

describe("«المزيد» menu", () => {
  it("offers customers with permission and opens the existing workspace from Arabic search", () => {
    signIn(["manage_customers"]);
    render(<Harness groups={NAV_GROUPS} />);
    const dialog = openMenu();
    fireEvent.change(within(dialog).getByRole("combobox"), { target: { value: "زبائن" } });
    expect(within(dialog).getAllByRole("option")).toHaveLength(1);
    fireEvent.keyDown(within(dialog).getByRole("combobox"), { key: "Enter" });
    expect(useWindowManager.getState().active).toBe("customers");
    expect(useNavigationPrefs.getState().recent).toEqual(["customers"]);
  });
  it("hides customers without the server-granted customer permission", () => {
    signIn(["finance.view"]);
    render(<Harness groups={NAV_GROUPS} />);
    expect(within(openMenu()).queryByText("العملاء")).not.toBeInTheDocument();
  });
  it("shows an elegant empty state when no pages are configured", () => {
    render(<Harness groups={[]} />);
    const dialog = openMenu();
    expect(within(dialog).getByText("لا توجد صفحات بعد")).toBeInTheDocument();
  });

  it("offers the native supplier page only with supplier permission", () => {
    signIn(["can_manage_suppliers"]);
    render(<Harness groups={NAV_GROUPS} />);
    const dialog = openMenu();
    fireEvent.click(within(dialog).getByText("الموردين"));
    expect(useWindowManager.getState().active).toBe("suppliers");
  });

  it("hides the supplier page without supplier permission", () => {
    render(<Harness groups={NAV_GROUPS} />);
    const dialog = openMenu();
    expect(within(dialog).queryByText("الموردين")).not.toBeInTheDocument();
  });

  it("opens from the top bar, focuses search, hides empty groups and unpermitted pages", async () => {
    render(<Harness />);
    const dialog = openMenu();
    await waitFor(() => expect(within(dialog).getByRole("combobox")).toHaveFocus());
    expect(within(dialog).getByText("الفواتير")).toBeInTheDocument();
    expect(within(dialog).queryByText("مجموعة فارغة")).not.toBeInTheDocument();
    expect(within(dialog).queryByText("التقارير")).not.toBeInTheDocument(); // window needs view_reports
  });

  it("shows pages the user is permitted to open", () => {
    signIn(["view_reports"]);
    render(<Harness />);
    expect(within(openMenu()).getByText("التقارير")).toBeInTheDocument();
  });

  it("searches instantly, moves with the arrows and opens with Enter", () => {
    render(<Harness />);
    const dialog = openMenu();
    const input = within(dialog).getByRole("combobox");
    fireEvent.change(input, { target: { value: "ش" } });
    expect(within(dialog).getByText("النتائج")).toBeInTheDocument();
    fireEvent.change(input, { target: { value: "bills" } });
    const options = within(dialog).getAllByRole("option");
    expect(options).toHaveLength(1);
    expect(options[0]).toHaveAttribute("aria-selected", "true");
    fireEvent.keyDown(input, { key: "Enter" });
    expect(runInvoices).toHaveBeenCalledTimes(1);
    expect(useUi.getState().panel).toBeNull();
    expect(useNavigationPrefs.getState().recent).toEqual(["invoices"]);
  });

  it("arrow keys walk the rows in visual order", () => {
    render(<Harness />);
    const dialog = openMenu();
    const input = within(dialog).getByRole("combobox");
    const selected = () =>
      within(dialog)
        .getAllByRole("option")
        .find((o) => o.getAttribute("aria-selected") === "true");
    expect(selected()).toHaveTextContent("الفواتير");
    fireEvent.keyDown(input, { key: "ArrowDown" });
    expect(selected()).toHaveTextContent("شركات الشحن");
    fireEvent.keyDown(input, { key: "ArrowUp" });
    expect(selected()).toHaveTextContent("الفواتير");
  });

  it("shows a clear empty state when nothing matches", () => {
    render(<Harness />);
    const dialog = openMenu();
    fireEvent.change(within(dialog).getByRole("combobox"), { target: { value: "غير موجود" } });
    expect(within(dialog).getByText("لا توجد نتائج لـ «غير موجود»")).toBeInTheDocument();
  });

  it("pins favorites, lists recent pages, and hides both sections when empty", () => {
    render(<Harness />);
    let dialog = openMenu();
    expect(within(dialog).queryByRole("region", { name: "المفضلة" })).not.toBeInTheDocument();
    expect(within(dialog).queryByRole("region", { name: "آخر استخدام" })).not.toBeInTheDocument();
    fireEvent.click(within(dialog).getByRole("button", { name: "إضافة شركات الشحن إلى المفضلة" }));
    expect(within(dialog).getByRole("region", { name: "المفضلة" })).toHaveTextContent("شركات الشحن");
    act(() => useNavigationPrefs.getState().recordVisit("invoices"));
    dialog = screen.getByRole("dialog", { name: "المزيد" });
    expect(within(dialog).getByRole("region", { name: "آخر استخدام" })).toHaveTextContent("الفواتير");
    expect(JSON.parse(localStorage.getItem("finora-management:navigation") ?? "{}")).toEqual({
      favorites: ["shipping"],
      recent: ["invoices"],
    });
  });

  it("Escape closes the menu and gives focus back to the button", async () => {
    render(<Harness />);
    const dialog = openMenu();
    const input = within(dialog).getByRole("combobox");
    await waitFor(() => expect(input).toHaveFocus());
    fireEvent.keyDown(input, { key: "Escape" });
    expect(useUi.getState().panel).toBeNull();
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "المزيد" })).not.toBeInTheDocument());
    expect(screen.getByRole("button", { name: "المزيد" })).toHaveFocus();
  });

  it("closes on an outside click and when the command palette opens (and vice versa)", async () => {
    render(<Harness />);
    openMenu();
    fireEvent.pointerDown(document.body);
    expect(useUi.getState().panel).toBeNull();
    openMenu();
    act(() => useUi.getState().setPaletteOpen(true));
    expect(useUi.getState().panel).toBeNull();
    act(() => useUi.getState().togglePanel("more"));
    expect(useUi.getState().paletteOpen).toBe(false);
  });
});
