import { pathToFileURL } from "node:url";
import path from "node:path";
import {
  app,
  BrowserWindow,
  dialog,
  ipcMain,
  screen,
  session,
  shell,
  type IpcMainInvokeEvent,
} from "electron";
import {
  finoraFormSchema,
  finoraPagePathSchema,
  finoraRequestSchema,
  IPC,
  printRequestSchema,
  reportExportSchema,
  rememberIdentitySchema,
  serverUrlSchema,
  type WindowState,
} from "../../shared/ipc";
import { getConfig, getServerUrl, rememberIdentity, setServerUrl } from "./config";
import {
  clearFinoraSession,
  finoraSession,
  sendFinoraForm,
  sendFinoraRequest,
  sendFinoraNetworkRequest,
} from "./finoraHttp";
import { getOfflineEngine, recordOfflineIssue, unavailableStatus } from "./offlineRuntime";
import { supplierDraftSchema, posSaleSchema } from "../../shared/offline";
import { reserveStockSchema } from "../../shared/stock";
import { customerCommandKey, customerAcknowledgement } from "../../shared/customerRecovery";
import { z } from "zod";
import { handleMediaProtocol, registerMediaScheme } from "./media";
import { openPrintWindow, printLocalPosReceipt } from "./printing";
import { exportReport } from "./reportExport";

import { windowGeometry } from "./windowGeometry";
import { protectWindow } from "./lifecycle";
import {
  openWorkspace,
  isWorkspaceMediaAllowed,
  trackWorkspaceWrite,
  finishWorkspaceWrite,
} from "./connectedPages";
import { backupProfile } from "./backupRuntime";
import { checkUpdate, downloadUpdate, launchUpdate } from "./updates";

let protection: ReturnType<typeof protectWindow> | null = null;
let inFlight = 0;
let restoring = false;
const approvedMedia = new Set<number>();
const activeWriteRequests = new Set<number>();
const DEV_SERVER_URL = process.env.VITE_DEV_SERVER_URL ?? null;
const RENDERER_FILE = path.join(__dirname, "../../dist/index.html");

let mainWindow: BrowserWindow | null = null;

function rendererOrigin(): string {
  return DEV_SERVER_URL ? new URL(DEV_SERVER_URL).origin : "file://";
}

/** Only our own top-level renderer may call privileged IPC. */
function assertTrustedSender(event: IpcMainInvokeEvent): void {
  const frame = event.senderFrame;
  const trusted =
    mainWindow !== null &&
    event.sender.id === mainWindow.webContents.id &&
    frame !== null &&
    frame.parent === null &&
    (DEV_SERVER_URL
      ? new URL(frame.url).origin === rendererOrigin()
      : frame.url.split("#")[0]?.split("?")[0] === pathToFileURL(RENDERER_FILE).href);
  if (!trusted) throw new Error("untrusted IPC sender");
}

function windowState(win: BrowserWindow): WindowState {
  return { maximized: win.isMaximized(), focused: win.isFocused() };
}

