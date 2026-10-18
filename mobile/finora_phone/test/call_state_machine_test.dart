import 'package:finora_phone/core/time/utc_time.dart';
import 'package:finora_phone/data/mappers/phone_normalize.dart';
import 'package:finora_phone/domain/usecases/call_state_machine.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  group('CallStateMachine inbound', () {
    test('detected → ringing → answered → ended (no synced call state)', () {
      final m = CallStateMachine();
      expect(m.transition(CallLifecycleState.ringing), isTrue);
      expect(m.transition(CallLifecycleState.answered), isTrue);
      expect(m.transition(CallLifecycleState.ended), isTrue);
      expect(m.isTerminal, isTrue);
    });

    test('rejects answered → ringing', () {
      final m = CallStateMachine();
      m.transition(CallLifecycleState.ringing);
      m.transition(CallLifecycleState.answered);
      expect(m.transition(CallLifecycleState.ringing), isFalse);
    });

    test('missed from ringing', () {
      final m = CallStateMachine();
      m.transition(CallLifecycleState.ringing);
      expect(m.transition(CallLifecycleState.missed), isTrue);
    });

    test('talk duration excludes ring time', () {
      final m = CallStateMachine();
      final t0 = DateTime.utc(2026, 1, 1, 12, 0, 0);
      m.transition(CallLifecycleState.ringing, at: t0);
      m.transition(
        CallLifecycleState.answered,
        at: t0.add(const Duration(seconds: 10)),
      );
      m.transition(
        CallLifecycleState.ended,
        at: t0.add(const Duration(seconds: 40)),
      );
      expect(m.timestamps.talkDurationSec, 30);
    });
  });

  group('CallStateMachine outbound', () {
    test('detected → dialing → answered → ended', () {
      final m = CallStateMachine(direction: 'outbound');
      expect(m.transition(CallLifecycleState.dialing), isTrue);
      expect(m.transition(CallLifecycleState.answered), isTrue);
      expect(m.transition(CallLifecycleState.ended), isTrue);
    });

    test('dialing → cancelled', () {
      final m = CallStateMachine(direction: 'outbound');
      m.transition(CallLifecycleState.dialing);
      expect(m.transition(CallLifecycleState.cancelled), isTrue);
    });
  });

  group('idempotency', () {
    test('primary key is device:local_uuid', () {
      final k = buildPrimaryIdempotencyKey(
        deviceUuid: 'dev-1',
        localCallUuid: 'uuid-abc',
      );
      expect(k, 'dev-1:uuid-abc');
    });

    test('reconciliation fingerprint stable within bucket', () {
      final t = DateTime.fromMillisecondsSinceEpoch(1700000005000, isUtc: true);
      final a = buildReconciliationFingerprint(
        normalizedPhone: phoneLookupKey('07701234567'),
        direction: 'inbound',
        startedAt: t,
        deviceUuid: 'dev-1',
      );
      final b = buildReconciliationFingerprint(
        normalizedPhone: phoneLookupKey('+964 770-123-4567'),
        direction: 'inbound',
        startedAt: t.add(const Duration(seconds: 2)),
        deviceUuid: 'dev-1',
      );
      expect(a, b);
    });

    test('two calls same bucket still have different primary keys', () {
      final a = buildPrimaryIdempotencyKey(
        deviceUuid: 'd',
        localCallUuid: 'u1',
      );
      final b = buildPrimaryIdempotencyKey(
        deviceUuid: 'd',
        localCallUuid: 'u2',
      );
      expect(a, isNot(b));
    });
  });

  group('UTC', () {
    test('toUtcIsoZ ends with Z', () {
      final s = toUtcIsoZ(DateTime.utc(2026, 8, 5, 10, 30));
      expect(s, '2026-08-05T10:30:00Z');
    });

    test('parseUtcIso normalizes Z', () {
      final dt = parseUtcIso('2026-08-05T10:30:00Z');
      expect(dt!.isUtc, isTrue);
      expect(dt.hour, 10);
    });

    test('ordering prefers server_received_at', () {
      final deviceA = DateTime.utc(2026, 8, 5, 10, 0, 0);
      final deviceB = DateTime.utc(2026, 8, 5, 10, 0, 1);
      final serverA = DateTime.utc(2026, 8, 5, 10, 0, 5);
      final serverB = DateTime.utc(2026, 8, 5, 10, 0, 2);
      // Without server: A < B by device
      expect(
        compareEventsByAuthority(
          aDeviceUtc: deviceA,
          bDeviceUtc: deviceB,
        ),
        lessThan(0),
      );
      // With server: B arrives first despite later device clock
      expect(
        compareEventsByAuthority(
          aServerReceived: serverA,
          aDeviceUtc: deviceA,
          bServerReceived: serverB,
          bDeviceUtc: deviceB,
        ),
        greaterThan(0),
      );
    });

    test('timezone shift does not change UTC instant', () {
      final localLike = DateTime.parse('2026-08-05T13:30:00+03:00');
      expect(toUtcIsoZ(localLike), '2026-08-05T10:30:00Z');
    });
  });

  group('phone formats', () {
    test('iraqi variants normalize', () {
      expect(phoneLookupKey('07701234567'), '7701234567');
      expect(phoneLookupKey('9647701234567'), '7701234567');
      expect(phoneLookupKey('+9647701234567'), '7701234567');
      expect(phoneLookupKey('0770-123-4567'), '7701234567');
      expect(phoneLookupKey('0770 123 4567'), '7701234567');
    });
  });
}
