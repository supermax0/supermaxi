import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../api/api_client.dart';
import '../errors/api_exception.dart';

class AppUpdateInfo {
  const AppUpdateInfo({
    required this.latestVersion,
    required this.latestBuild,
    required this.minVersion,
    required this.minBuild,
    required this.apkUrl,
    required this.force,
    required this.message,
  });

  final String latestVersion;
  final int latestBuild;
  final String minVersion;
  final int minBuild;
  final String apkUrl;
  final bool force;
  final String message;

  factory AppUpdateInfo.fromJson(Map<String, dynamic>? json) {
    final data = json ?? const <String, dynamic>{};
    return AppUpdateInfo(
      latestVersion: (data['latest_version'] as String?)?.trim().isNotEmpty == true
          ? (data['latest_version'] as String).trim()
          : '1.2.0',
      latestBuild: (data['latest_build'] as num?)?.toInt() ?? 3,
      minVersion: (data['min_version'] as String?)?.trim().isNotEmpty == true
          ? (data['min_version'] as String).trim()
          : '1.0.0',
      minBuild: (data['min_build'] as num?)?.toInt() ?? 1,
      apkUrl: (data['apk_url'] as String?)?.trim() ?? '',
      force: data['force'] == true,
      message: (data['message'] as String?)?.trim().isNotEmpty == true
          ? (data['message'] as String).trim()
          : 'يتوفر تحديث جديد لتطبيق Finora. حدّث الآن لتحسين الأداء والحماية.',
    );
  }
}

class BootstrapState {
  const BootstrapState({
    this.isLoading = true,
    this.maintenance = false,
    this.maintenanceMessage = '',
    this.appName = 'Finora',
    this.featureFlags = const {},
    this.appUpdate = const AppUpdateInfo(
      latestVersion: '1.2.0',
      latestBuild: 3,
      minVersion: '1.0.0',
      minBuild: 1,
      apkUrl: '',
      force: false,
      message: '',
    ),
    this.error,
  });

  final bool isLoading;
  final bool maintenance;
  final String maintenanceMessage;
  final String appName;
  final Map<String, bool> featureFlags;
  final AppUpdateInfo appUpdate;
  final String? error;

  BootstrapState copyWith({
    bool? isLoading,
    bool? maintenance,
    String? maintenanceMessage,
    String? appName,
    Map<String, bool>? featureFlags,
    AppUpdateInfo? appUpdate,
    String? error,
    bool clearError = false,
  }) {
    return BootstrapState(
      isLoading: isLoading ?? this.isLoading,
      maintenance: maintenance ?? this.maintenance,
      maintenanceMessage: maintenanceMessage ?? this.maintenanceMessage,
      appName: appName ?? this.appName,
      featureFlags: featureFlags ?? this.featureFlags,
      appUpdate: appUpdate ?? this.appUpdate,
      error: clearError ? null : (error ?? this.error),
    );
  }

  bool flag(String key, {bool fallback = true}) =>
      featureFlags[key] ?? fallback;
}

class BootstrapController extends StateNotifier<BootstrapState> {
  BootstrapController(this._api) : super(const BootstrapState()) {
    refresh();
  }

  final ApiClient _api;

  Future<void> refresh() async {
    state = state.copyWith(isLoading: true, clearError: true);
    try {
      final data = await _api.get('/api/mobile/v1/bootstrap');
      final branding = (data['branding'] as Map<String, dynamic>?) ?? {};
      final maintenance = (data['maintenance'] as Map<String, dynamic>?) ?? {};
      final rawFlags = (data['feature_flags'] as Map<String, dynamic>?) ?? {};
      final flags = <String, bool>{
        for (final e in rawFlags.entries) e.key: e.value == true,
      };
      state = state.copyWith(
        isLoading: false,
        appName: (branding['app_name'] as String?)?.isNotEmpty == true
            ? branding['app_name'] as String
            : 'Finora',
        maintenance: maintenance['enabled'] == true,
        maintenanceMessage: (maintenance['message'] as String?) ?? '',
        featureFlags: flags,
        appUpdate: AppUpdateInfo.fromJson(
          data['app_update'] as Map<String, dynamic>?,
        ),
      );
    } on ApiException catch (e) {
      state = state.copyWith(isLoading: false, error: e.message);
    } catch (e) {
      state = state.copyWith(isLoading: false, error: e.toString());
    }
  }
}

final bootstrapControllerProvider =
    StateNotifierProvider<BootstrapController, BootstrapState>((ref) {
  return BootstrapController(ref.watch(apiClientProvider));
});
