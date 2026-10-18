class CustomerEntity {
  const CustomerEntity({
    required this.id,
    required this.name,
    required this.phone,
    this.phone2 = '',
    this.city = '',
    this.address = '',
    this.notes = '',
    this.balance,
    this.totalPurchases,
    this.lastOrder,
    this.openOrdersCount = 0,
    this.deliveryStatus,
    this.lastNote,
    this.blacklisted = false,
    this.vip = false,
  });

  final int? id;
  final String name;
  final String phone;
  final String phone2;
  final String city;
  final String address;
  final String notes;
  final double? balance;
  final double? totalPurchases;
  final Map<String, dynamic>? lastOrder;
  final int openOrdersCount;
  final String? deliveryStatus;
  final String? lastNote;
  final bool blacklisted;
  final bool vip;

  factory CustomerEntity.fromJson(Map<String, dynamic> json) {
    return CustomerEntity(
      id: json['id'] is int ? json['id'] as int : int.tryParse('${json['id']}'),
      name: (json['name'] ?? '') as String,
      phone: (json['phone'] ?? '') as String,
      phone2: (json['phone2'] ?? '') as String,
      city: (json['city'] ?? '') as String,
      address: (json['address'] ?? '') as String,
      notes: (json['notes'] ?? '') as String,
      balance: (json['balance'] as num?)?.toDouble(),
      totalPurchases: (json['total_purchases'] as num?)?.toDouble(),
      lastOrder: json['last_order'] is Map
          ? Map<String, dynamic>.from(json['last_order'] as Map)
          : null,
      openOrdersCount: (json['open_orders_count'] as num?)?.toInt() ?? 0,
      deliveryStatus: json['delivery_status'] as String?,
      lastNote: json['last_note'] as String?,
      blacklisted: json['blacklisted'] == true,
      vip: json['vip'] == true,
    );
  }

  Map<String, dynamic> toJson() => {
        'id': id,
        'name': name,
        'phone': phone,
        'phone2': phone2,
        'city': city,
        'address': address,
        'notes': notes,
        'balance': balance,
        'total_purchases': totalPurchases,
        'last_order': lastOrder,
        'open_orders_count': openOrdersCount,
        'delivery_status': deliveryStatus,
        'last_note': lastNote,
        'blacklisted': blacklisted,
        'vip': vip,
      };

  CustomerEntity copyWith({
    int? id,
    String? name,
    String? phone,
    String? phone2,
    String? city,
    String? address,
    String? notes,
    double? balance,
    double? totalPurchases,
    Map<String, dynamic>? lastOrder,
    int? openOrdersCount,
    String? deliveryStatus,
    String? lastNote,
    bool? blacklisted,
    bool? vip,
  }) {
    return CustomerEntity(
      id: id ?? this.id,
      name: name ?? this.name,
      phone: phone ?? this.phone,
      phone2: phone2 ?? this.phone2,
      city: city ?? this.city,
      address: address ?? this.address,
      notes: notes ?? this.notes,
      balance: balance ?? this.balance,
      totalPurchases: totalPurchases ?? this.totalPurchases,
      lastOrder: lastOrder ?? this.lastOrder,
      openOrdersCount: openOrdersCount ?? this.openOrdersCount,
      deliveryStatus: deliveryStatus ?? this.deliveryStatus,
      lastNote: lastNote ?? this.lastNote,
      blacklisted: blacklisted ?? this.blacklisted,
      vip: vip ?? this.vip,
    );
  }
}

enum CallDirection { inbound, outbound }

enum CallStatus {
  detected,
  ringing,
  active,
  answered,
  missed,
  rejected,
  disconnected,
  ended,
  failed,
  synced,
}

class CallEvent {
  const CallEvent({
    required this.type,
    required this.number,
    required this.startedAt,
    this.callLogId,
    this.clientId,
    this.direction = 'inbound',
    this.simSlot,
    this.deviceId,
    this.idempotencyKey,
    this.durationSec,
  });

  final CallStatus type;
  final String number;
  final DateTime startedAt;
  final String? callLogId;
  final String? clientId;
  final String direction;
  final int? simSlot;
  final String? deviceId;
  final String? idempotencyKey;
  final int? durationSec;

  factory CallEvent.fromMap(Map<dynamic, dynamic> map) {
    final typeRaw = (map['type'] ?? 'ringing').toString().toLowerCase();
    final status = switch (typeRaw) {
      'detected' => CallStatus.detected,
      'active' || 'offhook' || 'answered' => CallStatus.answered,
      'missed' => CallStatus.missed,
      'rejected' => CallStatus.rejected,
      'disconnected' || 'idle' => CallStatus.disconnected,
      'ended' => CallStatus.ended,
      'failed' => CallStatus.failed,
      _ => CallStatus.ringing,
    };
    final started = DateTime.tryParse('${map['startedAt'] ?? ''}') ??
        DateTime.now();
    return CallEvent(
      type: status,
      number: (map['number'] ?? '').toString(),
      startedAt: started,
      callLogId: map['callLogId']?.toString(),
      clientId: map['clientId']?.toString(),
      direction: (map['direction'] ?? 'inbound').toString(),
      simSlot: map['simSlot'] is num ? (map['simSlot'] as num).toInt() : null,
      deviceId: map['deviceId']?.toString(),
      idempotencyKey: map['idempotencyKey']?.toString(),
      durationSec:
          map['durationSec'] is num ? (map['durationSec'] as num).toInt() : null,
    );
  }
}

