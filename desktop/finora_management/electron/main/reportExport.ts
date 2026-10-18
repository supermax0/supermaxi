/**
 * Report print / PDF / Excel. FINORA renders the content (same engine,
 * filters and permissions as the screen); main only loads it on the FINORA
 * session and saves the file where the user chooses.
 */
import { randomUUID } from "node:crypto";
import { rm, writeFile } from "node:fs/promises";
import path from "node:path";
import { pathToFileURL } from "node:url";
import { app, BrowserWindow, dialog } from "electron";
import { reportExportPath, type ReportExportRequest, type ReportExportResult } from "../../shared/ipc";
import { getServerUrl } from "./config";
import { FINORA_PARTITION, finoraSession } from "./finoraHttp";
import { netRequest } from "./netRequest";

const XLSX_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet";

function fileStem(request: ReportExportRequest): string {
  const { date_from: from, date_to: to } = request.query;
  const range = from && to ? `${from}_${to}` : request.query.period;
  return `${request.title} ${range}`.replace(/[\\/:*?"<>|]/g, "-");
}

/** FINORA's JSON error text, or a generic message. */
function serverError(body: Buffer, status: number): Error {
  try {
    const parsed: unknown = JSON.parse(body.toString("utf8"));
    if (parsed && typeof parsed === "object" && "error" in parsed && typeof parsed.error === "string") {
      return new Error(parsed.error);
    }
  } catch {
    // not JSON
  }
  if (status === 302 || status === 401) return new Error("انتهت الجلسة، سجّل الدخول من جديد");
  if (status === 403) return new Error("ليست لديك صلاحية تصدير هذا التقرير");
  return new Error(`تعذر تجهيز التقرير (${status})`);
}

function reportWindow(parent: BrowserWindow | null, origin: string, show: boolean): BrowserWindow {
  const win = new BrowserWindow({
    parent: parent ?? undefined,
    width: 1100,
    height: 780,
    show: false,
    autoHideMenuBar: true,
    backgroundColor: "#ffffff",
    title: "طباعة التقرير",
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
  win.webContents.on("will-navigate", (event, url) => {
    if (new URL(url).origin !== origin) event.preventDefault();
  });
  win.webContents.setWindowOpenHandler(() => ({ action: "deny" }));
  if (show) win.once("ready-to-show", () => win.show());
  return win;
}

/** Load the print page and fail on FINORA's refusals (403 JSON, expired session). */
async function loadReport(win: BrowserWindow, url: string): Promise<void> {
  let status = 200;
  win.webContents.once("did-navigate", (_event, _url, httpResponseCode) => {
    status = httpResponseCode;
  });
  await win.loadURL(url);
  if (status !== 200) {
    const text = await win.webContents
      .executeJavaScript("document.body ? document.body.innerText : ''", true)
      .catch(() => "");
    throw serverError(Buffer.from(String(text)), status);
  }
}

function saveDialog(parent: BrowserWindow | null, options: Electron.SaveDialogOptions) {
  return parent ? dialog.showSaveDialog(parent, options) : dialog.showSaveDialog(options);
}

export async function exportReport(
  parent: BrowserWindow | null,
  request: ReportExportRequest,
): Promise<ReportExportResult> {
  const serverUrl = await getServerUrl();
  if (!serverUrl) throw new Error("FINORA server is not configured");
  const origin = new URL(serverUrl).origin;
  const url = new URL(reportExportPath(request), `${serverUrl}/`).toString();

  if (request.format === "xlsx") {
    const response = await netRequest(finoraSession(), url, {
      method: "GET",
      headers: { Accept: `${XLSX_TYPE}, application/json` },
      timeoutMs: 120_000,
    });
    if (response.status !== 200 || !(response.contentType ?? "").includes("spreadsheetml")) {
      throw serverError(response.body, response.status);
    }
    const target = await saveDialog(parent, {
      title: "حفظ ملف Excel",
      defaultPath: `${fileStem(request)}.xlsx`,
      filters: [{ name: "Excel", extensions: ["xlsx"] }],
    });
    if (target.canceled || !target.filePath) return { saved: false };
    await writeFile(target.filePath, response.body);
    return { saved: true, path: target.filePath };
  }

  if (request.format === "print") {
    // Electron's system print dialog has no preview ("This app doesn't support print preview"), so render the
    // report to PDF first and show the real pages in Chromium's PDF viewer — its print button prints them.
    await showPrintPreview(parent, request.title, await renderPdf(parent, origin, url));
    return { saved: false };
  }

  {
    const pdf = await renderPdf(parent, origin, url);
    const target = await saveDialog(parent, {
      title: "حفظ PDF",
      defaultPath: `${fileStem(request)}.pdf`,
      filters: [{ name: "PDF", extensions: ["pdf"] }],
    });
    if (target.canceled || !target.filePath) return { saved: false };
    await writeFile(target.filePath, pdf);
    return { saved: true, path: target.filePath };
  }
}

async function renderPdf(parent: BrowserWindow | null, origin: string, url: string): Promise<Buffer> {
  const win = reportWindow(parent, origin, false);
  try {
    await loadReport(win, url);
    return await win.webContents.printToPDF({ landscape: true, pageSize: "A4", printBackground: true });
  } finally {
    win.destroy();
  }
}

/** Print preview: the exact A4 pages in a viewer window; the temporary PDF is deleted when it closes. */
async function showPrintPreview(parent: BrowserWindow | null, title: string, pdf: Buffer): Promise<void> {
  const file = path.join(app.getPath("temp"), `finora-print-${randomUUID()}.pdf`);
  await writeFile(file, pdf);
  const fileUrl = pathToFileURL(file).toString();
  const win = new BrowserWindow({
    parent: parent ?? undefined,
    width: 1100,
    height: 820,
    show: false,
    autoHideMenuBar: true,
    backgroundColor: "#525659",
    title: `معاينة الطباعة — ${title}`,
    webPreferences: {
      plugins: true, // Chromium PDF viewer
      sandbox: true,
      contextIsolation: true,
      nodeIntegration: false,
      webSecurity: true,
      devTools: false,
    },
  });
  win.removeMenu();
  win.webContents.on("will-navigate", (event, target) => {
    if (target !== fileUrl) event.preventDefault();
  });
  win.webContents.setWindowOpenHandler(() => ({ action: "deny" }));
  win.on("page-title-updated", (event) => event.preventDefault());
  win.once("ready-to-show", () => win.show());
  win.once("closed", () => {
    rm(file, { force: true }).catch((error: unknown) => console.warn("[print] temp PDF not removed", error));
  });
  try {
    await win.loadURL(fileUrl);
  } catch (error) {
    win.destroy();
    throw error;
  }
}
