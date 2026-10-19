import { BrowserWindow, dialog } from "electron";
import { closeWorkspaces, workspaceHasDrafts } from "./connectedPages";
import { flushOfflineWrites } from "./offlineRuntime";

export interface Activity {
  dirty: boolean;
  saving: boolean;
}
export function mayLeave(activity: Activity, decide: () => boolean): boolean {
  return !activity.saving && (!activity.dirty || decide());
}

export function protectWindow(win: BrowserWindow, isBusy: () => boolean = () => false) {
  let activity: Activity = { dirty: false, saving: false },
    accepted = false,
    negotiating = false;
  const permit = async () => {
    const current = {
      ...activity,
      saving: activity.saving || isBusy(),
      dirty: activity.dirty || (await workspaceHasDrafts()),
    };
    if (current.saving) {
      await dialog.showMessageBox(win, {
        type: "info",
        message: "توجد عملية حفظ جارية. انتظر ظهور نتيجتها قبل إغلاق التطبيق.",
        buttons: ["انتظار"],
      });
      return false;
    }
    return mayLeave(
      current,
      () =>
        dialog.showMessageBoxSync(win, {
          type: "warning",
          message: "لديك تعديلات غير محفوظة",
          detail: "الحقول التي لم تحفظ ستُفقد. العمليات المثبتة في سجل الأوفلاين تبقى محفوظة للمزامنة.",
          buttons: ["البقاء", "خروج دون حفظ"],
          defaultId: 0,
          cancelId: 0,
        }) === 1,
    );
  };
  const exit = async (beforeClose?: () => Promise<void>) => {
    if (negotiating || win.isDestroyed()) return false;
    negotiating = true;
    try {
      if (!(await permit())) return false;
      await flushOfflineWrites();
      if (beforeClose) await beforeClose();
      accepted = true;
      closeWorkspaces();
      win.close();
      return true;
    } catch (error) {
      await dialog.showMessageBox(win, {
        type: "error",
        message: "تعذر إكمال العملية بأمان؛ بقي التطبيق مفتوحاً",
        detail: error instanceof Error ? error.message : "راجع التخزين المحلي",
        buttons: ["حسناً"],
      });
      return false;
    } finally {
      negotiating = false;
    }
  };
  win.on("close", (event) => {
    if (!accepted) {
      event.preventDefault();
      void exit();
    }
  });
  let recovering = false;
  const recover = async () => {
    if (recovering || win.isDestroyed()) return;
    recovering = true;
    try {
      const choice = await dialog.showMessageBox(win, {
        type: "error",
        message: "توقفت واجهة FINORA عن الاستجابة",
        detail: "يمكن إعادة فتحها. راجع سجل المزامنة قبل تكرار أي عملية لم تظهر نتيجتها.",
        buttons: ["إعادة فتح الواجهة", "البقاء"],
        defaultId: 0,
        cancelId: 1,
      });
      if (choice.response === 0 && !win.isDestroyed()) {
        activity = { dirty: false, saving: false };
        win.reload();
      }
    } finally {
      recovering = false;
    }
  };
  win.webContents.on("render-process-gone", (_event, detail) => {
    if (detail.reason !== "clean-exit") {
      activity.saving = false;
      void recover();
    }
  });
  win.webContents.on("did-fail-load", (_event, code, _description, _url, mainFrame) => {
    if (mainFrame && code !== -3) void recover();
  });
  win.on("unresponsive", () => void recover());
  return {
    refreshRestored() {
      activity = { dirty: false, saving: false };
      closeWorkspaces();
      if (!win.isDestroyed()) win.reload();
    },
    leaving: () => negotiating,
    permit,
    update(next: Activity) {
      activity = next;
    },
    exit,
    async reload() {
      if (await permit()) {
        await flushOfflineWrites();
        activity = { dirty: false, saving: false };
        win.reload();
      }
    },
  };
}
