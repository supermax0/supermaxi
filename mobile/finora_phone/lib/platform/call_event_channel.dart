import 'dart:async';

import 'package:flutter/services.dart';

import '../domain/entities/entities.dart';
import '../domain/ports/ports.dart';

/// Phase 1 companion: Android telephony → EventChannel.
/// Phase 2: replace with AndroidInCallServiceSource.
class AndroidTelephonyOverlaySource implements CallEventSource {
  AndroidTelephonyOverlaySource();

  static const _events = EventChannel('iq.finora.phone/calls');
  StreamSubscription? _sub;
  final _controller = StreamController<CallEvent>.broadcast();

  @override
  Stream<CallEvent> get events => _controller.stream;

  @override
  Future<void> start() async {
    _sub ??= _events.receiveBroadcastStream().listen((event) {
      if (event is Map) {
        _controller.add(CallEvent.fromMap(event));
      }
    }, onError: (_) {
      // Never crash — telecom reliability first.
    });
  }

  @override
  Future<void> stop() async {
    await _sub?.cancel();
    _sub = null;
  }
}

class OverlayChannel {
  static const _channel = MethodChannel('iq.finora.phone/overlay');

  Future<void> showShell({required String number}) async {
    try {
      await _channel.invokeMethod('showShell', {'number': number});
    } catch (_) {}
  }

  Future<void> updateCrm(Map<String, dynamic> payload) async {
    try {
      await _channel.invokeMethod('updateCrm', payload);
    } catch (_) {}
  }

  Future<void> hide() async {
    try {
      await _channel.invokeMethod('hide');
    } catch (_) {}
  }

  Future<void> expand() async {
    try {
      await _channel.invokeMethod('expand');
    } catch (_) {}
  }

  Future<String?> consumePendingAction() async {
    try {
      final v = await _channel.invokeMethod('consumePendingAction');
      if (v is Map) {
        final action = v['action']?.toString();
        if (action == null || action.isEmpty) return null;
        // Prefer structured consumePendingLaunch via OverlayChannel.
        return action;
      }
      if (v is String && v.isNotEmpty) return v;
      return null;
    } catch (_) {
      return null;
    }
  }

  /// Structured launch payload: action + number + optional local_call_uuid.
  Future<Map<String, String?>> consumePendingLaunch() async {
    try {
      final v = await _channel.invokeMethod('consumePendingAction');
      if (v is Map) {
        return {
          'action': v['action']?.toString(),
          'number': v['number']?.toString(),
          'local_call_uuid': v['local_call_uuid']?.toString(),
        };
      }
      if (v is String && v.isNotEmpty) {
        return {'action': v, 'number': null, 'local_call_uuid': null};
      }
      return {};
    } catch (_) {
      return {};
    }
  }
}

class PermissionsChannel {
  static const _channel = MethodChannel('iq.finora.phone/permissions');

  Future<Map<String, bool>> status() async {
    try {
      final raw = await _channel.invokeMethod<Map>('status');
      if (raw == null) return {};
      return raw.map((k, v) => MapEntry(k.toString(), v == true));
    } catch (_) {
      return {};
    }
  }

  Future<bool> requestPhone() async {
    try {
      return await _channel.invokeMethod<bool>('requestPhone') ?? false;
    } catch (_) {
      return false;
    }
  }

  Future<bool> requestCallLog() async {
    try {
      return await _channel.invokeMethod<bool>('requestCallLog') ?? false;
    } catch (_) {
      return false;
    }
  }

  Future<bool> requestOverlay() async {
    try {
      return await _channel.invokeMethod<bool>('requestOverlay') ?? false;
    } catch (_) {
      return false;
    }
  }

  Future<bool> requestNotifications() async {
    try {
      return await _channel.invokeMethod<bool>('requestNotifications') ?? false;
    } catch (_) {
      return false;
    }
  }

  Future<bool> requestBatteryOptimization() async {
    try {
      return await _channel.invokeMethod<bool>('requestBatteryOptimization') ??
          false;
    } catch (_) {
      return false;
    }
  }

  Future<bool> dialNumber(String number, {int? simSlot}) async {
    try {
      return await _channel.invokeMethod<bool>('dialNumber', {
            'number': number,
            if (simSlot != null) 'simSlot': simSlot,
          }) ??
          false;
    } catch (_) {
      return false;
    }
  }

  /// Apply FLAG_SECURE when blocking screenshots.
  Future<void> setBlockScreenshots(bool enabled) async {
    try {
      await _channel.invokeMethod('setBlockScreenshots', {'enabled': enabled});
    } catch (_) {}
  }

  Future<List<Map<String, dynamic>>> readRecentCallLog({int hours = 24}) async {
    try {
      final raw = await _channel.invokeMethod<List>('readRecentCallLog', {'hours': hours});
      if (raw == null) return [];
      return raw
          .whereType<Map>()
          .map((e) => Map<String, dynamic>.from(e))
          .toList();
    } catch (_) {
      return [];
    }
  }

  /// Native device facts for `/devices/register` (manufacturer / SIM slots…).
  Future<Map<String, dynamic>> deviceInfo() async {
    try {
      final raw = await _channel.invokeMethod<Map>('deviceInfo');
      if (raw == null) return {};
      return Map<String, dynamic>.from(raw);
    } catch (_) {
      return {};
    }
  }

  Future<bool> requestMediaAudio() async {
    try {
      return await _channel.invokeMethod<bool>('requestMediaAudio') ?? false;
    } catch (_) {
      return false;
    }
  }

  /// Finds the native dialer recording for a call window and copies it into
  /// the app cache. Returns null when no matching file exists.
  Future<Map<String, dynamic>?> findCallRecording({
    required String phone,
    required int startedAtMs,
    required int endedAtMs,
  }) async {
    try {
      final raw = await _channel.invokeMethod<Map>('findCallRecording', {
        'phone': phone,
        'startedAtMs': startedAtMs,
        'endedAtMs': endedAtMs,
      });
      if (raw == null) return null;
      return Map<String, dynamic>.from(raw);
    } catch (_) {
      return null;
    }
  }

  Future<void> deleteCachedRecording(String path) async {
    try {
      await _channel.invokeMethod('deleteCachedRecording', {'path': path});
    } catch (_) {}
  }

  /// Opens a local audio file natively (MediaPlayer). Returns duration in ms,
  /// or null when the file cannot be played.
  Future<int?> playerOpen(String path) async {
    try {
      final raw = await _channel.invokeMethod<Map>('playerOpen', {'path': path});
      if (raw == null || raw['ok'] != true) return null;
      return (raw['durationMs'] as num?)?.toInt() ?? 0;
    } catch (_) {
      return null;
    }
  }

  Future<void> playerPlay() async {
    try {
      await _channel.invokeMethod('playerPlay');
    } catch (_) {}
  }

  Future<void> playerPause() async {
    try {
      await _channel.invokeMethod('playerPause');
    } catch (_) {}
  }

  Future<void> playerSeek(int positionMs) async {
    try {
      await _channel.invokeMethod('playerSeek', {'positionMs': positionMs});
    } catch (_) {}
  }

  Future<Map<String, dynamic>> playerState() async {
    try {
      final raw = await _channel.invokeMethod<Map>('playerState');
      if (raw == null) return {};
      return Map<String, dynamic>.from(raw);
    } catch (_) {
      return {};
    }
  }

  Future<void> playerStop() async {
    try {
      await _channel.invokeMethod('playerStop');
    } catch (_) {}
  }
}
