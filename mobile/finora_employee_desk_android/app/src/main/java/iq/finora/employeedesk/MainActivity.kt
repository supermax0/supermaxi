package iq.finora.employeedesk

import android.Manifest
import android.annotation.SuppressLint
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.Bitmap
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.view.View
import android.webkit.CookieManager
import android.webkit.ValueCallback
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

    private var fileCallback: ValueCallback<Array<Uri>>? = null

    private val notifyPermission = registerForActivityResult(
        ActivityResultContracts.RequestPermission()
    ) { askMediaPermission() }

    private var pendingFileIntent: Intent? = null

    private val mediaPermission = registerForActivityResult(
        ActivityResultContracts.RequestMultiplePermissions()
    ) {
        val intent = pendingFileIntent
        pendingFileIntent = null
        if (intent == null) return@registerForActivityResult
        try {
            filePicker.launch(intent)
        } catch (_: Exception) {
            fileCallback?.onReceiveValue(null)
            fileCallback = null
        }
    }

    private val filePicker = registerForActivityResult(
        ActivityResultContracts.StartActivityForResult()
    ) { result ->
        val uris = WebChromeClient.FileChooserParams.parseResult(result.resultCode, result.data)
        fileCallback?.onReceiveValue(uris)
        fileCallback = null
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
        findViewById<Button>(R.id.retryButton).setOnClickListener { loadDesk() }

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
            allowFileAccess = true
            allowContentAccess = true
            mediaPlaybackRequiresUserGesture = false
        }
        webView.addJavascriptInterface(DeskBridge(this), "FinoraDesk")
        webView.webChromeClient = object : WebChromeClient() {
            override fun onProgressChanged(view: WebView?, newProgress: Int) {
                progressBar.visibility = if (newProgress in 1..99) View.VISIBLE else View.GONE
                if (newProgress >= 100) swipeRefresh.isRefreshing = false
            }

            override fun onShowFileChooser(
                webView: WebView?,
                filePathCallback: ValueCallback<Array<Uri>>?,
                fileChooserParams: FileChooserParams?
            ): Boolean {
                fileCallback?.onReceiveValue(null)
                fileCallback = filePathCallback
                val intent = fileChooserParams?.createIntent() ?: Intent(Intent.ACTION_GET_CONTENT).apply {
                    addCategory(Intent.CATEGORY_OPENABLE)
                    type = "*/*"
                    putExtra(Intent.EXTRA_MIME_TYPES, arrayOf("image/*", "video/*", "audio/*", "application/pdf"))
                }
                val missing = missingMediaPermissions()
                if (missing.isNotEmpty()) {
                    pendingFileIntent = intent
                    mediaPermission.launch(missing)
                    return true
                }
                return try {
                    filePicker.launch(intent)
                    true
                } catch (_: Exception) {
                    fileCallback = null
                    false
                }
            }
        }
        webView.webViewClient = object : WebViewClient() {
            override fun shouldOverrideUrlLoading(view: WebView?, request: WebResourceRequest?): Boolean {
                val uri = request?.url ?: return false
                return handleExternalUri(uri)
            }

            override fun onPageStarted(view: WebView?, url: String?, favicon: Bitmap?) {
                errorPanel.visibility = View.GONE
                webView.visibility = View.VISIBLE
            }

            override fun onPageFinished(view: WebView?, url: String?) {
                swipeRefresh.isRefreshing = false
                CookieManager.getInstance().flush()
            }

            override fun onReceivedError(view: WebView?, request: WebResourceRequest?, error: WebResourceError?) {
                val scheme = request?.url?.scheme?.lowercase()
                if (scheme != null && scheme !in setOf("http", "https")) return
                if (request?.isForMainFrame == true) showError()
            }
        }

        swipeRefresh.isEnabled = false
        askNotifyPermission()

        onBackPressedDispatcher.addCallback(this, object : OnBackPressedCallback(true) {
            override fun handleOnBackPressed() {
                if (setupPanel.visibility == View.VISIBLE) {
                    finish()
                    return
                }
                if (webView.canGoBack()) webView.goBack()
                else {
                    isEnabled = false
                    onBackPressedDispatcher.onBackPressed()
                }
            }
        })

        if (handleIncomingUri(intent)) return
        if (FinoraApp.getTenantSlug(this) == null) {
            showSetup()
        } else if (savedInstanceState != null) {
            showWebContent()
            webView.restoreState(savedInstanceState)
        } else {
            showWebContent()
            loadDesk()
        }
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        handleIncomingUri(intent)
    }

    private fun missingMediaPermissions(): Array<String> {
        val needed = if (Build.VERSION.SDK_INT >= 33) {
            arrayOf(Manifest.permission.READ_MEDIA_IMAGES, Manifest.permission.READ_MEDIA_VIDEO)
        } else {
            arrayOf(Manifest.permission.READ_EXTERNAL_STORAGE)
        }
        return needed.filter {
            ContextCompat.checkSelfPermission(this, it) != PackageManager.PERMISSION_GRANTED
        }.toTypedArray()
    }

    fun askMediaPermission() {
        val missing = missingMediaPermissions()
        if (missing.isNotEmpty()) mediaPermission.launch(missing)
    }

    private fun askNotifyPermission() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.TIRAMISU) {
            askMediaPermission()
            return
        }
        if (ContextCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS)
            == PackageManager.PERMISSION_GRANTED
        ) {
            askMediaPermission()
            return
        }
        notifyPermission.launch(Manifest.permission.POST_NOTIFICATIONS)
    }

    private fun handleIncomingUri(intent: Intent?): Boolean {
        val data = intent?.data ?: return false
        val parsed = FinoraApp.parseDeskLink(data.toString()) ?: return false
        FinoraApp.saveCompanyConfig(this, parsed.first, parsed.second)
        showWebContent()
        loadDesk()
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
        loadDesk()
    }

    private fun showSetup() {
        setupPanel.visibility = View.VISIBLE
        swipeRefresh.visibility = View.GONE
        FinoraApp.getTenantSlug(this)?.let { setupTenantSlug.setText(it) }
    }

    private fun showWebContent() {
        setupPanel.visibility = View.GONE
        swipeRefresh.visibility = View.VISIBLE
    }

    private fun loadDesk() {
        val url = FinoraApp.deskStartUrl(this)
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
        return when (scheme) {
            "http", "https" -> false
            "tel", "mailto", "sms", "smsto" -> {
                try {
                    startActivity(Intent(Intent.ACTION_VIEW, uri))
                } catch (_: Exception) {
                    Toast.makeText(this, R.string.error_open_external, Toast.LENGTH_SHORT).show()
                }
                true
            }
            else -> false
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
