import path from "node:path";
import os from "node:os";
import type { ElectronApplication } from "@playwright/test";
import type { FinoraDesktopBridge } from "../shared/ipc";

/** Tests explicitly accept discarding their temporary forms; production close guards remain active. */
export async function closeIsolatedApp(application: ElectronApplication) {
  const profile = await application.evaluate(({ app }) => app.getPath("userData"));
  if (path.dirname(profile) !== path.resolve(os.tmpdir()) || !path.basename(profile).startsWith("finora-"))
    throw Error("Refusing to close a non-test FINORA profile");
  await application.evaluate(({ dialog }) => {
    dialog.showMessageBoxSync = () => 1;
    dialog.showMessageBox = async () => ({ response: 0, checkboxChecked: false });
  });
  const page = application.windows()[0];
  try {
    if (page && !page.isClosed()) {
      let permitted = false;
      for (let attempt = 0; attempt < 100; attempt++) {
        permitted = await page.evaluate(async () => {
          const bridge = (window as Window & { finoraDesktop?: FinoraDesktopBridge }).finoraDesktop;
          return bridge?.lifecycle ? bridge.lifecycle.confirmLeave() : true;
        });
        if (permitted) break;
        await page.waitForTimeout(100);
      }
      if (!permitted) throw Error("A test save did not finish before shutdown");
    }
    await application.close();
  } catch (error) {
    await application.evaluate(({ BrowserWindow }) => {
      for (const win of BrowserWindow.getAllWindows()) win.destroy();
    });
    await application.close();
    throw error;
  }
}
