package iq.finora.pos.data

import android.content.SharedPreferences
import com.google.gson.Gson
import com.google.gson.JsonParser
import iq.finora.pos.FinoraApp
import okhttp3.FormBody
import okhttp3.HttpUrl.Companion.toHttpUrlOrNull
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody

class PosRepository(
    private val prefs: SharedPreferences,
    private val client: OkHttpClient,
    private val gson: Gson = Gson()
) {

    fun getBaseUrl(): String? = FinoraApp.FIXED_BASE_URL

    fun setBaseUrl(@Suppress("UNUSED_PARAMETER") url: String) {
        // intentionally ignored: server URL is fixed for this app build
    }

    private fun clearStoredSession() {
        prefs.edit().remove(FinoraApp.KEY_SESSION_COOKIE_PAIR).apply()
    }

    fun logout() {
        val base = getBaseUrl() ?: return
        try {
            val req = Request.Builder().url("$base/logout").get().build()
            client.newCall(req).execute().close()
        } catch (_: Exception) {
        }
        clearStoredSession()
    }

    /** true إذا الجلسة لا تزال صالحة لـ POS */
    fun probeSession(): Boolean {
        val base = getBaseUrl() ?: return false
        return try {
            val req = Request.Builder().url("$base/pos/all-products").get().build()
            client.newCall(req).execute().use { resp ->
                if (!resp.isSuccessful) return false
                val body = resp.body?.string() ?: return false
                body.contains("\"success\"") && body.contains("\"products\"")
            }
        } catch (_: Exception) {
            false
        }
    }

    fun login(tenantSlug: String, username: String, password: String): Result<Unit> {
        val base = getBaseUrl() ?: return Result.failure(IllegalStateException("لم يُضبط عنوان الخادم"))
        clearStoredSession()
        val form = FormBody.Builder()
            .add("tenant_slug", tenantSlug.trim().lowercase())
            .add("username", username.trim())
            .add("password", password)
            .build()
        val req = Request.Builder()
            .url("$base/login")
            .post(form)
            .header("Accept", "text/html,application/json;q=0.9,*/*;q=0.8")
            .header("Origin", base)
            .header("Referer", "$base/login")
            .build()
        return try {
            var forbidden = false
            client.newCall(req).execute().use { resp ->
                if (resp.code == 403) {
                    forbidden = true
                    return@use
                }
                try {
                    resp.body?.string()
                } catch (_: Exception) {
                }
            }
            if (forbidden) {
                Result.failure(Exception("مرفوض"))
            } else if (probeSession()) {
                Result.success(Unit)
            } else {
                Result.failure(
                    Exception(
                        "تعذر إثبات الجلسة بعد الدخول. تحقق من: معرف الشركة، اسم المستخدم، كلمة المرور، " +
                            "وأن عنوان الخادم مطابق للمتصفح (مثلاً مع www أو بدون)."
                    )
                )
            }
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    fun loadAllProducts(): Result<List<ProductRow>> {
        val base = getBaseUrl() ?: return Result.failure(IllegalStateException("لا يوجد خادم"))
        val req = Request.Builder().url("$base/pos/all-products").get().build()
        return executeJson(req) { body ->
            val parsed = gson.fromJson(body, AllProductsResponse::class.java)
            if (parsed.success == true && parsed.products != null) {
                Result.success(parsed.products)
            } else {
                Result.failure(Exception(parsed.error ?: "غير مصرح أو خطأ في البيانات"))
            }
        }
    }

    fun searchProducts(q: String): Result<List<SearchProductItem>> {
        val base = getBaseUrl() ?: return Result.failure(IllegalStateException("لا يوجد خادم"))
        val url = "$base/pos/search-product".toHttpUrlOrNull()!!.newBuilder()
            .addQueryParameter("q", q)
            .build()
        val req = Request.Builder().url(url).get().build()
        return executeJson(req) { body ->
            val arr = JsonParser.parseString(body).asJsonArray
            val list = mutableListOf<SearchProductItem>()
            for (el in arr) {
                list.add(gson.fromJson(el, SearchProductItem::class.java))
            }
            Result.success(list)
        }
    }

    fun searchCustomers(q: String): Result<List<CustomerRow>> {
        val base = getBaseUrl() ?: return Result.failure(IllegalStateException("لا يوجد خادم"))
        val url = "$base/pos/search-customer".toHttpUrlOrNull()!!.newBuilder()
            .addQueryParameter("q", q)
            .build()
        val req = Request.Builder().url(url).get().build()
        return executeJson(req) { body ->
            val arr = JsonParser.parseString(body).asJsonArray
            val list = mutableListOf<CustomerRow>()
            for (el in arr) {
                list.add(gson.fromJson(el, CustomerRow::class.java))
            }
            Result.success(list)
        }
    }

    fun createOrder(
        customerId: Long,
        items: List<CreateOrderItem>,
        note: String?,
        scheduledDate: String?
    ): Result<CreateOrderResponse> {
        val base = getBaseUrl() ?: return Result.failure(IllegalStateException("لا يوجد خادم"))
        val payload = CreateOrderRequest(
            customerId = customerId,
            items = items,
            note = note?.takeIf { it.isNotBlank() },
            pageId = null,
            scheduledDate = scheduledDate?.takeIf { it.isNotBlank() }
        )
        val json = gson.toJson(payload)
        val body = json.toRequestBody(JSON)
        val req = Request.Builder()
            .url("$base/pos/create-order")
            .post(body)
            .header("Content-Type", "application/json; charset=utf-8")
            .build()
        return try {
            client.newCall(req).execute().use { resp ->
                val responseBody = resp.body?.string().orEmpty()
                val parsed = try {
                    gson.fromJson(responseBody, CreateOrderResponse::class.java)
                } catch (_: Exception) {
                    null
                }
                if (resp.isSuccessful && parsed?.success == true) {
                    return Result.success(parsed)
                }
                val err = parsed?.error
                    ?: extractJsonError(responseBody)
                    ?: "HTTP ${resp.code}"
                Result.failure(Exception(err))
            }
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    fun addCustomer(
        name: String,
        phone: String,
        phone2: String?,
        city: String?,
        address: String?
    ): Result<CustomerRow> {
        val base = getBaseUrl() ?: return Result.failure(IllegalStateException("لا يوجد خادم"))
        val payload = AddCustomerRequest(
            name = name.trim(),
            phone = phone.trim(),
            phone2 = phone2?.trim()?.takeIf { it.isNotEmpty() },
            city = city?.trim()?.takeIf { it.isNotEmpty() },
            address = address?.trim()?.takeIf { it.isNotEmpty() }
        )
        val req = Request.Builder()
            .url("$base/pos/add-customer")
            .post(gson.toJson(payload).toRequestBody(JSON))
            .header("Content-Type", "application/json; charset=utf-8")
            .build()

        return try {
            client.newCall(req).execute().use { resp ->
                val body = resp.body?.string().orEmpty()
                val parsed = try { gson.fromJson(body, AddCustomerResponse::class.java) } catch (_: Exception) { null }
                if (!resp.isSuccessful || parsed?.status != "success" || parsed.id == null) {
                    val msg = parsed?.msg ?: extractJsonError(body) ?: "فشل إضافة الزبون"
                    return Result.failure(Exception(msg))
                }
                Result.success(
                    CustomerRow(
                        id = parsed.id,
                        name = parsed.name ?: name,
                        phone = parsed.phone ?: phone,
                        phone2 = phone2.orEmpty(),
                        city = city.orEmpty(),
                        address = address.orEmpty(),
                        blacklisted = false,
                        blacklistMessage = ""
                    )
                )
            }
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    private fun extractJsonError(body: String): String? {
        return try {
            val o = JsonParser.parseString(body).asJsonObject
            when {
                o.has("error") -> o.get("error")?.asString
                o.has("msg") -> o.get("msg")?.asString
                else -> null
            }
        } catch (_: Exception) {
            null
        }
    }

    private fun <T> executeJson(req: Request, parse: (String) -> Result<T>): Result<T> {
        return try {
            client.newCall(req).execute().use { resp ->
                val body = resp.body?.string().orEmpty()
                if (!resp.isSuccessful) {
                    val err = try {
                        gson.fromJson(body, CreateOrderResponse::class.java)?.error
                    } catch (_: Exception) {
                        null
                    }
                    return Result.failure(Exception(err ?: "HTTP ${resp.code}"))
                }
                parse(body)
            }
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    companion object {
        private val JSON = "application/json; charset=utf-8".toMediaType()

        fun from(app: FinoraApp): PosRepository {
            val prefs = app.getSharedPreferences(FinoraApp.PREFS_NAME, android.content.Context.MODE_PRIVATE)
            return PosRepository(prefs, app.httpClient)
        }
    }
}
