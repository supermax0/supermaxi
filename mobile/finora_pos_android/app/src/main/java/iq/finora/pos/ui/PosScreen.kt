package iq.finora.pos.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.Logout
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.Edit
import androidx.compose.material.icons.filled.ExpandLess
import androidx.compose.material.icons.filled.ExpandMore
import androidx.compose.material.icons.filled.PersonAdd
import androidx.compose.material.icons.filled.ShoppingCart
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilledTonalButton
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.Surface
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.lifecycle.viewmodel.compose.viewModel
import androidx.navigation.NavHostController
import coil.compose.AsyncImage
import iq.finora.pos.data.PosRepository
import iq.finora.pos.ui.theme.Primary
import iq.finora.pos.ui.theme.Secondary
import kotlinx.coroutines.launch
import java.time.LocalDate
import java.time.format.DateTimeFormatter
import java.util.Locale

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun PosRoute(repository: PosRepository, nav: NavHostController) {
    val vm: PosViewModel = viewModel(factory = PosViewModel.Factory(repository))
    val snack = remember { SnackbarHostState() }
    val scope = rememberCoroutineScope()

    val loading by vm.loading.collectAsState()
    val products by vm.products.collectAsState()
    val customerQuery by vm.customerQuery.collectAsState()
    val customers by vm.customers.collectAsState()
    val selected by vm.selectedCustomer.collectAsState()
    val productQuery by vm.productQuery.collectAsState()
    val hits by vm.searchHits.collectAsState()
    val cart by vm.cart.collectAsState()
    val note by vm.note.collectAsState()
    val scheduledDate by vm.scheduledDate.collectAsState()
    val msg by vm.message.collectAsState()

    var showAddCustomer by remember { mutableStateOf(false) }
    var editPriceProductId by remember { mutableStateOf<Long?>(null) }
    var showInventory by remember { mutableStateOf(false) }

    val total = cart.sumOf { it.unitPrice * it.qty }

    LaunchedEffect(Unit) {
        vm.refreshCatalog()
    }

    LaunchedEffect(msg) {
        if (msg != null) {
            snack.showSnackbar(msg!!)
            vm.clearMessage()
        }
    }

    if (showAddCustomer) {
        AddCustomerDialog(
            loading = loading,
            onDismiss = { showAddCustomer = false },
            onSave = { name, phone, phone2, city, address ->
                vm.addCustomer(name, phone, phone2, city, address) {
                    showAddCustomer = false
                }
            }
        )
    }

    val lineToEdit = cart.firstOrNull { it.productId == editPriceProductId }
    if (lineToEdit != null) {
        EditPriceDialog(
            currentPrice = lineToEdit.unitPrice,
            onDismiss = { editPriceProductId = null },
            onSave = { newPrice ->
                vm.setUnitPrice(lineToEdit.productId, newPrice)
                editPriceProductId = null
            }
        )
    }

    Scaffold(
        snackbarHost = { SnackbarHost(snack) },
        bottomBar = {
            CheckoutBar(
                total = total,
                enabled = !loading && selected != null && cart.isNotEmpty(),
                onCheckout = {
                    vm.submitOrder { inv, tot ->
                        scope.launch { snack.showSnackbar("تم الطلب #$inv — ${fmtMoney(tot)} د.ع") }
                    }
                }
            )
        },
        topBar = {
            TopAppBar(
                title = {
                    Column {
                        Text("نقطة البيع", style = MaterialTheme.typography.titleLarge)
                        Text(
                            "سريع - احترافي - دقيق",
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant
                        )
                    }
                },
                actions = {
                    IconButton(onClick = {
                        repository.logout()
                        nav.navigate("login") {
                            popUpTo("pos") { inclusive = true }
                            launchSingleTop = true
                        }
                    }) {
                        Icon(Icons.AutoMirrored.Filled.Logout, contentDescription = "خروج")
                    }
                }
            )
        }
    ) { pad ->
        LazyColumn(
            modifier = Modifier
                .fillMaxSize()
                .padding(pad)
                .padding(horizontal = 16.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp)
        ) {
            item {
                Card(
                    colors = CardDefaults.cardColors(containerColor = Color.Transparent),
                    elevation = CardDefaults.cardElevation(defaultElevation = 0.dp)
                ) {
                    Box(
                        modifier = Modifier
                            .fillMaxWidth()
                            .background(Brush.horizontalGradient(listOf(Primary, Secondary)))
                            .padding(14.dp)
                    ) {
                        Column {
                            Text("إجمالي السلة", color = Color.White.copy(alpha = 0.85f))
                            Text(
                                "${fmtMoney(total)} د.ع",
                                style = MaterialTheme.typography.headlineMedium,
                                color = Color.White
                            )
                        }
                    }
                }
            }

            item {
                SectionTitle("الزبون")
                if (selected != null) {
                    PremiumCard {
                        Row(
                            modifier = Modifier
                                .fillMaxWidth()
                                .padding(12.dp),
                            horizontalArrangement = Arrangement.SpaceBetween,
                            verticalAlignment = Alignment.CenterVertically
                        ) {
                            Column {
                                Text(selected!!.name, style = MaterialTheme.typography.titleMedium)
                                Text(
                                    selected!!.phone,
                                    style = MaterialTheme.typography.bodySmall,
                                    color = MaterialTheme.colorScheme.onSurfaceVariant
                                )
                            }
                            TextButton(onClick = { vm.clearCustomer() }) { Text("تغيير") }
                        }
                    }
                } else {
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.End
                    ) {
                        TextButton(onClick = { showAddCustomer = true }) {
                            Icon(Icons.Default.PersonAdd, contentDescription = null)
                            Text("إضافة زبون")
                        }
                    }
                    OutlinedTextField(
                        value = customerQuery,
                        onValueChange = { vm.setCustomerQuery(it) },
                        modifier = Modifier.fillMaxWidth(),
                        singleLine = true,
                        label = { Text("بحث سريع بالاسم أو الهاتف") }
                    )
                    customers.take(8).forEach { c ->
                        PremiumCard(
                            modifier = Modifier
                                .fillMaxWidth()
                                .padding(top = 6.dp)
                                .clickable { vm.selectCustomer(c) }
                        ) {
                            Column(Modifier.padding(12.dp)) {
                                Text(c.name, style = MaterialTheme.typography.titleMedium)
                                Text(c.phone, style = MaterialTheme.typography.bodySmall)
                                if (c.blacklisted) {
                                    Text("قائمة سوداء", color = MaterialTheme.colorScheme.error)
                                }
                            }
                        }
                    }
                }
            }

            item {
                SectionTitle("إضافة منتج")
                OutlinedTextField(
                    value = productQuery,
                    onValueChange = { vm.setProductQuery(it) },
                    modifier = Modifier.fillMaxWidth(),
                    singleLine = true,
                    label = { Text("بحث ذكي بالاسم / الباركود") }
                )
                hits.take(12).forEach { p ->
                    PremiumCard(
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(top = 6.dp)
                            .clickable { vm.addProductFromSearch(p) }
                    ) {
                        Row(
                            modifier = Modifier
                                .fillMaxWidth()
                                .padding(12.dp),
                            horizontalArrangement = Arrangement.SpaceBetween,
                            verticalAlignment = Alignment.CenterVertically
                        ) {
                            Row(modifier = Modifier.weight(1f), verticalAlignment = Alignment.CenterVertically) {
                                ProductImage(imageUrl = p.imageUrl, baseUrl = repository.getBaseUrl().orEmpty())
                                Spacer(Modifier.size(10.dp))
                                Column {
                                    Text(p.name, style = MaterialTheme.typography.titleMedium)
                                    Text(
                                        "${fmtMoney(p.price)} د.ع • متوفر ${p.quantity}",
                                        style = MaterialTheme.typography.bodySmall,
                                        color = MaterialTheme.colorScheme.onSurfaceVariant
                                    )
                                }
                            }
                            Icon(Icons.Default.Add, contentDescription = null, tint = Primary)
                        }
                    }
                }
            }

            item {
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.SpaceBetween,
                    verticalAlignment = Alignment.CenterVertically
                ) {
                    SectionTitle("المخزون")
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        if (loading) {
                            CircularProgressIndicator(strokeWidth = 2.dp, modifier = Modifier.size(20.dp))
                            Spacer(Modifier.size(10.dp))
                        }
                        TextButton(onClick = { showInventory = !showInventory }) {
                            Icon(
                                if (showInventory) Icons.Default.ExpandLess else Icons.Default.ExpandMore,
                                contentDescription = null
                            )
                            Text(if (showInventory) "إخفاء المنتجات" else "عرض المنتجات")
                        }
                    }
                }
                if (showInventory) {
                    products.take(80).forEach { p ->
                        PremiumCard(
                            modifier = Modifier
                                .fillMaxWidth()
                                .padding(top = 6.dp)
                                .clickable { vm.addProductFromCatalog(p) }
                        ) {
                            Row(
                                modifier = Modifier
                                    .fillMaxWidth()
                                    .padding(12.dp),
                                horizontalArrangement = Arrangement.SpaceBetween,
                                verticalAlignment = Alignment.CenterVertically
                            ) {
                                Row(modifier = Modifier.weight(1f), verticalAlignment = Alignment.CenterVertically) {
                                    ProductImage(imageUrl = p.imageUrl, baseUrl = repository.getBaseUrl().orEmpty())
                                    Spacer(Modifier.size(10.dp))
                                    Column {
                                        Text(p.name, style = MaterialTheme.typography.titleMedium)
                                        Text(
                                            "${fmtMoney(p.salePrice)} د.ع • ${p.quantity}",
                                            style = MaterialTheme.typography.bodySmall,
                                            color = MaterialTheme.colorScheme.onSurfaceVariant
                                        )
                                    }
                                }
                                Icon(Icons.Default.Add, contentDescription = null, tint = Primary)
                            }
                        }
                    }
                }
            }

            item {
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.SpaceBetween,
                    verticalAlignment = Alignment.CenterVertically
                ) {
                    SectionTitle("سلة الطلب")
                    if (cart.isNotEmpty()) {
                        TextButton(onClick = { vm.clearCart() }) { Text("تفريغ السلة") }
                    }
                }
                if (cart.isEmpty()) {
                    PremiumCard {
                        Row(
                            modifier = Modifier
                                .fillMaxWidth()
                                .padding(14.dp),
                            verticalAlignment = Alignment.CenterVertically
                        ) {
                            Icon(
                                imageVector = Icons.Default.ShoppingCart,
                                contentDescription = null,
                                tint = MaterialTheme.colorScheme.onSurfaceVariant
                            )
                            Spacer(Modifier.size(8.dp))
                            Text("لا توجد عناصر في السلة", color = MaterialTheme.colorScheme.onSurfaceVariant)
                        }
                    }
                } else {
                    cart.forEach { line ->
                        PremiumCard(Modifier.fillMaxWidth()) {
                            Column(Modifier.padding(12.dp)) {
                                Row(
                                    Modifier.fillMaxWidth(),
                                    horizontalArrangement = Arrangement.SpaceBetween,
                                    verticalAlignment = Alignment.CenterVertically
                                ) {
                                    Row(modifier = Modifier.weight(1f), verticalAlignment = Alignment.CenterVertically) {
                                        ProductImage(imageUrl = line.imageUrl, baseUrl = repository.getBaseUrl().orEmpty())
                                        Spacer(Modifier.size(10.dp))
                                        Column {
                                            Text(line.name, style = MaterialTheme.typography.titleMedium)
                                            Text(
                                                "${fmtMoney(line.unitPrice)} د.ع × ${line.qty}",
                                                style = MaterialTheme.typography.bodySmall,
                                                color = MaterialTheme.colorScheme.onSurfaceVariant
                                            )
                                        }
                                    }
                                    IconButton(onClick = { vm.removeLine(line.productId) }) {
                                        Icon(Icons.Default.Delete, contentDescription = "حذف", tint = MaterialTheme.colorScheme.error)
                                    }
                                }
                                Row(verticalAlignment = Alignment.CenterVertically) {
                                    TextButton(
                                        onClick = { vm.setQty(line.productId, line.qty - 1) },
                                        enabled = line.qty > 1
                                    ) { Text("−") }
                                    Text("${line.qty}", modifier = Modifier.padding(horizontal = 8.dp), style = MaterialTheme.typography.titleMedium)
                                    TextButton(
                                        onClick = { vm.setQty(line.productId, line.qty + 1) },
                                        enabled = line.qty < line.maxStock
                                    ) { Text("+") }
                                    Spacer(Modifier.size(8.dp))
                                    TextButton(onClick = { editPriceProductId = line.productId }) {
                                        Icon(Icons.Default.Edit, contentDescription = null)
                                        Text("السعر")
                                    }
                                }
                            }
                        }
                    }
                }
            }

            item {
                OutlinedTextField(
                    value = scheduledDate,
                    onValueChange = { vm.setScheduledDate(it) },
                    modifier = Modifier.fillMaxWidth(),
                    label = { Text("تأجيل الطلب (YYYY-MM-DD)") },
                    singleLine = true
                )
                Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.End) {
                    TextButton(onClick = { vm.setScheduledDate(todayIso()) }) { Text("اليوم") }
                    TextButton(onClick = { vm.setScheduledDate(tomorrowIso()) }) { Text("غداً") }
                    TextButton(onClick = { vm.setScheduledDate("") }) { Text("إزالة") }
                }
                OutlinedTextField(
                    value = note,
                    onValueChange = { vm.setNote(it) },
                    modifier = Modifier.fillMaxWidth(),
                    label = { Text("ملاحظة (اختياري)") },
                    minLines = 2
                )
                Spacer(Modifier.height(8.dp))
                Spacer(Modifier.height(90.dp))
            }
        }
    }
}

