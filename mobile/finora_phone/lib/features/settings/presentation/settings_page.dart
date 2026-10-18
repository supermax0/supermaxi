import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:local_auth/local_auth.dart';
import 'package:package_info_plus/package_info_plus.dart';

import '../../../app/finora_phone_app.dart';
import '../../../core/bootstrap/phone_bootstrap.dart';
import '../../../core/config/app_config.dart';
import '../../../core/di/providers.dart';
import '../../../core/theme/app_colors.dart';
import '../../../core/theme/theme_controller.dart';
import '../../../core/ui/finora_ui.dart';
import '../../auth/data/app_lock_controller.dart';
import '../../auth/data/auth_controller.dart';
import '../../overlay/data/active_call_controller.dart';
import 'diagnostics_page.dart';
import 'outbox_failed_page.dart';

class SettingsPage extends ConsumerStatefulWidget {
  const SettingsPage({super.key});

  @override
  ConsumerState<SettingsPage> createState() => _SettingsPageState();
}

class _SettingsPageState extends ConsumerState<SettingsPage> {
  bool _bio = false;
  bool _blockScreenshots = true;
  final _pinCtrl = TextEditingController();
  PackageInfo? _info;
  int _permanentFailed = 0;
  bool _forceStop = false;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    final storage = ref.read(tokenStorageProvider);
    _bio = await storage.isBiometricEnabled();
    _blockScreenshots = await storage.isBlockScreenshots();
    _info = await loadPackageInfo();
    final counts = await ref.read(localDatabaseProvider).outboxCounts();
    _permanentFailed = counts['permanently_failed'] ?? 0;
    final health = ref.read(serviceHealthProvider);
    await health.load();
    _forceStop = health.forceStopSuspected;
    if (mounted) setState(() {});
  }

  @override
  void dispose() {
    _pinCtrl.dispose();
    super.dispose();
  }

  Widget _group(String title, List<Widget> children) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 14),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          FinoraSectionHeader(title),
          FinoraSurface(
            padding: const EdgeInsets.symmetric(vertical: 4),
            child: Column(children: children),
          ),
        ],
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final auth = ref.watch(authControllerProvider);
    final theme = ref.watch(themeModeProvider);
    final boot = ref.watch(phoneBootstrapProvider);
    return FinoraScaffold(
      appBar: AppBar(title: const Text('الإعدادات')),
      body: SafeArea(
        child: ListView(
          padding: const EdgeInsets.fromLTRB(16, 56, 16, 110),
          children: [
            if (_forceStop)
              Padding(
                padding: const EdgeInsets.only(bottom: 12),
                child: FinoraSurface(
                  padding: const EdgeInsets.all(14),
                  child: Row(
                    children: [
                      const Icon(Icons.warning_amber_rounded,
                          color: AppColors.warning),
                      const SizedBox(width: 10),
                      const Expanded(
                        child: Text(
                          'يُشتبه بـ Force Stop — لن تُستقبل أحداث المكالمات حتى يُفتح التطبيق يدوياً.',
                        ),
                      ),
                      TextButton(
                        onPressed: () async {
                          await ref
                              .read(serviceHealthProvider)
                              .clearForceStopFlag();
                          setState(() => _forceStop = false);
                        },
                        child: const Text('حسناً'),
                      ),
                    ],
                  ),
                ),
              ),
            FinoraSurface(
              padding: const EdgeInsets.all(16),
              child: Row(
                children: [
                  FinoraAvatar(
                    label: auth.employee?.name ?? 'F',
                    size: 54,
                    highlighted: true,
                  ),
                  const SizedBox(width: 14),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          auth.employee?.name ?? '—',
                          style: Theme.of(context).textTheme.headlineSmall,
                        ),
                        Text(
                          '${boot.companyName ?? AppConfig.tenantSlug} · ${appFlavorLabel()}',
                          style: Theme.of(context).textTheme.bodyMedium,
                        ),
                        Text(
                          'v${_info?.version ?? "—"}+${_info?.buildNumber ?? "—"}',
                          style: Theme.of(context).textTheme.bodySmall,
                        ),
                      ],
                    ),
                  ),
                ],
              ),
            ),
            const SizedBox(height: 16),
            _group('العام', [
              ListTile(
                title: const Text('لوحة اليوم'),
                leading: const Icon(Icons.dashboard_outlined),
                onTap: () => context.push('/dashboard'),
              ),
              ListTile(
                title: const Text('زمن متابعة الفائتة'),
                subtitle: Text('${boot.missedCallFollowupMinutes} دقيقة'),
                leading: const Icon(Icons.timer_outlined),
                onTap: () async {
                  final options = [5, 15, 30];
                  final picked = await showModalBottomSheet<int>(
                    context: context,
                    useRootNavigator: true,
                    builder: (ctx) => SafeArea(
                      child: Column(
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          for (final m in options)
                            ListTile(
                              title: Text('$m دقيقة'),
                              trailing: m == boot.missedCallFollowupMinutes
                                  ? const Icon(Icons.check,
                                      color: AppColors.goldAccent)
                                  : null,
                              onTap: () => Navigator.pop(ctx, m),
                            ),
                        ],
                      ),
                    ),
                  );
                  if (picked != null) {
                    await ref
                        .read(phoneBootstrapProvider.notifier)
                        .setFollowupMinutes(picked);
                  }
                },
              ),
              ListTile(
                title: const Text('المظهر'),
                subtitle: Text(switch (theme) {
                  ThemeMode.system => 'نظام',
                  ThemeMode.light => 'فاتح',
                  ThemeMode.dark => 'داكن',
                }),
                leading: const Icon(Icons.brightness_6_outlined),
                onTap: () async {
                  final next = switch (theme) {
                    ThemeMode.system => ThemeMode.light,
                    ThemeMode.light => ThemeMode.dark,
                    ThemeMode.dark => ThemeMode.system,
                  };
                  await ref.read(themeModeProvider.notifier).setMode(next);
                },
              ),
              SwitchListTile(
                title: const Text('منع لقطات الشاشة'),
                secondary: const Icon(Icons.screenshot_monitor_outlined),
                value: _blockScreenshots,
                onChanged: (v) async {
                  await ref.read(tokenStorageProvider).setBlockScreenshots(v);
                  await ref
                      .read(permissionsChannelProvider)
                      .setBlockScreenshots(v);
                  setState(() => _blockScreenshots = v);
                },
              ),
              SwitchListTile(
                title: const Text('قفل بيومتري'),
                secondary: const Icon(Icons.fingerprint),
                value: _bio,
                onChanged: (v) async {
                  if (v) {
                    final ok = await LocalAuthentication().authenticate(
                      localizedReason: 'تفعيل قفل Finora Phone',
                    );
                    if (!ok) return;
                  }
                  await ref.read(tokenStorageProvider).setBiometricEnabled(v);
                  setState(() => _bio = v);
                  await ref.read(appLockProvider.notifier).reevaluateAndLock();
                  ref.read(appLockProvider.notifier).unlock();
                },
              ),
              ListTile(
                title: const Text('تعيين PIN'),
                subtitle: const Text('اختياري — يقفل التطبيق عند الخروج'),
                leading: const Icon(Icons.pin_outlined),
                onTap: () async {
                  final ok = await showDialog<bool>(
                    context: context,
                    builder: (ctx) => AlertDialog(
                      title: const Text('PIN'),
                      content: TextField(
                        controller: _pinCtrl,
                        keyboardType: TextInputType.number,
                        obscureText: true,
                        maxLength: 6,
                        decoration:
                            const InputDecoration(hintText: '4-6 أرقام'),
                      ),
                      actions: [
                        TextButton(
                          onPressed: () => Navigator.pop(ctx, false),
                          child: const Text('إلغاء'),
                        ),
                        TextButton(
                          onPressed: () async {
                            await ref.read(tokenStorageProvider).setPin(null);
                            if (ctx.mounted) Navigator.pop(ctx, false);
                            await ref
                                .read(appLockProvider.notifier)
                                .reevaluateAndLock();
                            ref.read(appLockProvider.notifier).unlock();
                          },
                          child: const Text('مسح'),
                        ),
                        FilledButton(
                          onPressed: () => Navigator.pop(ctx, true),
                          child: const Text('حفظ'),
                        ),
                      ],
                    ),
                  );
                  if (ok == true) {
                    final pin = _pinCtrl.text.trim();
                    if (pin.isNotEmpty && (pin.length < 4 || pin.length > 6)) {
                      if (mounted) {
                        ScaffoldMessenger.of(context).showSnackBar(
                          const SnackBar(
                            content: Text('الـ PIN يجب أن يكون 4 إلى 6 أرقام'),
                          ),
                        );
                      }
                      return;
                    }
                    if (pin.isNotEmpty && !RegExp(r'^\d+$').hasMatch(pin)) {
                      if (mounted) {
                        ScaffoldMessenger.of(context).showSnackBar(
                          const SnackBar(content: Text('الـ PIN أرقام فقط')),
                        );
                      }
                      return;
                    }
                    await ref
                        .read(tokenStorageProvider)
                        .setPin(pin.isEmpty ? null : pin);
                    await ref
                        .read(appLockProvider.notifier)
                        .reevaluateAndLock();
                    ref.read(appLockProvider.notifier).unlock();
                  }
                },
              ),
            ]),
            _group('العمل', [
              ListTile(
                title: const Text('بحث متقدم'),
                leading: const Icon(Icons.manage_search_rounded),
                onTap: () => context.push('/search'),
              ),
              ListTile(
                title: const Text('مكالمات غير مصنّفة'),
                leading: const Icon(Icons.label_off_outlined),
                onTap: () => context.push('/unclassified-calls'),
              ),
              ListTile(
                title: const Text('مسودات الطلبات'),
                leading: const Icon(Icons.drafts_outlined),
                subtitle: const Text('مراجعة وتأكيد قبل القيد النهائي'),
                onTap: () => context.push('/order-drafts'),
              ),
              ListTile(
                title: const Text('مزامنة الآن'),
                leading: const Icon(Icons.cloud_sync_rounded),
                onTap: () async {
                  await ref.read(syncEngineProvider).flush();
                  await _load();
                  if (context.mounted) {
                    ScaffoldMessenger.of(context).showSnackBar(
                      const SnackBar(content: Text('تمت محاولة المزامنة')),
                    );
                  }
                },
              ),
              ListTile(
                title: const Text('عمليات فاشلة نهائياً'),
                leading: const Icon(Icons.error_outline_rounded),
                subtitle: Text(
                  _permanentFailed == 0
                      ? 'لا يوجد'
                      : '$_permanentFailed بانتظار إعادة المحاولة',
                ),
                trailing: _permanentFailed > 0
                    ? Badge(label: Text('$_permanentFailed'))
                    : null,
                onTap: () async {
                  await Navigator.of(context).push(
                    MaterialPageRoute(
                      builder: (_) => const OutboxFailedPage(),
                    ),
                  );
                  await _load();
                },
              ),
              ListTile(
                title: const Text('معالج الأذونات'),
                leading: const Icon(Icons.security_rounded),
                onTap: () => context.go('/permissions'),
              ),
              ListTile(
                title: const Text('Diagnostics'),
                leading: const Icon(Icons.bug_report_outlined),
                onTap: () => Navigator.of(context).push(
                  MaterialPageRoute(builder: (_) => const DiagnosticsPage()),
                ),
              ),
            ]),
            FinoraSurface(
              onTap: () => ref.read(authControllerProvider.notifier).logout(),
              padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
              child: const Row(
                children: [
                  Icon(Icons.logout_rounded, color: AppColors.error),
                  SizedBox(width: 12),
                  Text(
                    'تسجيل الخروج',
                    style: TextStyle(
                      color: AppColors.error,
                      fontWeight: FontWeight.w700,
                    ),
                  ),
                ],
              ),
            ),
            const SizedBox(height: 16),
            Text(
              'Phase 1 Companion — التسجيل / AI / الطوابير / التقارير المتقدمة قادمة لاحقاً',
              style: Theme.of(context).textTheme.bodySmall,
              textAlign: TextAlign.center,
            ),
          ],
        ),
      ),
    );
  }
}
