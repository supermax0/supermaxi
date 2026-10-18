import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../authentication/data/auth_controller.dart';
import '../../profile/data/profile_controller.dart';
import '../../../core/theme/app_colors.dart';
import '../../../core/theme/theme_controller.dart';

class MainShellPage extends ConsumerWidget {
  const MainShellPage({super.key, required this.navigationShell});

  final StatefulNavigationShell navigationShell;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    return Scaffold(
      extendBody: true,
      body: navigationShell,
      bottomNavigationBar: _FinoraNavigationBar(
        selectedIndex: navigationShell.currentIndex,
        onSelected: (index) => navigationShell.goBranch(
          index,
          initialLocation: index == navigationShell.currentIndex,
        ),
      ),
    );
  }
}

class _FinoraNavigationBar extends StatelessWidget {
  const _FinoraNavigationBar({
    required this.selectedIndex,
    required this.onSelected,
  });

  final int selectedIndex;
  final ValueChanged<int> onSelected;

  static const _items = <({IconData icon, IconData selected, String label})>[
    (
      icon: Icons.play_circle_outline_rounded,
      selected: Icons.play_circle_fill_rounded,
      label: 'الرئيسية'
    ),
    (
      icon: Icons.storefront_outlined,
      selected: Icons.storefront_rounded,
      label: 'المتجر'
    ),
    (
      icon: Icons.auto_awesome_outlined,
      selected: Icons.auto_awesome_rounded,
      label: 'المساعد'
    ),
    (
      icon: Icons.card_giftcard_outlined,
      selected: Icons.card_giftcard_rounded,
      label: 'المكافآت'
    ),
    (
      icon: Icons.person_outline_rounded,
      selected: Icons.person_rounded,
      label: 'حسابي'
    ),
  ];

  @override
  Widget build(BuildContext context) {
    final dark = Theme.of(context).brightness == Brightness.dark;
    final background = dark ? const Color(0xF21A1D24) : const Color(0xF7FFFFFF);
    final muted = dark ? const Color(0xFF9CA3AF) : const Color(0xFF77736B);

    return SafeArea(
      top: false,
      minimum: const EdgeInsets.fromLTRB(12, 0, 12, 10),
      child: Container(
        height: 72,
        padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 7),
        decoration: BoxDecoration(
          color: background,
          borderRadius: BorderRadius.circular(26),
          border: Border.all(
            color: dark ? const Color(0xFF30343E) : const Color(0x1FD9A441),
          ),
          boxShadow: const [
            BoxShadow(
              color: Color(0x30000000),
              blurRadius: 30,
              offset: Offset(0, 12),
            ),
          ],
        ),
        child: Row(
          children: List.generate(_items.length, (index) {
            final item = _items[index];
            final selected = index == selectedIndex;
            return Expanded(
              child: Semantics(
                selected: selected,
                button: true,
                label: item.label,
                child: InkWell(
                  borderRadius: BorderRadius.circular(20),
                  onTap: () => onSelected(index),
                  child: AnimatedContainer(
                    duration: const Duration(milliseconds: 260),
                    curve: Curves.easeOutCubic,
                    decoration: BoxDecoration(
                      color: selected
                          ? const Color(0x22D9A441)
                          : Colors.transparent,
                      borderRadius: BorderRadius.circular(20),
                    ),
                    child: Column(
                      mainAxisAlignment: MainAxisAlignment.center,
                      children: [
                        AnimatedScale(
                          duration: const Duration(milliseconds: 220),
                          scale: selected ? 1.12 : 1,
                          child: Icon(
                            selected ? item.selected : item.icon,
                            size: 24,
                            color: selected ? AppColors.goldAccent : muted,
                          ),
                        ),
                        const SizedBox(height: 3),
                        Text(
                          item.label,
                          maxLines: 1,
                          overflow: TextOverflow.fade,
                          style: TextStyle(
                            color: selected
                                ? (dark
                                    ? AppColors.textLight
                                    : AppColors.primaryDark)
                                : muted,
                            fontSize: 10,
                            fontWeight:
                                selected ? FontWeight.w800 : FontWeight.w600,
                          ),
                        ),
                      ],
                    ),
                  ),
                ),
              ),
            );
          }),
        ),
      ),
    );
  }
}

