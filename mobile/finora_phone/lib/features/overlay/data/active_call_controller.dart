import 'dart:async';
import 'dart:convert';

import 'package:connectivity_plus/connectivity_plus.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/di/providers.dart';
import '../../../core/features/feature_flags.dart';
import '../../../core/health/service_health_monitor.dart';
import '../../../core/logging/phone_logger.dart';
import '../../../core/bootstrap/phone_bootstrap.dart';
import '../../../data/mappers/phone_normalize.dart';
import '../../../domain/entities/entities.dart';
import '../../../domain/usecases/call_event_coordinator.dart';
import '../../../domain/usecases/call_state_machine.dart';
import '../../auth/data/auth_controller.dart';

class ActiveCallState {
  const ActiveCallState({
    this.status,
    this.lifecycle = CallLifecycleState.detected,
    this.number = '',
    this.clientId,
    this.idempotencyKey,
    this.localCallUuid,
    this.customer,
    this.startedAt,
    this.showAfterCall = false,
    this.noteDraft = '',
    this.direction = 'inbound',
    this.simSlot,
    this.overlayOpenedAt,
    this.localCrmShownAt,
    this.numberShownMs,
    this.localCrmMs,
  });

  final CallStatus? status;
  final CallLifecycleState lifecycle;
  final String number;
  final String? clientId;
  final String? idempotencyKey;
  final String? localCallUuid;
  final CustomerEntity? customer;
  final DateTime? startedAt;
  final bool showAfterCall;
  final String noteDraft;
  final String direction;
  final int? simSlot;
  final DateTime? overlayOpenedAt;
  final DateTime? localCrmShownAt;
  final int? numberShownMs;
  final int? localCrmMs;

  bool get isActive =>
      lifecycle == CallLifecycleState.ringing ||
      lifecycle == CallLifecycleState.dialing ||
      lifecycle == CallLifecycleState.answered ||
      lifecycle == CallLifecycleState.detected;

  ActiveCallState copyWith({
    CallStatus? status,
    CallLifecycleState? lifecycle,
    String? number,
    String? clientId,
    String? idempotencyKey,
    String? localCallUuid,
    CustomerEntity? customer,
    DateTime? startedAt,
    bool? showAfterCall,
    String? noteDraft,
    String? direction,
    int? simSlot,
    DateTime? overlayOpenedAt,
    DateTime? localCrmShownAt,
    int? numberShownMs,
    int? localCrmMs,
    bool clearCustomer = false,
  }) {
    return ActiveCallState(
      status: status ?? this.status,
      lifecycle: lifecycle ?? this.lifecycle,
      number: number ?? this.number,
      clientId: clientId ?? this.clientId,
      idempotencyKey: idempotencyKey ?? this.idempotencyKey,
      localCallUuid: localCallUuid ?? this.localCallUuid,
      customer: clearCustomer ? null : (customer ?? this.customer),
      startedAt: startedAt ?? this.startedAt,
      showAfterCall: showAfterCall ?? this.showAfterCall,
      noteDraft: noteDraft ?? this.noteDraft,
      direction: direction ?? this.direction,
      simSlot: simSlot ?? this.simSlot,
      overlayOpenedAt: overlayOpenedAt ?? this.overlayOpenedAt,
      localCrmShownAt: localCrmShownAt ?? this.localCrmShownAt,
      numberShownMs: numberShownMs ?? this.numberShownMs,
      localCrmMs: localCrmMs ?? this.localCrmMs,
    );
  }
}

final activeCallProvider =
    StateNotifierProvider<ActiveCallController, ActiveCallState>((ref) {
  return ActiveCallController(ref);
});

final serviceHealthProvider = Provider<ServiceHealthMonitor>((ref) {
  return ServiceHealthMonitor(ref.watch(localDatabaseProvider));
});

class ActiveCallController extends StateNotifier<ActiveCallState> {
  ActiveCallController(this._ref) : super(const ActiveCallState()) {
    _init();
  }

  final Ref _ref;
  StreamSubscription? _sub;
  StreamSubscription? _connSub;
  CallEventCoordinator? _coordinator;
  final Set<String> _createdMissedTasks = {};

  PhoneLogger get _log => _ref.read(phoneLoggerProvider);
  ServiceHealthMonitor get _health => _ref.read(serviceHealthProvider);
  int get _followupMinutes =>
      _ref.read(phoneBootstrapProvider).missedCallFollowupMinutes;

