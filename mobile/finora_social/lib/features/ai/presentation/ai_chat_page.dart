import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../core/theme/app_colors.dart';
import '../data/ai_controller.dart';

class AiChatPage extends ConsumerStatefulWidget {
  const AiChatPage({super.key});

  @override
  ConsumerState<AiChatPage> createState() => _AiChatPageState();
}

class _AiChatPageState extends ConsumerState<AiChatPage> {
  static const _quickPrompts = [
    'رشّح لي حسب ذوقي',
    'شنو أفضل العروض؟',
    'قارن بين منتجين',
    'كم رصيد نقاطي؟',
  ];

  final _controller = TextEditingController();
  final _focusNode = FocusNode();
  final _scrollController = ScrollController();

  @override
  void initState() {
    super.initState();
    Future.microtask(
      () => ref.read(aiControllerProvider.notifier).ensureConversation(),
    );
  }

  @override
  void dispose() {
    _controller.dispose();
    _focusNode.dispose();
    _scrollController.dispose();
    super.dispose();
  }

  void _scrollToEnd({bool immediate = false}) {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!_scrollController.hasClients) return;
      _scrollController.animateTo(
        _scrollController.position.maxScrollExtent,
        duration: Duration(milliseconds: immediate ? 120 : 280),
        curve: Curves.easeOutCubic,
      );
    });
  }

  Future<void> _send([String? preset]) async {
    final text = (preset ?? _controller.text).trim();
    if (text.isEmpty || ref.read(aiControllerProvider).sending) return;
    _controller.clear();
    FocusScope.of(context).unfocus();
    HapticFeedback.selectionClick();
    final future = ref.read(aiControllerProvider.notifier).send(text);
    _scrollToEnd(immediate: true);
    await future;
    _scrollToEnd();
    if (!mounted) return;
    final messages = ref.read(aiControllerProvider).messages;
    if (messages.isEmpty) return;
    for (final action in messages.last.uiActions) {
      if (action['type'] == 'open_cart') context.push('/cart');
      if (action['type'] == 'open_order' && action['order_id'] != null) {
        context.push('/profile/orders/${action['order_id']}');
      }
    }
  }

  Future<void> _newConversation() async {
    await ref.read(aiControllerProvider.notifier).newConversation();
    _scrollToEnd(immediate: true);
  }

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    final state = ref.watch(aiControllerProvider);
    ref.listen<AiState>(aiControllerProvider, (previous, next) {
      if (previous?.messages.length != next.messages.length ||
          previous?.sending != next.sending) {
        _scrollToEnd();
      }
    });

    return Scaffold(
      backgroundColor: colors.surface,
      appBar: AppBar(
        titleSpacing: 8,
        title: const Row(
          children: [
            _AiLogo(size: 38),
            SizedBox(width: 10),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text('Finora AI'),
                  Text(
                    'متصل بمنتجاتك وطلباتك',
                    style: TextStyle(
                      fontSize: 10,
                      fontWeight: FontWeight.w600,
                      color: AppColors.success,
                    ),
                  ),
                ],
              ),
            ),
          ],
        ),
        actions: [
          IconButton(
            tooltip: 'محادثة جديدة',
            onPressed: state.loading ? null : _newConversation,
            icon: const Icon(Icons.add_comment_outlined),
          ),
        ],
      ),
      body: Column(
        children: [
          if (state.error != null)
            _ErrorBanner(
              message: state.error!,
              onRetry: () =>
                  ref.read(aiControllerProvider.notifier).ensureConversation(),
            ),
          Expanded(
            child: state.loading && state.messages.isEmpty
                ? const _AiLoading()
                : state.messages.isEmpty
                    ? _AiWelcome(onPrompt: _send)
                    : ListView.builder(
                        controller: _scrollController,
                        padding: const EdgeInsets.fromLTRB(14, 12, 14, 20),
                        keyboardDismissBehavior:
                            ScrollViewKeyboardDismissBehavior.onDrag,
                        cacheExtent: 1000,
                        itemCount:
                            state.messages.length + (state.sending ? 1 : 0),
                        itemBuilder: (context, index) {
                          if (index == state.messages.length) {
                            return const _ThinkingBubble();
                          }
                          return _AiMessageBubble(
                            message: state.messages[index],
                            onPrompt: _send,
                            onProduct: (id) =>
                                context.push('/store/product/$id'),
                            onConfirm: (action) async {
                              final ok = await ref
                                  .read(aiControllerProvider.notifier)
                                  .confirmAction(action);
                              if (!context.mounted) return;
                              ScaffoldMessenger.of(context).showSnackBar(
                                SnackBar(
                                  content: Text(ok
                                      ? 'تمت الإضافة للعربة'
                                      : 'تعذر تأكيد الإجراء'),
                                ),
                              );
                              if (ok) context.push('/cart');
                            },
                          );
                        },
                      ),
          ),
          if (!state.loading)
            SizedBox(
              height: 44,
              child: ListView.separated(
                scrollDirection: Axis.horizontal,
                padding: const EdgeInsets.symmetric(horizontal: 12),
                itemCount: _quickPrompts.length,
                separatorBuilder: (_, __) => const SizedBox(width: 7),
                itemBuilder: (context, index) => ActionChip(
                  avatar: Icon(
                    index == 0
                        ? Icons.auto_awesome_rounded
                        : Icons.bolt_rounded,
                    size: 16,
                    color: AppColors.mutedGold,
                  ),
                  label: Text(_quickPrompts[index]),
                  onPressed:
                      state.sending ? null : () => _send(_quickPrompts[index]),
                ),
              ),
            ),
          _AiComposer(
            controller: _controller,
            focusNode: _focusNode,
            sending: state.sending,
            onSend: _send,
          ),
        ],
      ),
    );
  }
}

