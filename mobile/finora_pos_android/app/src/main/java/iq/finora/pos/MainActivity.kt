package iq.finora.pos

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.material3.Surface
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalLayoutDirection
import androidx.compose.ui.unit.LayoutDirection
import iq.finora.pos.data.PosRepository
import iq.finora.pos.ui.AppRoot
import iq.finora.pos.ui.theme.FinoraTheme

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val app = application as FinoraApp
        val repository = PosRepository.from(app)
        setContent {
            FinoraTheme {
                CompositionLocalProvider(
                    LocalLayoutDirection provides LayoutDirection.Rtl
                ) {
                    Surface(modifier = Modifier.fillMaxSize()) {
                        AppRoot(repository = repository)
                    }
                }
            }
        }
    }
}
