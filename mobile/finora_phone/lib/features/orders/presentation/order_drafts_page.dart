import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/di/providers.dart';
import '../../../core/theme/app_colors.dart';
import '../../../core/ui/finora_ui.dart';

class OrderDraftsPage extends ConsumerStatefulWidget {
  const OrderDraftsPage({super.key});

  @override
  ConsumerState<OrderDraftsPage> createState() => _OrderDraftsPageState();
}

class _OrderDraftsPageState extends ConsumerState<OrderDraftsPage> {
  List<Map<String, dynamic>> _drafts = const [];
  bool _loading = true;
  String? _message;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _message = null;
    });
    final rows = await ref.read(orderRepositoryProvider).listDrafts();
    if (mounted) {
      setState(() {
        _drafts = rows;
        _loading = false;
      });
    }
  }

  Future<void> _confirm(Map<String, dynamic> draft) async {
    final id = draft['id'];
    if (id is! num) {
      setState(() => _message = 'المسودة لم تُزامَن بعد — انتظر المزامنة ثم أكّد');
      return;
    }
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('تأكيد المسودة؟'),
        content: const Text(
          'سيُنشأ طلب/فاتورة نهائية ويُخصم المخزون حسب صلاحيات Finora. لا يمكن التراجع بسهولة.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx, false),
            child: const Text('إلغاء'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(ctx, true),
            child: const Text('تأكيد'),
          ),
        ],
      ),
    );
    if (ok != true) return;
    final success =
        await ref.read(orderRepositoryProvider).confirmDraft(draftId: id.toInt());
    if (!mounted) return;
    setState(() {
      _message = success ? 'تم التأكيد بنجاح' : 'فشل التأكيد — تحقق من الصلاحيات أو المخزون';
    });
    await _load();
  }

  String _statusLabel(String status) {
    switch (status) {
      case 'draft':
        return 'مسودة';
      case 'confirmed':
        return 'مؤكّد';
      case 'pending':
        return 'بانتظار المزامنة';
      default:
        return status;
    }
  }

  Color _statusColor(String status) {
    switch (status) {
      case 'draft':
        return AppColors.goldAccent;
      case 'confirmed':
        return AppColors.success;
      default:
        return AppColors.textMutedLight;
    }
  }

  @override
  Widget build(BuildContext context) {
    return FinoraScaffold(
      appBar: AppBar(
        title: const Text('مسودات الطلبات'),
        actions: [
          IconButton(
            onPressed: _load,
            icon: const Icon(Icons.refresh_rounded),
          ),
        ],
      ),
      body: SafeArea(
        child: _loading
            ? const Center(child: CircularProgressIndicator())
            : Column(
                children: [
                  if (_message != null)
                    Padding(
                      padding: const EdgeInsets.fromLTRB(16, 56, 16, 0),
                      child: FinoraSurface(
                        padding: const EdgeInsets.all(12),
                        child: Row(
                          children: [
                            const Icon(Icons.info_outline_rounded,
                                color: AppColors.goldAccent, size: 20),
                            const SizedBox(width: 10),
                            Expanded(child: Text(_message!)),
                          ],
                        ),
                      ),
                    ),
                  Expanded(
                    child: _drafts.isEmpty
                        ? const FinoraEmptyState(
                            icon: Icons.receipt_long_rounded,
                            title: 'لا توجد مسودات',
                            subtitle: 'مسودات الطلبات من المكالمات تظهر هنا',
                          )
                        : ListView.separated(
                            padding: const EdgeInsets.fromLTRB(16, 56, 16, 24),
                            itemCount: _drafts.length,
                            separatorBuilder: (_, __) => const SizedBox(height: 10),
                            itemBuilder: (context, i) {
                              final d = _drafts[i];
                              final status = '${d['status'] ?? 'draft'}';
                              final payload = d['payload'];
                              final total = payload is Map ? payload['total'] : null;
                              final summary = payload is Map
                                  ? (payload['items_summary'] as List?)?.join('، ')
                                  : null;
                              final canConfirm =
                                  status == 'draft' && d['id'] is num;
                              return FinoraSurface(
                                padding: const EdgeInsets.all(14),
                                child: Column(
                                  crossAxisAlignment: CrossAxisAlignment.stretch,
                                  children: [
                                    Row(
                                      children: [
                                        Container(
                                          width: 44,
                                          height: 44,
                                          decoration: BoxDecoration(
                                            shape: BoxShape.circle,
                                            color: AppColors.goldWash,
                                            border: Border.all(
                                              color: AppColors.goldAccent
                                                  .withOpacity(0.3),
                                            ),
                                          ),
                                          child: const Icon(
                                            Icons.shopping_bag_outlined,
                                            color: AppColors.goldAccent,
                                            size: 22,
                                          ),
                                        ),
                                        const SizedBox(width: 12),
                                        Expanded(
                                          child: Column(
                                            crossAxisAlignment:
                                                CrossAxisAlignment.start,
                                            children: [
                                              Text(
                                                'مسودة #${d['id'] ?? d['client_id']}',
                                                style: Theme.of(context)
                                                    .textTheme
                                                    .titleMedium,
                                              ),
                                              const SizedBox(height: 2),
                                              Text(
                                                _statusLabel(status),
                                                style: TextStyle(
                                                  color: _statusColor(status),
                                                  fontWeight: FontWeight.w700,
                                                  fontSize: 13,
                                                ),
                                              ),
                                            ],
                                          ),
                                        ),
                                        if (canConfirm)
                                          FilledButton(
                                            onPressed: () => _confirm(d),
                                            child: const Text('تأكيد'),
                                          ),
                                      ],
                                    ),
                                    if (total != null ||
                                        (summary != null &&
                                            summary.isNotEmpty) ||
                                        d['local_only'] == true) ...[
                                      const SizedBox(height: 10),
                                      Text(
                                        [
                                          if (total != null) 'الإجمالي: $total',
                                          if (summary != null &&
                                              summary.isNotEmpty)
                                            summary,
                                          if (d['local_only'] == true)
                                            'محلية — بانتظار المزامنة',
                                        ].join('\n'),
                                        style: Theme.of(context)
                                            .textTheme
                                            .bodyMedium,
                                      ),
                                    ],
                                  ],
                                ),
                              );
                            },
                          ),
                  ),
                ],
              ),
      ),
    );
  }
}
