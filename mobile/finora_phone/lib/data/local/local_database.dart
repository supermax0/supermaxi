import 'dart:convert';

import 'package:path/path.dart' as p;
import 'package:path_provider/path_provider.dart';
import 'package:sqflite/sqflite.dart';

/// Local SQLite store (offline-first).
/// v3: local_call_uuid, call_status vs sync_status, dialing/cancelled, UTC meta.
/// v4: field_latency_samples for Field Day P95.
/// v5: favorites table.
/// v6: call outcomes + smart follow-up + recent searches.
class LocalDatabase {
  LocalDatabase();

  Database? _db;
  static const schemaVersion = 6;

  Future<Database> get database async {
    if (_db != null) return _db!;
    _db = await _open();
    return _db!;
  }

  Future<Database> _open() async {
    final dir = await getApplicationDocumentsDirectory();
    final path = p.join(dir.path, 'finora_phone.db');
    return openDatabase(
      path,
      version: schemaVersion,
      onCreate: (db, version) async {
        await _createV2(db);
        await _migrateV2toV3(db);
        await _migrateV3toV4(db);
        await _migrateV4toV5(db);
        await _migrateV5toV6(db);
      },
      onUpgrade: (db, oldVersion, newVersion) async {
        if (oldVersion < 2) {
          await _migrateV1toV2(db);
        }
        if (oldVersion < 3) {
          await _migrateV2toV3(db);
        }
        if (oldVersion < 4) {
          await _migrateV3toV4(db);
        }
        if (oldVersion < 5) {
          await _migrateV4toV5(db);
        }
        if (oldVersion < 6) {
          await _migrateV5toV6(db);
        }
      },
    );
  }

  Future<void> _createV2(Database db) async {
    await db.execute('''
CREATE TABLE customers_cache (
  id INTEGER,
  phone_normalized TEXT PRIMARY KEY,
  phone2 TEXT,
  payload_json TEXT NOT NULL,
  updated_at TEXT NOT NULL
)''');
    await db.execute('''
CREATE TABLE call_logs (
  client_id TEXT PRIMARY KEY,
  local_call_uuid TEXT,
  idempotency_key TEXT UNIQUE,
  reconciliation_fingerprint TEXT,
  phone TEXT NOT NULL,
  direction TEXT NOT NULL,
  status TEXT NOT NULL,
  started_at TEXT NOT NULL,
  ended_at TEXT,
  duration_sec INTEGER,
  detected_at TEXT,
  ringing_at TEXT,
  dialing_at TEXT,
  answered_at TEXT,
  cancelled_at TEXT,
  failed_at TEXT,
  synced_at TEXT,
  customer_id INTEGER,
  customer_name TEXT,
  sync_status TEXT NOT NULL,
  server_id INTEGER,
  note TEXT,
  device_id TEXT,
  sim_slot INTEGER
)''');
    await db.execute(
      'CREATE INDEX IF NOT EXISTS ix_call_local_uuid ON call_logs(local_call_uuid)',
    );
    await db.execute(
      'CREATE INDEX IF NOT EXISTS ix_call_recon ON call_logs(reconciliation_fingerprint)',
    );
    await db.execute('''
CREATE TABLE notes (
  client_id TEXT PRIMARY KEY,
  body TEXT NOT NULL,
  call_client_id TEXT,
  customer_id INTEGER,
  sync_status TEXT NOT NULL,
  updated_at TEXT
)''');
    await db.execute('''
CREATE TABLE tasks (
  client_id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  phone TEXT NOT NULL,
  customer_id INTEGER,
  due_at TEXT,
  status TEXT NOT NULL,
  source TEXT NOT NULL,
  attempt_count INTEGER NOT NULL DEFAULT 1,
  sync_status TEXT NOT NULL,
  server_id INTEGER
)''');
    await db.execute('''
CREATE TABLE outbox (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  op TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  idempotency_key TEXT NOT NULL UNIQUE,
  status TEXT NOT NULL DEFAULT 'pending',
  retry_count INTEGER NOT NULL DEFAULT 0,
  attempts INTEGER NOT NULL DEFAULT 0,
  next_retry_at TEXT,
  last_error TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
)''');
    await db.execute('''
CREATE TABLE meta (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
)''');
    await db.execute('''
CREATE TABLE order_drafts (
  client_id TEXT PRIMARY KEY,
  customer_id INTEGER NOT NULL,
  payload_json TEXT NOT NULL,
  sync_status TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'draft',
  created_at TEXT NOT NULL
)''');
    await db.execute('''
CREATE TABLE active_session (
  id INTEGER PRIMARY KEY CHECK (id = 1),
  call_client_id TEXT,
  local_call_uuid TEXT,
  note_draft TEXT,
  payload_json TEXT,
  updated_at TEXT NOT NULL
)''');
    await db.execute('''
CREATE TABLE field_metrics (
  key TEXT PRIMARY KEY,
  value REAL NOT NULL,
  updated_at TEXT NOT NULL
)''');
  }