class PlaceholderTabPage extends StatelessWidget {
  const PlaceholderTabPage({
    super.key,
    required this.title,
    required this.subtitle,
    this.dark = false,
  });

  final String title;
  final String subtitle;
  final bool dark;

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: dark ? AppColors.primaryDark : null,
      appBar: AppBar(
        title: Text(title),
        backgroundColor: dark ? AppColors.primaryDark : null,
        foregroundColor: dark ? AppColors.textLight : null,
      ),
      body: Center(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Text(
                title,
                style: Theme.of(context).textTheme.headlineSmall?.copyWith(
                      color: dark ? AppColors.goldAccent : AppColors.mutedGold,
                      fontWeight: FontWeight.w700,
                    ),
              ),
              const SizedBox(height: 12),
              Text(
                subtitle,
                textAlign: TextAlign.center,
                style: TextStyle(
                  color: dark ? AppColors.textLight.withOpacity(0.8) : null,
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class ProfileTabPage extends ConsumerStatefulWidget {
  const ProfileTabPage({super.key});

  @override
  ConsumerState<ProfileTabPage> createState() => _ProfileTabPageState();
}

class _ProfileTabPageState extends ConsumerState<ProfileTabPage> {
  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (ref.read(authControllerProvider).isAuthenticated) {
        ref.read(profileControllerProvider.notifier).load();
      }
    });
  }

  Future<void> _confirmDelete() async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('حذف الحساب'),
        content:
            const Text('سيتم تعطيل حسابك وتسجيل الخروج. هل تريد المتابعة؟'),
        actions: [
          TextButton(
              onPressed: () => Navigator.pop(ctx, false),
              child: const Text('إلغاء')),
          TextButton(
            onPressed: () => Navigator.pop(ctx, true),
            child: const Text('حذف', style: TextStyle(color: AppColors.error)),
          ),
        ],
      ),
    );
    if (ok != true) return;
    final deleted =
        await ref.read(profileControllerProvider.notifier).deleteAccount();
    if (deleted && mounted) context.go('/home');
  }

  @override
  Widget build(BuildContext context) {
    final auth = ref.watch(authControllerProvider);
    final profile = ref.watch(profileControllerProvider);
    final themeMode = ref.watch(themeModeControllerProvider);
    final user = auth.user;
    if (!auth.isAuthenticated) {
      return Scaffold(
        appBar: AppBar(title: const Text('حسابي')),
        body: ListView(
          padding: const EdgeInsets.fromLTRB(20, 28, 20, 24),
          children: [
            Container(
              padding: const EdgeInsets.all(24),
              decoration: BoxDecoration(
                gradient: const LinearGradient(
                  begin: Alignment.topRight,
                  end: Alignment.bottomLeft,
                  colors: [AppColors.primaryDark, Color(0xFF292218)],
                ),
                borderRadius: BorderRadius.circular(28),
                boxShadow: const [
                  BoxShadow(
                    color: Color(0x28000000),
                    blurRadius: 28,
                    offset: Offset(0, 12),
                  ),
                ],
              ),
              child: Column(
                children: [
                  const CircleAvatar(
                    radius: 34,
                    backgroundColor: Color(0x22D9A441),
                    child: Icon(
                      Icons.person_rounded,
                      color: AppColors.goldAccent,
                      size: 36,
                    ),
                  ),
                  const SizedBox(height: 18),
                  const Text(
                    'تتصفح الآن كضيف',
                    style: TextStyle(
                      color: AppColors.textLight,
                      fontSize: 21,
                      fontWeight: FontWeight.w800,
                    ),
                  ),
                  const SizedBox(height: 8),
                  const Text(
                    'أنشئ حسابك برقم الهاتف عند رغبتك بالشراء أو حفظ المفضلة.',
                    textAlign: TextAlign.center,
                    style: TextStyle(color: Colors.white70, height: 1.5),
                  ),
                  const SizedBox(height: 20),
                  FilledButton.icon(
                    onPressed: () =>
                        context.push('/auth/phone?returnTo=/profile'),
                    icon: const Icon(Icons.login_rounded),
                    label: const Text('تسجيل الدخول'),
                  ),
                ],
              ),
            ),
            const SizedBox(height: 22),
            Card(
              child: Column(
                children: [
                  ListTile(
                    leading: const Icon(Icons.shopping_bag_outlined),
                    title: const Text('ابدأ التسوق'),
                    subtitle: const Text('شاهد المنتجات والعروض بدون حساب'),
                    trailing: const Icon(Icons.chevron_left_rounded),
                    onTap: () => context.go('/store'),
                  ),
                  const Divider(height: 1, indent: 64),
                  ListTile(
                    leading: const Icon(Icons.play_circle_outline_rounded),
                    title: const Text('شاهد الجديد'),
                    subtitle: const Text('تصفح الفيديوهات مباشرة'),
                    trailing: const Icon(Icons.chevron_left_rounded),
                    onTap: () => context.go('/home'),
                  ),
                ],
              ),
            ),
          ],
        ),
      );
    }
    final displayName = profile.name.isNotEmpty
        ? profile.name
        : (user?.name.isNotEmpty == true ? user!.name : 'مستخدم Finora');
    final displayPhone =
        profile.phone.isNotEmpty ? profile.phone : (user?.phone ?? '');
    return Scaffold(
      appBar: AppBar(title: const Text('حسابي')),
      body: RefreshIndicator(
        onRefresh: () => ref.read(profileControllerProvider.notifier).load(),
        child: ListView(
          padding: const EdgeInsets.fromLTRB(18, 8, 18, 28),
          children: [
            _ProfileHero(
              name: displayName,
              phone: displayPhone,
              tier: profile.rewardsTier,
              completion: profile.profileCompletion,
              onEdit: () => context.push('/profile/edit'),
            ),
            const SizedBox(height: 16),
            Row(
              children: [
                Expanded(
                  child: _ProfileStat(
                    icon: Icons.receipt_long_rounded,
                    label: 'الطلبات',
                    value: '${profile.ordersCount}',
                    onTap: () => context.push('/profile/orders'),
                  ),
                ),
                const SizedBox(width: 10),
                Expanded(
                  child: _ProfileStat(
                    icon: Icons.account_balance_wallet_outlined,
                    label: 'المشتريات',
                    value: _compactMoney(profile.totalSpent),
                  ),
                ),
                const SizedBox(width: 10),
                Expanded(
                  child: _ProfileStat(
                    icon: Icons.stars_rounded,
                    label: 'النقاط',
                    value: '${profile.rewardsBalance}',
                    onTap: () => context.go('/rewards'),
                  ),
                ),
              ],
            ),
            const SizedBox(height: 16),
            _PersonalizationCard(
              categories: profile.preferredCategories,
              favoritesCount: profile.favoritesCount,
              videoViews: profile.videoViews,
              onAskAi: () => context.go('/ai'),
            ),
            const SizedBox(height: 16),
            Card(
              child: Column(
                children: [
                  _AccountTile(
                    icon: Icons.location_on_outlined,
                    title: 'عناويني',
                    subtitle: 'إدارة عناوين التوصيل',
                    onTap: () => context.push('/profile/addresses'),
                  ),
                  const Divider(indent: 62),
                  _AccountTile(
                    icon: Icons.favorite_outline_rounded,
                    title: 'المحتوى المفضل',
                    subtitle: 'الفيديوهات التي أعجبتك',
                    onTap: () => context.push('/profile/liked-videos'),
                  ),
                  const Divider(indent: 62),
                  _AccountTile(
                    icon: Icons.bookmark_outline_rounded,
                    title: 'المحفوظات',
                    subtitle: 'ارجع لها بأي وقت',
                    onTap: () => context.push('/profile/saved-videos'),
                  ),
                  const Divider(indent: 62),
                  _AccountTile(
                    icon: Icons.notifications_outlined,
                    title: 'الإشعارات',
                    subtitle: 'الطلبات والعروض والردود',
                    onTap: () => context.push('/profile/notifications'),
                  ),
                  const Divider(indent: 62),
                  _AccountTile(
                    icon: Icons.shopping_cart_outlined,
                    title: 'العربة',
                    subtitle: 'أكمل المنتجات التي اخترتها',
                    onTap: () => context.push('/cart'),
                  ),
                ],
              ),
            ),
            const SizedBox(height: 14),
            Card(
              child: Padding(
                padding: const EdgeInsets.fromLTRB(16, 14, 16, 16),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const Row(
                      children: [
                        Icon(Icons.palette_outlined),
                        SizedBox(width: 10),
                        Text(
                          'مظهر التطبيق',
                          style: TextStyle(fontWeight: FontWeight.w800),
                        ),
                      ],
                    ),
                    const SizedBox(height: 14),
                    SizedBox(
                      width: double.infinity,
                      child: SegmentedButton<ThemeMode>(
                        segments: const [
                          ButtonSegment(
                            value: ThemeMode.system,
                            icon: Icon(Icons.brightness_auto_outlined),
                            label: Text('تلقائي'),
                          ),
                          ButtonSegment(
                            value: ThemeMode.light,
                            icon: Icon(Icons.light_mode_outlined),
                            label: Text('فاتح'),
                          ),
                          ButtonSegment(
                            value: ThemeMode.dark,
                            icon: Icon(Icons.dark_mode_outlined),
                            label: Text('داكن'),
                          ),
                        ],
                        selected: {themeMode},
                        showSelectedIcon: false,
                        onSelectionChanged: (selection) => ref
                            .read(themeModeControllerProvider.notifier)
                            .setMode(selection.first),
                      ),
                    ),
                  ],
                ),
              ),
            ),
            const SizedBox(height: 14),
            const Divider(),
            ListTile(
              leading: const Icon(Icons.delete_forever_outlined,
                  color: AppColors.error),
              title: const Text('حذف الحساب'),
              onTap: _confirmDelete,
            ),
            ListTile(
              leading: const Icon(Icons.logout, color: AppColors.error),
              title: const Text('تسجيل الخروج'),
              onTap: () async {
                await ref.read(authControllerProvider.notifier).logout();
                if (context.mounted) context.go('/home');
              },
            ),
          ],
        ),
      ),
    );
  }
}

