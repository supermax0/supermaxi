package iq.finora.pos.data

import android.content.SharedPreferences
import iq.finora.pos.FinoraApp
import okhttp3.HttpUrl.Companion.toHttpUrlOrNull
import okhttp3.Interceptor
import okhttp3.Response

/**
 * يلتقط سطر Set-Cookie لكوكي الجلسة من **كل** استجابة شبكة (بما فيها 302 بعد POST /login).
 * بدون هذا، قد لا يصل كوكي الجلسة إلى OkHttp CookieJar عند اتباع التحويلات.
 */
class SessionCookieCaptureInterceptor(
    private val prefs: SharedPreferences
) : Interceptor {

    override fun intercept(chain: Interceptor.Chain): Response {
        val resp = chain.proceed(chain.request())
        for (line in resp.headers("Set-Cookie")) {
            if (line.contains("Max-Age=0", ignoreCase = true)) {
                val seg = line.split(";").firstOrNull()?.trim() ?: continue
                val name = seg.substringBefore("=").trim()
                if (name.equals("session", ignoreCase = true)) {
                    prefs.edit().remove(FinoraApp.KEY_SESSION_COOKIE_PAIR).apply()
                }
                continue
            }
            val pair = extractSessionPair(line) ?: continue
            prefs.edit().putString(FinoraApp.KEY_SESSION_COOKIE_PAIR, pair).apply()
        }
        return resp
    }

    private fun extractSessionPair(setCookieLine: String): String? {
        val seg = setCookieLine.split(";").firstOrNull()?.trim() ?: return null
        val idx = seg.indexOf('=')
        if (idx < 1) return null
        val name = seg.substring(0, idx).trim()
        if (!name.equals("session", ignoreCase = true)) return null
        val value = seg.substring(idx + 1)
        if (value.isEmpty()) return null
        return "$name=$value"
    }
}

/**
 * يضيف رأس Cookie لكل طلب إلى نفس مضيف عنوان الخادم المحفوظ.
 */
class SessionCookieSendInterceptor(
    private val prefs: SharedPreferences
) : Interceptor {

    override fun intercept(chain: Interceptor.Chain): Response {
        val req = chain.request()
        val base = prefs.getString(FinoraApp.KEY_BASE_URL, null)?.trim()?.trimEnd('/')
            ?: return chain.proceed(req)
        val baseHost = base.toHttpUrlOrNull()?.host ?: return chain.proceed(req)
        if (req.url.host != baseHost) return chain.proceed(req)

        val pair = prefs.getString(FinoraApp.KEY_SESSION_COOKIE_PAIR, null) ?: return chain.proceed(req)
        val existing = req.header("Cookie")
        val merged = mergeCookieHeader(existing, pair)
        val newReq = req.newBuilder().header("Cookie", merged).build()
        return chain.proceed(newReq)
    }

    private fun mergeCookieHeader(existing: String?, pair: String): String {
        if (existing.isNullOrBlank()) return pair
        if (existing.contains("session=", ignoreCase = true)) {
            val parts = existing.split(";").map { it.trim() }.filter { it.isNotEmpty() }
                .filterNot { it.startsWith("session=", ignoreCase = true) }
            return (parts + pair).joinToString("; ")
        }
        return "$existing; $pair"
    }
}