  Future<void> _migrateV2toV3(Database db) async {
    Future<void> add(String sql) async {
      try {
        await db.execute(sql);
      } catch (_) {}
    }

    final cols = await db.rawQuery('PRAGMA table_info(call_logs)');
    final names = cols.map((c) => c['name'] as String).toSet();
    if (!names.contains('local_call_uuid')) {
      await add('ALTER TABLE call_logs ADD COLUMN local_call_uuid TEXT');
    }
    if (!names.contains('reconciliation_fingerprint')) {
      await add(
          'ALTER TABLE call_logs ADD COLUMN reconciliation_fingerprint TEXT');
    }
    if (!names.contains('dialing_at')) {
      await add('ALTER TABLE call_logs ADD COLUMN dialing_at TEXT');
    }
    if (!names.contains('cancelled_at')) {
      await add('ALTER TABLE call_logs ADD COLUMN cancelled_at TEXT');
    }
    if (!names.contains('failed_at')) {
      await add('ALTER TABLE call_logs ADD COLUMN failed_at TEXT');
    }
    // Split legacy status=synced into call_status ended + sync_status synced
    await add(
      "UPDATE call_logs SET sync_status = 'synced', status = 'ended' WHERE status = 'synced'",
    );
    await add(
      'CREATE INDEX IF NOT EXISTS ix_call_local_uuid ON call_logs(local_call_uuid)',
    );
    await add(
      'CREATE INDEX IF NOT EXISTS ix_call_recon ON call_logs(reconciliation_fingerprint)',
    );

    final sessionCols = await db.rawQuery('PRAGMA table_info(active_session)');
    final sNames = sessionCols.map((c) => c['name'] as String).toSet();
    if (!sNames.contains('local_call_uuid')) {
      await add('ALTER TABLE active_session ADD COLUMN local_call_uuid TEXT');
    }

    final odCols = await db.rawQuery('PRAGMA table_info(order_drafts)');
    final oNames = odCols.map((c) => c['name'] as String).toSet();
    if (!oNames.contains('status')) {
      await add(
          "ALTER TABLE order_drafts ADD COLUMN status TEXT NOT NULL DEFAULT 'draft'");
    }

    final taskCols = await db.rawQuery('PRAGMA table_info(tasks)');
    final tNames = taskCols.map((c) => c['name'] as String).toSet();
    if (!tNames.contains('attempt_count')) {
      await add(
          'ALTER TABLE tasks ADD COLUMN attempt_count INTEGER NOT NULL DEFAULT 1');
    }

    await db.execute('''
CREATE TABLE IF NOT EXISTS field_metrics (
  key TEXT PRIMARY KEY,
  value REAL NOT NULL,
  updated_at TEXT NOT NULL
)''');
  }

  Future<void> _migrateV3toV4(Database db) async {
    await db.execute('''
CREATE TABLE IF NOT EXISTS field_latency_samples (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  metric TEXT NOT NULL,
  value_ms REAL NOT NULL,
  recorded_at TEXT NOT NULL
)''');
    await db.execute(
      'CREATE INDEX IF NOT EXISTS ix_latency_metric ON field_latency_samples(metric)',
    );
  }

  Future<void> _migrateV4toV5(Database db) async {
    await db.execute('''
CREATE TABLE IF NOT EXISTS favorites (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  customer_id INTEGER,
  phone TEXT NOT NULL,
  name TEXT NOT NULL,
  created_at TEXT NOT NULL,
  UNIQUE(phone)
)''');
  }

