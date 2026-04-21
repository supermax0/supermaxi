package iq.finora.pos.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.navigation.NavHostController
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.rememberNavController
import iq.finora.pos.data.PosRepository
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

@Composable
fun AppRoot(repository: PosRepository) {
    val nav = rememberNavController()
    NavHost(navController = nav, startDestination = "splash") {
        composable("splash") { SplashRoute(repository, nav) }
        composable("setup") { SetupRoute(repository, nav) }
        composable("login") { LoginRoute(repository, nav) }
        composable("pos") { PosRoute(repository, nav) }
    }
}

@Composable
private fun SplashRoute(repository: PosRepository, nav: NavHostController) {
    Column(
        modifier = Modifier.fillMaxSize(),
        verticalArrangement = Arrangement.Center,
        horizontalAlignment = Alignment.CenterHorizontally
    ) {
        CircularProgressIndicator()
    }
    LaunchedEffect(Unit) {
        val dest = withContext(Dispatchers.IO) {
            when {
                repository.getBaseUrl() == null -> "setup"
                repository.probeSession() -> "pos"
                else -> "login"
            }
        }
        nav.navigate(dest) {
            popUpTo("splash") { inclusive = true }
            launchSingleTop = true
        }
    }
}

@Composable
private fun SetupRoute(repository: PosRepository, nav: NavHostController) {
    var url by remember { mutableStateOf("") }
    var err by remember { mutableStateOf<String?>(null) }
    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(24.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp)
    ) {
        Text("عنوان الخادم", style = MaterialTheme.typography.headlineSmall)
        Text(
            "مثال: https://shop.example.com — بدون شرطة في النهاية",
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant
        )
        OutlinedTextField(
            value = url,
            onValueChange = { url = it; err = null },
            modifier = Modifier.fillMaxWidth(),
            singleLine = true,
            label = { Text("الرابط") },
            placeholder = { Text("https://…") }
        )
        err?.let { Text(it, color = MaterialTheme.colorScheme.error) }
        Spacer(Modifier.height(8.dp))
        Button(
            onClick = {
                val n = url.trim().trimEnd('/')
                if (n.isEmpty()) {
                    err = "أدخل الرابط"
                } else {
                    repository.setBaseUrl(n)
                    nav.navigate("login") {
                        popUpTo("setup") { inclusive = true }
                        launchSingleTop = true
                    }
                }
            },
            modifier = Modifier.fillMaxWidth()
        ) { Text("متابعة") }
    }
}
