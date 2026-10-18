import 'dart:convert';

import '../../core/api/api_client.dart';
import '../../core/errors/api_exception.dart';
import '../../core/logging/phone_logger.dart';
import '../../core/sync/sync_engine.dart';
import '../../domain/entities/entities.dart';
import '../../domain/ports/ports.dart';
import '../../platform/call_event_channel.dart';
import '../local/local_database.dart';
import '../mappers/phone_normalize.dart';

class CustomerRepositoryImpl implements CustomerRepository {
  CustomerRepositoryImpl({
    required LocalDatabase db,
    required ApiClient api,
    required SyncEngine sync,
    PhoneLogger? logger,
  })  : _db = db,
        _api = api,
        _sync = sync,
        _logger = logger;

  final LocalDatabase _db;
  final ApiClient _api;
  final SyncEngine _sync;
  final PhoneLogger? _logger;

  @override
  Future<CustomerEntity?> lookupByPhone(
    String phone, {
    bool allowNetwork = true,
  }) async {
    final key = phoneLookupKey(phone);
    if (key.isEmpty) return null;
    final cached = await _db.getCustomerByPhone(key);
    if (cached != null) {
      await _logger?.log('customer_cache_hit', data: {'phone': phone});
      final entity = CustomerEntity.fromJson(cached);
      if (allowNetwork) {
        _refreshNetwork(phone);
      }
      return entity;
    }
    await _logger?.log('customer_cache_miss', data: {'phone': phone});
    if (!allowNetwork) return null;
    try {
      final res = await _api.get(
        '/api/phone/v1/customers/by-phone',
        query: {'phone': normalizePhone(phone)},
      );
      if (res['found'] == true && res['customer'] is Map) {
        final map = Map<String, dynamic>.from(res['customer'] as Map);
        final entity = CustomerEntity.fromJson(map);
        await _cache(entity);
        await _logger?.log('customer_api_success', data: {'phone': phone});
        return entity;
      }
      await _logger?.log('customer_api_success', data: {'phone': phone, 'found': false});
    } on ApiException catch (e) {
      await _logger?.log('customer_api_failed', data: {'error': e.message});
      return null;
    }
    return null;
  }

  Future<void> _refreshNetwork(String phone) async {
    try {
      final res = await _api.get(
        '/api/phone/v1/customers/by-phone',
        query: {'phone': normalizePhone(phone)},
      );
      if (res['found'] == true && res['customer'] is Map) {
        final entity =
            CustomerEntity.fromJson(Map<String, dynamic>.from(res['customer'] as Map));
        await _cache(entity);
      }
    } catch (_) {}
  }

  Future<void> _cache(CustomerEntity entity) async {
    final phone = phoneLookupKey(entity.phone);
    await _db.upsertCustomerCache(
      phoneNormalized: phone,
      phone2: phoneLookupKey(entity.phone2),
      id: entity.id,
      payload: entity.toJson(),
    );
  }

  @override
  Future<CustomerEntity> createCustomer({
    required String name,
    required String phone,
    String? city,
    String? address,
    String? notes,
    required String clientId,
  }) async {
    final payload = {
      'name': name,
      'phone': normalizePhone(phone),
      'city': city,
      'address': address,
      'notes': notes,
      'client_id': clientId,
    };

    // Prefer online create so order drafts unlock immediately with server id.
    try {
      final res = await _api.post('/api/phone/v1/customers', data: payload);
      if (res['customer'] is Map) {
        final entity = CustomerEntity.fromJson(
          Map<String, dynamic>.from(res['customer'] as Map),
        );
        await _cache(entity);
        await _logger?.log('customer_created_online', data: {'id': entity.id});
        return entity;
      }
    } on ApiException catch (e) {
      if (e.code != 'offline') {
        await _logger?.log('customer_create_failed', data: {'error': e.message});
        // Fall through to offline queue for transient failures except validation.
        if (e.statusCode != null && e.statusCode! >= 400 && e.statusCode! < 500) {
          rethrow;
        }
      }
    } catch (_) {}

    final entity = CustomerEntity(
      id: null,
      name: name,
      phone: normalizePhone(phone),
      city: city ?? '',
      address: address ?? '',
      notes: notes ?? '',
    );
    await _cache(entity);
    await _db.enqueueOutbox(
      op: 'create_customer',
      payload: payload,
      idempotencyKey: clientId,
    );
    await _logger?.log('outbox_enqueued', data: {'op': 'create_customer'});
    _sync.flush();
    return entity;
  }

