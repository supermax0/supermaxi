package iq.finora.employeedesk

import android.webkit.CookieManager
import androidx.work.Worker
import androidx.work.WorkerParameters
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL

class AlertWorker(
    private val context: android.content.Context,
    params: WorkerParameters
) : Worker(context, params) {
    override fun doWork(): Result {
        val base = FinoraApp.getBaseUrl(context)
        val cookie = CookieManager.getInstance().getCookie(base) ?: return Result.success()
        return try {
            val conn = URL("$base/api/employee-desk/alerts").openConnection() as HttpURLConnection
            conn.connectTimeout = 12000
            conn.readTimeout = 12000
            conn.setRequestProperty("Cookie", cookie)
            conn.setRequestProperty("Accept", "application/json")
            val text = conn.inputStream.bufferedReader().readText()
            conn.disconnect()
            val data = JSONObject(text)
            if (!data.optBoolean("ok")) return Result.success()
            val unread = data.optInt("unread", 0)
            val latest = data.optJSONObject("latest") ?: return Result.success()
            val key = "${latest.optString("page_id")}:${latest.optString("psid")}:${latest.optString("preview")}"
            val last = FinoraApp.prefs(context).getString(FinoraApp.KEY_LAST_ALERT, "")
            if (unread > 0 && key.isNotBlank() && key != last) {
                FinoraApp.prefs(context).edit().putString(FinoraApp.KEY_LAST_ALERT, key).apply()
                DeskNotifier.show(
                    context,
                    latest.optString("name", context.getString(R.string.notif_title)),
                    latest.optString("preview", "رسالة جديدة")
                )
            }
            Result.success()
        } catch (_: Exception) {
            Result.retry()
        }
    }
}
