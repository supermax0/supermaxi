package iq.finora.pos.ui

import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.viewModelScope
import iq.finora.pos.data.CreateOrderItem
import iq.finora.pos.data.CustomerRow
import iq.finora.pos.data.PosRepository
import iq.finora.pos.data.ProductRow
import iq.finora.pos.data.SearchProductItem
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.FlowPreview
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.debounce
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.flow.filter
import kotlinx.coroutines.flow.launchIn
import kotlinx.coroutines.flow.onEach
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

data class CartLine(
    val lineKey: String,
    val productId: Long,
    val name: String,
    val unitPrice: Double,
    var qty: Int,
    val maxStock: Int,
    val imageUrl: String? = "",
    val color: String = "",
    val saleMode: String = "normal"
)

@OptIn(FlowPreview::class)
class PosViewModel(private val repository: PosRepository) : ViewModel() {

    private val _loading = MutableStateFlow(false)
    val loading: StateFlow<Boolean> = _loading.asStateFlow()

    private val _message = MutableStateFlow<String?>(null)
    val message: StateFlow<String?> = _message.asStateFlow()

    private val _products = MutableStateFlow<List<ProductRow>>(emptyList())
    val products: StateFlow<List<ProductRow>> = _products.asStateFlow()

    private val _customerQuery = MutableStateFlow("")
    val customerQuery: StateFlow<String> = _customerQuery.asStateFlow()

    private val _customers = MutableStateFlow<List<CustomerRow>>(emptyList())
    val customers: StateFlow<List<CustomerRow>> = _customers.asStateFlow()

    private val _selectedCustomer = MutableStateFlow<CustomerRow?>(null)
    val selectedCustomer: StateFlow<CustomerRow?> = _selectedCustomer.asStateFlow()

    private val _productQuery = MutableStateFlow("")
    val productQuery: StateFlow<String> = _productQuery.asStateFlow()

    private val _searchHits = MutableStateFlow<List<SearchProductItem>>(emptyList())
    val searchHits: StateFlow<List<SearchProductItem>> = _searchHits.asStateFlow()

    private val _cart = MutableStateFlow<List<CartLine>>(emptyList())
    val cart: StateFlow<List<CartLine>> = _cart.asStateFlow()

    private val _note = MutableStateFlow("")
    val note: StateFlow<String> = _note.asStateFlow()

    private val _scheduledDate = MutableStateFlow("")
    val scheduledDate: StateFlow<String> = _scheduledDate.asStateFlow()

    init {
        _customerQuery
            .debounce(350)
            .distinctUntilChanged()
            .filter { it.length >= 2 }
            .onEach { q ->
                val r = withContext(Dispatchers.IO) { repository.searchCustomers(q) }
                if (r.isSuccess) _customers.value = r.getOrDefault(emptyList())
                else _customers.value = emptyList()
            }
            .launchIn(viewModelScope)

        _productQuery
            .debounce(300)
            .distinctUntilChanged()
            .filter { it.isNotEmpty() }
            .onEach { q ->
                val local = localProductSearch(q)
                if (local.isNotEmpty()) {
                    _searchHits.value = local
                } else {
                    val r = withContext(Dispatchers.IO) { repository.searchProducts(q) }
                    if (r.isSuccess) _searchHits.value = r.getOrDefault(emptyList())
                    else _searchHits.value = emptyList()
                }
            }
            .launchIn(viewModelScope)
    }

    private fun normalizeText(s: String): String {
        return s
            .lowercase()
            .replace("أ", "ا")
            .replace("إ", "ا")
            .replace("آ", "ا")
            .replace("ى", "ي")
            .replace("ة", "ه")
            .trim()
    }

    private fun localProductSearch(query: String): List<SearchProductItem> {
        val nq = normalizeText(query)
        if (nq.isBlank()) return emptyList()
        return _products.value
            .filter { normalizeText(it.name).contains(nq) }
            .take(20)
            .map {
                SearchProductItem(
                    id = it.id,
                    name = it.name,
                    price = it.salePrice,
                    quantity = it.quantity,
                    imageUrl = it.imageUrl,
                    isBarcode = false,
                    hasColors = it.hasColors,
                    colors = it.colors,
                    exchangeSalePrice = it.exchangeSalePrice,
                    hasExchangeSale = it.hasExchangeSale
                )
            }
    }

    fun refreshCatalog() {
        viewModelScope.launch {
            _loading.value = true
            _message.value = null
            val r = withContext(Dispatchers.IO) { repository.loadAllProducts() }
            _loading.value = false
            if (r.isSuccess) {
                _products.value = r.getOrDefault(emptyList())
            } else {
                _message.value = r.exceptionOrNull()?.message ?: "تعذر تحميل المنتجات"
            }
        }
    }

    fun setCustomerQuery(s: String) {
        _customerQuery.value = s
        if (s.length < 2) _customers.value = emptyList()
    }

    fun selectCustomer(c: CustomerRow) {
        if (c.blacklisted) {
            _message.value = c.blacklistMessage ?: "زبون في القائمة السوداء"
            return
        }
        _selectedCustomer.value = c
        _customerQuery.value = ""
        _customers.value = emptyList()
    }

    fun clearCustomer() {
        _selectedCustomer.value = null
    }

    fun setProductQuery(s: String) {
        _productQuery.value = s
        if (s.isBlank()) _searchHits.value = emptyList()
    }

    fun addProductFromCatalog(p: ProductRow) {
        addConfiguredProduct(p, "", "normal")
        _message.value = null
    }

