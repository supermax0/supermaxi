import 'dart:convert';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:package_info_plus/package_info_plus.dart';

import '../../../core/bootstrap/phone_bootstrap.dart';
import '../../../core/di/providers.dart';
import '../../../core/errors/api_exception.dart';
import '../../../domain/entities/entities.dart';

enum AuthStatus { unknown, authenticated, unauthenticated }

class AuthState {
  const AuthState({
    this.status = AuthStatus.unknown,
    this.employee,
    this.error,
    this.offline = false,
  });

  final AuthStatus status;
  final EmployeeSession? employee;
  final String? error;

  /// Signed in from cached credentials because the server was unreachable.
  final bool offline;

  AuthState copyWith({
    AuthStatus? status,
    EmployeeSession? employee,
    String? error,
    bool? offline,
  }) {
    return AuthState(
      status: status ?? this.status,
      employee: employee ?? this.employee,
      error: error,
      offline: offline ?? this.offline,
    );
  }
}

final authControllerProvider =
    StateNotifierProvider<AuthController, AuthState>((ref) {
  return AuthController(ref);
});

class AuthController extends StateNotifier<AuthState> {
  AuthController(this._ref) : super(const AuthState()) {
    restore();
  }

  final Ref _ref;

  Future<void> restore() async {
    final storage = _ref.read(tokenStorageProvider);
    final token = await storage.readAccessToken();
    final refresh = await storage.readRefreshToken();
    final hasCredentials = (token != null && token.isNotEmpty) ||
        (refresh != null && refresh.isNotEmpty);
    if (!hasCredentials) {
      state = const AuthState(status: AuthStatus.unauthenticated);
      return;
    }
    final cached = await _readCachedEmployee();
    if (cached != null) {
      // Open the app immediately from cache; the server check runs after.
      state = AuthState(
        status: AuthStatus.authenticated,
        employee: cached,
        offline: true,
      );
    }
    await _revalidate(cached: cached);
  }

  /// Re-checks the session with the server; keeps the user signed in offline.
  Future<void> revalidate() async {
    if (state.status == AuthStatus.unauthenticated) return;
    await _revalidate(cached: state.employee ?? await _readCachedEmployee());
  }

  Future<void> _revalidate({EmployeeSession? cached}) async {
    try {
      final api = _ref.read(apiClientProvider);
      final res = await api.get('/api/phone/v1/auth/me');
      final emp = EmployeeSession.fromJson(
        Map<String, dynamic>.from(res['employee'] as Map),
      );
      await _cacheEmployee(emp);
      state = AuthState(status: AuthStatus.authenticated, employee: emp);
      _ref.read(syncEngineProvider).flush();
      try {
        await _ref.read(phoneBootstrapProvider.notifier).refresh();
      } catch (_) {}
    } catch (e) {
      if (_isAuthFailure(e)) {
        final storage = _ref.read(tokenStorageProvider);
        await storage.clearTokens();
        await storage.clearSession();
        state = const AuthState(status: AuthStatus.unauthenticated);
        return;
      }
      // Server unreachable or failing: stay signed in with what we know.
      final fallback = cached ?? state.employee;
      state = fallback == null
          ? const AuthState(status: AuthStatus.unauthenticated)
          : AuthState(
              status: AuthStatus.authenticated,
              employee: fallback,
              offline: true,
            );
    }
  }

  /// Only a rejected identity ends the session — never a network problem.
  bool _isAuthFailure(Object error) {
    if (error is! ApiException) return false;
    if (error.code == 'offline') return false;
    const authCodes = {
      'token_invalid',
      'token_expired',
      'device_revoked',
      'session_revoked',
      'unauthorized',
    };
    if (error.code != null && authCodes.contains(error.code)) return true;
    return error.statusCode == 401 || error.statusCode == 403;
  }

  Future<EmployeeSession?> _readCachedEmployee() async {
    try {
      final raw = await _ref.read(tokenStorageProvider).readSessionJson();
      if (raw == null || raw.isEmpty) return null;
      return EmployeeSession.fromJson(
        Map<String, dynamic>.from(jsonDecode(raw) as Map),
      );
    } catch (_) {
      return null;
    }
  }