class _ProfileHero extends StatelessWidget {
  const _ProfileHero({
    required this.name,
    required this.phone,
    required this.tier,
    required this.completion,
    required this.onEdit,
  });

  final String name;
  final String phone;
  final String tier;
  final int completion;
  final VoidCallback onEdit;

  @override
  Widget build(BuildContext context) {
    final safeCompletion = completion.clamp(0, 100);
    return Container(
      padding: const EdgeInsets.all(20),
      decoration: BoxDecoration(
        gradient: const LinearGradient(
          begin: Alignment.topRight,
          end: Alignment.bottomLeft,
          colors: [AppColors.primaryDark, Color(0xFF342814)],
        ),
        borderRadius: BorderRadius.circular(28),
        boxShadow: const [
          BoxShadow(
            color: Color(0x26000000),
            blurRadius: 24,
            offset: Offset(0, 12),
          ),
        ],
      ),
      child: Column(
        children: [
          Row(
            children: [
              CircleAvatar(
                radius: 31,
                backgroundColor: const Color(0x24E7B84B),
                child: Text(
                  name.isNotEmpty ? name.characters.first.toUpperCase() : 'F',
                  style: const TextStyle(
                    color: AppColors.goldAccent,
                    fontSize: 25,
                    fontWeight: FontWeight.w900,
                  ),
                ),
              ),
              const SizedBox(width: 14),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      name,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: const TextStyle(
                        color: Colors.white,
                        fontSize: 20,
                        fontWeight: FontWeight.w900,
                      ),
                    ),
                    const SizedBox(height: 3),
                    Text(
                      phone,
                      textDirection: TextDirection.ltr,
                      style: const TextStyle(color: Colors.white60),
                    ),
                  ],
                ),
              ),
              IconButton.filledTonal(
                tooltip: 'تعديل الحساب',
                onPressed: onEdit,
                style: IconButton.styleFrom(
                  backgroundColor: Colors.white12,
                  foregroundColor: Colors.white,
                ),
                icon: const Icon(Icons.edit_rounded),
              ),
            ],
          ),
          const SizedBox(height: 18),
          Row(
            children: [
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      tier.isEmpty ? 'عضو Finora' : tier,
                      style: const TextStyle(
                        color: AppColors.goldAccent,
                        fontWeight: FontWeight.w800,
                      ),
                    ),
                    const SizedBox(height: 7),
                    ClipRRect(
                      borderRadius: BorderRadius.circular(99),
                      child: LinearProgressIndicator(
                        minHeight: 7,
                        value: safeCompletion / 100,
                        backgroundColor: Colors.white12,
                        valueColor: const AlwaysStoppedAnimation(
                          AppColors.goldAccent,
                        ),
                      ),
                    ),
                  ],
                ),
              ),
              const SizedBox(width: 14),
              Text(
                'اكتمال $safeCompletion%',
                style: const TextStyle(
                  color: Colors.white70,
                  fontSize: 12,
                  fontWeight: FontWeight.w700,
                ),
              ),
            ],
          ),
        ],
      ),
    );
  }
}

