import type { LucideIcon } from "lucide-react";
import type { Permission } from "@/api/finora/schemas";
import type { WindowId } from "@/windows/registry";

/** What happens when a navigation item is chosen. Uses the app's existing navigation (windows) — no router. */
export type NavTarget = { kind: "window"; window: WindowId } | { kind: "run"; run(): void };

/** One page / function reachable from «المزيد» and from the Ctrl+K palette. */
export interface NavItem {
  /** Stable id — favorites and recent pages are stored by it, so never rename it. */
  id: string;
  label: string;
  description?: string;
  icon: LucideIcon;
  /** Alternative names and synonyms (Arabic or English) the search also matches. */
  keywords?: readonly string[];
  /** Hidden for users FINORA does not grant this permission. Window targets also inherit the window's permission. */
  permission?: Permission;
  target: NavTarget;
}

export interface NavGroup {
  id: string;
  title: string;
  icon?: LucideIcon;
  items: readonly NavItem[];
}
