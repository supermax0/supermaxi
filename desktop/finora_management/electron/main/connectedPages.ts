import { app, BrowserWindow, dialog } from "electron";
import { z } from "zod";
import { getServerUrl } from "./config";
import { finoraSession, sendFinoraNetworkRequest } from "./finoraHttp";
import { windowGeometry } from "./windowGeometry";
import { WORKSPACE_PAGES, type WorkspacePageId } from "../../shared/workspacePages";

const windows = new Map<WorkspacePageId, BrowserWindow>();
const permissions = new Map<number, string>();
const requests = new Map<number, number>();
const capabilities = z.object({ ok: z.literal(true), pages: z.array(z.string()) });
export function trackWorkspaceWrite(request: number, contents: number | undefined) {
  if (contents !== undefined) requests.set(request, contents);
}
export function finishWorkspaceWrite(request: number) {
  requests.delete(request);
}

export function isWorkspaceMediaAllowed(id: number | undefined, origin: string) {
  if (id === undefined || !permissions.has(id)) return false;
  try {
    return new URL(origin).origin === permissions.get(id);
  } catch {
    return false;
  }
}

export async function openWorkspace(parent: BrowserWindow | null, input: unknown) {
  const id = z.enum(Object.keys(WORKSPACE_PAGES) as [WorkspacePageId, ...WorkspacePageId[]]).parse(input);
  const response = await sendFinoraNetworkRequest({ method: "GET", path: "/api/v1/desktop/workspace" });
  if (!response.ok || !capabilities.parse(response.data).pages.includes(id))
    throw Error("هذه الصفحة غير متاحة لحسابك أو تحتاج تحديث السيرفر");
  const server = await getServerUrl();
  if (!server) throw Error("حدد خادم FINORA أولاً");
  const existing = windows.get(id);
  if (existing && !existing.isDestroyed()) {
    existing.show();
    existing.focus();
    return;
  }
  const definition = WORKSPACE_PAGES[id],
    origin = new URL(server).origin;
  const win = new BrowserWindow({
    ...windowGeometry(parent?.getContentBounds() ?? { width: 1200, height: 800 }),
    parent: parent ?? undefined,
    title: `${definition.title} — FINORA`,
    autoHideMenuBar: true,
    backgroundColor: "#f6f5fa",
    show: false,
    webPreferences: {
      session: finoraSession(),
      sandbox: true,
      contextIsolation: true,
      nodeIntegration: false,
      webSecurity: true,
      devTools: !app.isPackaged,
    },
  });
  const contentsId = win.webContents.id;
  let waitingForSave = false;
  win.on("close", (event) => {
    if (![...requests.values()].includes(contentsId)) return;
    event.preventDefault();
    if (waitingForSave) return;
    waitingForSave = true;
    void dialog
      .showMessageBox(win, {
        type: "info",
        message: "انتظر اكتمال حفظ الصفحة قبل إغلاقها.",
        buttons: ["انتظار"],
      })
      .finally(() => {
        waitingForSave = false;
      })
      .catch(() => console.warn("[workspace] save-wait dialog could not open"));
  });
  windows.set(id, win);
  if (id === "messages" || id === "cameraAudit") permissions.set(win.webContents.id, origin);
  const sameOrigin = (url: string) => {
    try {
      return new URL(url).origin === origin;
    } catch {
      return false;
    }
  };
  win.webContents.on("will-navigate", (event, url) => {
    if (!sameOrigin(url)) event.preventDefault();
  });
  win.webContents.on("will-redirect", (event, url) => {
    if (!sameOrigin(url)) event.preventDefault();
  });
  win.webContents.setWindowOpenHandler(({ url }) => {
    if (!sameOrigin(url)) return { action: "deny" };
    // Print and detail popups inherit the restricted session, never the privileged preload.
    return {
      action: "allow",
      overrideBrowserWindowOptions: {
        parent: win,
        autoHideMenuBar: true,
        webPreferences: {
          session: finoraSession(),
          sandbox: true,
          contextIsolation: true,
          nodeIntegration: false,
          webSecurity: true,
        },
      },
    };
  });
  win.webContents.on("dom-ready", () => {
    void win.webContents.insertCSS(
      "body.finora-app .sidebar,body.finora-app .topbar{display:none!important} body.finora-app .app{grid-template-columns:minmax(0,1fr)!important} body.finora-app .content{margin:0!important;min-width:0!important;width:100%!important} body.finora-app .page-main{margin:0!important;width:100%!important}",
    );
    void win.webContents
      .executeJavaScript(
        `(() => {
      const fields = new Map();
      const value = e => e.isContentEditable ? e.innerHTML : e.type === 'checkbox' || e.type === 'radio' ? e.checked : e.value;
      document.addEventListener('focusin', e => { if(e.target.matches('input:not([type=search]):not([type=password]),textarea,select,[contenteditable=true]') && !fields.has(e.target)) fields.set(e.target,value(e.target)); }, true);
      document.addEventListener('submit', e => { queueMicrotask(() => { if (!e.defaultPrevented && e.target instanceof HTMLFormElement) for (const node of fields.keys()) if (e.target.contains(node)) fields.delete(node); }); }, true);
      window.addEventListener('beforeunload', e => { if([...fields].some(([node,initial]) => node.isConnected && node.getClientRects().length && value(node)!==initial)) { e.preventDefault(); e.returnValue=''; }});
      window.__finoraHasDraft = () => [...fields].some(([node,initial]) => node.isConnected && node.getClientRects().length && value(node)!==initial);
    })()`,
      )
      .catch(() => console.warn("[workspace] exit protection could not load"));
  });
  win.webContents.on("will-prevent-unload", (event) => {
    if (
      dialog.showMessageBoxSync(win, {
        type: "warning",
        buttons: ["البقاء", "مغادرة دون حفظ"],
        defaultId: 0,
        cancelId: 0,
        message: "لديك تعديلات غير محفوظة في هذه الصفحة",
      }) === 1
    )
      event.preventDefault();
  });
  win.once("ready-to-show", () => win.show());
  win.on("closed", () => {
    windows.delete(id);
    permissions.delete(contentsId);
  });
  win.webContents.on("render-process-gone", (_event, detail) => {
    if (detail.reason === "clean-exit" || win.isDestroyed()) return;
    void dialog
      .showMessageBox(win, {
        type: "error",
        message: "تعطلت واجهة الصفحة المتصلة",
        detail: "أعد فتحها وراجع نتيجة الحفظ قبل تكرار أي عملية.",
        buttons: ["إعادة فتح الصفحة", "البقاء"],
        defaultId: 0,
        cancelId: 1,
      })
      .then((result) => {
        if (result.response === 0 && !win.isDestroyed()) win.reload();
      })
      .catch(() => console.warn("[workspace] recovery dialog could not open"));
  });
  win.webContents.on("did-fail-load", (_event, code, _description, _url, mainFrame) => {
    if (mainFrame && code !== -3 && !win.isDestroyed())
      void dialog.showMessageBox(win, {
        type: "error",
        message: "تعذّر تحميل الصفحة. تحقق من الاتصال ثم أعد فتحها.",
        buttons: ["حسناً"],
      });
  });
  await win.loadURL(new URL(definition.path, server).toString());
}

export async function workspaceHasDrafts() {
  const dirty = await Promise.all(
    [...windows.values()]
      .filter((w) => !w.isDestroyed())
      .map((w) => w.webContents.executeJavaScript("Boolean(window.__finoraHasDraft?.())").catch(() => true)),
  );
  return dirty.some(Boolean);
}
export function closeWorkspaces() {
  for (const win of windows.values()) if (!win.isDestroyed()) win.destroy();
  windows.clear();
  permissions.clear();
}
