import path from "node:path";
import { app, BrowserWindow, ipcMain, screen, session, shell, type IpcMainInvokeEvent } from "electron";
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
    (DEV_SERVER_URL ? frame.url.startsWith(rendererOrigin()) : frame.url.startsWith("file://"));
  if (!trusted) throw new Error("untrusted IPC sender");
}

function windowState(win: BrowserWindow): WindowState {
  return { maximized: win.isMaximized(), focused: win.isFocused() };
}

const DEFAULT_SIZE = { width: 1440, height: 900 };
const MIN_SIZE = { width: 1180, height: 700 };

function createMainWindow(): BrowserWindow {
  // 1440×900 by default, shrunk to the work area on smaller screens (never below the minimum).
  const area = screen.getPrimaryDisplay().workAreaSize;
  const win = new BrowserWindow({
    width: Math.max(Math.min(DEFAULT_SIZE.width, area.width), MIN_SIZE.width),
    height: Math.max(Math.min(DEFAULT_SIZE.height, area.height), MIN_SIZE.height),
    center: true,
    minWidth: MIN_SIZE.width,
    minHeight: MIN_SIZE.height,
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
    if (!url.startsWith(rendererOrigin())) event.preventDefault();
  });

  if (DEV_SERVER_URL) void win.loadURL(DEV_SERVER_URL);
  else void win.loadFile(RENDERER_FILE);
  return win;
}

