package iq.finora.pos.ui

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.automirrored.filled.Logout
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.HorizontalDivider
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
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.lifecycle.viewmodel.compose.viewModel
import androidx.navigation.NavHostController
import iq.finora.pos.data.PosRepository
import kotlinx.coroutines.launch
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
    val msg by vm.message.collectAsState()

    var showServer by remember { mutableStateOf(false) }
    var serverDraft by remember { mutableStateOf(repository.getBaseUrl().orEmpty()) }

    LaunchedEffect(Unit) {
        vm.refreshCatalog()
    }

    LaunchedEffect(msg) {
        if (msg != null) {
            snack.showSnackbar(msg!!)
            vm.clearMessage()
        }
    }

    if (showServer) {
        AlertDialog(
            onDismissRequest = { showServer = false },
            title = { Text("تغيير عنوان الخادم") },
            text = {
                OutlinedTextField(
                    value = serverDraft,
                    onValueChange = { serverDraft = it },
                    modifier = Modifier.fillMaxWidth(),
                    singleLine = true,
                    label = { Text("الرابط") }
                )
            },
            confirmButton = {
                TextButton(onClick = {
                    val n = serverDraft.trim().trimEnd('/')
                    if (n.isNotEmpty()) {
                        repository.setBaseUrl(n)
                        repository.logout()
                        showServer = false
                        nav.navigate("login") {
                            popUpTo("pos") { inclusive = true }
                            launchSingleTop = true
                        }
                    }
                }) { Text("حفظ وإعادة الدخول") }
            },
            dismissButton = {
                TextButton(onClick = { showServer = false }) { Text("إلغاء") }
            }
        )
    }

    Scaffold(
        snackbarHost = { SnackbarHost(snack) },
        topBar = {
            TopAppBar(
                title = { Text("نقطة البيع") },
                actions = {
                    IconButton(onClick = { serverDraft = repository.getBaseUrl().orEmpty(); showServer = true }) {
                        Icon(Icons.Default.Settings, contentDescription = "إعدادات")
                    }
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
                Text("الزبون", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold)
                if (selected != null) {
                    Card(colors = CardDefaults.cardColors()) {
                        Row(
                            Modifier
                                .fillMaxWidth()
                                .padding(12.dp),
                            horizontalArrangement = Arrangement.SpaceBetween,
                            verticalAlignment = Alignment.CenterVertically
                        ) {
                            Column {
                                Text(selected!!.name, style = MaterialTheme.typography.titleSmall)
                                Text(selected!!.phone, style = MaterialTheme.typography.bodySmall)
                            }
                            TextButton(onClick = { vm.clearCustomer() }) { Text("تغيير") }
                        }
                    }
                } else {
                    OutlinedTextField(
                        value = customerQuery,
                        onValueChange = { vm.setCustomerQuery(it) },
                        modifier = Modifier.fillMaxWidth(),
                        singleLine = true,
                        label = { Text("بحث بالاسم أو الهاتف") }
                    )
                    customers.take(12).forEach { c ->
                        Card(
                            modifier = Modifier
                                .fillMaxWidth()
                                .padding(vertical = 4.dp)
                                .clickable { vm.selectCustomer(c) }
                        ) {
                            Column(Modifier.padding(12.dp)) {
                                Text(c.name)
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
                HorizontalDivider()
                Text("إضافة منتج", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold)
                OutlinedTextField(
                    value = productQuery,
                    onValueChange = { vm.setProductQuery(it) },
                    modifier = Modifier.fillMaxWidth(),
                    singleLine = true,
                    label = { Text("بحث أو باركود") }
                )
                hits.take(15).forEach { p ->
                    Card(
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(vertical = 4.dp)
                            .clickable { vm.addProductFromSearch(p) }
                    ) {
                        Row(
                            Modifier
                                .fillMaxWidth()
                                .padding(12.dp),
                            horizontalArrangement = Arrangement.SpaceBetween
                        ) {
                            Column(Modifier.weight(1f)) {
                                Text(p.name)
                                Text(
                                    "${fmtMoney(p.price)} — متوفر ${p.quantity}",
                                    style = MaterialTheme.typography.bodySmall
                                )
                            }
                            Icon(Icons.Default.Add, contentDescription = null)
                        }
                    }
                }
            }

            item {
                HorizontalDivider()
                Row(
                    Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.SpaceBetween,
                    verticalAlignment = Alignment.CenterVertically
                ) {
                    Text("المخزون", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold)
                    if (loading) {
                        CircularProgressIndicator(Modifier.height(24.dp), strokeWidth = 2.dp)
                    } else {
                        TextButton(onClick = { vm.refreshCatalog() }) { Text("تحديث") }
                    }
                }
                Text(
                    "اضغط على صف لإضافته للسلة",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
                products.take(80).forEach { p ->
                    Card(
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(vertical = 3.dp)
                            .clickable { vm.addProductFromCatalog(p) }
                    ) {
                        Row(
                            Modifier
                                .fillMaxWidth()
                                .padding(10.dp),
                            horizontalArrangement = Arrangement.SpaceBetween
                        ) {
                            Column(Modifier.weight(1f)) {
                                Text(p.name, style = MaterialTheme.typography.bodyLarge)
                                Text(
                                    "${fmtMoney(p.salePrice)} — ${p.quantity}",
                                    style = MaterialTheme.typography.bodySmall
                                )
                            }
                            Icon(Icons.Default.Add, contentDescription = null)
                        }
                    }
                }
            }

            item {
                HorizontalDivider()
                Text("السلة", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold)
                if (cart.isEmpty()) {
                    Text("لا عناصر", color = MaterialTheme.colorScheme.onSurfaceVariant)
                } else {
                    cart.forEach { line ->
                        Card(Modifier.fillMaxWidth()) {
                            Column(Modifier.padding(12.dp)) {
                                Row(
                                    Modifier.fillMaxWidth(),
                                    horizontalArrangement = Arrangement.SpaceBetween,
                                    verticalAlignment = Alignment.CenterVertically
                                ) {
                                    Column(Modifier.weight(1f)) {
                                        Text(line.name)
                                        Text(
                                            "${fmtMoney(line.unitPrice)} × ${line.qty}",
                                            style = MaterialTheme.typography.bodySmall
                                        )
                                    }
                                    IconButton(onClick = { vm.removeLine(line.productId) }) {
                                        Icon(Icons.Default.Delete, contentDescription = "حذف")
                                    }
                                }
                                Row(verticalAlignment = Alignment.CenterVertically) {
                                    TextButton(onClick = {
                                        vm.setQty(line.productId, line.qty - 1)
                                    }, enabled = line.qty > 1) { Text("−") }
                                    Text("${line.qty}", modifier = Modifier.padding(horizontal = 8.dp))
                                    TextButton(
                                        onClick = { vm.setQty(line.productId, line.qty + 1) },
                                        enabled = line.qty < line.maxStock
                                    ) { Text("+") }
                                }
                            }
                        }
                    }
                    val total = cart.sumOf { it.unitPrice * it.qty }
                    Text(
                        "الإجمالي: ${fmtMoney(total)}",
                        style = MaterialTheme.typography.titleMedium,
                        fontWeight = FontWeight.Bold
                    )
                }
            }

            item {
                OutlinedTextField(
                    value = note,
                    onValueChange = { vm.setNote(it) },
                    modifier = Modifier.fillMaxWidth(),
                    label = { Text("ملاحظة (اختياري)") },
                    minLines = 2
                )
                Spacer(Modifier.height(8.dp))
                FilledTonalButton(
                    onClick = {
                        vm.submitOrder { inv, tot ->
                            scope.launch {
                                snack.showSnackbar("تم الطلب #$inv — الإجمالي ${fmtMoney(tot)}")
                            }
                        }
                    },
                    modifier = Modifier.fillMaxWidth(),
                    enabled = !loading && selected != null && cart.isNotEmpty()
                ) { Text("تأكيد الطلب") }
                Spacer(Modifier.height(24.dp))
            }
        }
    }
}

private fun fmtMoney(v: Double): String {
    return String.format(Locale.US, "%,.0f", v)
}
