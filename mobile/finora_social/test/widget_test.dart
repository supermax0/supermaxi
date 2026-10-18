import 'package:flutter_test/flutter_test.dart';
import 'package:flutter/material.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:finora_social/app/finora_app.dart';
import 'package:finora_social/core/api/api_client.dart';
import 'package:finora_social/core/storage/token_storage.dart';

class _FakeApiClient extends ApiClient {
  _FakeApiClient() : super(tokenStorage: TokenStorage());

  @override
  Future<Map<String, dynamic>> get(String path) async {
    if (path == '/api/mobile/v1/bootstrap') {
      return {
        'ok': true,
        'branding': {'app_name': 'Finora'},
        'maintenance': {'enabled': false, 'message': ''},
        'feature_flags': <String, bool>{},
      };
    }
    return {'ok': true};
  }

  @override
  Future<Map<String, dynamic>> post(
    String path, {
    Map<String, dynamic>? data,
  }) async {
    if (path == '/api/mobile/v1/auth/phone-login') {
      return {
        'ok': true,
        'access_token': 'access',
        'refresh_token': 'refresh',
        'user': {
          'id': 1,
          'phone': data?['phone'] ?? '07700000000',
          'name': '',
        },
      };
    }
    return {'ok': true};
  }
}

void main() {
  testWidgets('Finora app opens guest shell without asking for a phone',
      (tester) async {
    FlutterSecureStorage.setMockInitialValues({});
    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          apiClientProvider.overrideWithValue(_FakeApiClient()),
        ],
        child: const FinoraApp(),
      ),
    );
    await tester.pumpAndSettle();
    expect(find.text('الرئيسية'), findsOneWidget);
    expect(find.text('رقم الهاتف'), findsNothing);
  });

  testWidgets('guest can browse store and is asked to sign in for cart',
      (tester) async {
    FlutterSecureStorage.setMockInitialValues({});
    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          apiClientProvider.overrideWithValue(_FakeApiClient()),
        ],
        child: const FinoraApp(),
      ),
    );
    await tester.pumpAndSettle();

    await tester.tap(find.text('المتجر'));
    await tester.pumpAndSettle();
    expect(find.text('متجر Finora'), findsOneWidget);
    expect(find.text('رقم الهاتف'), findsNothing);

    await tester.tap(find.byIcon(Icons.shopping_cart_outlined));
    await tester.pumpAndSettle();
    expect(find.text('رقم الهاتف'), findsOneWidget);
    expect(find.text('متابعة التصفح كضيف'), findsOneWidget);

    await tester.enterText(find.byType(TextField), '07701234567');
    await tester.tap(find.text('متابعة'));
    await tester.pumpAndSettle();
    expect(find.text('رمز التحقق'), findsNothing);
    expect(find.text('العربة فارغة'), findsOneWidget);
  });
}
