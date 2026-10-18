import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../core/theme/app_colors.dart';
import '../../authentication/data/auth_controller.dart';
import '../data/comments_controller.dart';

Future<void> showCommentsSheet(BuildContext context, int videoId) {
  return showModalBottomSheet<void>(
    context: context,
    isScrollControlled: true,
    useSafeArea: true,
    backgroundColor: Colors.transparent,
    barrierColor: Colors.black54,
    builder: (context) => Container(
      height: MediaQuery.sizeOf(context).height * 0.84,
      clipBehavior: Clip.antiAlias,
      decoration: BoxDecoration(
        color: Theme.of(context).colorScheme.surface,
        borderRadius: const BorderRadius.vertical(top: Radius.circular(30)),
      ),
      child: Padding(
        padding: EdgeInsets.only(
          bottom: MediaQuery.viewInsetsOf(context).bottom,
        ),
        child: CommentsSheet(videoId: videoId),
      ),
    ),
  );
}

class CommentsSheet extends ConsumerStatefulWidget {
  const CommentsSheet({super.key, required this.videoId});

  final int videoId;

  @override
  ConsumerState<CommentsSheet> createState() => _CommentsSheetState();
}

class _CommentsSheetState extends ConsumerState<CommentsSheet> {
  final _controller = TextEditingController();
  final _focusNode = FocusNode();

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      ref.read(commentsControllerProvider(widget.videoId).notifier).load();
    });
  }

  @override
  void dispose() {
    _controller.dispose();
    _focusNode.dispose();
    super.dispose();
  }

  Future<void> _send() async {
    if (!ref.read(authControllerProvider).isAuthenticated) {
      Navigator.pop(context);
      if (mounted) context.push('/auth/phone?returnTo=/home');
      return;
    }
    final ok = await ref
        .read(commentsControllerProvider(widget.videoId).notifier)
        .send(_controller.text);
    if (ok) {
      _controller.clear();
      HapticFeedback.lightImpact();
    }
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final colors = theme.colorScheme;
    final state = ref.watch(commentsControllerProvider(widget.videoId));
    final notifier =
        ref.read(commentsControllerProvider(widget.videoId).notifier);
    final isAuthenticated = ref.watch(authControllerProvider).isAuthenticated;
    final totalComments = state.items.fold<int>(
      state.items.length,
      (total, item) => total + item.replies.length,
    );

    void protectedAction(VoidCallback action) {
      if (isAuthenticated) {
        action();
      } else {
        Navigator.pop(context);
        context.push('/auth/phone?returnTo=/home');
      }
    }

    void beginReply(CommentItem item) {
      protectedAction(() {
        notifier.setReplyTo(item);
        _focusNode.requestFocus();
      });
    }

    void like(CommentItem item, {int? rootId}) {
      protectedAction(() {
        HapticFeedback.selectionClick();
        notifier.toggleLike(item, rootId: rootId);
      });
    }

    return Column(
      children: [
        const SizedBox(height: 10),
        Container(
          width: 46,
          height: 5,
          decoration: BoxDecoration(
            color: colors.onSurface.withOpacity(0.18),
            borderRadius: BorderRadius.circular(99),
          ),
        ),
        Padding(
          padding: const EdgeInsets.fromLTRB(18, 14, 18, 12),
          child: Row(
            children: [
              Container(
                width: 40,
                height: 40,
                decoration: BoxDecoration(
                  color: AppColors.goldAccent.withOpacity(0.14),
                  borderRadius: BorderRadius.circular(14),
                ),
                child: const Icon(
                  Icons.forum_rounded,
                  color: AppColors.mutedGold,
                ),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text('المجتمع', style: theme.textTheme.titleLarge),
                    Text(
                      totalComments == 0
                          ? 'ابدأ أول محادثة'
                          : '$totalComments تعليق ورد',
                      style: theme.textTheme.bodySmall?.copyWith(
                        color: colors.onSurfaceVariant,
                      ),
                    ),
                  ],
                ),
              ),
              IconButton(
                tooltip: 'إغلاق',
                onPressed: () => Navigator.pop(context),
                icon: const Icon(Icons.close_rounded),
              ),
            ],
          ),
        ),
        Divider(color: colors.outlineVariant),
        if (state.error != null)
          Container(
            width: double.infinity,
            margin: const EdgeInsets.fromLTRB(16, 10, 16, 0),
            padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
            decoration: BoxDecoration(
              color: colors.errorContainer,
              borderRadius: BorderRadius.circular(14),
            ),
            child: Text(
              state.error!,
              style: TextStyle(color: colors.onErrorContainer),
            ),
          ),
        Expanded(
          child: state.isLoading
              ? const Center(child: CircularProgressIndicator())
              : state.items.isEmpty
                  ? _EmptyComments(onWrite: () => _focusNode.requestFocus())
                  : RefreshIndicator(
                      onRefresh: notifier.load,
                      child: ListView.separated(
                        padding: const EdgeInsets.fromLTRB(16, 14, 16, 24),
                        keyboardDismissBehavior:
                            ScrollViewKeyboardDismissBehavior.onDrag,
                        cacheExtent: 900,
                        itemCount: state.items.length,
                        separatorBuilder: (_, __) => const SizedBox(height: 18),
                        itemBuilder: (context, index) {
                          final item = state.items[index];
                          return _CommentTile(
                            item: item,
                            onReply: () => beginReply(item),
                            onLike: () => like(item),
                            onReplyLike: (reply) =>
                                like(reply, rootId: item.id),
                          );
                        },
                      ),
                    ),
        ),
        if (state.replyToName != null)
          Container(
            margin: const EdgeInsets.fromLTRB(14, 0, 14, 6),
            padding: const EdgeInsetsDirectional.fromSTEB(12, 7, 4, 7),
            decoration: BoxDecoration(
              color: AppColors.goldAccent.withOpacity(0.12),
              borderRadius: BorderRadius.circular(12),
            ),
            child: Row(
              children: [
                const Icon(
                  Icons.reply_rounded,
                  color: AppColors.mutedGold,
                  size: 18,
                ),
                const SizedBox(width: 7),
                Expanded(
                  child: Text(
                    'الرد على ${state.replyToName}',
                    style: const TextStyle(
                      color: AppColors.mutedGold,
                      fontWeight: FontWeight.w700,
                    ),
                  ),
                ),
                IconButton(
                  visualDensity: VisualDensity.compact,
                  onPressed: () => notifier.setReplyTo(null),
                  icon: const Icon(Icons.close_rounded, size: 18),
                ),
              ],
            ),
          ),
        _CommentComposer(
          controller: _controller,
          focusNode: _focusNode,
          isAuthenticated: isAuthenticated,
          isSending: state.isSending,
          onSend: _send,
        ),
      ],
    );
  }
}

