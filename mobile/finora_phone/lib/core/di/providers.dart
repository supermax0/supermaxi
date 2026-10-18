import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../api/api_client.dart';
import '../storage/token_storage.dart';
import '../sync/sync_engine.dart';
import '../logging/phone_logger.dart';
import '../../data/local/local_database.dart';
import '../../data/repositories/repositories.dart';
import '../../domain/ports/ports.dart';
import '../../platform/call_event_channel.dart';

final tokenStorageProvider = Provider((ref) => TokenStorage());

final phoneLoggerProvider = Provider((ref) {
  return PhoneLogger(storage: ref.watch(tokenStorageProvider));
});

final crashReporterProvider = Provider<CrashReporter>((ref) {
  return LocalCrashReporter(storage: ref.watch(tokenStorageProvider));
});

final apiClientProvider = Provider((ref) {
  return ApiClient(tokenStorage: ref.watch(tokenStorageProvider));
});

final localDatabaseProvider = Provider((ref) => LocalDatabase());

final syncEngineProvider = Provider((ref) {
  return SyncEngine(
    db: ref.watch(localDatabaseProvider),
    api: ref.watch(apiClientProvider),
    storage: ref.watch(tokenStorageProvider),
    logger: ref.watch(phoneLoggerProvider),
  );
});

final customerRepositoryProvider = Provider<CustomerRepository>((ref) {
  return CustomerRepositoryImpl(
    db: ref.watch(localDatabaseProvider),
    api: ref.watch(apiClientProvider),
    sync: ref.watch(syncEngineProvider),
    logger: ref.watch(phoneLoggerProvider),
  );
});

final callLogRepositoryProvider = Provider<CallLogRepository>((ref) {
  return CallLogRepositoryImpl(
    db: ref.watch(localDatabaseProvider),
    sync: ref.watch(syncEngineProvider),
    api: ref.watch(apiClientProvider),
  );
});

final taskRepositoryProvider = Provider<TaskRepository>((ref) {
  return TaskRepositoryImpl(
    db: ref.watch(localDatabaseProvider),
    sync: ref.watch(syncEngineProvider),
    api: ref.watch(apiClientProvider),
  );
});

final noteRepositoryProvider = Provider<NoteRepository>((ref) {
  return NoteRepositoryImpl(
    db: ref.watch(localDatabaseProvider),
    sync: ref.watch(syncEngineProvider),
  );
});

final orderRepositoryProvider = Provider<OrderRepository>((ref) {
  return OrderRepositoryImpl(
    db: ref.watch(localDatabaseProvider),
    sync: ref.watch(syncEngineProvider),
    api: ref.watch(apiClientProvider),
  );
});

final callEventSourceProvider = Provider<CallEventSource>((ref) {
  return AndroidTelephonyOverlaySource();
});

final overlayChannelProvider = Provider((ref) => OverlayChannel());
final permissionsChannelProvider = Provider((ref) => PermissionsChannel());

final recordingRepositoryProvider = Provider<RecordingRepository>((ref) {
  return RecordingRepositoryImpl(
    db: ref.watch(localDatabaseProvider),
    sync: ref.watch(syncEngineProvider),
    channel: ref.watch(permissionsChannelProvider),
    logger: ref.watch(phoneLoggerProvider),
  );
});
final callAiAssistantProvider =
    Provider<CallAiAssistant>((ref) => CallAiAssistantStub());
final queueRepositoryProvider =
    Provider<QueueRepository>((ref) => QueueRepositoryStub());
final reportsRepositoryProvider =
    Provider<ReportsRepository>((ref) => ReportsRepositoryStub());
