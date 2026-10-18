import 'dart:io';
import 'dart:math' as math;

import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:open_filex/open_filex.dart';
import 'package:package_info_plus/package_info_plus.dart';
import 'package:path_provider/path_provider.dart';

import '../config/app_config.dart';
import '../theme/app_colors.dart';
import 'bootstrap_controller.dart';

int compareSemver(String left, String right) {
  List<int> parts(String raw) => raw
      .split('.')
      .map((part) => int.tryParse(part.trim()) ?? 0)
      .toList(growable: false);

  final a = parts(left);
  final b = parts(right);
  final len = math.max(a.length, b.length);
  for (var i = 0; i < len; i++) {
    final av = i < a.length ? a[i] : 0;
    final bv = i < b.length ? b[i] : 0;
    if (av != bv) return av.compareTo(bv);
  }
  return 0;
}

bool isBuildOlder({
  required String currentVersion,
  required int currentBuild,
  required String targetVersion,
  required int targetBuild,
}) {
  final byName = compareSemver(currentVersion, targetVersion);
  if (byName != 0) return byName < 0;
  return currentBuild < targetBuild;
}

String resolveApkUrl(String raw) {
  final value = raw.trim();
  if (value.isEmpty) return '';
  if (value.startsWith('http://') || value.startsWith('https://')) {
    return value;
  }
  final base = AppConfig.apiBaseUrl.replaceAll(RegExp(r'/$'), '');
  if (value.startsWith('/')) return '$base$value';
  return '$base/$value';
}

/// Blocks the app when a newer Social APK is published on the server.
class AppUpdateGate extends ConsumerStatefulWidget {
  const AppUpdateGate({super.key, required this.child});

  final Widget child;

  @override
  ConsumerState<AppUpdateGate> createState() => _AppUpdateGateState();
}

class _AppUpdateGateState extends ConsumerState<AppUpdateGate> {
  PackageInfo? _packageInfo;
  bool _dismissedOptional = false;
  bool _downloading = false;
  double _progress = 0;
  String? _downloadError;
  CancelToken? _cancelToken;

  @override
  void initState() {
    super.initState();
    _loadPackageInfo();
  }

  Future<void> _loadPackageInfo() async {
    final info = await PackageInfo.fromPlatform();
    if (!mounted) return;
    setState(() => _packageInfo = info);
  }

  @override
  void dispose() {
    _cancelToken?.cancel('disposed');
    super.dispose();
  }