class _EmptyComments extends StatelessWidget {
  const _EmptyComments({required this.onWrite});

  final VoidCallback onWrite;

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(32),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(Icons.chat_bubble_outline_rounded,
                size: 54, color: colors.onSurfaceVariant.withOpacity(0.5)),
            const SizedBox(height: 14),
            Text(
              'المكان ينتظر رأيك',
              style: Theme.of(context).textTheme.titleMedium?.copyWith(
                    fontWeight: FontWeight.w800,
                  ),
            ),
            const SizedBox(height: 6),
            Text(
              'اكتب تعليقاً مفيداً وابدأ الحوار',
              style: TextStyle(color: colors.onSurfaceVariant),
            ),
            const SizedBox(height: 16),
            TextButton.icon(
              onPressed: onWrite,
              icon: const Icon(Icons.edit_rounded),
              label: const Text('اكتب الآن'),
            ),
          ],
        ),
      ),
    );
  }
}

class _CommentTile extends StatelessWidget {
  const _CommentTile({
    required this.item,
    required this.onReply,
    required this.onLike,
    required this.onReplyLike,
  });

  final CommentItem item;
  final VoidCallback onReply;
  final VoidCallback onLike;
  final ValueChanged<CommentItem> onReplyLike;

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        _CommentRow(item: item, onReply: onReply, onLike: onLike),
        if (item.replies.isNotEmpty)
          Container(
            margin: const EdgeInsetsDirectional.only(start: 24, top: 12),
            padding: const EdgeInsetsDirectional.only(start: 14),
            decoration: BoxDecoration(
              border: BorderDirectional(
                start: BorderSide(color: colors.outlineVariant, width: 2),
              ),
            ),
            child: Column(
              children: [
                for (final reply in item.replies)
                  Padding(
                    padding: const EdgeInsets.only(bottom: 14),
                    child: _CommentRow(
                      item: reply,
                      onReply: onReply,
                      onLike: () => onReplyLike(reply),
                      compact: true,
                    ),
                  ),
              ],
            ),
          ),
      ],
    );
  }
}

