/// UTC helpers for Finora Phone sync.
/// Storage and API payloads use ISO-8601 with Z (UTC).
library;

String toUtcIsoZ(DateTime dt) {
  final u = dt.toUtc();
  final y = u.year.toString().padLeft(4, '0');
  final m = u.month.toString().padLeft(2, '0');
  final d = u.day.toString().padLeft(2, '0');
  final h = u.hour.toString().padLeft(2, '0');
  final min = u.minute.toString().padLeft(2, '0');
  final s = u.second.toString().padLeft(2, '0');
  return '$y-$m-$d${'T'}$h:$min:${s}Z';
}

DateTime? parseUtcIso(String? raw) {
  if (raw == null || raw.trim().isEmpty) return null;
  var t = raw.trim();
  if (t.endsWith('Z')) {
    t = '${t.substring(0, t.length - 1)}+00:00';
  }
  final dt = DateTime.tryParse(t);
  return dt?.toUtc();
}

/// Critical event ordering: prefer server_received_at when present,
/// else device UTC timestamp. Never rely on local wall-clock alone.
int compareEventsByAuthority({
  DateTime? aServerReceived,
  required DateTime aDeviceUtc,
  DateTime? bServerReceived,
  required DateTime bDeviceUtc,
}) {
  final a = aServerReceived ?? aDeviceUtc.toUtc();
  final b = bServerReceived ?? bDeviceUtc.toUtc();
  return a.compareTo(b);
}
