package iq.finora.pos.ui

import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.viewModelScope
import iq.finora.pos.data.PosRepository
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

class LoginViewModel(private val repository: PosRepository) : ViewModel() {

    private val _busy = MutableStateFlow(false)
    val busy: StateFlow<Boolean> = _busy.asStateFlow()

    private val _error = MutableStateFlow<String?>(null)
    val error: StateFlow<String?> = _error.asStateFlow()

    private val _done = MutableStateFlow(false)
    val done: StateFlow<Boolean> = _done.asStateFlow()

    fun clearDone() {
        _done.value = false
    }

    fun login(tenantSlug: String, username: String, password: String) {
        _error.value = null
        viewModelScope.launch {
            _busy.value = true
            val result = withContext(Dispatchers.IO) {
                repository.login(tenantSlug, username, password)
            }
            _busy.value = false
            if (result.isSuccess) {
                _done.value = true
            } else {
                _error.value = result.exceptionOrNull()?.message
                    ?: "فشل الاتصال أو بيانات غير صحيحة"
            }
        }
    }

    class Factory(private val repository: PosRepository) : ViewModelProvider.Factory {
        @Suppress("UNCHECKED_CAST")
        override fun <T : ViewModel> create(modelClass: Class<T>): T =
            LoginViewModel(repository) as T
    }
}
