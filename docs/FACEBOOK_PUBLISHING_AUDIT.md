# Facebook Publishing Implementation Audit

## Summary

- **Graph API endpoint**: Correct. Page feed = `POST /{page_id}/feed`, photos = `POST /{page_id}/photos`, videos = `POST /{page_id}/videos`.
- **page_id usage**: Correct in both `modules/publisher` and `platforms/facebook.py`; token is Page Access Token per page.
- **page access token**: Used correctly (decrypted per page, passed to Graph API).
- **published flag**: Not sent; Page posts are published by default. No change needed.
- **photo/video endpoints**: Correct (`/photos` with `source` file, `/videos` with `source` file).
- **API error handling**: Retry on rate-limit; errors propagated to post status and user. One bug fixed: success detection and JSON parse safety.

---

## File-by-File

### modules/publisher/services/facebook_service.py

| Line | Topic | Status / Bug | Fix |
|------|--------|--------------|-----|
| 23 | Graph API base | `GRAPH_BASE = "https://graph.facebook.com/v19.0"` | OK. Consider v21.0 for parity with platforms/facebook.py. |
| 41 | Success detection | **BUG**: Success only when `"id" in data`. Photo API can return `post_id`; non-JSON response (e.g. gateway error) makes `resp.json()` raise and masks real error. | Treat success when `status_code == 200` and (`"id" in data` or `"post_id" in data`). Parse JSON in try/except and on failure return a structured error instead of retrying blindly. |
| 94–95 | Feed endpoint | `POST /{page_id}/feed` with `message`, `access_token` | OK. |
| 103–109 | Photo endpoint | `POST /{page_id}/photos` with `caption`, `access_token`, `files["source"]` | OK. |
| 118–126 | Video endpoint | `POST /{page_id}/videos` with `description`, `access_token`, `files["source"]` | OK. |
| 29–64 | Error handling | Rate-limit retry; non-retryable errors returned | OK. |

### platforms/facebook.py

| Line | Topic | Status / Bug | Fix |
|------|--------|--------------|-----|
| 46–48 | page_id | Required; no fallback to `"me"` | OK (already fixed in prior change). |
| 96–101 | Feed | `POST /{me_or_page}/feed` with `access_token`, `message` | OK. |
| 74–93 | Photo | `POST /{me_or_page}/photos` with file or `url` | OK. |
| 50–69 | Video | `POST /{me_or_page}/videos` with file or `file_url` | OK. |
| 68–69, 90–91 | Error handling | Non-200 raises RuntimeError with message | OK. No retry; caller can retry. |

### modules/publisher/api/posts_api.py

| Line | Topic | Status / Bug | Fix |
|------|--------|--------------|-----|
| 183–209 | create_post | Validates `page_ids`, `text` or `media_ids`; creates post and calls `publish_single_post_now` | OK. |
| 214–224 | Background publish | Multi-page runs in thread; returns 202 | OK. |

### modules/publisher/services/scheduler_service.py

| Line | Topic | Status / Bug | Fix |
|------|--------|--------------|-----|
| 124–132 | _publish_with_token | Uses `page_id`, decrypted `token`; text/photo/video by media_list | OK. |
| 139–147 | page_ids loop | Resolves page and token per `page_id` | OK. |
| 189 | result handling | Treats `result.get("success")` and stores `facebook_post_ids` | OK. |

### static/publisher/js/publisher.js

| Line | Topic | Status / Bug | Fix |
|------|--------|--------------|-----|
| 609–666 | submitPost | Validates page_ids and text/media; POST to `/publisher/api/posts/create` or `.../schedule` | OK. If no publish request appears in Network: (1) ensure at least one page is selected and text or media is present, (2) check Console for JS errors that could prevent the fetch, (3) ensure form submit is not prevented elsewhere. |
| 12–26 | apiFetchJson | Relative URL; `credentials: "include"` | OK. If app is under a subpath (e.g. /app/), base URL may need to be configurable. |

---

## Bugs Fixed in Code

1. **modules/publisher/services/facebook_service.py**  
   - **Success detection**: Accept 200 with `"id"` or `"post_id"` in response.  
   - **JSON parse**: Safe parse; on failure return clear error instead of retry.

---

## Recommendations

- Ensure **Page** (not user profile) is linked and that **page_id** and Page Access Token are stored.
- Page post visibility is controlled by the Page’s default audience in Facebook; no `privacy` parameter is sent for Page posts.
- If the publish request never appears in the browser Network tab, check client-side: validation, JS errors, and that the submit handler is attached to the correct form.