  Future<void> _migrateV5toV6(Database db) async {
    Future<void> add(String sql) async {
      try {
        await db.execute(sql);
      } catch (_) {}
    }

    final cols = await db.rawQuery('PRAGMA table_info(call_logs)');
    final names = cols.map((c) => c['name'] as String).toSet();
    for (final col in [
      "ALTER TABLE call_logs ADD COLUMN outcome TEXT",
      "ALTER TABLE call_logs ADD COLUMN outcome_note TEXT",
      "ALTER TABLE call_logs ADD COLUMN follow_up_required INTEGER NOT NULL DEFAULT 0",
      "ALTER TABLE call_logs ADD COLUMN follow_up_at TEXT",
      "ALTER TABLE call_logs ADD COLUMN outcome_recorded_at TEXT",
      "ALTER TABLE call_logs ADD COLUMN outcome_client_id TEXT",
      "ALTER TABLE call_logs ADD COLUMN unclassified INTEGER NOT NULL DEFAULT 0",
    ]) {
      final name = col.split('ADD COLUMN ').last.split(' ').first;
      if (!names.contains(name)) await add(col);
    }

    final taskCols = await db.rawQuery('PRAGMA table_info(tasks)');
    final tNames = taskCols.map((c) => c['name'] as String).toSet();
    for (final col in [
      "ALTER TABLE tasks ADD COLUMN task_type TEXT",
      "ALTER TABLE tasks ADD COLUMN priority TEXT NOT NULL DEFAULT 'normal'",
      "ALTER TABLE tasks ADD COLUMN reason TEXT",
      "ALTER TABLE tasks ADD COLUMN resolved_by_call_id INTEGER",
      "ALTER TABLE tasks ADD COLUMN snoozed_until TEXT",
      "ALTER TABLE tasks ADD COLUMN call_id INTEGER",
    ]) {
      final name = col.split('ADD COLUMN ').last.split(' ').first;
      if (!tNames.contains(name)) await add(col);
    }

    await db.execute('''
CREATE TABLE IF NOT EXISTS recent_searches (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  query TEXT NOT NULL UNIQUE,
  created_at TEXT NOT NULL
)''');
    await db.execute('''
CREATE TABLE IF NOT EXISTS timeline_cache (
  customer_id INTEGER PRIMARY KEY,
  payload_json TEXT NOT NULL,
  updated_at TEXT NOT NULL
)''');
  }

  Future<void> _migrateV1toV2(Database db) async {
    final cols = await db.rawQuery('PRAGMA table_info(call_logs)');
    final names = cols.map((c) => c['name'] as String).toSet();
    Future<void> add(String sql) async {
      try {
        await db.execute(sql);
      } catch (_) {}
    }

    if (!names.contains('idempotency_key')) {
      await add('ALTER TABLE call_logs ADD COLUMN idempotency_key TEXT');
    }
    if (!names.contains('detected_at')) {
      await add('ALTER TABLE call_logs ADD COLUMN detected_at TEXT');
    }
    if (!names.contains('ringing_at')) {
      await add('ALTER TABLE call_logs ADD COLUMN ringing_at TEXT');
    }
    if (!names.contains('answered_at')) {
      await add('ALTER TABLE call_logs ADD COLUMN answered_at TEXT');
    }
    if (!names.contains('synced_at')) {
      await add('ALTER TABLE call_logs ADD COLUMN synced_at TEXT');
    }
    if (!names.contains('device_id')) {
      await add('ALTER TABLE call_logs ADD COLUMN device_id TEXT');
    }
    if (!names.contains('sim_slot')) {
      await add('ALTER TABLE call_logs ADD COLUMN sim_slot INTEGER');
    }

    final outboxCols = await db.rawQuery('PRAGMA table_info(outbox)');
    final oNames = outboxCols.map((c) => c['name'] as String).toSet();
    if (!oNames.contains('status')) {
      await add(
          "ALTER TABLE outbox ADD COLUMN status TEXT NOT NULL DEFAULT 'pending'");
    }
    if (!oNames.contains('retry_count')) {
      await add(
          'ALTER TABLE outbox ADD COLUMN retry_count INTEGER NOT NULL DEFAULT 0');
    }
    if (!oNames.contains('updated_at')) {
      await add('ALTER TABLE outbox ADD COLUMN updated_at TEXT');
      await add(
          "UPDATE outbox SET updated_at = created_at WHERE updated_at IS NULL");
    }
    await db.execute('''
CREATE TABLE IF NOT EXISTS active_session (
  id INTEGER PRIMARY KEY CHECK (id = 1),
  call_client_id TEXT,
  note_draft TEXT,
  payload_json TEXT,
  updated_at TEXT NOT NULL
)''');
  }