@Composable
private fun PremiumCard(
    modifier: Modifier = Modifier,
    content: @Composable () -> Unit
) {
    Card(
        modifier = modifier.border(
            width = 1.dp,
            color = MaterialTheme.colorScheme.outline.copy(alpha = 0.18f),
            shape = MaterialTheme.shapes.medium
        ),
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface),
        elevation = CardDefaults.cardElevation(defaultElevation = 4.dp)
    ) {
        content()
    }
}

@Composable
private fun CheckoutBar(
    total: Double,
    enabled: Boolean,
    onCheckout: () -> Unit
) {
    Surface(tonalElevation = 6.dp, shadowElevation = 10.dp) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 16.dp, vertical = 10.dp),
            horizontalArrangement = Arrangement.spacedBy(10.dp),
            verticalAlignment = Alignment.CenterVertically
        ) {
            Column(
                modifier = Modifier
                    .weight(1f)
                    .clip(MaterialTheme.shapes.medium)
                    .background(MaterialTheme.colorScheme.surfaceVariant)
                    .padding(horizontal = 12.dp, vertical = 10.dp)
            ) {
                Text("الإجمالي", style = MaterialTheme.typography.bodySmall)
                Text("${fmtMoney(total)} د.ع", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)
            }
            FilledTonalButton(
                onClick = onCheckout,
                enabled = enabled,
                modifier = Modifier.height(52.dp)
            ) {
                Text("تأكيد الطلب")
            }
        }
    }
}

