import 'dart:convert';
import 'dart:io';

import '../../core/api/api_client.dart';
import '../../core/errors/api_exception.dart';
import '../../core/logging/phone_logger.dart';
import '../../core/storage/token_storage.dart';
import '../../data/local/local_database.dart';
import '../../data/mappers/phone_normalize.dart';

class SyncEngine {
  SyncEngine({
    required LocalDatabase db,
    required ApiClient api,
    required TokenStorage storage,
    PhoneLogger? logger,
  })  : _db = db,
        _api = api,
        _storage = storage,
        _logger = logger ?? PhoneLogger(storage: storage);

  final LocalDatabase _db;
  final ApiClient _api;
  final TokenStorage _storage;
  final PhoneLogger _logger;
  bool _running = false;

  static const maxRetries = 8;

  Future<void> flush() async {
    if (_running) return;
    _running = true;
    await _logger.log('sync_started');
    try {
      final rows = await _db.pendingOutbox();
      for (final row in rows) {
        final id = row['id'] as int;
        final op = row['op'] as String;
        final payload =
            jsonDecode(row['payload_json'] as String) as Map<String, dynamic>;
        final attempts = row['retry_count'] as int? ??
            row['attempts'] as int? ??
            0;
        final idem = row['idempotency_key'] as String? ?? '';
        try {
          await _db.setOutboxStatus(id, 'syncing');
          await _dispatch(op, payload, idempotencyKey: idem);
          await _db.deleteOutbox(id);
          if (op == 'upsert_call') {
            final clientId = payload['client_id']?.toString();
            if (clientId != null) await _db.markCallSynced(clientId);
          }
        } on ApiException catch (e) {
          if (e.code == 'device_revoked') {
            await _storage.wipeAllSensitive();
            await _db.wipeBusinessData();
            await _logger.log('sync_failed', data: {'error': 'device_revoked'});
            break;
          }
          if (e.code == 'offline') {
            await _db.bumpOutbox(id, e.message, _backoff(attempts));
            break;
          }
          // Duplicate / conflict = success (idempotent).
          if (e.statusCode == 409 ||
              e.code == 'duplicate' ||
              e.code == 'already_exists') {
            await _db.deleteOutbox(id);
            continue;
          }
          final permanent = attempts + 1 >= maxRetries;
          await _db.bumpOutbox(
            id,
            e.message,
            _backoff(attempts),
            permanent: permanent,
          );
          await _storage.setLastApiError(e.message);
        } catch (e) {
          final permanent = attempts + 1 >= maxRetries;
          await _db.bumpOutbox(
            id,
            e.toString(),
            _backoff(attempts),
            permanent: permanent,
          );
        }
      }
      await _storage.setLastSync(DateTime.now().toIso8601String());
      await _logger.log('sync_completed');
    } catch (e) {
      await _logger.log('sync_failed', data: {'error': e.toString()});
    } finally {
      _running = false;
    }
  }

  Duration _backoff(int attempts) {
    final seconds = [2, 5, 15, 60, 120, 300, 600, 900];
    final idx = attempts.clamp(0, seconds.length - 1);
    return Duration(seconds: seconds[idx]);
  }

  Future<void> _dispatch(
    String op,
    Map<String, dynamic> payload, {
    required String idempotencyKey,
  }) async {
    final headers = <String, dynamic>{};
    if (idempotencyKey.isNotEmpty) {
      headers['Idempotency-Key'] = idempotencyKey;
    }
    switch (op) {
      case 'create_customer':
        final res = await _api.post(
          '/api/phone/v1/customers',
          data: payload,
          extraHeaders: headers,
        );
        if (res['customer'] is Map) {
          final c = Map<String, dynamic>.from(res['customer'] as Map);
          final phone = (c['phone'] ?? payload['phone'] ?? '').toString();
          await _db.upsertCustomerCache(
            phoneNormalized: phoneLookupKey(phone),
            phone2: null,
            id: c['id'] is int ? c['id'] as int : int.tryParse('${c['id']}'),
            payload: c,
          );
        }
      case 'create_note':
        await _api.post('/api/phone/v1/notes', data: payload, extraHeaders: headers);
      case 'create_task':
        final taskRes = await _api.post(
          '/api/phone/v1/tasks',
          data: payload,
          extraHeaders: headers,
        );
        final task = taskRes['task'];
        if (task is Map && payload['client_id'] != null) {
          final clientId = payload['client_id'].toString();
          final rows = await _db.listTasks();
          final match =
              rows.where((r) => r['client_id'] == clientId).toList();
          if (match.isNotEmpty) {
            final row = Map<String, Object?>.from(match.first);
            row['server_id'] =
                task['id'] is int ? task['id'] as int : int.tryParse('${task['id']}');
            row['sync_status'] = 'synced';
            await _db.upsertTask(row);
          }
        }
      case 'upsert_call':
        await _api.post('/api/phone/v1/calls', data: payload, extraHeaders: headers);
      case 'set_call_outcome':
        final callId = payload['call_id'];
        if (callId == null) {
          throw ApiException('call_id required for set_call_outcome');
        }
        await _api.post(
          '/api/phone/v1/calls/$callId/outcome',
          data: payload,
          extraHeaders: headers,
        );
      case 'batch_calls':
        await _api.post('/api/phone/v1/calls/batch', data: payload, extraHeaders: headers);
      case 'create_order':
        await _api.post('/api/phone/v1/orders', data: payload, extraHeaders: headers);
      case 'patch_task':
        final taskId = payload['id'] ?? await _resolveTaskId(payload['client_id']);
        if (taskId == null) {
          throw ApiException('لم تتم مزامنة المهمة بعد');
        }
        await _api.patch('/api/phone/v1/tasks/$taskId', data: payload, extraHeaders: headers);
      case 'register_device':
        await _api.post('/api/phone/v1/devices/register', data: payload, extraHeaders: headers);
      case 'upload_recording':
        final callClientId = payload['call_client_id']?.toString() ?? '';
        final filePath = payload['file_path']?.toString() ?? '';
        if (filePath.isEmpty || !File(filePath).existsSync()) {
          return; // Cached file is gone; nothing to upload.
        }
        final callRow = await _db.getCallLog(callClientId);
        final serverId = callRow?['server_id'];
        if (serverId == null) {
          // upsert_call is queued ahead of this op; retry after it lands.
          throw ApiException('المكالمة لم تتزامن بعد');
        }
        try {
          await _api.postMultipart(
            '/api/phone/v1/calls/$serverId/recording',
            filePath: filePath,
            fields: {
              if (payload['duration_sec'] != null)
                'duration_sec': payload['duration_sec'],
              'client_id': callClientId,
            },
            extraHeaders: headers,
          );
        } on ApiException catch (e) {
          if (e.code == 'feature_disabled') {
            return; // Server turned the feature off; drop silently.
          }
          rethrow;
        }
        try {
          File(filePath).deleteSync();
        } catch (_) {}
      default:
        throw ApiException('Unknown outbox op: $op');
    }
  }

  Future<int?> _resolveTaskId(Object? clientId) async {
    if (clientId == null) return null;
    final rows = await _db.listTasks();
    for (final row in rows) {
      if (row['client_id'] == clientId) {
        final serverId = row['server_id'];
        if (serverId is int) return serverId;
        return int.tryParse('$serverId');
      }
    }
    return null;
  }
}
