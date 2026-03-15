export type PostStatus =
  | "draft"
  | "queued"
  | "scheduled"
  | "publishing"
  | "published"
  | "failed"
  | "partial";

export interface PublisherPost {
  id: number;
  tenant_slug?: string | null;
  text?: string | null;
  media_ids: number[];
  page_ids: string[];
  facebook_post_ids?: Record<string, string>;
  status: PostStatus;
  publish_type: "now" | "scheduled";
  publish_time?: string | null;
  error_message?: string | null;
  created_at?: string | null;
}

export interface PublisherPage {
  id: number;
  tenant_slug?: string | null;
  page_id: string;
  page_name: string;
  created_at?: string | null;
}

export interface PublisherMedia {
  id: number;
  tenant_slug?: string | null;
  filename: string;
  original_name?: string | null;
  media_type: "image" | "video";
  size_bytes?: number | null;
  url_path: string;
  created_at?: string | null;
}

export interface PublisherSettings {
  fb_app_id: string;
  fb_app_secret: string;
  fb_user_token: string;
  has_secret: boolean;
  has_token: boolean;
  updated_at?: string | null;
}

export interface PaginationMeta {
  page: number;
  per_page: number;
  total: number;
  total_pages: number;
}

export interface ApiErrorPayload {
  code?: string;
  message?: string;
  fields?: Record<string, string>;
}
