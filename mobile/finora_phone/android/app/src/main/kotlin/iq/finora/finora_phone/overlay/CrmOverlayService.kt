package iq.finora.finora_phone.overlay

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.Service
import android.content.Intent
import android.graphics.PixelFormat
import android.os.Build
import android.os.IBinder
import android.provider.Settings
import android.view.Gravity
import android.view.WindowManager
import androidx.core.app.NotificationCompat

/**
 * Lightweight system overlay for CRM shell.
 * Answer/decline remain in the stock Phone app.
 * Positioned at TOP; draggable within upper ~28% of screen.
 */
class CrmOverlayService : Service() {
    companion object {
        const val ACTION_SHOW = "iq.finora.phone.overlay.SHOW"
        const val ACTION_UPDATE = "iq.finora.phone.overlay.UPDATE"
        const val ACTION_NUMBER = "iq.finora.phone.overlay.NUMBER"
        const val ACTION_ANSWERED = "iq.finora.phone.overlay.ANSWERED"
        const val ACTION_HIDE = "iq.finora.phone.overlay.HIDE"
        const val ACTION_EXPAND = "iq.finora.phone.overlay.EXPAND"
        const val ACTION_AFTER_CALL = "iq.finora.phone.overlay.AFTER_CALL"
        const val EXTRA_NUMBER = "number"
        const val EXTRA_CRM = "crm"
        const val EXTRA_CRM_KEYS = "crm_keys"
        private const val CHANNEL_ID = "finora_phone_overlay"
        private const val CHANNEL_AFTER = "finora_phone_after_call"
        private const val NOTIF_ID = 4401
        private const val AFTER_NOTIF_ID = 4402

        /** Never leave the shell spinning if Flutter never answers. */
        private const val CRM_TIMEOUT_MS = 4500L

        /** Survives service restarts so a dismissed call stays dismissed. */
        @Volatile
        private var dismissedNumber: String? = null
    }

    private var windowManager: WindowManager? = null
    private var overlayView: OverlayWindow? = null
    private var layoutParams: WindowManager.LayoutParams? = null
    private var shownForNumber: String? = null
    private var crmDelivered = false
    private val handler = android.os.Handler(android.os.Looper.getMainLooper())
    private val crmTimeout = Runnable { showLocalFallback() }

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onCreate() {
        super.onCreate()
        ensureChannel()
        startForeground(NOTIF_ID, buildNotification("Finora Phone", "جاهز لعرض معلومات المتصل"))
        windowManager = getSystemService(WINDOW_SERVICE) as WindowManager
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        when (intent?.action) {
            ACTION_SHOW -> {
                val number = intent.getStringExtra(EXTRA_NUMBER) ?: ""
                showShell(number)
            }
            ACTION_UPDATE -> {
                val keys = intent.getStringArrayListExtra(EXTRA_CRM_KEYS) ?: arrayListOf()
                val crm = mutableMapOf<String, Any?>()
                for (key in keys) {
                    crm[key] = intent.getStringExtra("crm_$key")
                }
                val name = crm["name"]?.toString().orEmpty()
                if (name.isNotBlank() && name != "…") {
                    crmDelivered = true
                    handler.removeCallbacks(crmTimeout)
                }
                val phone = crm["phone"]?.toString().orEmpty()
                if (phone.isNotBlank()) shownForNumber = phone
                overlayView?.updateCrm(crm)
            }
            ACTION_NUMBER -> {
                val number = intent.getStringExtra(EXTRA_NUMBER).orEmpty()
                if (number.isNotBlank()) {
                    shownForNumber = number
                    overlayView?.setPhone(number)
                    startForeground(NOTIF_ID, buildNotification("مكالمة", number))
                }
            }
            ACTION_ANSWERED -> overlayView?.setInCall(true)
            ACTION_HIDE -> {
                dismissedNumber = null
                hideOverlay()
            }
            ACTION_EXPAND -> openApp()
            ACTION_AFTER_CALL -> {
                val number = intent.getStringExtra(EXTRA_NUMBER)
                    .orEmpty()
                    .ifBlank { shownForNumber.orEmpty() }
                dismissedNumber = null
                hideOverlayKeepService = true
                hideOverlay()
                // Without a number there is nothing actionable to open.
                if (number.isNotBlank()) postAfterCallNotification(number)
                stopSelf()
            }
        }
        return START_STICKY
    }

