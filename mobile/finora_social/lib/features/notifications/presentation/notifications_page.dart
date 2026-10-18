import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../core/theme/app_colors.dart';
import '../data/notifications_controller.dart';

class NotificationsPage extends ConsumerStatefulWidget {
  const NotificationsPage({super.key});

  @override
  ConsumerState<NotificationsPage> createState() => _NotificationsPageState();
}

class _NotificationsPageState extends ConsumerState<NotificationsPage> {
  @override
  void initState() {
    super.initState();
    Future.microtask(
      () => ref.read(notificationsControllerProvider.notifier).refresh(),
    );
  }

  @override
  Widget build(BuildContext context) {
    final state = ref.watch(notificationsControllerProvider);
    return Scaffold(
      appBar: AppBar(title: const Text('الإشعارات')),
      body: state.loading && state.items.isEmpty
          ? const Center(child: CircularProgressIndicator())
          : RefreshIndicator(
              onRefresh: () =>
                  ref.read(notificationsControllerProvider.notifier).refresh(),
              child: state.items.isEmpty
                  ? ListView(
                      children: const [
                        SizedBox(height: 120),
                        Center(child: Text('لا توجد إشعارات')),
                      ],
                    )
                  : ListView.separated(
                      itemCount: state.items.length,
                      separatorBuilder: (_, __) => const Divider(height: 1),
                      itemBuilder: (context, index) {
                        final n = state.items[index];
                        return ListTile(
                          leading: Icon(
                            n.read
                                ? Icons.notifications_none
                                : Icons.notifications_active,
                            color: n.read ? Colors.grey : AppColors.mutedGold,
                          ),
                          title: Text(
                            n.title,
                            style: TextStyle(
                              fontWeight:
                                  n.read ? FontWeight.w500 : FontWeight.w700,
                            ),
                          ),
                          subtitle: Text(n.body),
                          onTap: () async {
                            if (!n.read) {
                              await ref
                                  .read(
                                      notificationsControllerProvider.notifier)
                                  .markRead(n.id);
                            }
                            final orderId = n.data['order_id'];
                            if (orderId != null && context.mounted) {
                              context.push('/profile/orders/$orderId');
                            }
                          },
                        );
                      },
                    ),
            ),
    );
  }
}
