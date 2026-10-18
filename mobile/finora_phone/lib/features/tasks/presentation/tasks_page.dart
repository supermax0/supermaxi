import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:intl/intl.dart';
import 'package:uuid/uuid.dart';

import '../../../core/actions/customer_actions.dart';
import '../../../core/bootstrap/phone_bootstrap.dart';
import '../../../core/di/providers.dart';
import '../../../core/features/feature_flags.dart';
import '../../../core/theme/app_colors.dart';
import '../../../core/ui/finora_ui.dart';
import '../../../domain/entities/entities.dart';

final tasksFilterProvider = StateProvider<String>((ref) => 'open');

final tasksProvider = FutureProvider<List<TaskEntity>>((ref) async {
  final filter = ref.watch(tasksFilterProvider);
  final repo = ref.watch(taskRepositoryProvider);
  if (filter == 'open') {
    return repo.listLocal(status: 'open');
  }
  await repo.pullRemote(filter: filter == 'all' ? null : filter);
  return repo.listLocal(filter: filter == 'all' ? null : filter);
});

class TasksPage extends ConsumerWidget {
  const TasksPage({super.key});

  Future<void> _createManual(BuildContext context, WidgetRef ref) async {
    final titleCtrl = TextEditingController(text: 'مهمة متابعة');
    final phoneCtrl = TextEditingController();
    final ok = await showModalBottomSheet<bool>(
      context: context,
      isScrollControlled: true,
      useRootNavigator: true,
      builder: (ctx) => Padding(
        padding: EdgeInsets.only(
          left: 20,
          right: 20,
          top: 12,
          bottom: MediaQuery.of(ctx).viewInsets.bottom +
              MediaQuery.of(ctx).viewPadding.bottom +
              20,
        ),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Text('مهمة جديدة', style: Theme.of(ctx).textTheme.headlineSmall),
            const SizedBox(height: 12),
            TextField(
              controller: titleCtrl,
              decoration: const InputDecoration(labelText: 'العنوان'),
            ),
            const SizedBox(height: 10),
            TextField(
              controller: phoneCtrl,
              keyboardType: TextInputType.phone,
              decoration: const InputDecoration(labelText: 'رقم الهاتف'),
            ),
            const SizedBox(height: 14),
            FilledButton(
              onPressed: () => Navigator.pop(ctx, true),
              child: const Text('إنشاء'),
            ),
          ],
        ),
      ),
    );
    if (ok != true || phoneCtrl.text.trim().isEmpty) return;
    final minutes = ref.read(phoneBootstrapProvider).missedCallFollowupMinutes;
    await ref.read(taskRepositoryProvider).createLocal(
          TaskEntity(
            clientId: const Uuid().v4(),
            title: titleCtrl.text.trim().isEmpty
                ? 'مهمة متابعة'
                : titleCtrl.text.trim(),
            phone: phoneCtrl.text.trim(),
            dueAt: DateTime.now().toUtc().add(Duration(minutes: minutes)),
            source: 'manual',
            taskType: 'manual',
          ),
        );
    ref.invalidate(tasksProvider);
  }

  Color _priorityColor(String p) {
    return switch (p) {
      'urgent' => AppColors.error,
      'high' => Colors.orange,
      'low' => Colors.blueGrey,
      _ => AppColors.goldAccent,
    };
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final async = ref.watch(tasksProvider);
    final filter = ref.watch(tasksFilterProvider);
    final flags = ref.watch(featureFlagsProvider);
    final fmt = DateFormat('yyyy/MM/dd HH:mm');
    return FinoraScaffold(
      appBar: AppBar(
        title: const Text('المهام'),
        actions: [
          IconButton(
            tooltip: 'تحديث',
            onPressed: () async {
              await ref.read(taskRepositoryProvider).pullRemote(filter: filter);
              ref.invalidate(tasksProvider);
            },
            icon: const Icon(Icons.refresh_rounded),
          ),
        ],
      ),
      floatingActionButton: Padding(
        padding: EdgeInsets.only(bottom: finoraShellBottomInset(context)),
        child: FloatingActionButton(
          onPressed: () => _createManual(context, ref),
          child: const Icon(Icons.add_task_rounded),
        ),
      ),
      body: SafeArea(
        child: Column(
          children: [
            if (flags.smartFollowup)
              SingleChildScrollView(
                scrollDirection: Axis.horizontal,
                padding: const EdgeInsets.fromLTRB(12, 8, 12, 4),
                child: Row(
                  children: [
                    for (final f in [
                      ('open', 'مفتوحة'),
                      ('today', 'اليوم'),
                      ('overdue', 'متأخرة'),
                      ('high_priority', 'عالية'),
                      ('missed', 'فائتة'),
                      ('callback', 'إعادة اتصال'),
                      ('complaint', 'شكاوى'),
                    ])
                      Padding(
                        padding: const EdgeInsets.only(left: 6),
                        child: ChoiceChip(
                          label: Text(f.$2),
                          selected: filter == f.$1,
                          onSelected: (_) {
                            ref.read(tasksFilterProvider.notifier).state =
                                f.$1;
                          },
                        ),
                      ),
                  ],
                ),
              ),
            Expanded(
              child: async.when(
                loading: () =>
                    const Center(child: CircularProgressIndicator()),
                error: (e, _) => Center(child: Text('$e')),
                data: (tasks) {
                  if (tasks.isEmpty) {
                    return const Center(child: Text('لا مهام'));
                  }
                  return ListView.separated(
                    padding: const EdgeInsets.fromLTRB(16, 8, 16, 100),
                    itemCount: tasks.length,
                    separatorBuilder: (_, __) => const SizedBox(height: 8),
                    itemBuilder: (context, i) {
                      final t = tasks[i];
                      return FinoraSurface(
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.stretch,
                          children: [
                            ListTile(
                              contentPadding: EdgeInsets.zero,
                              title: Text(t.title),
                              subtitle: Text(
                                [
                                  t.phone,
                                  if (t.dueAt != null)
                                    fmt.format(t.dueAt!.toLocal()),
                                  t.status,
                                ].join(' · '),
                              ),
                              trailing: Container(
                                padding: const EdgeInsets.symmetric(
                                  horizontal: 8,
                                  vertical: 4,
                                ),
                                decoration: BoxDecoration(
                                  color: _priorityColor(t.priority)
                                      .withOpacity(0.15),
                                  borderRadius: BorderRadius.circular(8),
                                ),
                                child: Text(
                                  t.priority,
                                  style: TextStyle(
                                    color: _priorityColor(t.priority),
                                    fontWeight: FontWeight.w700,
                                    fontSize: 11,
                                  ),
                                ),
                              ),
                            ),
                            Wrap(
                              spacing: 6,
                              children: [
                                TextButton(
                                  onPressed: () =>
                                      CustomerActions.dial(ref, t.phone),
                                  child: const Text('اتصال'),
                                ),
                                TextButton(
                                  onPressed: () async {
                                    await ref
                                        .read(taskRepositoryProvider)
                                        .updateStatus(
                                          t.clientId,
                                          'completed',
                                        );
                                    ref.invalidate(tasksProvider);
                                  },
                                  child: const Text('إكمال'),
                                ),
                                TextButton(
                                  onPressed: () async {
                                    await ref
                                        .read(taskRepositoryProvider)
                                        .snooze(
                                          t.clientId,
                                          DateTime.now()
                                              .toUtc()
                                              .add(const Duration(hours: 2)),
                                        );
                                    ref.invalidate(tasksProvider);
                                  },
                                  child: const Text('تأجيل'),
                                ),
                                TextButton(
                                  onPressed: () async {
                                    final c = await ref
                                        .read(customerRepositoryProvider)
                                        .lookupByPhone(
                                          t.phone,
                                          allowNetwork: true,
                                        );
                                    if (!context.mounted) return;
                                    context.push(
                                      '/customer-detail',
                                      extra: c ??
                                          CustomerEntity(
                                            id: t.customerId,
                                            name: t.title,
                                            phone: t.phone,
                                          ),
                                    );
                                  },
                                  child: const Text('الزبون'),
                                ),
                              ],
                            ),
                          ],
                        ),
                      );
                    },
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