  Future<void> _init() async {
    await _log.log('app_started');
    await _health.load();
    await _health.markServiceStarted();
    _coordinator = CallEventCoordinator(
      persist: (log) async {
        await _ref.read(callLogRepositoryProvider).upsertLocal(
              log.copyWithCustomer(
                customerId: state.customer?.id,
                customerName: state.customer?.name,
                note: state.noteDraft.isEmpty ? null : state.noteDraft,
              ),
            );
      },
      resolveExistingUuid: ({
        required String reconciliationFingerprint,
        String? localCallUuid,
      }) async {
        final db = _ref.read(localDatabaseProvider);
        if (localCallUuid != null) {
          final hit = await db.getCallByLocalUuid(localCallUuid);
          if (hit != null) return hit['local_call_uuid'] as String?;
        }
        final byRecon = await db.getCallByRecon(reconciliationFingerprint);
        return byRecon?['local_call_uuid'] as String?;
      },
      onHealth: (origin) {
        switch (origin) {
          case CallEventOrigin.telephony:
            _health.markTelephony();
            break;
          case CallEventOrigin.receiver:
            _health.markReceiver();
            break;
          case CallEventOrigin.callLog:
          case CallEventOrigin.activeSession:
            break;
        }
      },
    );

    final source = _ref.read(callEventSourceProvider);
    await source.start();
    _sub = source.events.listen(_onEvent);
    _connSub = Connectivity().onConnectivityChanged.listen((result) {
      final list = result is List ? result : [result];
      final offline = list.every((e) => e == ConnectivityResult.none);
      if (!offline) {
        final auth = _ref.read(authControllerProvider);
        if (auth.offline) {
          _ref.read(authControllerProvider.notifier).revalidate();
        }
        _ref.read(syncEngineProvider).flush();
      }
    });
    await _restoreSession();
    await _recoverMissed();
  }

  Future<void> _restoreSession() async {
    try {
      final row = await _ref.read(localDatabaseProvider).readActiveSession();
      if (row == null) return;
      final note = row['note_draft'] as String? ?? '';
      if (note.isNotEmpty) {
        state = state.copyWith(
          noteDraft: note,
          localCallUuid: row['local_call_uuid'] as String?,
          clientId: row['call_client_id'] as String?,
        );
      }
    } catch (_) {}
  }

  Future<void> _recoverMissed() async {
    try {
      final deviceId = await _ref.read(apiClientProvider).ensureDeviceId();
      final raw = await _ref
          .read(permissionsChannelProvider)
          .readRecentCallLog(hours: 24);
      await _ref.read(localDatabaseProvider).bumpMetric(
            'android_calllog_count',
            raw.length.toDouble(),
          );
      for (final row in raw) {
        final number = normalizePhone('${row['number'] ?? ''}');
        if (number.isEmpty) continue;
        final started = DateTime.tryParse('${row['startedAt'] ?? ''}') ??
            DateTime.fromMillisecondsSinceEpoch(
              (row['date'] as num?)?.toInt() ??
                  DateTime.now().millisecondsSinceEpoch,
            );
        final type = '${row['type'] ?? ''}'.toLowerCase();
        final direction = type.contains('out') ? 'outbound' : 'inbound';
        final status = type.contains('miss')
            ? CallStatus.missed
            : (type.contains('reject')
                ? CallStatus.rejected
                : CallStatus.ended);
        final simSlot = (row['simSlot'] as num?)?.toInt();
        final log = await _coordinator?.ingest(
          CoordinatedCallEvent(
            origin: CallEventOrigin.callLog,
            type: status,
            number: number,
            startedAt: started.toUtc(),
            direction: direction,
            deviceId: deviceId,
            durationSec: (row['duration'] as num?)?.toInt(),
            simSlot: simSlot,
          ),
        );
        if (status == CallStatus.missed && log != null) {
          await _createMissedTaskOnce(
            phone: number,
            callClientId: log.clientId,
            localUuid: log.localCallUuid,
          );
        }
      }
      await _ref.read(taskRepositoryProvider).pullRemote();
    } catch (_) {}
  }