class _AiLogo extends StatelessWidget {
  const _AiLogo({this.size = 42});

  final double size;

  @override
  Widget build(BuildContext context) {
    return Container(
      width: size,
      height: size,
      decoration: BoxDecoration(
        gradient: const LinearGradient(
          begin: Alignment.topRight,
          end: Alignment.bottomLeft,
          colors: [AppColors.goldAccent, AppColors.mutedGold],
        ),
        borderRadius: BorderRadius.circular(size * 0.34),
        boxShadow: const [
          BoxShadow(color: Color(0x33B9821F), blurRadius: 14),
        ],
      ),
      child: Icon(
        Icons.auto_awesome_rounded,
        color: AppColors.primaryDark,
        size: size * 0.56,
      ),
    );
  }
}

class _AiWelcome extends StatelessWidget {
  const _AiWelcome({required this.onPrompt});

  final ValueChanged<String> onPrompt;

  @override
  Widget build(BuildContext context) {
    return ListView(
      padding: const EdgeInsets.fromLTRB(22, 26, 22, 24),
      children: [
        const Align(child: _AiLogo(size: 72)),
        const SizedBox(height: 18),
        Text(
          'مساعدك الشخصي للتسوق',
          textAlign: TextAlign.center,
          style: Theme.of(context).textTheme.headlineSmall,
        ),
        const SizedBox(height: 8),
        Text(
          'يفهم احتياجك، يقارن المنتجات الحقيقية، ويتابع طلباتك ونقاطك بدون تخمين.',
          textAlign: TextAlign.center,
          style: TextStyle(
            color: Theme.of(context).colorScheme.onSurfaceVariant,
            height: 1.55,
          ),
        ),
        const SizedBox(height: 24),
        _CapabilityCard(
          icon: Icons.manage_search_rounded,
          title: 'اختيار ذكي',
          subtitle: 'قل ميزانيتك واستخدامك ونرشح الأنسب',
          onTap: () =>
              onPrompt('رشّح لي منتجاً مناسباً حسب ميزانيتي واستخدامي'),
        ),
        const SizedBox(height: 10),
        _CapabilityCard(
          icon: Icons.compare_arrows_rounded,
          title: 'مقارنة دقيقة',
          subtitle: 'سعر ومواصفات وتوفر من بيانات المتجر',
          onTap: () => onPrompt('أريد مقارنة بين منتجين'),
        ),
        const SizedBox(height: 10),
        _CapabilityCard(
          icon: Icons.local_shipping_outlined,
          title: 'خدمة ما بعد الطلب',
          subtitle: 'تتبع الطلب والنقاط والكوبونات',
          onTap: () => onPrompt('ساعدني بمتابعة طلبي'),
        ),
      ],
    );
  }
}

class _CapabilityCard extends StatelessWidget {
  const _CapabilityCard({
    required this.icon,
    required this.title,
    required this.subtitle,
    required this.onTap,
  });