function registerIpc(): void {
  ipcMain.handle(IPC.offlineReserveStock, async (event, payload: unknown) => {
    assertTrustedSender(event);
    return (await getOfflineEngine(sendFinoraNetworkRequest)).manageStock(
      "reserve",
      reserveStockSchema.parse(payload),
    );
  });
  ipcMain.handle(IPC.offlineReturnStock, async (event) => {
    assertTrustedSender(event);
    return (await getOfflineEngine(sendFinoraNetworkRequest)).manageStock("return");
  });
  ipcMain.handle(IPC.offlineResumeStock, async (event) => {
    assertTrustedSender(event);
    return (await getOfflineEngine(sendFinoraNetworkRequest)).manageStock("resume");
  });
  ipcMain.handle(IPC.offlineDownloadSnapshot, async (event, payload: unknown) => {
    assertTrustedSender(event);
    return (await getOfflineEngine(sendFinoraNetworkRequest)).downloadSnapshot(
      z.boolean().optional().parse(payload),
    );
  });
  ipcMain.handle(IPC.offlineStatus, async (event) => {
    assertTrustedSender(event);
    try {
      return (await getOfflineEngine(sendFinoraNetworkRequest)).status();
    } catch (error) {
      recordOfflineIssue(error);
      return unavailableStatus();
    }
  });
  ipcMain.handle(IPC.offlineSaveSupplierDraft, async (event, payload: unknown) => {
    assertTrustedSender(event);
    return (await getOfflineEngine(sendFinoraNetworkRequest)).saveSupplierDraft(
      supplierDraftSchema.parse(payload),
    );
  });
  ipcMain.handle(IPC.offlineSavePosSale, async (event, payload: unknown) => {
    assertTrustedSender(event);
    const parsed = z.object({ id: z.string().uuid(), input: posSaleSchema }).strict().parse(payload);
    return (await getOfflineEngine(sendFinoraNetworkRequest)).savePosSale(parsed.id, parsed.input);
  });
  ipcMain.handle(IPC.offlinePrintPosSale, async (event, payload: unknown) => {
    assertTrustedSender(event);
    const receipt = await (
      await getOfflineEngine(sendFinoraNetworkRequest)
    ).posReceipt(z.string().uuid().parse(payload));
    return printLocalPosReceipt(mainWindow, receipt);
  });
  ipcMain.handle(IPC.offlineSynchronize, async (event) => {
    assertTrustedSender(event);
    return (await getOfflineEngine(sendFinoraNetworkRequest)).synchronize();
  });
  ipcMain.handle(IPC.offlineRetry, async (event, payload: unknown) => {
    assertTrustedSender(event);
    return (await getOfflineEngine(sendFinoraNetworkRequest)).retry(z.string().uuid().parse(payload));
  });
  ipcMain.handle(IPC.offlineDiscardHR, async (event, payload: unknown) => {
    assertTrustedSender(event);
    return (await getOfflineEngine(sendFinoraNetworkRequest)).discardHR(z.string().uuid().parse(payload));
  });
  ipcMain.handle(IPC.windowMinimize, (event) => {
    assertTrustedSender(event);
    mainWindow?.minimize();
  });
  ipcMain.handle(IPC.windowToggleMaximize, (event) => {
    assertTrustedSender(event);
    if (!mainWindow) throw new Error("no window");
    if (mainWindow.isMaximized()) mainWindow.unmaximize();
    else mainWindow.maximize();
    return windowState(mainWindow);
  });
  ipcMain.handle(IPC.windowClose, (event) => {
    assertTrustedSender(event);
    mainWindow?.close();
  });
  ipcMain.handle(IPC.windowGetState, (event) => {
    assertTrustedSender(event);
    if (!mainWindow) throw new Error("no window");
    return windowState(mainWindow);
  });

  ipcMain.handle(IPC.finoraRequest, (event, payload: unknown) => {
    assertTrustedSender(event);
    const parsed = finoraRequestSchema.safeParse(payload);
    if (!parsed.success) {
      return { ok: false, failure: "refused", detail: parsed.error.issues[0]?.message ?? "invalid request" };
    }
    return sendFinoraRequest(parsed.data);
  });
  ipcMain.handle(IPC.customerCommandsList, async (event) => {
    assertTrustedSender(event);
    try {
      return (await getOfflineEngine(sendFinoraNetworkRequest)).customerCommands.list();
    } catch (error) {
      recordOfflineIssue(error);
      return { available: false, items: [], error: "تعذّر فتح طلبات الحفظ المشفرة؛ لم تُحذف بياناتك" };
    }
  });
  ipcMain.handle(IPC.stockCommandsList, async (event) => {
    assertTrustedSender(event);
    try {
      return (await getOfflineEngine(sendFinoraNetworkRequest)).stockCommands.list();
    } catch (error) {
      recordOfflineIssue(error);
      return { available: false, items: [], error: "تعذّر فتح عمليات المخزون المشفرة؛ لم تُحذف بياناتك" };
    }
  });
  ipcMain.handle(IPC.stockCommandsRetry, async (event, payload: unknown) => {
    assertTrustedSender(event);
    const key = customerCommandKey.parse(payload);
    const engine = await getOfflineEngine(sendFinoraNetworkRequest);
    return engine.stockCommands.retry(key, (request) => sendFinoraNetworkRequest(request, engine.serverUrl));
  });
  ipcMain.handle(IPC.stockCommandsAcknowledge, async (event, payload: unknown) => {
    assertTrustedSender(event);
    const input = customerAcknowledgement.parse(payload);
    return (await getOfflineEngine(sendFinoraNetworkRequest)).stockCommands.acknowledge(
      input.key,
      input.path,
      input.scope,
    );
  });
  ipcMain.handle(IPC.customerCommandsRetry, async (event, payload: unknown) => {
    assertTrustedSender(event);
    const key = customerCommandKey.parse(payload);
    const engine = await getOfflineEngine(sendFinoraNetworkRequest);
    return engine.customerCommands.retry(key, (request) =>
      sendFinoraNetworkRequest(request, engine.serverUrl),
    );
  });
  ipcMain.handle(IPC.customerCommandsAcknowledge, async (event, payload: unknown) => {
    assertTrustedSender(event);
    const input = customerAcknowledgement.parse(payload);
    return (await getOfflineEngine(sendFinoraNetworkRequest)).customerCommands.acknowledge(
      input.key,
      input.path,
      input.scope,
    );
  });
  ipcMain.handle(IPC.finoraSubmitForm, (event, payload: unknown) => {
    assertTrustedSender(event);
    const parsed = finoraFormSchema.safeParse(payload);
    if (!parsed.success) {
      return { ok: false, failure: "refused", detail: parsed.error.issues[0]?.message ?? "invalid form" };
    }
    return sendFinoraForm(parsed.data);
  });
  ipcMain.handle(IPC.sessionClear, async (event) => {
    assertTrustedSender(event);
    await clearFinoraSession();
  });

  ipcMain.handle(IPC.printOpen, async (event, payload: unknown) => {
    assertTrustedSender(event);
    const parsed = printRequestSchema.safeParse(payload);
    if (!parsed.success) throw new Error("invalid print request");
    await openPrintWindow(mainWindow, parsed.data);
  });
  ipcMain.handle(IPC.reportExport, async (event, payload: unknown) => {
    assertTrustedSender(event);
    const parsed = reportExportSchema.safeParse(payload);
    if (!parsed.success) throw new Error("invalid report export");
    return exportReport(mainWindow, parsed.data);
  });
  ipcMain.handle(IPC.openInFinora, async (event, payload: unknown) => {
    assertTrustedSender(event);
    const parsed = finoraPagePathSchema.safeParse(payload);
    const serverUrl = await getServerUrl();
    if (!parsed.success || !serverUrl) throw new Error("invalid FINORA page");
    await shell.openExternal(new URL(parsed.data, `${serverUrl}/`).toString());
  });

  ipcMain.handle(IPC.autoStartGet, (event) => {
    assertTrustedSender(event);
    return app.getLoginItemSettings(loginItemTarget()).openAtLogin;
  });
  ipcMain.handle(IPC.autoStartSet, (event, payload: unknown) => {
    assertTrustedSender(event);
    if (typeof payload !== "boolean") throw new Error("invalid auto-start value");
    app.setLoginItemSettings({ openAtLogin: payload, ...loginItemTarget() });
    return app.getLoginItemSettings(loginItemTarget()).openAtLogin;
  });

  ipcMain.handle(IPC.configGet, (event) => {
    assertTrustedSender(event);
    return getConfig();
  });
  ipcMain.handle(IPC.configSetServer, async (event, payload: unknown) => {
    assertTrustedSender(event);
    const parsed = serverUrlSchema.safeParse(payload);
    if (!parsed.success) throw new Error("invalid server url");
    const current = await getConfig();
    if (current.serverUrl !== parsed.data) await clearFinoraSession();
    return setServerUrl(parsed.data);
  });
  ipcMain.handle(IPC.configRememberIdentity, (event, payload: unknown) => {
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

function hardenSessions(): void {
  for (const ses of [session.defaultSession, finoraSession()]) {
    ses.setPermissionRequestHandler((_wc, _permission, callback) => callback(false));
    ses.setPermissionCheckHandler(() => false);
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
        void getOfflineEngine(sendFinoraNetworkRequest)
          .then((engine) => engine.synchronize())
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
