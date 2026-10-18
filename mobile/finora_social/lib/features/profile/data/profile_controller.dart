import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api/api_client.dart';
import '../../../core/errors/api_exception.dart';
import '../../authentication/data/auth_controller.dart';

class ProfileAddress {
  ProfileAddress({
    required this.id,
    required this.label,
    required this.fullName,
    required this.phone,
    required this.city,
    required this.address,
    this.notes = '',
    this.isDefault = false,
  });

  factory ProfileAddress.fromJson(Map<String, dynamic> json) {
    return ProfileAddress(
      id: json['id'] as int,
      label: (json['label'] as String?) ?? 'المنزل',
      fullName: (json['full_name'] as String?) ?? '',
      phone: (json['phone'] as String?) ?? '',
      city: (json['city'] as String?) ?? '',
      address: (json['address'] as String?) ?? '',
      notes: (json['notes'] as String?) ?? '',
      isDefault: json['is_default'] == true,
    );
  }

  final int id;
  final String label;
  final String fullName;
  final String phone;
  final String city;
  final String address;
  final String notes;
  final bool isDefault;
}

class ProfileState {
  const ProfileState({
    this.name = '',
    this.email = '',
    this.phone = '',
    this.city = '',
    this.address = '',
    this.rewardsBalance = 0,
    this.rewardsTier = '',
    this.ordersCount = 0,
    this.totalSpent = 0,
    this.favoritesCount = 0,
    this.videoViews = 0,
    this.profileCompletion = 0,
    this.memberSince,
    this.preferredCategories = const [],
    this.addresses = const [],
    this.isLoading = false,
    this.error,
  });

  final String name;
  final String email;
  final String phone;
  final String city;
  final String address;
  final int rewardsBalance;
  final String rewardsTier;
  final int ordersCount;
  final int totalSpent;
  final int favoritesCount;
  final int videoViews;
  final int profileCompletion;
  final DateTime? memberSince;
  final List<String> preferredCategories;
  final List<ProfileAddress> addresses;
  final bool isLoading;
  final String? error;

  ProfileState copyWith({
    String? name,
    String? email,
    String? phone,
    String? city,
    String? address,
    int? rewardsBalance,
    String? rewardsTier,
    int? ordersCount,
    int? totalSpent,
    int? favoritesCount,
    int? videoViews,
    int? profileCompletion,
    DateTime? memberSince,
    List<String>? preferredCategories,
    List<ProfileAddress>? addresses,
    bool? isLoading,
    String? error,
    bool clearError = false,
  }) {
    return ProfileState(
      name: name ?? this.name,
      email: email ?? this.email,
      phone: phone ?? this.phone,
      city: city ?? this.city,
      address: address ?? this.address,
      rewardsBalance: rewardsBalance ?? this.rewardsBalance,
      rewardsTier: rewardsTier ?? this.rewardsTier,
      ordersCount: ordersCount ?? this.ordersCount,
      totalSpent: totalSpent ?? this.totalSpent,
      favoritesCount: favoritesCount ?? this.favoritesCount,
      videoViews: videoViews ?? this.videoViews,
      profileCompletion: profileCompletion ?? this.profileCompletion,
      memberSince: memberSince ?? this.memberSince,
      preferredCategories: preferredCategories ?? this.preferredCategories,
      addresses: addresses ?? this.addresses,
      isLoading: isLoading ?? this.isLoading,
      error: clearError ? null : (error ?? this.error),
    );
  }
}

class ProfileController extends StateNotifier<ProfileState> {
  ProfileController(this._api, this._ref) : super(const ProfileState());

  final ApiClient _api;
  final Ref _ref;

  Future<void> load() async {
    state = state.copyWith(isLoading: true, clearError: true);
    try {
      final data = await _api.get('/api/mobile/v1/profile');
      final user = (data['user'] as Map<String, dynamic>?) ?? {};
      final customer = (data['customer'] as Map<String, dynamic>?) ?? {};
      final rewards = (data['rewards'] as Map<String, dynamic>?) ?? {};
      final tier = (rewards['tier'] as Map<String, dynamic>?) ?? {};
      final insights = (data['insights'] as Map<String, dynamic>?) ?? {};
      final addrData = await _api.get('/api/mobile/v1/profile/addresses');
      final addresses = ((addrData['items'] as List<dynamic>?) ?? [])
          .whereType<Map<String, dynamic>>()
          .map(ProfileAddress.fromJson)
          .toList();
      state = state.copyWith(
        name: (user['name'] as String?) ?? '',
        email: (user['email'] as String?) ?? '',
        phone: (user['phone'] as String?) ?? '',
        city: (customer['city'] as String?) ?? '',
        address: (customer['address'] as String?) ?? '',
        rewardsBalance: (rewards['balance'] as int?) ?? 0,
        rewardsTier: (tier['name'] as String?) ?? '',
        ordersCount: (insights['orders_count'] as int?) ?? 0,
        totalSpent: (insights['total_spent'] as int?) ?? 0,
        favoritesCount: (insights['favorites_count'] as int?) ?? 0,
        videoViews: (insights['video_views'] as int?) ?? 0,
        profileCompletion: (insights['profile_completion'] as int?) ?? 0,
        memberSince:
            DateTime.tryParse((insights['member_since'] as String?) ?? ''),
        preferredCategories:
            ((insights['preferred_categories'] as List<dynamic>?) ?? [])
                .map((item) => item.toString())
                .where((item) => item.isNotEmpty)
                .toList(),
        addresses: addresses,
        isLoading: false,
      );
      final mobileUser = MobileUser.fromJson(user);
      _ref.read(authControllerProvider.notifier).applyUser(mobileUser);
    } on ApiException catch (e) {
      state = state.copyWith(isLoading: false, error: e.message);
    }
  }

  Future<bool> saveProfile({
    required String name,
    required String email,
    required String city,
    required String address,
  }) async {
    state = state.copyWith(isLoading: true, clearError: true);
    try {
      await _api.patch(
        '/api/mobile/v1/profile',
        data: {
          'name': name,
          'email': email,
          'city': city,
          'address': address,
        },
      );
      await load();
      return true;
    } on ApiException catch (e) {
      state = state.copyWith(isLoading: false, error: e.message);
      return false;
    }
  }

  Future<bool> addAddress(Map<String, dynamic> payload) async {
    try {
      await _api.post('/api/mobile/v1/profile/addresses', data: payload);
      await load();
      return true;
    } on ApiException catch (e) {
      state = state.copyWith(error: e.message);
      return false;
    }
  }

  Future<bool> deleteAddress(int id) async {
    try {
      await _api.delete('/api/mobile/v1/profile/addresses/$id');
      await load();
      return true;
    } on ApiException catch (e) {
      state = state.copyWith(error: e.message);
      return false;
    }
  }

  Future<bool> deleteAccount({String reason = ''}) async {
    try {
      await _api.post(
        '/api/mobile/v1/profile/delete-account',
        data: {'reason': reason},
      );
      await _ref.read(authControllerProvider.notifier).logout();
      return true;
    } on ApiException catch (e) {
      state = state.copyWith(error: e.message);
      return false;
    }
  }
}

final profileControllerProvider =
    StateNotifierProvider<ProfileController, ProfileState>((ref) {
  return ProfileController(ref.watch(apiClientProvider), ref);
});
