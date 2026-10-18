import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/di/providers.dart';
import '../../../core/theme/app_colors.dart';
import '../../../core/ui/finora_ui.dart';

class OutboxFailedPage extends ConsumerStatefulWidget {
  const OutboxFailedPage({super.key});

  @override
  ConsumerState<OutboxFailedPage> createState() => _OutboxFailedPageState();
}

class _OutboxFailedPageState extends ConsumerState<OutboxFailedPage> {
  List<Map<String, Object?>> _rows = const [];
  bool _loading = true;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    setState(() => _loading = true);
    final rows =
        await ref.read(localDatabaseProvider).permanentlyFailedOutbox();
    if (mounted) {
      setState(() {
        _rows = rows;
        _loading = false;
      });
    }
  }

  Future<void> _retry(int id) async {
    await ref.read(localDatabaseProvider).retryOutbox(id);
    await ref.read(syncEngineProvider).flush();
    await _load();
  }

  Future<void> _retryAll() async {
    await ref.read(localDatabaseProvider).retryAllPermanentlyFailed();
    await ref.read(syncEngineProvider).flush();
    await _load();
  }

  Future<void> _discard(int id) async {
    await ref.read(localDatabaseProvider).deleteOutbox(id);
    await _load();
  }

  String _opLabel(String op) {
    switch (op) {
      case 'create_customer':
        return 'إنشاء زبون';
      case 'create_task':
        return 'إنشاء مهمة';
      case 'create_note':
        return 'حفظ ملاحظة';
      case 'create_order':
        return 'مسودة طلب';
      case 'sync_call':
        return 'مزامنة مكالمة';
      default:
        return op;
    }
  }

  @override
  Widget build(BuildContext context) {
    return FinoraScaffold(
      appBar: AppBar(
        title: const Text('عمليات فاشلة نهائياً'),
        actions: [
          if (_rows.isNotEmpty)
            TextButton(
              onPressed: _retryAll,
              child: const Text('إعادة الكل'),
            ),
          IconButton(
            onPressed: _load,
            icon: const Icon(Icons.refresh_rounded),
          ),
        ],
      ),
      body: SafeArea(
        child: _loading
            ? const Center(child: CircularProgressIndicator())
            : _rows.isEmpty
                ? const FinoraEmptyState(
                    icon: Icons.cloud_off_rounded,
                    title: 'لا توجد عمليات فاشلة',
                    subtitle: 'العمليات التي فشلت بعد كل المحاولات تظهر هنا',
                  )
                : ListView.separated(
                    padding: const EdgeInsets.fromLTRB(16, 56, 16, 24),
                    itemCount: _rows.length,
                    separatorBuilder: (_, __) => const SizedBox(height: 10),
                    itemBuilder: (context, i) {
                      final r = _rows[i];
                      final id = r['id'] as int;
                      final op = '${r['op']}';
                      final err = '${r['last_error'] ?? ''}';
                      String summary = '';
                      try {
                        final payload = jsonDecode(
                          r['payload_json'] as String? ?? '{}',
                        );
                        if (payload is Map) {
                          summary = [
                            if (payload['phone'] != null)
                              'هاتف: ${payload['phone']}',
                            if (payload['client_id'] != null)
                              'client: ${payload['client_id']}',
                            if (payload['title'] != null) '${payload['title']}',
                          ].join(' · ');
                        }
                      } catch (_) {}
                      return FinoraSurface(
                        padding: const EdgeInsets.all(14),
                        child: Row(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Container(
                              width: 44,
                              height: 44,
                              decoration: BoxDecoration(
                                shape: BoxShape.circle,
                                color: AppColors.error.withOpacity(0.12),
                                border: Border.all(
                                  color: AppColors.error.withOpacity(0.35),
                                ),
                              ),
                              child: const Icon(
                                Icons.error_outline_rounded,
                                color: AppColors.error,
                                size: 22,
                              ),
                            ),
                            const SizedBox(width: 12),
                            Expanded(
                              child: Column(
                                crossAxisAlignment: CrossAxisAlignment.start,
                                children: [
                                  Text(
                                    _opLabel(op),
                                    style:
                                        Theme.of(context).textTheme.titleMedium,
                                  ),
                                  if (summary.isNotEmpty) ...[
                                    const SizedBox(height: 4),
                                    Text(
                                      summary,
                                      style:
                                          Theme.of(context).textTheme.bodyMedium,
                                    ),
                                  ],
                                  if (err.isNotEmpty) ...[
                                    const SizedBox(height: 4),
                                    Text(
                                      err,
                                      style: Theme.of(context)
                                          .textTheme
                                          .bodySmall
                                          ?.copyWith(color: AppColors.error),
                                    ),
                                  ],
                                ],
                              ),
                            ),
                            Column(
                              children: [
                                IconButton(
                                  tooltip: 'إعادة',
                                  onPressed: () => _retry(id),
                                  icon: const Icon(Icons.refresh_rounded),
                                  color: AppColors.goldAccent,
                                ),
                                IconButton(
                                  tooltip: 'تجاهل',
                                  onPressed: () => _discard(id),
                                  icon: const Icon(Icons.delete_outline_rounded),
                                  color: AppColors.textMutedLight,
                                ),
                              ],
                            ),
                          ],
                        ),
                      );
                    },
                  ),
      ),
    );
  }
}
