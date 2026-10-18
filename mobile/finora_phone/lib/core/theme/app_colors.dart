import 'package:flutter/material.dart';

/// Finora Phone visual tokens — charcoal + warm gold (not purple / cream defaults).
abstract final class AppColors {
  static const Color primaryDark = Color(0xFF07090E);
  static const Color ink = Color(0xFF0C1018);
  static const Color surfaceDark = Color(0xFF141821);
  static const Color elevatedDark = Color(0xFF1C222E);
  static const Color hairlineDark = Color(0xFF2A3140);

  static const Color softWhite = Color(0xFFF5F6F8);
  static const Color mist = Color(0xFFECEEF2);
  static const Color surfaceLight = Color(0xFFFFFFFF);
  static const Color lineLight = Color(0xFFDDE1E8);
  static const Color hairlineLight = Color(0xFFE8EBF0);

  static const Color goldAccent = Color(0xFFE2B04A);
  static const Color goldBright = Color(0xFFF0C96A);
  static const Color mutedGold = Color(0xFFB07D28);
  static const Color goldWash = Color(0x33E2B04A);

  static const Color textDark = Color(0xFF0E1218);
  static const Color textLight = Color(0xFFF6F7F9);
  static const Color textMutedLight = Color(0xFF6A7280);
  static const Color textMutedDark = Color(0xFF98A0B0);

  static const Color info = Color(0xFF5B8DEF);
  static const Color error = Color(0xFFE05656);
  static const Color success = Color(0xFF2F9E68);
  static const Color warning = Color(0xFFE09A3E);

  static const LinearGradient darkAtmosphere = LinearGradient(
    begin: Alignment.topRight,
    end: Alignment.bottomLeft,
    colors: [
      Color(0xFF0E121A),
      Color(0xFF07090E),
      Color(0xFF121018),
    ],
    stops: [0.0, 0.55, 1.0],
  );

  static const LinearGradient lightAtmosphere = LinearGradient(
    begin: Alignment.topCenter,
    end: Alignment.bottomCenter,
    colors: [
      Color(0xFFF8F6F1),
      Color(0xFFF1F3F7),
      Color(0xFFEAECEF),
    ],
  );

  static const LinearGradient goldSheen = LinearGradient(
    begin: Alignment.topLeft,
    end: Alignment.bottomRight,
    colors: [Color(0xFFF0C96A), Color(0xFFC9962E)],
  );
}