    fun addProductFromSearch(p: SearchProductItem) {
        addConfiguredProduct(
            ProductRow(
                p.id, p.name, p.price, p.quantity, p.imageUrl,
                p.hasColors, p.colors, p.exchangeSalePrice, p.hasExchangeSale
            ),
            "",
            "normal"
        )
        _searchHits.value = emptyList()
        _productQuery.value = ""
    }

    fun addConfiguredProduct(
        product: ProductRow,
        color: String,
        saleMode: String
    ) {
        if (product.hasColors && color.isBlank()) {
            _message.value = "يجب اختيار لون للمنتج"
            return
        }
        if (saleMode == "exchange" && !product.hasExchangeSale) {
            _message.value = "ميزة الاستبدال غير متاحة لهذا المنتج"
            return
        }
        val selectedPrice = if (saleMode == "exchange") {
            product.exchangeSalePrice ?: product.salePrice
        } else product.salePrice
        val stock = if (color.isNotBlank()) {
            product.colors.firstOrNull { it.name == color }?.let { it.quantity ?: it.qty } ?: 0
        } else product.quantity
        addOrIncrement(
            product.id, product.name, selectedPrice, stock, product.imageUrl,
            color, saleMode
        )
    }

    private fun addOrIncrement(
        productId: Long,
        name: String,
        price: Double,
        stock: Int,
        imageUrl: String?,
        color: String,
        saleMode: String
    ) {
        val lineKey = "$productId::$color::$saleMode"
        _cart.update { lines ->
            val i = lines.indexOfFirst { it.lineKey == lineKey }
            val physicalUsed = lines
                .filter { it.productId == productId && it.color == color }
                .sumOf { it.qty }
            if (i >= 0) {
                val cur = lines[i]
                if (physicalUsed >= stock) {
                    _message.value = "لا يمكن تجاوز المخزون المتاح"
                    return@update lines
                }
                lines.toMutableList().apply { this[i] = cur.copy(qty = cur.qty + 1) }
            } else {
                if (stock <= physicalUsed) {
                    _message.value = "الكمية غير متوفرة لهذا المنتج"
                    return@update lines
                }
                lines + CartLine(
                    lineKey, productId, name, price, qty = 1, maxStock = stock,
                    imageUrl = imageUrl, color = color, saleMode = saleMode
                )
            }
        }
    }

    fun setQty(lineKey: String, qty: Int) {
        _cart.update { lines ->
            val target = lines.firstOrNull { it.lineKey == lineKey } ?: return@update lines
            val usedByOtherModes = lines
                .filter {
                    it.lineKey != lineKey &&
                        it.productId == target.productId &&
                        it.color == target.color
                }
                .sumOf { it.qty }
            val allowedForLine = (target.maxStock - usedByOtherModes).coerceAtLeast(1)
            lines.map {
                if (it.lineKey == lineKey) {
                    val q = qty.coerceIn(1, allowedForLine)
                    it.copy(qty = q)
                } else it
            }
        }
    }

    fun removeLine(lineKey: String) {
        _cart.update { it.filter { line -> line.lineKey != lineKey } }
    }

    fun setNote(s: String) {
        _note.value = s
    }

    fun clearCart() {
        _cart.value = emptyList()
    }

    fun setScheduledDate(s: String) {
        _scheduledDate.value = s
    }

    fun setUnitPrice(lineKey: String, price: Double) {
        if (price <= 0) return
        _cart.update { lines ->
            lines.map {
                if (it.lineKey == lineKey) it.copy(unitPrice = price) else it
            }
        }
    }

    fun addCustomer(
        name: String,
        phone: String,
        phone2: String,
        city: String,
        address: String,
        onSuccess: () -> Unit
    ) {
        if (name.isBlank() || phone.isBlank()) {
            _message.value = "الاسم والهاتف مطلوبان"
            return
        }
        viewModelScope.launch {
            _loading.value = true
            val r = withContext(Dispatchers.IO) {
                repository.addCustomer(name, phone, phone2, city, address)
            }
            _loading.value = false
            if (r.isSuccess) {
                val c = r.getOrNull()!!
                _selectedCustomer.value = c
                _customerQuery.value = ""
                _customers.value = emptyList()
                _message.value = "تمت إضافة الزبون بنجاح"
                onSuccess()
            } else {
                _message.value = r.exceptionOrNull()?.message ?: "تعذر إضافة الزبون"
            }
        }
    }

    fun submitOrder(onSuccess: (Long, Double) -> Unit) {
        val cust = _selectedCustomer.value
        if (cust == null) {
            _message.value = "اختر زبوناً"
            return
        }
        val lines = _cart.value
        if (lines.isEmpty()) {
            _message.value = "أضف منتجات للسلة"
            return
        }
        viewModelScope.launch {
            _loading.value = true
            _message.value = null
            val items = lines.map {
                CreateOrderItem(
                    productId = it.productId,
                    qty = it.qty,
                    price = it.unitPrice,
                    color = it.color.ifBlank { null },
                    saleMode = it.saleMode
                )
            }
            val r = withContext(Dispatchers.IO) {
                repository.createOrder(cust.id, items, _note.value, _scheduledDate.value)
            }
            _loading.value = false
            if (r.isSuccess) {
                val body = r.getOrNull()!!
                onSuccess(body.invoiceId ?: 0L, body.total ?: 0.0)
                _cart.value = emptyList()
                _note.value = ""
                _scheduledDate.value = ""
            } else {
                _message.value = r.exceptionOrNull()?.message ?: "فشل إنشاء الطلب"
            }
        }
    }

    fun clearMessage() {
        _message.value = null
    }

    class Factory(private val repository: PosRepository) : ViewModelProvider.Factory {
        @Suppress("UNCHECKED_CAST")
        override fun <T : ViewModel> create(modelClass: Class<T>): T =
            PosViewModel(repository) as T
    }
}
