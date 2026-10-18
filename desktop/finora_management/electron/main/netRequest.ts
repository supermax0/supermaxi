/**
 * HTTP over Electron's `net.request` bound to the FINORA session partition.
 * Works on every Electron line we ship (22 for Windows 7/8, current for
 * Windows 10/11) — `session.fetch` and global FormData do not exist on 22.
 */
import { net, type Session } from "electron";

export interface NetResponse {
  status: number;
  location: string | null;
  contentType: string | null;
  body: Buffer;
}

export class NetTimeoutError extends Error {
  constructor() {
    super("request timed out");
    this.name = "NetTimeoutError";
  }
}

function header(headers: Record<string, string | string[]>, name: string): string | null {
  const key = Object.keys(headers).find((k) => k.toLowerCase() === name);
  if (!key) return null;
  const value = headers[key];
  return Array.isArray(value) ? (value[0] ?? null) : (value ?? null);
}

export function netRequest(
  ses: Session,
  url: string,
  options: { method: "GET" | "POST"; headers: Record<string, string>; body?: Buffer; timeoutMs: number },
): Promise<NetResponse> {
  return new Promise((resolve, reject) => {
    const request = net.request({
      url,
      method: options.method,
      session: ses,
      useSessionCookies: true,
      redirect: "manual",
    });
    let settled = false;
    const finish = (fn: () => void) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      fn();
    };
    const timer = setTimeout(() => {
      finish(() => reject(new NetTimeoutError()));
      request.abort();
    }, options.timeoutMs);

    for (const [name, value] of Object.entries(options.headers)) request.setHeader(name, value);

    // FINORA answers expired sessions with a redirect to /login: report it, never follow it.
    request.on("redirect", (statusCode, _method, redirectUrl) => {
      finish(() =>
        resolve({ status: statusCode, location: redirectUrl, contentType: null, body: Buffer.alloc(0) }),
      );
      request.abort();
    });
    request.on("response", (response) => {
      const chunks: Buffer[] = [];
      response.on("data", (chunk: Buffer) => chunks.push(chunk));
      response.on("end", () =>
        finish(() =>
          resolve({
            status: response.statusCode,
            location: header(response.headers, "location"),
            contentType: header(response.headers, "content-type"),
            body: Buffer.concat(chunks),
          }),
        ),
      );
      response.on("error", (error: Error) => finish(() => reject(error)));
    });
    request.on("error", (error: Error) => finish(() => reject(error)));
    if (options.body) request.write(options.body);
    request.end();
  });
}

/** multipart/form-data encoder (UTF-8 field values; ASCII file name). */
export function encodeMultipart(
  fields: Array<[string, string]>,
  file?: { field: string; name: string; type: string; data: Uint8Array },
  files: { field: string; name: string; type: string; data: Uint8Array }[] = [],
): { body: Buffer; contentType: string } {
  const boundary = `----FinoraDesktop${Date.now().toString(16)}${Math.random().toString(16).slice(2)}`;
  const parts: Buffer[] = [];
  for (const [name, value] of fields) {
    parts.push(
      Buffer.from(
        `--${boundary}\r\nContent-Disposition: form-data; name="${name}"\r\n\r\n${value}\r\n`,
        "utf8",
      ),
    );
  }
  const uploads = [...(file ? [file] : []), ...files];
  for (const file of uploads) {
    const extension = file.type.split("/")[1] === "jpeg" ? "jpg" : (file.type.split("/")[1] ?? "png");
    parts.push(
      Buffer.from(
        `--${boundary}\r\nContent-Disposition: form-data; name="${file.field}"; filename="upload.${extension}"\r\nContent-Type: ${file.type}\r\n\r\n`,
        "utf8",
      ),
      Buffer.from(file.data),
      Buffer.from("\r\n", "utf8"),
    );
  }
  parts.push(Buffer.from(`--${boundary}--\r\n`, "utf8"));
  return { body: Buffer.concat(parts), contentType: `multipart/form-data; boundary=${boundary}` };
}
