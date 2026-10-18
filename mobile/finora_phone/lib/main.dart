import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'app/finora_phone_app.dart';
import 'core/config/app_config.dart';
import 'core/logging/phone_logger.dart';
import 'core/storage/token_storage.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  final storage = TokenStorage();
  final crash = LocalCrashReporter(storage: storage);
  final logger = PhoneLogger(storage: storage);

  FlutterError.onError = (details) {
    FlutterError.presentError(details);
    unawaited(crash.recordFlutterError(details.exception, details.stack));
  };
  PlatformDispatcher.instance.onError = (error, stack) {
    unawaited(crash.recordError(error, stack, reason: 'platform'));
    return true;
  };

  final configurationError =
      AppConfig.validationError(releaseMode: kReleaseMode);
  if (configurationError != null) {
    runApp(_ConfigurationErrorApp(message: configurationError));
    return;
  }

  await logger.log('app_started', data: {
    'flavor': const String.fromEnvironment('FLAVOR', defaultValue: 'development'),
  });

  runApp(const ProviderScope(child: FinoraPhoneApp()));
}

class _ConfigurationErrorApp extends StatelessWidget {
  const _ConfigurationErrorApp({required this.message});

  final String message;

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      debugShowCheckedModeBanner: false,
      home: Scaffold(
        body: Center(
          child: Padding(
            padding: const EdgeInsets.all(24),
            child: Text(message, textAlign: TextAlign.center),
          ),
        ),
      ),
    );
  }
}
