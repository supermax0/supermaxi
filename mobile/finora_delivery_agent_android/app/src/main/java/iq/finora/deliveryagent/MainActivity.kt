package iq.finora.deliveryagent

import android.Manifest
import android.annotation.SuppressLint
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.Bitmap
import android.net.Uri
import android.os.Bundle
import android.view.View
import android.webkit.CookieManager
import android.webkit.GeolocationPermissions
import android.webkit.WebChromeClient
import android.webkit.WebResourceError
import android.webkit.WebResourceRequest
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.ProgressBar
import android.widget.TextView
import android.widget.Toast
import androidx.activity.OnBackPressedCallback
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat
import androidx.swiperefreshlayout.widget.SwipeRefreshLayout

class MainActivity : AppCompatActivity() {

    private lateinit var setupPanel: LinearLayout
    private lateinit var setupBaseUrl: EditText
    private lateinit var setupTenantSlug: EditText
    private lateinit var swipeRefresh: SwipeRefreshLayout
    private lateinit var webView: WebView
    private lateinit var errorPanel: LinearLayout
    private lateinit var progressBar: ProgressBar
    private var pendingGeoOrigin: String? = null
    private var pendingGeoCallback: GeolocationPermissions.Callback? = null

    private val locationPermissionLauncher =
        registerForActivityResult(ActivityResultContracts.RequestMultiplePermissions()) { grants ->
            val allowed = grants[Manifest.permission.ACCESS_FINE_LOCATION] == true ||
                grants[Manifest.permission.ACCESS_COARSE_LOCATION] == true
            pendingGeoCallback?.invoke(pendingGeoOrigin, allowed, false)
            pendingGeoOrigin = null
            pendingGeoCallback = null
        }

