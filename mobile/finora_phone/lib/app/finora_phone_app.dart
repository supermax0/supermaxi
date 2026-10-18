import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:package_info_plus/package_info_plus.dart';

import '../core/bootstrap/phone_bootstrap.dart';
import '../core/config/app_config.dart';
import '../core/di/providers.dart';
import '../core/theme/app_theme.dart';
import '../core/theme/theme_controller.dart';
import '../features/auth/data/app_lock_controller.dart';
import '../features/overlay/data/active_call_controller.dart';
import 'router.dart';

class FinoraPhoneApp extends ConsumerStatefulWidget {
  const FinoraPhoneApp({super.key});

  @override
  ConsumerState<FinoraPhoneApp> createState() => _FinoraPhoneAppState();
}

class _FinoraPhoneAppState extends ConsumerState<FinoraPhoneApp>
    with WidgetsBindingObserver {
  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    WidgetsBinding.instance.addPostFrameCallback((_) async {
      await _applySecureFlag();
      await _consumeLaunchAction();
    });
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.paused) {
      // Soft lock when leaving app — telephony unaffected.
      ref.read(appLockProvider.notifier).lockIfEnabled();
    }
    if (state == AppLifecycleState.resumed) {
      _consumeLaunchAction();
    }
  }

  Future<void> _applySecureFlag() async {
    final block = await ref.read(tokenStorageProvider).isBlockScreenshots();
    await ref.read(permissionsChannelProvider).setBlockScreenshots(block);
  }

  Future<void> _consumeLaunchAction() async {
    final payload =
        await ref.read(overlayChannelProvider).consumePendingLaunch();
    final action = payload['action'];
    if (!mounted || action == null || action.isEmpty) return;
    final number = payload['number'];
    final uuid = payload['local_call_uuid'];
    if (number != null && number.trim().isNotEmpty) {
      await ref.read(activeCallProvider.notifier).hydrateFromLaunch(
            number: number,
            localCallUuid: uuid,
            showAfterCall: action == 'after-call',
          );
    }
    // Unlock for call workflow.
    ref.read(appLockProvider.notifier).unlock();
    final router = ref.read(goRouterProvider);
    if (action == 'tools') {
      router.push('/tools');
    } else if (action == 'note' || action == 'task') {
      router.push('/tools?focus=$action');
    } else if (action == 'after-call') {
      router.push('/after-call');
    }
  }

  @override
  Widget build(BuildContext context) {
    ref.watch(callBootstrapProvider);
    final router = ref.watch(goRouterProvider);
    final themeMode = ref.watch(themeModeProvider);

    ref.listen(activeCallProvider, (prev, next) {
      if (next.showAfterCall && prev?.showAfterCall != true) {
        ref.read(appLockProvider.notifier).unlock();
        router.push('/after-call');
      }
    });

    return MaterialApp.router(
      title: 'Finora Phone',
      debugShowCheckedModeBanner: false,
      theme: AppTheme.light,
      darkTheme: AppTheme.dark,
      themeMode: themeMode,
      locale: const Locale('ar'),
      builder: (context, child) {
        return Directionality(
          textDirection: TextDirection.rtl,
          child: child ?? const SizedBox.shrink(),
        );
      },
      routerConfig: router,
    );
  }
}

Future<PackageInfo?> loadPackageInfo() async {
  try {
    return await PackageInfo.fromPlatform();
  } catch (_) {
    return null;
  }
}

String appFlavorLabel() {
  final flavor =
      const String.fromEnvironment('FLAVOR', defaultValue: 'development');
  if (flavor == 'staging' || flavor == 'fieldtest') {
    return 'Field Test';
  }
  if (flavor == 'production') return 'Production';
  return flavor;
}

String appApiHost() => AppConfig.apiBaseUrl;

PhoneBootstrapSettings readBootstrap(WidgetRef ref) =>
    ref.watch(phoneBootstrapProvider);
