import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api/api_client.dart';
import '../../../core/config/app_config.dart';
import '../../../core/errors/api_exception.dart';
import '../../notifications/data/notifications_controller.dart';
import '../../store/data/store_controller.dart';

class FeedVideo {
  FeedVideo({
    required this.id,
    required this.title,
    required this.description,
    required this.playbackUrl,
    this.thumbnailUrl,
    this.likesCount = 0,
    this.viewsCount = 0,
    this.savesCount = 0,
    this.sharesCount = 0,
    this.commentsCount = 0,
    this.likedByMe = false,
    this.savedByMe = false,
    this.allowSharing = true,
    this.allowSaving = true,
    this.allowComments = true,
    this.products = const [],
  });

  factory FeedVideo.fromJson(Map<String, dynamic> json) {
    String? url = json['playback_url'] as String? ??
        json['hls_master_url'] as String? ??
        json['original_asset_url'] as String?;
    if (url != null && url.startsWith('/')) {
      url = '${AppConfig.apiBaseUrl}$url';
    }
    String? thumb = json['thumbnail_url'] as String?;
    if (thumb != null && thumb.startsWith('/')) {
      thumb = '${AppConfig.apiBaseUrl}$thumb';
    }
    final products = ((json['products'] as List<dynamic>?) ?? [])
        .whereType<Map<String, dynamic>>()
        .map(StoreProduct.fromJson)
        .toList();
    return FeedVideo(
      id: json['id'] as int,
      title: (json['title'] as String?) ?? '',
      description: (json['description'] as String?) ?? '',
      playbackUrl: url ?? '',
      thumbnailUrl: thumb,
      likesCount: (json['likes_count'] as int?) ?? 0,
      viewsCount: (json['views_count'] as int?) ?? 0,
      savesCount: (json['saves_count'] as int?) ?? 0,
      sharesCount: (json['shares_count'] as int?) ?? 0,
      commentsCount: (json['comments_count'] as int?) ?? 0,
      likedByMe: json['liked_by_me'] == true,
      savedByMe: json['saved_by_me'] == true,
      allowSharing: json['allow_sharing'] != false,
      allowSaving: json['allow_saving'] != false,
      allowComments: json['allow_comments'] != false,
      products: products,
    );
  }

  final int id;
  final String title;
  final String description;
  final String playbackUrl;
  final String? thumbnailUrl;
  final int likesCount;
  final int viewsCount;
  final int savesCount;
  final int sharesCount;
  final int commentsCount;
  final bool likedByMe;
  final bool savedByMe;
  final bool allowSharing;
  final bool allowSaving;
  final bool allowComments;
  final List<StoreProduct> products;

  StoreProduct? get primaryProduct =>
      products.isEmpty ? null : products.first;

  FeedVideo copyWith({
    int? likesCount,
    int? viewsCount,
    int? savesCount,
    int? sharesCount,
    int? commentsCount,
    bool? likedByMe,
    bool? savedByMe,
    List<StoreProduct>? products,
  }) {
    return FeedVideo(
      id: id,
      title: title,
      description: description,
      playbackUrl: playbackUrl,
      thumbnailUrl: thumbnailUrl,
      likesCount: likesCount ?? this.likesCount,
      viewsCount: viewsCount ?? this.viewsCount,
      savesCount: savesCount ?? this.savesCount,
      sharesCount: sharesCount ?? this.sharesCount,
      commentsCount: commentsCount ?? this.commentsCount,
      likedByMe: likedByMe ?? this.likedByMe,
      savedByMe: savedByMe ?? this.savedByMe,
      allowSharing: allowSharing,
      allowSaving: allowSaving,
      allowComments: allowComments,
      products: products ?? this.products,
    );
  }
}

class FeedState {
  const FeedState({
    this.items = const [],
    this.nextCursor,
    this.isLoading = false,
    this.isLoadingMore = false,
    this.error,
  });

  final List<FeedVideo> items;
  final String? nextCursor;
  final bool isLoading;
  final bool isLoadingMore;
  final String? error;

  FeedState copyWith({
    List<FeedVideo>? items,
    String? nextCursor,
    bool? isLoading,
    bool? isLoadingMore,
    String? error,
    bool clearError = false,
    bool clearCursor = false,
  }) {
    return FeedState(
      items: items ?? this.items,
      nextCursor: clearCursor ? null : (nextCursor ?? this.nextCursor),
      isLoading: isLoading ?? this.isLoading,
      isLoadingMore: isLoadingMore ?? this.isLoadingMore,
      error: clearError ? null : (error ?? this.error),
    );
  }
}

