import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { buildSync } from "esbuild";
import { _electron as electron, expect, test } from "@playwright/test";
import { startFinoraStub, STUB_CREDENTIALS } from "./finoraStub";

declare global {
  interface Window {
    __audioStarts: number[];
    __soundDesignTest: {
      SOUND_NOTES: Record<string, unknown>;
      scheduleSound(ctx: BaseAudioContext, cue: string, volume: number): void;
    };
  }
}

test("real interface audio is soft, globally muted, and persists across Electron restart", async () => {
  test.setTimeout(120000);
  const profile = mkdtempSync(path.join(tmpdir(), "finora-interface-audio-"));
  if (
    path.dirname(profile) !== path.resolve(tmpdir()) ||
    !path.basename(profile).startsWith("finora-interface-audio-")
  )
    throw Error("Unsafe test cleanup");
  const stub = await startFinoraStub();
  const outputs = path.resolve(__dirname, "../../../tests/_artifacts/interface-sounds-20261013");
  mkdirSync(outputs, { recursive: true });
  const launch = () =>
    electron.launch({
      args: [path.resolve(__dirname, "..")],
      cwd: path.resolve(__dirname, ".."),
      env: { ...process.env, FINORA_SERVER_URL: stub.url, FINORA_USER_DATA_DIR: profile },
    });
  let app = await launch();
  try {
    let page = await app.firstWindow();
    await page.context().addInitScript(() => {
      const starts: number[] = [];
      window.__audioStarts = starts;
      const original = AudioContext.prototype.createOscillator;
      AudioContext.prototype.createOscillator = function () {
        const node = original.call(this),
          start = node.start;
        node.start = function (at?: number) {
          starts.push(at ?? 0);
          start.call(this, at);
        };
        return node;
      };
    });
    await page.reload();
    const count = () => page.evaluate(() => window.__audioStarts.length);
    expect(await count()).toBe(0);
    await page.getByLabel("اسم المستخدم").click();
    await expect.poll(count).toBeGreaterThan(0);
    await page.waitForTimeout(200);
    const beforeKeys = await count();
    await page.getByLabel("اسم المستخدم").pressSequentially("admin", { delay: 110 });
    await page.waitForTimeout(100);
    expect(await count()).toBe(beforeKeys + 5);
    await page.getByLabel("اسم المستخدم").press("Backspace");
    await page.waitForTimeout(100);
    expect(await count()).toBe(beforeKeys + 6);
    const beforeScan = await count();
    await page.getByLabel("اسم المستخدم").pressSequentially("880123456789", { delay: 5 });
    await page.waitForTimeout(100);
    expect(await count()).toBe(beforeScan);
    const beforeTyping = await count();
    await page.getByLabel("معرف الشركة").fill(STUB_CREDENTIALS.tenantSlug);
    await page.getByLabel("اسم المستخدم").fill(STUB_CREDENTIALS.username);
    await page.getByLabel("كلمة المرور").fill(STUB_CREDENTIALS.password);
    expect(await count()).toBe(beforeTyping);
    const beforeSubmit = await count();
    await page.getByRole("button", { name: "تسجيل الدخول", exact: true }).click();
    await page.getByRole("button", { name: "المنتجات", exact: true }).waitFor();
    await expect.poll(count).toBeGreaterThan(beforeSubmit);
    await page.getByRole("button", { name: "الإعدادات", exact: true }).click();
    let settings = page.getByRole("dialog", { name: "الإعدادات", exact: true });
    await settings.getByRole("button", { name: "الأصوات", exact: true }).click();
    const slider = settings.getByRole("slider", { name: "مستوى صوت الواجهة" });
    await slider.focus();
    await slider.press("Home");
    for (let i = 0; i < 9; i++) await slider.press("ArrowRight");
    await expect(slider).toHaveValue("45");
    await page.waitForTimeout(200);
    let before = await count();
    await settings.getByRole("button", { name: "تجربة صوت نجاح", exact: true }).click();
    await expect.poll(count).toBeGreaterThan(before);
    await settings.getByRole("switch", { name: "صوت الكتابة", exact: true }).click();
    await expect(settings.getByRole("button", { name: "تجربة صوت كتابة", exact: true })).toBeDisabled();
    await settings.getByRole("switch", { name: "أصوات الواجهة", exact: true }).click();
    await expect(slider).toBeDisabled();
    await page.waitForTimeout(200);
    before = await count();
    await settings.getByRole("button", { name: "الاتصال", exact: true }).click();
    await settings.getByText("خادم FINORA", { exact: true }).waitFor();
    expect(await count()).toBe(before);
    await app.close();
    app = await launch();
    page = await app.firstWindow();
    await page.getByRole("button", { name: "الإعدادات", exact: true }).click();
    settings = page.getByRole("dialog", { name: "الإعدادات", exact: true });
    await settings.getByRole("button", { name: "الأصوات", exact: true }).click();
    await expect(settings.getByRole("switch", { name: "أصوات الواجهة", exact: true })).toHaveAttribute(
      "aria-checked",
      "false",
    );
    await expect(settings.getByRole("slider", { name: "مستوى صوت الواجهة" })).toHaveValue("45");
    await expect(settings.getByRole("switch", { name: "صوت الكتابة", exact: true })).toHaveAttribute(
      "aria-checked",
      "false",
    );
    await settings.getByRole("switch", { name: "أصوات الواجهة", exact: true }).click();
    await settings.getByRole("button", { name: "تجربة صوت ضغطة", exact: true }).click();
    // Render the exact production sound synthesizer in OfflineAudioContext.
    const bundle = buildSync({
      entryPoints: [path.resolve(__dirname, "../src/services/sounds.ts")],
      bundle: true,
      write: false,
      format: "iife",
      globalName: "__soundDesignTest",
      footer: { js: "window.__soundDesignTest = __soundDesignTest;" },
      define: { "import.meta.env.DEV": "false" },
    });
    const compiled = bundle.outputFiles[0];
    if (!compiled) throw Error("Missing synthesizer bundle");
    await page.evaluate(compiled.text);
    const waveforms = await page.evaluate(async () => {
      const design = window.__soundDesignTest;
      const results = [];
      for (const cue of Object.keys(design.SOUND_NOTES)) {
        const ctx = new OfflineAudioContext(1, 22050, 44100);
        design.scheduleSound(ctx, cue, 100);
        const samples = (await ctx.startRendering()).getChannelData(0);
        const peak = samples.reduce((max, value) => Math.max(max, Math.abs(value)), 0);
        let last = 0;
        samples.forEach((value, index) => {
          if (Math.abs(value) > 0.0001) last = index / 44100;
        });
        results.push({ cue, peak, last, samples: cue === "success" ? Array.from(samples) : [] });
      }
      return results;
    });
    for (const waveform of waveforms) {
      expect(waveform.peak).toBeGreaterThan(waveform.cue === "typing" ? 0.005 : 0.02);
      expect(waveform.peak).toBeLessThan(waveform.cue === "typing" ? 0.05 : 0.25);
      expect(waveform.last).toBeLessThan(waveform.cue === "typing" ? 0.04 : 0.35);
    }
    writeFileSync(
      path.join(outputs, "audio-metrics.json"),
      JSON.stringify(
        waveforms.map(({ cue, peak, last }) => ({ cue, peak, last })),
        null,
        2,
      ),
    );
    const success = waveforms.find((row) => row.cue === "success");
    if (!success) throw Error("Success sound missing");
    const wav = Buffer.alloc(44 + success.samples.length * 2);
    wav.write("RIFF", 0);
    wav.writeUInt32LE(wav.length - 8, 4);
    wav.write("WAVEfmt ", 8);
    wav.writeUInt32LE(16, 16);
    wav.writeUInt16LE(1, 20);
    wav.writeUInt16LE(1, 22);
    wav.writeUInt32LE(44100, 24);
    wav.writeUInt32LE(88200, 28);
    wav.writeUInt16LE(2, 32);
    wav.writeUInt16LE(16, 34);
    wav.write("data", 36);
    wav.writeUInt32LE(wav.length - 44, 40);
    success.samples.forEach((value, index) => wav.writeInt16LE(Math.round(value * 32767), 44 + index * 2));
    writeFileSync(path.join(outputs, "success-preview.wav"), wav);
    await settings.screenshot({ path: path.join(outputs, "sound-settings.png"), animations: "disabled" });
  } finally {
    await app.close();
    await stub.close();
    rmSync(profile, { recursive: true, force: true });
  }
});