class _ProfileStat extends StatelessWidget {
  const _ProfileStat({
    required this.icon,
    required this.label,
    required this.value,
    this.onTap,
  });

  final IconData icon;
  final String label;
  final String value;
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) {
    return Card(
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(22),
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 14),
          child: Column(
            children: [
              Icon(icon, color: AppColors.mutedGold, size: 22),
              const SizedBox(height: 7),
              Text(
                value,
                maxLines: 1,
                style: const TextStyle(fontWeight: FontWeight.w900),
              ),
              const SizedBox(height: 2),
              Text(
                label,
                style: TextStyle(
                  fontSize: 11,
                  color: Theme.of(context).colorScheme.onSurfaceVariant,
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _PersonalizationCard extends StatelessWidget {
  const _PersonalizationCard({
    required this.categories,
    required this.favoritesCount,
    required this.videoViews,
    required this.onAskAi,
  });

  final List<String> categories;
  final int favoritesCount;
  final int videoViews;
  final VoidCallback onAskAi;

  @override
  Widget build(BuildContext context) {
    final visibleCategories = categories.take(4).toList();
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Row(
              children: [
                Icon(Icons.auto_awesome_rounded, color: AppColors.mutedGold),
                SizedBox(width: 9),
                Expanded(
                  child: Text(
                    'تجربتك الشخصية',
                    style: TextStyle(fontWeight: FontWeight.w900, fontSize: 16),
                  ),
                ),
              ],
            ),
            const SizedBox(height: 7),
            Text(
              favoritesCount == 0 && videoViews == 0
                  ? 'كلما تفاعلت أكثر، تصير اقتراحات Finora أدق لك.'
                  : 'نستخدم تفاعلك ومفضلاتك حتى نرتب اقتراحات أنسب لك.',
              style: TextStyle(
                color: Theme.of(context).colorScheme.onSurfaceVariant,
              ),
            ),
            if (visibleCategories.isNotEmpty) ...[
              const SizedBox(height: 12),
              Wrap(
                spacing: 7,
                runSpacing: 7,
                children: [
                  for (final category in visibleCategories)
                    Chip(label: Text(category)),
                ],
              ),
            ],
            const SizedBox(height: 12),
            SizedBox(
              width: double.infinity,
              child: FilledButton.tonalIcon(
                onPressed: onAskAi,
                icon: const Icon(Icons.auto_awesome_rounded),
                label: const Text('اسأل مساعدك الشخصي'),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _AccountTile extends StatelessWidget {
  const _AccountTile({
    required this.icon,
    required this.title,
    required this.subtitle,
    required this.onTap,
  });

  final IconData icon;
  final String title;
  final String subtitle;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return ListTile(
      leading: Container(
        width: 40,
        height: 40,
        decoration: BoxDecoration(
          color: AppColors.goldAccent.withOpacity(0.1),
          borderRadius: BorderRadius.circular(13),
        ),
        child: Icon(icon, color: AppColors.mutedGold, size: 21),
      ),
      title: Text(title, style: const TextStyle(fontWeight: FontWeight.w800)),
      subtitle: Text(subtitle),
      trailing: const Icon(Icons.chevron_left_rounded),
      onTap: onTap,
    );
  }
}

String _compactMoney(int value) {
  if (value >= 1000000) {
    final amount = value / 1000000;
    return '${amount.toStringAsFixed(amount >= 10 ? 0 : 1)}م';
  }
  if (value >= 1000) return '${(value / 1000).toStringAsFixed(0)}ألف';
  return '$value';
}
