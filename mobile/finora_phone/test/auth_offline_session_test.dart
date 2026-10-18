import 'dart:convert';

import 'package:dio/dio.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:finora_phone/core/api/api_client.dart';
import 'package:finora_phone/core/di/providers.dart';
import 'package:finora_phone/core/storage/token_storage.dart';
import 'package:finora_phone/features/auth/data/auth_controller.dart';

/// Serves canned responses so the session can be restored without a network.
class _FakeAdapter implements HttpClientAdapter {
  _FakeAdapter({this.offline = false, this.statusCode = 200, this.body = '{}'});

  final bool offline;
  final int statusCode;
  final String body;

  @override
  Future<ResponseBody> fetch(
    RequestOptions options,
    Stream<Uint8List>? requestStream,
    Future<void>? cancelFuture,
  ) async {
    if (offline) {
      throw DioException.connectionError(
        requestOptions: options,
        reason: 'no network',
      );
    }
    return ResponseBody.fromString(
      body,
      statusCode,
      headers: {
        Headers.contentTypeHeader: [Headers.jsonContentType],
      },
    );
  }

  @override
  void close({bool force = false}) {}
}

ProviderContainer _containerWith(HttpClientAdapter adapter) {
  final storage = TokenStorage();
  final dio = Dio(BaseOptions(baseUrl: 'https://example.test'))
    ..httpClientAdapter = adapter;
  return ProviderContainer(
    overrides: [
      tokenStorageProvider.overrideWithValue(storage),
      apiClientProvider.overrideWithValue(
        ApiClient(tokenStorage: storage, dio: dio),
      ),
    ],
  );
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  final secureValues = <String, String>{};
  const channel = MethodChannel('plugins.it_nomads.com/flutter_secure_storage');

  setUp(() {
    secureValues.clear();
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(channel, (call) async {
      final args = Map<String, dynamic>.from(call.arguments as Map);
      final key = args['key'] as String?;
      switch (call.method) {
        case 'write':
          secureValues[key!] = args['value'] as String;
          return null;
        case 'read':
          return secureValues[key];
        case 'delete':
          secureValues.remove(key);
          return null;
        case 'readAll':
          return Map<String, String>.from(secureValues);
        case 'deleteAll':
          secureValues.clear();
          return null;
        case 'containsKey':
          return secureValues.containsKey(key);
        default:
          return null;
      }
    });
  });

  tearDown(() {
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(channel, null);
  });

  test('stays signed in from cache when the server is unreachable', () async {
    secureValues['finora_phone_access_token'] = 'access';
    secureValues['finora_phone_refresh_token'] = 'refresh';
    secureValues['finora_phone_employee_session'] = jsonEncode({
      'id': 7,
      'name': 'أحمد',
      'username': 'ahmed',
      'role': 'agent',
      'branch_id': 2,
    });

    final container = _containerWith(_FakeAdapter(offline: true));
    addTearDown(container.dispose);

    await container.read(authControllerProvider.notifier).restore();
    final state = container.read(authControllerProvider);

    expect(state.status, AuthStatus.authenticated);
    expect(state.offline, isTrue);
    expect(state.employee?.name, 'أحمد');
    expect(secureValues['finora_phone_access_token'], 'access');
  });

  test('signs out and clears cache when the server rejects the token',
      () async {
    secureValues['finora_phone_access_token'] = 'expired';
    secureValues['finora_phone_employee_session'] = jsonEncode({
      'id': 7,
      'name': 'أحمد',
      'username': 'ahmed',
      'role': 'agent',
    });

    final container = _containerWith(
      _FakeAdapter(
        statusCode: 401,
        body: jsonEncode({
          'ok': false,
          'code': 'token_invalid',
          'error': 'Invalid or expired access token',
        }),
      ),
    );
    addTearDown(container.dispose);

    await container.read(authControllerProvider.notifier).restore();
    final state = container.read(authControllerProvider);

    expect(state.status, AuthStatus.unauthenticated);
    expect(secureValues.containsKey('finora_phone_access_token'), isFalse);
    expect(secureValues.containsKey('finora_phone_employee_session'), isFalse);
  });

  test('caches the session on a successful check', () async {
    secureValues['finora_phone_access_token'] = 'access';

    final container = _containerWith(
      _FakeAdapter(
        body: jsonEncode({
          'ok': true,
          'employee': {
            'id': 3,
            'name': 'سارة',
            'username': 'sara',
            'role': 'agent',
          },
        }),
      ),
    );
    addTearDown(container.dispose);

    await container.read(authControllerProvider.notifier).restore();

    expect(secureValues['finora_phone_employee_session'], isNotNull);
    expect(
      jsonDecode(secureValues['finora_phone_employee_session']!)['username'],
      'sara',
    );
  });
}
