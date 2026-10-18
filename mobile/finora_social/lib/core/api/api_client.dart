import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:uuid/uuid.dart';

import '../config/app_config.dart';
import '../errors/api_exception.dart';
import '../storage/token_storage.dart';

final tokenStorageProvider = Provider<TokenStorage>((ref) => TokenStorage());

final deviceIdProvider = FutureProvider<String>((ref) async {
  final storage = ref.watch(tokenStorageProvider);
  final existing = await storage.readDeviceId();
  if (existing != null && existing.isNotEmpty) return existing;
  final id = const Uuid().v4();
  await storage.saveDeviceId(id);
  return id;
});

final apiClientProvider = Provider<ApiClient>((ref) {
  return ApiClient(tokenStorage: ref.watch(tokenStorageProvider));
});

class ApiClient {
  ApiClient({
    required TokenStorage tokenStorage,
    Dio? dio,
  })  : _tokenStorage = tokenStorage,
        _dio = dio ??
            Dio(
              BaseOptions(
                baseUrl: AppConfig.apiBaseUrl,
                connectTimeout: const Duration(seconds: 20),
                receiveTimeout: const Duration(seconds: 20),
                sendTimeout: const Duration(seconds: 20),
                followRedirects: true,
                maxRedirects: 5,
                headers: {
                  'Content-Type': 'application/json',
                  'Accept': 'application/json',
                  'X-Tenant-Slug': AppConfig.tenantSlug,
                },
              ),
            ) {
    _dio.interceptors.add(
      InterceptorsWrapper(
        onRequest: (options, handler) async {
          final token = await _tokenStorage.readAccessToken();
          if (token != null && token.isNotEmpty) {
            options.headers['Authorization'] = 'Bearer $token';
          }
          handler.next(options);
        },
        onError: (error, handler) async {
          if (error.response?.statusCode == 401) {
            final refreshed = await _tryRefresh();
            if (refreshed) {
              final req = error.requestOptions;
              final token = await _tokenStorage.readAccessToken();
              req.headers['Authorization'] = 'Bearer $token';
              try {
                final response = await _dio.fetch(req);
                return handler.resolve(response);
              } catch (_) {}
            }
          }
          handler.next(error);
        },
      ),
    );
  }

  final Dio _dio;
  final TokenStorage _tokenStorage;
  bool _refreshing = false;

  Future<bool> _tryRefresh() async {
    if (_refreshing) return false;
    _refreshing = true;
    try {
      final refresh = await _tokenStorage.readRefreshToken();
      if (refresh == null || refresh.isEmpty) return false;
      final response = await _dio.post(
        '/api/mobile/v1/auth/refresh',
        data: {'refresh_token': refresh},
      );
      final data = response.data as Map<String, dynamic>;
      if (data['ok'] != true) return false;
      await _tokenStorage.saveTokens(
        accessToken: data['access_token'] as String,
        refreshToken: data['refresh_token'] as String,
      );
      return true;
    } catch (_) {
      await _tokenStorage.clear();
      return false;
    } finally {
      _refreshing = false;
    }
  }

  Future<Map<String, dynamic>> get(String path) async {
    try {
      final response = await _dio.get(path);
      return _unwrap(response.data);
    } on DioException catch (e) {
      throw _mapError(e);
    }
  }

  Future<Map<String, dynamic>> post(
    String path, {
    Map<String, dynamic>? data,
  }) async {
    try {
      final response = await _dio.post(path, data: data);
      return _unwrap(response.data);
    } on DioException catch (e) {
      throw _mapError(e);
    }
  }

  Future<Map<String, dynamic>> patch(
    String path, {
    Map<String, dynamic>? data,
  }) async {
    try {
      final response = await _dio.patch(path, data: data);
      return _unwrap(response.data);
    } on DioException catch (e) {
      throw _mapError(e);
    }
  }

  Future<Map<String, dynamic>> delete(String path) async {
    try {
      final response = await _dio.delete(path);
      return _unwrap(response.data);
    } on DioException catch (e) {
      throw _mapError(e);
    }
  }

  Future<Map<String, dynamic>> deleteLike(int videoId) =>
      delete('/api/mobile/v1/videos/$videoId/like');

  Future<Map<String, dynamic>> deleteSave(int videoId) =>
      delete('/api/mobile/v1/videos/$videoId/save');

  Map<String, dynamic> _unwrap(dynamic raw) {
    if (raw is! Map<String, dynamic>) {
      throw ApiException('الخادم أرسل استجابة غير صالحة. حاول مرة أخرى.');
    }
    if (raw['ok'] == false) {
      throw ApiException(
        (raw['error'] as String?) ?? 'تعذر تنفيذ الطلب',
        code: raw['code'] as String?,
      );
    }
    return raw;
  }

  ApiException _mapError(DioException e) {
    final data = e.response?.data;
    if (data is Map && data['error'] is String) {
      final code = data['code'] as String?;
      final friendly = switch (code) {
        'tenant_required' => 'إعداد المتجر غير مكتمل في هذه النسخة.',
        'tenant_not_found' => 'المتجر المرتبط بالتطبيق غير موجود.',
        'schema_error' => 'الخدمة تُحدّث حالياً. حاول بعد قليل.',
        'unauthorized' ||
        'token_invalid' ||
        'session_revoked' =>
          'سجّل الدخول للمتابعة.',
        _ => data['error'] as String,
      };
      return ApiException(
        friendly,
        statusCode: e.response?.statusCode,
        code: code,
      );
    }
    if (e.type == DioExceptionType.connectionTimeout ||
        e.type == DioExceptionType.receiveTimeout) {
      return ApiException('انتهت مهلة الاتصال بالخادم');
    }
    if (e.type == DioExceptionType.connectionError) {
      return ApiException(
        'تعذر الوصول إلى الخادم. تأكد من الإنترنت ثم اضغط إعادة المحاولة.',
      );
    }
    if (e.type == DioExceptionType.badCertificate) {
      return ApiException('تعذر التحقق من أمان اتصال الخادم.');
    }
    if (e.type == DioExceptionType.cancel) {
      return ApiException('تم إلغاء الطلب.');
    }
    final status = e.response?.statusCode;
    if (status != null && status >= 500) {
      return ApiException('الخادم غير متاح مؤقتاً. حاول بعد قليل.',
          statusCode: status);
    }
    return ApiException('تعذر تحميل البيانات. حاول مرة أخرى.',
        statusCode: status);
  }
}