  Future<void> _cacheEmployee(EmployeeSession emp) async {
    try {
      await _ref
          .read(tokenStorageProvider)
          .saveSessionJson(jsonEncode(emp.toJson()));
    } catch (_) {}
  }

  Future<bool> login({
    required String username,
    required String password,
    String? tenantSlug,
  }) async {
    try {
      final api = _ref.read(apiClientProvider);
      final storage = _ref.read(tokenStorageProvider);
      final slug = (tenantSlug ?? '').trim().toLowerCase();
      if (slug.isNotEmpty) {
        await storage.saveTenantSlug(slug);
      }
      final deviceId = await api.ensureDeviceId();
      final devicePayload = await _buildDevicePayload(deviceId);
      final res = await api.post(
        '/api/phone/v1/auth/login',
        data: {
          'username': username.trim(),
          'password': password,
          'device_id': deviceId,
          ...devicePayload,
          if (slug.isNotEmpty) 'tenant_slug': slug,
        },
      );
      await storage.saveTokens(
        accessToken: res['access_token'] as String,
        refreshToken: res['refresh_token'] as String,
      );
      // Ensure device row exists even if older backend.
      try {
        await api.post(
          '/api/phone/v1/devices/register',
          data: {
            'device_uuid': deviceId,
            ...devicePayload,
          },
        );
      } catch (_) {}
      final emp = EmployeeSession.fromJson(
        Map<String, dynamic>.from(res['employee'] as Map),
      );
      await _cacheEmployee(emp);
      state = AuthState(status: AuthStatus.authenticated, employee: emp);
      try {
        await _ref.read(phoneBootstrapProvider.notifier).refresh();
      } catch (_) {}
      _ref.read(syncEngineProvider).flush();
      return true;
    } on ApiException catch (e) {
      state = AuthState(status: AuthStatus.unauthenticated, error: e.message);
      return false;
    } catch (e) {
      state = AuthState(
        status: AuthStatus.unauthenticated,
        error: e.toString(),
      );
      return false;
    }
  }

  Future<void> logout() async {
    try {
      await _ref.read(apiClientProvider).post('/api/phone/v1/auth/logout');
    } catch (_) {}
    final storage = _ref.read(tokenStorageProvider);
    await storage.clearTokens();
    await storage.clearSession();
    state = const AuthState(status: AuthStatus.unauthenticated);
  }

  Future<Map<String, dynamic>> _buildDevicePayload(String deviceId) async {
    String appVersion = const String.fromEnvironment(
      'APP_VERSION',
      defaultValue: '1.0.3',
    );
    String buildNumber = '';
    try {
      final info = await PackageInfo.fromPlatform();
      appVersion = info.version;
      buildNumber = info.buildNumber;
    } catch (_) {}

    Map<String, dynamic> native = {};
    try {
      native = await _ref.read(permissionsChannelProvider).deviceInfo();
    } catch (_) {}

    final manufacturer = '${native['manufacturer'] ?? ''}'.trim();
    final model = '${native['model'] ?? ''}'.trim();
    final androidVersion = '${native['android_version'] ?? ''}'.trim();
    final deviceName = '${native['device_name'] ?? ''}'.trim().isNotEmpty
        ? '${native['device_name']}'.trim()
        : [manufacturer, model].where((e) => e.isNotEmpty).join(' ').trim();
    final simSlots = native['sim_slots_count'];

    return {
      'device_name':
          deviceName.isNotEmpty ? deviceName : 'Finora Phone',
      'manufacturer': manufacturer.isNotEmpty ? manufacturer : null,
      'model': model.isNotEmpty ? model : null,
      'android_version':
          androidVersion.isNotEmpty ? androidVersion : null,
      'app_version': buildNumber.isEmpty
          ? appVersion
          : '$appVersion+$buildNumber',
      if (simSlots is num) 'sim_slots_count': simSlots.toInt(),
    };
  }
}
