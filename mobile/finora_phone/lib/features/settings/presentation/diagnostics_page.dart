import 'dart:convert';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:package_info_plus/package_info_plus.dart';
import 'package:path_provider/path_provider.dart';
import 'package:share_plus/share_plus.dart';

import '../../../core/config/app_config.dart';
import '../../../core/di/providers.dart';
import '../../../core/theme/app_colors.dart';
import '../../../core/ui/finora_ui.dart';
import '../../../data/mappers/phone_normalize.dart';
import '../../../domain/usecases/call_event_coordinator.dart';
import '../../../domain/usecases/call_state_machine.dart';
import '../../auth/data/auth_controller.dart';
import '../../overlay/data/active_call_controller.dart';

class DiagnosticsPage extends ConsumerStatefulWidget {
  const DiagnosticsPage({super.key});

  @override
  ConsumerState<DiagnosticsPage> createState() => _DiagnosticsPageState();
}

class _DiagnosticsPageState extends ConsumerState<DiagnosticsPage> {
  Map<String, dynamic> _data = {};
  Map<String, dynamic>? _fieldDay;
  bool _loading = true;
  String? _toolResult;

  bool get _showFieldTools {
    final flavor = const String.fromEnvironment('FLAVOR', defaultValue: 'development');
    return flavor == 'development' ||
        flavor == 'staging' ||
        flavor == 'fieldtest' ||
        !const bool.fromEnvironment('dart.vm.product');
  }

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    setState(() => _loading = true);
    final storage = ref.read(tokenStorageProvider);
    final perms = await ref.read(permissionsChannelProvider).status();
    final db = ref.read(localDatabaseProvider);
    final outbox = await db.outboxCounts();
    final cacheCount = await db.customerCacheCount();
    final dbOk = await db.ping();
    final health = ref.read(serviceHealthProvider);
    await health.load();
    final metrics = await db.allMetrics();
    PackageInfo? info;
    try {
      info = await PackageInfo.fromPlatform();
    } catch (_) {}
    final emp = ref.read(authControllerProvider).employee;
    final call = ref.read(activeCallProvider);
    _data = {
      'app_label': 'Finora Phone Field Test',
      'api_base_url': AppConfig.apiBaseUrl,
      'tenant': AppConfig.tenantSlug,
      'employee': emp?.name,
      'employee_id': emp?.id,
      'device_id': await storage.readDeviceId(),
      'app_version': info?.version,
      'build_number': info?.buildNumber,
      'android_version':
          Platform.isAndroid ? Platform.operatingSystemVersion : null,
      'overlay_permission': perms['overlay'],
      'phone_permission': perms['phone'],
      'call_log_permission': perms['callLog'],
      'notification_permission': perms['notifications'],
      'battery_optimization': 'check_manually',
      'foreground_service': 'companion_overlay',
      'last_call_event': await storage.readLastCallEvent(),
      'last_successful_sync': await storage.readLastSync(),
      'pending_outbox': outbox['pending'],
      'failed_outbox': outbox['failed'],
      'permanently_failed_outbox': outbox['permanently_failed'],
      'local_db_ok': dbOk,
      'customer_cache_count': cacheCount,
      'local_call_count': await db.callLogCount(),
      'last_api_error': await storage.readLastApiError(),
      'active_lifecycle': call.lifecycle.name,
      'number_shown_ms': call.numberShownMs,
      'local_crm_ms': call.localCrmMs,
      'flavor':
          const String.fromEnvironment('FLAVOR', defaultValue: 'development'),
      'call_recovery_architecture': CallRecoveryDocs.architecture,
      'acceptance_phrasing':
          'لا يفقد التطبيق أي حدث مكالمة يسمح Android والجهاز للتطبيق بالوصول إليه، ويتم اكتشاف الفروقات عبر المصالحة مع Android CallLog.',
      ...health.toDiagnosticsMap(),
      'field_metrics': metrics,
      'exported_at': DateTime.now().toUtc().toIso8601String(),
    };
    if (mounted) setState(() => _loading = false);
  }

  Future<Map<String, dynamic>> _buildFieldDayReport() async {
    final db = ref.read(localDatabaseProvider);
    final deviceId = await ref.read(apiClientProvider).ensureDeviceId();
    final raw =
        await ref.read(permissionsChannelProvider).readRecentCallLog(hours: 24);
    final locals = await db.listCallLogs(limit: 500);
    var matched = 0;
    for (final row in raw) {
      final number = normalizePhone('${row['number'] ?? ''}');
      if (number.isEmpty) continue;
      final started = DateTime.tryParse('${row['startedAt'] ?? ''}') ??
          DateTime.fromMillisecondsSinceEpoch(
            (row['date'] as num?)?.toInt() ??
                DateTime.now().millisecondsSinceEpoch,
          );
      final type = '${row['type'] ?? ''}'.toLowerCase();
      final direction = type.contains('out') ? 'outbound' : 'inbound';
      final fp = buildReconciliationFingerprint(
        normalizedPhone: phoneLookupKey(number),
        direction: direction,
        startedAt: started.toUtc(),
        deviceUuid: deviceId,
      );
      final hit = locals.any((r) {
        final localFp = r['reconciliation_fingerprint'] as String?;
        if (localFp != null && localFp == fp) return true;
        final phone = r['phone'] as String? ?? '';
        final s =
            DateTime.tryParse(r['started_at'] as String? ?? '') ?? DateTime(1970);
        return phoneLookupKey(phone) == phoneLookupKey(number) &&
            (s.difference(started).inSeconds).abs() <= 8 &&
            (r['direction'] as String? ?? 'inbound') == direction;
      });
      if (hit) matched++;
    }
    return Map<String, dynamic>.from(
      await db.fieldDaySnapshot(
        androidCallLogCount: raw.length,
        matchedCallLogCount: matched,
      ),
    );
  }

  Future<void> _export() async {
    final safe = Map<String, dynamic>.from(_data)
      ..removeWhere((k, _) =>
          k.contains('token') || k.contains('password') || k.contains('secret'));
    if (_fieldDay != null) {
      safe['field_day_report'] = _fieldDay;
    }
    if (safe['device_id'] is String) {
      final id = safe['device_id'] as String;
      safe['device_id'] = id.length > 8
          ? '${id.substring(0, 4)}…${id.substring(id.length - 4)}'
          : '***';
    }
    final text = const JsonEncoder.withIndent('  ').convert(safe);
    try {
      final dir = await getTemporaryDirectory();
      final file = File(
        '${dir.path}/finora_phone_diag_${DateTime.now().millisecondsSinceEpoch}.json',
      );
      await file.writeAsString(text);
      await Share.shareXFiles(
        [XFile(file.path)],
        text: 'Finora Phone Diagnostics',
      );
    } catch (_) {
      await Clipboard.setData(ClipboardData(text: text));
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('تم نسخ التقرير (بدون أسرار)')),
        );
      }
    }
  }

  Future<void> _runTool(String name, Future<String> Function() fn) async {
    setState(() => _toolResult = 'Running $name…');
    try {
      final r = await fn();
      setState(() => _toolResult = '$name: $r');
    } catch (e) {
      setState(() => _toolResult = '$name FAILED: $e');
    }
  }

  Widget _kv(String key, Object? value) {
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 8),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Expanded(
            flex: 2,
            child: Text(
              key,
              style: const TextStyle(
                fontWeight: FontWeight.w600,
                fontSize: 13,
              ),
            ),
          ),
          Expanded(
            flex: 3,
            child: Text(
              '${value ?? '—'}',
              style: const TextStyle(fontSize: 13),
            ),
          ),
        ],
      ),
    );
  }

  Widget _group(String title, List<MapEntry<String, dynamic>> entries) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 14),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          FinoraSectionHeader(title),
          FinoraSurface(
            padding: EdgeInsets.zero,
            child: Column(
              children: [
                for (var i = 0; i < entries.length; i++) ...[
                  _kv(entries[i].key, entries[i].value),
                  if (i < entries.length - 1)
                    Divider(
                      height: 1,
                      color: AppColors.hairlineLight.withOpacity(0.6),
                    ),
                ],
              ],
            ),
          ),
        ],
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final forceWarn = _data['force_stop_warning'] != null;
    final pass = _fieldDay?['pass'];
    final keys = _data.keys.toList();
    final appKeys = [
      'app_label',
      'app_version',
      'build_number',
      'flavor',
      'api_base_url',
      'tenant',
    ];
    final userKeys = ['employee', 'employee_id', 'device_id'];
    final permKeys = [
      'overlay_permission',
      'phone_permission',
      'call_log_permission',
      'notification_permission',
      'battery_optimization',
      'foreground_service',
    ];
    final syncKeys = [
      'last_call_event',
      'last_successful_sync',
      'pending_outbox',
      'failed_outbox',
      'permanently_failed_outbox',
      'last_api_error',
    ];
    final localKeys = [
      'local_db_ok',
      'customer_cache_count',
      'local_call_count',
      'active_lifecycle',
      'number_shown_ms',
      'local_crm_ms',
    ];
    List<MapEntry<String, dynamic>> pick(Iterable<String> ks) => ks
        .where((k) => keys.contains(k))
        .map((k) => MapEntry(k, _data[k]))
        .toList();
    final rest = keys
        .where((k) =>
            !appKeys.contains(k) &&
            !userKeys.contains(k) &&
            !permKeys.contains(k) &&
            !syncKeys.contains(k) &&
            !localKeys.contains(k) &&
            k != 'field_metrics' &&
            k != 'exported_at' &&
            k != 'force_stop_warning')
        .map((k) => MapEntry(k, _data[k]))
        .toList();

    return FinoraScaffold(
      appBar: AppBar(
        title: const Text('التشخيص'),
        actions: [
          IconButton(onPressed: _load, icon: const Icon(Icons.refresh_rounded)),
        ],
      ),
      body: SafeArea(
        child: _loading
            ? const Center(child: CircularProgressIndicator())
            : ListView(
                padding: const EdgeInsets.fromLTRB(16, 56, 16, 24),
                children: [
                  if (forceWarn)
                    Padding(
                      padding: const EdgeInsets.only(bottom: 12),
                      child: FinoraSurface(
                        padding: const EdgeInsets.all(14),
                        child: Row(
                          children: [
                            const Icon(Icons.warning_amber_rounded,
                                color: AppColors.warning),
                            const SizedBox(width: 10),
                            Expanded(
                              child: Text('${_data['force_stop_warning']}'),
                            ),
                          ],
                        ),
                      ),
                    ),
                  if (_showFieldTools) ...[
                    const FinoraSectionHeader('أدوات الاختبار الميداني'),
                    FinoraSurface(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.stretch,
                        children: [
                          Text(
                            'Staging/dev فقط — لا Mock في المسارات الطبيعية',
                            style: Theme.of(context).textTheme.bodySmall,
                          ),
                          const SizedBox(height: 12),
                          Wrap(
                            spacing: 8,
                            runSpacing: 8,
                            children: [
                              FilledButton.tonal(
                                onPressed: () => _runTool('Sync', () async {
                                  await ref.read(syncEngineProvider).flush();
                                  return 'flush requested';
                                }),
                                child: const Text('محاكاة المزامنة'),
                              ),
                              FilledButton.tonal(
                                onPressed: () => _runTool('API', () async {
                                  final api = ref.read(apiClientProvider);
                                  final r =
                                      await api.get('/api/phone/v1/bootstrap');
                                  return 'ok keys=${r.keys.take(5).join(",")}';
                                }),
                                child: const Text('اختبار API'),
                              ),
                              FilledButton.tonal(
                                onPressed: () => _runTool('Overlay', () async {
                                  final o = ref.read(overlayChannelProvider);
                                  await o.updateCrm({
                                    'name': 'Field Test',
                                    'phone': '0700000000',
                                    'minimal': true,
                                  });
                                  await Future<void>.delayed(
                                    const Duration(seconds: 2),
                                  );
                                  await o.hide();
                                  await ref
                                      .read(serviceHealthProvider)
                                      .markOverlay();
                                  return 'shown then hidden';
                                }),
                                child: const Text('اختبار Overlay'),
                              ),
                              FilledButton.tonal(
                                onPressed: () => _runTool('Lookup', () async {
                                  final c = await ref
                                      .read(customerRepositoryProvider)
                                      .lookupByPhone('07701234567',
                                          allowNetwork: true);
                                  return c == null
                                      ? 'no customer'
                                      : 'found ${c.name}';
                                }),
                                child: const Text('Customer Lookup'),
                              ),
                              FilledButton.tonal(
                                onPressed: () =>
                                    _runTool('Notification', () async {
                                  final p = await ref
                                      .read(permissionsChannelProvider)
                                      .status();
                                  return 'notifications=${p['notifications']}';
                                }),
                                child: const Text('Notification'),
                              ),
                              FilledButton.tonal(
                                onPressed: () =>
                                    _runTool('ForceStopFlag', () async {
                                  await ref
                                      .read(serviceHealthProvider)
                                      .markForceStopSuspected();
                                  await _load();
                                  return 'flag set';
                                }),
                                child: const Text('Force Stop'),
                              ),
                              FilledButton(
                                onPressed: () => _runTool('FieldDay', () async {
                                  final report = await _buildFieldDayReport();
                                  setState(() => _fieldDay = report);
                                  final p = report['pass'] as Map? ?? {};
                                  final ok = p.values.every((v) => v == true);
                                  return ok
                                      ? 'PASS — missing=${report['missing_vs_calllog']}'
                                      : 'REVIEW — missing=${report['missing_vs_calllog']} p95=${report['p95_number_shown_ms']}';
                                }),
                                child: const Text('Field Day Report'),
                              ),
                            ],
                          ),
                          if (_toolResult != null) ...[
                            const SizedBox(height: 12),
                            Text(
                              _toolResult!,
                              style: Theme.of(context).textTheme.bodySmall,
                            ),
                          ],
                        ],
                      ),
                    ),
                    if (_fieldDay != null) ...[
                      const SizedBox(height: 14),
                      FinoraSurface(
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text(
                              'Field Day Report',
                              style: Theme.of(context).textTheme.titleMedium,
                            ),
                            const SizedBox(height: 6),
                            Text(
                              pass is Map && pass.values.every((v) => v == true)
                                  ? 'ضمن أهداف القبول (عيّنة اليوم)'
                                  : 'يحتاج مراجعة — انظر التفاصيل',
                            ),
                            const SizedBox(height: 10),
                            ..._fieldDay!.entries
                                .where((e) =>
                                    e.key != 'targets' && e.key != 'pass')
                                .map(
                                  (e) => Padding(
                                    padding: const EdgeInsets.only(bottom: 6),
                                    child: Text('${e.key}: ${e.value}'),
                                  ),
                                ),
                          ],
                        ),
                      ),
                    ],
                    const SizedBox(height: 8),
                  ],
                  _group('التطبيق', pick(appKeys)),
                  _group('المستخدم والجهاز', pick(userKeys)),
                  _group('الصلاحيات', pick(permKeys)),
                  _group('المزامنة', pick(syncKeys)),
                  _group('البيانات المحلية', pick(localKeys)),
                  if (rest.isNotEmpty) _group('أخرى', rest),
                  Padding(
                    padding: const EdgeInsets.only(top: 4),
                    child: FilledButton.icon(
                      onPressed: _export,
                      icon: const Icon(Icons.ios_share_rounded),
                      label: const Text('تصدير التقرير'),
                    ),
                  ),
                ],
              ),
      ),
    );
  }
}
