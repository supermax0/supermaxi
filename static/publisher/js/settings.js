/* settings.js — Publisher Settings page interactions */

function settingsToast(msg, type = "info") {
    const wrap = document.getElementById("toastWrap");
    if (!wrap) return;
    const t = document.createElement("div");
    t.className = "pub-toast " + type;
    t.textContent = msg || "";
    wrap.appendChild(t);
    setTimeout(() => t.remove(), 4200);
}

async function settingsFetchJson(url, options = {}) {
    const opts = {
        credentials: "include",
        ...options,
        headers: {
            Accept: "application/json",
            ...(options.headers || {}),
        },
    };
    const res = await fetch(url, opts);
    const contentType = res.headers.get("content-type") || "";
    if (!contentType.includes("application/json")) {
        return { success: false, message: "استجابة غير صالحة من الخادم" };
    }
    return res.json();
}

function settingsSetDot(id, hasValue) {
    const el = document.getElementById(id);
    if (!el) return;
    el.className = "status-dot " + (hasValue ? "dot-green" : "dot-gray");
}

function settingsGetPayloadData(payload, legacyKey) {
    if (payload && payload.data && typeof payload.data === "object") return payload.data;
    if (legacyKey && payload && payload[legacyKey] !== undefined) return payload[legacyKey];
    return null;
}

function settingsTogglePassword(button) {
    const inputId = button.getAttribute("data-target");
    if (!inputId) return;
    const input = document.getElementById(inputId);
    if (!input) return;
    input.type = input.type === "password" ? "text" : "password";
}

async function settingsLoadSettings() {
    try {
        const r = await settingsFetchJson("/publisher/api/settings");
        if (!r.success) return;
        const s = settingsGetPayloadData(r, "settings") || {};

        const appId = document.getElementById("fbAppId");
        if (appId) {
            appId.placeholder = s.fb_app_id || "App ID...";
            if (s.fb_app_id) appId.value = s.fb_app_id;
        }
        const openAiInput = document.getElementById("openAiApiKey");
        if (openAiInput) {
            openAiInput.placeholder = s.has_openai_key ? "●●●●●●●●" : "sk-...";
        }
        settingsSetDot("appIdDot", !!s.fb_app_id);
        settingsSetDot("appSecretDot", !!s.has_secret);
        settingsSetDot("tokenDot", !!s.has_token);
        settingsSetDot("openAiDot", !!s.has_openai_key);
    } catch (e) {
        console.error(e);
    }
}

async function settingsSaveCredentials() {
    const btn = document.getElementById("saveCredentialsBtn");
    const fb_app_id = (document.getElementById("fbAppId")?.value || "").trim();
    const fb_app_secret = (document.getElementById("fbAppSecret")?.value || "").trim();
    const openai_api_key = (document.getElementById("openAiApiKey")?.value || "").trim();

    if (!fb_app_id && !fb_app_secret && !openai_api_key) {
        settingsToast("أدخل App ID أو App Secret أو OpenAI API Key", "error");
        return;
    }

    if (btn) btn.disabled = true;
    try {
        const r = await settingsFetchJson("/publisher/api/settings", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ fb_app_id, fb_app_secret, openai_api_key }),
        });
        if (r.success) {
            settingsToast(r.message || "تم حفظ الإعدادات", "success");
            const saved = settingsGetPayloadData(r, "settings") || {};
            settingsSetDot("appIdDot", !!saved.fb_app_id);
            settingsSetDot("appSecretDot", !!saved.has_secret);
            settingsSetDot("openAiDot", !!saved.has_openai_key);
            const secret = document.getElementById("fbAppSecret");
            if (secret) secret.value = "";
            const openAiInput = document.getElementById("openAiApiKey");
            if (openAiInput) openAiInput.value = "";
        } else {
            settingsToast(r.message || "حدث خطأ أثناء الحفظ", "error");
        }
    } finally {
        if (btn) btn.disabled = false;
    }
}

async function settingsSaveToken() {
    const btn = document.getElementById("saveTokenBtn");
    const fb_user_token = (document.getElementById("fbUserToken")?.value || "").trim();
    if (!fb_user_token) {
        settingsToast("أدخل User Token أولاً", "error");
        return;
    }

    if (btn) btn.disabled = true;
    try {
        const r = await settingsFetchJson("/publisher/api/settings", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ fb_user_token }),
        });
        if (r.success) {
            settingsToast(r.message || "تم حفظ التوكن", "success");
            settingsSetDot("tokenDot", true);
            const token = document.getElementById("fbUserToken");
            if (token) token.value = "";
        } else {
            settingsToast(r.message || "فشل حفظ التوكن", "error");
        }
    } finally {
        if (btn) btn.disabled = false;
    }
}

