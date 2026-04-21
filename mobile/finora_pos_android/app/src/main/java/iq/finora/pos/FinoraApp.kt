package iq.finora.pos

import android.app.Application
import iq.finora.pos.data.SessionCookieCaptureInterceptor
import iq.finora.pos.data.SessionCookieSendInterceptor
import okhttp3.CookieJar
import okhttp3.ConnectionSpec
import okhttp3.OkHttpClient
import java.util.concurrent.TimeUnit

class FinoraApp : Application() {

    lateinit var httpClient: OkHttpClient
        private set

    override fun onCreate() {
        super.onCreate()
        val prefs = getSharedPreferences(PREFS_NAME, MODE_PRIVATE)
        // إزالة كوكيز قديمة من نسخة OkHttp CookieJar السابقة
        prefs.edit().remove("okhttp_cookies").apply()

        httpClient = OkHttpClient.Builder()
            .cookieJar(CookieJar.NO_COOKIES)
            .addInterceptor(SessionCookieSendInterceptor(prefs))
            .addNetworkInterceptor(SessionCookieCaptureInterceptor(prefs))
            .followRedirects(true)
            .followSslRedirects(true)
            .connectTimeout(30, TimeUnit.SECONDS)
            .readTimeout(120, TimeUnit.SECONDS)
            .writeTimeout(60, TimeUnit.SECONDS)
            .connectionSpecs(listOf(ConnectionSpec.MODERN_TLS, ConnectionSpec.CLEARTEXT))
            .build()
    }

    companion object {
        const val PREFS_NAME = "finora_pos"
        const val KEY_BASE_URL = "base_url"
        /** قيمة رأس Cookie لكوكي الجلسة، مثل session=... */
        const val KEY_SESSION_COOKIE_PAIR = "session_cookie_pair"
    }
}