  @override
  Future<CustomerEntity?> updateCustomer({
    required int customerId,
    String? name,
    String? city,
    String? address,
    String? notes,
    String? phone2,
  }) async {
    final body = <String, dynamic>{};
    if (name != null) body['name'] = name;
    if (city != null) body['city'] = city;
    if (address != null) body['address'] = address;
    if (notes != null) body['notes'] = notes;
    if (phone2 != null) body['phone2'] = phone2;
    if (body.isEmpty) return null;
    try {
      final res = await _api.patch(
        '/api/phone/v1/customers/$customerId',
        data: body,
      );
      if (res['customer'] is Map) {
        final entity = CustomerEntity.fromJson(
          Map<String, dynamic>.from(res['customer'] as Map),
        );
        await _cache(entity);
        return entity;
      }
    } on ApiException catch (e) {
      await _logger?.log('customer_patch_failed', data: {'error': e.message});
      rethrow;
    }
    return null;
  }

  @override
  Future<Map<String, dynamic>?> timeline(int customerId, {String? cursor}) async {
    try {
      final query = <String, String>{'limit': '30'};
      if (cursor != null && cursor.isNotEmpty) query['cursor'] = cursor;
      final res = await _api.get(
        '/api/phone/v1/customers/$customerId/timeline',
        query: query,
      );
      if (cursor == null || cursor.isEmpty) {
        await _db.cacheTimeline(customerId, res);
      }
      return res;
    } on ApiException {
      return _db.readTimelineCache(customerId);
    } catch (_) {
      return _db.readTimelineCache(customerId);
    }
  }

  @override
  Future<List<CustomerEntity>> searchLocal(String query) async {
    final rows = await _db.searchCustomers(query);
    return rows.map(CustomerEntity.fromJson).toList();
  }

  @override
  Future<List<CustomerEntity>> searchRemote(String query) async {
    final q = query.trim();
    if (q.length < 2) return searchLocal(q);
    try {
      final res = await _api.get(
        '/api/phone/v1/customers/search',
        query: {'q': q, 'limit': '40'},
      );
      final list = (res['customers'] as List? ?? [])
          .whereType<Map>()
          .map((e) => CustomerEntity.fromJson(Map<String, dynamic>.from(e)))
          .toList();
      for (final c in list) {
        await _cache(c);
      }
      if (list.isNotEmpty) return list;
    } on ApiException {
      // Fall through to local.
    } catch (_) {}
    return searchLocal(q);
  }

  @override
  Future<Map<String, dynamic>?> advancedSearch(
    String query, {
    String? types,
  }) async {
    final q = query.trim();
    final digits = q.replaceAll(RegExp(r'\D'), '');
    if (digits.length < 3 && q.length < 2) {
      return {
        'query': q,
        'groups': {
          'customers': [],
          'orders': [],
          'invoices': [],
          'calls': [],
          'products': [],
        },
        'pagination': {'next_cursor': null, 'has_more': false},
      };
    }
    try {
      final params = <String, String>{'q': q, 'limit': '20'};
      if (types != null && types.isNotEmpty) params['types'] = types;
      final res = await _api.get('/api/phone/v1/search', query: params);
      await _db.saveRecentSearch(q);
      return res;
    } on ApiException {
      final local = await searchLocal(q);
      return {
        'query': q,
        'groups': {
          'customers': local
              .map((c) => {
                    'type': 'customer',
                    'id': c.id,
                    'title': c.name,
                    'subtitle': c.phone,
                    'summary': '${c.city} ${c.address}'.trim(),
                    'highlight': q,
                  })
              .toList(),
          'orders': [],
          'invoices': [],
          'calls': [],
          'products': [],
        },
        'pagination': {'next_cursor': null, 'has_more': false},
        'offline': true,
      };
    }
  }
}

class CallLogRepositoryImpl implements CallLogRepository {
  CallLogRepositoryImpl({
    required LocalDatabase db,
    required SyncEngine sync,
    required ApiClient api,
  })  : _db = db,
        _sync = sync,
        _api = api;

  final LocalDatabase _db;
  final SyncEngine _sync;
  final ApiClient _api;