  /// Cold-start from after-call notification / overlay tap.
  Future<void> hydrateFromLaunch({
    required String number,
    String? localCallUuid,
    bool showAfterCall = false,
  }) async {
    final phone = normalizePhone(number);
    if (phone.isEmpty && (localCallUuid == null || localCallUuid.isEmpty)) {
      return;
    }
    CustomerEntity? customer;
    if (phone.isNotEmpty) {
      customer = await _ref
          .read(customerRepositoryProvider)
          .lookupByPhone(phone, allowNetwork: true);
    }
    String? clientId = state.clientId;
    String? uuid = localCallUuid ?? state.localCallUuid;
    if (uuid != null) {
      final row = await _ref.read(localDatabaseProvider).getCallByLocalUuid(uuid);
      clientId ??= row?['client_id'] as String?;
    }
    state = state.copyWith(
      number: phone.isNotEmpty ? phone : state.number,
      customer: customer,
      clientId: clientId,
      localCallUuid: uuid,
      showAfterCall: showAfterCall,
      lifecycle: showAfterCall ? CallLifecycleState.ended : state.lifecycle,
      status: showAfterCall ? CallStatus.ended : state.status,
      startedAt: state.startedAt ?? DateTime.now().toUtc(),
    );
  }

  void attachCustomer(CustomerEntity customer) {
    state = state.copyWith(customer: customer);
  }

