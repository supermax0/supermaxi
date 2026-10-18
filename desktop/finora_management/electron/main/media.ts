/**
 * finora-media://media/<path> → FINORA image fetched with the session cookie.
 * Lets product thumbnails load under the renderer's strict CSP without
 * opening it to the network, and only for same-server image paths.
 */
import { protocol } from "electron";
import { MEDIA_SCHEME, mediaPathSchema } from "../../shared/ipc";
import { fetchFinoraImage } from "./finoraHttp";

export function registerMediaScheme(): void {
  protocol.registerSchemesAsPrivileged([
    {
      scheme: MEDIA_SCHEME,
      privileges: { standard: true, secure: true, supportFetchAPI: true, stream: true },
    },
  ]);
}

async function resolveImage(url: string): Promise<{ type: string; data: Buffer } | null> {
  const parsed = mediaPathSchema.safeParse(decodeURI(new URL(url).pathname));
  if (!parsed.success) return null;
  try {
    return await fetchFinoraImage(parsed.data);
  } catch (error) {
    console.warn("[media] fetch failed", error instanceof Error ? error.message : String(error));
    return null;
  }
}

type LegacyProtocol = {
  registerBufferProtocol(
    scheme: string,
    handler: (
      request: { url: string },
      callback: (response: { statusCode?: number; mimeType?: string; data?: Buffer }) => void,
    ) => void,
  ): boolean;
};

export function handleMediaProtocol(): void {
  if (typeof protocol.handle === "function") {
    protocol.handle(MEDIA_SCHEME, async (request) => {
      const image = await resolveImage(request.url);
      if (!image) return new Response(null, { status: 404 });
      return new Response(image.data, {
        status: 200,
        headers: { "content-type": image.type, "cache-control": "private, max-age=3600" },
      });
    });
    return;
  }
  // Electron 22 (Windows 7/8 build): protocol.handle does not exist yet.
  (protocol as unknown as LegacyProtocol).registerBufferProtocol(MEDIA_SCHEME, (request, callback) => {
    void resolveImage(request.url).then((image) =>
      callback(image ? { statusCode: 200, mimeType: image.type, data: image.data } : { statusCode: 404 }),
    );
  });
}
