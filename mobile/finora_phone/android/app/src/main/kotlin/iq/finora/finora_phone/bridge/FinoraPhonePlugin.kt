package iq.finora.finora_phone.bridge

import android.Manifest
import android.app.Activity
import android.content.Intent
import android.content.pm.PackageManager
import android.database.Cursor
import android.net.Uri
import android.os.Build
import android.provider.CallLog
import android.provider.Settings
import android.telephony.SubscriptionManager
import androidx.core.app.ActivityCompat
import androidx.core.content.ContextCompat
import io.flutter.embedding.engine.plugins.FlutterPlugin
import io.flutter.embedding.engine.plugins.activity.ActivityAware
import io.flutter.embedding.engine.plugins.activity.ActivityPluginBinding
import io.flutter.plugin.common.EventChannel
import io.flutter.plugin.common.MethodCall
import io.flutter.plugin.common.MethodChannel
import io.flutter.plugin.common.PluginRegistry
import iq.finora.finora_phone.call.CallStateMonitor
import iq.finora.finora_phone.overlay.CrmOverlayService

/**
 * Bridges Flutter ↔ native companion overlay.
 * Phase 2 hook: swap CallStateMonitor for InCallService without changing channel names.
 */
class FinoraPhonePlugin : FlutterPlugin, MethodChannel.MethodCallHandler, ActivityAware,
    PluginRegistry.RequestPermissionsResultListener {
    private var methodChannel: MethodChannel? = null
    private var permissionsChannel: MethodChannel? = null
    private var eventChannel: EventChannel? = null
    private var activity: Activity? = null
    private var activityBinding: ActivityPluginBinding? = null
    private var appContext: android.content.Context? = null
    private var monitor: CallStateMonitor? = null
    private var eventSink: EventChannel.EventSink? = null
    private var pendingPermissionResult: MethodChannel.Result? = null
    private var pendingPermissionKeys: Array<String> = emptyArray()
    private var player: android.media.MediaPlayer? = null
    private var playerCompleted = false

    override fun onAttachedToEngine(binding: FlutterPlugin.FlutterPluginBinding) {
        appContext = binding.applicationContext
        methodChannel = MethodChannel(binding.binaryMessenger, "iq.finora.phone/overlay")
        methodChannel?.setMethodCallHandler(this)
        permissionsChannel = MethodChannel(binding.binaryMessenger, "iq.finora.phone/permissions")
        permissionsChannel?.setMethodCallHandler(this)
        eventChannel = EventChannel(binding.binaryMessenger, "iq.finora.phone/calls")
        eventChannel?.setStreamHandler(object : EventChannel.StreamHandler {
            override fun onListen(arguments: Any?, events: EventChannel.EventSink?) {
                eventSink = events
                startMonitor()
            }

            override fun onCancel(arguments: Any?) {
                eventSink = null
            }
        })
    }

    private fun startMonitor() {
        val ctx = appContext ?: return
        if (monitor != null) return
        monitor = CallStateMonitor(ctx) { payload ->
            android.os.Handler(ctx.mainLooper).post {
                eventSink?.success(payload)
            }
        }
        monitor?.start()
    }

    override fun onDetachedFromEngine(binding: FlutterPlugin.FlutterPluginBinding) {
        releasePlayer()
        monitor?.stop()
        monitor = null
        methodChannel?.setMethodCallHandler(null)
        permissionsChannel?.setMethodCallHandler(null)
        eventChannel?.setStreamHandler(null)
    }

    override fun onMethodCall(call: MethodCall, result: MethodChannel.Result) {
        val ctx = appContext
        if (ctx == null) {
            result.error("no_context", null, null)
            return
        }
        when (call.method) {
            "showShell" -> {
                val number = call.argument<String>("number") ?: ""
                val intent = Intent(ctx, CrmOverlayService::class.java).apply {
                    action = CrmOverlayService.ACTION_SHOW
                    putExtra(CrmOverlayService.EXTRA_NUMBER, number)
                }
                ContextCompat.startForegroundService(ctx, intent)
                result.success(true)
            }
            "updateCrm" -> {
                val args = call.arguments as? Map<*, *> ?: emptyMap<Any, Any>()
                val intent = Intent(ctx, CrmOverlayService::class.java).apply {
                    action = CrmOverlayService.ACTION_UPDATE
                    for ((k, v) in args) {
                        putExtra("crm_$k", v?.toString() ?: "")
                    }
                    putExtra(CrmOverlayService.EXTRA_CRM_KEYS, ArrayList(args.keys.map { it.toString() }))
                }
                ctx.startService(intent)
                result.success(true)
            }
            "hide" -> {
                val intent = Intent(ctx, CrmOverlayService::class.java).apply {
                    action = CrmOverlayService.ACTION_HIDE
                }
                ctx.startService(intent)
                result.success(true)
            }
            "expand" -> {
                val intent = Intent(ctx, CrmOverlayService::class.java).apply {
                    action = CrmOverlayService.ACTION_EXPAND
                }
                ctx.startService(intent)
                result.success(true)
            }
            "status" -> {
                result.success(
                    mapOf(
                        "phone" to hasPermission(Manifest.permission.READ_PHONE_STATE),
                        "callLog" to hasPermission(Manifest.permission.READ_CALL_LOG),
                        "overlay" to Settings.canDrawOverlays(ctx),
                        "notifications" to if (Build.VERSION.SDK_INT >= 33)
                            hasPermission(Manifest.permission.POST_NOTIFICATIONS) else true,
                        "mediaAudio" to hasMediaAudioPermission(),
                    )
                )
            }
            "requestPhone" -> {
                requestPermsAsync(
                    arrayOf(
                        Manifest.permission.READ_PHONE_STATE,
                        Manifest.permission.READ_PHONE_NUMBERS,
                    ),
                    result,
                )
            }
            "requestCallLog" -> {
                requestPermsAsync(arrayOf(Manifest.permission.READ_CALL_LOG), result)
            }
            "requestOverlay" -> {
                val act = activity
                if (act != null && !Settings.canDrawOverlays(ctx)) {
                    val intent = Intent(
                        Settings.ACTION_MANAGE_OVERLAY_PERMISSION,
                        Uri.parse("package:${ctx.packageName}")
                    )
                    act.startActivity(intent)
                }
                // Overlay grant happens in Settings — caller refreshes on resume.
                result.success(Settings.canDrawOverlays(ctx))
            }
            "requestNotifications" -> {
                if (Build.VERSION.SDK_INT >= 33) {
                    requestPermsAsync(arrayOf(Manifest.permission.POST_NOTIFICATIONS), result)
                } else {
                    result.success(true)
                }
            }
            "requestBatteryOptimization" -> {
                val act = activity
                if (act != null && Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
                    try {
                        val intent = Intent(Settings.ACTION_IGNORE_BATTERY_OPTIMIZATION_SETTINGS)
                        act.startActivity(intent)
                    } catch (_: Exception) {
                        try {
                            act.startActivity(Intent(Settings.ACTION_SETTINGS))
                        } catch (_: Exception) {
                        }
                    }
                }
                result.success(true)
            }
            "readRecentCallLog" -> {
                val hours = call.argument<Int>("hours") ?: 24
                result.success(readCallLog(hours))
            }
            "dialNumber" -> {
                val number = call.argument<String>("number") ?: ""
                val simSlot = call.argument<Int>("simSlot")
                result.success(dialNumber(number, simSlot))
            }
            "setBlockScreenshots" -> {
                val enabled = call.argument<Boolean>("enabled") ?: true
                val act = activity
                if (act != null) {
                    try {
                        if (enabled) {
                            act.window.addFlags(android.view.WindowManager.LayoutParams.FLAG_SECURE)
                        } else {
                            act.window.clearFlags(android.view.WindowManager.LayoutParams.FLAG_SECURE)
                        }
                    } catch (_: Exception) {
                    }
                }
                result.success(true)
            }
            "consumePendingAction" -> {
                val intentAction = activity?.intent?.getStringExtra("finora_action")
                val intentNumber = activity?.intent?.getStringExtra("finora_number")
                val intentUuid = activity?.intent?.getStringExtra("finora_local_call_uuid")
                if (!intentAction.isNullOrBlank()) {
                    activity?.intent?.removeExtra("finora_action")
                    activity?.intent?.removeExtra("finora_number")
                    activity?.intent?.removeExtra("finora_local_call_uuid")
                    iq.finora.finora_phone.overlay.PendingLaunchAction.clear()
                    result.success(
                        mapOf(
                            "action" to intentAction,
                            "number" to (intentNumber ?: ""),
                            "local_call_uuid" to intentUuid,
                        )
                    )
                } else {
                    result.success(iq.finora.finora_phone.overlay.PendingLaunchAction.consume())
                }
            }
            "deviceInfo" -> {
                result.success(deviceInfoMap())
            }
            "requestMediaAudio" -> {
                requestPermsAsync(mediaAudioPermissions(), result)
            }
            "findCallRecording" -> {
                val phone = call.argument<String>("phone") ?: ""
                val startedAtMs = call.argument<Number>("startedAtMs")?.toLong() ?: 0L
                val endedAtMs = call.argument<Number>("endedAtMs")?.toLong()
                    ?: System.currentTimeMillis()
                if (!hasMediaAudioPermission()) {
                    result.success(null)
                    return
                }
                Thread {
                    val found = try {
                        iq.finora.finora_phone.call.CallRecordingFinder.find(
                            ctx, phone, startedAtMs, endedAtMs
                        )
                    } catch (_: Exception) {
                        null
                    }
                    android.os.Handler(ctx.mainLooper).post { result.success(found) }
                }.start()
            }
            "deleteCachedRecording" -> {
                val path = call.argument<String>("path") ?: ""
                try {
                    val file = java.io.File(path)
                    if (file.exists() && file.path.contains("call_recordings")) {
                        file.delete()
                    }
                } catch (_: Exception) {
                }
                result.success(true)
            }
            "playerOpen" -> {
                val path = call.argument<String>("path") ?: ""
                result.success(openPlayer(path))
            }
            "playerPlay" -> {
                try {
                    player?.start()
                } catch (_: Exception) {
                }
                result.success(true)
            }
            "playerPause" -> {
                try {
                    if (player?.isPlaying == true) player?.pause()
                } catch (_: Exception) {
                }
                result.success(true)
            }
            "playerSeek" -> {
                val ms = call.argument<Number>("positionMs")?.toInt() ?: 0
                try {
                    player?.seekTo(ms)
                } catch (_: Exception) {
                }
                result.success(true)
            }
            "playerState" -> {
                result.success(playerState())
            }
            "playerStop" -> {
                releasePlayer()
                result.success(true)
            }
            else -> result.notImplemented()
        }
    }

    private fun deviceInfoMap(): Map<String, Any?> {
        val ctx = appContext ?: return emptyMap()
        var simSlots: Int? = null
        try {
            if (hasPermission(Manifest.permission.READ_PHONE_STATE) &&
                Build.VERSION.SDK_INT >= Build.VERSION_CODES.LOLLIPOP_MR1
            ) {
                val sm = ctx.getSystemService(SubscriptionManager::class.java)
                simSlots = sm?.activeSubscriptionInfoCount
            }
        } catch (_: Exception) {
        }
        return mapOf(
            "manufacturer" to Build.MANUFACTURER,
            "model" to Build.MODEL,
            "android_version" to Build.VERSION.RELEASE,
            "sim_slots_count" to simSlots,
            "device_name" to "${Build.MANUFACTURER} ${Build.MODEL}".trim(),
        )
    }

    private fun hasPermission(perm: String): Boolean {
        val ctx = appContext ?: return false
        return ContextCompat.checkSelfPermission(ctx, perm) == PackageManager.PERMISSION_GRANTED
    }

    /// Local playback for call recordings — avoids third-party audio plugins.
    private fun openPlayer(path: String): Map<String, Any?> {
        releasePlayer()
        if (path.isBlank() || !java.io.File(path).exists()) {
            return mapOf("ok" to false, "durationMs" to 0)
        }
        return try {
            val mp = android.media.MediaPlayer()
            mp.setAudioAttributes(
                android.media.AudioAttributes.Builder()
                    .setUsage(android.media.AudioAttributes.USAGE_MEDIA)
                    .setContentType(android.media.AudioAttributes.CONTENT_TYPE_SPEECH)
                    .build()
            )
            mp.setDataSource(path)
            mp.prepare()
            mp.setOnCompletionListener { playerCompleted = true }
            player = mp
            playerCompleted = false
            mapOf("ok" to true, "durationMs" to mp.duration)
        } catch (_: Exception) {
            releasePlayer()
            mapOf("ok" to false, "durationMs" to 0)
        }
    }

    private fun playerState(): Map<String, Any?> {
        val mp = player
        if (mp == null) {
            return mapOf(
                "positionMs" to 0,
                "durationMs" to 0,
                "playing" to false,
                "completed" to false,
            )
        }
        return try {
            mapOf(
                "positionMs" to mp.currentPosition,
                "durationMs" to mp.duration,
                "playing" to mp.isPlaying,
                "completed" to playerCompleted,
            )
        } catch (_: Exception) {
            mapOf(
                "positionMs" to 0,
                "durationMs" to 0,
                "playing" to false,
                "completed" to false,
            )
        }
    }

    private fun releasePlayer() {
        try {
            player?.stop()
        } catch (_: Exception) {
        }
        try {
            player?.release()
        } catch (_: Exception) {
        }
        player = null
        playerCompleted = false
    }

    private fun mediaAudioPermissions(): Array<String> =
        if (Build.VERSION.SDK_INT >= 33) {
            arrayOf(Manifest.permission.READ_MEDIA_AUDIO)
        } else {
            arrayOf(Manifest.permission.READ_EXTERNAL_STORAGE)
        }

    private fun hasMediaAudioPermission(): Boolean =
        mediaAudioPermissions().all { hasPermission(it) }

    private fun requestPermsAsync(perms: Array<String>, result: MethodChannel.Result) {
        val act = activity
        if (act == null) {
            result.success(perms.all { hasPermission(it) })
            return
        }
        val already = perms.all { hasPermission(it) }
        if (already) {
            result.success(true)
            return
        }
        if (pendingPermissionResult != null) {
            result.error("busy", "Another permission request is in progress", null)
            return
        }
        pendingPermissionResult = result
        pendingPermissionKeys = perms
        ActivityCompat.requestPermissions(act, perms, 9911)
    }

    override fun onRequestPermissionsResult(
        requestCode: Int,
        permissions: Array<out String>,
        grantResults: IntArray,
    ): Boolean {
        if (requestCode != 9911) return false
        val pending = pendingPermissionResult ?: return false
        pendingPermissionResult = null
        val granted = pendingPermissionKeys.isNotEmpty() &&
            pendingPermissionKeys.all { hasPermission(it) }
        pending.success(granted)
        pendingPermissionKeys = emptyArray()
        return true
    }

    private fun readCallLog(hours: Int): List<Map<String, Any?>> {
        val ctx = appContext ?: return emptyList()
        if (!hasPermission(Manifest.permission.READ_CALL_LOG)) return emptyList()
        val since = System.currentTimeMillis() - hours * 60L * 60L * 1000L
        val out = mutableListOf<Map<String, Any?>>()
        var cursor: Cursor? = null
        try {
            cursor = ctx.contentResolver.query(
                CallLog.Calls.CONTENT_URI,
                arrayOf(
                    CallLog.Calls.NUMBER,
                    CallLog.Calls.TYPE,
                    CallLog.Calls.DATE,
                    CallLog.Calls.DURATION,
                    CallLog.Calls.PHONE_ACCOUNT_ID,
                ),
                "${CallLog.Calls.DATE} >= ?",
                arrayOf(since.toString()),
                "${CallLog.Calls.DATE} DESC"
            )
            while (cursor != null && cursor.moveToNext() && out.size < 200) {
                val numberIdx = cursor.getColumnIndex(CallLog.Calls.NUMBER)
                val typeIdx = cursor.getColumnIndex(CallLog.Calls.TYPE)
                val dateIdx = cursor.getColumnIndex(CallLog.Calls.DATE)
                val durationIdx = cursor.getColumnIndex(CallLog.Calls.DURATION)
                val accountIdx = cursor.getColumnIndex(CallLog.Calls.PHONE_ACCOUNT_ID)
                val type = if (typeIdx >= 0) cursor.getInt(typeIdx) else 0
                val number = if (numberIdx >= 0) cursor.getString(numberIdx) ?: "" else ""
                val date = if (dateIdx >= 0) cursor.getLong(dateIdx) else 0L
                val duration = if (durationIdx >= 0) cursor.getLong(durationIdx) else 0L
                val accountId = if (accountIdx >= 0) cursor.getString(accountIdx) else null
                val typeLabel = when (type) {
                    CallLog.Calls.MISSED_TYPE -> "missed"
                    CallLog.Calls.OUTGOING_TYPE -> "outgoing"
                    CallLog.Calls.REJECTED_TYPE -> "rejected"
                    else -> "incoming"
                }
                out.add(
                    mapOf(
                        "number" to number,
                        "type" to typeLabel,
                        "date" to date,
                        "duration" to duration,
                        "startedAt" to java.time.Instant.ofEpochMilli(date).toString(),
                        "phoneAccountId" to accountId,
                        "simSlot" to resolveSimSlot(accountId),
                    )
                )
            }
        } catch (_: Exception) {
        } finally {
            cursor?.close()
        }
        return out
    }

    private fun dialNumber(number: String, simSlot: Int?): Boolean {
        val ctx = appContext ?: return false
        if (number.isBlank()) return false
        // Outgoing calls never carry the number in telephony callbacks.
        CallStateMonitor.publishNumber(ctx, number)
        try {
            if (simSlot != null &&
                Build.VERSION.SDK_INT >= Build.VERSION_CODES.M &&
                hasPermission(Manifest.permission.CALL_PHONE)
            ) {
                val sm = ctx.getSystemService(SubscriptionManager::class.java)
                val info = sm?.activeSubscriptionInfoList?.firstOrNull {
                    it.simSlotIndex == simSlot
                }
                if (info != null) {
                    val intent = Intent(Intent.ACTION_CALL, Uri.parse("tel:$number"))
                    intent.putExtra("android.telecom.extra.PHONE_ACCOUNT_HANDLE", info.subscriptionId)
                    intent.putExtra("com.android.phone.extra.slot", simSlot)
                    intent.putExtra("subscription", info.subscriptionId)
                    intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                    ctx.startActivity(intent)
                    return true
                }
            }
        } catch (_: Exception) {
        }
        return try {
            val intent = Intent(Intent.ACTION_DIAL, Uri.parse("tel:$number"))
            intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            ctx.startActivity(intent)
            true
        } catch (_: Exception) {
            false
        }
    }

    private fun resolveSimSlot(accountId: String?): Int? {
        if (accountId.isNullOrBlank()) return null
        val ctx = appContext ?: return null
        if (!hasPermission(Manifest.permission.READ_PHONE_STATE)) return null
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.LOLLIPOP_MR1) return null
        return try {
            val sm = ctx.getSystemService(SubscriptionManager::class.java) ?: return null
            val list = sm.activeSubscriptionInfoList ?: return null
            for (info in list) {
                if (info.subscriptionId.toString() == accountId) return info.simSlotIndex
                if (!info.iccId.isNullOrBlank() && info.iccId == accountId) return info.simSlotIndex
            }
            null
        } catch (_: Exception) {
            null
        }
    }

    override fun onAttachedToActivity(binding: ActivityPluginBinding) {
        activity = binding.activity
        activityBinding = binding
        binding.addRequestPermissionsResultListener(this)
        startMonitor()
    }

    override fun onDetachedFromActivityForConfigChanges() {
        activityBinding?.removeRequestPermissionsResultListener(this)
        activityBinding = null
        activity = null
    }

    override fun onReattachedToActivityForConfigChanges(binding: ActivityPluginBinding) {
        activity = binding.activity
        activityBinding = binding
        binding.addRequestPermissionsResultListener(this)
    }

    override fun onDetachedFromActivity() {
        activityBinding?.removeRequestPermissionsResultListener(this)
        activityBinding = null
        activity = null
    }
}
