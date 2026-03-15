import type {
  ApiErrorPayload,
  PaginationMeta,
  PublisherMedia,
  PublisherPage,
  PublisherPost,
  PublisherSettings,
} from "./types";

type JsonObject = Record<string, unknown>;

const API_BASE = (window as any).PUBLISHER_API_BASE || "/publisher/api";

export class ApiError extends Error {
  status: number;
  details?: ApiErrorPayload;

  constructor(message: string, status = 400, details?: ApiErrorPayload) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.details = details;
  }
}

async function request<T = JsonObject>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    credentials: "include",
    ...init,
    headers: {
      Accept: "application/json",
      ...(init?.headers || {}),
    },
  });

  let payload: any = {};
  const contentType = res.headers.get("content-type") || "";
  if (contentType.includes("application/json")) {
    payload = await res.json();
  }

  if (!res.ok || payload?.success === false) {
    const errorPayload = payload?.error || {};
    throw new ApiError(
      errorPayload?.message || payload?.message || "حدث خطأ في الطلب",
      res.status,
      errorPayload,
    );
  }

  return payload as T;
}

function pickItems<T>(payload: any, legacyKey: string): T[] {
  if (Array.isArray(payload?.data?.items)) return payload.data.items;
  if (Array.isArray(payload?.data)) return payload.data;
  if (Array.isArray(payload?.[legacyKey])) return payload[legacyKey];
  return [];
}

function pickObject<T>(payload: any, legacyKey?: string): T {
  if (payload?.data && typeof payload.data === "object" && !Array.isArray(payload.data)) {
    return payload.data as T;
  }
  if (legacyKey && payload?.[legacyKey] && typeof payload[legacyKey] === "object") {
    return payload[legacyKey] as T;
  }
  return payload as T;
}

function pickMeta(payload: any): PaginationMeta | null {
  if (payload?.meta && typeof payload.meta === "object") {
    return payload.meta as PaginationMeta;
  }
  return null;
}

export async function listPosts(params: {
  status?: string;
  page?: number;
  per_page?: number;
  q?: string;
} = {}): Promise<{ items: PublisherPost[]; meta: PaginationMeta | null }> {
  const q = new URLSearchParams();
  Object.entries(params).forEach(([k, v]) => {
    if (v !== undefined && v !== null && `${v}`.trim() !== "") q.set(k, String(v));
  });
  const payload = await request(`/posts${q.toString() ? `?${q.toString()}` : ""}`);
  return { items: pickItems<PublisherPost>(payload, "posts"), meta: pickMeta(payload) };
}

export async function createPost(body: {
  text: string;
  page_ids: string[];
  media_ids: number[];
}): Promise<{ post: PublisherPost; message: string }> {
  const payload = await request("/posts/create", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return {
    post: pickObject<PublisherPost>(payload, "post"),
    message: payload?.message || "تمت العملية بنجاح",
  };
}

export async function schedulePost(body: {
  text: string;
  page_ids: string[];
  media_ids: number[];
  publish_time: string;
  timezone_offset_minutes: number;
}): Promise<{ post: PublisherPost; message: string }> {
  const payload = await request("/posts/schedule", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return {
    post: pickObject<PublisherPost>(payload, "post"),
    message: payload?.message || "تمت الجدولة بنجاح",
  };
}

export async function listPages(params: { page?: number; per_page?: number } = {}) {
  const q = new URLSearchParams();
  if (params.page) q.set("page", String(params.page));
  if (params.per_page) q.set("per_page", String(params.per_page));
  const payload = await request(`/pages${q.toString() ? `?${q.toString()}` : ""}`);
  return { items: pickItems<PublisherPage>(payload, "pages"), meta: pickMeta(payload) };
}

export async function deletePage(pageDbId: number): Promise<void> {
  await request(`/pages/${pageDbId}`, { method: "DELETE" });
}

export async function connectPages(userToken?: string): Promise<string> {
  const payload = await request("/settings/connect-pages", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(userToken ? { user_token: userToken } : {}),
  });
  return payload?.message || "تم ربط الصفحات بنجاح";
}

export async function listMedia(params: {
  q?: string;
  type?: "image" | "video";
  page?: number;
  per_page?: number;
} = {}) {
  const q = new URLSearchParams();
  Object.entries(params).forEach(([k, v]) => {
    if (v !== undefined && v !== null && `${v}`.trim() !== "") q.set(k, String(v));
  });
  const payload = await request(`/media${q.toString() ? `?${q.toString()}` : ""}`);
  return { items: pickItems<PublisherMedia>(payload, "media"), meta: pickMeta(payload) };
}

export async function deleteMedia(mediaId: number): Promise<void> {
  await request(`/media/${mediaId}`, { method: "DELETE" });
}

export async function uploadMedia(file: File): Promise<PublisherMedia> {
  const fd = new FormData();
  fd.append("file", file);
  const payload = await request("/media/upload", {
    method: "POST",
    body: fd,
  });
  return pickObject<PublisherMedia>(payload, "media");
}

export async function getSettings(): Promise<PublisherSettings> {
  const payload = await request("/settings");
  return pickObject<PublisherSettings>(payload, "settings");
}

export async function saveSettings(body: {
  fb_app_id?: string;
  fb_app_secret?: string;
  fb_user_token?: string;
}): Promise<string> {
  const payload = await request("/settings", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return payload?.message || "تم حفظ الإعدادات";
}

export async function generateAiPost(body: {
  topic: string;
  tone: string;
  length: string;
}): Promise<string> {
  const payload = await request("/ai/generate_post", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return payload?.data?.text || payload?.text || "";
}
