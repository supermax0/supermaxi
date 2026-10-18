import { expect, test } from "@playwright/test";
import { DevDataSource } from "../src/data/devSource";
import type { Message } from "../src/data/schemas";
import { readFile } from "node:fs/promises";
import path from "node:path";

test("private media preview, analysis, upload and microphone review preserve the Finora workspace", async ({
  page,
}, testInfo) => {
  const source = new DevDataSource({ simulate: false, latency: 0 });
  const conversations = await source.listConversations({ channel: "all", filter: "all", search: "" });
  const conversation = conversations.find((row) => row.id === "c6");
  if (!conversation) throw new Error("Missing test conversation");
  const profile = await source.getCustomer("c6");
  const png = Buffer.from(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aN3sAAAAASUVORK5CYII=",
    "base64",
  );
  const video = await readFile(path.resolve("e2e-settings/fixtures/clip.mp4"));
  const messages: Message[] = [
    {
      id: "image-in",
      conversationId: "c6",
      sender: "customer",
      authorName: null,
      text: "هاي شاشة المخزون",
      at: new Date().toISOString(),
      delivery: null,
      attachments: [
        {
          id: "0",
          kind: "image",
          name: "screen.png",
          mimeType: "image/png",
          sizeBytes: png.length,
          status: "stored",
        },
      ],
    },
    {
      id: "video-in",
      conversationId: "c6",
      sender: "customer",
      authorName: null,
      text: "شرح المشكلة بالفيديو",
      at: new Date().toISOString(),
      delivery: null,
      attachments: [
        {
          id: "0",
          kind: "video",
          name: "clip.mp4",
          mimeType: "video/mp4",
          sizeBytes: video.length,
          status: "stored",
        },
      ],
    },
  ];
  const operator = {
    id: 1,
    username: "owner",
    role: "super_admin",
    permissions: ["conversations.view", "messages.send", "ai.takeover", "notes.write"],
  };
  let sent = 0;
  await page.addInitScript(
    (value) =>
      sessionStorage.setItem(
        "finora-core.session",
        JSON.stringify({ accessToken: "media-test-token", refreshToken: "fake", operator: value }),
      ),
    operator,
  );
  await page.context().grantPermissions(["microphone"], { origin: "http://localhost:5176" });
  await page.route("http://127.0.0.1:5019/**", async (route) => {
    const request = route.request();
    const pathname = new URL(request.url()).pathname;
    const headers = {
      "Access-Control-Allow-Origin": "*",
      "Access-Control-Allow-Headers": "*",
      "Access-Control-Allow-Methods": "GET, POST, PATCH",
    };
    if (request.method() === "OPTIONS") {
      await route.fulfill({ status: 204, headers });
      return;
    }
    expect(request.headers().authorization).toBe("Bearer media-test-token");
    expect(request.url()).not.toContain("media-test-token");
    if (pathname.endsWith("/events/stream")) {
      await route.abort();
      return;
    }
    let body: unknown = { items: [] };
    if (pathname.endsWith("/status"))
      body = {
        ...(await source.getStatus()),
        environment: "production",
        devLoopback: false,
        conversationCount: 1,
      };
    if (pathname.endsWith("/conversations")) body = { items: [conversation] };
    if (pathname.endsWith("/customers/c6")) body = profile;
    if (pathname.endsWith("/conversations/c6/messages")) body = { items: messages };
    if (pathname.endsWith("/conversations/c6/shadow")) body = { enabled: false, items: [] };
    const mediaMatch = pathname.match(/\/messages\/(image-in|video-in)\/attachments\/0$/);
    if (mediaMatch) {
      await route.fulfill({
        body: mediaMatch[1] === "image-in" ? png : video,
        contentType: mediaMatch[1] === "image-in" ? "image/png" : "video/mp4",
        headers,
      });
      return;
    }
    if (pathname.endsWith("/analyze")) {
      const row = messages.find((item) => pathname.includes(`/messages/${item.id}/`));
      if (!row?.attachments?.[0]) throw new Error("Missing test attachment");
      row.attachments[0].analysis = {
        status: "completed",
        summary: "شرح شاشة المخزون",
        details: "زر إضافة منتج واضح، افتح المخزون ثم اضغط إضافة منتج.",
        needsHuman: false,
        provider: "local",
        model: "vision-test",
        frameTimes: row.id === "video-in" ? [0.5, 1.5] : [],
      };
      body = { message: row };
    }
    if (pathname.endsWith("/conversations/c6/media")) {
      const uploaded = request.postDataBuffer();
      if (!uploaded) throw new Error("Missing multipart body");
      const multipart = uploaded.toString("latin1");
      const kind = multipart.includes("Content-Type: audio/")
        ? "audio"
        : multipart.includes("Content-Type: video/")
          ? "video"
          : "image";
      expect(request.headers()["content-type"]).toContain("multipart/form-data; boundary=");
      expect(request.headers()["idempotency-key"]).toBeTruthy();
      const row: Message = {
        id: `sent-${++sent}`,
        conversationId: "c6",
        sender: "human",
        authorName: "owner",
        text: "",
        at: new Date().toISOString(),
        delivery: "sent",
        attachments: [
          {
            id: "0",
            kind,
            mimeType: kind === "audio" ? "audio/mpeg" : kind === "video" ? "video/mp4" : "image/jpeg",
            name: kind === "audio" ? "voice.mp3" : kind === "video" ? "clip.mp4" : "screen.jpg",
            sizeBytes: 100,
            status: "stored",
          },
        ],
      };
      messages.push(row);
      body = { message: row };
    }
    await route.fulfill({ json: body, headers });
  });
  await page.goto("/?gl=0", { waitUntil: "domcontentloaded" });
  await page.locator(".orb-hit").click();
  const text = page.getByLabel("نص الرسالة");
  await expect(text).toBeVisible();
  await page.getByRole("button", { name: "عرض الصورة", exact: true }).click();
  await expect(page.getByAltText("screen.png")).toBeVisible();
  const imageCard = page.getByLabel("مرفق صورة", { exact: true });
  await imageCard.getByRole("button", { name: "تحليل بالذكاء" }).click();
  await expect(imageCard.getByLabel("نتيجة تحليل المرفق")).toContainText("زر إضافة منتج");
  await page.getByRole("button", { name: "عرض الفيديو", exact: true }).click();
  await expect(page.getByLabel("مشغل الفيديو")).toBeVisible();
  const videoCard = page.getByLabel("مرفق فيديو", { exact: true });
  await videoCard.getByRole("button", { name: "تحليل بالذكاء" }).click();
  await expect(videoCard).toContainText("اعتمد على 2 لقطات");
  await text.fill("هذا النص يبقى مسودة");
  await page
    .getByLabel("اختيار صورة أو فيديو أو صوت")
    .setInputFiles({ name: "screen.png", mimeType: "image/png", buffer: png });
  await expect(page.getByAltText("الصورة المختارة")).toBeVisible();
  expect(sent).toBe(0);
  await page.screenshot({ path: testInfo.outputPath("media-desktop.png") });
  await page.getByRole("button", { name: "إرسال المرفق", exact: true }).click();
  await expect(page.getByAltText("الصورة المختارة")).not.toBeVisible();
  await expect(text).toHaveValue("هذا النص يبقى مسودة");
  expect(sent).toBe(1);
  await page
    .getByLabel("اختيار صورة أو فيديو أو صوت")
    .setInputFiles({ name: "clip.mp4", mimeType: "video/mp4", buffer: video });
  await expect(page.locator(".media-draft video")).toBeVisible();
  await page.getByRole("button", { name: "إرسال المرفق", exact: true }).click();
  await expect(page.locator(".media-draft video")).not.toBeVisible();
  expect(sent).toBe(2);
  await page.getByRole("button", { name: "تسجيل فويز", exact: true }).click();
  await expect(page.getByText("نسجل الفويز…")).toBeVisible();
  await page.waitForTimeout(1200);
  await page.getByRole("button", { name: "إيقاف ومعاينة", exact: true }).click();
  await expect(page.getByLabel("معاينة المرفق قبل الإرسال")).toBeVisible();
  expect(sent).toBe(2);
  await page.locator(".media-draft audio").evaluate((element) =>
    element.addEventListener("playing", () => {
      (element as HTMLElement).dataset.played = "yes";
    }),
  );
  await page.locator(".media-draft").getByRole("button", { name: "تشغيل الفويز" }).click();
  await expect(page.locator(".media-draft audio")).toHaveAttribute("data-played", "yes");
  await page.setViewportSize({ width: 1280, height: 720 });
  await page.screenshot({ path: testInfo.outputPath("media-compact.png") });
  expect(
    await page.locator(".composer").evaluate((element) => element.scrollWidth <= element.clientWidth),
  ).toBe(true);
  await page.getByRole("button", { name: "إرسال المرفق", exact: true }).click();
  await expect(page.getByLabel("معاينة المرفق قبل الإرسال")).not.toBeVisible();
  expect(sent).toBe(3);
  await expect(page.getByLabel("مرفق صوتي", { exact: true })).toBeVisible();
});