  @override
  Future<void> upsertLocal(CallLogEntity log) async {
    final deviceId = log.deviceId ?? await _api.ensureDeviceId();
    final idem = log.idempotencyKey ??
        (log.localCallUuid != null
            ? '$deviceId:${log.localCallUuid}'
            : 'call|${phoneLookupKey(log.phone)}|${log.direction}|${log.startedAt.toUtc().millisecondsSinceEpoch}|$deviceId|${log.simSlot ?? 'na'}');
    String? utcZ(DateTime? d) {
      if (d == null) return null;
      final s = d.toUtc().toIso8601String();
      return '${s.split('.').first}Z';
    }

    await _db.upsertCallLog({
      'client_id': log.clientId,
      'local_call_uuid': log.localCallUuid,
      'idempotency_key': idem,
      'reconciliation_fingerprint': log.reconciliationFingerprint,
      'phone': normalizePhone(log.phone),
      'direction': log.direction,
      'status': log.status == 'synced' ? 'ended' : log.status,
      'started_at': utcZ(log.startedAt),
      'ended_at': utcZ(log.endedAt),
      'duration_sec': log.durationSec,
      'detected_at': utcZ(log.detectedAt),
      'ringing_at': utcZ(log.ringingAt),
      'dialing_at': utcZ(log.dialingAt),
      'answered_at': utcZ(log.answeredAt),
      'cancelled_at': utcZ(log.cancelledAt),
      'failed_at': utcZ(log.failedAt),
      'synced_at': utcZ(log.syncedAt),
      'customer_id': log.customerId,
      'customer_name': log.customerName,
      'sync_status': log.syncStatus,
      'server_id': log.serverId,
      'note': log.note,
      'device_id': deviceId,
      'sim_slot': log.simSlot,
    });
    await _db.enqueueOutbox(
      op: 'upsert_call',
      payload: {
        'client_id': log.clientId,
        'local_call_uuid': log.localCallUuid,
        'idempotency_key': idem,
        'phone': normalizePhone(log.phone),
        'phone_normalized': phoneLookupKey(log.phone),
        'direction': log.direction,
        'call_status': log.status == 'synced' ? 'ended' : log.status,
        'sync_status': 'pending',
        'status': log.status == 'synced' ? 'ended' : log.status,
        'started_at': utcZ(log.startedAt),
        'ended_at': utcZ(log.endedAt),
        'duration_sec': log.durationSec,
        'detected_at': utcZ(log.detectedAt),
        'ringing_at': utcZ(log.ringingAt),
        'dialing_at': utcZ(log.dialingAt),
        'answered_at': utcZ(log.answeredAt),
        'cancelled_at': utcZ(log.cancelledAt),
        'failed_at': utcZ(log.failedAt),
        'customer_id': log.customerId,
        'synced_note': log.note,
        'device_id': deviceId,
        'sim_slot': log.simSlot,
      },
      idempotencyKey: idem,
    );
    await _db.bumpMetric('total_detected_calls');
    _sync.flush();
  }

  @override
  Future<List<CallLogEntity>> listLocal({int limit = 200}) async {
    final rows = await _db.listCallLogs(limit: limit);
    return rows
        .map(
          (r) => CallLogEntity(
            clientId: r['client_id'] as String,
            localCallUuid: r['local_call_uuid'] as String?,
            reconciliationFingerprint:
                r['reconciliation_fingerprint'] as String?,
            phone: r['phone'] as String,
            direction: r['direction'] as String,
            status: r['status'] as String,
            startedAt: DateTime.tryParse(r['started_at'] as String? ?? '') ??
                DateTime.now(),
            endedAt: DateTime.tryParse(r['ended_at'] as String? ?? ''),
            durationSec: r['duration_sec'] as int?,
            customerId: r['customer_id'] as int?,
            customerName: r['customer_name'] as String?,
            syncStatus: r['sync_status'] as String? ?? 'pending',
            serverId: r['server_id'] as int?,
            note: r['note'] as String?,
            idempotencyKey: r['idempotency_key'] as String?,
            deviceId: r['device_id'] as String?,
            simSlot: r['sim_slot'] as int?,
            detectedAt: DateTime.tryParse(r['detected_at'] as String? ?? ''),
            ringingAt: DateTime.tryParse(r['ringing_at'] as String? ?? ''),
            dialingAt: DateTime.tryParse(r['dialing_at'] as String? ?? ''),
            answeredAt: DateTime.tryParse(r['answered_at'] as String? ?? ''),
            cancelledAt: DateTime.tryParse(r['cancelled_at'] as String? ?? ''),
            failedAt: DateTime.tryParse(r['failed_at'] as String? ?? ''),
            syncedAt: DateTime.tryParse(r['synced_at'] as String? ?? ''),
            outcome: r['outcome'] as String?,
            outcomeNote: r['outcome_note'] as String?,
            followUpRequired: (r['follow_up_required'] as int? ?? 0) == 1,
            followUpAt: DateTime.tryParse(r['follow_up_at'] as String? ?? ''),
            outcomeClientId: r['outcome_client_id'] as String?,
            unclassified: (r['unclassified'] as int? ?? 0) == 1,
          ),
        )
        .toList();
  }