  Future<void> upsertCustomerCache({
    required String phoneNormalized,
    String? phone2,
    int? id,
    required Map<String, dynamic> payload,
  }) async {
    final db = await database;
    await db.insert(
      'customers_cache',
      {
        'id': id,
        'phone_normalized': phoneNormalized,
        'phone2': phone2,
        'payload_json': jsonEncode(payload),
        'updated_at': DateTime.now().toIso8601String(),
      },
      conflictAlgorithm: ConflictAlgorithm.replace,
    );
  }

  Future<Map<String, dynamic>?> getCustomerByPhone(String phoneNormalized) async {
    final db = await database;
    final rows = await db.query(
      'customers_cache',
      where: 'phone_normalized = ? OR phone2 = ? OR phone_normalized LIKE ?',
      whereArgs: [
        phoneNormalized,
        phoneNormalized,
        '%${phoneNormalized.length >= 10 ? phoneNormalized.substring(phoneNormalized.length - 10) : phoneNormalized}',
      ],
      limit: 1,
    );
    if (rows.isEmpty) return null;
    return jsonDecode(rows.first['payload_json'] as String)
        as Map<String, dynamic>;
  }

  Future<int> customerCacheCount() async {
    final db = await database;
    final r = await db.rawQuery('SELECT COUNT(*) AS c FROM customers_cache');
    return (r.first['c'] as int?) ?? 0;
  }

  Future<List<Map<String, dynamic>>> searchCustomers(String q) async {
    final db = await database;
    final rows = await db.query('customers_cache', limit: 50);
    final needle = q.toLowerCase();
    return rows
        .map((r) =>
            jsonDecode(r['payload_json'] as String) as Map<String, dynamic>)
        .where((m) {
          final name = '${m['name'] ?? ''}'.toLowerCase();
          final phone = '${m['phone'] ?? ''}';
          return needle.isEmpty || name.contains(needle) || phone.contains(q);
        })
        .toList();
  }

  Future<void> upsertCallLog(Map<String, Object?> row) async {
    final db = await database;
    // Prefer match by idempotency_key to prevent duplicates.
    final key = row['idempotency_key'] as String?;
    if (key != null && key.isNotEmpty) {
      final existing = await db.query(
        'call_logs',
        where: 'idempotency_key = ?',
        whereArgs: [key],
        limit: 1,
      );
      if (existing.isNotEmpty) {
        final clientId = existing.first['client_id'] as String;
        row = Map<String, Object?>.from(row)..['client_id'] = clientId;
        await db.update('call_logs', row, where: 'client_id = ?', whereArgs: [clientId]);
        return;
      }
    }
    await db.insert('call_logs', row, conflictAlgorithm: ConflictAlgorithm.replace);
  }

  Future<List<Map<String, Object?>>> listCallLogs({int limit = 200}) async {
    final db = await database;
    return db.query('call_logs', orderBy: 'started_at DESC', limit: limit);
  }

  Future<Map<String, Object?>?> getCallLog(String clientId) async {
    final db = await database;
    final rows = await db.query(
      'call_logs',
      where: 'client_id = ?',
      whereArgs: [clientId],
      limit: 1,
    );
    return rows.isEmpty ? null : rows.first;
  }

  Future<Map<String, Object?>?> getCallLogByIdempotency(String key) async {
    final db = await database;
    final rows = await db.query(
      'call_logs',
      where: 'idempotency_key = ?',
      whereArgs: [key],
      limit: 1,
    );
    return rows.isEmpty ? null : rows.first;
  }

  Future<void> markCallSynced(String clientId) async {
    final db = await database;
    await db.update(
      'call_logs',
      {
        'sync_status': 'synced',
        'synced_at': DateTime.now().toUtc().toIso8601String(),
        // Do NOT overwrite call_status with "synced"
      },
      where: 'client_id = ?',
      whereArgs: [clientId],
    );
  }

  Future<Map<String, Object?>?> getCallByLocalUuid(String uuid) async {
    final db = await database;
    final rows = await db.query(
      'call_logs',
      where: 'local_call_uuid = ?',
      whereArgs: [uuid],
      limit: 1,
    );
    return rows.isEmpty ? null : rows.first;
  }