    @SuppressLint("SetJavaScriptEnabled")
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_root)

        setupPanel = findViewById(R.id.setupPanel)
        setupBaseUrl = findViewById(R.id.setupBaseUrl)
        setupTenantSlug = findViewById(R.id.setupTenantSlug)
        swipeRefresh = findViewById(R.id.swipeRefresh)
        webView = findViewById(R.id.webView)
        errorPanel = findViewById(R.id.errorPanel)
        progressBar = findViewById(R.id.progressBar)

        setupBaseUrl.setText(FinoraApp.getBaseUrl(this))

        findViewById<Button>(R.id.setupSaveBtn).setOnClickListener { saveSetupAndOpen() }
        findViewById<Button>(R.id.retryButton).setOnClickListener { loadPortal() }

        CookieManager.getInstance().setAcceptCookie(true)
        CookieManager.getInstance().setAcceptThirdPartyCookies(webView, true)

        webView.settings.apply {
            javaScriptEnabled = true
            domStorageEnabled = true
            databaseEnabled = true
            setGeolocationEnabled(true)
            loadWithOverviewMode = true
            useWideViewPort = true
            builtInZoomControls = false
            displayZoomControls = false
            setSupportZoom(false)
        }

        webView.webChromeClient = object : WebChromeClient() {
            override fun onProgressChanged(view: WebView?, newProgress: Int) {
                progressBar.progress = newProgress
                progressBar.visibility = if (newProgress in 1..99) View.VISIBLE else View.GONE
                if (newProgress >= 100) swipeRefresh.isRefreshing = false
            }

            override fun onGeolocationPermissionsShowPrompt(
                origin: String?,
                callback: GeolocationPermissions.Callback?
            ) {
                val originHost = origin?.let { Uri.parse(it).host }?.lowercase()
                val portalHost = Uri.parse(FinoraApp.getBaseUrl(this@MainActivity)).host?.lowercase()
                if (originHost == null || originHost != portalHost) {
                    callback?.invoke(origin, false, false)
                    return
                }
                if (hasLocationPermission()) {
                    callback?.invoke(origin, true, false)
                    return
                }
                pendingGeoOrigin = origin
                pendingGeoCallback = callback
                locationPermissionLauncher.launch(
                    arrayOf(
                        Manifest.permission.ACCESS_FINE_LOCATION,
                        Manifest.permission.ACCESS_COARSE_LOCATION,
                    )
                )
            }
        }

        webView.webViewClient = object : WebViewClient() {
            override fun shouldOverrideUrlLoading(
                view: WebView?,
                request: WebResourceRequest?
            ): Boolean {
                val uri = request?.url ?: return false
                return handleExternalUri(uri)
            }

            @Deprecated("Deprecated in Java")
            override fun shouldOverrideUrlLoading(view: WebView?, url: String?): Boolean {
                if (url.isNullOrBlank()) return false
                return handleExternalUri(Uri.parse(url))
            }

            override fun onPageStarted(view: WebView?, url: String?, favicon: Bitmap?) {
                errorPanel.visibility = View.GONE
                webView.visibility = View.VISIBLE
            }

            override fun onPageFinished(view: WebView?, url: String?) {
                swipeRefresh.isRefreshing = false
                CookieManager.getInstance().flush()
            }

            override fun onReceivedError(
                view: WebView?,
                request: WebResourceRequest?,
                error: WebResourceError?
            ) {
                val scheme = request?.url?.scheme?.lowercase()
                if (scheme != null && scheme !in setOf("http", "https")) {
                    return
                }
                if (request?.isForMainFrame == true) {
                    showError()
                }
            }
        }

        // Its direct child is a FrameLayout, which cannot report WebView/modal scroll.
        // Refresh is now an explicit action in the portal instead of a scroll gesture.
        swipeRefresh.isEnabled = false

        onBackPressedDispatcher.addCallback(this, object : OnBackPressedCallback(true) {
            override fun handleOnBackPressed() {
                if (setupPanel.visibility == View.VISIBLE) {
                    finish()
                    return
                }
                if (webView.canGoBack()) {
                    webView.goBack()
                } else {
                    isEnabled = false
                    onBackPressedDispatcher.onBackPressed()
                }
            }
        })

        if (handleIncomingUri(intent)) {
            return
        }

        if (FinoraApp.getTenantSlug(this) == null) {
            showSetup()
        } else if (savedInstanceState != null) {
            showWebContent()
            webView.restoreState(savedInstanceState)
        } else {
            showWebContent()
            loadPortal()
        }
    }

    private fun hasLocationPermission(): Boolean {
        val fine = ContextCompat.checkSelfPermission(this, Manifest.permission.ACCESS_FINE_LOCATION)
        val coarse = ContextCompat.checkSelfPermission(this, Manifest.permission.ACCESS_COARSE_LOCATION)
        return fine == PackageManager.PERMISSION_GRANTED || coarse == PackageManager.PERMISSION_GRANTED
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        handleIncomingUri(intent)
    }

    private fun handleIncomingUri(intent: Intent?): Boolean {
        val data = intent?.data ?: return false
        val parsed = FinoraApp.parsePortalLink(data.toString()) ?: return false
        FinoraApp.saveCompanyConfig(this, parsed.first, parsed.second)
        showWebContent()
        loadPortal()
        return true
    }

    private fun saveSetupAndOpen() {
        val base = setupBaseUrl.text.toString().trim().trimEnd('/')
        val tenant = setupTenantSlug.text.toString().trim().lowercase()
        if (!base.startsWith("http://") && !base.startsWith("https://")) {
            Toast.makeText(this, getString(R.string.setup_invalid_url), Toast.LENGTH_SHORT).show()
            return
        }
        if (!Regex("^[a-z0-9][a-z0-9_-]{0,62}$").matches(tenant)) {
            Toast.makeText(this, getString(R.string.setup_invalid_company), Toast.LENGTH_SHORT).show()
            return
        }
        FinoraApp.saveCompanyConfig(this, base, tenant)
        showWebContent()
        loadPortal()
    }

    private fun showSetup() {
        setupPanel.visibility = View.VISIBLE
        swipeRefresh.visibility = View.GONE
        if (FinoraApp.getTenantSlug(this) != null) {
            setupTenantSlug.setText(FinoraApp.getTenantSlug(this))
        }
    }

    private fun showWebContent() {
        setupPanel.visibility = View.GONE
        swipeRefresh.visibility = View.VISIBLE
    }

    private fun loadPortal() {
        val url = FinoraApp.portalLoginUrl(this)
        if (url == null) {
            showSetup()
            return
        }
        errorPanel.visibility = View.GONE
        webView.visibility = View.VISIBLE
        webView.loadUrl(url)
    }

    private fun handleExternalUri(uri: Uri): Boolean {
        val scheme = uri.scheme?.lowercase() ?: return false
        when (scheme) {
            "http", "https" -> {
                val host = uri.host?.lowercase().orEmpty()
                if (host.contains("maps.google.") || host == "maps.app.goo.gl" || host.endsWith(".goo.gl")) {
                    openExternal(uri)
                    return true
                }
                return false
            }
            "tel", "mailto", "sms", "smsto", "geo", "maps" -> {
                openExternal(uri)
                return true
            }
            else -> return false
        }
    }

    private fun openExternal(uri: Uri) {
        try {
            startActivity(Intent(Intent.ACTION_VIEW, uri))
        } catch (_: Exception) {
            Toast.makeText(this, R.string.error_open_external, Toast.LENGTH_SHORT).show()
        }
    }

    private fun showError() {
        webView.visibility = View.GONE
        errorPanel.visibility = View.VISIBLE
        findViewById<TextView>(R.id.errorText).text = getString(R.string.error_loading)
        swipeRefresh.isRefreshing = false
    }

    override fun onSaveInstanceState(outState: Bundle) {
        super.onSaveInstanceState(outState)
        if (::webView.isInitialized && setupPanel.visibility != View.VISIBLE) {
            webView.saveState(outState)
        }
    }
}
