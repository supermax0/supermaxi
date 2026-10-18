import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/di/providers.dart';
import '../../../core/storage/token_storage.dart';

/// Soft UI lock — never blocks telephony / overlay.
class AppLockState {
  const AppLockState({
    this.locked = false,
    this.enabled = false,
    this.ready = false,
  });

  final bool locked;
  final bool enabled;
  final bool ready;

  AppLockState copyWith({bool? locked, bool? enabled, bool? ready}) {
    return AppLockState(
      locked: locked ?? this.locked,
      enabled: enabled ?? this.enabled,
      ready: ready ?? this.ready,
    );
  }
}

final appLockProvider =
    StateNotifierProvider<AppLockController, AppLockState>((ref) {
  return AppLockController(ref.watch(tokenStorageProvider));
});

class AppLockController extends StateNotifier<AppLockState> {
  AppLockController(this._storage) : super(const AppLockState()) {
    refresh();
  }

  final TokenStorage _storage;

  Future<void> refresh() async {
    final pin = await _storage.readPin();
    final bio = await _storage.isBiometricEnabled();
    final enabled = bio || (pin != null && pin.isNotEmpty);
    state = AppLockState(
      enabled: enabled,
      locked: enabled,
      ready: true,
    );
  }

  void unlock() {
    if (!state.locked) return;
    state = state.copyWith(locked: false);
  }

  void lockIfEnabled() {
    if (state.enabled) {
      state = state.copyWith(locked: true);
    }
  }

  Future<void> reevaluateAndLock() async {
    final pin = await _storage.readPin();
    final bio = await _storage.isBiometricEnabled();
    final enabled = bio || (pin != null && pin.isNotEmpty);
    state = AppLockState(
      enabled: enabled,
      locked: enabled,
      ready: true,
    );
  }
}
