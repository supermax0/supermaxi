import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api/api_client.dart';
import '../../../core/errors/api_exception.dart';

class AppNotification {
  AppNotification({
    required this.id,
    required this.title,
    required this.body,
    required this.read,
    this.type = '',
    this.createdAt,
    this.data = const {},
  });

  factory AppNotification.fromJson(Map<String, dynamic> json) {
    return AppNotification(
      id: json['id'] as int,
      title: (json['title'] as String?) ?? '',
      body: (json['body'] as String?) ?? '',
      type: (json['type'] as String?) ?? '',
      read: json['read'] == true,
      createdAt: json['created_at'] as String?,
      data: (json['data'] as Map<String, dynamic>?) ?? const {},
    );
  }

  final int id;
  final String title;
  final String body;
  final String type;
  final bool read;
  final String? createdAt;
  final Map<String, dynamic> data;
}

class NotificationsState {
  NotificationsState({
    this.items = const [],
    this.unreadCount = 0,
    this.loading = false,
    this.error,
  });

  final List<AppNotification> items;
  final int unreadCount;
  final bool loading;
  final String? error;

  NotificationsState copyWith({
    List<AppNotification>? items,
    int? unreadCount,
    bool? loading,
    String? error,
    bool clearError = false,
  }) {
    return NotificationsState(
      items: items ?? this.items,
      unreadCount: unreadCount ?? this.unreadCount,
      loading: loading ?? this.loading,
      error: clearError ? null : (error ?? this.error),
    );
  }
}

final notificationsControllerProvider =
    StateNotifierProvider<NotificationsController, NotificationsState>((ref) {
  return NotificationsController(ref.watch(apiClientProvider));
});

class NotificationsController extends StateNotifier<NotificationsState> {
  NotificationsController(this._api) : super(NotificationsState());

  final ApiClient _api;

  Future<void> refresh() async {
    state = state.copyWith(loading: true, clearError: true);
    try {
      final raw = await _api.get('/api/mobile/v1/notifications');
      final items = ((raw['items'] as List<dynamic>?) ?? [])
          .whereType<Map<String, dynamic>>()
          .map(AppNotification.fromJson)
          .toList();
      state = state.copyWith(
        items: items,
        unreadCount: (raw['unread_count'] as int?) ?? 0,
        loading: false,
      );
    } on ApiException catch (e) {
      state = state.copyWith(loading: false, error: e.message);
    }
  }

  Future<void> markRead(int id) async {
    await _api.patch('/api/mobile/v1/notifications/$id/read');
    await refresh();
  }
}

/// Fire-and-forget analytics batch (best effort).
class AnalyticsTracker {
  AnalyticsTracker(this._api);

  final ApiClient _api;
  final List<Map<String, dynamic>> _queue = [];

  void track(String eventName, {Map<String, dynamic>? properties}) {
    _queue.add({
      'event_name': eventName,
      if (properties != null) ...properties,
      'properties': properties ?? {},
      'client_ts': DateTime.now().toUtc().toIso8601String(),
    });
    if (_queue.length >= 8) {
      flush();
    }
  }

  Future<void> flush() async {
    if (_queue.isEmpty) return;
    final batch = List<Map<String, dynamic>>.from(_queue);
    _queue.clear();
    try {
      await _api
          .post('/api/mobile/v1/analytics/events', data: {'events': batch});
    } catch (_) {
      // Re-queue lightly on failure
      _queue.insertAll(0, batch.take(20));
    }
  }
}

final analyticsTrackerProvider = Provider<AnalyticsTracker>((ref) {
  return AnalyticsTracker(ref.watch(apiClientProvider));
});