class FeedController extends StateNotifier<FeedState> {
  FeedController(this._api, this._ref) : super(const FeedState());

  final ApiClient _api;
  final Ref _ref;

  AnalyticsTracker get _analytics => _ref.read(analyticsTrackerProvider);

  Future<void> refresh() async {
    state =
        state.copyWith(isLoading: true, clearError: true, clearCursor: true);
    try {
      final data = await _api.get('/api/mobile/v1/feed?limit=6');
      final raw = (data['items'] as List<dynamic>? ?? [])
          .whereType<Map<String, dynamic>>()
          .map(FeedVideo.fromJson)
          .toList();
      state = state.copyWith(
        items: raw,
        nextCursor: data['next_cursor'] as String?,
        isLoading: false,
      );
    } on ApiException catch (e) {
      state = state.copyWith(isLoading: false, error: e.message);
    }
  }

  Future<void> loadMore() async {
    final cursor = state.nextCursor;
    if (cursor == null || state.isLoadingMore) return;
    state = state.copyWith(isLoadingMore: true);
    try {
      final data = await _api.get('/api/mobile/v1/feed?limit=6&cursor=$cursor');
      final raw = (data['items'] as List<dynamic>? ?? [])
          .whereType<Map<String, dynamic>>()
          .map(FeedVideo.fromJson)
          .toList();
      state = state.copyWith(
        items: [...state.items, ...raw],
        nextCursor: data['next_cursor'] as String?,
        isLoadingMore: false,
      );
    } on ApiException catch (e) {
      state = state.copyWith(isLoadingMore: false, error: e.message);
    }
  }

  Future<void> recordView(int videoId) async {
    try {
      await _api.post('/api/mobile/v1/videos/$videoId/view',
          data: {'watch_ms': 1000});
      _analytics.track('video_view', properties: {'video_id': videoId});
    } catch (_) {}
  }

  Future<void> toggleLike(int index) async {
    if (index < 0 || index >= state.items.length) return;
    final item = state.items[index];
    try {
      if (item.likedByMe) {
        final data = await _api.deleteLike(item.id);
        _patch(
            index,
            item.copyWith(
              likedByMe: false,
              likesCount: data['likes_count'] as int? ?? item.likesCount,
            ));
      } else {
        final data = await _api.post('/api/mobile/v1/videos/${item.id}/like');
        _patch(
            index,
            item.copyWith(
              likedByMe: true,
              likesCount: data['likes_count'] as int? ?? item.likesCount + 1,
            ));
        _analytics.track('video_like', properties: {'video_id': item.id});
      }
    } catch (_) {}
  }

  Future<void> toggleSave(int index) async {
    if (index < 0 || index >= state.items.length) return;
    final item = state.items[index];
    if (!item.allowSaving) return;
    try {
      if (item.savedByMe) {
        final data = await _api.deleteSave(item.id);
        _patch(
            index,
            item.copyWith(
              savedByMe: false,
              savesCount: data['saves_count'] as int? ?? item.savesCount,
            ));
      } else {
        final data = await _api.post('/api/mobile/v1/videos/${item.id}/save');
        _patch(
            index,
            item.copyWith(
              savedByMe: true,
              savesCount: data['saves_count'] as int? ?? item.savesCount + 1,
            ));
        _analytics.track('video_save', properties: {'video_id': item.id});
      }
    } catch (_) {}
  }

  Future<void> share(int index) async {
    if (index < 0 || index >= state.items.length) return;
    final item = state.items[index];
    if (!item.allowSharing) return;
    try {
      final data = await _api.post(
        '/api/mobile/v1/videos/${item.id}/share',
        data: {'channel': 'app'},
      );
      _patch(
        index,
        item.copyWith(
            sharesCount: data['shares_count'] as int? ?? item.sharesCount + 1),
      );
      _analytics.track('video_share', properties: {'video_id': item.id});
    } catch (_) {}
  }

  void _patch(int index, FeedVideo video) {
    final list = [...state.items];
    list[index] = video;
    state = state.copyWith(items: list);
  }
}

final feedControllerProvider =
    StateNotifierProvider<FeedController, FeedState>((ref) {
  return FeedController(ref.watch(apiClientProvider), ref);
});
