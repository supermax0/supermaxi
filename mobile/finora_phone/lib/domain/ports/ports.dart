import '../entities/entities.dart';

/// Ingress for call events. Phase 1: telephony overlay.
/// Phase 2: swap implementation to InCallService without rewriting UI/domain.
abstract class CallEventSource {
  Stream<CallEvent> get events;
  Future<void> start();
  Future<void> stop();
}

abstract class CustomerRepository {
  Future<CustomerEntity?> lookupByPhone(String phone, {bool allowNetwork = true});
  Future<CustomerEntity> createCustomer({
    required String name,
    required String phone,
    String? city,
    String? address,
    String? notes,
    required String clientId,
  });
  Future<CustomerEntity?> updateCustomer({
    required int customerId,
    String? name,
    String? city,
    String? address,
    String? notes,
    String? phone2,
  });
  Future<Map<String, dynamic>?> timeline(int customerId, {String? cursor});
  Future<List<CustomerEntity>> searchLocal(String query);
  Future<List<CustomerEntity>> searchRemote(String query);
  Future<Map<String, dynamic>?> advancedSearch(String query, {String? types});
}

abstract class CallLogRepository {
  Future<void> upsertLocal(CallLogEntity log);
  Future<List<CallLogEntity>> listLocal({int limit = 200});
  Future<void> recoverFromDeviceLogs(List<CallLogEntity> deviceLogs);
  Future<void> setOutcome({
    required String clientId,
    required int? serverId,
    required String outcome,
    String? outcomeNote,
    bool followUpRequired = false,
    DateTime? followUpAt,
    required String outcomeClientId,
    bool hasLinkedOrder = false,
  });
  Future<void> markUnclassified(String clientId);
  Future<List<CallLogEntity>> listUnclassified({int limit = 50});
}

abstract class TaskRepository {
  Future<void> createLocal(TaskEntity task);
  Future<List<TaskEntity>> listLocal({String? status, String? filter});
  Future<void> updateStatus(String clientId, String status);
  Future<void> snooze(String clientId, DateTime until);
  Future<void> pullRemote({String? filter});
}

abstract class NoteRepository {
  Future<void> createLocal(NoteEntity note);
}

abstract class OrderRepository {
  Future<Map<String, dynamic>> createConfirmedOrder({
    required int customerId,
    required List<Map<String, dynamic>> items,
    String? note,
    required String clientId,
  });
  Future<String> enqueueOrder({
    required int customerId,
    required List<Map<String, dynamic>> items,
    String? note,
    required String clientId,
  });
  Future<List<Map<String, dynamic>>> listDrafts();
  Future<bool> confirmDraft({required int draftId});
}

/// Finds the native dialer recording for a finished call and queues its upload.
abstract class RecordingRepository {
  Future<void> captureForCall({
    required String callClientId,
    required String phone,
    required DateTime startedAt,
    DateTime? endedAt,
  });
}

abstract class CallAiAssistant {
  Future<String?> summarizeCall(String callClientId);
}

abstract class QueueRepository {
  Future<List<Map<String, dynamic>>> listQueue();
}

abstract class ReportsRepository {
  Future<Map<String, dynamic>> dailySummary(DateTime day);
}
