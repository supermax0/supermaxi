import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../core/theme/app_colors.dart';
import '../data/rewards_controller.dart';

class RewardsPage extends ConsumerStatefulWidget {
  const RewardsPage({super.key});

  @override
  ConsumerState<RewardsPage> createState() => _RewardsPageState();
}

class _RewardsPageState extends ConsumerState<RewardsPage> {
  @override
  void initState() {
    super.initState();
    Future.microtask(
        () => ref.read(rewardsControllerProvider.notifier).refresh());
  }

  @override
  Widget build(BuildContext context) {
    final state = ref.watch(rewardsControllerProvider);
    final summary = state.summary;

    return Scaffold(
      appBar: AppBar(title: const Text('المكافآت')),
      body: state.loading && summary == null
          ? const Center(child: CircularProgressIndicator())
          : RefreshIndicator(
              onRefresh: () =>
                  ref.read(rewardsControllerProvider.notifier).refresh(),
              child: ListView(
                padding: const EdgeInsets.all(20),
                children: [
                  if (state.error != null)
                    Padding(
                      padding: const EdgeInsets.only(bottom: 12),
                      child: Text(state.error!,
                          style: const TextStyle(color: AppColors.error)),
                    ),
                  Container(
                    padding: const EdgeInsets.all(20),
                    decoration: BoxDecoration(
                      gradient: LinearGradient(
                        colors: [
                          AppColors.primaryDark,
                          AppColors.primaryDark.withOpacity(0.85),
                        ],
                      ),
                      borderRadius: BorderRadius.circular(16),
                    ),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          summary?.tierName ?? 'Silver',
                          style: const TextStyle(
                            color: AppColors.goldAccent,
                            fontWeight: FontWeight.w700,
                          ),
                        ),
                        const SizedBox(height: 8),
                        Text(
                          '${summary?.balance ?? 0}',
                          style: const TextStyle(
                            color: AppColors.textLight,
                            fontSize: 36,
                            fontWeight: FontWeight.w800,
                          ),
                        ),
                        const Text(
                          'نقطة متاحة',
                          style: TextStyle(color: Colors.white70),
                        ),
                        if ((summary?.pendingPoints ?? 0) > 0) ...[
                          const SizedBox(height: 8),
                          Text(
                            'قيد التأكيد: ${summary!.pendingPoints}',
                            style: const TextStyle(color: Colors.white60),
                          ),
                        ],
                      ],
                    ),
                  ),
                  const SizedBox(height: 20),
                  if (state.campaigns.isNotEmpty) ...[
                    Text('حملات نشطة',
                        style: Theme.of(context).textTheme.titleMedium),
                    const SizedBox(height: 8),
                    for (final c in state.campaigns)
                      ListTile(
                        contentPadding: EdgeInsets.zero,
                        leading: const Icon(Icons.campaign_outlined,
                            color: AppColors.mutedGold),
                        title: Text('${c['name']}'),
                        subtitle: Text('مضاعف نقاط ×${c['bonus_multiplier']}'),
                      ),
                    const SizedBox(height: 12),
                  ],
                  Text('استبدال النقاط',
                      style: Theme.of(context).textTheme.titleMedium),
                  const SizedBox(height: 8),
                  if (state.redemptions.isEmpty)
                    const Text('لا توجد خيارات استبدال حالياً')
                  else
                    for (final opt in state.redemptions)
                      ListTile(
                        contentPadding: EdgeInsets.zero,
                        title: Text('${opt['label']}'),
                        trailing: TextButton(
                          onPressed: () async {
                            try {
                              await ref
                                  .read(rewardsControllerProvider.notifier)
                                  .redeemToCart(opt['points'] as int);
                              if (!context.mounted) return;
                              ScaffoldMessenger.of(context).showSnackBar(
                                const SnackBar(
                                    content:
                                        Text('تم تطبيق النقاط على العربة')),
                              );
                              context.push('/cart');
                            } catch (e) {
                              if (!context.mounted) return;
                              ScaffoldMessenger.of(context).showSnackBar(
                                SnackBar(content: Text('$e')),
                              );
                            }
                          },
                          child: const Text('تطبيق'),
                        ),
                      ),
                  const SizedBox(height: 20),
                  Text('سجل الحركات',
                      style: Theme.of(context).textTheme.titleMedium),
                  const SizedBox(height: 8),
                  if (state.history.isEmpty)
                    const Text('لا توجد حركات بعد')
                  else
                    for (final tx in state.history)
                      ListTile(
                        contentPadding: EdgeInsets.zero,
                        title: Text(tx.description.isNotEmpty
                            ? tx.description
                            : tx.type),
                        subtitle: Text('${tx.status} · ${tx.direction}'),
                        trailing: Text(
                          '${tx.direction == 'credit' ? '+' : '-'}${tx.points}',
                          style: TextStyle(
                            color: tx.direction == 'credit'
                                ? AppColors.success
                                : AppColors.error,
                            fontWeight: FontWeight.w700,
                          ),
                        ),
                      ),
                ],
              ),
            ),
    );
  }
}