  CallLogEntity _fromRow(Map<String, Object?> r) {
    return CallLogEntity(
      clientId: r['client_id'] as String,
      localCallUuid: r['local_call_uuid'] as String?,
      reconciliationFingerprint: r['reconciliation_fingerprint'] as String?,
      phone: r['phone'] as String,
      direction: r['direction'] as String,
      status: r['status'] as String,
      startedAt:
          DateTime.tryParse(r['started_at'] as String? ?? '') ?? DateTime.now(),
      endedAt: DateTime.tryParse(r['ended_at'] as String? ?? ''),
      durationSec: r['duration_sec'] as int?,
      customerId: r['customer_id'] as int?,
      customerName: r['customer_name'] as String?,
      syncStatus: r['sync_status'] as String? ?? 'pending',
      serverId: r['server_id'] as int?,
      note: r['note'] as String?,
      idempotencyKey: r['idempotency_key'] as String?,
      deviceId: r['device_id'] as String?,
      simSlot: r['sim_slot'] as int?,
      outcome: r['outcome'] as String?,
      outcomeNote: r['outcome_note'] as String?,
      followUpRequired: (r['follow_up_required'] as int? ?? 0) == 1,
      followUpAt: DateTime.tryParse(r['follow_up_at'] as String? ?? ''),
      outcomeClientId: r['outcome_client_id'] as String?,
      unclassified: (r['unclassified'] as int? ?? 0) == 1,
    );
  }

  @override
  Future<void> setOutcome({
    required String clientId,
    required int? serverId,
    required String outcome,
    String? outcomeNote,
    bool followUpRequired = false,
    DateTime? followUpAt,
    required String outcomeClientId,
    bool hasLinkedOrder = false,
  }) async {
    String? utcZ(DateTime? d) {
      if (d == null) return null;
      final s = d.toUtc().toIso8601String();
      return '${s.split('.').first}Z';
    }

    await _db.setCallOutcomeLocal(
      clientId: clientId,
      outcome: outcome,
      outcomeNote: outcomeNote,
      followUpRequired: followUpRequired,
      followUpAt: utcZ(followUpAt),
      outcomeClientId: outcomeClientId,
    );
    if (serverId != null) {
      await _db.enqueueOutbox(
        op: 'set_call_outcome',
        payload: {
          'call_id': serverId,
          'outcome': outcome,
          'outcome_note': outcomeNote,
          'follow_up_required': followUpRequired,
          'follow_up_at': utcZ(followUpAt),
          'outcome_client_id': outcomeClientId,
          'has_linked_order': hasLinkedOrder,
        },
        idempotencyKey: outcomeClientId,
      );
      _sync.flush();
    }
  }

  @override
  Future<void> markUnclassified(String clientId) async {
    await _db.markCallUnclassified(clientId);
  }

  @override
  Future<List<CallLogEntity>> listUnclassified({int limit = 50}) async {
    final rows = await _db.listUnclassifiedCalls(limit: limit);
    return rows.map(_fromRow).toList();
  }

  @override
  Future<void> recoverFromDeviceLogs(List<CallLogEntity> deviceLogs) async {
    for (final log in deviceLogs) {
      if (log.idempotencyKey != null) {
        final byKey =
            await _db.getCallLogByIdempotency(log.idempotencyKey!);
        if (byKey != null) continue;
      }
      final existing = await _db.getCallLog(log.clientId);
      if (existing != null) continue;
      final all = await _db.listCallLogs(limit: 500);
      final dup = all.any((r) {
        final phone = r['phone'] as String? ?? '';
        final started =
            DateTime.tryParse(r['started_at'] as String? ?? '') ?? DateTime(1970);
        return phoneLookupKey(phone) == phoneLookupKey(log.phone) &&
            (started.difference(log.startedAt).inSeconds).abs() <= 5 &&
            (r['direction'] as String? ?? 'inbound') == log.direction;
      });
      if (dup) continue;
      await upsertLocal(log);
    }
  }
}

