/** Sandboxed preload: exposes a narrow, typed bridge. No Node APIs reach the renderer. */
import { contextBridge, ipcRenderer, type IpcRendererEvent } from "electron";
import { IPC } from "../../shared/channels";
import type { FinoraDesktopBridge, WindowState } from "../../shared/ipc";

const bridge: FinoraDesktopBridge = {
  lifecycle: {
    confirmLeave: () => ipcRenderer.invoke(IPC.confirmLeave),
    activity: (input) => ipcRenderer.invoke(IPC.activity, input),
    reload: () => ipcRenderer.invoke(IPC.reload),
  },
  pages: { open: (id) => ipcRenderer.invoke(IPC.pagesOpen, id) },
  updates: {
    check: () => ipcRenderer.invoke(IPC.updateCheck),
    download: () => ipcRenderer.invoke(IPC.updateDownload),
    install: () => ipcRenderer.invoke(IPC.updateInstall),
  },
  backup: {
    export: (password) => ipcRenderer.invoke(IPC.backupExport, password),
    restore: (password) => ipcRenderer.invoke(IPC.backupRestore, password),
  },
  stockRecovery: {
    list: () => ipcRenderer.invoke(IPC.stockCommandsList),
    retry: (key) => ipcRenderer.invoke(IPC.stockCommandsRetry, key),
    acknowledge: (input) => ipcRenderer.invoke(IPC.stockCommandsAcknowledge, input),
  },
  customerRecovery: {
    list: () => ipcRenderer.invoke(IPC.customerCommandsList),
    retry: (key) => ipcRenderer.invoke(IPC.customerCommandsRetry, key),
    acknowledge: (input) => ipcRenderer.invoke(IPC.customerCommandsAcknowledge, input),
  },
  offline: {
    savePosSale: (id, input) => ipcRenderer.invoke(IPC.offlineSavePosSale, { id, input }),
    printPosSale: (id) => ipcRenderer.invoke(IPC.offlinePrintPosSale, id),
    reserveStock: (input) => ipcRenderer.invoke(IPC.offlineReserveStock, input),
    returnStock: () => ipcRenderer.invoke(IPC.offlineReturnStock),
    resumeStockRequest: () => ipcRenderer.invoke(IPC.offlineResumeStock),
    downloadSnapshot: (restart) => ipcRenderer.invoke(IPC.offlineDownloadSnapshot, restart),
    status: () => ipcRenderer.invoke(IPC.offlineStatus),
    saveSupplierDraft: (input) => ipcRenderer.invoke(IPC.offlineSaveSupplierDraft, input),
    synchronize: () => ipcRenderer.invoke(IPC.offlineSynchronize),
    retry: (id) => ipcRenderer.invoke(IPC.offlineRetry, id),
    discardHR: (id) => ipcRenderer.invoke(IPC.offlineDiscardHR, id),
  },
  window: {
    minimize: () => ipcRenderer.invoke(IPC.windowMinimize),
    toggleMaximize: () => ipcRenderer.invoke(IPC.windowToggleMaximize),
    close: () => ipcRenderer.invoke(IPC.windowClose),
    getState: () => ipcRenderer.invoke(IPC.windowGetState),
    onState(listener) {
      const handler = (_event: IpcRendererEvent, state: WindowState) => listener(state);
      ipcRenderer.on(IPC.windowState, handler);
      return () => {
        ipcRenderer.removeListener(IPC.windowState, handler);
      };
    },
  },
  finora: {
    request: (request) => ipcRenderer.invoke(IPC.finoraRequest, request),
    submitForm: (request) => ipcRenderer.invoke(IPC.finoraSubmitForm, request),
    clearSession: () => ipcRenderer.invoke(IPC.sessionClear),
  },
  print: {
    open: (request) => ipcRenderer.invoke(IPC.printOpen, request),
  },
  reports: {
    export: (request) => ipcRenderer.invoke(IPC.reportExport, request),
  },
  app: {
    openInFinora: (path) => ipcRenderer.invoke(IPC.openInFinora, path),
    getAutoStart: () => ipcRenderer.invoke(IPC.autoStartGet),
    setAutoStart: (enabled) => ipcRenderer.invoke(IPC.autoStartSet, enabled),
  },
  config: {
    get: () => ipcRenderer.invoke(IPC.configGet),
    setServer: (serverUrl) => ipcRenderer.invoke(IPC.configSetServer, serverUrl),
    rememberIdentity: (identity) => ipcRenderer.invoke(IPC.configRememberIdentity, identity),
  },
};

contextBridge.exposeInMainWorld("finoraDesktop", bridge);