  Future<Map<String, Object?>?> getCallByRecon(String fingerprint) async {
    final db = await database;
    final rows = await db.query(
      'call_logs',
      where: 'reconciliation_fingerprint = ?',
      whereArgs: [fingerprint],
      limit: 1,
    );
    return rows.isEmpty ? null : rows.first;
  }

  Future<int> callLogCount() async {
    final db = await database;
    final r = await db.rawQuery('SELECT COUNT(*) AS c FROM call_logs');
    return (r.first['c'] as int?) ?? 0;
  }

  Future<void> setMeta(String key, String value) async {
    final db = await database;
    await db.insert(
      'meta',
      {'key': key, 'value': value},
      conflictAlgorithm: ConflictAlgorithm.replace,
    );
  }

  Future<String?> getMeta(String key) async {
    final db = await database;
    final rows =
        await db.query('meta', where: 'key = ?', whereArgs: [key], limit: 1);
    if (rows.isEmpty) return null;
    return rows.first['value'] as String?;
  }

  Future<void> bumpMetric(String key, [double delta = 1]) async {
    final db = await database;
    final rows = await db.query(
      'field_metrics',
      where: 'key = ?',
      whereArgs: [key],
      limit: 1,
    );
    final prev = rows.isEmpty ? 0.0 : (rows.first['value'] as num).toDouble();
    await db.insert(
      'field_metrics',
      {
        'key': key,
        'value': prev + delta,
        'updated_at': DateTime.now().toUtc().toIso8601String(),
      },
      conflictAlgorithm: ConflictAlgorithm.replace,
    );
  }

  Future<Map<String, double>> allMetrics() async {
    final db = await database;
    final rows = await db.query('field_metrics');
    return {
      for (final r in rows) r['key'] as String: (r['value'] as num).toDouble(),
    };
  }

  Future<void> recordLatencySample(String metric, double valueMs) async {
    final db = await database;
    await db.insert('field_latency_samples', {
      'metric': metric,
      'value_ms': valueMs,
      'recorded_at': DateTime.now().toUtc().toIso8601String(),
    });
    // Keep last ~200 samples per metric.
    await db.rawDelete(
      '''
DELETE FROM field_latency_samples WHERE id NOT IN (
  SELECT id FROM field_latency_samples
  WHERE metric = ?
  ORDER BY id DESC
  LIMIT 200
) AND metric = ?
''',
      [metric, metric],
    );
  }

  Future<double?> latencyPercentile(String metric, double p) async {
    final db = await database;
    final rows = await db.query(
      'field_latency_samples',
      columns: ['value_ms'],
      where: 'metric = ?',
      whereArgs: [metric],
      orderBy: 'value_ms ASC',
    );
    if (rows.isEmpty) return null;
    final values =
        rows.map((r) => (r['value_ms'] as num).toDouble()).toList();
    final idx = ((p.clamp(0, 100) / 100.0) * (values.length - 1)).round();
    return values[idx.clamp(0, values.length - 1)];
  }

  Future<int> duplicateFingerprintCount() async {
    final db = await database;
    final rows = await db.rawQuery('''
SELECT reconciliation_fingerprint AS fp, COUNT(*) AS c
FROM call_logs
WHERE reconciliation_fingerprint IS NOT NULL
  AND reconciliation_fingerprint != ''
GROUP BY reconciliation_fingerprint
HAVING c > 1
''');
    var total = 0;
    for (final r in rows) {
      total += ((r['c'] as num?)?.toInt() ?? 0) - 1;
    }
    return total;
  }

