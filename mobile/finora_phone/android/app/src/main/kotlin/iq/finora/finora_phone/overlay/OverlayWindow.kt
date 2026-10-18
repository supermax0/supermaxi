package iq.finora.finora_phone.overlay

import android.content.Context
import android.graphics.Color
import android.graphics.drawable.GradientDrawable
import android.os.Handler
import android.os.Looper
import android.os.SystemClock
import android.util.TypedValue
import android.view.Gravity
import android.view.MotionEvent
import android.view.View
import android.view.ViewConfiguration
import android.widget.HorizontalScrollView
import android.widget.ImageButton
import android.widget.LinearLayout
import android.widget.ProgressBar
import android.widget.TextView
import kotlin.math.abs

/**
 * Draggable / minimizable CRM chrome.
 * Kept at TOP so it does not cover stock answer/decline buttons.
 * Quick actions stay safe: they only open Finora screens or side apps —
 * answering, rejecting and order confirmation never live here.
 */
class OverlayWindow(context: Context) : LinearLayout(context) {
    private val card: LinearLayout
    private val avatar: TextView
    private val title: TextView
    private val subtitle: TextView
    private val timer: TextView
    private val spinner: ProgressBar
    private val chipsRow: LinearLayout
    private val chipsScroller: HorizontalScrollView
    private val warning: TextView
    private val actions: LinearLayout
    private val minimizeBtn: ImageButton

    private var minimized = false
    private var inCall = false
    private var lastPhone = ""
    private var startY = 0f
    private var startX = 0f
    private var paramsY = 80
    private var dragging = false
    private var callStartedAt = 0L
    private val touchSlop = ViewConfiguration.get(context).scaledTouchSlop
    private val ticker = Handler(Looper.getMainLooper())
    private val tick = object : Runnable {
        override fun run() {
            renderTimer()
            ticker.postDelayed(this, 1000L)
        }
    }

    var onOpenCustomer: (() -> Unit)? = null
    var onQuickAction: ((String) -> Unit)? = null
    var onWhatsApp: ((String) -> Unit)? = null
    var onCopyNumber: ((String) -> Unit)? = null
    var onDismiss: (() -> Unit)? = null
    var onDragY: ((Int) -> Unit)? = null

    private companion object {
        const val GOLD = "#E7B84B"
        const val SURFACE = "#F0161A22"
        const val BORDER = "#59E7B84B"
        const val TEXT_MUTED = "#B3FFFFFF"
        const val DANGER = "#E5484D"
    }

