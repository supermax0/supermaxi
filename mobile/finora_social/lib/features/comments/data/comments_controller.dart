import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api/api_client.dart';
import '../../../core/errors/api_exception.dart';

class CommentItem {
  CommentItem({
    required this.id,
    required this.body,
    required this.authorName,
    required this.likesCount,
    required this.likedByMe,
    required this.isCompanyReply,
    required this.isPinned,
    required this.createdAt,
    required this.repliesCount,
    this.replies = const [],
  });

  factory CommentItem.fromJson(Map<String, dynamic> json) {
    final repliesRaw = json['replies'] as List<dynamic>? ?? [];
    return CommentItem(
      id: json['id'] as int,
      body: (json['body'] as String?) ?? '',
      authorName: (json['author_name'] as String?) ?? 'مستخدم',
      likesCount: (json['likes_count'] as int?) ?? 0,
      likedByMe: json['liked_by_me'] == true,
      isCompanyReply: json['is_company_reply'] == true,
      isPinned: json['is_pinned'] == true,
      createdAt: DateTime.tryParse((json['created_at'] as String?) ?? ''),
      repliesCount: (json['replies_count'] as int?) ?? repliesRaw.length,
      replies: repliesRaw
          .whereType<Map<String, dynamic>>()
          .map(CommentItem.fromJson)
          .toList(),
    );
  }

  final int id;
  final String body;
  final String authorName;
  final int likesCount;
  final bool likedByMe;
  final bool isCompanyReply;
  final bool isPinned;
  final DateTime? createdAt;
  final int repliesCount;
  final List<CommentItem> replies;

  CommentItem copyWith({
    int? likesCount,
    bool? likedByMe,
    List<CommentItem>? replies,
    int? repliesCount,
  }) {
    return CommentItem(
      id: id,
      body: body,
      authorName: authorName,
      likesCount: likesCount ?? this.likesCount,
      likedByMe: likedByMe ?? this.likedByMe,
      isCompanyReply: isCompanyReply,
      isPinned: isPinned,
      createdAt: createdAt,
      repliesCount: repliesCount ?? this.repliesCount,
      replies: replies ?? this.replies,
    );
  }
}

class CommentsState {
  const CommentsState({
    this.items = const [],
    this.isLoading = false,
    this.isSending = false,
    this.error,
    this.replyToId,
    this.replyToName,
  });

  final List<CommentItem> items;
  final bool isLoading;
  final bool isSending;
  final String? error;
  final int? replyToId;
  final String? replyToName;

  CommentsState copyWith({
    List<CommentItem>? items,
    bool? isLoading,
    bool? isSending,
    String? error,
    int? replyToId,
    String? replyToName,
    bool clearError = false,
    bool clearReply = false,
  }) {
    return CommentsState(
      items: items ?? this.items,
      isLoading: isLoading ?? this.isLoading,
      isSending: isSending ?? this.isSending,
      error: clearError ? null : (error ?? this.error),
      replyToId: clearReply ? null : (replyToId ?? this.replyToId),
      replyToName: clearReply ? null : (replyToName ?? this.replyToName),
    );
  }
}

class CommentsController extends StateNotifier<CommentsState> {
  CommentsController(this._api, this.videoId) : super(const CommentsState());

  final ApiClient _api;
  final int videoId;

  Future<void> load() async {
    state = state.copyWith(isLoading: true, clearError: true);
    try {
      final data = await _api.get('/api/mobile/v1/videos/$videoId/comments');
      final items = (data['items'] as List<dynamic>? ?? [])
          .whereType<Map<String, dynamic>>()
          .map(CommentItem.fromJson)
          .toList();
      state = state.copyWith(items: items, isLoading: false);
    } on ApiException catch (e) {
      state = state.copyWith(isLoading: false, error: e.message);
    }
  }

  void setReplyTo(CommentItem? comment) {
    if (comment == null) {
      state = state.copyWith(clearReply: true);
      return;
    }
    state =
        state.copyWith(replyToId: comment.id, replyToName: comment.authorName);
  }

  Future<bool> send(String body) async {
    final text = body.trim();
    if (text.isEmpty) return false;
    state = state.copyWith(isSending: true, clearError: true);
    try {
      final replyToId = state.replyToId;
      final Map<String, dynamic> data;
      if (replyToId != null) {
        data = await _api.post(
          '/api/mobile/v1/comments/${state.replyToId}/replies',
          data: {'body': text},
        );
      } else {
        data = await _api.post(
          '/api/mobile/v1/videos/$videoId/comments',
          data: {'body': text},
        );
      }
      final raw = data['comment'] as Map<String, dynamic>?;
      if (raw == null) {
        state = state.copyWith(isSending: false, clearReply: true);
        await load();
      } else {
        final created = CommentItem.fromJson(raw);
        final updated = replyToId == null
            ? [created, ...state.items]
            : _appendReply(state.items, replyToId, created);
        state = state.copyWith(
          items: updated,
          isSending: false,
          clearReply: true,
        );
      }
      return true;
    } on ApiException catch (e) {
      state = state.copyWith(isSending: false, error: e.message);
      return false;
    }
  }

  Future<void> toggleLike(CommentItem comment, {int? rootId}) async {
    final previousItems = state.items;
    final optimistic = comment.copyWith(
      likedByMe: !comment.likedByMe,
      likesCount: comment.likedByMe
          ? (comment.likesCount - 1).clamp(0, 1 << 31)
          : comment.likesCount + 1,
    );
    state = state.copyWith(
      items: _replaceComment(state.items, comment.id, optimistic),
      clearError: true,
    );
    try {
      final Map<String, dynamic> data;
      if (comment.likedByMe) {
        data = await _api.delete('/api/mobile/v1/comments/${comment.id}/like');
      } else {
        data = await _api.post('/api/mobile/v1/comments/${comment.id}/like');
      }
      final reconciled = optimistic.copyWith(
        likedByMe: data['liked'] as bool? ?? optimistic.likedByMe,
        likesCount: data['likes_count'] as int? ?? optimistic.likesCount,
      );
      state = state.copyWith(
        items: _replaceComment(state.items, comment.id, reconciled),
      );
    } on ApiException catch (e) {
      state = state.copyWith(items: previousItems, error: e.message);
    } catch (_) {
      state = state.copyWith(
        items: previousItems,
        error: 'تعذر تحديث الإعجاب. حاول مرة أخرى.',
      );
    }
  }

  List<CommentItem> _appendReply(
    List<CommentItem> items,
    int rootId,
    CommentItem reply,
  ) {
    return [
      for (final item in items)
        if (item.id == rootId)
          item.copyWith(
            replies: [...item.replies, reply],
            repliesCount: item.repliesCount + 1,
          )
        else
          item,
    ];
  }

  List<CommentItem> _replaceComment(
    List<CommentItem> items,
    int id,
    CommentItem replacement,
  ) {
    return [
      for (final item in items)
        if (item.id == id)
          replacement
        else if (item.replies.any((reply) => reply.id == id))
          item.copyWith(
            replies: [
              for (final reply in item.replies)
                if (reply.id == id) replacement else reply,
            ],
          )
        else
          item,
    ];
  }
}

final commentsControllerProvider = StateNotifierProvider.autoDispose
    .family<CommentsController, CommentsState, int>((ref, videoId) {
  return CommentsController(ref.watch(apiClientProvider), videoId);
});
