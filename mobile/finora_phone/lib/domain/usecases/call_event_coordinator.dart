/// Single creation path for call records.
///
/// CallEventSource (Telephony / BroadcastReceiver / CallLog / ActiveSession)
///       ↓
/// CallEventCoordinator
///       ↓
/// CallStateMachine
///       ↓
/// LocalCallRepository
///
/// Only the coordinator may create/update the authoritative local call row.
library;

import 'package:uuid/uuid.dart';

import '../../data/mappers/phone_normalize.dart';
import '../entities/entities.dart';
import 'call_state_machine.dart';

enum CallEventOrigin {
  telephony,
  receiver,
  callLog,
  activeSession,
}

class CoordinatedCallEvent {
  const CoordinatedCallEvent({
    required this.origin,
    required this.type,
    required this.number,
    required this.startedAt,
    this.direction = 'inbound',
    this.simSlot,
    this.deviceId,
    this.localCallUuid,
    this.durationSec,
  });

  final CallEventOrigin origin;
  final CallStatus type;
  final String number;
  final DateTime startedAt;
  final String direction;
  final int? simSlot;
  final String? deviceId;
  final String? localCallUuid;
  final int? durationSec;
}

typedef PersistCallFn = Future<void> Function(CallLogEntity log);
typedef ResolveExistingUuidFn = Future<String?> Function({
  required String reconciliationFingerprint,
  String? localCallUuid,
});

class CallEventCoordinator {
  CallEventCoordinator({
    required this.persist,
    required this.resolveExistingUuid,
    this.onHealth,
  });

  final PersistCallFn persist;
  final ResolveExistingUuidFn resolveExistingUuid;
  final void Function(CallEventOrigin origin)? onHealth;

  final _uuid = const Uuid();
  CallStateMachine? _machine;
  String? _localCallUuid;
  String? _idempotencyKey;
  String? _deviceId;
  SyncStatus syncStatus = SyncStatus.pending;

  CallStateMachine? get machine => _machine;
  String? get localCallUuid => _localCallUuid;
  String? get idempotencyKey => _idempotencyKey;

  Future<CallLogEntity?> ingest(CoordinatedCallEvent event) async {
    onHealth?.call(event.origin);

    final number = normalizePhone(event.number);
    final deviceId = event.deviceId ?? 'unknown-device';
    _deviceId = deviceId;
    final direction = event.direction;
    final started = event.startedAt.toUtc();

    final isNewSession = event.type == CallStatus.ringing ||
        event.type == CallStatus.detected;

    if (isNewSession || _localCallUuid == null) {
      // Persist local_call_uuid immediately before further processing.
      var uuid = event.localCallUuid;
      if (uuid == null || uuid.isEmpty) {
        final fingerprint = buildReconciliationFingerprint(
          normalizedPhone: phoneLookupKey(number),
          direction: direction,
          startedAt: started,
          deviceUuid: deviceId,
          simSlot: event.simSlot,
        );
        uuid = await resolveExistingUuid(
              reconciliationFingerprint: fingerprint,
              localCallUuid: null,
            ) ??
            _uuid.v4();
      }
      _localCallUuid = uuid;
      _idempotencyKey =
          buildPrimaryIdempotencyKey(deviceUuid: deviceId, localCallUuid: uuid);
      _machine = CallStateMachine(direction: direction);
      _machine!.transition(CallLifecycleState.detected, at: started);
    }

    final m = _machine!;
    m.direction = direction;

    final next = _mapStatus(event.type, direction, m.state);
    if (next != null) {
      if (!m.transition(next, at: started) && isNewSession) {
        // Reset if illegal on stale machine
        _machine = CallStateMachine(direction: direction);
        _machine!.transition(CallLifecycleState.detected, at: started);
        _machine!.transition(next, at: started);
      } else if (!m.canTransition(next) && m.state != next) {
        // Ignore illegal jumps from secondary sources (CallLog may lag).
        if (event.origin == CallEventOrigin.callLog && m.isTerminal) {
          // already terminal — still persist fingerprint merge
        } else if (event.origin != CallEventOrigin.telephony &&
            event.origin != CallEventOrigin.receiver) {
          // secondary source cannot create parallel records
        }
      }
    }

    final log = CallLogEntity(
      clientId: _idempotencyKey!,
      localCallUuid: _localCallUuid,
      idempotencyKey: _idempotencyKey,
      phone: number,
      direction: direction,
      status: m.state.name,
      startedAt: m.timestamps.detectedAt ?? started,
      endedAt: m.timestamps.endedAt,
      durationSec: event.durationSec ?? m.timestamps.talkDurationSec,
      syncStatus: syncStatus == SyncStatus.permanentlyFailed
          ? 'permanently_failed'
          : syncStatus.name,
      deviceId: deviceId,
      simSlot: event.simSlot,
      detectedAt: m.timestamps.detectedAt,
      ringingAt: m.timestamps.ringingAt,
      dialingAt: m.timestamps.dialingAt,
      answeredAt: m.timestamps.answeredAt,
      cancelledAt: m.timestamps.cancelledAt,
      failedAt: m.timestamps.failedAt,
      reconciliationFingerprint: buildReconciliationFingerprint(
        normalizedPhone: phoneLookupKey(number),
        direction: direction,
        startedAt: started,
        deviceUuid: deviceId,
        simSlot: event.simSlot,
      ),
    );

    await persist(log);
    return log;
  }

  void markSynced() {
    syncStatus = SyncStatus.synced;
  }

  void reset() {
    _machine = null;
    _localCallUuid = null;
    _idempotencyKey = null;
    syncStatus = SyncStatus.pending;
  }

  CallLifecycleState? _mapStatus(
    CallStatus type,
    String direction,
    CallLifecycleState current,
  ) {
    switch (type) {
      case CallStatus.detected:
        return direction == 'outbound'
            ? CallLifecycleState.dialing
            : CallLifecycleState.detected;
      case CallStatus.ringing:
        return direction == 'outbound'
            ? CallLifecycleState.dialing
            : CallLifecycleState.ringing;
      case CallStatus.answered:
      case CallStatus.active:
        return CallLifecycleState.answered;
      case CallStatus.missed:
        return CallLifecycleState.missed;
      case CallStatus.rejected:
        return CallLifecycleState.rejected;
      case CallStatus.failed:
        return CallLifecycleState.failed;
      case CallStatus.ended:
      case CallStatus.disconnected:
        if (current == CallLifecycleState.ringing) {
          return CallLifecycleState.missed;
        }
        if (current == CallLifecycleState.dialing) {
          return CallLifecycleState.cancelled;
        }
        return CallLifecycleState.ended;
      case CallStatus.synced:
        return null; // sync is separate
    }
  }
}

/// Documentation of recovery merge rules (see also PHASE_1_5 docs).
abstract final class CallRecoveryDocs {
  static const architecture = '''
CallEventSource → CallEventCoordinator → CallStateMachine → LocalCallRepository

- Telephony Monitor: primary live transitions.
- BroadcastReceiver: secondary live transitions (same coordinator; no new row).
- Android CallLog: recovery/reconcile via secondary fingerprint; never creates
  a second authoritative row if local_call_uuid / primary idempotency matches.
- Active session: restores in-progress note + local_call_uuid after process death.

Kill vs Force Stop:
- Swipe from Recents: process may die; FG service / receivers can restart.
- System process kill: same — recoverable on next launch + CallLog reconcile.
- Settings Force Stop: Android blocks receivers/alarms until user opens the app.
  Do NOT claim event delivery after Force Stop.
''';
}
