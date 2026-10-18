package iq.finora.finora_phone.call

import android.Manifest
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import android.os.Handler
import android.os.Looper
import android.provider.CallLog
import android.telephony.PhoneStateListener
import android.telephony.TelephonyCallback
import android.telephony.TelephonyManager
import java.util.concurrent.atomic.AtomicBoolean

/**
 * Observes call state for Companion CRM Overlay.
 * Does NOT answer/reject. Does NOT register as dialer.
 *
 * Emits stable idempotencyKey = phone|direction|bucket|device|sim
 * Dedupes RINGING so BroadcastReceiver + Monitor don't double-fire.
 *
 * Number sourcing: TelephonyCallback (API 31+) carries no phone number, so the
 * number comes from PHONE_STATE broadcast / outgoing dial / CallLog recovery and
 * is merged here before the start event is emitted.
 */
class CallStateMonitor(
    private val context: Context,
    private val onEvent: (Map<String, Any?>) -> Unit,
) {
    private val telephony = context.getSystemService(Context.TELEPHONY_SERVICE) as TelephonyManager
    private val handler = Handler(Looper.getMainLooper())
    private var lastState = TelephonyManager.CALL_STATE_IDLE
    private var ringingNumber: String? = null
    private var startedAtMs: Long = 0L
    private var direction: String = "inbound"
    private var idempotencyKey: String? = null
    private var callback: Any? = null
    private var pendingStart: Runnable? = null
    private var pendingStartType: String? = null
    private var startEmitted = false
    private val overlayShown = AtomicBoolean(false)

    companion object {
        /** Process-wide gate so CallStateReceiver cannot double-show. */
        @JvmStatic
        val globalOverlayGate = AtomicBoolean(false)

        /** Grace period to let the number arrive before emitting the start event. */
        private const val NUMBER_WAIT_MS = 450L

        /** CallLog needs a moment to persist the row after the call ends. */
        private const val CALL_LOG_RECOVERY_DELAY_MS = 800L

        /** A number is only trusted for the call it was published for. */
        private const val NUMBER_TTL_MS = 90_000L

        @Volatile
        private var pendingNumber: String = ""

        @Volatile
        private var pendingNumberAtMs: Long = 0L

        @Volatile
        private var activeMonitor: CallStateMonitor? = null

        @JvmStatic
        fun cachedNumber(): String {
            if (pendingNumber.isEmpty()) return ""
            if (System.currentTimeMillis() - pendingNumberAtMs > NUMBER_TTL_MS) return ""
            return pendingNumber
        }

        /**
         * Feeds the number of the in-flight call from any secondary source
         * (PHONE_STATE broadcast, outgoing dial, CallLog recovery).
         */
        @JvmStatic
        fun publishNumber(context: Context, raw: String?) {
            val number = raw?.trim().orEmpty()
            if (number.isEmpty()) return
            pendingNumber = number
            pendingNumberAtMs = System.currentTimeMillis()
            activeMonitor?.onNumberResolved(number)
            pushNumberToOverlay(context, number)
        }

        @JvmStatic
        fun clearCachedNumber() {
            pendingNumber = ""
            pendingNumberAtMs = 0L
        }

        private fun pushNumberToOverlay(context: Context, number: String) {
            if (!globalOverlayGate.get()) return
            try {
                val intent = Intent(
                    context,
                    iq.finora.finora_phone.overlay.CrmOverlayService::class.java,
                ).apply {
                    action = iq.finora.finora_phone.overlay.CrmOverlayService.ACTION_NUMBER
                    putExtra(
                        iq.finora.finora_phone.overlay.CrmOverlayService.EXTRA_NUMBER,
                        number,
                    )
                }
                context.startService(intent)
            } catch (_: Exception) {
            }
        }

        @JvmStatic
        fun buildIdempotencyKey(
            phone: String,
            direction: String,
            startedAtMs: Long,
            deviceId: String,
            simSlot: Int?,
            bucketSeconds: Int = 5,
        ): String {
            val bucket = (startedAtMs / (bucketSeconds * 1000L)) * (bucketSeconds * 1000L)
            val norm = phone.filter { it.isDigit() }.let {
                if (it.length >= 10) it.takeLast(10) else it.ifEmpty { "unknown" }
            }
            val sim = simSlot?.toString() ?: "na"
            return "call|$norm|$direction|$bucket|$deviceId|$sim"
        }
    }

    fun start() {
        activeMonitor = this
        try {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
                val cb = object : TelephonyCallback(), TelephonyCallback.CallStateListener {
                    override fun onCallStateChanged(state: Int) {
                        handleState(state, null)
                    }
                }
                telephony.registerTelephonyCallback(context.mainExecutor, cb)
                callback = cb
            } else {
                @Suppress("DEPRECATION")
                val listener = object : PhoneStateListener() {
                    @Deprecated("Deprecated in Java")
                    override fun onCallStateChanged(state: Int, phoneNumber: String?) {
                        handleState(state, phoneNumber)
                    }
                }
                @Suppress("DEPRECATION")
                telephony.listen(listener, PhoneStateListener.LISTEN_CALL_STATE)
                callback = listener
            }
        } catch (_: SecurityException) {
        } catch (_: Exception) {
        }
    }

    fun stop() {
        if (activeMonitor === this) activeMonitor = null
        cancelPendingStart()
        try {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
                val cb = callback as? TelephonyCallback ?: return
                telephony.unregisterTelephonyCallback(cb)
            } else {
                @Suppress("DEPRECATION")
                val listener = callback as? PhoneStateListener ?: return
                @Suppress("DEPRECATION")
                telephony.listen(listener, PhoneStateListener.LISTEN_NONE)
            }
        } catch (_: Exception) {
        }
        callback = null
    }

    private fun deviceId(): String {
        val prefs = context.getSharedPreferences("finora_phone_native", Context.MODE_PRIVATE)
        var id = prefs.getString("device_id", null)
        if (id.isNullOrBlank()) {
            id = java.util.UUID.randomUUID().toString()
            prefs.edit().putString("device_id", id).apply()
        }
        return id
    }

    private fun activeSimSlot(): Int? {
        return try {
            if (Build.VERSION.SDK_INT < Build.VERSION_CODES.LOLLIPOP_MR1) return null
            val sm = context.getSystemService(android.telephony.SubscriptionManager::class.java)
                ?: return null
            val list = sm.activeSubscriptionInfoList ?: return null
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.N) {
                val defId = android.telephony.SubscriptionManager.getDefaultVoiceSubscriptionId()
                val match = list.firstOrNull { it.subscriptionId == defId }
                if (match != null) return match.simSlotIndex
            }
            if (list.size == 1) list[0].simSlotIndex else null
        } catch (_: Exception) {
            null
        }
    }

    private fun handleState(state: Int, phoneNumber: String?) {
        when (state) {
            TelephonyManager.CALL_STATE_RINGING -> {
                if (lastState == TelephonyManager.CALL_STATE_RINGING) return
                direction = "inbound"
                startedAtMs = System.currentTimeMillis()
                ringingNumber = firstNonBlank(phoneNumber, cachedNumber(), ringingNumber)
                maybeShowOverlay(ringingNumber.orEmpty())
                beginStart("ringing")
            }
            TelephonyManager.CALL_STATE_OFFHOOK -> {
                if (lastState == TelephonyManager.CALL_STATE_IDLE) {
                    // Outbound: no RINGING first.
                    direction = "outbound"
                    startedAtMs = System.currentTimeMillis()
                    ringingNumber = firstNonBlank(phoneNumber, cachedNumber(), ringingNumber)
                    maybeShowOverlay(ringingNumber.orEmpty())
                    beginStart("outbound")
                } else {
                    flushPendingStart()
                    emit("answered", ringingNumber, activeSimSlot())
                }
                notifyOverlayAnswered()
            }
            TelephonyManager.CALL_STATE_IDLE -> {
                val previous = lastState
                flushPendingStart()
                val endType = when (previous) {
                    TelephonyManager.CALL_STATE_RINGING -> "missed"
                    TelephonyManager.CALL_STATE_OFFHOOK -> "ended"
                    else -> null
                }
                val ended = EndedCall(
                    number = firstNonBlank(ringingNumber, cachedNumber()),
                    clientId = idempotencyKey,
                    direction = direction,
                    startedAtMs = startedAtMs,
                )
                releaseCallState()
                if (endType == null) {
                    hideOverlay()
                } else if (ended.number.isNotEmpty() || !hasCallLogPermission()) {
                    finishCall(endType, ended)
                } else {
                    recoverNumberThenFinish(endType, ended)
                }
            }
        }
        lastState = state
    }

    /** Emits the start event once the number is known, or after a short grace period. */
    private fun beginStart(type: String) {
        cancelPendingStart()
        startEmitted = false
        pendingStartType = type
        if (!ringingNumber.isNullOrBlank()) {
            emitStart(type)
            return
        }
        val runnable = Runnable { emitStart(type) }
        pendingStart = runnable
        handler.postDelayed(runnable, NUMBER_WAIT_MS)
    }

    private fun emitStart(type: String) {
        cancelPendingStart()
        if (startEmitted) return
        startEmitted = true
        val sim = activeSimSlot()
        val number = ringingNumber.orEmpty()
        idempotencyKey = buildIdempotencyKey(number, direction, startedAtMs, deviceId(), sim)
        if (type == "outbound") {
            emit("detected", number, sim)
            emit("answered", number, sim)
        } else {
            emit("ringing", number, sim)
        }
    }

    private fun flushPendingStart() {
        val type = pendingStartType ?: return
        if (startEmitted) return
        emitStart(type)
    }

    private fun cancelPendingStart() {
        pendingStart?.let { handler.removeCallbacks(it) }
        pendingStart = null
    }

    /** Called when a secondary source resolves the number of the in-flight call. */
    private fun onNumberResolved(number: String) {
        handler.post {
            if (ringingNumber.isNullOrBlank()) {
                ringingNumber = number
            }
            if (!startEmitted && pendingStartType != null) {
                emitStart(pendingStartType!!)
            }
        }
    }

    private fun releaseCallState() {
        cancelPendingStart()
        pendingStartType = null
        startEmitted = false
        ringingNumber = null
        idempotencyKey = null
        overlayShown.set(false)
        globalOverlayGate.set(false)
        clearCachedNumber()
    }

    private data class EndedCall(
        val number: String,
        val clientId: String?,
        val direction: String,
        val startedAtMs: Long,
    )

    private fun finishCall(endType: String, ended: EndedCall) {
        onEvent(
            mapOf(
                "type" to endType,
                "number" to ended.number,
                "direction" to ended.direction,
                "startedAt" to java.time.Instant.ofEpochMilli(
                    if (ended.startedAtMs == 0L) System.currentTimeMillis() else ended.startedAtMs
                ).toString(),
                "clientId" to ended.clientId,
                "idempotencyKey" to ended.clientId,
                "deviceId" to deviceId(),
                "simSlot" to activeSimSlot(),
            )
        )
        // Hide overlay + offer after-call even if Flutter process is dead.
        try {
            val intent = android.content.Intent(
                context,
                iq.finora.finora_phone.overlay.CrmOverlayService::class.java
            ).apply {
                action = iq.finora.finora_phone.overlay.CrmOverlayService.ACTION_AFTER_CALL
                putExtra(
                    iq.finora.finora_phone.overlay.CrmOverlayService.EXTRA_NUMBER,
                    ended.number,
                )
            }
            context.startService(intent)
        } catch (_: Exception) {
            hideOverlay()
        }
    }

    private fun recoverNumberThenFinish(endType: String, ended: EndedCall) {
        handler.postDelayed({
            Thread {
                val recovered = readLastCallLogNumber(ended.startedAtMs)
                handler.post { finishCall(endType, ended.copy(number = recovered)) }
            }.start()
        }, CALL_LOG_RECOVERY_DELAY_MS)
    }

    private fun hasCallLogPermission(): Boolean {
        return try {
            context.checkCallingOrSelfPermission(Manifest.permission.READ_CALL_LOG) ==
                PackageManager.PERMISSION_GRANTED
        } catch (_: Exception) {
            false
        }
    }

    /** Last resort: the row the platform writes when the call ends. */
    private fun readLastCallLogNumber(callStartedAtMs: Long): String {
        if (!hasCallLogPermission()) return ""
        var cursor: android.database.Cursor? = null
        return try {
            val since = (if (callStartedAtMs == 0L) System.currentTimeMillis() else callStartedAtMs) -
                120_000L
            cursor = context.contentResolver.query(
                CallLog.Calls.CONTENT_URI,
                arrayOf(CallLog.Calls.NUMBER, CallLog.Calls.DATE),
                "${CallLog.Calls.DATE} >= ?",
                arrayOf(since.toString()),
                "${CallLog.Calls.DATE} DESC LIMIT 1",
            )
            if (cursor != null && cursor.moveToFirst()) {
                val idx = cursor.getColumnIndex(CallLog.Calls.NUMBER)
                if (idx >= 0) cursor.getString(idx).orEmpty() else ""
            } else {
                ""
            }
        } catch (_: Exception) {
            ""
        } finally {
            try {
                cursor?.close()
            } catch (_: Exception) {
            }
        }
    }

    /** Unlocks the in-call actions + duration timer on the overlay. */
    private fun notifyOverlayAnswered() {
        if (!globalOverlayGate.get()) return
        try {
            val intent = android.content.Intent(
                context,
                iq.finora.finora_phone.overlay.CrmOverlayService::class.java
            ).apply { action = iq.finora.finora_phone.overlay.CrmOverlayService.ACTION_ANSWERED }
            context.startService(intent)
        } catch (_: Exception) {
        }
    }

    private fun hideOverlay() {
        try {
            val intent = android.content.Intent(
                context,
                iq.finora.finora_phone.overlay.CrmOverlayService::class.java
            ).apply { action = iq.finora.finora_phone.overlay.CrmOverlayService.ACTION_HIDE }
            context.startService(intent)
        } catch (_: Exception) {
        }
    }

    private fun maybeShowOverlay(number: String) {
        if (!globalOverlayGate.compareAndSet(false, true)) {
            // Receiver already opened the shell — keep it in sync with the number.
            if (number.isNotEmpty()) pushNumberToOverlay(context, number)
            return
        }
        if (!overlayShown.compareAndSet(false, true)) return
        try {
            val intent = android.content.Intent(
                context,
                iq.finora.finora_phone.overlay.CrmOverlayService::class.java
            ).apply {
                action = iq.finora.finora_phone.overlay.CrmOverlayService.ACTION_SHOW
                putExtra(iq.finora.finora_phone.overlay.CrmOverlayService.EXTRA_NUMBER, number)
            }
            androidx.core.content.ContextCompat.startForegroundService(context, intent)
        } catch (_: Exception) {
            globalOverlayGate.set(false)
            overlayShown.set(false)
        }
    }

    private fun firstNonBlank(vararg values: String?): String {
        for (value in values) {
            val trimmed = value?.trim().orEmpty()
            if (trimmed.isNotEmpty()) return trimmed
        }
        return ""
    }

    private fun emit(type: String, number: String?, simSlot: Int?) {
        onEvent(
            mapOf(
                "type" to type,
                "number" to (number ?: ""),
                "direction" to direction,
                "startedAt" to java.time.Instant.ofEpochMilli(
                    if (startedAtMs == 0L) System.currentTimeMillis() else startedAtMs
                ).toString(),
                "clientId" to idempotencyKey,
                "idempotencyKey" to idempotencyKey,
                "deviceId" to deviceId(),
                "simSlot" to simSlot,
            )
        )
    }
}
