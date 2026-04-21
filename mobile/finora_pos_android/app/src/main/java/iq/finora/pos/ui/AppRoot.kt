package iq.finora.pos.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
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
