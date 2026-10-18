import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../core/di/providers.dart';
import '../../../core/theme/app_colors.dart';
import '../../../core/ui/finora_ui.dart';
import '../../auth/data/permissions_gate.dart';

class PermissionsWizardPage extends ConsumerStatefulWidget {
  const PermissionsWizardPage({super.key});

  @override
  ConsumerState<PermissionsWizardPage> createState() =>
      _PermissionsWizardPageState();
}

class _PermissionsWizardPageState extends ConsumerState<PermissionsWizardPage>
    with WidgetsBindingObserver {
  Map<String, bool> _status = {};
  bool _loading = false;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    _refresh();
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.resumed) {
      _refresh();
    }
  }

  Future<void> _refresh() async {
    final s = await ref.read(permissionsChannelProvider).status();
    if (mounted) setState(() => _status = s);
  }

  bool get _criticalOk =>
      _status['phone'] == true &&
      _status['callLog'] == true &&
      _status['overlay'] == true;

  Future<void> _done({required bool limited}) async {
    if (!limited && !_criticalOk) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text('امنح صلاحيات الهاتف وسجل المكالمات والنافذة العائمة أولاً'),
        ),
      );
      return;
    }
    if (limited) {
      final ok = await showDialog<bool>(
        context: context,
        builder: (ctx) => AlertDialog(
          title: const Text('وضع محدود؟'),
          content: const Text(
            'بدون الصلاحيات الحرجة قد تفوت أحداث مكالمات ويتعطل الـ Overlay. يمكنك العودة لاحقاً من الإعدادات.',
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(ctx, false),
              child: const Text('رجوع'),
            ),
            FilledButton(
              onPressed: () => Navigator.pop(ctx, true),
              child: const Text('متابعة محدود'),
            ),
          ],
        ),
      );
      if (ok != true) return;
    }
    await ref.read(permissionsGateProvider.notifier).markDone();
    if (mounted) context.go('/phone');
  }

  @override
  Widget build(BuildContext context) {
    final steps = [
      (
        'حالة الهاتف',
        'لاستقبال أحداث المكالمات دون التدخل في الرد/الرفض',
        'phone',
        () => ref.read(permissionsChannelProvider).requestPhone(),
        true,
      ),
      (
        'سجل المكالمات',
        'ضروري لإظهار رقم المتصل ولاستعادة المكالمات الفائتة',
        'callLog',
        () => ref.read(permissionsChannelProvider).requestCallLog(),
        true,
      ),
      (
        'النافذة العائمة',
        'لعرض بطاقة الزبون فوق شاشة الاتصال الأصلية',
        'overlay',
        () => ref.read(permissionsChannelProvider).requestOverlay(),
        true,
      ),
      (
        'الإشعارات',
        'لتنبيهات المكالمات الفائتة ومهام المتابعة',
        'notifications',
        () => ref.read(permissionsChannelProvider).requestNotifications(),
        false,
      ),
      (
        'ملفات الصوت',
        'لرفع تسجيلات المكالمات من مسجّل النظام وربطها بالزبون',
        'mediaAudio',
        () => ref.read(permissionsChannelProvider).requestMediaAudio(),
        false,
      ),
      (
        'تحسين البطارية',
        'افتح الإعدادات واستثنِ Finora من إيقاف البطارية (OEM)',
        'battery',
        () => ref.read(permissionsChannelProvider).requestBatteryOptimization(),
        false,
      ),
    ];

    return FinoraScaffold(
      appBar: AppBar(title: const Text('أذونات Finora Phone')),
      body: SafeArea(
        child: ListView(
          padding: const EdgeInsets.fromLTRB(20, 56, 20, 28),
          children: [
            const FinoraBrandMark(compact: true),
            const SizedBox(height: 16),
            Text(
              'التطبيق Companion — الرد والرفض يبقيان في هاتف النظام. Finora يعرض معلومات الزبون فقط.',
              style: Theme.of(context).textTheme.bodyMedium,
              textAlign: TextAlign.center,
            ),
            const SizedBox(height: 20),
            ...steps.map((s) {
              final key = s.$3;
              final granted = key == 'battery' ? false : _status[key] == true;
              final critical = s.$5;
              return Padding(
                padding: const EdgeInsets.only(bottom: 10),
                child: FinoraSurface(
                  padding: const EdgeInsets.symmetric(
                    horizontal: 8,
                    vertical: 4,
                  ),
                  child: ListTile(
                    title: Text('${s.$1}${critical ? ' *' : ''}'),
                    subtitle: Text(s.$2),
                    trailing: granted
                        ? const Icon(Icons.check_circle_rounded,
                            color: AppColors.success)
                        : FilledButton(
                            onPressed: _loading
                                ? null
                                : () async {
                                    setState(() => _loading = true);
                                    await s.$4();
                                    await Future<void>.delayed(
                                      const Duration(milliseconds: 400),
                                    );
                                    await _refresh();
                                    if (mounted) {
                                      setState(() => _loading = false);
                                    }
                                  },
                            child: Text(key == 'battery' ? 'فتح' : 'منح'),
                          ),
                  ),
                ),
              );
            }),
            Text(
              '* صلاحيات حرجة للاختبار الميداني',
              style: Theme.of(context).textTheme.bodySmall,
            ),
            const SizedBox(height: 14),
            FilledButton(
              onPressed: () => _done(limited: false),
              child: const Text('متابعة'),
            ),
            TextButton(
              onPressed: () => _done(limited: true),
              child: const Text('تخطي الآن (وضع محدود)'),
            ),
          ],
        ),
      ),
    );
  }
}
