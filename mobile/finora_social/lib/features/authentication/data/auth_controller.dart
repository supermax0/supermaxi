import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api/api_client.dart';
import '../../../core/errors/api_exception.dart';
import '../../../core/storage/token_storage.dart';

class MobileUser {
  MobileUser({
    required this.id,
    required this.phone,
    required this.name,
    this.email,
    this.customerId,
  });

  factory MobileUser.fromJson(Map<String, dynamic> json) {
    return MobileUser(
      id: json['id'] as int,
      phone: (json['phone'] as String?) ?? '',
      name: (json['name'] as String?) ?? '',
      email: json['email'] as String?,
      customerId: json['customer_id'] as int?,
    );
  }

  final int id;
  final String phone;
  final String name;
  final String? email;
  final int? customerId;
}

class AuthState {
  const AuthState({
    this.user,
    this.isLoading = false,
    this.error,
    this.otpPhone,
  });

  final MobileUser? user;
  final bool isLoading;
  final String? error;
  final String? otpPhone;

  bool get isAuthenticated => user != null;

  AuthState copyWith({
    MobileUser? user,
    bool? isLoading,
    String? error,
    String? otpPhone,
    bool clearUser = false,
    bool clearError = false,
  }) {
    return AuthState(
      user: clearUser ? null : (user ?? this.user),
      isLoading: isLoading ?? this.isLoading,
      error: clearError ? null : (error ?? this.error),
      otpPhone: otpPhone ?? this.otpPhone,
    );
  }
}

class AuthController extends StateNotifier<AuthState> {
  AuthController(this._api, this._storage) : super(const AuthState()) {
    _restore();
  }

  final ApiClient _api;
  final TokenStorage _storage;

  Future<void> _restore() async {
    final access = await _storage.readAccessToken();
    if (access == null || access.isEmpty) return;
    state = state.copyWith(isLoading: true, clearError: true);
    try {
      final data = await _api.get('/api/mobile/v1/auth/me');
      final user = MobileUser.fromJson(data['user'] as Map<String, dynamic>);
      state = state.copyWith(user: user, isLoading: false);
    } catch (_) {
      await _storage.clear();
      state = state.copyWith(clearUser: true, isLoading: false);
    }
  }

  Future<bool> requestOtp(String phone) async {
    state = state.copyWith(isLoading: true, clearError: true, otpPhone: phone);
    try {
      await _api
          .post('/api/mobile/v1/auth/request-otp', data: {'phone': phone});
      state = state.copyWith(isLoading: false);
      return true;
    } on ApiException catch (e) {
      state = state.copyWith(isLoading: false, error: e.message);
      return false;
    }
  }

  Future<bool> loginWithPhone({
    required String phone,
    required String deviceId,
  }) async {
    state = state.copyWith(isLoading: true, clearError: true, otpPhone: phone);
    try {
      final data = await _api.post(
        '/api/mobile/v1/auth/phone-login',
        data: {
          'phone': phone,
          'device_id': deviceId,
          'platform': 'flutter',
          'app_version': '1.0.0',
        },
      );
      await _storage.saveTokens(
        accessToken: data['access_token'] as String,
        refreshToken: data['refresh_token'] as String,
      );
      final user = MobileUser.fromJson(data['user'] as Map<String, dynamic>);
      state = state.copyWith(user: user, isLoading: false);
      return true;
    } on ApiException catch (e) {
      state = state.copyWith(isLoading: false, error: e.message);
      return false;
    }
  }

  Future<bool> verifyOtp({
    required String phone,
    required String code,
    required String deviceId,
    String? name,
  }) async {
    state = state.copyWith(isLoading: true, clearError: true);
    try {
      final data = await _api.post(
        '/api/mobile/v1/auth/verify-otp',
        data: {
          'phone': phone,
          'code': code,
          'device_id': deviceId,
          'name': name ?? '',
          'platform': 'flutter',
        },
      );
      await _storage.saveTokens(
        accessToken: data['access_token'] as String,
        refreshToken: data['refresh_token'] as String,
      );
      final user = MobileUser.fromJson(data['user'] as Map<String, dynamic>);
      state = state.copyWith(user: user, isLoading: false);
      try {
        await _api.post(
          '/api/mobile/v1/devices/register',
          data: {
            'device_id': deviceId,
            'platform': 'flutter',
            'app_version': '1.0.0',
          },
        );
      } catch (_) {
        // Non-blocking device registration.
      }
      return true;
    } on ApiException catch (e) {
      state = state.copyWith(isLoading: false, error: e.message);
      return false;
    }
  }

  Future<void> logout() async {
    try {
      final refresh = await _storage.readRefreshToken();
      await _api.post(
        '/api/mobile/v1/auth/logout',
        data: {'refresh_token': refresh},
      );
    } catch (_) {
      // Always clear local session.
    }
    await _storage.clear();
    state = const AuthState();
  }

  void applyUser(MobileUser user) {
    state = state.copyWith(user: user, clearError: true);
  }
}

final authControllerProvider =
    StateNotifierProvider<AuthController, AuthState>((ref) {
  return AuthController(
    ref.watch(apiClientProvider),
    ref.watch(tokenStorageProvider),
  );
});