  Future<Map<String, Object?>> fieldDaySnapshot({
    required int androidCallLogCount,
    required int matchedCallLogCount,
  }) async {
    final metrics = await allMetrics();
    final localCount = await callLogCount();
    final outbox = await outboxCounts();
    final p95Number = await latencyPercentile('number_shown_ms', 95);
    final p95Crm = await latencyPercentile('local_crm_ms', 95);
    final dupes = await duplicateFingerprintCount();
    final missing = (androidCallLogCount - matchedCallLogCount)
        .clamp(0, androidCallLogCount);
    final overlayShown = metrics['overlay_shown_count'] ?? 0;
    final overlayFailed = metrics['overlay_failed_count'] ?? 0;
    final detected = metrics['total_detected_calls'] ?? localCount.toDouble();
    final sumNumber = metrics['sum_number_shown_ms'] ?? 0;
    final sumCrm = metrics['sum_local_crm_ms'] ?? 0;
    final avgNumber =
        overlayShown > 0 ? sumNumber / overlayShown : null;
    final avgCrm = overlayShown > 0 ? sumCrm / overlayShown : null;

    return {
      'android_calllog_count_24h': androidCallLogCount,
      'local_call_count': localCount,
      'matched_calllog_count': matchedCallLogCount,
      'missing_vs_calllog': missing,
      'duplicate_calls_extra': dupes,
      'total_detected_calls': detected,
      'overlay_shown_count': overlayShown,
      'overlay_failed_count': overlayFailed,
      'p95_number_shown_ms': p95Number,
      'p95_local_crm_ms': p95Crm,
      'avg_number_shown_ms': avgNumber,
      'avg_local_crm_ms': avgCrm,
      'pending_outbox': outbox['pending'],
      'failed_outbox': outbox['failed'],
      'permanently_failed_outbox': outbox['permanently_failed'],
      'targets': {
        'missing_vs_calllog': 0,
        'duplicate_calls': 0,
        'p95_number_shown_ms': 500,
        'p95_local_crm_ms': 800,
        'permanently_failed': 0,
      },
      'pass': {
        'missing': missing == 0,
        'duplicates': dupes == 0,
        'p95_number': p95Number == null || p95Number < 500,
        'p95_crm': p95Crm == null || p95Crm < 800,
        'permanently_failed': (outbox['permanently_failed'] ?? 0) == 0,
      },
      'generated_at': DateTime.now().toUtc().toIso8601String(),
    };
  }

  Future<void> upsertNote(Map<String, Object?> row) async {
    final db = await database;
    row = Map<String, Object?>.from(row)
      ..['updated_at'] = DateTime.now().toIso8601String();
    await db.insert('notes', row, conflictAlgorithm: ConflictAlgorithm.replace);
  }

  Future<List<Map<String, Object?>>> listNotesByCustomer(int customerId) async {
    final db = await database;
    return db.query(
      'notes',
      where: 'customer_id = ?',
      whereArgs: [customerId],
      orderBy: 'updated_at DESC',
      limit: 50,
    );
  }

  Future<List<Map<String, Object?>>> listFavorites({int limit = 20}) async {
    final db = await database;
    return db.query('favorites', orderBy: 'created_at DESC', limit: limit);
  }

  Future<bool> isFavorite({int? customerId, required String phone}) async {
    final db = await database;
    final rows = await db.query(
      'favorites',
      where: customerId != null ? 'customer_id = ? OR phone = ?' : 'phone = ?',
      whereArgs: customerId != null ? [customerId, phone] : [phone],
      limit: 1,
    );
    return rows.isNotEmpty;
  }

  Future<void> addFavorite({
    int? customerId,
    required String phone,
    required String name,
  }) async {
    final db = await database;
    await db.insert(
      'favorites',
      {
        'customer_id': customerId,
        'phone': phone,
        'name': name,
        'created_at': DateTime.now().toUtc().toIso8601String(),
      },
      conflictAlgorithm: ConflictAlgorithm.replace,
    );
  }

  Future<void> removeFavorite({int? customerId, required String phone}) async {
    final db = await database;
    if (customerId != null) {
      await db.delete(
        'favorites',
        where: 'customer_id = ? OR phone = ?',
        whereArgs: [customerId, phone],
      );
    } else {
      await db.delete('favorites', where: 'phone = ?', whereArgs: [phone]);
    }
  }

  Future<void> upsertTask(Map<String, Object?> row) async {
    final db = await database;
    await db.insert('tasks', row, conflictAlgorithm: ConflictAlgorithm.replace);
  }

  Future<List<Map<String, Object?>>> listTasks({String? status}) async {
    final db = await database;
    if (status == null) {
      return db.query('tasks', orderBy: 'due_at ASC');
    }
    return db.query(
      'tasks',
      where: 'status = ?',
      whereArgs: [status],
      orderBy: 'due_at ASC',
    );
  }