    private var hideOverlayKeepService = false

    private fun openApp(action: String = "tools") {
        val number = shownForNumber ?: ""
        val launch = packageManager.getLaunchIntentForPackage(packageName)
        launch?.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_SINGLE_TOP or Intent.FLAG_ACTIVITY_CLEAR_TOP)
        launch?.putExtra("finora_action", action)
        launch?.putExtra("finora_number", number)
        if (launch != null) {
            PendingLaunchAction.set(action, number = number)
            startActivity(launch)
        }
    }

    private fun openWhatsApp(phone: String) {
        val target = phone.ifBlank { shownForNumber.orEmpty() }
        if (target.isBlank()) return
        try {
            val intent = Intent(Intent.ACTION_VIEW).apply {
                data = android.net.Uri.parse("https://wa.me/${waNumber(target)}")
                addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            }
            startActivity(intent)
        } catch (_: Exception) {
            toast("تعذّر فتح واتساب")
        }
    }

    /** wa.me needs an international number without symbols. */
    private fun waNumber(phone: String): String {
        val digits = phone.filter { it.isDigit() }
        return when {
            digits.startsWith("00") -> digits.removePrefix("00")
            digits.startsWith("0") -> "964" + digits.removePrefix("0")
            else -> digits
        }
    }

    private fun copyNumber(phone: String) {
        val target = phone.ifBlank { shownForNumber.orEmpty() }
        if (target.isBlank()) return
        try {
            val clipboard = getSystemService(android.content.ClipboardManager::class.java)
            clipboard?.setPrimaryClip(android.content.ClipData.newPlainText("رقم", target))
            toast("تم نسخ الرقم")
        } catch (_: Exception) {
        }
    }

    private fun toast(message: String) {
        try {
            android.widget.Toast.makeText(this, message, android.widget.Toast.LENGTH_SHORT).show()
        } catch (_: Exception) {
        }
    }

    private fun postAfterCallNotification(number: String) {
        try {
            ensureAfterChannel()
            PendingLaunchAction.set("after-call", number = number)
            val launch = packageManager.getLaunchIntentForPackage(packageName)
            launch?.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_SINGLE_TOP or Intent.FLAG_ACTIVITY_CLEAR_TOP)
            launch?.putExtra("finora_action", "after-call")
            launch?.putExtra("finora_number", number)
            val pi = android.app.PendingIntent.getActivity(
                this,
                42,
                launch,
                android.app.PendingIntent.FLAG_UPDATE_CURRENT or android.app.PendingIntent.FLAG_IMMUTABLE,
            )
            val notif = NotificationCompat.Builder(this, CHANNEL_AFTER)
                .setContentTitle("بعد المكالمة — Finora Phone")
                .setContentText(if (number.isBlank()) "افتح لإكمال الملاحظة أو المهمة" else number)
                .setSmallIcon(android.R.drawable.sym_call_incoming)
                .setContentIntent(pi)
                .setAutoCancel(true)
                .setPriority(NotificationCompat.PRIORITY_DEFAULT)
                .build()
            val mgr = getSystemService(NotificationManager::class.java)
            mgr.notify(AFTER_NOTIF_ID, notif)
        } catch (_: Exception) {
        }
    }

    private fun ensureAfterChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val mgr = getSystemService(NotificationManager::class.java)
            mgr.createNotificationChannel(
                NotificationChannel(
                    CHANNEL_AFTER,
                    "Finora Phone After Call",
                    NotificationManager.IMPORTANCE_DEFAULT,
                )
            )
        }
    }

    private fun showShell(number: String) {
        if (!Settings.canDrawOverlays(this)) {
            // Degrade — never block telephony.
            return
        }
        if (number.isNotBlank() && number == dismissedNumber) return
        if (overlayView != null) {
            // Same or new call — never stack overlays, just refresh the shell.
            if (number.isNotBlank() && number != shownForNumber) {
                shownForNumber = number
                overlayView?.setPhone(number)
            }
            armCrmTimeout()
            return
        }
        try {
            val view = OverlayWindow(this)
            view.onOpenCustomer = { openApp() }
            view.onQuickAction = { action -> openApp(action) }
            view.onWhatsApp = { phone -> openWhatsApp(phone) }
            view.onCopyNumber = { phone -> copyNumber(phone) }
            view.onDismiss = {
                dismissedNumber = shownForNumber
                hideOverlay()
            }
            view.onDragY = { y ->
                layoutParams?.y = y
                try {
                    windowManager?.updateViewLayout(view, layoutParams)
                } catch (_: Exception) {
                }
            }
            view.updateCrm(mapOf("phone" to number, "name" to "جاري التحميل…", "minimal" to "true"))
            val type = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O)
                WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY
            else
                @Suppress("DEPRECATION")
                WindowManager.LayoutParams.TYPE_PHONE

            val params = WindowManager.LayoutParams(
                WindowManager.LayoutParams.MATCH_PARENT,
                WindowManager.LayoutParams.WRAP_CONTENT,
                type,
                WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE or
                    WindowManager.LayoutParams.FLAG_LAYOUT_IN_SCREEN or
                    WindowManager.LayoutParams.FLAG_NOT_TOUCH_MODAL or
                    WindowManager.LayoutParams.FLAG_SHOW_WHEN_LOCKED,
                PixelFormat.TRANSLUCENT,
            )
            params.gravity = Gravity.TOP
            params.y = 72
            // Keep height small — never cover bottom answer buttons.
            windowManager?.addView(view, params)
            overlayView = view
            layoutParams = params
            shownForNumber = number
            armCrmTimeout()
            startForeground(
                NOTIF_ID,
                buildNotification("مكالمة واردة", number.ifBlank { "جارٍ تحديد الرقم" }),
            )
        } catch (_: Exception) {
        }
    }

    private fun armCrmTimeout() {
        crmDelivered = false
        handler.removeCallbacks(crmTimeout)
        handler.postDelayed(crmTimeout, CRM_TIMEOUT_MS)
    }

    /**
     * Flutter never answered (process killed / not logged in). Show whatever the
     * device itself knows instead of spinning forever.
     */
    private fun showLocalFallback() {
        if (crmDelivered) return
        val number = shownForNumber.orEmpty()
        val label = lookupContactName(number)
            ?: number.ifBlank { "رقم غير معروف" }
        overlayView?.updateCrm(mapOf("name" to label, "phone" to number))
    }

    private fun lookupContactName(number: String): String? {
        if (number.isBlank()) return null
        if (checkCallingOrSelfPermission(android.Manifest.permission.READ_CONTACTS) !=
            android.content.pm.PackageManager.PERMISSION_GRANTED
        ) {
            return null
        }
        var cursor: android.database.Cursor? = null
        return try {
            val uri = android.net.Uri.withAppendedPath(
                android.provider.ContactsContract.PhoneLookup.CONTENT_FILTER_URI,
                android.net.Uri.encode(number),
            )
            cursor = contentResolver.query(
                uri,
                arrayOf(android.provider.ContactsContract.PhoneLookup.DISPLAY_NAME),
                null,
                null,
                null,
            )
            if (cursor != null && cursor.moveToFirst()) {
                cursor.getString(0)?.takeIf { it.isNotBlank() }
            } else {
                null
            }
        } catch (_: Exception) {
            null
        } finally {
            try {
                cursor?.close()
            } catch (_: Exception) {
            }
        }
    }

    private fun hideOverlay() {
        handler.removeCallbacks(crmTimeout)
        crmDelivered = false
        try {
            overlayView?.let { windowManager?.removeView(it) }
        } catch (_: Exception) {
        }
        overlayView = null
        layoutParams = null
        shownForNumber = null
        iq.finora.finora_phone.call.CallStateMonitor.globalOverlayGate.set(false)
        if (!hideOverlayKeepService) {
            stopForeground(STOP_FOREGROUND_REMOVE)
            stopSelf()
        }
        hideOverlayKeepService = false
    }

    private fun ensureChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val mgr = getSystemService(NotificationManager::class.java)
            mgr.createNotificationChannel(
                NotificationChannel(
                    CHANNEL_ID,
                    "Finora Phone Overlay",
                    NotificationManager.IMPORTANCE_LOW,
                )
            )
        }
    }

    private fun buildNotification(title: String, text: String): Notification {
        return NotificationCompat.Builder(this, CHANNEL_ID)
            .setContentTitle(title)
            .setContentText(text)
            .setSmallIcon(android.R.drawable.sym_call_incoming)
            .setOngoing(true)
            .build()
    }

    override fun onDestroy() {
        hideOverlay()
        super.onDestroy()
    }
}
