import 'package:dio/dio.dart';
import 'package:uuid/uuid.dart';

import '../config/app_config.dart';
import '../errors/api_exception.dart';
import '../storage/token_storage.dart';

class ApiClient {
  ApiClient({required TokenStorage tokenStorage, Dio? dio})
      : _tokenStorage = tokenStorage,
        _dio = dio ??
            Dio(
              BaseOptions(
                baseUrl: AppConfig.apiBaseUrl,
                connectTimeout: const Duration(seconds: 20),
                receiveTimeout: const Duration(seconds: 30),
                headers: {
                  'Accept': 'application/json',
                  'Content-Type': 'application/json',
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
          final savedTenant = await _tokenStorage.readTenantSlug();
          final tenant = (savedTenant != null && savedTenant.isNotEmpty)
              ? savedTenant
              : AppConfig.tenantSlug;
          options.headers['X-Tenant-Slug'] = tenant;
          handler.next(options);
        },
        onError: (error, handler) async {
          if (error.response?.statusCode == 401 &&
              !(error.requestOptions.extra['retried'] == true)) {
            final refreshed = await _tryRefresh();
            if (refreshed) {
              final req = error.requestOptions;
              req.extra['retried'] = true;
              final token = await _tokenStorage.readAccessToken();
              req.headers['Authorization'] = 'Bearer $token';
              try {
                final response = await _dio.fetch(req);
                return handler.resolve(response);
              } catch (e) {
                return handler.next(error);
              }
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

  Dio get dio => _dio;

  Future<String> ensureDeviceId() async {
    var id = await _tokenStorage.readDeviceId();
    if (id == null || id.isEmpty) {
      id = const Uuid().v4();
      await _tokenStorage.saveDeviceId(id);
    }
    return id;
  }

  Future<bool> _tryRefresh() async {
    if (_refreshing) return false;
    _refreshing = true;
    try {
      final refresh = await _tokenStorage.readRefreshToken();
      if (refresh == null || refresh.isEmpty) return false;
      final deviceId = await ensureDeviceId();
      final savedTenant = await _tokenStorage.readTenantSlug();
      final tenant = (savedTenant != null && savedTenant.isNotEmpty)
          ? savedTenant
          : AppConfig.tenantSlug;
      final res = await Dio(
        BaseOptions(
          baseUrl: AppConfig.apiBaseUrl,
          connectTimeout: const Duration(seconds: 20),
          receiveTimeout: const Duration(seconds: 30),
          headers: {
            'Accept': 'application/json',
            'Content-Type': 'application/json',
            'X-Tenant-Slug': tenant,
          },
        ),
      ).post(
        '/api/phone/v1/auth/refresh',
        data: {'refresh_token': refresh, 'device_id': deviceId},
      );
      final data = res.data;
      if (data is Map && data['ok'] == true) {
        await _tokenStorage.saveTokens(
          accessToken: data['access_token'] as String,
          refreshToken: data['refresh_token'] as String,
        );
        return true;
      }
      return false;
    } catch (_) {
      return false;
    } finally {
      _refreshing = false;
    }
  }

  Future<Map<String, dynamic>> post(
    String path, {
    Object? data,
    Map<String, dynamic>? extraHeaders,
  }) async {
    try {
      final res = await _dio.post(
        path,
        data: data,
        options: extraHeaders == null
            ? null
            : Options(headers: extraHeaders),
      );
      return _unwrap(res.data);
    } on DioException catch (e) {
      final err = _mapError(e);
      await _tokenStorage.setLastApiError(err.message);
      throw err;
    }
  }

  Future<Map<String, dynamic>> patch(
    String path, {
    Object? data,
    Map<String, dynamic>? extraHeaders,
  }) async {
    try {
      final res = await _dio.patch(
        path,
        data: data,
        options: extraHeaders == null
            ? null
            : Options(headers: extraHeaders),
      );
      return _unwrap(res.data);
    } on DioException catch (e) {
      final err = _mapError(e);
      await _tokenStorage.setLastApiError(err.message);
      throw err;
    }
  }

  /// Uploads a file with optional form fields (e.g. call recordings).
  Future<Map<String, dynamic>> postMultipart(
    String path, {
    required String filePath,
    String fileField = 'file',
    Map<String, dynamic>? fields,
    Map<String, dynamic>? extraHeaders,
  }) async {
    try {
      final form = FormData.fromMap({
        ...?fields,
        fileField: await MultipartFile.fromFile(filePath),
      });
      final res = await _dio.post(
        path,
        data: form,
        options: Options(
          headers: extraHeaders,
          contentType: 'multipart/form-data',
          sendTimeout: const Duration(minutes: 5),
          receiveTimeout: const Duration(minutes: 2),
        ),
      );
      return _unwrap(res.data);
    } on DioException catch (e) {
      final err = _mapError(e);
      await _tokenStorage.setLastApiError(err.message);
      throw err;
    }
  }

  Future<Map<String, dynamic>> get(String path,
      {Map<String, dynamic>? query}) async {
    try {
      final res = await _dio.get(path, queryParameters: query);
      return _unwrap(res.data);
    } on DioException catch (e) {
      final err = _mapError(e);
      await _tokenStorage.setLastApiError(err.message);
      throw err;
    }
  }

  Map<String, dynamic> _unwrap(dynamic data) {
    if (data is! Map) {
      throw ApiException('استجابة غير صالحة من الخادم');
    }
    final map = Map<String, dynamic>.from(data);
    if (map['ok'] == false) {
      throw ApiException(
        (map['error'] as String?) ?? 'حدث خطأ',
        code: map['code'] as String?,
      );
    }
    return map;
  }

  ApiException _mapError(DioException e) {
    final data = e.response?.data;
    if (data is Map && data['error'] != null) {
      return ApiException(
        data['error'].toString(),
        code: data['code']?.toString(),
        statusCode: e.response?.statusCode,
      );
    }
    // No response at all means the server was unreachable, not an auth problem.
    if (e.response == null) {
      return ApiException('لا يوجد اتصال بالإنترنت', code: 'offline');
    }
    return ApiException('فشل الاتصال بالخادم', statusCode: e.response?.statusCode);
  }
}