  Future<List<Map<String, Object?>>> listUnclassifiedCalls({int limit = 50}) async {
    final db = await database;
    return db.query(
      'call_logs',
      where:
          "(outcome IS NULL OR outcome = '') AND (unclassified = 1 OR status IN ('answered','ended'))",
      orderBy: 'started_at DESC',
      limit: limit,
    );
  }

  Future<void> setCallOutcomeLocal({
    required String clientId,
    required String outcome,
    String? outcomeNote,
    bool followUpRequired = false,
    String? followUpAt,
    required String outcomeClientId,
  }) async {
    final db = await database;
    await db.update(
      'call_logs',
      {
        'outcome': outcome,
        'outcome_note': outcomeNote,
        'follow_up_required': followUpRequired ? 1 : 0,
        'follow_up_at': followUpAt,
        'outcome_recorded_at': DateTime.now().toUtc().toIso8601String(),
        'outcome_client_id': outcomeClientId,
        'unclassified': 0,
      },
      where: 'client_id = ?',
      whereArgs: [clientId],
    );
  }

  Future<void> markCallUnclassified(String clientId) async {
    final db = await database;
    await db.update(
      'call_logs',
      {'unclassified': 1},
      where: 'client_id = ?',
      whereArgs: [clientId],
    );
  }

  Future<void> saveRecentSearch(String query) async {
    final q = query.trim();
    if (q.isEmpty) return;
    final db = await database;
    final now = DateTime.now().toIso8601String();
    await db.insert(
      'recent_searches',
      {'query': q, 'created_at': now},
      conflictAlgorithm: ConflictAlgorithm.replace,
    );
    // Keep last 20
    await db.rawDelete(
      'DELETE FROM recent_searches WHERE id NOT IN '
      '(SELECT id FROM recent_searches ORDER BY created_at DESC LIMIT 20)',
    );
  }

  Future<List<String>> listRecentSearches({int limit = 12}) async {
    final db = await database;
    final rows = await db.query(
      'recent_searches',
      orderBy: 'created_at DESC',
      limit: limit,
    );
    return rows.map((r) => r['query'] as String).toList();
  }

  Future<void> clearRecentSearches() async {
    final db = await database;
    await db.delete('recent_searches');
  }

  Future<void> cacheTimeline(int customerId, Map<String, dynamic> payload) async {
    final db = await database;
    await db.insert(
      'timeline_cache',
      {
        'customer_id': customerId,
        'payload_json': jsonEncode(payload),
        'updated_at': DateTime.now().toUtc().toIso8601String(),
      },
      conflictAlgorithm: ConflictAlgorithm.replace,
    );
  }

  Future<Map<String, dynamic>?> readTimelineCache(int customerId) async {
    final db = await database;
    final rows = await db.query(
      'timeline_cache',
      where: 'customer_id = ?',
      whereArgs: [customerId],
      limit: 1,
    );
    if (rows.isEmpty) return null;
    try {
      final raw = jsonDecode(rows.first['payload_json'] as String);
      if (raw is Map) return Map<String, dynamic>.from(raw);
    } catch (_) {}
    return null;
  }

  Future<void> enqueueOutbox({
    required String op,
    required Map<String, dynamic> payload,
    required String idempotencyKey,
  }) async {
    final db = await database;
    final now = DateTime.now().toIso8601String();
    await db.insert(
      'outbox',
      {
        'op': op,
        'payload_json': jsonEncode(payload),
        'idempotency_key': idempotencyKey,
        'status': 'pending',
        'retry_count': 0,
        'attempts': 0,
        'next_retry_at': now,
        'created_at': now,
        'updated_at': now,
      },
      conflictAlgorithm: ConflictAlgorithm.ignore,
    );
  }

  Future<List<Map<String, Object?>>> pendingOutbox({int limit = 50}) async {
    final db = await database;
    final now = DateTime.now().toIso8601String();
    return db.query(
      'outbox',
      where:
          "(status = 'pending' OR status = 'failed') AND (next_retry_at IS NULL OR next_retry_at <= ?)",
      whereArgs: [now],
      orderBy: 'id ASC',
      limit: limit,
    );
  }

  Future<Map<String, int>> outboxCounts() async {
    final db = await database;
    Future<int> count(String status) async {
      final r = await db.rawQuery(
        'SELECT COUNT(*) AS c FROM outbox WHERE status = ?',
        [status],
      );
      return (r.first['c'] as int?) ?? 0;
    }

    return {
      'pending': await count('pending'),
      'syncing': await count('syncing'),
      'failed': await count('failed'),
      'permanently_failed': await count('permanently_failed'),
    };
  }

