package iq.finora.finora_phone

import android.content.Intent
import android.os.Bundle
import android.view.WindowManager
import io.flutter.embedding.android.FlutterActivity
import io.flutter.embedding.engine.FlutterEngine
import iq.finora.finora_phone.bridge.FinoraPhonePlugin
import iq.finora.finora_phone.overlay.PendingLaunchAction

class MainActivity : FlutterActivity() {
    override fun configureFlutterEngine(flutterEngine: FlutterEngine) {
        super.configureFlutterEngine(flutterEngine)
        flutterEngine.plugins.add(FinoraPhonePlugin())
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        // Hide sensitive CRM from screenshots / recent apps by default.
        window.setFlags(
            WindowManager.LayoutParams.FLAG_SECURE,
            WindowManager.LayoutParams.FLAG_SECURE,
        )
        captureAction(intent)
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        captureAction(intent)
    }

    private fun captureAction(intent: Intent?) {
        val action = intent?.getStringExtra("finora_action")
        if (!action.isNullOrBlank()) {
            PendingLaunchAction.set(
                action,
                number = intent.getStringExtra("finora_number"),
                localCallUuid = intent.getStringExtra("finora_local_call_uuid"),
            )
        }
    }
}
