/// Call lifecycle (call_status) separate from sync_status.
///
/// Inbound:
///   detected → ringing → answered → ended
///                      → missed / rejected / failed
///
/// Outbound:
///   detected → dialing → answered → ended
///                      → failed / cancelled
///
/// Sync is NOT a call state: SyncStatus pending|syncing|synced|…
library;

enum CallLifecycleState {
  detected,
  ringing,
  dialing,
  answered,
  ended,
  missed,
  rejected,
  failed,
  cancelled,
}

enum SyncStatus {
  pending,
  syncing,
  synced,
  failed,
  permanentlyFailed,
}

class CallTimestamps {
  const CallTimestamps({
    this.detectedAt,
    this.ringingAt,
    this.dialingAt,
    this.answeredAt,
    this.endedAt,
    this.cancelledAt,
    this.failedAt,
  });

  final DateTime? detectedAt;
  final DateTime? ringingAt;
  final DateTime? dialingAt;
  final DateTime? answeredAt;
  final DateTime? endedAt;
  final DateTime? cancelledAt;
  final DateTime? failedAt;

  CallTimestamps copyWith({
    DateTime? detectedAt,
    DateTime? ringingAt,
    DateTime? dialingAt,
    DateTime? answeredAt,
    DateTime? endedAt,
    DateTime? cancelledAt,
    DateTime? failedAt,
  }) {
    return CallTimestamps(
      detectedAt: detectedAt ?? this.detectedAt,
      ringingAt: ringingAt ?? this.ringingAt,
      dialingAt: dialingAt ?? this.dialingAt,
      answeredAt: answeredAt ?? this.answeredAt,
      endedAt: endedAt ?? this.endedAt,
      cancelledAt: cancelledAt ?? this.cancelledAt,
      failedAt: failedAt ?? this.failedAt,
    );
  }

  /// Talk time only — ring/dial time excluded.
  int? get talkDurationSec {
    if (answeredAt == null || endedAt == null) return null;
    final sec = endedAt!.difference(answeredAt!).inSeconds;
    return sec < 0 ? 0 : sec;
  }

  Map<String, dynamic> toUtcJson() => {
        'detected_at': detectedAt?.toUtc().toIso8601String().replaceFirst(RegExp(r'\.\d+'), ''),
        'ringing_at': ringingAt?.toUtc().toIso8601String().replaceFirst(RegExp(r'\.\d+'), ''),
        'dialing_at': dialingAt?.toUtc().toIso8601String().replaceFirst(RegExp(r'\.\d+'), ''),
        'answered_at': answeredAt?.toUtc().toIso8601String().replaceFirst(RegExp(r'\.\d+'), ''),
        'ended_at': endedAt?.toUtc().toIso8601String().replaceFirst(RegExp(r'\.\d+'), ''),
        'cancelled_at': cancelledAt?.toUtc().toIso8601String().replaceFirst(RegExp(r'\.\d+'), ''),
        'failed_at': failedAt?.toUtc().toIso8601String().replaceFirst(RegExp(r'\.\d+'), ''),
      };
}

class CallStateMachine {
  CallStateMachine({
    CallLifecycleState initial = CallLifecycleState.detected,
    CallTimestamps? timestamps,
    this.direction = 'inbound',
  })  : state = initial,
        timestamps = timestamps ?? const CallTimestamps();

  CallLifecycleState state;
  CallTimestamps timestamps;
  String direction;

  static const Map<CallLifecycleState, Set<CallLifecycleState>> inboundAllowed = {
    CallLifecycleState.detected: {
      CallLifecycleState.ringing,
      CallLifecycleState.answered,
      CallLifecycleState.failed,
    },
    CallLifecycleState.ringing: {
      CallLifecycleState.answered,
      CallLifecycleState.missed,
      CallLifecycleState.rejected,
      CallLifecycleState.failed,
    },
    CallLifecycleState.answered: {
      CallLifecycleState.ended,
      CallLifecycleState.failed,
    },
    CallLifecycleState.ended: {},
    CallLifecycleState.missed: {},
    CallLifecycleState.rejected: {},
    CallLifecycleState.failed: {},
    CallLifecycleState.dialing: {},
    CallLifecycleState.cancelled: {},
  };

