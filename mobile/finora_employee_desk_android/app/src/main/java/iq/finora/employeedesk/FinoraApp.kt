package iq.finora.employeedesk

import android.app.Application
import android.app.NotificationChannel
import android.app.NotificationManager
import android.content.Context
import android.os.Build
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import java.util.concurrent.TimeUnit

class FinoraApp : Application() {
    override fun onCreate() {
        super.onCreate()
        instance = this
        ensureChannel()
        WorkManager.getInstance(this).enqueueUniquePeriodicWork(
            "desk-alerts",
            ExistingPeriodicWorkPolicy.UPDATE,
            PeriodicWorkRequestBuilder<AlertWorker>(15, TimeUnit.MINUTES).build()
        )
    }

    companion object {
        private lateinit var instance: FinoraApp
        const val PREFS_NAME = "finora_employee_desk"
        const val KEY_BASE_URL = "base_url"
        const val KEY_TENANT_SLUG = "tenant_slug"
        const val KEY_LAST_ALERT = "last_alert_key"
        const val CHANNEL_ID = "employee_desk"
        const val DEFAULT_BASE_URL = "https://www.finora.company"

        fun prefs(context: Context = instance) =
            context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)

        fun getBaseUrl(context: Context = instance): String {
            return prefs(context).getString(KEY_BASE_URL, DEFAULT_BASE_URL)?.trim()?.trimEnd('/')
                ?: DEFAULT_BASE_URL
        }

        fun getTenantSlug(context: Context = instance): String? {
            return prefs(context).getString(KEY_TENANT_SLUG, null)?.trim()?.lowercase()?.takeIf { it.isNotEmpty() }
        }

        fun saveCompanyConfig(context: Context, baseUrl: String, tenantSlug: String) {
            prefs(context).edit()
                .putString(KEY_BASE_URL, baseUrl.trim().trimEnd('/'))
                .putString(KEY_TENANT_SLUG, tenantSlug.trim().lowercase())
                .apply()
        }

        fun deskLoginUrl(context: Context = instance): String? {
            val slug = getTenantSlug(context) ?: return null
            return "${getBaseUrl(context)}/employee-desk/login/$slug"
        }

        fun deskStartUrl(context: Context = instance): String? {
            val slug = getTenantSlug(context) ?: return null
            val base = getBaseUrl(context)
            val cookie = android.webkit.CookieManager.getInstance().getCookie(base).orEmpty()
            return if (cookie.contains("session")) "$base/employee-desk" else "$base/employee-desk/login/$slug"
        }

        fun parseDeskLink(url: String?): Pair<String, String>? {
            if (url.isNullOrBlank()) return null
            return try {
                val uri = android.net.Uri.parse(url.trim())
                val host = uri.host ?: return null
                val scheme = uri.scheme ?: "https"
                val segments = uri.pathSegments
                val loginIdx = segments.indexOf("login")
                val tenant = when {
                    loginIdx >= 0 && segments.size > loginIdx + 1 -> segments[loginIdx + 1]
                    else -> return null
                }
                Pair("$scheme://$host".trimEnd('/'), tenant.lowercase())
            } catch (_: Exception) {
                null
            }
        }

        fun ensureChannel(context: Context = instance) {
            if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return
            val manager = context.getSystemService(NotificationManager::class.java) ?: return
            manager.createNotificationChannel(
                NotificationChannel(
                    CHANNEL_ID,
                    context.getString(R.string.notif_channel),
                    NotificationManager.IMPORTANCE_HIGH
                )
            )
        }
    }
}
