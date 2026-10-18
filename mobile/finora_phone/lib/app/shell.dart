import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../core/theme/app_colors.dart';
import '../core/ui/finora_ui.dart';
import '../features/auth/data/auth_controller.dart';
import '../features/call_history/presentation/call_history_page.dart';
import '../features/customers/presentation/customers_page.dart';
import '../features/overlay/presentation/overlay_ui.dart';
import '../features/phone/presentation/phone_dial_pad_page.dart';
import '../features/settings/presentation/settings_page.dart';
import '../features/tasks/presentation/tasks_page.dart';

class AppShell extends ConsumerWidget {
  const AppShell({super.key, required this.navigationShell});

  final StatefulNavigationShell navigationShell;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final dark = Theme.of(context).brightness == Brightness.dark;
    return FinoraScaffold(
      extendBody: true,
      body: Column(
        children: [
          const IncomingCallBanner(),
          const OfflineBanner(),
          Expanded(child: navigationShell),
        ],
      ),
      bottomNavigationBar: Container(
        decoration: BoxDecoration(
          border: Border(
            top: BorderSide(
              color: dark ? AppColors.hairlineDark : AppColors.hairlineLight,
            ),
          ),
          boxShadow: [
            BoxShadow(
              color: Colors.black.withOpacity(dark ? 0.35 : 0.06),
              blurRadius: 18,
              offset: const Offset(0, -4),
            ),
          ],
        ),
        child: NavigationBar(
          selectedIndex: navigationShell.currentIndex,
          onDestinationSelected: navigationShell.goBranch,
          destinations: const [
            NavigationDestination(
              icon: Icon(Icons.dialpad_rounded),
              selectedIcon: Icon(Icons.dialpad_rounded),
              label: 'هاتف',
            ),
            NavigationDestination(
              icon: Icon(Icons.history_rounded),
              selectedIcon: Icon(Icons.history_rounded),
              label: 'سجل',
            ),
            NavigationDestination(
              icon: Icon(Icons.people_outline_rounded),
              selectedIcon: Icon(Icons.people_rounded),
              label: 'زبائن',
            ),
            NavigationDestination(
              icon: Icon(Icons.task_alt_outlined),
              selectedIcon: Icon(Icons.task_alt_rounded),
              label: 'مهام',
            ),
            NavigationDestination(
              icon: Icon(Icons.tune_rounded),
              selectedIcon: Icon(Icons.tune_rounded),
              label: 'إعدادات',
            ),
          ],
        ),
      ),
    );
  }
}

class OfflineBanner extends ConsumerWidget {
  const OfflineBanner({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final offline = ref.watch(
      authControllerProvider.select((s) => s.offline),
    );
    if (!offline) return const SizedBox.shrink();
    return Material(
      color: AppColors.warning.withOpacity(0.16),
      child: InkWell(
        onTap: () => ref.read(authControllerProvider.notifier).revalidate(),
        child: Padding(
          padding: const EdgeInsets.fromLTRB(16, 8, 16, 8),
          child: Row(
            children: [
              const Icon(Icons.cloud_off_rounded, size: 18),
              const SizedBox(width: 8),
              Expanded(
                child: Text(
                  'وضع بدون اتصال — ملاحظاتك ومهامك تُحفظ وتُرسل تلقائياً',
                  style: Theme.of(context).textTheme.bodySmall,
                ),
              ),
              const Icon(Icons.refresh_rounded, size: 18),
            ],
          ),
        ),
      ),
    );
  }
}

class ShellBranches {
  static const phone = PhoneDialPadPage();
  static const history = CallHistoryPage();
  static const customers = CustomersPage();
  static const tasks = TasksPage();
  static const settings = SettingsPage();
}