class TaskRepositoryImpl implements TaskRepository {
  TaskRepositoryImpl({
    required LocalDatabase db,
    required SyncEngine sync,
    required ApiClient api,
  })  : _db = db,
        _sync = sync,
        _api = api;

  final LocalDatabase _db;
  final SyncEngine _sync;
  final ApiClient _api;

  @override
  Future<void> createLocal(TaskEntity task) async {
    await _db.upsertTask({
      'client_id': task.clientId,
      'title': task.title,
      'phone': normalizePhone(task.phone),
      'customer_id': task.customerId,
      'due_at': task.dueAt?.toUtc().toIso8601String(),
      'status': task.status,
      'source': task.source,
      'task_type': task.taskType ?? task.source,
      'priority': task.priority,
      'reason': task.reason,
      'attempt_count': task.attemptCount,
      'call_id': task.callId,
      'sync_status': task.syncStatus,
      'server_id': task.id,
    });
    await _db.enqueueOutbox(
      op: 'create_task',
      payload: {
        'client_id': task.clientId,
        'title': task.title,
        'phone': normalizePhone(task.phone),
        'customer_id': task.customerId,
        'due_at': task.dueAt?.toUtc().toIso8601String(),
        'status': task.status,
        'source': task.source,
        'task_type': task.taskType ?? task.source,
        'priority': task.priority,
        'reason': task.reason,
        'call_id': task.callId,
      },
      idempotencyKey: task.clientId,
    );
    _sync.flush();
  }

  @override
  Future<List<TaskEntity>> listLocal({String? status, String? filter}) async {
    var rows = await _db.listTasks(status: status);
    if (filter != null && filter.isNotEmpty) {
      final now = DateTime.now().toUtc();
      final todayStart = DateTime.utc(now.year, now.month, now.day);
      final tomorrow = todayStart.add(const Duration(days: 1));
      rows = rows.where((r) {
        final st = r['status'] as String? ?? 'open';
        final due = DateTime.tryParse(r['due_at'] as String? ?? '');
        final tt = r['task_type'] as String? ?? r['source'] as String? ?? '';
        final pr = r['priority'] as String? ?? 'normal';
        final reason = r['reason'] as String? ?? '';
        switch (filter) {
          case 'today':
            return due != null &&
                !due.isBefore(todayStart) &&
                due.isBefore(tomorrow);
          case 'overdue':
            return due != null &&
                due.isBefore(now) &&
                (st == 'open' || st == 'in_progress' || st == 'overdue');
          case 'high_priority':
            return pr == 'high' || pr == 'urgent';
          case 'missed':
            return tt.contains('missed');
          case 'callback':
            return tt.contains('callback');
          case 'complaint':
            return tt.contains('complaint') || reason == 'complaint';
          default:
            return true;
        }
      }).toList();
    }
    return rows
        .map(
          (r) => TaskEntity(
            clientId: r['client_id'] as String,
            title: r['title'] as String,
            phone: r['phone'] as String,
            customerId: r['customer_id'] as int?,
            dueAt: DateTime.tryParse(r['due_at'] as String? ?? ''),
            status: r['status'] as String? ?? 'open',
            source: r['source'] as String? ?? 'manual',
            syncStatus: r['sync_status'] as String? ?? 'pending',
            id: r['server_id'] as int?,
            taskType: r['task_type'] as String?,
            priority: r['priority'] as String? ?? 'normal',
            reason: r['reason'] as String?,
            attemptCount: r['attempt_count'] as int? ?? 1,
            callId: r['call_id'] as int?,
          ),
        )
        .toList();
  }

  @override
  Future<void> updateStatus(String clientId, String status) async {
    final rows = await _db.listTasks();
    final match = rows.where((r) => r['client_id'] == clientId).toList();
    if (match.isEmpty) return;
    final row = Map<String, Object?>.from(match.first);
    row['status'] = status;
    row['sync_status'] = 'pending';
    await _db.upsertTask(row);
    // Tasks created offline have no server id yet; sync resolves it by client_id
    // once the queued create_task ahead of this entry succeeds.
    await _db.enqueueOutbox(
      op: 'patch_task',
      payload: {
        'id': row['server_id'],
        'client_id': clientId,
        'status': status,
      },
      idempotencyKey: 'task-patch-$clientId-$status',
    );
    _sync.flush();
  }

