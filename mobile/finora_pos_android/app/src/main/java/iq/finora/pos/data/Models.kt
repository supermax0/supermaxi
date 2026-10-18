package iq.finora.pos.data

import com.google.gson.annotations.SerializedName

data class ProductColorRow(
    val name: String,
    val qty: Int = 0,
    val quantity: Int? = null
)

data class ProductRow(
    val id: Long,
    val name: String,
    @SerializedName("sale_price") val salePrice: Double,
    val quantity: Int,
    @SerializedName("image_url") val imageUrl: String? = "",
    @SerializedName("has_colors") val hasColors: Boolean = false,
    val colors: List<ProductColorRow> = emptyList(),
    @SerializedName("exchange_sale_price") val exchangeSalePrice: Double? = null,
    @SerializedName("has_exchange_sale") val hasExchangeSale: Boolean = false
)

data class AllProductsResponse(
    val success: Boolean,
    val products: List<ProductRow>?,
    val error: String?
)

data class SearchProductItem(
    val id: Long,
    val name: String,
    val price: Double,
    val quantity: Int,
    @SerializedName("image_url") val imageUrl: String? = "",
    @SerializedName("is_barcode") val isBarcode: Boolean = false,
    @SerializedName("has_colors") val hasColors: Boolean = false,
    val colors: List<ProductColorRow> = emptyList(),
    @SerializedName("exchange_sale_price") val exchangeSalePrice: Double? = null,
    @SerializedName("has_exchange_sale") val hasExchangeSale: Boolean = false
)

data class CustomerRow(
    val id: Long,
    val name: String,
    val phone: String,
    @SerializedName("phone2") val phone2: String? = "",
    val city: String? = "",
    val address: String? = "",
    val blacklisted: Boolean = false,
    @SerializedName("blacklist_message") val blacklistMessage: String? = ""
)

data class CreateOrderItem(
    @SerializedName("product_id") val productId: Long,
    val qty: Int,
    val price: Double?,
    val color: String? = null,
    @SerializedName("sale_mode") val saleMode: String = "normal"
)

data class CreateOrderRequest(
    @SerializedName("customer_id") val customerId: Long,
    val items: List<CreateOrderItem>,
    val note: String? = null,
    @SerializedName("page_id") val pageId: Long? = null,
    @SerializedName("scheduled_date") val scheduledDate: String? = null
)

data class CreateOrderResponse(
    val success: Boolean?,
    @SerializedName("invoice_id") val invoiceId: Long?,
    val total: Double?,
    val error: String?,
    val blacklisted: Boolean? = null,
    val available: Int? = null
)

data class AddCustomerRequest(
    val name: String,
    val phone: String,
    val phone2: String? = null,
    val city: String? = null,
    val address: String? = null
)

data class AddCustomerResponse(
    val status: String?,
    val id: Long?,
    val name: String?,
    val phone: String?,
    val msg: String?
)
