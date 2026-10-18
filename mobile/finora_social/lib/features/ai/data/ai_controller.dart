import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api/api_client.dart';
import '../../../core/errors/api_exception.dart';

class AiMessage {
  AiMessage({
    required this.id,
    required this.role,
    required this.content,
    this.meta = const {},
    this.createdAt,
  });

  factory AiMessage.fromJson(Map<String, dynamic> json) {
    return AiMessage(
      id: (json['id'] as int?) ?? 0,
      role: (json['role'] as String?) ?? 'assistant',
      content: (json['content'] as String?) ?? '',
      meta: (json['meta'] as Map<String, dynamic>?) ?? const {},
      createdAt: json['created_at'] as String?,
    );
  }

  final int id;
  final String role;
  final String content;
  final Map<String, dynamic> meta;
  final String? createdAt;

  List<Map<String, dynamic>> get products =>
      ((meta['products'] as List<dynamic>?) ?? [])
          .whereType<Map<String, dynamic>>()
          .toList();

  List<Map<String, dynamic>> get pendingActions =>
      ((meta['pending_actions'] as List<dynamic>?) ?? [])
          .whereType<Map<String, dynamic>>()
          .toList();

  List<Map<String, dynamic>> get uiActions =>
      ((meta['ui_actions'] as List<dynamic>?) ?? [])
          .whereType<Map<String, dynamic>>()
          .toList();

  List<String> get suggestions =>
      ((meta['suggestions'] as List<dynamic>?) ?? [])
          .map((e) => e.toString())
          .where((e) => e.isNotEmpty)
          .toList();
}

class AiState {
  AiState({
    this.conversationId,
    this.messages = const [],
    this.loading = false,
    this.sending = false,
    this.error,
  });

  final int? conversationId;
  final List<AiMessage> messages;
  final bool loading;
  final bool sending;
  final String? error;

  AiState copyWith({
    int? conversationId,
    List<AiMessage>? messages,
    bool? loading,
    bool? sending,
    String? error,
    bool clearError = false,
  }) {
    return AiState(
      conversationId: conversationId ?? this.conversationId,
      messages: messages ?? this.messages,
      loading: loading ?? this.loading,
      sending: sending ?? this.sending,
      error: clearError ? null : (error ?? this.error),
    );
  }
}

final aiControllerProvider =
    StateNotifierProvider<AiController, AiState>((ref) {
  return AiController(ref.watch(apiClientProvider));
});

class AiController extends StateNotifier<AiState> {
  AiController(this._api) : super(AiState());

  final ApiClient _api;

  Future<void> ensureConversation() async {
    if (state.conversationId != null && state.messages.isNotEmpty) return;
    state = state.copyWith(loading: true, clearError: true);
    try {
      final raw = await _api.post('/api/mobile/v1/ai/conversations', data: {});
      final conv = (raw['conversation'] as Map<String, dynamic>?) ?? {};
      final messages = ((conv['messages'] as List<dynamic>?) ?? [])
          .whereType<Map<String, dynamic>>()
          .map(AiMessage.fromJson)
          .toList();
      state = state.copyWith(
        conversationId: conv['id'] as int?,
        messages: messages,
        loading: false,
      );
    } on ApiException catch (e) {
      state = state.copyWith(loading: false, error: e.message);
    }
  }

  Future<void> send(String content) async {
    await ensureConversation();
    final id = state.conversationId;
    if (id == null) return;
    final localUser = AiMessage(
      id: -DateTime.now().microsecondsSinceEpoch,
      role: 'user',
      content: content,
      createdAt: DateTime.now().toIso8601String(),
    );
    final messagesBeforeSend = state.messages;
    state = state.copyWith(
      messages: [...state.messages, localUser],
      sending: true,
      clearError: true,
    );
    try {
      final raw = await _api.post(
        '/api/mobile/v1/ai/conversations/$id/messages',
        data: {'content': content},
      );
      final user = AiMessage.fromJson(
        (raw['user_message'] as Map<String, dynamic>?) ?? {},
      );
      final assistant = AiMessage.fromJson(
        (raw['assistant_message'] as Map<String, dynamic>?) ?? {},
      );
      state = state.copyWith(
        messages: [...messagesBeforeSend, user, assistant],
        sending: false,
      );
    } on ApiException catch (e) {
      state = state.copyWith(sending: false, error: e.message);
    }
  }

  Future<void> newConversation() async {
    state = AiState(loading: true);
    try {
      final raw = await _api.post('/api/mobile/v1/ai/conversations', data: {
        'title': 'محادثة جديدة',
      });
      final conversation = (raw['conversation'] as Map<String, dynamic>?) ?? {};
      final messages = ((conversation['messages'] as List<dynamic>?) ?? [])
          .whereType<Map<String, dynamic>>()
          .map(AiMessage.fromJson)
          .toList();
      state = state.copyWith(
        conversationId: conversation['id'] as int?,
        messages: messages,
        loading: false,
      );
    } on ApiException catch (error) {
      state = state.copyWith(loading: false, error: error.message);
    }
  }

  Future<bool> confirmAction(Map<String, dynamic> action) async {
    final id = state.conversationId;
    if (id == null) return false;
    try {
      final raw = await _api.post(
        '/api/mobile/v1/ai/conversations/$id/confirm-action',
        data: {'action': action},
      );
      final assistant = AiMessage.fromJson(
        (raw['assistant_message'] as Map<String, dynamic>?) ?? {},
      );
      state = state.copyWith(messages: [...state.messages, assistant]);
      return raw['ok'] == true;
    } on ApiException catch (e) {
      state = state.copyWith(error: e.message);
      return false;
    }
  }
}