    init {
        orientation = VERTICAL
        setPadding(dp(10), 0, dp(10), 0)

        avatar = TextView(context).apply {
            gravity = Gravity.CENTER
            setTextColor(Color.parseColor(GOLD))
            setTextSize(TypedValue.COMPLEX_UNIT_SP, 17f)
            paint.isFakeBoldText = true
            background = GradientDrawable().apply {
                shape = GradientDrawable.OVAL
                setColor(Color.parseColor("#26E7B84B"))
                setStroke(dp(1), Color.parseColor(BORDER))
            }
            text = "؟"
        }
        title = TextView(context).apply {
            setTextColor(Color.WHITE)
            setTextSize(TypedValue.COMPLEX_UNIT_SP, 16f)
            paint.isFakeBoldText = true
            maxLines = 1
            text = "Finora"
        }
        subtitle = TextView(context).apply {
            setTextColor(Color.parseColor(TEXT_MUTED))
            setTextSize(TypedValue.COMPLEX_UNIT_SP, 13f)
            maxLines = 1
        }
        timer = TextView(context).apply {
            setTextColor(Color.parseColor(GOLD))
            setTextSize(TypedValue.COMPLEX_UNIT_SP, 13f)
            paint.isFakeBoldText = true
            visibility = GONE
        }
        spinner = ProgressBar(context).apply { isIndeterminate = true }
        minimizeBtn = ImageButton(context).apply {
            setImageResource(android.R.drawable.arrow_up_float)
            setBackgroundColor(Color.TRANSPARENT)
            setColorFilter(Color.parseColor(TEXT_MUTED))
            contentDescription = "تصغير"
            setOnClickListener { toggleMinimize() }
        }
        val closeBtn = ImageButton(context).apply {
            setImageResource(android.R.drawable.ic_menu_close_clear_cancel)
            setBackgroundColor(Color.TRANSPARENT)
            setColorFilter(Color.parseColor(TEXT_MUTED))
            contentDescription = "إخفاء"
            setOnClickListener { onDismiss?.invoke() }
        }

        val texts = LinearLayout(context).apply {
            orientation = VERTICAL
            setPadding(dp(10), 0, dp(10), 0)
            addView(title)
            addView(subtitle)
        }
        val header = LinearLayout(context).apply {
            orientation = HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
            addView(avatar, LayoutParams(dp(42), dp(42)))
            addView(texts, LayoutParams(0, LayoutParams.WRAP_CONTENT, 1f))
            addView(timer)
            addView(spinner, LayoutParams(dp(18), dp(18)))
            addView(minimizeBtn, LayoutParams(dp(34), dp(34)))
            addView(closeBtn, LayoutParams(dp(34), dp(34)))
        }

        chipsRow = LinearLayout(context).apply { orientation = HORIZONTAL }
        chipsScroller = HorizontalScrollView(context).apply {
            isHorizontalScrollBarEnabled = false
            visibility = GONE
            addView(chipsRow)
        }

        warning = TextView(context).apply {
            setTextColor(Color.WHITE)
            setTextSize(TypedValue.COMPLEX_UNIT_SP, 12f)
            paint.isFakeBoldText = true
            setPadding(dp(10), dp(6), dp(10), dp(6))
            background = GradientDrawable().apply {
                cornerRadius = dp(10).toFloat()
                setColor(Color.parseColor("#33E5484D"))
                setStroke(dp(1), Color.parseColor(DANGER))
            }
            visibility = GONE
        }

        actions = LinearLayout(context).apply {
            orientation = HORIZONTAL
            visibility = GONE
            addView(actionPill("أدوات") { onQuickAction?.invoke("tools") })
            addView(actionPill("ملاحظة") { onQuickAction?.invoke("note") })
            addView(actionPill("مهمة") { onQuickAction?.invoke("task") })
            addView(actionPill("واتساب") { onWhatsApp?.invoke(lastPhone) })
        }

        card = LinearLayout(context).apply {
            orientation = VERTICAL
            setPadding(dp(12), dp(10), dp(12), dp(10))
            background = GradientDrawable().apply {
                cornerRadius = dp(18).toFloat()
                setColor(Color.parseColor(SURFACE))
                setStroke(dp(1), Color.parseColor(BORDER))
            }
            addView(header)
            addView(chipsScroller, spaced())
            addView(warning, spaced())
            addView(actions, spaced())
        }
        addView(card)

        isClickable = true
        isFocusable = true
        // Long press copies; a plain tap must still behave like the rest of the card.
        subtitle.setOnLongClickListener {
            onCopyNumber?.invoke(lastPhone)
            true
        }
        subtitle.setOnClickListener {
            if (minimized) toggleMinimize() else onOpenCustomer?.invoke()
        }
        setOnTouchListener { _, event -> handleDrag(event) }
    }

    private fun handleDrag(event: MotionEvent): Boolean {
        when (event.actionMasked) {
            MotionEvent.ACTION_DOWN -> {
                startY = event.rawY
                startX = event.rawX
                dragging = false
            }
            MotionEvent.ACTION_MOVE -> {
                val dy = event.rawY - startY
                val dx = event.rawX - startX
                if (!dragging && (abs(dy) > touchSlop || abs(dx) > touchSlop)) {
                    dragging = true
                }
                if (dragging) {
                    val maxY = (resources.displayMetrics.heightPixels * 0.28f).toInt()
                    paramsY = (paramsY + dy.toInt()).coerceIn(24, maxY)
                    startY = event.rawY
                    onDragY?.invoke(paramsY)
                }
            }
            MotionEvent.ACTION_UP, MotionEvent.ACTION_CANCEL -> {
                if (!dragging && event.actionMasked == MotionEvent.ACTION_UP) {
                    if (minimized) toggleMinimize() else onOpenCustomer?.invoke()
                }
                dragging = false
            }
            else -> return false
        }
        return true
    }

    private fun toggleMinimize() {
        minimized = !minimized
        minimizeBtn.setImageResource(
            if (minimized) android.R.drawable.arrow_down_float
            else android.R.drawable.arrow_up_float
        )
        applyVisibility()
    }

    /** Actions appear only after answering so the ringing UI stays minimal. */
    fun setInCall(active: Boolean) {
        if (inCall == active) return
        inCall = active
        if (active) {
            callStartedAt = SystemClock.elapsedRealtime()
            ticker.removeCallbacks(tick)
            ticker.post(tick)
        } else {
            ticker.removeCallbacks(tick)
        }
        applyVisibility()
    }

    /** Number can arrive after the shell is already on screen (API 31+). */
    fun setPhone(phone: String) {
        if (phone.isBlank()) return
        lastPhone = phone
        subtitle.text = phone
        applyVisibility()
    }

