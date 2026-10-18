import 'package:flutter/material.dart';

import '../theme/app_colors.dart';

/// Height of the shell navigation bar, excluding the system gesture area.
const double kFinoraNavBarHeight = 68;

/// Space the shell navigation bar covers at the bottom of a branch page.
///
/// Branch pages render behind the bar, so floating content must clear it.
double finoraShellBottomInset(BuildContext context) =>
    kFinoraNavBarHeight + MediaQuery.viewPaddingOf(context).bottom;

/// Soft atmospheric backdrop for Finora Phone screens.
class FinoraScaffold extends StatelessWidget {
  const FinoraScaffold({
    super.key,
    required this.body,
    this.appBar,
    this.floatingActionButton,
    this.bottomNavigationBar,
    this.extendBody = false,
  });

  final Widget body;
  final PreferredSizeWidget? appBar;
  final Widget? floatingActionButton;
  final Widget? bottomNavigationBar;
  final bool extendBody;

  @override
  Widget build(BuildContext context) {
    final dark = Theme.of(context).brightness == Brightness.dark;
    return Scaffold(
      extendBody: extendBody,
      extendBodyBehindAppBar: appBar != null,
      appBar: appBar,
      floatingActionButton: floatingActionButton,
      bottomNavigationBar: bottomNavigationBar,
      body: DecoratedBox(
        decoration: BoxDecoration(
          gradient: dark ? AppColors.darkAtmosphere : AppColors.lightAtmosphere,
        ),
        child: Stack(
          fit: StackFit.expand,
          children: [
            Positioned(
              top: -80,
              left: dark ? -40 : null,
              right: dark ? null : -60,
              child: IgnorePointer(
                child: Container(
                  width: 220,
                  height: 220,
                  decoration: BoxDecoration(
                    shape: BoxShape.circle,
                    gradient: RadialGradient(
                      colors: [
                        AppColors.goldAccent.withOpacity(dark ? 0.14 : 0.10),
                        Colors.transparent,
                      ],
                    ),
                  ),
                ),
              ),
            ),
            body,
          ],
        ),
      ),
    );
  }
}

class FinoraEmptyState extends StatelessWidget {
  const FinoraEmptyState({
    super.key,
    required this.icon,
    required this.title,
    this.subtitle,
  });

  final IconData icon;
  final String title;
  final String? subtitle;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(32),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Container(
              width: 72,
              height: 72,
              decoration: BoxDecoration(
                shape: BoxShape.circle,
                color: AppColors.goldWash,
                border: Border.all(
                  color: AppColors.goldAccent.withOpacity(0.35),
                ),
              ),
              child: Icon(icon, color: AppColors.goldAccent, size: 32),
            ),
            const SizedBox(height: 18),
            Text(title, style: theme.textTheme.titleLarge, textAlign: TextAlign.center),
            if (subtitle != null) ...[
              const SizedBox(height: 8),
              Text(
                subtitle!,
                style: theme.textTheme.bodyMedium,
                textAlign: TextAlign.center,
              ),
            ],
          ],
        ),
      ),
    );
  }
}

class FinoraAvatar extends StatelessWidget {
  const FinoraAvatar({
    super.key,
    required this.label,
    this.size = 44,
    this.highlighted = false,
  });

  final String label;
  final double size;
  final bool highlighted;

  @override
  Widget build(BuildContext context) {
    final trimmed = label.trim();
    final letter = trimmed.isEmpty
        ? '?'
        : String.fromCharCode(trimmed.runes.first);
    return Container(
      width: size,
      height: size,
      alignment: Alignment.center,
      decoration: BoxDecoration(
        shape: BoxShape.circle,
        gradient: highlighted ? AppColors.goldSheen : null,
        color: highlighted ? null : AppColors.goldWash,
        border: Border.all(
          color: AppColors.goldAccent.withOpacity(highlighted ? 0.0 : 0.28),
        ),
      ),
      child: Text(
        letter,
        style: TextStyle(
          fontFamily: 'Noto Sans Arabic',
          fontWeight: FontWeight.w800,
          fontSize: size * 0.38,
          color: highlighted ? AppColors.ink : AppColors.goldAccent,
        ),
      ),
    );
  }
}

class FinoraSectionHeader extends StatelessWidget {
  const FinoraSectionHeader(this.title, {super.key, this.trailing});

  final String title;
  final Widget? trailing;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.fromLTRB(4, 8, 4, 10),
      child: Row(
        children: [
          Container(
            width: 3,
            height: 14,
            decoration: BoxDecoration(
              color: AppColors.goldAccent,
              borderRadius: BorderRadius.circular(2),
            ),
          ),
          const SizedBox(width: 8),
          Expanded(
            child: Text(title, style: Theme.of(context).textTheme.titleMedium),
          ),
          if (trailing != null) trailing!,
        ],
      ),
    );
  }
}

class FinoraSurface extends StatelessWidget {
  const FinoraSurface({
    super.key,
    required this.child,
    this.padding = const EdgeInsets.all(16),
    this.onTap,
  });

  final Widget child;
  final EdgeInsetsGeometry padding;
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) {
    final dark = Theme.of(context).brightness == Brightness.dark;
    final box = Container(
      padding: padding,
      decoration: BoxDecoration(
        color: dark ? AppColors.elevatedDark.withOpacity(0.92) : Colors.white.withOpacity(0.92),
        borderRadius: BorderRadius.circular(20),
        border: Border.all(
          color: dark ? AppColors.hairlineDark : AppColors.hairlineLight,
        ),
      ),
      child: child,
    );
    if (onTap == null) return box;
    return Material(
      color: Colors.transparent,
      child: InkWell(
        borderRadius: BorderRadius.circular(20),
        onTap: onTap,
        child: box,
      ),
    );
  }
}

class FinoraBrandMark extends StatelessWidget {
  const FinoraBrandMark({super.key, this.compact = false});

  final bool compact;

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.center,
      children: [
        Text(
          'FINORA',
          style: Theme.of(context).textTheme.displayLarge?.copyWith(
                fontSize: compact ? 28 : 40,
                letterSpacing: 4,
                color: AppColors.goldAccent,
              ),
        ),
        Text(
          'PHONE',
          style: Theme.of(context).textTheme.titleMedium?.copyWith(
                letterSpacing: 8,
                fontWeight: FontWeight.w600,
                color: Theme.of(context).brightness == Brightness.dark
                    ? AppColors.textMutedDark
                    : AppColors.textMutedLight,
              ),
        ),
      ],
    );
  }
}
