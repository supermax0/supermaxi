import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:intl/intl.dart';

import '../../../core/actions/customer_actions.dart';
import '../../../core/di/providers.dart';
import '../../../core/theme/app_colors.dart';
import '../../../core/ui/finora_ui.dart';
import '../../../domain/entities/entities.dart';

final callHistoryProvider = FutureProvider<List<CallLogEntity>>((ref) {
  return ref.watch(callLogRepositoryProvider).listLocal();
});

String _callStatusAr(String status) {
  return switch (status) {
    'detected' => 'مكتشفة',
    'ringing' => 'رنين',
    'dialing' => 'اتصال',
    'answered' => 'تم الرد',
    'ended' => 'انتهت',
    'missed' => 'فائتة',
    'rejected' => 'مرفوضة',
    'failed' => 'فشلت',
    'cancelled' => 'ملغاة',
    _ => status,
  };
}

String _syncStatusAr(String status) {
  return switch (status) {
    'pending' => 'بانتظار المزامنة',
    'syncing' => 'جارٍ المزامنة',
    'synced' => 'مزامنة',
    'failed' => 'فشل المزامنة',
    'permanently_failed' || 'permanentlyFailed' => 'فشل دائم',
    _ => status,
  };
}

String _directionAr(String direction) {
  return direction == 'outbound' ? 'صادرة' : 'واردة';
}

class CallHistoryPage extends ConsumerWidget {
  const CallHistoryPage({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final async = ref.watch(callHistoryProvider);
    final fmt = DateFormat('yyyy/MM/dd HH:mm');
    return FinoraScaffold(
      appBar: AppBar(
        title: const Text('سجل المكالمات'),
        actions: [
          IconButton(
            tooltip: 'مزامنة',
            onPressed: () {
              ref.read(syncEngineProvider).flush();
              ref.invalidate(callHistoryProvider);
            },
            icon: const Icon(Icons.sync_rounded),
          ),
        ],
      ),
      body: SafeArea(
        child: async.when(
          loading: () => const Center(child: CircularProgressIndicator()),
          error: (e, _) => Center(child: Text('$e')),
          data: (logs) {
            if (logs.isEmpty) {
              return const FinoraEmptyState(
                icon: Icons.phone_disabled_outlined,
                title: 'لا توجد مكالمات بعد',
                subtitle: 'ستظهر المكالمات هنا بعد أول اتصال مراقب',
              );
            }
            return ListView.separated(
              padding: const EdgeInsets.fromLTRB(16, 56, 16, 100),
              itemCount: logs.length,
              separatorBuilder: (_, __) => const SizedBox(height: 10),
              itemBuilder: (_, i) {
                final log = logs[i];
                final icon = switch (log.status) {
                  'missed' => Icons.call_missed_rounded,
                  'rejected' => Icons.call_end_rounded,
                  'failed' || 'cancelled' => Icons.phone_disabled_rounded,
                  _ => log.direction == 'outbound'
                      ? Icons.call_made_rounded
                      : Icons.call_received_rounded,
                };
                final accent = log.status == 'missed'
                    ? AppColors.error
                    : (log.syncStatus == 'failed' ||
                            log.syncStatus == 'permanently_failed'
                        ? AppColors.warning
                        : AppColors.goldAccent);
                final title = log.customerName?.isNotEmpty == true
                    ? log.customerName!
                    : log.phone;
                final simHint =
                    log.simSlot == null ? null : 'SIM ${log.simSlot! + 1}';
                return FinoraSurface(
                  onTap: () async {
                    final c = await ref
                        .read(customerRepositoryProvider)
                        .lookupByPhone(log.phone, allowNetwork: true);
                    if (!context.mounted) return;
                    if (c != null) {
                      context.push('/customer-detail', extra: c);
                    } else {
                      context.push(
                        '/customer-detail',
                        extra: CustomerEntity(
                          id: log.customerId,
                          name: title,
                          phone: log.phone,
                        ),
                      );
                    }
                  },
                  padding: const EdgeInsets.symmetric(
                    horizontal: 14,
                    vertical: 12,
                  ),
                  child: Row(
                    children: [
                      Container(
                        width: 44,
                        height: 44,
                        decoration: BoxDecoration(
                          shape: BoxShape.circle,
                          color: accent.withOpacity(0.14),
                        ),
                        child: Icon(icon, color: accent, size: 22),
                      ),
                      const SizedBox(width: 12),
                      Expanded(
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text(
                              title,
                              style: Theme.of(context).textTheme.titleMedium,
                            ),
                            const SizedBox(height: 3),
                            Text(
                              [
                                '${_directionAr(log.direction)} · ${_callStatusAr(log.status)}',
                                fmt.format(log.startedAt.toLocal()),
                                _syncStatusAr(log.syncStatus),
                                if (simHint != null) simHint,
                              ].join(' · '),
                              style: Theme.of(context).textTheme.bodySmall,
                            ),
                          ],
                        ),
                      ),
                      IconButton(
                        tooltip: 'واتساب',
                        onPressed: () =>
                            CustomerActions.openWhatsApp(log.phone),
                        icon: const Icon(Icons.chat_rounded,
                            color: AppColors.goldAccent),
                      ),
                      IconButton(
                        tooltip: 'اتصال',
                        onPressed: () => CustomerActions.dial(ref, log.phone),
                        icon: const Icon(Icons.call_rounded,
                            color: AppColors.success),
                      ),
                      if (log.durationSec != null)
                        Text(
                          '${log.durationSec}ث',
                          style: Theme.of(context).textTheme.labelLarge,
                        ),
                    ],
                  ),
                );
              },
            );
          },
        ),
      ),
    );
  }
}