  Future<void> setOutboxStatus(int id, String status, {String? error}) async {
    final db = await database;
    await db.update(
      'outbox',
      {
        'status': status,
        if (error != null) 'last_error': error,
        'updated_at': DateTime.now().toIso8601String(),
      },
      where: 'id = ?',
      whereArgs: [id],
    );
  }

  Future<void> deleteOutbox(int id) async {
    final db = await database;
    await db.delete('outbox', where: 'id = ?', whereArgs: [id]);
  }

  Future<List<Map<String, Object?>>> permanentlyFailedOutbox({int limit = 100}) async {
    final db = await database;
    return db.query(
      'outbox',
      where: "status = 'permanently_failed'",
      orderBy: 'id DESC',
      limit: limit,
    );
  }

  Future<void> retryOutbox(int id) async {
    final db = await database;
    await db.update(
      'outbox',
      {
        'status': 'pending',
        'next_retry_at': DateTime.now().toIso8601String(),
        'updated_at': DateTime.now().toIso8601String(),
      },
      where: 'id = ?',
      whereArgs: [id],
    );
  }

  Future<void> retryAllPermanentlyFailed() async {
    final db = await database;
    await db.update(
      'outbox',
      {
        'status': 'pending',
        'next_retry_at': DateTime.now().toIso8601String(),
        'updated_at': DateTime.now().toIso8601String(),
      },
      where: "status = 'permanently_failed'",
    );
  }

  Future<void> bumpOutbox(
    int id,
    String error,
    Duration backoff, {
    bool permanent = false,
  }) async {
    final db = await database;
    final rows = await db.query('outbox', where: 'id = ?', whereArgs: [id]);
    if (rows.isEmpty) return;
    final attempts = (rows.first['attempts'] as int? ?? 0) + 1;
    final retryCount = (rows.first['retry_count'] as int? ?? 0) + 1;
    await db.update(
      'outbox',
      {
        'attempts': attempts,
        'retry_count': retryCount,
        'last_error': error,
        'status': permanent ? 'permanently_failed' : 'failed',
        'next_retry_at': DateTime.now().add(backoff).toIso8601String(),
        'updated_at': DateTime.now().toIso8601String(),
      },
      where: 'id = ?',
      whereArgs: [id],
    );
  }

  Future<void> upsertOrderDraft(Map<String, Object?> row) async {
    final db = await database;
    await db.insert('order_drafts', row,
        conflictAlgorithm: ConflictAlgorithm.replace);
  }

  Future<List<Map<String, Object?>>> listOrderDrafts({int limit = 50}) async {
    final db = await database;
    return db.query('order_drafts', orderBy: 'created_at DESC', limit: limit);
  }

  Future<void> saveActiveSession({
    String? callClientId,
    String? noteDraft,
    Map<String, dynamic>? payload,
  }) async {
    final db = await database;
    await db.insert(
      'active_session',
      {
        'id': 1,
        'call_client_id': callClientId,
        'note_draft': noteDraft,
        'payload_json': payload == null ? null : jsonEncode(payload),
        'updated_at': DateTime.now().toIso8601String(),
      },
      conflictAlgorithm: ConflictAlgorithm.replace,
    );
  }

  Future<Map<String, Object?>?> readActiveSession() async {
    final db = await database;
    final rows = await db.query('active_session', where: 'id = 1', limit: 1);
    return rows.isEmpty ? null : rows.first;
  }

  Future<void> clearActiveSession() async {
    final db = await database;
    await db.delete('active_session', where: 'id = 1');
  }

  Future<bool> ping() async {
    try {
      final db = await database;
      await db.rawQuery('SELECT 1');
      return true;
    } catch (_) {
      return false;
    }
  }

  /// Wipe business data after device revoke (keeps schema).
  Future<void> wipeBusinessData() async {
    final db = await database;
    for (final t in [
      'customers_cache',
      'call_logs',
      'notes',
      'tasks',
      'outbox',
      'order_drafts',
      'active_session',
      'meta',
      'favorites',
      'recent_searches',
      'timeline_cache',
    ]) {
      await db.delete(t);
    }
  }
}