  Future<void> _onEvent(CallEvent event) async {
    final overlay = _ref.read(overlayChannelProvider);
    final number = normalizePhone(event.number);
    final deviceId =
        event.deviceId ?? await _ref.read(apiClientProvider).ensureDeviceId();
    final direction = event.direction;
    final started = event.startedAt.toUtc();

    final origin = CallEventOrigin.telephony;
    await _ref.read(tokenStorageProvider).setLastCallEvent(jsonEncode({
          'type': event.type.name,
          'phone': PhoneLogger.maskPhone(number),
          'at': DateTime.now().toUtc().toIso8601String(),
        }));

    final isStart = event.type == CallStatus.ringing ||
        event.type == CallStatus.detected;

    if (isStart &&
        state.localCallUuid != null &&
        state.number.isNotEmpty &&
        phoneLookupKey(state.number) != phoneLookupKey(number)) {
      await overlay.hide();
      _coordinator?.reset();
      state = const ActiveCallState();
      await _ref.read(localDatabaseProvider).clearActiveSession();
    }

    final log = await _coordinator!.ingest(
      CoordinatedCallEvent(
        origin: origin,
        type: event.type,
        number: number,
        startedAt: started,
        direction: direction,
        simSlot: event.simSlot,
        deviceId: deviceId,
        localCallUuid: state.localCallUuid,
      ),
    );

    final m = _coordinator!.machine;
    if (log == null || m == null) return;

    if (isStart) {
      await _log.log(
        direction == 'outbound'
            ? 'outgoing_call_detected'
            : 'incoming_call_detected',
        data: {'phone': number, 'uuid': log.localCallUuid},
      );
      final t0 = DateTime.now();
      state = ActiveCallState(
        status: CallStatus.ringing,
        lifecycle: m.state,
        number: number,
        clientId: log.clientId,
        idempotencyKey: log.idempotencyKey,
        localCallUuid: log.localCallUuid,
        startedAt: started,
        direction: direction,
        simSlot: event.simSlot,
        overlayOpenedAt: t0,
        numberShownMs: 0,
      );

      await overlay.updateCrm({'name': '…', 'phone': number, 'minimal': true});
      await _health.markOverlay();
      await _log.log('overlay_opened', data: {'phone': number});
      await _ref.read(localDatabaseProvider).bumpMetric('overlay_shown_count');

      final cacheStart = DateTime.now();
      final customer = number.isEmpty
          ? null
          : await _ref
              .read(customerRepositoryProvider)
              .lookupByPhone(number, allowNetwork: false);
      final localMs = DateTime.now().difference(cacheStart).inMilliseconds;
      if (customer != null) {
        state = state.copyWith(
          customer: customer,
          localCrmShownAt: DateTime.now(),
          localCrmMs: localMs,
          numberShownMs: DateTime.now().difference(t0).inMilliseconds,
        );
        await overlay.updateCrm({
          'name': customer.name,
          'phone': customer.phone,
          'balance': customer.balance,
          'vip': customer.vip,
          'blacklisted': customer.blacklisted,
          'openOrders': customer.openOrdersCount,
          'lastNote': customer.lastNote,
          'totalPurchases': customer.totalPurchases,
          'openOnly': true,
        });
      } else {
        state = state.copyWith(
          numberShownMs: DateTime.now().difference(t0).inMilliseconds,
          localCrmMs: localMs,
        );
        if (number.isNotEmpty) {
          await overlay.updateCrm({
            'name': 'زبون جديد',
            'phone': number,
            'isNew': true,
            'openOnly': true,
          });
        }
      }
      await _ref
          .read(localDatabaseProvider)
          .bumpMetric('sum_number_shown_ms', (state.numberShownMs ?? 0).toDouble());
      await _ref
          .read(localDatabaseProvider)
          .bumpMetric('sum_local_crm_ms', (state.localCrmMs ?? 0).toDouble());
      if (state.numberShownMs != null) {
        await _ref.read(localDatabaseProvider).recordLatencySample(
              'number_shown_ms',
              state.numberShownMs!.toDouble(),
            );
      }
      if (state.localCrmMs != null) {
        await _ref.read(localDatabaseProvider).recordLatencySample(
              'local_crm_ms',
              state.localCrmMs!.toDouble(),
            );
      }
      if (number.isNotEmpty) {
        _hydrateNetwork(number, log.localCallUuid ?? '');
      }
      await _ref.read(localDatabaseProvider).saveActiveSession(
            callClientId: log.clientId,
            noteDraft: state.noteDraft,
            payload: {
              'local_call_uuid': log.localCallUuid,
              'lifecycle': m.state.name,
            },
          );
      // Patch session local uuid via raw update if column exists
      try {
        final db = await _ref.read(localDatabaseProvider).database;
        await db.update(
          'active_session',
          {'local_call_uuid': log.localCallUuid},
          where: 'id = 1',
        );
      } catch (_) {}
      return;
    }

    if (event.type == CallStatus.answered || event.type == CallStatus.active) {
      await _log.log('call_answered', data: {'phone': number});
      state = state.copyWith(
        status: CallStatus.answered,
        lifecycle: CallLifecycleState.answered,
      );
      await _adoptLateNumber(number);
      // Resolve open missed tasks for this number (local).
      await _resolveLocalMissedTasks(number.isNotEmpty ? number : state.number);
      return;
    }

    if (event.type == CallStatus.missed ||
        event.type == CallStatus.rejected ||
        event.type == CallStatus.ended ||
        event.type == CallStatus.disconnected ||
        event.type == CallStatus.failed) {
      await _adoptLateNumber(number);
      final target = m.state;
      final clientId = state.clientId ?? log.clientId;
      final talk = m.timestamps.talkDurationSec;
      await _log.log(
        target == CallLifecycleState.missed ? 'call_missed' : 'call_ended',
        data: {'phone': number, 'duration': talk},
      );

      if (target == CallLifecycleState.missed) {
        await _createMissedTaskOnce(
          phone: number.isNotEmpty ? number : state.number,
          callClientId: clientId,
          localUuid: state.localCallUuid ?? log.localCallUuid,
        );
      }

      if (state.noteDraft.trim().isNotEmpty) {
        await _ref.read(noteRepositoryProvider).createLocal(
              NoteEntity(
                clientId: 'note-$clientId',
                body: state.noteDraft.trim(),
                callClientId: clientId,
                customerId: state.customer?.id,
              ),
            );
        await _log.log('note_saved');
      }

      await overlay.hide();
      await _log.log('overlay_closed');
      await _ref.read(localDatabaseProvider).clearActiveSession();
      final showAfter = target == CallLifecycleState.ended;
      // Answered calls may have a native dialer recording — pick it up
      // in the background and queue the upload.
      if (target == CallLifecycleState.ended &&
          _ref.read(featureFlagsProvider).recording) {
        final recPhone = number.isNotEmpty ? number : state.number;
        final recStart = state.startedAt ?? started;
        if (recPhone.isNotEmpty) {
          unawaited(
            _ref.read(recordingRepositoryProvider).captureForCall(
                  callClientId: clientId,
                  phone: recPhone,
                  startedAt: recStart,
                  endedAt: DateTime.now(),
                ),
          );
        }
      }
      state = state.copyWith(
        status: CallStatus.ended,
        lifecycle: target,
        showAfterCall: showAfter,
      );
      _coordinator?.markSynced(); // sync_status only — call_status stays terminal
    }
  }

  /// API 31+ can only resolve the number after the start event was emitted.
  Future<void> _adoptLateNumber(String number) async {
    if (number.isEmpty || state.number.isNotEmpty) return;
    state = state.copyWith(number: number);
    final customer = await _ref
        .read(customerRepositoryProvider)
        .lookupByPhone(number, allowNetwork: true);
    if (customer == null) {
      await _ref.read(overlayChannelProvider).updateCrm({
        'name': 'زبون جديد',
        'phone': number,
        'isNew': true,
        'openOnly': true,
      });
      return;
    }
    state = state.copyWith(customer: customer);
    await _ref.read(overlayChannelProvider).updateCrm({
      'name': customer.name,
      'phone': customer.phone,
      'balance': customer.balance,
      'vip': customer.vip,
      'blacklisted': customer.blacklisted,
      'openOrders': customer.openOrdersCount,
      'lastNote': customer.lastNote,
      'totalPurchases': customer.totalPurchases,
      'openOnly': true,
    });
  }