@Composable
private fun ProductImage(imageUrl: String?, baseUrl: String) {
    val resolved = resolveImageUrl(imageUrl, baseUrl)
    AsyncImage(
        model = resolved,
        contentDescription = null,
        modifier = Modifier
            .size(44.dp)
            .clip(MaterialTheme.shapes.small)
            .background(MaterialTheme.colorScheme.surfaceVariant),
        contentScale = ContentScale.Crop
    )
}

private fun resolveImageUrl(raw: String?, baseUrl: String): String? {
    if (raw.isNullOrBlank()) return null
    return when {
        raw.startsWith("http://") || raw.startsWith("https://") -> raw
        raw.startsWith("/") -> "$baseUrl$raw"
        else -> "$baseUrl/$raw"
    }
}

@Composable
private fun SectionTitle(text: String) {
    Text(
        text = text,
        style = MaterialTheme.typography.titleLarge,
        fontWeight = FontWeight.Bold,
        modifier = Modifier.padding(top = 6.dp, bottom = 2.dp)
    )
}

@Composable
private fun AddCustomerDialog(
    loading: Boolean,
    onDismiss: () -> Unit,
    onSave: (name: String, phone: String, phone2: String, city: String, address: String) -> Unit
) {
    var name by remember { mutableStateOf("") }
    var phone by remember { mutableStateOf("") }
    var phone2 by remember { mutableStateOf("") }
    var city by remember { mutableStateOf("") }
    var address by remember { mutableStateOf("") }

    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("إضافة زبون جديد") },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                OutlinedTextField(value = name, onValueChange = { name = it }, label = { Text("الاسم") })
                OutlinedTextField(value = phone, onValueChange = { phone = it }, label = { Text("الهاتف") })
                OutlinedTextField(value = phone2, onValueChange = { phone2 = it }, label = { Text("هاتف إضافي") })
                OutlinedTextField(value = city, onValueChange = { city = it }, label = { Text("المحافظة") })
                OutlinedTextField(value = address, onValueChange = { address = it }, label = { Text("العنوان") })
            }
        },
        confirmButton = {
            TextButton(enabled = !loading, onClick = { onSave(name, phone, phone2, city, address) }) { Text("حفظ") }
        },
        dismissButton = { TextButton(onClick = onDismiss) { Text("إلغاء") } }
    )
}

@Composable
private fun EditPriceDialog(
    currentPrice: Double,
    onDismiss: () -> Unit,
    onSave: (Double) -> Unit
) {
    var value by remember { mutableStateOf(currentPrice.toString()) }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("تعديل سعر المنتج") },
        text = {
            OutlinedTextField(
                value = value,
                onValueChange = { value = it },
                label = { Text("السعر الجديد") },
                singleLine = true
            )
        },
        confirmButton = {
            TextButton(onClick = {
                val v = value.toDoubleOrNull() ?: 0.0
                if (v > 0) onSave(v)
            }) { Text("تطبيق") }
        },
        dismissButton = { TextButton(onClick = onDismiss) { Text("إلغاء") } }
    )
}

private fun todayIso(): String = LocalDate.now().format(DateTimeFormatter.ISO_LOCAL_DATE)
private fun tomorrowIso(): String = LocalDate.now().plusDays(1).format(DateTimeFormatter.ISO_LOCAL_DATE)

private fun fmtMoney(v: Double): String = String.format(Locale.US, "%,.0f", v)