class _CommentRow extends StatelessWidget {
  const _CommentRow({
    required this.item,
    required this.onReply,
    required this.onLike,
    this.compact = false,
  });

  final CommentItem item;
  final VoidCallback onReply;
  final VoidCallback onLike;
  final bool compact;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final colors = theme.colorScheme;
    return GestureDetector(
      behavior: HitTestBehavior.opaque,
      onDoubleTap: onLike,
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          CircleAvatar(
            radius: compact ? 15 : 19,
            backgroundColor: item.isCompanyReply
                ? AppColors.goldAccent
                : colors.surfaceVariant,
            child: Text(
              item.authorName.isNotEmpty
                  ? item.authorName.characters.first.toUpperCase()
                  : '?',
              style: TextStyle(
                color: item.isCompanyReply
                    ? AppColors.primaryDark
                    : colors.onSurfaceVariant,
                fontWeight: FontWeight.w800,
                fontSize: compact ? 11 : 13,
              ),
            ),
          ),
          const SizedBox(width: 10),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Wrap(
                  spacing: 7,
                  runSpacing: 4,
                  crossAxisAlignment: WrapCrossAlignment.center,
                  children: [
                    Text(
                      item.authorName,
                      style: TextStyle(
                        color: item.isCompanyReply
                            ? AppColors.mutedGold
                            : colors.onSurface,
                        fontWeight: FontWeight.w800,
                        fontSize: compact ? 12 : 13.5,
                      ),
                    ),
                    if (item.isCompanyReply)
                      const _MiniBadge(label: 'Finora', icon: Icons.verified),
                    if (item.isPinned)
                      const _MiniBadge(
                        label: 'مثبّت',
                        icon: Icons.push_pin_rounded,
                      ),
                    Text(
                      _relativeTime(item.createdAt),
                      style: theme.textTheme.labelSmall?.copyWith(
                        color: colors.onSurfaceVariant,
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: 5),
                Text(
                  item.body,
                  style: theme.textTheme.bodyMedium?.copyWith(
                    color: colors.onSurface,
                    height: 1.5,
                  ),
                ),
                const SizedBox(height: 7),
                Row(
                  children: [
                    _CommentAction(
                      onTap: onLike,
                      active: item.likedByMe,
                      icon: item.likedByMe
                          ? Icons.favorite_rounded
                          : Icons.favorite_border_rounded,
                      label:
                          item.likesCount == 0 ? 'إعجاب' : '${item.likesCount}',
                    ),
                    const SizedBox(width: 18),
                    _CommentAction(
                      onTap: onReply,
                      icon: Icons.reply_rounded,
                      label: 'رد',
                    ),
                  ],
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class _MiniBadge extends StatelessWidget {
  const _MiniBadge({required this.label, required this.icon});

  final String label;
  final IconData icon;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
      decoration: BoxDecoration(
        color: AppColors.goldAccent.withOpacity(0.13),
        borderRadius: BorderRadius.circular(99),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(icon, size: 10, color: AppColors.mutedGold),
          const SizedBox(width: 3),
          Text(
            label,
            style: const TextStyle(
              color: AppColors.mutedGold,
              fontSize: 9,
              fontWeight: FontWeight.w800,
            ),
          ),
        ],
      ),
    );
  }
}

class _CommentAction extends StatelessWidget {
  const _CommentAction({
    required this.onTap,
    required this.icon,
    required this.label,
    this.active = false,
  });

  final VoidCallback onTap;
  final IconData icon;
  final String label;
  final bool active;

  @override
  Widget build(BuildContext context) {
    final muted = Theme.of(context).colorScheme.onSurfaceVariant;
    return InkWell(
      onTap: onTap,
      borderRadius: BorderRadius.circular(10),
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 2, vertical: 4),
        child: Row(
          children: [
            AnimatedSwitcher(
              duration: const Duration(milliseconds: 180),
              transitionBuilder: (child, animation) =>
                  ScaleTransition(scale: animation, child: child),
              child: Icon(
                icon,
                key: ValueKey(active),
                size: 16,
                color: active ? AppColors.error : muted,
              ),
            ),
            const SizedBox(width: 5),
            Text(
              label,
              style: TextStyle(
                color: active ? AppColors.error : muted,
                fontSize: 12,
                fontWeight: FontWeight.w700,
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _CommentComposer extends StatelessWidget {
  const _CommentComposer({
    required this.controller,
    required this.focusNode,
    required this.isAuthenticated,
    required this.isSending,
    required this.onSend,
  });

  final TextEditingController controller;
  final FocusNode focusNode;
  final bool isAuthenticated;
  final bool isSending;
  final VoidCallback onSend;

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    return SafeArea(
      top: false,
      child: Container(
        padding: const EdgeInsets.fromLTRB(12, 10, 12, 12),
        decoration: BoxDecoration(
          color: colors.surface,
          border: Border(top: BorderSide(color: colors.outlineVariant)),
        ),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.end,
          children: [
            Expanded(
              child: TextField(
                controller: controller,
                focusNode: focusNode,
                minLines: 1,
                maxLines: 4,
                textInputAction: TextInputAction.newline,
                decoration: InputDecoration(
                  hintText: isAuthenticated
                      ? 'شارك رأيك باحترام…'
                      : 'سجّل الدخول للمشاركة',
                  prefixIcon: const Icon(Icons.chat_bubble_outline_rounded),
                  filled: true,
                  fillColor: colors.surfaceVariant.withOpacity(0.55),
                  contentPadding:
                      const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
                  border: OutlineInputBorder(
                    borderRadius: BorderRadius.circular(20),
                    borderSide: BorderSide.none,
                  ),
                  enabledBorder: OutlineInputBorder(
                    borderRadius: BorderRadius.circular(20),
                    borderSide: BorderSide.none,
                  ),
                ),
              ),
            ),
            const SizedBox(width: 8),
            IconButton.filled(
              tooltip: 'إرسال',
              onPressed: isSending ? null : onSend,
              style: IconButton.styleFrom(
                backgroundColor: AppColors.goldAccent,
                foregroundColor: AppColors.primaryDark,
                minimumSize: const Size(50, 50),
              ),
              icon: isSending
                  ? const SizedBox(
                      width: 18,
                      height: 18,
                      child: CircularProgressIndicator(strokeWidth: 2),
                    )
                  : const Icon(Icons.arrow_upward_rounded),
            ),
          ],
        ),
      ),
    );
  }
}

String _relativeTime(DateTime? timestamp) {
  if (timestamp == null) return 'الآن';
  final difference = DateTime.now().toUtc().difference(timestamp.toUtc());
  if (difference.isNegative || difference.inMinutes < 1) return 'الآن';
  if (difference.inMinutes < 60) return 'منذ ${difference.inMinutes} د';
  if (difference.inHours < 24) return 'منذ ${difference.inHours} س';
  if (difference.inDays < 7) return 'منذ ${difference.inDays} ي';
  return '${timestamp.day}/${timestamp.month}/${timestamp.year}';
}