  @override
  Future<void> snooze(String clientId, DateTime until) async {
    final rows = await _db.listTasks();
    final match = rows.where((r) => r['client_id'] == clientId).toList();
    if (match.isEmpty) return;
    final row = Map<String, Object?>.from(match.first);
    final iso = until.toUtc().toIso8601String();
    row['snoozed_until'] = iso;
    row['due_at'] = iso;
    if (row['status'] == 'overdue') row['status'] = 'open';
    row['sync_status'] = 'pending';
    await _db.upsertTask(row);
    await _db.enqueueOutbox(
      op: 'patch_task',
      payload: {
        'id': row['server_id'],
        'client_id': clientId,
        'snoozed_until': iso,
        'due_at': iso,
        'status': row['status'],
      },
      idempotencyKey: 'task-snooze-$clientId-$iso',
    );
    _sync.flush();
  }

  @override
  Future<void> pullRemote({String? filter}) async {
    try {
      final query = <String, String>{};
      if (filter != null && filter.isNotEmpty) query['filter'] = filter;
      final res = await _api.get('/api/phone/v1/tasks', query: query);
      final list = (res['tasks'] as List? ?? []).whereType<Map>();
      for (final raw in list) {
        final t = Map<String, dynamic>.from(raw);
        final clientId = (t['client_id'] ?? 'srv-${t['id']}').toString();
        await _db.upsertTask({
          'client_id': clientId,
          'title': t['title']?.toString() ?? 'مهمة',
          'phone': normalizePhone('${t['phone'] ?? ''}'),
          'customer_id': t['customer_id'] is int
              ? t['customer_id'] as int
              : int.tryParse('${t['customer_id']}'),
          'due_at': t['due_at']?.toString(),
          'status': t['status']?.toString() ?? 'open',
          'source': t['source']?.toString() ?? 'missed_call',
          'task_type': t['task_type']?.toString(),
          'priority': t['priority']?.toString() ?? 'normal',
          'reason': t['reason']?.toString(),
          'sync_status': 'synced',
          'server_id':
              t['id'] is int ? t['id'] as int : int.tryParse('${t['id']}'),
          'attempt_count': (t['attempt_count'] as num?)?.toInt() ?? 1,
          'call_id': t['call_id'] is int
              ? t['call_id'] as int
              : int.tryParse('${t['call_id']}'),
        });
      }
    } catch (_) {}
  }
}

class NoteRepositoryImpl implements NoteRepository {
  NoteRepositoryImpl({required LocalDatabase db, required SyncEngine sync})
      : _db = db,
        _sync = sync;

  final LocalDatabase _db;
  final SyncEngine _sync;

  @override
  Future<void> createLocal(NoteEntity note) async {
    await _db.upsertNote({
      'client_id': note.clientId,
      'body': note.body,
      'call_client_id': note.callClientId,
      'customer_id': note.customerId,
      'sync_status': note.syncStatus,
    });
    await _db.enqueueOutbox(
      op: 'create_note',
      payload: {
        'client_id': note.clientId,
        'body': note.body,
        'call_client_id': note.callClientId,
        'customer_id': note.customerId,
      },
      idempotencyKey: note.clientId,
    );
    _sync.flush();
  }
}

class OrderRepositoryImpl implements OrderRepository {
  OrderRepositoryImpl({
    required LocalDatabase db,
    required SyncEngine sync,
    required ApiClient api,
  })  : _db = db,
        _sync = sync,
        _api = api;

  final LocalDatabase _db;
  final SyncEngine _sync;
  final ApiClient _api;

  @override
  Future<Map<String, dynamic>> createConfirmedOrder({
    required int customerId,
    required List<Map<String, dynamic>> items,
    String? note,
    required String clientId,
  }) async {
    final created = await _api.post(
      '/api/phone/v1/orders',
      data: {
        'customer_id': customerId,
        'items': items,
        'note': note,
        'client_id': clientId,
        'idempotency_key': clientId,
      },
      extraHeaders: {'Idempotency-Key': clientId},
    );
    final draft = created['draft'];
    final draftId = draft is Map ? (draft['id'] as num?)?.toInt() : null;
    if (draftId == null) {
      throw StateError('لم يُرجع الخادم رقم الطلب');
    }
    final confirmed = await _api.post('/api/phone/v1/orders/$draftId/confirm');
    return confirmed;
  }

