import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import 'app_colors.dart';
import '../ui/finora_ui.dart';

abstract final class AppTheme {
  static TextTheme _textTheme(Brightness brightness) {
    final base = brightness == Brightness.dark
        ? AppColors.textLight
        : AppColors.textDark;
    final muted = brightness == Brightness.dark
        ? AppColors.textMutedDark
        : AppColors.textMutedLight;
    return TextTheme(
      displayLarge: TextStyle(
        fontFamily: 'Noto Sans Arabic',
        fontSize: 40,
        fontWeight: FontWeight.w800,
        height: 1.15,
        letterSpacing: -0.5,
        color: base,
      ),
      headlineLarge: TextStyle(
        fontFamily: 'Noto Sans Arabic',
        fontSize: 28,
        fontWeight: FontWeight.w800,
        height: 1.2,
        color: base,
      ),
      headlineMedium: TextStyle(
        fontFamily: 'Noto Sans Arabic',
        fontSize: 22,
        fontWeight: FontWeight.w800,
        height: 1.25,
        color: base,
      ),
      headlineSmall: TextStyle(
        fontFamily: 'Noto Sans Arabic',
        fontSize: 18,
        fontWeight: FontWeight.w700,
        height: 1.3,
        color: base,
      ),
      titleLarge: TextStyle(
        fontFamily: 'Noto Sans Arabic',
        fontSize: 17,
        fontWeight: FontWeight.w700,
        color: base,
      ),
      titleMedium: TextStyle(
        fontFamily: 'Noto Sans Arabic',
        fontSize: 15,
        fontWeight: FontWeight.w600,
        color: base,
      ),
      bodyLarge: TextStyle(
        fontFamily: 'Noto Sans Arabic',
        fontSize: 15,
        fontWeight: FontWeight.w500,
        height: 1.45,
        color: base,
      ),
      bodyMedium: TextStyle(
        fontFamily: 'Noto Sans Arabic',
        fontSize: 13.5,
        fontWeight: FontWeight.w400,
        height: 1.45,
        color: muted,
      ),
      bodySmall: TextStyle(
        fontFamily: 'Noto Sans Arabic',
        fontSize: 12,
        fontWeight: FontWeight.w400,
        height: 1.4,
        color: muted,
      ),
      labelLarge: TextStyle(
        fontFamily: 'Noto Sans Arabic',
        fontSize: 14,
        fontWeight: FontWeight.w700,
        color: base,
      ),
    );
  }

  static ThemeData get light {
    final text = _textTheme(Brightness.light);
    final base = ThemeData(
      useMaterial3: true,
      brightness: Brightness.light,
      colorScheme: const ColorScheme.light(
        primary: AppColors.goldAccent,
        onPrimary: AppColors.ink,
        secondary: AppColors.mutedGold,
        surface: AppColors.surfaceLight,
        onSurface: AppColors.textDark,
        error: AppColors.error,
      ),
      scaffoldBackgroundColor: AppColors.softWhite,
      fontFamily: 'Noto Sans Arabic',
      textTheme: text,
    );
    return _polish(base, dark: false);
  }

  static ThemeData get dark {
    final text = _textTheme(Brightness.dark);
    final base = ThemeData(
      useMaterial3: true,
      brightness: Brightness.dark,
      colorScheme: const ColorScheme.dark(
        primary: AppColors.goldAccent,
        onPrimary: AppColors.ink,
        secondary: AppColors.mutedGold,
        surface: AppColors.surfaceDark,
        onSurface: AppColors.textLight,
        error: AppColors.error,
      ),
      scaffoldBackgroundColor: AppColors.primaryDark,
      fontFamily: 'Noto Sans Arabic',
      textTheme: text,
    );
    return _polish(base, dark: true);
  }

