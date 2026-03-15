import React, { useEffect, useMemo, useState } from "react";
import {
  ApiError,
  connectPages,
  createPost,
  deleteMedia,
  deletePage,
  generateAiPost,
  getSettings,
  listMedia,
  listPages,
  listPosts,
  saveSettings,
  schedulePost,
  uploadMedia,
} from "./api";
import type { PublisherMedia, PublisherPage, PublisherPost } from "./types";

type RouteKey = "dashboard" | "composer" | "media" | "settings";
type ToastType = "success" | "error" | "info";

interface Toast {
  id: number;
  type: ToastType;
  message: string;
}

const navItems: Array<{ key: RouteKey; href: string; title: string; icon: string }> = [
  { key: "dashboard", href: "/publisher/", title: "لوحة التحكم", icon: "📊" },
  { key: "composer", href: "/publisher/create", title: "إنشاء منشور", icon: "✏️" },
  { key: "media", href: "/publisher/media", title: "مكتبة الوسائط", icon: "🖼️" },
  { key: "settings", href: "/publisher/settings", title: "الإعدادات", icon: "⚙️" },
];

function routeFromPath(pathname: string): RouteKey {
  if (pathname.includes("/publisher/create")) return "composer";
  if (pathname.includes("/publisher/media")) return "media";
  if (pathname.includes("/publisher/settings")) return "settings";
  return "dashboard";
}

function statusLabel(status: string): string {
  const labels: Record<string, string> = {
    draft: "مسودة",
    queued: "في الانتظار",
    scheduled: "مجدول",
    publishing: "قيد النشر",
    published: "منشور",
    failed: "فشل",
    partial: "نشر جزئي",
  };
  return labels[status] || status;
}

