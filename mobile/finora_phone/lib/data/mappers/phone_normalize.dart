String normalizePhone(String? raw) {
  if (raw == null) return '';
  final digits = raw.replaceAll(RegExp(r'[^0-9]'), '');
  return digits;
}

String phoneLookupKey(String? raw) {
  final d = normalizePhone(raw);
  if (d.length >= 10) return d.substring(d.length - 10);
  return d;
}
