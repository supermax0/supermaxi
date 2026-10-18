import 'dart:convert';

import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../di/providers.dart';
import '../storage/token_storage.dart';

/// Central registry — pages must not parse bootstrap JSON directly.
class FeatureFlags {
  const FeatureFlags({
    this.overlay = true,
    this.offlineSync = true,
    this.recording = false,
    this.ai = false,
    this.queue = false,
    this.reportsAdvanced = false,
    this.orderDraftRequired = false,
    this.timeline = true,
    this.callOutcomes = true,
    this.advancedSearch = true,
    this.smartFollowup = true,
    this.voiceNotes = false,
    this.productSuggestions = false,
    this.supervisorDashboard = false,
  });

  final bool overlay;
  final bool offlineSync;
  final bool recording;
  final bool ai;
  final bool queue;
  final bool reportsAdvanced;
  final bool orderDraftRequired;
  final bool timeline;
  final bool callOutcomes;
  final bool advancedSearch;
  final bool smartFollowup;
  final bool voiceNotes;
  final bool productSuggestions;
  final bool supervisorDashboard;

  /// Safe offline defaults when bootstrap fails.
  static const fallback = FeatureFlags();

  factory FeatureFlags.fromJson(Map<String, dynamic>? json) {
    if (json == null || json.isEmpty) return fallback;
    bool f(String key, {bool def = false}) {
      final v = json[key];
      if (v is bool) return v;
      if (v is num) return v != 0;
      if (v is String) {
        final s = v.toLowerCase();
        if (s == '1' || s == 'true' || s == 'yes') return true;
        if (s == '0' || s == 'false' || s == 'no') return false;
      }
      return def;
    }

    return FeatureFlags(
      overlay: f('overlay', def: true),
      offlineSync: f('offline_sync', def: true),
      recording: f('recording'),
      ai: f('ai'),
      queue: f('queue'),
      reportsAdvanced: f('reports_advanced'),
      orderDraftRequired: f('order_draft_required'),
      timeline: f('phone_timeline_enabled', def: true),
      callOutcomes: f('phone_call_outcomes_enabled', def: true),
      advancedSearch: f('phone_advanced_search_enabled', def: true),
      smartFollowup: f('phone_smart_followup_enabled', def: true),
      voiceNotes: f('phone_voice_notes_enabled'),
      productSuggestions: f('phone_product_suggestions_enabled'),
      supervisorDashboard: f('phone_supervisor_dashboard_enabled'),
    );
  }

  Map<String, dynamic> toJson() => {
        'overlay': overlay,
        'offline_sync': offlineSync,
        'recording': recording,
        'ai': ai,
        'queue': queue,
        'reports_advanced': reportsAdvanced,
        'order_draft_required': orderDraftRequired,
        'phone_timeline_enabled': timeline,
        'phone_call_outcomes_enabled': callOutcomes,
        'phone_advanced_search_enabled': advancedSearch,
        'phone_smart_followup_enabled': smartFollowup,
        'phone_voice_notes_enabled': voiceNotes,
        'phone_product_suggestions_enabled': productSuggestions,
        'phone_supervisor_dashboard_enabled': supervisorDashboard,
      };
}

class FeatureFlagsController extends StateNotifier<FeatureFlags> {
  FeatureFlagsController(this._storage) : super(FeatureFlags.fallback) {
    _restore();
  }

  final TokenStorage _storage;

  Future<void> _restore() async {
    final raw = await _storage.readFeatureFlagsJson();
    if (raw == null || raw.isEmpty) return;
    try {
      final map = jsonDecode(raw);
      if (map is Map) {
        state = FeatureFlags.fromJson(Map<String, dynamic>.from(map));
      }
    } catch (_) {}
  }

  Future<void> applyFromBootstrap(Map<String, dynamic>? flags) async {
    final next = FeatureFlags.fromJson(flags);
    state = next;
    await _storage.saveFeatureFlagsJson(jsonEncode(next.toJson()));
  }
}

final featureFlagsProvider =
    StateNotifierProvider<FeatureFlagsController, FeatureFlags>((ref) {
  return FeatureFlagsController(ref.watch(tokenStorageProvider));
});
