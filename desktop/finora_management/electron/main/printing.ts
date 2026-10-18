/**
 * Printing uses FINORA's own print pages (same templates, same permissions as
 * the web). They load in a sandboxed window on the FINORA session partition;
 * the orders page opens the system print dialog by itself.
 */
import { BrowserWindow } from "electron";
import { printPath, type PrintRequest } from "../../shared/ipc";
import { getServerUrl } from "./config";
import { FINORA_PARTITION } from "./finoraHttp";
import { receiptHtml } from "./posReceipt";
import type { OfflineEngine } from "./offlineEngine";

export async function printLocalPosReceipt(
  parent: BrowserWindow | null,
  receipt: Awaited<ReturnType<OfflineEngine["posReceipt"]>>,
): Promise<void> {
  const win = new BrowserWindow({
    parent: parent ?? undefined,
    width: 760,
    height: 800,
    title: "إيصال البيع المحلي",
    autoHideMenuBar: true,
    show: false,
    webPreferences: {
      sandbox: true,
      contextIsolation: true,
      nodeIntegration: false,
      javascript: false,
      devTools: false,
    },
  });
  win.webContents.on("will-navigate", (e) => e.preventDefault());
  win.webContents.setWindowOpenHandler(() => ({ action: "deny" }));
  try {
    await win.loadURL(`data:text/html;charset=utf-8,${encodeURIComponent(receiptHtml(receipt))}`);
    win.show();
    await new Promise<void>((resolve, reject) =>
      win.webContents.print({ silent: false, printBackground: true }, (success, reason) => {
        if (success || reason === "cancelled") resolve();
        else reject(new Error(`تعذّرت طباعة الإيصال: ${reason}`));
      }),
    );
  } catch (error) {
    win.close();
    throw error;
  }
}

export async function openPrintWindow(parent: BrowserWindow | null, request: PrintRequest): Promise<void> {
  const serverUrl = await getServerUrl();
  if (!serverUrl) throw new Error("FINORA server is not configured");
  const origin = new URL(serverUrl).origin;

  const win = new BrowserWindow({
    parent: parent ?? undefined,
    width: 980,
    height: 760,
    minWidth: 640,
    minHeight: 480,
    title:
      request.kind === "inventory_activity"
        ? "حركة المخزون"
        : request.kind === "orders"
          ? "طباعة الطلبات"
          : request.kind === "finance_report" ||
              request.kind === "financial_control_snapshot" ||
              request.kind === "financial_control_comparison"
            ? "طباعة التقرير المالي"
            : request.kind === "finance_voucher"
              ? "طباعة السند المالي"
              : request.kind === "finance_cash_shift"
                ? "طباعة وردية الصندوق"
                : request.kind === "finance_loan"
                  ? "جدول الأقساط"
                  : request.kind === "supplier"
                    ? "كشف حساب المورد"
                    : request.kind === "customer_statement"
                      ? "كشف مستحقات العميل"
                      : request.kind === "customer_transactions"
                        ? "حركات تحصيل العميل"
                        : request.kind === "shipping_receipt"
                          ? "سند قبض"
                          : "طباعة أمر الشراء",
    autoHideMenuBar: true,
    backgroundColor: "#ffffff",
    show: false,
    webPreferences: {
      partition: FINORA_PARTITION,
      sandbox: true,
      contextIsolation: true,
      nodeIntegration: false,
      webSecurity: true,
      devTools: false,
    },
  });
  win.removeMenu();
  // Stay on the FINORA server: no navigation away, no pop-ups.
  win.webContents.on("will-navigate", (event, url) => {
    if (new URL(url).origin !== origin) event.preventDefault();
  });
  win.webContents.setWindowOpenHandler(() => ({ action: "deny" }));
  win.once("ready-to-show", () => win.show());
  await win.loadURL(new URL(printPath(request), `${serverUrl}/`).toString());
}
