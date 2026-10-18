import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api/api_client.dart';
import '../../../core/errors/api_exception.dart';

class RewardsSummary {
  RewardsSummary({
    required this.balance,
    required this.pendingPoints,
    required this.lifetimeEarned,
    required this.lifetimeRedeemed,
    required this.tierKey,
    required this.tierName,
  });

  factory RewardsSummary.fromJson(Map<String, dynamic> json) {
    final tier = (json['tier'] as Map<String, dynamic>?) ?? {};
    return RewardsSummary(
      balance: (json['balance'] as int?) ?? 0,
      pendingPoints: (json['pending_points'] as int?) ?? 0,
      lifetimeEarned: (json['lifetime_earned'] as int?) ?? 0,
      lifetimeRedeemed: (json['lifetime_redeemed'] as int?) ?? 0,
      tierKey: (tier['key'] as String?) ?? 'silver',
      tierName: (tier['name'] as String?) ?? 'Silver',
    );
  }

  final int balance;
  final int pendingPoints;
  final int lifetimeEarned;
  final int lifetimeRedeemed;
  final String tierKey;
  final String tierName;
}

class RewardTxn {
  RewardTxn({
    required this.id,
    required this.type,
    required this.points,
    required this.direction,
    required this.status,
    this.description = '',
    this.createdAt,
  });

  factory RewardTxn.fromJson(Map<String, dynamic> json) {
    return RewardTxn(
      id: json['id'] as int,
      type: (json['type'] as String?) ?? '',
      points: (json['points'] as int?) ?? 0,
      direction: (json['direction'] as String?) ?? '',
      status: (json['status'] as String?) ?? '',
      description: (json['description'] as String?) ?? '',
      createdAt: json['created_at'] as String?,
    );
  }

  final int id;
  final String type;
  final int points;
  final String direction;
  final String status;
  final String description;
  final String? createdAt;
}

class RewardsState {
  RewardsState({
    this.summary,
    this.history = const [],
    this.redemptions = const [],
    this.campaigns = const [],
    this.loading = false,
    this.error,
  });

  final RewardsSummary? summary;
  final List<RewardTxn> history;
  final List<Map<String, dynamic>> redemptions;
  final List<Map<String, dynamic>> campaigns;
  final bool loading;
  final String? error;

  RewardsState copyWith({
    RewardsSummary? summary,
    List<RewardTxn>? history,
    List<Map<String, dynamic>>? redemptions,
    List<Map<String, dynamic>>? campaigns,
    bool? loading,
    String? error,
    bool clearError = false,
  }) {
    return RewardsState(
      summary: summary ?? this.summary,
      history: history ?? this.history,
      redemptions: redemptions ?? this.redemptions,
      campaigns: campaigns ?? this.campaigns,
      loading: loading ?? this.loading,
      error: clearError ? null : (error ?? this.error),
    );
  }
}

final rewardsControllerProvider =
    StateNotifierProvider<RewardsController, RewardsState>((ref) {
  return RewardsController(ref.watch(apiClientProvider));
});

class RewardsController extends StateNotifier<RewardsState> {
  RewardsController(this._api) : super(RewardsState());

  final ApiClient _api;

  Future<void> refresh() async {
    state = state.copyWith(loading: true, clearError: true);
    try {
      final raw = await _api.get('/api/mobile/v1/rewards');
      final summary = RewardsSummary.fromJson(
        (raw['rewards'] as Map<String, dynamic>?) ?? {},
      );
      final campaigns = ((raw['campaigns'] as List<dynamic>?) ?? [])
          .whereType<Map<String, dynamic>>()
          .toList();
      final histRaw = await _api.get('/api/mobile/v1/rewards/history');
      final history = ((histRaw['items'] as List<dynamic>?) ?? [])
          .whereType<Map<String, dynamic>>()
          .map(RewardTxn.fromJson)
          .toList();
      final redRaw =
          await _api.get('/api/mobile/v1/rewards/available-redemptions');
      final redemptions = ((redRaw['items'] as List<dynamic>?) ?? [])
          .whereType<Map<String, dynamic>>()
          .toList();
      state = state.copyWith(
        summary: summary,
        history: history,
        redemptions: redemptions,
        campaigns: campaigns,
        loading: false,
      );
    } on ApiException catch (e) {
      state = state.copyWith(loading: false, error: e.message);
    }
  }

  Future<void> redeemToCart(int points) async {
    await _api.post('/api/mobile/v1/rewards/redeem', data: {'points': points});
    await refresh();
  }
}
