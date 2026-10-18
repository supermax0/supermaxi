import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';

final themeModeControllerProvider =
    StateNotifierProvider<ThemeModeController, ThemeMode>((ref) {
  final controller = ThemeModeController();
  controller.restore();
  return controller;
});

class ThemeModeController extends StateNotifier<ThemeMode> {
  ThemeModeController({FlutterSecureStorage? storage})
      : _storage = storage ?? const FlutterSecureStorage(),
        super(ThemeMode.system);

  static const _storageKey = 'finora_theme_mode';
  final FlutterSecureStorage _storage;

  Future<void> restore() async {
    try {
      final saved = await _storage.read(key: _storageKey);
      state = switch (saved) {
        'light' => ThemeMode.light,
        'dark' => ThemeMode.dark,
        _ => ThemeMode.system,
      };
    } catch (_) {
      // System theme remains a safe default when platform storage is unavailable.
    }
  }

  Future<void> setMode(ThemeMode mode) async {
    if (state == mode) return;
    state = mode;
    try {
      await _storage.write(key: _storageKey, value: mode.name);
    } catch (_) {
      // The in-memory selection still applies for the current session.
    }
  }
}
