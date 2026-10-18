import 'package:flutter_secure_storage/flutter_secure_storage.dart';

class TokenStorage {
  TokenStorage({FlutterSecureStorage? storage})
      : _storage = storage ?? const FlutterSecureStorage();

  final FlutterSecureStorage _storage;

  static const _accessKey = 'finora_phone_access_token';
  static const _refreshKey = 'finora_phone_refresh_token';
  static const _deviceKey = 'finora_phone_device_id';
  static const _pinKey = 'finora_phone_pin_lock';
  static const _bioKey = 'finora_phone_bio_lock';
  static const _permsDoneKey = 'finora_phone_perms_done';
  static const _diagLogKey = 'finora_phone_diag_log';
  static const _crashKey = 'finora_phone_crash_log';
  static const _lastSyncKey = 'finora_phone_last_sync';
  static const _lastCallEventKey = 'finora_phone_last_call_event';
  static const _lastApiErrorKey = 'finora_phone_last_api_error';
  static const _blockScreenshotsKey = 'finora_phone_block_screenshots';
  static const _secureRecentsKey = 'finora_phone_secure_recents';
  static const _tenantKey = 'finora_phone_tenant_slug';
  static const _followupMinutesKey = 'finora_phone_followup_minutes';
  static const _featureFlagsKey = 'finora_phone_feature_flags';
  static const _sessionKey = 'finora_phone_employee_session';

  Future<void> saveTokens({
    required String accessToken,
    required String refreshToken,
  }) async {
    await _storage.write(key: _accessKey, value: accessToken);
    await _storage.write(key: _refreshKey, value: refreshToken);
  }

  Future<String?> readAccessToken() => _storage.read(key: _accessKey);
  Future<String?> readRefreshToken() => _storage.read(key: _refreshKey);
  Future<String?> readDeviceId() => _storage.read(key: _deviceKey);
  Future<void> saveDeviceId(String deviceId) =>
      _storage.write(key: _deviceKey, value: deviceId);

  Future<void> clearTokens() async {
    await _storage.delete(key: _accessKey);
    await _storage.delete(key: _refreshKey);
  }

  /// Cached employee session, so the app can open offline without re-login.
  Future<void> saveSessionJson(String json) =>
      _storage.write(key: _sessionKey, value: json);

  Future<String?> readSessionJson() => _storage.read(key: _sessionKey);

  Future<void> clearSession() => _storage.delete(key: _sessionKey);

  /// Full local wipe when device is revoked server-side.
  Future<void> wipeAllSensitive() async {
    await clearTokens();
    await clearSession();
    await _storage.delete(key: _pinKey);
    await _storage.delete(key: _diagLogKey);
    await _storage.delete(key: _lastSyncKey);
    await _storage.delete(key: _lastCallEventKey);
    await _storage.delete(key: _lastApiErrorKey);
  }

  Future<void> setPin(String? pin) async {
    if (pin == null || pin.isEmpty) {
      await _storage.delete(key: _pinKey);
    } else {
      await _storage.write(key: _pinKey, value: pin);
    }
  }

  Future<String?> readPin() => _storage.read(key: _pinKey);

  Future<void> setBiometricEnabled(bool enabled) =>
      _storage.write(key: _bioKey, value: enabled ? '1' : '0');

  Future<bool> isBiometricEnabled() async =>
      (await _storage.read(key: _bioKey)) == '1';

  Future<void> setPermissionsDone(bool done) =>
      _storage.write(key: _permsDoneKey, value: done ? '1' : '0');

  Future<bool> isPermissionsDone() async =>
      (await _storage.read(key: _permsDoneKey)) == '1';

  Future<void> appendDiagnosticLog(String line) async {
    final prev = await _storage.read(key: _diagLogKey) ?? '';
    final next = '$prev\n$line'.trim();
    final clipped =
        next.length > 80000 ? next.substring(next.length - 80000) : next;
    await _storage.write(key: _diagLogKey, value: clipped);
  }

  Future<String?> readDiagnosticLog() => _storage.read(key: _diagLogKey);

  Future<void> writeCrashLog(String value) =>
      _storage.write(key: _crashKey, value: value);
  Future<String?> readCrashLog() => _storage.read(key: _crashKey);

  Future<void> setLastSync(String iso) =>
      _storage.write(key: _lastSyncKey, value: iso);
  Future<String?> readLastSync() => _storage.read(key: _lastSyncKey);

  Future<void> setLastCallEvent(String json) =>
      _storage.write(key: _lastCallEventKey, value: json);
  Future<String?> readLastCallEvent() => _storage.read(key: _lastCallEventKey);

  Future<void> setLastApiError(String msg) =>
      _storage.write(key: _lastApiErrorKey, value: msg);
  Future<String?> readLastApiError() => _storage.read(key: _lastApiErrorKey);

  Future<void> setBlockScreenshots(bool v) =>
      _storage.write(key: _blockScreenshotsKey, value: v ? '1' : '0');
  Future<bool> isBlockScreenshots() async =>
      (await _storage.read(key: _blockScreenshotsKey)) != '0'; // default on

  Future<void> setSecureRecents(bool v) =>
      _storage.write(key: _secureRecentsKey, value: v ? '1' : '0');
  Future<bool> isSecureRecents() async =>
      (await _storage.read(key: _secureRecentsKey)) != '0';

  Future<void> saveTenantSlug(String slug) =>
      _storage.write(key: _tenantKey, value: slug.trim().toLowerCase());

  Future<String?> readTenantSlug() => _storage.read(key: _tenantKey);

  Future<void> saveFollowupMinutes(int minutes) =>
      _storage.write(key: _followupMinutesKey, value: '$minutes');

  Future<int?> readFollowupMinutes() async {
    final raw = await _storage.read(key: _followupMinutesKey);
    return int.tryParse(raw ?? '');
  }

  Future<void> saveFeatureFlagsJson(String json) =>
      _storage.write(key: _featureFlagsKey, value: json);

  Future<String?> readFeatureFlagsJson() =>
      _storage.read(key: _featureFlagsKey);
}