function formatDate(value?: string | null): string {
  if (!value) return "—";
  try {
    return new Date(value).toLocaleString("ar-SA", {
      year: "numeric",
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return "—";
  }
}

function formatSize(bytes?: number | null): string {
  if (!bytes) return "—";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function normalizeMediaUrl(urlPath: string): string {
  if (!urlPath) return "";
  if (urlPath.startsWith("/media/")) {
    return `/publisher/media-file/${urlPath.replace(/^\/media\//, "")}`;
  }
  return urlPath;
}

function getErrorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  if (error instanceof Error) return error.message;
  return "حدث خطأ غير متوقع";
}

export const App: React.FC = () => {
  const [route, setRoute] = useState<RouteKey>(() => routeFromPath(window.location.pathname));
  const [toasts, setToasts] = useState<Toast[]>([]);

  useEffect(() => {
    const onPopState = () => setRoute(routeFromPath(window.location.pathname));
    window.addEventListener("popstate", onPopState);
    return () => window.removeEventListener("popstate", onPopState);
  }, []);

  const notify = (message: string, type: ToastType = "info") => {
    const id = Date.now() + Math.floor(Math.random() * 1000);
    setToasts((prev) => [...prev, { id, type, message }]);
    window.setTimeout(() => {
      setToasts((prev) => prev.filter((item) => item.id !== id));
    }, 4200);
  };

  const navigate = (href: string) => {
    window.history.pushState({}, "", href);
    setRoute(routeFromPath(href));
  };

  return (
    <div className="pub-root">
      <aside className="pub-sidebar">
        <div className="pub-logo">
          <span className="pub-logo-icon">📢</span>
          <div>
            <div className="pub-logo-title">Publisher SPA</div>
            <div className="pub-logo-sub">واجهة احترافية للنشر</div>
          </div>
        </div>
        <nav className="pub-nav">
          {navItems.map((item) => (
            <a
              key={item.key}
              href={item.href}
              className={item.key === route ? "active" : ""}
              onClick={(event) => {
                event.preventDefault();
                navigate(item.href);
              }}
            >
              <span>{item.icon}</span>
              <span>{item.title}</span>
            </a>
          ))}
        </nav>
        <div className="pub-sidebar-footer">
          <a href="/">العودة إلى النظام</a>
          <a href={`${window.location.pathname}?legacy=1`}>الوضع القديم</a>
        </div>
      </aside>

      <main className="pub-main">
        {route === "dashboard" && <DashboardPage notify={notify} />}
        {route === "composer" && <ComposerPage notify={notify} />}
        {route === "media" && <MediaPage notify={notify} />}
        {route === "settings" && <SettingsPage notify={notify} />}
      </main>

      <div className="pub-toast-wrap">
        {toasts.map((toast) => (
          <div key={toast.id} className={`pub-toast ${toast.type}`}>
            {toast.message}
          </div>
        ))}
      </div>
    </div>
  );
};

const DashboardPage: React.FC<{ notify: (message: string, type?: ToastType) => void }> = ({
  notify,
}) => {
  const [loading, setLoading] = useState(true);
  const [posts, setPosts] = useState<PublisherPost[]>([]);

  const load = async () => {
    setLoading(true);
    try {
      const res = await listPosts({ page: 1, per_page: 20 });
      setPosts(res.items);
    } catch (error) {
      notify(getErrorMessage(error), "error");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void load();
  }, []);

  const stats = useMemo(() => {
    const byStatus: Record<string, number> = {};
    posts.forEach((post) => {
      byStatus[post.status] = (byStatus[post.status] || 0) + 1;
    });
    return {
      total: posts.length,
      scheduled: byStatus.scheduled || 0,
      published: byStatus.published || 0,
      failed: byStatus.failed || 0,
    };
  }, [posts]);

  return (
    <>
      <header className="page-header">
        <h1>لوحة الناشر</h1>
        <button className="btn btn-outline" onClick={() => void load()}>
          تحديث البيانات
        </button>
      </header>

      <section className="stats-grid">
        <div className="stat-card">
          <div className="stat-title">إجمالي المنشورات</div>
          <div className="stat-value">{stats.total}</div>
        </div>
        <div className="stat-card">
          <div className="stat-title">مجدولة</div>
          <div className="stat-value">{stats.scheduled}</div>
        </div>
        <div className="stat-card">
          <div className="stat-title">منشورة</div>
          <div className="stat-value">{stats.published}</div>
        </div>
        <div className="stat-card">
          <div className="stat-title">فشلت</div>
          <div className="stat-value">{stats.failed}</div>
        </div>
      </section>

      <section className="card">
        <div className="card-title">أحدث المنشورات</div>
        <table className="table">
          <thead>
            <tr>
              <th>المحتوى</th>
              <th>الحالة</th>
              <th>الصفحات</th>
              <th>التاريخ</th>
            </tr>
          </thead>
          <tbody>
            {loading && (
              <tr>
                <td colSpan={4}>جاري تحميل المنشورات...</td>
              </tr>
            )}
            {!loading && posts.length === 0 && (
              <tr>
                <td colSpan={4}>لا توجد منشورات بعد.</td>
              </tr>
            )}
            {!loading &&
              posts.map((post) => (
                <tr key={post.id}>
                  <td>{post.text?.slice(0, 70) || "—"}</td>
                  <td>
                    <span className={`badge ${post.status}`}>{statusLabel(post.status)}</span>
                  </td>
                  <td>{post.page_ids?.length || 0}</td>
                  <td>{formatDate(post.created_at)}</td>
                </tr>
              ))}
          </tbody>
        </table>
      </section>
    </>
  );
};

const ComposerPage: React.FC<{ notify: (message: string, type?: ToastType) => void }> = ({
  notify,
}) => {
  const [pages, setPages] = useState<PublisherPage[]>([]);
  const [media, setMedia] = useState<PublisherMedia[]>([]);
  const [text, setText] = useState("");
  const [selectedPages, setSelectedPages] = useState<string[]>([]);
  const [selectedMedia, setSelectedMedia] = useState<number[]>([]);
  const [mode, setMode] = useState<"now" | "scheduled">("now");
  const [publishTime, setPublishTime] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [loading, setLoading] = useState(true);

  const [aiTopic, setAiTopic] = useState("");
  const [aiTone, setAiTone] = useState("احترافي");
  const [aiLength, setAiLength] = useState("متوسط");
  const [aiLoading, setAiLoading] = useState(false);

  const load = async () => {
    setLoading(true);
    try {
      const [pagesRes, mediaRes] = await Promise.all([
        listPages({ page: 1, per_page: 200 }),
        listMedia({ page: 1, per_page: 60 }),
      ]);
      setPages(pagesRes.items);
      setMedia(mediaRes.items);
    } catch (error) {
      notify(getErrorMessage(error), "error");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void load();
  }, []);

  const handleSubmit = async () => {
    if (!selectedPages.length) {
      notify("اختر صفحة واحدة على الأقل.", "error");
      return;
    }
    if (!text.trim() && !selectedMedia.length) {
      notify("اكتب نصًا أو أرفق وسائط.", "error");
      return;
    }
    if (mode === "scheduled" && !publishTime) {
      notify("حدد وقت الجدولة.", "error");
      return;
    }

    setSubmitting(true);
    try {
      const payload = {
        text: text.trim(),
        page_ids: selectedPages,
        media_ids: selectedMedia,
      };
      const message =
        mode === "now"
          ? (await createPost(payload)).message
          : (
              await schedulePost({
                ...payload,
                publish_time: publishTime,
                timezone_offset_minutes: new Date().getTimezoneOffset(),
              })
            ).message;
      notify(message, "success");
      setText("");
      setSelectedMedia([]);
      if (mode === "scheduled") setPublishTime("");
    } catch (error) {
      notify(getErrorMessage(error), "error");
    } finally {
      setSubmitting(false);
    }
  };

  const handleGenerateAi = async () => {
    if (!aiTopic.trim()) {
      notify("اكتب موضوعًا أولًا.", "error");
      return;
    }
    setAiLoading(true);
    try {
      const generated = await generateAiPost({
        topic: aiTopic.trim(),
        tone: aiTone,
        length: aiLength,
      });
      if (!generated.trim()) {
        notify("لم يتم توليد نص صالح.", "error");
        return;
      }
      setText(generated);
      notify("تم توليد النص بنجاح.", "success");
    } catch (error) {
      notify(getErrorMessage(error), "error");
    } finally {
      setAiLoading(false);
    }
  };

  const togglePage = (pageId: string) => {
    setSelectedPages((prev) =>
      prev.includes(pageId) ? prev.filter((id) => id !== pageId) : [...prev, pageId],
    );
  };

  const toggleMedia = (mediaId: number) => {
    setSelectedMedia((prev) =>
      prev.includes(mediaId) ? prev.filter((id) => id !== mediaId) : [...prev, mediaId],
    );
  };

  return (
    <>
      <header className="page-header">
        <h1>إنشاء منشور احترافي</h1>
        <button className="btn btn-outline" onClick={() => void load()}>
          تحديث القوائم
        </button>
      </header>

      <section className="card">
        <div className="card-title">مساعد الذكاء الاصطناعي</div>
        <div className="row">
          <input
            className="input"
            placeholder="موضوع المنشور"
            value={aiTopic}
            onChange={(e) => setAiTopic(e.target.value)}
          />
          <select className="input" value={aiTone} onChange={(e) => setAiTone(e.target.value)}>
            <option value="احترافي">احترافي</option>
            <option value="ودي">ودي</option>
            <option value="تسويقي">تسويقي</option>
            <option value="إبداعي">إبداعي</option>
          </select>
          <select className="input" value={aiLength} onChange={(e) => setAiLength(e.target.value)}>
            <option value="قصير">قصير</option>
            <option value="متوسط">متوسط</option>
            <option value="طويل">طويل</option>
          </select>
          <button className="btn btn-outline" onClick={() => void handleGenerateAi()} disabled={aiLoading}>
            {aiLoading ? "جارٍ التوليد..." : "توليد نص"}
          </button>
        </div>
      </section>

      <section className="card">
        <div className="card-title">المحتوى والوسائط</div>
        <textarea
          className="input textarea"
          placeholder="اكتب نص المنشور هنا..."
          value={text}
          onChange={(e) => setText(e.target.value)}
        />
        <div className="media-grid compact">
          {loading && <div className="empty">جاري تحميل الوسائط...</div>}
          {!loading &&
            media.map((item) => (
              <button
                key={item.id}
                className={`media-card ${selectedMedia.includes(item.id) ? "selected" : ""}`}
                type="button"
                onClick={() => toggleMedia(item.id)}
              >
                {item.media_type === "image" ? (
                  <img src={normalizeMediaUrl(item.url_path)} alt={item.original_name || item.filename} />
                ) : (
                  <div className="media-video-icon">🎬</div>
                )}
                <div className="media-meta">{item.original_name || item.filename}</div>
              </button>
            ))}
        </div>
      </section>

      <section className="card">
        <div className="card-title">الصفحات وخيارات النشر</div>
        <div className="pages-wrap">
          {loading && <div className="empty">جاري تحميل الصفحات...</div>}
          {!loading && pages.length === 0 && (
            <div className="empty">لا توجد صفحات مربوطة. اربط الصفحات من صفحة الإعدادات.</div>
          )}
          {!loading &&
            pages.map((page) => (
              <label key={page.id} className="page-chip">
                <input
                  type="checkbox"
                  checked={selectedPages.includes(page.page_id)}
                  onChange={() => togglePage(page.page_id)}
                />
                <span>{page.page_name}</span>
              </label>
            ))}
        </div>

        <div className="row">
          <button
            type="button"
            className={`btn ${mode === "now" ? "btn-primary" : "btn-outline"}`}
            onClick={() => setMode("now")}
          >
            نشر الآن
          </button>
          <button
            type="button"
            className={`btn ${mode === "scheduled" ? "btn-primary" : "btn-outline"}`}
            onClick={() => setMode("scheduled")}
          >
            جدولة
          </button>
          {mode === "scheduled" && (
            <input
              type="datetime-local"
              className="input"
              value={publishTime}
              onChange={(e) => setPublishTime(e.target.value)}
            />
          )}
        </div>

        <button className="btn btn-primary full" onClick={() => void handleSubmit()} disabled={submitting}>
          {submitting ? "جارٍ الإرسال..." : mode === "scheduled" ? "حفظ الجدولة" : "نشر الآن"}
        </button>
      </section>
    </>
  );
};

const MediaPage: React.FC<{ notify: (message: string, type?: ToastType) => void }> = ({
  notify,
}) => {
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [search, setSearch] = useState("");
  const [mediaType, setMediaType] = useState<"" | "image" | "video">("");
  const [items, setItems] = useState<PublisherMedia[]>([]);

  const load = async () => {
    setLoading(true);
    try {
      const response = await listMedia({
        q: search || undefined,
        type: mediaType || undefined,
        page: 1,
        per_page: 120,
      });
      setItems(response.items);
    } catch (error) {
      notify(getErrorMessage(error), "error");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void load();
  }, [search, mediaType]);

  const handleFiles = async (files: FileList | null) => {
    if (!files || !files.length) return;
    setUploading(true);
    try {
      for (const file of Array.from(files)) {
        await uploadMedia(file);
      }
      notify("تم رفع الملفات بنجاح.", "success");
      await load();
    } catch (error) {
      notify(getErrorMessage(error), "error");
    } finally {
      setUploading(false);
    }
  };

  const removeMedia = async (id: number) => {
    if (!window.confirm("هل تريد حذف هذا الوسيط؟")) return;
    try {
      await deleteMedia(id);
      notify("تم حذف الوسيط.", "success");
      await load();
    } catch (error) {
      notify(getErrorMessage(error), "error");
    }
  };

  return (
    <>
      <header className="page-header">
        <h1>مكتبة الوسائط</h1>
        <label className="btn btn-primary">
          {uploading ? "جارٍ الرفع..." : "رفع ملفات"}
          <input
            type="file"
            multiple
            accept="image/*,video/*"
            hidden
            disabled={uploading}
            onChange={(e) => void handleFiles(e.target.files)}
          />
        </label>
      </header>

      <section className="card">
        <div className="row">
          <input
            className="input"
            placeholder="بحث بالاسم..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
          <select className="input" value={mediaType} onChange={(e) => setMediaType(e.target.value as any)}>
            <option value="">الكل</option>
            <option value="image">صور</option>
            <option value="video">فيديو</option>
          </select>
          <button className="btn btn-outline" onClick={() => void load()}>
            إعادة تحميل
          </button>
        </div>
      </section>

      <section className="media-grid">
        {loading && <div className="empty">جاري تحميل الوسائط...</div>}
        {!loading && !items.length && <div className="empty">لا توجد وسائط حالياً.</div>}
        {!loading &&
          items.map((item) => (
            <div key={item.id} className="media-card">
              {item.media_type === "image" ? (
                <img src={normalizeMediaUrl(item.url_path)} alt={item.original_name || item.filename} />
              ) : (
                <div className="media-video-icon">🎬</div>
              )}
              <div className="media-meta">
                <div>{item.original_name || item.filename}</div>
                <div>{formatSize(item.size_bytes)}</div>
              </div>
              <div className="media-actions">
                <button className="btn btn-danger btn-sm" onClick={() => void removeMedia(item.id)}>
                  حذف
                </button>
              </div>
            </div>
          ))}
      </section>
    </>
  );
};

const SettingsPage: React.FC<{ notify: (message: string, type?: ToastType) => void }> = ({
  notify,
}) => {
  const [loading, setLoading] = useState(true);
  const [pagesLoading, setPagesLoading] = useState(false);
  const [fbAppId, setFbAppId] = useState("");
  const [fbAppSecret, setFbAppSecret] = useState("");
  const [fbUserToken, setFbUserToken] = useState("");
  const [pages, setPages] = useState<PublisherPage[]>([]);

  const load = async () => {
    setLoading(true);
    try {
      const [settingsRes, pagesRes] = await Promise.all([
        getSettings(),
        listPages({ page: 1, per_page: 200 }),
      ]);
      setFbAppId(settingsRes.fb_app_id || "");
      setPages(pagesRes.items);
    } catch (error) {
      notify(getErrorMessage(error), "error");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void load();
  }, []);

  const loadPages = async () => {
    setPagesLoading(true);
    try {
      const pagesRes = await listPages({ page: 1, per_page: 200 });
      setPages(pagesRes.items);
    } catch (error) {
      notify(getErrorMessage(error), "error");
    } finally {
      setPagesLoading(false);
    }
  };

  const saveCredentials = async () => {
    try {
      const message = await saveSettings({
        fb_app_id: fbAppId.trim(),
        fb_app_secret: fbAppSecret.trim() || undefined,
      });
      setFbAppSecret("");
      notify(message, "success");
    } catch (error) {
      notify(getErrorMessage(error), "error");
    }
  };

  const saveToken = async () => {
    if (!fbUserToken.trim()) {
      notify("أدخل User Token أولاً.", "error");
      return;
    }
    try {
      const message = await saveSettings({ fb_user_token: fbUserToken.trim() });
      setFbUserToken("");
      notify(message, "success");
    } catch (error) {
      notify(getErrorMessage(error), "error");
    }
  };

  const syncPages = async () => {
    try {
      const message = await connectPages(fbUserToken.trim() || undefined);
      notify(message, "success");
      if (fbUserToken.trim()) setFbUserToken("");
      await loadPages();
    } catch (error) {
      notify(getErrorMessage(error), "error");
    }
  };

  const removePage = async (id: number) => {
    if (!window.confirm("إلغاء ربط هذه الصفحة؟")) return;
    try {
      await deletePage(id);
      notify("تم إلغاء ربط الصفحة.", "success");
      await loadPages();
    } catch (error) {
      notify(getErrorMessage(error), "error");
    }
  };

  return (
    <>
      <header className="page-header">
        <h1>إعدادات الناشر</h1>
        <button className="btn btn-outline" onClick={() => void load()}>
          تحديث
        </button>
      </header>

      <section className="card">
        <div className="card-title">بيانات التطبيق</div>
        {loading ? (
          <div className="empty">جاري تحميل الإعدادات...</div>
        ) : (
          <>
            <div className="form-group">
              <label>App ID</label>
              <input
                className="input"
                dir="ltr"
                value={fbAppId}
                placeholder="123456789..."
                onChange={(e) => setFbAppId(e.target.value)}
              />
            </div>
            <div className="form-group">
              <label>App Secret</label>
              <input
                className="input"
                dir="ltr"
                type="password"
                value={fbAppSecret}
                placeholder="سيتم حفظه بشكل مشفر"
                onChange={(e) => setFbAppSecret(e.target.value)}
              />
            </div>
            <button className="btn btn-primary" onClick={() => void saveCredentials()}>
              حفظ بيانات التطبيق
            </button>
          </>
        )}
      </section>

      <section className="card">
        <div className="card-title">User Access Token والصفحات</div>
        <div className="form-group">
          <label>User Token</label>
          <input
            className="input"
            dir="ltr"
            type="password"
            value={fbUserToken}
            placeholder="EAAB..."
            onChange={(e) => setFbUserToken(e.target.value)}
          />
        </div>
        <div className="row">
          <button className="btn btn-outline" onClick={() => void saveToken()}>
            حفظ التوكن
          </button>
          <button className="btn btn-primary" onClick={() => void syncPages()}>
            جلب وربط الصفحات
          </button>
        </div>
      </section>

      <section className="card">
        <div className="card-title">الصفحات المربوطة</div>
        {pagesLoading && <div className="empty">جاري تحديث الصفحات...</div>}
        {!pagesLoading && pages.length === 0 && <div className="empty">لا توجد صفحات مربوطة.</div>}
        {!pagesLoading &&
          pages.map((page) => (
            <div key={page.id} className="list-row">
              <div>
                <div>{page.page_name}</div>
                <div className="muted">ID: {page.page_id}</div>
              </div>
              <button className="btn btn-danger btn-sm" onClick={() => void removePage(page.id)}>
                حذف
              </button>
            </div>
          ))}
      </section>
    </>
  );
};
