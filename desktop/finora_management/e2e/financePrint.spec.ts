import { readFileSync, writeFileSync, mkdtempSync, rmSync, mkdirSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { _electron as electron, expect, test } from "@playwright/test";
import { startFinoraStub } from "./finoraStub";

test("actual cashier/admin invoice and finance templates print as A4 PDFs without layout overflow", async () => {
  test.setTimeout(120000);
  const profile = mkdtempSync(path.join(tmpdir(), "finora-print-e2e-"));
  if (
    path.dirname(profile) !== path.resolve(tmpdir()) ||
    !path.basename(profile).startsWith("finora-print-e2e-")
  )
    throw Error("Unsafe test cleanup");
  const stub = await startFinoraStub({ finance: true });
  const app = await electron.launch({
    args: [path.resolve(__dirname, "..")],
    cwd: path.resolve(__dirname, ".."),
    env: { ...process.env, FINORA_SERVER_URL: stub.url, FINORA_USER_DATA_DIR: profile },
  });
  const outputs = path.resolve(__dirname, "../../../tests/_artifacts");
  mkdirSync(outputs, { recursive: true });
  try {
    for (const name of [
      "invoice-print-admin-single",
      "invoice-print-cashier-batch",
      "finance-voucher",
      "finance-customer-installments",
      "finance-standalone-debt",
      "finance-loan",
      "finance-report",
    ]) {
      const html = readFileSync(path.join(outputs, `${name}.html`), "utf8");
      const result = await app.evaluate(async ({ BrowserWindow, session }, html) => {
        const partition = `print-test-${Date.now()}`;
        session
          .fromPartition(partition)
          .webRequest.onBeforeRequest({ urls: ["http://*/*", "https://*/*"] }, (_details, callback) =>
            callback({ cancel: true }),
          );
        const win = new BrowserWindow({
          show: false,
          width: 900,
          height: 1200,
          webPreferences: {
            partition,
            sandbox: true,
            nodeIntegration: false,
            contextIsolation: true,
            backgroundThrottling: false,
          },
        });
        try {
          await win.loadURL(`data:text/html;charset=utf-8,${encodeURIComponent(html)}`);
          await win.webContents.executeJavaScript("document.fonts.ready.then(()=>true)");
          const codes = await win.webContents.executeJavaScript(`new Promise((resolve,reject)=>{
            const started=Date.now();const check=()=>{
              const roots=[...document.querySelectorAll('[data-finora-print-ready]')];
              if(roots.every(r=>r.dataset.finoraPrintReady==='ready'))return resolve([...document.querySelectorAll('[data-invoice-barcode], [data-invoice-qrcode] img')].map(i=>({tag:i.tagName,complete:i.complete,width:i.naturalWidth})));
              if(Date.now()-started>5000)return reject(Error('Invoice printable codes are not ready'));
              setTimeout(check,50);
            };check();})`);
          const pdf = (
            await win.webContents.printToPDF({
              printBackground: true,
              preferCSSPageSize: true,
              pageSize: "A4",
            })
          ).toString("base64");
          return { pdf, codes };
        } finally {
          win.close();
        }
      }, html);
      const pdf = Buffer.from(result.pdf, "base64");
      expect(pdf.subarray(0, 5).toString()).toBe("%PDF-");
      expect(pdf.length).toBeGreaterThan(5000);
      if (name.startsWith("invoice-")) {
        expect(result.codes.length).toBeGreaterThanOrEqual(2);
        for (const code of result.codes) expect(code).toMatchObject({ tag: "IMG", complete: true });
        for (const code of result.codes) expect(code.width).toBeGreaterThan(0);
      }
      writeFileSync(path.join(outputs, `${name}.pdf`), pdf);
    }
  } finally {
    await app.close();
    await stub.close();
    rmSync(profile, { recursive: true, force: true });
  }
});