  final IconData icon;
  final String title;
  final String subtitle;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return Card(
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(22),
        child: Padding(
          padding: const EdgeInsets.all(15),
          child: Row(
            children: [
              Container(
                width: 46,
                height: 46,
                decoration: BoxDecoration(
                  color: AppColors.goldAccent.withOpacity(0.12),
                  borderRadius: BorderRadius.circular(15),
                ),
                child: Icon(icon, color: AppColors.mutedGold),
              ),
              const SizedBox(width: 13),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(title,
                        style: const TextStyle(fontWeight: FontWeight.w900)),
                    Text(
                      subtitle,
                      style: TextStyle(
                        color: Theme.of(context).colorScheme.onSurfaceVariant,
                        fontSize: 12,
                      ),
                    ),
                  ],
                ),
              ),
              const Icon(Icons.chevron_left_rounded),
            ],
          ),
        ),
      ),
    );
  }
}

class _AiMessageBubble extends StatelessWidget {
  const _AiMessageBubble({
    required this.message,
    required this.onPrompt,
    required this.onProduct,
    required this.onConfirm,
  });

  final AiMessage message;
  final ValueChanged<String> onPrompt;
  final ValueChanged<int> onProduct;
  final ValueChanged<Map<String, dynamic>> onConfirm;

  @override
  Widget build(BuildContext context) {
    final isUser = message.role == 'user';
    final colors = Theme.of(context).colorScheme;
    return Padding(
      padding: const EdgeInsets.only(bottom: 14),
      child: Row(
        mainAxisAlignment:
            isUser ? MainAxisAlignment.end : MainAxisAlignment.start,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          if (!isUser) ...[
            const _AiLogo(size: 32),
            const SizedBox(width: 8),
          ],
          Flexible(
            child: Container(
              constraints: BoxConstraints(
                maxWidth: MediaQuery.sizeOf(context).width * 0.84,
              ),
              padding: const EdgeInsets.all(14),
              decoration: BoxDecoration(
                color: isUser
                    ? AppColors.goldAccent
                    : colors.surfaceVariant.withOpacity(0.52),
                borderRadius: BorderRadiusDirectional.only(
                  topStart: const Radius.circular(20),
                  topEnd: const Radius.circular(20),
                  bottomStart: Radius.circular(isUser ? 20 : 5),
                  bottomEnd: Radius.circular(isUser ? 5 : 20),
                ),
                border:
                    isUser ? null : Border.all(color: colors.outlineVariant),
              ),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  SelectableText(
                    message.content,
                    style: TextStyle(
                      color: isUser ? AppColors.primaryDark : colors.onSurface,
                      height: 1.55,
                      fontWeight: isUser ? FontWeight.w600 : FontWeight.w500,
                    ),
                  ),
                  if (message.products.isNotEmpty) ...[
                    const SizedBox(height: 12),
                    SizedBox(
                      height: 142,
                      child: ListView.separated(
                        scrollDirection: Axis.horizontal,
                        itemCount: message.products.length,
                        separatorBuilder: (_, __) => const SizedBox(width: 8),
                        itemBuilder: (context, index) {
                          final product = message.products[index];
                          return _AiProductCard(
                            product: product,
                            onTap: () => onProduct(
                              int.tryParse('${product['id']}') ?? 0,
                            ),
                          );
                        },
                      ),
                    ),
                  ],
                  if (message.pendingActions.isNotEmpty) ...[
                    const SizedBox(height: 10),
                    for (final action in message.pendingActions)
                      SizedBox(
                        width: double.infinity,
                        child: FilledButton.icon(
                          onPressed: () => onConfirm(action),
                          icon: const Icon(Icons.verified_rounded),
                          label: Text(
                            'تأكيد إضافة ${action['name'] ?? 'المنتج'}',
                          ),
                        ),
                      ),
                  ],
                  if (message.suggestions.isNotEmpty) ...[
                    const SizedBox(height: 10),
                    Wrap(
                      spacing: 7,
                      runSpacing: 7,
                      children: [
                        for (final suggestion in message.suggestions)
                          ActionChip(
                            label: Text(suggestion),
                            onPressed: () => onPrompt(suggestion),
                          ),
                      ],
                    ),
                  ],
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _AiProductCard extends StatelessWidget {
  const _AiProductCard({required this.product, required this.onTap});

  final Map<String, dynamic> product;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final imageUrl = '${product['image_url'] ?? ''}';
    return SizedBox(
      width: 220,
      child: Material(
        color: Theme.of(context).colorScheme.surface,
        borderRadius: BorderRadius.circular(16),
        clipBehavior: Clip.antiAlias,
        child: InkWell(
          onTap: onTap,
          child: Row(
            children: [
              SizedBox(
                width: 84,
                height: double.infinity,
                child: imageUrl.isEmpty
                    ? const Icon(Icons.inventory_2_outlined)
                    : Image.network(
                        imageUrl,
                        fit: BoxFit.cover,
                        errorBuilder: (_, __, ___) =>
                            const Icon(Icons.broken_image_outlined),
                      ),
              ),
              Expanded(
                child: Padding(
                  padding: const EdgeInsets.all(10),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    mainAxisAlignment: MainAxisAlignment.center,
                    children: [
                      Text(
                        '${product['name'] ?? ''}',
                        maxLines: 2,
                        overflow: TextOverflow.ellipsis,
                        style: const TextStyle(fontWeight: FontWeight.w900),
                      ),
                      const SizedBox(height: 6),
                      Text(
                        '${product['price'] ?? 0} د.ع',
                        style: const TextStyle(
                          color: AppColors.mutedGold,
                          fontWeight: FontWeight.w800,
                        ),
                      ),
                      Text(
                        '${product['stock_status'] ?? ''}',
                        maxLines: 1,
                        style: const TextStyle(
                          color: AppColors.success,
                          fontSize: 11,
                        ),
                      ),
                    ],
                  ),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _ThinkingBubble extends StatelessWidget {
  const _ThinkingBubble();

  @override
  Widget build(BuildContext context) {
    final muted = Theme.of(context).colorScheme.onSurfaceVariant;
    return Padding(
      padding: const EdgeInsets.only(bottom: 14),
      child: Row(
        children: [
          const _AiLogo(size: 32),
          const SizedBox(width: 8),
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 15, vertical: 13),
            decoration: BoxDecoration(
              color: Theme.of(context).colorScheme.surfaceVariant,
              borderRadius: BorderRadius.circular(18),
            ),
            child: Row(
              children: [
                for (var index = 0; index < 3; index++)
                  Container(
                    width: 6,
                    height: 6,
                    margin: const EdgeInsets.symmetric(horizontal: 2),
                    decoration: BoxDecoration(
                      shape: BoxShape.circle,
                      color: muted.withOpacity(0.45 + index * 0.2),
                    ),
                  ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class _AiComposer extends StatelessWidget {
  const _AiComposer({
    required this.controller,
    required this.focusNode,
    required this.sending,
    required this.onSend,
  });

  final TextEditingController controller;
  final FocusNode focusNode;
  final bool sending;
  final VoidCallback onSend;

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    return SafeArea(
      top: false,
      child: Container(
        padding: const EdgeInsets.fromLTRB(12, 8, 12, 12),
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
                  hintText: 'اسأل عن منتج أو ميزانية أو طلب…',
                  prefixIcon: const Icon(Icons.auto_awesome_outlined),
                  filled: true,
                  fillColor: colors.surfaceVariant.withOpacity(0.55),
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
              onPressed: sending ? null : onSend,
              style: IconButton.styleFrom(
                backgroundColor: AppColors.goldAccent,
                foregroundColor: AppColors.primaryDark,
                minimumSize: const Size(52, 52),
              ),
              icon: const Icon(Icons.arrow_upward_rounded),
            ),
          ],
        ),
      ),
    );
  }
}

class _AiLoading extends StatelessWidget {
  const _AiLoading();

  @override
  Widget build(BuildContext context) {
    return const Center(
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          _AiLogo(size: 58),
          SizedBox(height: 18),
          CircularProgressIndicator(strokeWidth: 2.5),
        ],
      ),
    );
  }
}

class _ErrorBanner extends StatelessWidget {
  const _ErrorBanner({required this.message, required this.onRetry});

  final String message;
  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    return Material(
      color: colors.errorContainer,
      child: ListTile(
        leading: Icon(
          Icons.error_outline_rounded,
          color: colors.onErrorContainer,
        ),
        title: Text(message, style: TextStyle(color: colors.onErrorContainer)),
        trailing: TextButton(onPressed: onRetry, child: const Text('إعادة')),
      ),
    );
  }
}
