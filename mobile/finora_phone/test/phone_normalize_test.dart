import 'package:finora_phone/data/mappers/phone_normalize.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  group('phone normalize', () {
    test('strips non-digits', () {
      expect(normalizePhone('+964 770-123-4567'), '9647701234567');
    });

    test('lookup key uses last 10', () {
      expect(phoneLookupKey('07701234567'), '7701234567');
      expect(phoneLookupKey('9647701234567'), '7701234567');
    });
  });
}
