import 'package:finora_social/app/finora_app.dart';
import 'package:finora_social/core/api/api_client.dart';
import 'package:finora_social/core/storage/token_storage.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_test/flutter_test.dart';

class _VisualApiClient extends ApiClient {
  _VisualApiClient() : super(tokenStorage: TokenStorage());

  @override
  Future<Map<String, dynamic>> get(String path) async {
    if (path == '/api/mobile/v1/bootstrap') {
      return {
        'branding': {'app_name': 'Finora'},
        'maintenance': {'enabled': false, 'message': ''},
        'feature_flags': <String, bool>{},
      };
    }
    if (path.startsWith('/api/mobile/v1/feed')) {
      return {'items': <dynamic>[], 'next_cursor': null};
    }
    if (path == '/api/mobile/v1/categories') {
      return {
        'items': [
          {'name': 'شاشات', 'products_count': 12},
          {'name': 'أجهزة منزلية', 'products_count': 8},
          {'name': 'عطور', 'products_count': 5},
        ],
      };
    }
    if (path.startsWith('/api/mobile/v1/products')) {
      return {
        'items': [
          {
            'id': 1,
            'name': 'شاشة ذكية 55 بوصة',
            'price': 589000,
            'old_price': 650000,
            'discount_percent': 9,
            'category': 'شاشات',
            'stock_status': 'متوفر',
            'is_available': true,
          },
          {
            'id': 2,
            'name': 'ثلاجة اقتصادية حديثة',
            'price': 425000,
            'category': 'أجهزة منزلية',
            'stock_status': 'كمية محدودة',
            'is_available': true,
          },
          {
            'id': 3,
            'name': 'عطر فاخر يدوم طويلاً',
            'price': 75000,
            'old_price': 90000,
            'discount_percent': 17,
            'category': 'عطور',
            'stock_status': 'متوفر',
            'is_available': true,
          },
          {
            'id': 4,
            'name': 'مكيف سبليت موفر للطاقة',
            'price': 699000,
            'category': 'أجهزة منزلية',
            'stock_status': 'متوفر',
            'is_available': true,
          },
        ],
        'has_more': false,
        'next_offset': null,
      };
    }
    return <String, dynamic>{};
  }
}

Future<void> _pumpStore(
  WidgetTester tester, {
  required String themeMode,
  required Key boundaryKey,
}) async {
  FlutterSecureStorage.setMockInitialValues({
    'finora_theme_mode': themeMode,
  });
  tester.view
    ..physicalSize = const Size(430, 932)
    ..devicePixelRatio = 1;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);

  await tester.pumpWidget(
    ProviderScope(
      overrides: [
        apiClientProvider.overrideWithValue(_VisualApiClient()),
      ],
      child: RepaintBoundary(
        key: boundaryKey,
        child: const FinoraApp(),
      ),
    ),
  );
  await tester.pumpAndSettle();
  await tester.tap(find.text('المتجر'));
  await tester.pumpAndSettle();
  expect(find.text('متجر Finora'), findsOneWidget);
}

void main() {
  testWidgets('store renders cleanly in light theme', (tester) async {
    const boundaryKey = ValueKey('store-light-smoke');
    await _pumpStore(
      tester,
      themeMode: 'light',
      boundaryKey: boundaryKey,
    );
    expect(find.byKey(boundaryKey), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets('store renders cleanly in dark theme', (tester) async {
    const boundaryKey = ValueKey('store-dark-smoke');
    await _pumpStore(
      tester,
      themeMode: 'dark',
      boundaryKey: boundaryKey,
    );
    expect(find.byKey(boundaryKey), findsOneWidget);
    expect(tester.takeException(), isNull);
  });
}