function createMainWindow(): BrowserWindow {
  const area = screen.getPrimaryDisplay().workAreaSize;
  const win = new BrowserWindow({
    ...windowGeometry(area),
    center: true,
    frame: false,
    show: false,
    backgroundColor: "#f4f4fb",
    title: "FINORA Management",
    icon: path.join(__dirname, "../../build/icon.ico"),
    webPreferences: {
      preload: path.join(__dirname, "../preload/index.js"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      webSecurity: true,
      spellcheck: false,
      devTools: !app.isPackaged,
    },
  });

  protection = protectWindow(win, () => inFlight > 0 || activeWriteRequests.size > 0);
  win.once("ready-to-show", () => win.show());
  const pushState = () => {
    if (!win.isDestroyed()) win.webContents.send(IPC.windowState, windowState(win));
  };
  for (const evt of ["maximize", "unmaximize", "focus", "blur", "restore"] as const) {
    win.on(evt as "maximize", pushState);
  }

  win.webContents.setWindowOpenHandler(({ url }) => {
    if (/^https?:\/\//i.test(url)) void shell.openExternal(url);
    return { action: "deny" };
  });
  win.webContents.on("will-navigate", (event, url) => {
    const allowed = DEV_SERVER_URL
      ? new URL(url).origin === rendererOrigin()
      : url.split("#")[0]?.split("?")[0] === pathToFileURL(RENDERER_FILE).href;
    if (!allowed) event.preventDefault();
  });

  if (DEV_SERVER_URL) void win.loadURL(DEV_SERVER_URL);
  else void win.loadFile(RENDERER_FILE);
  return win;
}

function registerIpc(): void {
  const handle = (channel: string, handler: (event: IpcMainInvokeEvent, payload: unknown) => unknown) => {
    ipcMain.handle(channel, async (event, payload: unknown) => {
      const readOnly = [
        IPC.activity,
        IPC.confirmLeave,
        IPC.reload,
        IPC.updateCheck,
        IPC.updateInstall,
        IPC.backupRestore,
        IPC.windowGetState,
        IPC.windowClose,
        IPC.windowMinimize,
        IPC.windowToggleMaximize,
        IPC.configGet,
        IPC.offlineStatus,
        IPC.customerCommandsList,
        IPC.stockCommandsList,
        IPC.autoStartGet,
      ].includes(channel as never);
      const writing =
        !readOnly &&
        !(
          channel === IPC.finoraRequest &&
          finoraRequestSchema.safeParse(payload).success &&
          (payload as { method: string }).method === "GET"
        );
      if (writing && protection?.leaving()) throw Error("انتظر إكمال إغلاق التطبيق أو إلغاءه");
      if (writing && restoring) throw Error("انتظر اكتمال الاستعادة قبل تغيير البيانات");
      if (writing) inFlight++;
      try {
        return await handler(event, payload);
      } finally {
        if (writing) inFlight--;
      }
    });
  };
  handle(IPC.activity, (event, payload) => {
    assertTrustedSender(event);
    protection?.update(z.object({ dirty: z.boolean(), saving: z.boolean() }).strict().parse(payload));
  });
  handle(IPC.confirmLeave, async (event) => {
    assertTrustedSender(event);
    return protection?.permit() ?? false;
  });
  handle(IPC.reload, async (event) => {
    assertTrustedSender(event);
    await protection?.reload();
  });
  handle(IPC.pagesOpen, async (event, payload) => {
    assertTrustedSender(event);
    await openWorkspace(mainWindow, payload);
  });
  handle(IPC.updateCheck, (event) => {
    assertTrustedSender(event);
    return checkUpdate();
  });
  handle(IPC.updateDownload, (event) => {
    assertTrustedSender(event);
    return downloadUpdate();
  });
  handle(IPC.updateInstall, async (event) => {
    assertTrustedSender(event);
    if (!app.isPackaged) throw Error("التثبيت متاح في الإصدار المثبّت فقط");
    await protection?.exit(launchUpdate);
  });
  handle(IPC.backupExport, (event, payload) => {
    assertTrustedSender(event);
    if (!mainWindow) throw Error("no window");
    return backupProfile(mainWindow, "export", payload);
  });
  handle(IPC.backupRestore, async (event, payload) => {
    assertTrustedSender(event);
    if (!mainWindow) throw Error("no window");
    if (restoring || !(await protection?.permit())) return { restored: false };
    restoring = true;
    inFlight++;
    try {
      const result = await backupProfile(mainWindow, "restore", payload);
      if ("restored" in result && result.restored) setImmediate(() => protection?.refreshRestored());
      return result;
    } finally {
      restoring = false;
      inFlight--;
    }
  });
  handle(IPC.offlineReserveStock, async (event, payload: unknown) => {
    assertTrustedSender(event);
    return (await getOfflineEngine(sendFinoraNetworkRequest)).manageStock(
      "reserve",
      reserveStockSchema.parse(payload),
    );
  });
  handle(IPC.offlineReturnStock, async (event) => {
    assertTrustedSender(event);
    return (await getOfflineEngine(sendFinoraNetworkRequest)).manageStock("return");
  });
  handle(IPC.offlineResumeStock, async (event) => {
    assertTrustedSender(event);
    return (await getOfflineEngine(sendFinoraNetworkRequest)).manageStock("resume");
  });
  handle(IPC.offlineDownloadSnapshot, async (event, payload: unknown) => {
    assertTrustedSender(event);
    return (await getOfflineEngine(sendFinoraNetworkRequest)).downloadSnapshot(
      z.boolean().optional().parse(payload),
    );
  });
  handle(IPC.offlineStatus, async (event) => {
    assertTrustedSender(event);
    try {
      return (await getOfflineEngine(sendFinoraNetworkRequest)).status();
    } catch (error) {
      recordOfflineIssue(error);
      return unavailableStatus();
    }
  });
  handle(IPC.offlineSaveSupplierDraft, async (event, payload: unknown) => {
    assertTrustedSender(event);
    return (await getOfflineEngine(sendFinoraNetworkRequest)).saveSupplierDraft(
      supplierDraftSchema.parse(payload),
    );
  });
  handle(IPC.offlineSavePosSale, async (event, payload: unknown) => {
    assertTrustedSender(event);
    const parsed = z.object({ id: z.string().uuid(), input: posSaleSchema }).strict().parse(payload);
    return (await getOfflineEngine(sendFinoraNetworkRequest)).savePosSale(parsed.id, parsed.input);
  });
  handle(IPC.offlinePrintPosSale, async (event, payload: unknown) => {
    assertTrustedSender(event);
    const receipt = await (
      await getOfflineEngine(sendFinoraNetworkRequest)
    ).posReceipt(z.string().uuid().parse(payload));
    return printLocalPosReceipt(mainWindow, receipt);
  });
  handle(IPC.offlineSynchronize, async (event) => {
    assertTrustedSender(event);
    const engine = await getOfflineEngine(sendFinoraNetworkRequest);
    await engine.synchronize();
    return engine.reconcileRestoredQuota();
  });
  handle(IPC.offlineRetry, async (event, payload: unknown) => {
    assertTrustedSender(event);
    return (await getOfflineEngine(sendFinoraNetworkRequest)).retry(z.string().uuid().parse(payload));
  });
  handle(IPC.offlineDiscardHR, async (event, payload: unknown) => {
    assertTrustedSender(event);
    return (await getOfflineEngine(sendFinoraNetworkRequest)).discardHR(z.string().uuid().parse(payload));
  });
  handle(IPC.windowMinimize, (event) => {
    assertTrustedSender(event);
    mainWindow?.minimize();
  });
  handle(IPC.windowToggleMaximize, (event) => {
    assertTrustedSender(event);
    if (!mainWindow) throw new Error("no window");
    if (mainWindow.isMaximized()) mainWindow.unmaximize();
    else mainWindow.maximize();
    return windowState(mainWindow);
  });
  handle(IPC.windowClose, (event) => {
    assertTrustedSender(event);
    mainWindow?.close();
  });
  handle(IPC.windowGetState, (event) => {
    assertTrustedSender(event);
    if (!mainWindow) throw new Error("no window");
    return windowState(mainWindow);
  });

  handle(IPC.finoraRequest, (event, payload: unknown) => {
    assertTrustedSender(event);
    const parsed = finoraRequestSchema.safeParse(payload);
    if (!parsed.success) {
      return { ok: false, failure: "refused", detail: parsed.error.issues[0]?.message ?? "invalid request" };
    }
    return sendFinoraRequest(parsed.data);
  });
  handle(IPC.customerCommandsList, async (event) => {
    assertTrustedSender(event);
    try {
      return (await getOfflineEngine(sendFinoraNetworkRequest)).customerCommands.list();
    } catch (error) {
      recordOfflineIssue(error);
      return { available: false, items: [], error: "تعذّر فتح طلبات الحفظ المشفرة؛ لم تُحذف بياناتك" };
    }
  });
  handle(IPC.stockCommandsList, async (event) => {
    assertTrustedSender(event);
    try {
      return (await getOfflineEngine(sendFinoraNetworkRequest)).stockCommands.list();
    } catch (error) {
      recordOfflineIssue(error);
      return { available: false, items: [], error: "تعذّر فتح عمليات المخزون المشفرة؛ لم تُحذف بياناتك" };
    }
  });
  handle(IPC.stockCommandsRetry, async (event, payload: unknown) => {
    assertTrustedSender(event);
    const key = customerCommandKey.parse(payload);
    const engine = await getOfflineEngine(sendFinoraNetworkRequest);
    return engine.stockCommands.retry(key, (request) => sendFinoraNetworkRequest(request, engine.serverUrl));
  });
  handle(IPC.stockCommandsAcknowledge, async (event, payload: unknown) => {
    assertTrustedSender(event);
    const input = customerAcknowledgement.parse(payload);
    return (await getOfflineEngine(sendFinoraNetworkRequest)).stockCommands.acknowledge(
      input.key,
      input.path,
      input.scope,
    );
  });
  handle(IPC.customerCommandsRetry, async (event, payload: unknown) => {
    assertTrustedSender(event);
    const key = customerCommandKey.parse(payload);
    const engine = await getOfflineEngine(sendFinoraNetworkRequest);
    return engine.customerCommands.retry(key, (request) =>
      sendFinoraNetworkRequest(request, engine.serverUrl),
    );
  });
  handle(IPC.customerCommandsAcknowledge, async (event, payload: unknown) => {
    assertTrustedSender(event);
    const input = customerAcknowledgement.parse(payload);
    return (await getOfflineEngine(sendFinoraNetworkRequest)).customerCommands.acknowledge(
      input.key,
      input.path,
      input.scope,
    );
  });
  handle(IPC.finoraSubmitForm, (event, payload: unknown) => {
    assertTrustedSender(event);
    const parsed = finoraFormSchema.safeParse(payload);
    if (!parsed.success) {
      return { ok: false, failure: "refused", detail: parsed.error.issues[0]?.message ?? "invalid form" };
    }
    return sendFinoraForm(parsed.data);
  });
  handle(IPC.sessionClear, async (event) => {
    assertTrustedSender(event);
    await clearFinoraSession();
  });

  handle(IPC.printOpen, async (event, payload: unknown) => {
    assertTrustedSender(event);
    const parsed = printRequestSchema.safeParse(payload);
    if (!parsed.success) throw new Error("invalid print request");
    await openPrintWindow(mainWindow, parsed.data);
  });
  handle(IPC.reportExport, async (event, payload: unknown) => {
    assertTrustedSender(event);
    const parsed = reportExportSchema.safeParse(payload);
    if (!parsed.success) throw new Error("invalid report export");
    return exportReport(mainWindow, parsed.data);
  });
  handle(IPC.openInFinora, async (event, payload: unknown) => {
    assertTrustedSender(event);
    const parsed = finoraPagePathSchema.safeParse(payload);
    const serverUrl = await getServerUrl();
    if (!parsed.success || !serverUrl) throw new Error("invalid FINORA page");
    await shell.openExternal(new URL(parsed.data, `${serverUrl}/`).toString());
  });

  handle(IPC.autoStartGet, (event) => {
    assertTrustedSender(event);
    return app.getLoginItemSettings(loginItemTarget()).openAtLogin;
  });
  handle(IPC.autoStartSet, (event, payload: unknown) => {
    assertTrustedSender(event);
    if (typeof payload !== "boolean") throw new Error("invalid auto-start value");
    app.setLoginItemSettings({ openAtLogin: payload, ...loginItemTarget() });
    return app.getLoginItemSettings(loginItemTarget()).openAtLogin;
  });

  handle(IPC.configGet, (event) => {
    assertTrustedSender(event);
    return getConfig();
  });
  handle(IPC.configSetServer, async (event, payload: unknown) => {
    assertTrustedSender(event);
    const parsed = serverUrlSchema.safeParse(payload);
    if (!parsed.success) throw new Error("invalid server url");
    const current = await getConfig();
    if (current.serverUrl !== parsed.data) await clearFinoraSession();
    return setServerUrl(parsed.data);
  });
  handle(IPC.configRememberIdentity, (event, payload: unknown) => {
    assertTrustedSender(event);
    const parsed = rememberIdentitySchema.safeParse(payload);
    if (!parsed.success) throw new Error("invalid identity");
    return rememberIdentity(parsed.data.tenantSlug, parsed.data.username);
  });
}

/** The installed exe starts by itself; an unpackaged run (electron .) must pass the app folder. */
function loginItemTarget(): { path?: string; args?: string[] } {
  return app.isPackaged ? {} : { path: process.execPath, args: [path.resolve(app.getAppPath())] };
}

function trustedMedia(id: number | undefined, url: string) {
  if (!mainWindow || id !== mainWindow.webContents.id) return false;
  try {
    return DEV_SERVER_URL
      ? new URL(url).origin === rendererOrigin()
      : url === "file://" ||
          url === "null" ||
          url.split("#")[0]?.split("?")[0] === pathToFileURL(RENDERER_FILE).href;
  } catch {
    return false;
  }
}
function hardenSessions(): void {
  const remote = finoraSession();
  remote.webRequest.onBeforeRequest((details, callback) => {
    if (["POST", "PUT", "PATCH", "DELETE"].includes(details.method)) {
      if (protection?.leaving()) {
        callback({ cancel: true });
        return;
      }
      activeWriteRequests.add(details.id);
      trackWorkspaceWrite(details.id, details.webContentsId);
    }
    callback({ cancel: false });
  });
  remote.webRequest.onCompleted((details) => {
    activeWriteRequests.delete(details.id);
    finishWorkspaceWrite(details.id);
  });
  remote.webRequest.onErrorOccurred((details) => {
    activeWriteRequests.delete(details.id);
    finishWorkspaceWrite(details.id);
  });
  for (const ses of [session.defaultSession, finoraSession()]) {
    ses.setPermissionCheckHandler(
      (wc, permission, requestingOrigin) =>
        permission === "media" &&
        !!wc &&
        approvedMedia.has(wc.id) &&
        (isWorkspaceMediaAllowed(wc.id, requestingOrigin) || trustedMedia(wc.id, requestingOrigin)),
    );
    ses.setPermissionRequestHandler((wc, permission, callback, details) => {
      if (
        permission !== "media" ||
        !(
          isWorkspaceMediaAllowed(wc.id, details.requestingUrl) || trustedMedia(wc.id, details.requestingUrl)
        ) ||
        !mainWindow
      ) {
        callback(false);
        return;
      }
      void dialog
        .showMessageBox(mainWindow, {
          type: "question",
          message: "السماح لصفحة FINORA باستخدام الكاميرا أو الميكروفون؟",
          detail: "اسمح فقط عند بدء المسح أو التسجيل بنفسك.",
          buttons: ["رفض", "سماح"],
          defaultId: 0,
          cancelId: 0,
        })
        .then(
          (result) => {
            if (result.response === 1) {
              approvedMedia.add(wc.id);
              wc.once("destroyed", () => approvedMedia.delete(wc.id));
            }
            callback(result.response === 1);
          },
          () => callback(false),
        );
    });
  }
}

app.on("web-contents-created", (_event, contents) => {
  contents.on("will-attach-webview", (event) => event.preventDefault());
});

registerMediaScheme();

// Isolated profile for automated tests (separate cookies/settings).
if (process.env.FINORA_USER_DATA_DIR) app.setPath("userData", process.env.FINORA_USER_DATA_DIR);

const gotLock = app.requestSingleInstanceLock();
if (!gotLock) {
  app.quit();
} else {
  app.on("second-instance", () => {
    if (!mainWindow) return;
    if (mainWindow.isMinimized()) mainWindow.restore();
    mainWindow.focus();
  });

  app
    .whenReady()
    .then(() => {
      app.setAppUserModelId("company.finora.management");
      hardenSessions();
      handleMediaProtocol();
      registerIpc();
      const syncTimer = setInterval(() => {
        if (restoring || protection?.leaving()) return;
        void getOfflineEngine(sendFinoraNetworkRequest)
          .then(async (engine) => {
            inFlight++;
            try {
              await engine.synchronize();
              await engine.reconcileRestoredQuota();
            } finally {
              inFlight--;
            }
          })
          .catch(recordOfflineIssue);
      }, 15_000);
      syncTimer.unref();
      mainWindow = createMainWindow();
      mainWindow.on("closed", () => {
        mainWindow = null;
      });
    })
    .catch((error: unknown) => {
      console.error("[main] startup failed", error);
      app.exit(1);
    });

  app.on("window-all-closed", () => app.quit());
}
