package iq.finora.finora_phone.call

import android.content.Context
import android.database.ContentObserver
import android.net.Uri
import android.os.Handler
import android.os.Looper
import android.provider.CallLog

/**
 * Watches CallLog for missed-call recovery when process was killed during RINGING.
 */
class CallLogObserver(
    private val context: Context,
    private val onChanged: () -> Unit,
) : ContentObserver(Handler(Looper.getMainLooper())) {
    fun register() {
        try {
            context.contentResolver.registerContentObserver(
                CallLog.Calls.CONTENT_URI,
                true,
                this,
            )
        } catch (_: SecurityException) {
        } catch (_: Exception) {
        }
    }

    fun unregister() {
        try {
            context.contentResolver.unregisterContentObserver(this)
        } catch (_: Exception) {
        }
    }

    override fun onChange(selfChange: Boolean, uri: Uri?) {
        onChanged()
    }
}
