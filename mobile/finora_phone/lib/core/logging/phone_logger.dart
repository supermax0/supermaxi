import 'dart:convert';
import 'dart:developer' as developer;

import '../storage/token_storage.dart';

/// Structured event logger. Masks phone numbers; never logs tokens/passwords.
class PhoneLogger {
  PhoneLogger({TokenStorage? storage}) : _storage = storage;

  final TokenStorage? _storage;
  final List<Map<String, dynamic>> _buffer = [];
  static const _maxBuffer = 200;

  static String maskPhone(String? raw) {
    final d = (raw ?? '').replaceAll(RegExp(r'[^0-9]'), '');
    if (d.length < 7) return '***';
    final head = d.substring(0, 4);
    final tail = d.substring(d.length - 4);
    return '$head***$tail';
  }

  Future<void> log(
    String event, {
    Map<String, dynamic>? data,
  }) async {
    final safe = <String, dynamic>{};
    if (data != null) {
      for (final e in data.entries) {
        final k = e.key.toLowerCase();
        if (k.contains('token') ||
            k.contains('password') ||
            k.contains('secret') ||
            k.contains('authorization')) {
          continue;
        }
        var v = e.value;
        if (k.contains('phone') || k.contains('number')) {
          v = maskPhone(v?.toString());
        }
        safe[e.key] = v;
      }
    }
    final row = {
      'ts': DateTime.now().toIso8601String(),
      'event': event,
      ...safe,
    };
    _buffer.add(row);
    if (_buffer.length > _maxBuffer) {
      _buffer.removeRange(0, _buffer.length - _maxBuffer);
    }
    developer.log(jsonEncode(row), name: 'finora_phone');
    try {
      await _storage?.appendDiagnosticLog(jsonEncode(row));
    } catch (_) {}
  }

  List<Map<String, dynamic>> recent({int limit = 50}) {
    if (_buffer.length <= limit) return List.from(_buffer);
    return _buffer.sublist(_buffer.length - limit);
  }

  void clear() => _buffer.clear();
}

/// Crash reporter port — local only in Phase 1.5; remote later.
abstract class CrashReporter {
  Future<void> recordError(Object error, StackTrace? stack, {String? reason});
  Future<void> recordFlutterError(Object error, StackTrace? stack);
  Future<List<String>> dumpLocal();
}

class LocalCrashReporter implements CrashReporter {
  LocalCrashReporter({required TokenStorage storage}) : _storage = storage;

  final TokenStorage _storage;

  @override
  Future<void> recordError(Object error, StackTrace? stack, {String? reason}) async {
    final line = jsonEncode({
      'ts': DateTime.now().toIso8601String(),
      'reason': reason,
      'error': error.toString(),
      'stack': stack?.toString().split('\n').take(12).join('\n'),
    });
    await _append(line);
  }

  @override
  Future<void> recordFlutterError(Object error, StackTrace? stack) =>
      recordError(error, stack, reason: 'flutter');

  Future<void> _append(String line) async {
    final prev = await _storage.readCrashLog() ?? '';
    final next = '$prev\n$line'.trim();
    final clipped = next.length > 50000 ? next.substring(next.length - 50000) : next;
    await _storage.writeCrashLog(clipped);
  }

  @override
  Future<List<String>> dumpLocal() async {
    final raw = await _storage.readCrashLog() ?? '';
    return raw.split('\n').where((e) => e.trim().isNotEmpty).toList();
  }
}