  @override
  Future<String> enqueueOrder({
    required int customerId,
    required List<Map<String, dynamic>> items,
    String? note,
    required String clientId,
  }) async {
    final payload = {
      'customer_id': customerId,
      'items': items,
      'note': note,
      'client_id': clientId,
    };
    await _db.upsertOrderDraft({
      'client_id': clientId,
      'customer_id': customerId,
      'payload_json': jsonEncode(payload),
      'sync_status': 'pending',
      'status': 'draft',
      'created_at': DateTime.now().toUtc().toIso8601String(),
    });
    await _db.enqueueOutbox(
      op: 'create_order',
      payload: {
        ...payload,
        'idempotency_key': clientId,
      },
      idempotencyKey: clientId,
    );
    _sync.flush();
    return clientId;
  }

  @override
  Future<List<Map<String, dynamic>>> listDrafts() async {
    try {
      final res = await _api.get('/api/phone/v1/orders/drafts');
      final list = (res['drafts'] as List? ?? [])
          .whereType<Map>()
          .map((e) => Map<String, dynamic>.from(e))
          .toList();
      return list;
    } catch (_) {
      final local = await _db.listOrderDrafts();
      return local
          .map(
            (r) => {
              'client_id': r['client_id'],
              'customer_id': r['customer_id'],
              'status': r['status'] ?? 'draft',
              'payload': jsonDecode(r['payload_json'] as String? ?? '{}'),
              'local_only': true,
            },
          )
          .toList();
    }
  }

  @override
  Future<bool> confirmDraft({required int draftId}) async {
    try {
      await _api.post('/api/phone/v1/orders/$draftId/confirm');
      return true;
    } catch (_) {
      return false;
    }
  }
}

/// Picks up the native dialer's recording after a call and queues its upload.
class RecordingRepositoryImpl implements RecordingRepository {
  RecordingRepositoryImpl({
    required LocalDatabase db,
    required SyncEngine sync,
    required PermissionsChannel channel,
    PhoneLogger? logger,
  })  : _db = db,
        _sync = sync,
        _channel = channel,
        _logger = logger;

  final LocalDatabase _db;
  final SyncEngine _sync;
  final PermissionsChannel _channel;
  final PhoneLogger? _logger;

  @override
  Future<void> captureForCall({
    required String callClientId,
    required String phone,
    required DateTime startedAt,
    DateTime? endedAt,
  }) async {
    final end = endedAt ?? DateTime.now();
    // The recorder finalizes the file shortly after the call ends; retry a few
    // times before giving up.
    for (final wait in const [4, 8, 15]) {
      await Future.delayed(Duration(seconds: wait));
      final found = await _channel.findCallRecording(
        phone: phone,
        startedAtMs: startedAt.millisecondsSinceEpoch,
        endedAtMs: end.millisecondsSinceEpoch,
      );
      if (found == null) continue;
      final path = found['path']?.toString() ?? '';
      if (path.isEmpty) continue;
      final durationMs = found['durationMs'];
      await _db.enqueueOutbox(
        op: 'upload_recording',
        payload: {
          'call_client_id': callClientId,
          'file_path': path,
          'duration_sec': durationMs is num ? (durationMs / 1000).round() : null,
          'size': found['size'],
          'name': found['name'],
        },
        idempotencyKey: 'rec-$callClientId',
      );
      await _logger?.log('recording_enqueued', data: {
        'call': callClientId,
        'size': found['size'],
      });
      _sync.flush();
      return;
    }
    await _logger?.log('recording_not_found', data: {'call': callClientId});
  }
}

/// Future-module stubs.
class RecordingRepositoryStub implements RecordingRepository {
  @override
  Future<void> captureForCall({
    required String callClientId,
    required String phone,
    required DateTime startedAt,
    DateTime? endedAt,
  }) async {}
}

class CallAiAssistantStub implements CallAiAssistant {
  @override
  Future<String?> summarizeCall(String callClientId) async => null;
}

class QueueRepositoryStub implements QueueRepository {
  @override
  Future<List<Map<String, dynamic>>> listQueue() async => const [];
}

class ReportsRepositoryStub implements ReportsRepository {
  @override
  Future<Map<String, dynamic>> dailySummary(DateTime day) async =>
      {'calls': 0, 'missed': 0, 'orders': 0};
}