    fun updateCrm(data: Map<String, Any?>) {
        val name = data["name"]?.toString()
        val phone = data["phone"]?.toString().orEmpty()
        val isNew = asBool(data["isNew"])
        val minimal = asBool(data["minimal"])
        val resolved = !name.isNullOrBlank() && name != "…"
        val label = when {
            resolved -> name!!
            isNew -> "زبون جديد"
            else -> "جاري التحميل…"
        }
        title.text = label
        avatar.text = if (resolved) initial(label) else "؟"
        if (phone.isNotBlank()) lastPhone = phone
        subtitle.text = lastPhone
        spinner.visibility = if (resolved) GONE else VISIBLE

        val blacklisted = asBool(data["blacklisted"])
        warning.text = "زبون في القائمة السوداء — راجع الإدارة قبل أي طلب"
        warning.visibility = if (blacklisted && !minimal) VISIBLE else GONE

        if (minimal) {
            chipsRow.removeAllViews()
            applyVisibility()
            return
        }

        chipsRow.removeAllViews()
        money(data["balance"])?.let { addChip("رصيد: $it", false) }
        data["openOrders"]?.toString()?.takeIf { it.isNotBlank() && it != "0" }
            ?.let { addChip("طلبات مفتوحة: $it", false) }
        money(data["totalPurchases"])?.let { addChip("مشتريات: $it", false) }
        if (asBool(data["vip"])) addChip("VIP", false)
        if (blacklisted) addChip("قائمة سوداء", true)
        if (asBool(data["lockMinimal"])) chipsRow.removeAllViews()
        applyVisibility()
    }

    private fun applyVisibility() {
        val compact = minimized
        subtitle.visibility = if (compact || lastPhone.isBlank()) GONE else VISIBLE
        chipsScroller.visibility =
            if (!compact && chipsRow.childCount > 0) VISIBLE else GONE
        actions.visibility = if (!compact && inCall) VISIBLE else GONE
        if (compact) warning.visibility = GONE
        timer.visibility = if (inCall) VISIBLE else GONE
    }

    private fun renderTimer() {
        val seconds = ((SystemClock.elapsedRealtime() - callStartedAt) / 1000L)
            .coerceAtLeast(0L)
        timer.text = String.format("%02d:%02d", seconds / 60, seconds % 60)
    }

    private fun addChip(label: String, danger: Boolean) {
        val accent = if (danger) DANGER else GOLD
        val chip = TextView(context).apply {
            text = label
            setTextColor(Color.parseColor(accent))
            setTextSize(TypedValue.COMPLEX_UNIT_SP, 11f)
            setPadding(dp(10), dp(4), dp(10), dp(4))
            background = GradientDrawable().apply {
                cornerRadius = dp(999).toFloat()
                setColor(Color.parseColor(if (danger) "#26E5484D" else "#1FE7B84B"))
                setStroke(dp(1), Color.parseColor(if (danger) "#66E5484D" else BORDER))
            }
        }
        val lp = LayoutParams(LayoutParams.WRAP_CONTENT, LayoutParams.WRAP_CONTENT)
        lp.rightMargin = dp(6)
        chipsRow.addView(chip, lp)
    }

    private fun actionPill(label: String, onClick: () -> Unit): View {
        return TextView(context).apply {
            text = label
            gravity = Gravity.CENTER
            setTextColor(Color.parseColor(GOLD))
            setTextSize(TypedValue.COMPLEX_UNIT_SP, 12f)
            paint.isFakeBoldText = true
            setPadding(dp(10), dp(8), dp(10), dp(8))
            isClickable = true
            background = GradientDrawable().apply {
                cornerRadius = dp(12).toFloat()
                setColor(Color.parseColor("#1FE7B84B"))
                setStroke(dp(1), Color.parseColor(BORDER))
            }
            layoutParams = LayoutParams(0, LayoutParams.WRAP_CONTENT, 1f).apply {
                rightMargin = dp(6)
            }
            setOnClickListener { onClick() }
        }
    }

    private fun spaced(): LayoutParams {
        return LayoutParams(LayoutParams.MATCH_PARENT, LayoutParams.WRAP_CONTENT).apply {
            topMargin = dp(8)
        }
    }

    /** CRM values cross the intent boundary as strings ("1500.0"). */
    private fun money(value: Any?): String? {
        val raw = value?.toString()?.trim().orEmpty()
        if (raw.isEmpty() || raw == "null") return null
        val amount = raw.toDoubleOrNull() ?: return raw
        if (amount == 0.0) return null
        return String.format("%,d", amount.toLong())
    }

    private fun initial(value: String): String {
        val trimmed = value.trim()
        return if (trimmed.isEmpty()) "؟" else trimmed.substring(0, 1)
    }

    override fun onDetachedFromWindow() {
        ticker.removeCallbacks(tick)
        super.onDetachedFromWindow()
    }

    private fun asBool(value: Any?): Boolean {
        return when (value) {
            is Boolean -> value
            is Number -> value.toInt() != 0
            is String -> value.equals("true", true) || value == "1" || value.equals("yes", true)
            else -> false
        }
    }

    private fun dp(v: Int): Int =
        TypedValue.applyDimension(
            TypedValue.COMPLEX_UNIT_DIP,
            v.toFloat(),
            resources.displayMetrics,
        ).toInt()
}