class CallLogEntity {
  const CallLogEntity({
    required this.clientId,
    required this.phone,
    required this.direction,
    required this.status,
    required this.startedAt,
    this.endedAt,
    this.durationSec,
    this.customerId,
    this.customerName,
    this.syncStatus = 'pending',
    this.serverId,
    this.note,
    this.idempotencyKey,
    this.localCallUuid,
    this.reconciliationFingerprint,
    this.deviceId,
    this.simSlot,
    this.detectedAt,
    this.ringingAt,
    this.dialingAt,
    this.answeredAt,
    this.cancelledAt,
    this.failedAt,
    this.syncedAt,
    this.outcome,
    this.outcomeNote,
    this.followUpRequired = false,
    this.followUpAt,
    this.outcomeClientId,
    this.unclassified = false,
  });

  final String clientId;
  final String phone;
  final String direction;
  /// call_status only (never "synced")
  final String status;
  final DateTime startedAt;
  final DateTime? endedAt;
  final int? durationSec;
  final int? customerId;
  final String? customerName;
  final String syncStatus;
  final int? serverId;
  final String? note;
  final String? idempotencyKey;
  final String? localCallUuid;
  final String? reconciliationFingerprint;
  final String? deviceId;
  final int? simSlot;
  final DateTime? detectedAt;
  final DateTime? ringingAt;
  final DateTime? dialingAt;
  final DateTime? answeredAt;
  final DateTime? cancelledAt;
  final DateTime? failedAt;
  final DateTime? syncedAt;
  final String? outcome;
  final String? outcomeNote;
  final bool followUpRequired;
  final DateTime? followUpAt;
  final String? outcomeClientId;
  final bool unclassified;
}

class TaskEntity {
  const TaskEntity({
    required this.clientId,
    required this.title,
    required this.phone,
    this.id,
    this.customerId,
    this.dueAt,
    this.status = 'open',
    this.source = 'missed_call',
    this.syncStatus = 'pending',
    this.taskType,
    this.priority = 'normal',
    this.reason,
    this.attemptCount = 1,
    this.callId,
  });

  final int? id;
  final String clientId;
  final String title;
  final String phone;
  final int? customerId;
  final DateTime? dueAt;
  final String status;
  final String source;
  final String syncStatus;
  final String? taskType;
  final String priority;
  final String? reason;
  final int attemptCount;
  final int? callId;
}

class TimelineItem {
  const TimelineItem({
    required this.id,
    required this.type,
    required this.occurredAt,
    required this.title,
    required this.summary,
    this.status,
    this.referenceType,
    this.referenceId,
    this.employeeName,
    this.metadata = const {},
  });

  final String id;
  final String type;
  final DateTime occurredAt;
  final String title;
  final String summary;
  final String? status;
  final String? referenceType;
  final int? referenceId;
  final String? employeeName;
  final Map<String, dynamic> metadata;

  factory TimelineItem.fromJson(Map<String, dynamic> json) {
    final emp = json['employee'];
    return TimelineItem(
      id: (json['id'] ?? '').toString(),
      type: (json['type'] ?? '').toString(),
      occurredAt: DateTime.tryParse('${json['occurred_at'] ?? ''}')?.toLocal() ??
          DateTime.now(),
      title: (json['title'] ?? '').toString(),
      summary: (json['summary'] ?? '').toString(),
      status: json['status']?.toString(),
      referenceType: json['reference_type']?.toString(),
      referenceId: (json['reference_id'] as num?)?.toInt(),
      employeeName: emp is Map ? emp['name']?.toString() : null,
      metadata: json['metadata'] is Map
          ? Map<String, dynamic>.from(json['metadata'] as Map)
          : const {},
    );
  }
}

class NoteEntity {
  const NoteEntity({
    required this.clientId,
    required this.body,
    this.callClientId,
    this.customerId,
    this.syncStatus = 'pending',
  });

  final String clientId;
  final String body;
  final String? callClientId;
  final int? customerId;
  final String syncStatus;
}

class EmployeeSession {
  const EmployeeSession({
    required this.id,
    required this.name,
    required this.username,
    required this.role,
    this.branchId,
  });

  final int id;
  final String name;
  final String username;
  final String role;
  final int? branchId;

  factory EmployeeSession.fromJson(Map<String, dynamic> json) {
    return EmployeeSession(
      id: (json['id'] as num).toInt(),
      name: (json['name'] ?? '') as String,
      username: (json['username'] ?? '') as String,
      role: (json['role'] ?? '') as String,
      branchId: (json['branch_id'] as num?)?.toInt(),
    );
  }

  Map<String, dynamic> toJson() => {
        'id': id,
        'name': name,
        'username': username,
        'role': role,
        'branch_id': branchId,
      };
}
