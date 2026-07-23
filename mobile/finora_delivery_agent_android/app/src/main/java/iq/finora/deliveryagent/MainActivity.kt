package iq.finora.deliveryagent

import android.annotation.SuppressLint
import android.content.Intent
import android.graphics.Bitmap
import android.net.Uri
import android.os.Bundle
import android.view.View
import android.webkit.CookieManager
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
import androidx.appcompat.app.AppCompatActivity
import androidx.swiperefreshlayout.widget.SwipeRefreshLayout

class MainActivity : AppCompatActivity() {

    private lateinit var setupPanel: LinearLayout
    private lateinit var setupBaseUrl: EditText
    private lateinit var setupTenantSlug: EditText
    private lateinit var swipeRefresh: SwipeRefreshLayout
    private lateinit var webView: WebView
    private lateinit var errorPanel: LinearLayout
    private lateinit var progressBar: ProgressBar

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
            loadWithOverviewMode = true
            useWideViewPort = true
            builtInZoomControls = false
            displayZoomControls = false
            setSupportZoom(false)
        }

        webView.webChromeClient = object : WebChromeClient() {
            override fun onProgressChanged(view: WebView?, newProgress: Int) {
                progressBar.visibility = if (newProgress in 1..99) View.VISIBLE else View.GONE
                if (newProgress >= 100) swipeRefresh.isRefreshing = false
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
                // tel/mailto/sms are not web pages — do not show portal load error
                if (scheme != null && scheme !in setOf("http", "https")) {
                    return
                }
                if (request?.isForMainFrame == true) {
                    showError()
                }
            }
        }

        swipeRefresh.setOnRefreshListener { webView.reload() }
        swipeRefresh.setColorSchemeResources(R.color.finora_blue)

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
        if (base.isEmpty() || tenant.isEmpty()) {
            Toast.makeText(this, getString(R.string.setup_missing), Toast.LENGTH_SHORT).show()
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
            "http", "https" -> return false
            "tel", "mailto", "sms", "smsto", "geo" -> {
                try {
                    startActivity(Intent(Intent.ACTION_VIEW, uri))
                } catch (_: Exception) {
                    Toast.makeText(this, R.string.error_open_external, Toast.LENGTH_SHORT).show()
                }
                return true
            }
            else -> {
                // Keep portal navigation inside the WebView for unknown app schemes
                // unless they are clearly external actions.
                return false
            }
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
