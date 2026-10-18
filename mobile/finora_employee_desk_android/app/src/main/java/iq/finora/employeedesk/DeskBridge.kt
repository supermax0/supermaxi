package iq.finora.employeedesk

import android.webkit.JavascriptInterface

class DeskBridge(private val activity: MainActivity) {
    @JavascriptInterface
    fun notify(title: String?, body: String?) {
        activity.runOnUiThread {
            DeskNotifier.show(activity, title.orEmpty(), body.orEmpty())
        }
    }

    @JavascriptInterface
    fun askMedia() {
        activity.runOnUiThread { activity.askMediaPermission() }
    }
}