  Future<void> _startUpdate(AppUpdateInfo update) async {
    final url = resolveApkUrl(update.apkUrl);
    if (url.isEmpty) {
      setState(() => _downloadError = 'رابط التحديث غير متوفر.');
      return;
    }
    if (!Platform.isAndroid) {
      setState(() => _downloadError = 'التحديث التلقائي متاح على Android فقط.');
      return;
    }

    setState(() {
      _downloading = true;
      _progress = 0;
      _downloadError = null;
    });

    final token = CancelToken();
    _cancelToken = token;

    try {
      final dir = await getTemporaryDirectory();
      final file = File(
        '${dir.path}/finora-social-${update.latestVersion}+${update.latestBuild}.apk',
      );
      if (await file.exists()) {
        await file.delete();
      }

      final dio = Dio(
        BaseOptions(
          connectTimeout: const Duration(seconds: 30),
          receiveTimeout: const Duration(minutes: 10),
          headers: const {'X-Tenant-Slug': AppConfig.tenantSlug},
        ),
      );
      await dio.download(
        url,
        file.path,
        cancelToken: token,
        onReceiveProgress: (received, total) {
          if (!mounted || total <= 0) return;
          setState(() => _progress = (received / total).clamp(0.0, 1.0));
        },
      );

      if (!mounted) return;
      setState(() {
        _downloading = false;
        _progress = 1;
      });

      final result = await OpenFilex.open(
        file.path,
        type: 'application/vnd.android.package-archive',
      );
      if (!mounted) return;
      if (result.type != ResultType.done) {
        setState(() {
          _downloadError =
              result.message.isNotEmpty ? result.message : 'تعذر فتح ملف التثبيت.';
        });
      }
    } on DioException catch (e) {
      if (!mounted || CancelToken.isCancel(e)) return;
      setState(() {
        _downloading = false;
        _downloadError = e.message ?? 'فشل تنزيل التحديث.';
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _downloading = false;
        _downloadError = e.toString();
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    final boot = ref.watch(bootstrapControllerProvider);
    final info = _packageInfo;

    if (boot.isLoading ||
        boot.error != null ||
        boot.maintenance ||
        info == null ||
        _dismissedOptional) {
      return widget.child;
    }

    final update = boot.appUpdate;
    final currentBuild = int.tryParse(info.buildNumber) ?? 0;
    final belowMin = isBuildOlder(
      currentVersion: info.version,
      currentBuild: currentBuild,
      targetVersion: update.minVersion,
      targetBuild: update.minBuild,
    );
    final belowLatest = isBuildOlder(
      currentVersion: info.version,
      currentBuild: currentBuild,
      targetVersion: update.latestVersion,
      targetBuild: update.latestBuild,
    );

    if (!belowLatest && !belowMin) {
      return widget.child;
    }

    final force = belowMin || update.force;

    return Stack(
      fit: StackFit.expand,
      children: [
        widget.child,
        Material(
          color: const Color(0xCC0B1020),
          child: SafeArea(
            child: Center(
              child: SingleChildScrollView(
                padding: const EdgeInsets.all(24),
                child: Container(
                  constraints: const BoxConstraints(maxWidth: 420),
                  padding: const EdgeInsets.all(26),
                  decoration: BoxDecoration(
                    color: Colors.white,
                    borderRadius: BorderRadius.circular(28),
                    border: Border.all(color: AppColors.lineLight),
                    boxShadow: const [
                      BoxShadow(
                        color: Color(0x22000000),
                        blurRadius: 28,
                        offset: Offset(0, 14),
                      ),
                    ],
                  ),
                  child: Column(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      Container(
                        width: 72,
                        height: 72,
                        decoration: const BoxDecoration(
                          color: Color(0xFFFFF2D8),
                          shape: BoxShape.circle,
                        ),
                        child: const Icon(
                          Icons.system_update_rounded,
                          color: AppColors.mutedGold,
                          size: 34,
                        ),
                      ),
                      const SizedBox(height: 18),
                      Text(
                        force ? 'تحديث مطلوب' : 'يتوفر تحديث',
                        style: const TextStyle(
                          color: AppColors.textDark,
                          fontSize: 23,
                          fontWeight: FontWeight.w800,
                        ),
                      ),
                      const SizedBox(height: 10),
                      Text(
                        update.message.isNotEmpty
                            ? update.message
                            : 'نسخة جديدة جاهزة للتثبيت مباشرة من التطبيق.',
                        textAlign: TextAlign.center,
                        style: const TextStyle(
                          color: Color(0xFF6D6B66),
                          height: 1.5,
                        ),
                      ),
                      const SizedBox(height: 12),
                      Text(
                        'الحالية ${info.version}+${info.buildNumber}  →  '
                        '${update.latestVersion}+${update.latestBuild}',
                        textDirection: TextDirection.ltr,
                        textAlign: TextAlign.center,
                        style: const TextStyle(
                          color: Color(0xFF9A968D),
                          fontSize: 12,
                          fontWeight: FontWeight.w600,
                        ),
                      ),
                      if (_downloading) ...[
                        const SizedBox(height: 22),
                        LinearProgressIndicator(
                          value: _progress <= 0 ? null : _progress,
                          minHeight: 8,
                          borderRadius:
                              const BorderRadius.all(Radius.circular(20)),
                          color: AppColors.goldAccent,
                          backgroundColor: const Color(0x33D9A441),
                        ),
                        const SizedBox(height: 10),
                        Text(
                          _progress <= 0
                              ? 'جاري التنزيل…'
                              : 'جاري التنزيل… ${(_progress * 100).round()}%',
                          style: const TextStyle(
                            color: Color(0xFF6D6B66),
                            fontSize: 13,
                          ),
                        ),
                      ],
                      if (_downloadError != null) ...[
                        const SizedBox(height: 14),
                        Text(
                          _downloadError!,
                          textAlign: TextAlign.center,
                          style: const TextStyle(
                            color: AppColors.error,
                            height: 1.4,
                          ),
                        ),
                      ],
                      const SizedBox(height: 22),
                      SizedBox(
                        width: double.infinity,
                        child: FilledButton.icon(
                          style: FilledButton.styleFrom(
                            backgroundColor: AppColors.primaryDark,
                            foregroundColor: AppColors.textLight,
                            minimumSize: const Size.fromHeight(52),
                            shape: RoundedRectangleBorder(
                              borderRadius: BorderRadius.circular(17),
                            ),
                          ),
                          onPressed:
                              _downloading ? null : () => _startUpdate(update),
                          icon: Icon(
                            _downloading
                                ? Icons.hourglass_top_rounded
                                : Icons.download_rounded,
                          ),
                          label: Text(
                            _downloading ? 'جارٍ التحديث…' : 'تحديث الآن',
                          ),
                        ),
                      ),
                      if (!force) ...[
                        const SizedBox(height: 10),
                        TextButton(
                          onPressed: _downloading
                              ? null
                              : () => setState(() => _dismissedOptional = true),
                          child: const Text('لاحقاً'),
                        ),
                      ],
                    ],
                  ),
                ),
              ),
            ),
          ),
        ),
      ],
    );
  }
}