  static const Map<CallLifecycleState, Set<CallLifecycleState>> outboundAllowed = {
    CallLifecycleState.detected: {
      CallLifecycleState.dialing,
      CallLifecycleState.answered,
      CallLifecycleState.failed,
      CallLifecycleState.cancelled,
    },
    CallLifecycleState.dialing: {
      CallLifecycleState.answered,
      CallLifecycleState.failed,
      CallLifecycleState.cancelled,
    },
    CallLifecycleState.answered: {
      CallLifecycleState.ended,
      CallLifecycleState.failed,
    },
    CallLifecycleState.ended: {},
    CallLifecycleState.failed: {},
    CallLifecycleState.cancelled: {},
    CallLifecycleState.ringing: {},
    CallLifecycleState.missed: {},
    CallLifecycleState.rejected: {},
  };

  Map<CallLifecycleState, Set<CallLifecycleState>> get allowed =>
      direction == 'outbound' ? outboundAllowed : inboundAllowed;

  bool canTransition(CallLifecycleState next) {
    if (state == next) return true;
    return allowed[state]?.contains(next) ?? false;
  }

  bool transition(CallLifecycleState next, {DateTime? at}) {
    if (state == next) return true;
    if (!canTransition(next)) return false;
    final now = at ?? DateTime.now().toUtc();
    state = next;
    switch (next) {
      case CallLifecycleState.detected:
        timestamps = timestamps.copyWith(detectedAt: now);
        break;
      case CallLifecycleState.ringing:
        timestamps = timestamps.copyWith(
          detectedAt: timestamps.detectedAt ?? now,
          ringingAt: now,
        );
        break;
      case CallLifecycleState.dialing:
        timestamps = timestamps.copyWith(
          detectedAt: timestamps.detectedAt ?? now,
          dialingAt: now,
        );
        break;
      case CallLifecycleState.answered:
        timestamps = timestamps.copyWith(
          detectedAt: timestamps.detectedAt ?? now,
          answeredAt: now,
        );
        break;
      case CallLifecycleState.ended:
      case CallLifecycleState.missed:
      case CallLifecycleState.rejected:
        timestamps = timestamps.copyWith(endedAt: now);
        break;
      case CallLifecycleState.cancelled:
        timestamps = timestamps.copyWith(cancelledAt: now, endedAt: now);
        break;
      case CallLifecycleState.failed:
        timestamps = timestamps.copyWith(failedAt: now, endedAt: now);
        break;
    }
    return true;
  }

  String get statusLabel => state.name;
  bool get isTerminal =>
      state == CallLifecycleState.ended ||
      state == CallLifecycleState.missed ||
      state == CallLifecycleState.rejected ||
      state == CallLifecycleState.failed ||
      state == CallLifecycleState.cancelled;
}

/// Primary idempotency: device_uuid:local_call_uuid
String buildPrimaryIdempotencyKey({
  required String deviceUuid,
  required String localCallUuid,
}) {
  return '$deviceUuid:$localCallUuid';
}

/// Secondary fingerprint for CallLog reconciliation only (not sole identity).
String buildReconciliationFingerprint({
  required String normalizedPhone,
  required String direction,
  required DateTime startedAt,
  required String deviceUuid,
  int? simSlot,
  int bucketSeconds = 5,
}) {
  final bucket =
      (startedAt.toUtc().millisecondsSinceEpoch ~/ (bucketSeconds * 1000)) *
          (bucketSeconds * 1000);
  final sim = simSlot?.toString() ?? 'na';
  final phone = normalizedPhone.isEmpty ? 'unknown' : normalizedPhone;
  return 'recon|$phone|$direction|$bucket|$deviceUuid|$sim';
}

/// @Deprecated — kept for recovery matching only.
String buildCallIdempotencyKey({
  required String normalizedPhone,
  required String direction,
  required DateTime startedAt,
  required String deviceId,
  int? simSlot,
  int bucketSeconds = 5,
}) {
  return buildReconciliationFingerprint(
    normalizedPhone: normalizedPhone,
    direction: direction,
    startedAt: startedAt,
    deviceUuid: deviceId,
    simSlot: simSlot,
    bucketSeconds: bucketSeconds,
  );
}
