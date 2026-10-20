/**
 * The only entry point components and hooks use to reach FINORA.
 * Endpoint ↔ feature mapping: docs/finora-integration-map.md
 */
import { desktopBridge } from "@/services/bridge";
import { auth } from "./auth";
import { orders } from "./orders";
import { pos } from "./pos";
import { products } from "./products";
import { purchases } from "./purchases";
import { reports } from "./reports";
import { suppliers } from "./suppliers";
import { hr } from "./hr";
import { finance } from "./finance";
import { customers } from "./customers";
import { expenses } from "./expenses";
import { branchCash } from "./branchCash";
import { branches } from "./branches";
import { permissions } from "./permissions";
import { catalog } from "./catalog";
import { pricing } from "./pricing";
import { storeAnalytics } from "./storeAnalytics";
import { recommendations } from "./recommendations";
import { shipping } from "./shipping";
import { inventoryAudit } from "./inventoryAudit";
import { inventoryActivity } from "./inventoryActivity";
import { stockOperations } from "./stockOperations";
import { cashShifts } from "./cashShifts";
import { financialControl } from "./financialControl";
import { displayPreferences } from "./displayPreferences";

export const finora = {
  displayPreferences,
  auth,
  orders,
  pos,
  products,
  purchases,
  reports,
  suppliers,
  hr,
  finance,
  customers,
  expenses,
  shipping,
  branches,
  permissions,
  catalog,
  pricing,
  storeAnalytics,
  recommendations,
  branchCash,
  inventoryAudit,
  inventoryActivity,
  stockOperations,
  cashShifts,
  financialControl,
  config: {
    get: () => desktopBridge().config.get(),
    setServer: (serverUrl: string) => desktopBridge().config.setServer(serverUrl),
  },
};

export { FinoraApiError, toFinoraError, type FinoraErrorKind } from "./errors";
export type { FinoraSession, Permission } from "./schemas";
