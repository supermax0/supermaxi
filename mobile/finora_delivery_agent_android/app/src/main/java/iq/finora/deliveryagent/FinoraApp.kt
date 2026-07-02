package iq.finora.deliveryagent

import android.app.Application
import android.content.Context

class FinoraApp : Application() {
    override fun onCreate() {
        super.onCreate()
        instance = this
    }

    companion object {
        private lateinit var instance: FinoraApp

        const val PREFS_NAME = "finora_delivery_agent"
        const val KEY_BASE_URL = "base_url"
        const val KEY_TENANT_SLUG = "tenant_slug"
        const val DEFAULT_BASE_URL = "https://www.finora.company"

        fun prefs(context: Context = instance) =
            context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)

        fun getBaseUrl(context: Context = instance): String {
            return prefs(context).getString(KEY_BASE_URL, DEFAULT_BASE_URL)?.trim()?.trimEnd('/')
                ?: DEFAULT_BASE_URL
        }

        fun getTenantSlug(context: Context = instance): String? {
            val slug = prefs(context).getString(KEY_TENANT_SLUG, null)?.trim()?.lowercase()
            return slug?.takeIf { it.isNotEmpty() }
        }

        fun saveCompanyConfig(context: Context, baseUrl: String, tenantSlug: String) {
            prefs(context).edit()
                .putString(KEY_BASE_URL, baseUrl.trim().trimEnd('/'))
                .putString(KEY_TENANT_SLUG, tenantSlug.trim().lowercase())
                .apply()
        }

        fun portalLoginUrl(context: Context = instance): String? {
            val slug = getTenantSlug(context) ?: return null
            return "${getBaseUrl(context)}/delivery-agent/login/$slug"
        }

        fun parsePortalLink(url: String?): Pair<String, String>? {
            if (url.isNullOrBlank()) return null
            return try {
                val uri = android.net.Uri.parse(url.trim())
                val host = uri.host ?: return null
                val scheme = uri.scheme ?: "https"
                val segments = uri.pathSegments
                val loginIdx = segments.indexOf("login")
                val tenant = when {
                    loginIdx >= 0 && segments.size > loginIdx + 1 -> segments[loginIdx + 1]
                    segments.size >= 3 && segments[0] == "delivery-agent" && segments[1] == "login" -> segments[2]
                    else -> return null
                }
                val base = "$scheme://$host"
                Pair(base.trimEnd('/'), tenant.lowercase())
            } catch (_: Exception) {
                null
            }
        }
    }
}
