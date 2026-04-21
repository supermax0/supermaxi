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
    val productId: Long,
    val name: String,
    val unitPrice: Double,
    var qty: Int,
    val maxStock: Int
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
                val r = withContext(Dispatchers.IO) { repository.searchProducts(q) }
                if (r.isSuccess) _searchHits.value = r.getOrDefault(emptyList())
                else _searchHits.value = emptyList()
            }
            .launchIn(viewModelScope)
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
        addOrIncrement(p.id, p.name, p.salePrice, p.quantity)
        _message.value = null
    }

    fun addProductFromSearch(p: SearchProductItem) {
        addOrIncrement(p.id, p.name, p.price, p.quantity)
        _searchHits.value = emptyList()
        _productQuery.value = ""
    }

    private fun addOrIncrement(productId: Long, name: String, price: Double, stock: Int) {
        _cart.update { lines ->
            val i = lines.indexOfFirst { it.productId == productId }
            if (i >= 0) {
                val cur = lines[i]
                if (cur.qty >= cur.maxStock) {
                    _message.value = "لا يمكن تجاوز المخزون المتاح"
                    return@update lines
                }
                lines.toMutableList().apply { this[i] = cur.copy(qty = cur.qty + 1) }
            } else {
                if (stock <= 0) {
                    _message.value = "الكمية غير متوفرة لهذا المنتج"
                    return@update lines
                }
                lines + CartLine(productId, name, price, qty = 1, maxStock = stock)
            }
        }
    }

    fun setQty(productId: Long, qty: Int) {
        _cart.update { lines ->
            lines.map {
                if (it.productId == productId) {
                    val q = qty.coerceIn(1, it.maxStock)
                    it.copy(qty = q)
                } else it
            }
        }
    }

    fun removeLine(productId: Long) {
        _cart.update { it.filter { line -> line.productId != productId } }
    }

    fun setNote(s: String) {
        _note.value = s
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
                    price = it.unitPrice
                )
            }
            val r = withContext(Dispatchers.IO) {
                repository.createOrder(cust.id, items, _note.value)
            }
            _loading.value = false
            if (r.isSuccess) {
                val body = r.getOrNull()!!
                onSuccess(body.invoiceId ?: 0L, body.total ?: 0.0)
                _cart.value = emptyList()
                _note.value = ""
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
