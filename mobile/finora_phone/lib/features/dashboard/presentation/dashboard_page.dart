import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/di/providers.dart';
import '../../../core/theme/app_colors.dart';
import '../../../core/ui/finora_ui.dart';
import '../../auth/data/auth_controller.dart';
import '../../call_history/presentation/call_history_page.dart';
import '../../orders/presentation/order_drafts_page.dart';
import '../../tasks/presentation/tasks_page.dart';

class DashboardPage extends ConsumerWidget {
  const DashboardPage({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final emp = ref.watch(authControllerProvider).employee;
    final history = ref.watch(callHistoryProvider);
    final tasks = ref.watch(tasksProvider);

    return FinoraScaffold(
      appBar: AppBar(title: const Text('لوحة اليوم')),
      body: SafeArea(
        child: ListView(
          padding: const EdgeInsets.fromLTRB(16, 56, 16, 28),
          children: [
            Text(
              'مرحباً ${emp?.name ?? ''}',
              style: Theme.of(context).textTheme.headlineSmall,
            ),
            const SizedBox(height: 6),
            Text(
              'ملخص سريع ليوم العمل',
              style: Theme.of(context).textTheme.bodyMedium,
            ),
            const SizedBox(height: 18),
            history.when(
              data: (logs) {
                final missed =
                    logs.where((l) => l.status == 'missed').length;
                return FinoraSurface(
                  onTap: () => context.go('/history'),
                  child: Row(
                    children: [
                      const Icon(Icons.history_rounded,
                          color: AppColors.goldAccent),
                      const SizedBox(width: 12),
                      Expanded(
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text(
                              'المكالمات',
                              style: Theme.of(context).textTheme.titleMedium,
                            ),
                            Text('${logs.length} محلية · $missed فائتة'),
                          ],
                        ),
                      ),
                      const Icon(Icons.chevron_left),
                    ],
                  ),
                );
              },
              loading: () => const LinearProgressIndicator(),
              error: (_, __) => const SizedBox.shrink(),
            ),
            const SizedBox(height: 10),
            tasks.when(
              data: (items) => FinoraSurface(
                onTap: () => context.go('/tasks'),
                child: Row(
                  children: [
                    const Icon(Icons.task_alt_rounded,
                        color: AppColors.goldAccent),
                    const SizedBox(width: 12),
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(
                            'مهام مفتوحة',
                            style: Theme.of(context).textTheme.titleMedium,
                          ),
                          Text('${items.length}'),
                        ],
                      ),
                    ),
                    const Icon(Icons.chevron_left),
                  ],
                ),
              ),
              loading: () => const SizedBox.shrink(),
              error: (_, __) => const SizedBox.shrink(),
            ),
            const SizedBox(height: 10),
            FinoraSurface(
              onTap: () => Navigator.of(context).push(
                MaterialPageRoute(builder: (_) => const OrderDraftsPage()),
              ),
              child: const Row(
                children: [
                  Icon(Icons.drafts_outlined, color: AppColors.goldAccent),
                  SizedBox(width: 12),
                  Expanded(child: Text('مسودات الطلبات')),
                  Icon(Icons.chevron_left),
                ],
              ),
            ),
            const SizedBox(height: 10),
            FinoraSurface(
              onTap: () => context.go('/phone'),
              child: const Row(
                children: [
                  Icon(Icons.dialpad_rounded, color: AppColors.goldAccent),
                  SizedBox(width: 12),
                  Expanded(child: Text('فتح لوحة الاتصال')),
                  Icon(Icons.chevron_left),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}