  Future<void> _createMissedTaskOnce({
    required String phone,
    required String callClientId,
    String? localUuid,
  }) async {
    final taskKey = 'missed-${localUuid ?? callClientId}';
    if (_createdMissedTasks.contains(taskKey)) return;
    _createdMissedTasks.add(taskKey);
    // Coalesce: if open missed task for same phone within 15m, bump attempt
    final existing = await _ref.read(localDatabaseProvider).listTasks(status: 'open');
    final phoneKey = phoneLookupKey(phone);
    final recent = existing.where((t) {
      if ((t['source'] as String?) != 'missed_call') return false;
      return phoneLookupKey('${t['phone']}') == phoneKey;
    }).toList();
    if (recent.isNotEmpty) {
      final row = Map<String, Object?>.from(recent.first);
      final attempts = (row['attempt_count'] as int? ?? 1) + 1;
      row['attempt_count'] = attempts;
      await _ref.read(localDatabaseProvider).upsertTask(row);
      return;
    }
    await _ref.read(taskRepositoryProvider).createLocal(
          TaskEntity(
            clientId: taskKey,
            title: 'متابعة مكالمة فائتة',
            phone: phone,
            customerId: state.customer?.id,
            dueAt: DateTime.now().toUtc().add(Duration(minutes: _followupMinutes)),
            source: 'missed_call',
          ),
        );
    await _log.log('task_created', data: {'source': 'missed_call'});
  }

  Future<void> _resolveLocalMissedTasks(String phone) async {
    final phoneKey = phoneLookupKey(phone);
    final open = await _ref.read(localDatabaseProvider).listTasks(status: 'open');
    for (final t in open) {
      if (phoneLookupKey('${t['phone']}') != phoneKey) continue;
      if ((t['source'] as String?) != 'missed_call') continue;
      final row = Map<String, Object?>.from(t);
      row['status'] = 'resolved_by_answered_call';
      await _ref.read(localDatabaseProvider).upsertTask(row);
    }
  }

  Future<void> _hydrateNetwork(String number, String uuid) async {
    try {
      final fresh = await _ref
          .read(customerRepositoryProvider)
          .lookupByPhone(number, allowNetwork: true);
      if (state.localCallUuid != uuid) return;
      if (fresh == null) return;
      state = state.copyWith(customer: fresh);
      await _ref.read(overlayChannelProvider).updateCrm({
        'name': fresh.name,
        'phone': fresh.phone,
        'balance': fresh.balance,
        'vip': fresh.vip,
        'blacklisted': fresh.blacklisted,
        'openOrders': fresh.openOrdersCount,
        'lastNote': fresh.lastNote,
        'totalPurchases': fresh.totalPurchases,
        'openOnly': true,
      });
    } catch (_) {}
  }

  void setNoteDraft(String value) {
    state = state.copyWith(noteDraft: value);
    _ref.read(localDatabaseProvider).saveActiveSession(
          callClientId: state.clientId,
          noteDraft: value,
        );
  }

  void dismissAfterCall() {
    state = const ActiveCallState();
    _coordinator?.reset();
  }

  @override
  void dispose() {
    _sub?.cancel();
    _connSub?.cancel();
    super.dispose();
  }
}

extension on CallLogEntity {
  CallLogEntity copyWithCustomer({
    int? customerId,
    String? customerName,
    String? note,
  }) {
    return CallLogEntity(
      clientId: clientId,
      phone: phone,
      direction: direction,
      status: status,
      startedAt: startedAt,
      endedAt: endedAt,
      durationSec: durationSec,
      customerId: customerId ?? this.customerId,
      customerName: customerName ?? this.customerName,
      syncStatus: syncStatus,
      serverId: serverId,
      note: note ?? this.note,
      idempotencyKey: idempotencyKey,
      localCallUuid: localCallUuid,
      reconciliationFingerprint: reconciliationFingerprint,
      deviceId: deviceId,
      simSlot: simSlot,
      detectedAt: detectedAt,
      ringingAt: ringingAt,
      dialingAt: dialingAt,
      answeredAt: answeredAt,
      cancelledAt: cancelledAt,
      failedAt: failedAt,
      syncedAt: syncedAt,
    );
  }
}
