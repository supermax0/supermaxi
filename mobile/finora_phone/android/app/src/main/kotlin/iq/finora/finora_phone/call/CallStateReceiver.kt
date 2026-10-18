package iq.finora.finora_phone.call

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.telephony.TelephonyManager

/**
 * Secondary PHONE_STATE path — and the only source of the incoming number on
 * API 31+, where TelephonyCallback no longer reports it.
 *
 * The number is always published (needs READ_CALL_LOG to be delivered by the
 * platform); only opening the overlay is gated so it never double-opens.
 */
class CallStateReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action != TelephonyManager.ACTION_PHONE_STATE_CHANGED) return
        val state = intent.getStringExtra(TelephonyManager.EXTRA_STATE) ?: return
        @Suppress("DEPRECATION")
        val number = intent.getStringExtra(TelephonyManager.EXTRA_INCOMING_NUMBER)?.trim().orEmpty()

        if (state == TelephonyManager.EXTRA_STATE_IDLE) {
            CallStateMonitor.clearCachedNumber()
            return
        }
        if (number.isNotEmpty()) {
            CallStateMonitor.publishNumber(context, number)
        }
        if (state != TelephonyManager.EXTRA_STATE_RINGING) return
        if (!CallStateMonitor.globalOverlayGate.compareAndSet(false, true)) return
        try {
            val svc = Intent(context, iq.finora.finora_phone.overlay.CrmOverlayService::class.java).apply {
                action = iq.finora.finora_phone.overlay.CrmOverlayService.ACTION_SHOW
                putExtra(iq.finora.finora_phone.overlay.CrmOverlayService.EXTRA_NUMBER, number)
            }
            androidx.core.content.ContextCompat.startForegroundService(context, svc)
        } catch (_: Exception) {
            CallStateMonitor.globalOverlayGate.set(false)
        }
    }
}