async function settingsConnectPages() {
    const container = document.getElementById("pagesContainer");
    const noMsg = document.getElementById("noPagesMsg");
    const token = (document.getElementById("fbUserToken")?.value || "").trim();

    if (container) {
        container.innerHTML = '<div class="empty-state"><span class="spinner"></span><p>جاري جلب الصفحات...</p></div>';
    }
    if (noMsg) noMsg.style.display = "none";

    const r = await settingsFetchJson("/publisher/api/settings/connect-pages", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(token ? { user_token: token } : {}),
    });

    if (r.success) {
        settingsToast(r.message || "تم ربط الصفحات", "success");
        if (token) {
            const tokenInput = document.getElementById("fbUserToken");
            if (tokenInput) tokenInput.value = "";
            settingsSetDot("tokenDot", true);
        }
    } else {
        settingsToast(r.message || "خطأ في جلب الصفحات", "error");
    }

    await settingsRenderSavedPages();
}

async function settingsRenderSavedPages() {
    const container = document.getElementById("pagesContainer");
    const noMsg = document.getElementById("noPagesMsg");
    if (!container || !noMsg) return;

    try {
        const r = await settingsFetchJson("/publisher/api/pages");
        const pagesData = settingsGetPayloadData(r, "pages");
        const pages = Array.isArray(pagesData)
            ? pagesData
            : (pagesData && Array.isArray(pagesData.items) ? pagesData.items : []);

        if (!pages.length) {
            container.innerHTML = "";
            noMsg.style.display = "block";
            return;
        }

        noMsg.style.display = "none";
        container.innerHTML = "";

        const list = document.createElement("div");
        list.className = "page-list";
        pages.forEach((p) => {
            const item = document.createElement("div");
            item.className = "page-item";

            const info = document.createElement("div");
            info.className = "page-item-info";

            const avatar = document.createElement("div");
            avatar.className = "page-avatar";
            avatar.textContent = "F";

            const txt = document.createElement("div");
            const name = document.createElement("div");
            name.className = "page-name";
            name.textContent = p.page_name || "بدون اسم";

            const pageId = document.createElement("div");
            pageId.className = "page-id";
            pageId.textContent = "ID: " + (p.page_id || "");

            txt.appendChild(name);
            txt.appendChild(pageId);

            info.appendChild(avatar);
            info.appendChild(txt);

            const actions = document.createElement("div");
            actions.className = "page-actions";

            const linked = document.createElement("span");
            linked.className = "badge badge-published";
            linked.textContent = "مربوطة";

            const del = document.createElement("button");
            del.className = "btn-icon btn-sm";
            del.type = "button";
            del.textContent = "حذف";
            del.addEventListener("click", () => settingsDeletePage(p.id));

            actions.appendChild(linked);
            actions.appendChild(del);

            item.appendChild(info);
            item.appendChild(actions);
            list.appendChild(item);
        });
        container.appendChild(list);
    } catch (e) {
        container.innerHTML = '<p class="danger-text">خطأ في تحميل الصفحات</p>';
    }
}

async function settingsDeletePage(id) {
    if (!confirm("هل تريد إلغاء ربط هذه الصفحة؟")) return;
    const r = await settingsFetchJson("/publisher/api/pages/" + id, {
        method: "DELETE",
    });
    if (r.success) {
        settingsToast("تم إلغاء الربط", "success");
        settingsRenderSavedPages();
    } else {
        settingsToast(r.message || "حدث خطأ", "error");
    }
}

document.addEventListener("DOMContentLoaded", () => {
    document.querySelectorAll(".eye-btn[data-target]").forEach((btn) => {
        btn.addEventListener("click", () => settingsTogglePassword(btn));
    });

    document.getElementById("saveCredentialsBtn")?.addEventListener("click", settingsSaveCredentials);
    document.getElementById("saveTokenBtn")?.addEventListener("click", settingsSaveToken);
    document.getElementById("connectPagesBtn")?.addEventListener("click", settingsConnectPages);
    document.getElementById("refreshPagesBtn")?.addEventListener("click", settingsConnectPages);

    settingsLoadSettings();
    settingsRenderSavedPages();
});