  static ThemeData _polish(ThemeData base, {required bool dark}) {
    final line = dark ? AppColors.hairlineDark : AppColors.lineLight;
    final surface = dark ? AppColors.elevatedDark : AppColors.surfaceLight;
    final bg = dark ? AppColors.primaryDark : AppColors.softWhite;

    return base.copyWith(
      appBarTheme: AppBarTheme(
        backgroundColor: Colors.transparent,
        foregroundColor: dark ? AppColors.textLight : AppColors.textDark,
        elevation: 0,
        centerTitle: true,
        scrolledUnderElevation: 0,
        systemOverlayStyle:
            dark ? SystemUiOverlayStyle.light : SystemUiOverlayStyle.dark,
        titleTextStyle: base.textTheme.titleLarge,
      ),
      dividerTheme: DividerThemeData(color: line, thickness: 1, space: 1),
      chipTheme: ChipThemeData(
        backgroundColor: dark ? AppColors.goldWash : const Color(0x22E2B04A),
        labelStyle: base.textTheme.bodySmall?.copyWith(
          color: dark ? AppColors.goldBright : AppColors.mutedGold,
          fontWeight: FontWeight.w600,
        ),
        side: BorderSide.none,
        padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 0),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(20)),
      ),
      filledButtonTheme: FilledButtonThemeData(
        style: FilledButton.styleFrom(
          backgroundColor: AppColors.goldAccent,
          foregroundColor: AppColors.ink,
          // Height only — an infinite minimum width collapses Row siblings.
          minimumSize: const Size(0, 50),
          padding: const EdgeInsets.symmetric(horizontal: 20),
          elevation: 0,
          textStyle: const TextStyle(
            fontFamily: 'Noto Sans Arabic',
            fontWeight: FontWeight.w800,
            fontSize: 15,
          ),
          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
        ),
      ),
      outlinedButtonTheme: OutlinedButtonThemeData(
        style: OutlinedButton.styleFrom(
          foregroundColor: dark ? AppColors.textLight : AppColors.textDark,
          minimumSize: const Size(0, 48),
          padding: const EdgeInsets.symmetric(horizontal: 20),
          side: BorderSide(color: line),
          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
        ),
      ),
      textButtonTheme: TextButtonThemeData(
        style: TextButton.styleFrom(
          foregroundColor: AppColors.mutedGold,
          textStyle: const TextStyle(
            fontFamily: 'Noto Sans Arabic',
            fontWeight: FontWeight.w700,
          ),
        ),
      ),
      floatingActionButtonTheme: FloatingActionButtonThemeData(
        backgroundColor: AppColors.success,
        foregroundColor: Colors.white,
        elevation: 0,
        highlightElevation: 0,
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(22)),
      ),
      inputDecorationTheme: InputDecorationTheme(
        filled: true,
        fillColor: surface,
        contentPadding:
            const EdgeInsets.symmetric(horizontal: 18, vertical: 16),
        labelStyle: TextStyle(
          color: dark ? AppColors.textMutedDark : AppColors.textMutedLight,
        ),
        border: OutlineInputBorder(
          borderRadius: BorderRadius.circular(16),
          borderSide: BorderSide(color: line),
        ),
        enabledBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(16),
          borderSide: BorderSide(color: line),
        ),
        focusedBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(16),
          borderSide: const BorderSide(color: AppColors.goldAccent, width: 1.6),
        ),
      ),
      cardTheme: CardTheme(
        elevation: 0,
        color: surface,
        margin: EdgeInsets.zero,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(20),
          side: BorderSide(color: line.withOpacity(0.85)),
        ),
      ),
      listTileTheme: ListTileThemeData(
        contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 4),
        iconColor: dark ? AppColors.goldBright : AppColors.mutedGold,
        titleTextStyle: base.textTheme.titleMedium,
        subtitleTextStyle: base.textTheme.bodyMedium,
      ),
      snackBarTheme: SnackBarThemeData(
        behavior: SnackBarBehavior.floating,
        backgroundColor: dark ? AppColors.elevatedDark : AppColors.ink,
        contentTextStyle: const TextStyle(
          fontFamily: 'Noto Sans Arabic',
          color: AppColors.textLight,
        ),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(14)),
      ),
      bottomSheetTheme: BottomSheetThemeData(
        backgroundColor: surface,
        modalBackgroundColor: surface,
        shape: const RoundedRectangleBorder(
          borderRadius: BorderRadius.vertical(top: Radius.circular(28)),
        ),
        showDragHandle: true,
        dragHandleColor: line,
      ),
      navigationBarTheme: NavigationBarThemeData(
        backgroundColor: dark ? const Color(0xE6141821) : const Color(0xF2FFFFFF),
        indicatorColor: AppColors.goldWash,
        elevation: 0,
        height: kFinoraNavBarHeight,
        labelTextStyle: MaterialStateProperty.resolveWith((states) {
          final selected = states.contains(MaterialState.selected);
          return TextStyle(
            fontFamily: 'Noto Sans Arabic',
            fontSize: 11.5,
            fontWeight: selected ? FontWeight.w800 : FontWeight.w500,
            color: selected
                ? (dark ? AppColors.goldBright : AppColors.mutedGold)
                : (dark ? AppColors.textMutedDark : AppColors.textMutedLight),
          );
        }),
        iconTheme: MaterialStateProperty.resolveWith((states) {
          final selected = states.contains(MaterialState.selected);
          return IconThemeData(
            size: 22,
            color: selected
                ? (dark ? AppColors.goldBright : AppColors.mutedGold)
                : (dark ? AppColors.textMutedDark : AppColors.textMutedLight),
          );
        }),
      ),
      dialogTheme: DialogTheme(
        backgroundColor: surface,
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(22)),
      ),
      scaffoldBackgroundColor: bg,
    );
  }
}
