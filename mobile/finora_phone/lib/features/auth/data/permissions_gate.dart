import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/di/providers.dart';

class PermissionsGateState {
  const PermissionsGateState({this.ready = false, this.done = false});

  final bool ready;
  final bool done;

  PermissionsGateState copyWith({bool? ready, bool? done}) {
    return PermissionsGateState(
      ready: ready ?? this.ready,
      done: done ?? this.done,
    );
  }
}

final permissionsGateProvider =
    StateNotifierProvider<PermissionsGateController, PermissionsGateState>(
  (ref) => PermissionsGateController(ref),
);

class PermissionsGateController extends StateNotifier<PermissionsGateState> {
  PermissionsGateController(this._ref) : super(const PermissionsGateState()) {
    refresh();
  }

  final Ref _ref;

  Future<void> refresh() async {
    final done = await _ref.read(tokenStorageProvider).isPermissionsDone();
    state = PermissionsGateState(ready: true, done: done);
  }

  Future<void> markDone() async {
    await _ref.read(tokenStorageProvider).setPermissionsDone(true);
    state = const PermissionsGateState(ready: true, done: true);
  }
}
