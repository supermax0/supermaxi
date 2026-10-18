import 'package:flutter_test/flutter_test.dart';
import 'package:finora_phone/data/mappers/phone_normalize.dart';

void main() {
  test('normalizePhone strips non-digits', () {
    expect(normalizePhone('+964 770-123-4567'), '9647701234567');
  });

  test('phoneLookupKey uses last 10 digits', () {
    expect(phoneLookupKey('07701234567'), '7701234567');
    expect(phoneLookupKey('9647701234567'), '7701234567');
  });
}
