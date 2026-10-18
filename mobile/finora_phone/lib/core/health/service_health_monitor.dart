/// Local Service Health Monitor — conservative updates (events / slow heartbeat).
/// Persists via LocalDatabase meta (no extra dependency).
library;

import '../../data/local/local_database.dart';

class ServiceHealthMonitor {
  ServiceHealthMonitor(this._db);

  final LocalDatabase _db;

  static const heartbeatMinInterval = Duration(minutes: 5);

  DateTime? lastServiceStartedAt;
  DateTime? lastServiceHeartbeatAt;
  DateTime? lastTelephonyEventAt;
  DateTime? lastReceiverEventAt;
  DateTime? lastOverlayEventAt;
  int unexpectedServiceStopCount = 0;
  bool forceStopSuspected = false;
  String? oemBackgroundHint;

  Future<void> load() async {
    lastServiceStartedAt = DateTime.tryParse(await _db.getMeta('health_service_started') ?? '');
    lastServiceHeartbeatAt =
        DateTime.tryParse(await _db.getMeta('health_heartbeat') ?? '');
    lastTelephonyEventAt =
        DateTime.tryParse(await _db.getMeta('health_telephony') ?? '');
    lastReceiverEventAt =
        DateTime.tryParse(await _db.getMeta('health_receiver') ?? '');
    lastOverlayEventAt =
        DateTime.tryParse(await _db.getMeta('health_overlay') ?? '');
    unexpectedServiceStopCount =
        int.tryParse(await _db.getMeta('health_unexpected_stops') ?? '0') ?? 0;
    forceStopSuspected = (await _db.getMeta('health_force_stop')) == '1';
    oemBackgroundHint = await _db.getMeta('health_oem_hint');
  }

  Future<void> _set(String key, String? value) async {
    if (value == null) return;
    await _db.setMeta(key, value);
  }

  Future<void> markServiceStarted() async {
    lastServiceStartedAt = DateTime.now().toUtc();
    lastServiceHeartbeatAt = lastServiceStartedAt;
    forceStopSuspected = false;
    await _set('health_service_started', lastServiceStartedAt!.toIso8601String());
    await _set('health_heartbeat', lastServiceHeartbeatAt!.toIso8601String());
    await _set('health_force_stop', '0');
  }

  Future<void> heartbeat({bool force = false}) async {
    final now = DateTime.now().toUtc();
    if (!force &&
        lastServiceHeartbeatAt != null &&
        now.difference(lastServiceHeartbeatAt!) < heartbeatMinInterval) {
      return;
    }
    lastServiceHeartbeatAt = now;
    await _set('health_heartbeat', now.toIso8601String());
  }

  Future<void> markTelephony() async {
    lastTelephonyEventAt = DateTime.now().toUtc();
    await _set('health_telephony', lastTelephonyEventAt!.toIso8601String());
    await heartbeat();
  }

  Future<void> markReceiver() async {
    lastReceiverEventAt = DateTime.now().toUtc();
    await _set('health_receiver', lastReceiverEventAt!.toIso8601String());
    await heartbeat();
  }

  Future<void> markOverlay() async {
    lastOverlayEventAt = DateTime.now().toUtc();
    await _set('health_overlay', lastOverlayEventAt!.toIso8601String());
    await heartbeat();
  }

  Future<void> markUnexpectedStop() async {
    unexpectedServiceStopCount += 1;
    await _set('health_unexpected_stops', '$unexpectedServiceStopCount');
  }

  Future<void> markForceStopSuspected() async {
    forceStopSuspected = true;
    oemBackgroundHint =
        'بعد Force Stop من إعدادات Android، النظام يمنع الـ receivers حتى يفتح المستخدم التطبيق يدوياً.';
    await _set('health_force_stop', '1');
    await _set('health_oem_hint', oemBackgroundHint!);
  }

  Future<void> clearForceStopFlag() async {
    forceStopSuspected = false;
    await _set('health_force_stop', '0');
  }

  Map<String, dynamic> toDiagnosticsMap() => {
        'last_service_started_at': lastServiceStartedAt?.toUtc().toIso8601String(),
        'last_service_heartbeat_at':
            lastServiceHeartbeatAt?.toUtc().toIso8601String(),
        'last_telephony_event_at':
            lastTelephonyEventAt?.toUtc().toIso8601String(),
        'last_receiver_event_at': lastReceiverEventAt?.toUtc().toIso8601String(),
        'last_overlay_event_at': lastOverlayEventAt?.toUtc().toIso8601String(),
        'unexpected_service_stop_count': unexpectedServiceStopCount,
        'force_stop_suspected': forceStopSuspected,
        'force_stop_warning': forceStopSuspected
            ? 'Android Force Stop يمنع الاستقبال حتى الفتح اليدوي — ليس ضماناً من التطبيق.'
            : null,
        'oem_background_hint': oemBackgroundHint,
        'kill_vs_force_stop':
            'Recents swipe ≠ Force Stop. Force Stop blocks receivers until manual open.',
      };
}
