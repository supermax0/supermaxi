import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:share_plus/share_plus.dart';

import '../../../core/theme/app_colors.dart';
import '../../authentication/data/auth_controller.dart';
import '../../cart/data/cart_controller.dart';
import '../../comments/presentation/comments_sheet.dart';
import '../../store/data/store_controller.dart';
import '../../store/presentation/video_products_sheet.dart';
import '../data/feed_controller.dart';
import 'feed_video_player.dart';

class VideoFeedPage extends ConsumerStatefulWidget {
  const VideoFeedPage({super.key});

  @override
  ConsumerState<VideoFeedPage> createState() => _VideoFeedPageState();
}

class _VideoFeedPageState extends ConsumerState<VideoFeedPage> {
  final _pageController = PageController();
  int _index = 0;
  final _viewed = <int>{};
  bool _overlayOpen = false;
  final _playerKeys = <int, GlobalKey<FeedVideoPlayerState>>{};

  GlobalKey<FeedVideoPlayerState> _keyFor(int videoId) {
    return _playerKeys.putIfAbsent(
      videoId,
      () => GlobalKey<FeedVideoPlayerState>(),
    );
  }

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      ref.read(feedControllerProvider.notifier).refresh();
    });
  }

  @override
  void dispose() {
    _pageController.dispose();
    super.dispose();
  }

  void _onPageChanged(int index, FeedState feed) {
    setState(() => _index = index);
    final item = feed.items[index];
    if (!_viewed.contains(item.id)) {
      _viewed.add(item.id);
      ref.read(feedControllerProvider.notifier).recordView(item.id);
    }
    if (index >= feed.items.length - 2) {
      ref.read(feedControllerProvider.notifier).loadMore();
    }
    // Drop keys far from the viewport to avoid unbounded growth.
    final keep = <int>{
      for (var i = index - 1; i <= index + 1; i++)
        if (i >= 0 && i < feed.items.length) feed.items[i].id,
    };
    _playerKeys.removeWhere((id, _) => !keep.contains(id));
  }

  bool _requireAccount({String returnTo = '/home'}) {
    if (ref.read(authControllerProvider).isAuthenticated) return true;
    context.push('/auth/phone?returnTo=$returnTo');
    return false;
  }

  Future<void> _openComments(int videoId) async {
    if (_overlayOpen) return;
    setState(() => _overlayOpen = true);
    try {
      await showCommentsSheet(context, videoId);
    } finally {
      if (mounted) setState(() => _overlayOpen = false);
    }
  }

  Future<void> _openProducts(int videoId) async {
    if (_overlayOpen) return;
    setState(() => _overlayOpen = true);
    try {
      await showVideoProductsSheet(context, videoId);
    } finally {
      if (mounted) setState(() => _overlayOpen = false);
    }
  }

  Future<void> _openProduct(StoreProduct product) async {
    context.push('/store/product/${product.id}');
  }

  Future<void> _addProductFromVideo(
      FeedVideo video, StoreProduct product) async {
    if (!_requireAccount(returnTo: '/store/product/${product.id}')) return;
    try {
      await ref.read(cartControllerProvider.notifier).addProduct(
            product.id,
            videoId: video.id,
          );
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('تمت الإضافة للعربة')),
      );
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('$e')),
      );
    }
  }

  @override
  Widget build(BuildContext context) {
    final feed = ref.watch(feedControllerProvider);
    final feedIsVisible = TickerMode.of(context);

    if (feed.isLoading && feed.items.isEmpty) {
      return const _FeedStatusView(
        icon: Icons.play_arrow_rounded,
        title: 'Finora Social',
        subtitle: 'نجهّز لك أحدث الفيديوهات والعروض',
        loading: true,
      );
    }

    if (feed.error != null && feed.items.isEmpty) {
      return _FeedStatusView(
        icon: Icons.wifi_off_rounded,
        title: 'تعذّر تحميل الفيديوهات',
        subtitle: feed.error!,
        actionLabel: 'إعادة المحاولة',
        onAction: () => ref.read(feedControllerProvider.notifier).refresh(),
      );
    }

    if (feed.items.isEmpty) {
      return _FeedStatusView(
        icon: Icons.video_collection_outlined,
        title: 'قريباً على Finora',
        subtitle: 'لا توجد فيديوهات منشورة الآن. اكتشف المنتجات من المتجر.',
        actionLabel: 'فتح المتجر',
        onAction: () => context.go('/store'),
      );
    }

    return Scaffold(
      backgroundColor: AppColors.primaryDark,
      body: PageView.builder(
        controller: _pageController,
        scrollDirection: Axis.vertical,
        allowImplicitScrolling: true,
        physics: const PageScrollPhysics(parent: BouncingScrollPhysics()),
        itemCount: feed.items.length,
        onPageChanged: (i) => _onPageChanged(i, feed),
        itemBuilder: (context, index) {
          final video = feed.items[index];
          final active = index == _index && feedIsVisible && !_overlayOpen;
          // Keep only the current and adjacent players warm to cap memory use.
          final warm = (index - _index).abs() <= 1;
          final playerKey = _keyFor(video.id);
          return RepaintBoundary(
            child: Stack(
              fit: StackFit.expand,
              children: [
                if (warm)
                  FeedVideoPlayer(
                    key: playerKey,
                    video: video,
                    isActive: active,
                    shouldWarm: warm,
                    onDoubleTapLike: () {
                      if (_requireAccount()) {
                        ref
                            .read(feedControllerProvider.notifier)
                            .toggleLike(index);
                      }
                    },
                  )
                else
                  Container(color: AppColors.primaryDark),
                const IgnorePointer(
                  child: DecoratedBox(
                    decoration: BoxDecoration(
                      gradient: LinearGradient(
                        begin: Alignment.topCenter,
                        end: Alignment.bottomCenter,
                        colors: [
                          Color(0x66000000),
                          Color(0x00000000),
                          Color(0xD9000000),
                        ],
                        stops: [0, 0.43, 1],
                      ),
                    ),
                  ),
                ),
                // Full-screen pause/play under the interactive overlay so empty
                // video areas still toggle, while product/description keep taps.
                if (warm && active)
                  Positioned.fill(
                    child: _FeedCenterTapZone(
                      onTap: () =>
                          playerKey.currentState?.toggleFromUserTap(),
                    ),
                  ),
                _FeedOverlay(
                  video: video,
                  onLike: () {
                    if (_requireAccount()) {
                      ref
                          .read(feedControllerProvider.notifier)
                          .toggleLike(index);
                    }
                  },
                  onSave: () {
                    if (_requireAccount()) {
                      ref
                          .read(feedControllerProvider.notifier)
                          .toggleSave(index);
                    }
                  },
                  onComments: () => _openComments(video.id),
                  onProducts: () => _openProducts(video.id),
                  onOpenProduct: (p) => _openProduct(p),
                  onProductCta: (p) => _addProductFromVideo(video, p),
                  onShare: () async {
                    await ref
                        .read(feedControllerProvider.notifier)
                        .share(index);
                    await Share.share(
                      video.playbackUrl.isNotEmpty
                          ? video.playbackUrl
                          : 'Finora: ${video.title}',
                    );
                  },
                ),
              ],
            ),
          );
        },
      ),
    );
  }
}

class _FeedStatusView extends StatelessWidget {
  const _FeedStatusView({
    required this.icon,
    required this.title,
    required this.subtitle,
    this.loading = false,
    this.actionLabel,
    this.onAction,
  });

  final IconData icon;
  final String title;
  final String subtitle;
  final bool loading;
  final String? actionLabel;
  final VoidCallback? onAction;

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: AppColors.primaryDark,
      body: Container(
        decoration: const BoxDecoration(
          gradient: RadialGradient(
            center: Alignment(0.65, -0.55),
            radius: 1.25,
            colors: [Color(0xFF4B3716), AppColors.primaryDark],
          ),
        ),
        child: SafeArea(
          child: Center(
            child: Padding(
              padding: const EdgeInsets.all(30),
              child: Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  Container(
                    width: 92,
                    height: 92,
                    decoration: BoxDecoration(
                      color: const Color(0x1FD9A441),
                      borderRadius: BorderRadius.circular(30),
                      border: Border.all(color: const Color(0x55D9A441)),
                      boxShadow: const [
                        BoxShadow(
                          color: Color(0x33D9A441),
                          blurRadius: 36,
                          spreadRadius: 4,
                        ),
                      ],
                    ),
                    child: Icon(icon, color: AppColors.goldAccent, size: 44),
                  ),
                  const SizedBox(height: 24),
                  Text(
                    title,
                    textAlign: TextAlign.center,
                    style: const TextStyle(
                      color: AppColors.textLight,
                      fontSize: 25,
                      fontWeight: FontWeight.w900,
                    ),
                  ),
                  const SizedBox(height: 9),
                  Text(
                    subtitle,
                    textAlign: TextAlign.center,
                    style: const TextStyle(
                      color: Color(0xFFB8BBC3),
                      fontSize: 14,
                      height: 1.55,
                    ),
                  ),
                  if (loading) ...[
                    const SizedBox(height: 25),
                    const SizedBox(
                      width: 34,
                      child: LinearProgressIndicator(
                        color: AppColors.goldAccent,
                        backgroundColor: Color(0x33FFFFFF),
                        borderRadius: BorderRadius.all(Radius.circular(20)),
                      ),
                    ),
                  ],
                  if (actionLabel != null && onAction != null) ...[
                    const SizedBox(height: 25),
                    FilledButton.icon(
                      onPressed: onAction,
                      icon: const Icon(Icons.arrow_back_rounded),
                      label: Text(actionLabel!),
                    ),
                  ],
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}

class _FeedOverlay extends StatefulWidget {
  const _FeedOverlay({
    required this.video,
    required this.onLike,
    required this.onSave,
    required this.onShare,
    required this.onComments,
    required this.onProducts,
    required this.onOpenProduct,
    required this.onProductCta,
  });

  final FeedVideo video;
  final VoidCallback onLike;
  final VoidCallback onSave;
  final VoidCallback onShare;
  final VoidCallback onComments;
  final VoidCallback onProducts;
  final ValueChanged<StoreProduct> onOpenProduct;
  final ValueChanged<StoreProduct> onProductCta;

  @override
  State<_FeedOverlay> createState() => _FeedOverlayState();
}

class _FeedOverlayState extends State<_FeedOverlay> {
  bool _descExpanded = false;

  @override
  void didUpdateWidget(covariant _FeedOverlay oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.video.id != widget.video.id) {
      _descExpanded = false;
    }
  }

  @override
  Widget build(BuildContext context) {
    final video = widget.video;
    final product = video.primaryProduct;

    return SafeArea(
      child: Padding(
        padding: const EdgeInsets.fromLTRB(14, 12, 12, 104),
        child: Stack(
          fit: StackFit.expand,
          children: [
            Align(
              alignment: Alignment.topCenter,
              child: Row(
                children: [
                  const IgnorePointer(child: _BrandPill()),
                  const Expanded(child: IgnorePointer(child: SizedBox(height: 42))),
                  const IgnorePointer(
                    child: _FeedTabsGroup(),
                  ),
                  const Expanded(child: IgnorePointer(child: SizedBox(height: 42))),
                  const _GlassIconButton(
                    icon: Icons.notifications_none_rounded,
                    onTap: _noop,
                  ),
                ],
              ),
            ),
            Align(
              alignment: Alignment.bottomCenter,
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.end,
                children: [
                  Expanded(
                    child: Column(
                      mainAxisSize: MainAxisSize.min,
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        if (product != null) ...[
                          _FeedProductCard(
                            product: product,
                            onOpen: () => widget.onOpenProduct(product),
                            onCta: product.isAvailable
                                ? () => widget.onProductCta(product)
                                : null,
                          ),
                          const SizedBox(height: 12),
                        ],
                        // Let taps on badge/title pass through to pause/play.
                        const IgnorePointer(
                          child: _FeedCaptionChrome(),
                        ),
                        IgnorePointer(
                          child: Text(
                            video.title,
                            style: const TextStyle(
                              color: AppColors.textLight,
                              fontWeight: FontWeight.w900,
                              fontSize: 20,
                              height: 1.25,
                            ),
                          ),
                        ),
                        if (video.description.isNotEmpty) ...[
                          const SizedBox(height: 7),
                          GestureDetector(
                            behavior: HitTestBehavior.opaque,
                            onTap: () {
                              setState(() => _descExpanded = !_descExpanded);
                            },
                            child: Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                AnimatedSize(
                                  duration: const Duration(milliseconds: 220),
                                  curve: Curves.easeOutCubic,
                                  alignment: Alignment.topRight,
                                  child: Text(
                                    video.description,
                                    maxLines: _descExpanded ? 20 : 2,
                                    overflow: TextOverflow.ellipsis,
                                    style: const TextStyle(
                                      color: Color(0xFFD7D9DE),
                                      fontSize: 13,
                                      height: 1.5,
                                    ),
                                  ),
                                ),
                                if (!_descExpanded &&
                                    video.description.length > 60)
                                  const Padding(
                                    padding: EdgeInsets.only(top: 2),
                                    child: Text(
                                      'المزيد',
                                      style: TextStyle(
                                        color: AppColors.goldAccent,
                                        fontSize: 12,
                                        fontWeight: FontWeight.w700,
                                      ),
                                    ),
                                  ),
                                if (_descExpanded)
                                  const Padding(
                                    padding: EdgeInsets.only(top: 2),
                                    child: Text(
                                      'أقل',
                                      style: TextStyle(
                                        color: AppColors.goldAccent,
                                        fontSize: 12,
                                        fontWeight: FontWeight.w700,
                                      ),
                                    ),
                                  ),
                              ],
                            ),
                          ),
                        ],
                        const SizedBox(height: 13),
                        const IgnorePointer(
                          child: Row(
                            mainAxisSize: MainAxisSize.min,
                            children: [
                              Icon(
                                Icons.keyboard_double_arrow_up_rounded,
                                color: Color(0xFFB8BBC3),
                                size: 18,
                              ),
                              SizedBox(width: 5),
                              Text(
                                'اسحب للأعلى للمزيد',
                                style: TextStyle(
                                  color: Color(0xFFB8BBC3),
                                  fontSize: 11,
                                  fontWeight: FontWeight.w600,
                                ),
                              ),
                            ],
                          ),
                        ),
                      ],
                    ),
                  ),
                  const SizedBox(width: 12),
                  Column(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      _ActionButton(
                        icon: video.likedByMe
                            ? Icons.favorite_rounded
                            : Icons.favorite_border_rounded,
                        label: '${video.likesCount}',
                        color: video.likedByMe
                            ? AppColors.error
                            : AppColors.textLight,
                        onTap: widget.onLike,
                      ),
                      const SizedBox(height: 13),
                      if (video.allowComments) ...[
                        _ActionButton(
                          icon: Icons.mode_comment_outlined,
                          label: '${video.commentsCount}',
                          onTap: widget.onComments,
                        ),
                        const SizedBox(height: 13),
                      ],
                      _ActionButton(
                        icon: Icons.shopping_bag_rounded,
                        label: video.products.length > 1
                            ? '${video.products.length}'
                            : 'تسوّق',
                        emphasized: true,
                        onTap: widget.onProducts,
                      ),
                      const SizedBox(height: 13),
                      if (video.allowSaving) ...[
                        _ActionButton(
                          icon: video.savedByMe
                              ? Icons.bookmark_rounded
                              : Icons.bookmark_border_rounded,
                          label: '${video.savesCount}',
                          onTap: widget.onSave,
                        ),
                        const SizedBox(height: 13),
                      ],
                      if (video.allowSharing)
                        _ActionButton(
                          icon: Icons.ios_share_rounded,
                          label: '${video.sharesCount}',
                          onTap: widget.onShare,
                        ),
                    ],
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _FeedProductCard extends StatelessWidget {
  const _FeedProductCard({
    required this.product,
    required this.onOpen,
    required this.onCta,
  });

  final StoreProduct product;
  final VoidCallback onOpen;
  final VoidCallback? onCta;

  String _fmt(int n) {
    final s = n.toString();
    final buf = StringBuffer();
    for (var i = 0; i < s.length; i++) {
      final fromEnd = s.length - i;
      if (i > 0 && fromEnd % 3 == 0) buf.write(',');
      buf.write(s[i]);
    }
    return buf.toString();
  }

  @override
  Widget build(BuildContext context) {
    final hasSpecial =
        product.specialPrice != null && product.specialPrice != product.price;
    final cta = (product.customCta?.trim().isNotEmpty == true)
        ? product.customCta!.trim()
        : 'أضف للعربة';

    return Material(
      color: Colors.transparent,
      child: InkWell(
        onTap: onOpen,
        borderRadius: BorderRadius.circular(16),
        child: Container(
          padding: const EdgeInsets.all(8),
          decoration: BoxDecoration(
            color: const Color(0xE6121824),
            borderRadius: BorderRadius.circular(16),
            border: Border.all(color: const Color(0x44D9A441)),
            boxShadow: const [
              BoxShadow(
                color: Color(0x66000000),
                blurRadius: 18,
                offset: Offset(0, 6),
              ),
            ],
          ),
          child: Row(
            children: [
              ClipRRect(
                borderRadius: BorderRadius.circular(12),
                child: SizedBox(
                  width: 56,
                  height: 56,
                  child: product.imageUrl.isNotEmpty
                      ? Image.network(
                          product.imageUrl,
                          fit: BoxFit.cover,
                          errorBuilder: (_, __, ___) => const ColoredBox(
                            color: Color(0xFF1F2937),
                            child: Icon(
                              Icons.shopping_bag_outlined,
                              color: AppColors.goldAccent,
                            ),
                          ),
                        )
                      : const ColoredBox(
                          color: Color(0xFF1F2937),
                          child: Icon(
                            Icons.shopping_bag_outlined,
                            color: AppColors.goldAccent,
                          ),
                        ),
                ),
              ),
              const SizedBox(width: 10),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      product.name,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: const TextStyle(
                        color: AppColors.textLight,
                        fontWeight: FontWeight.w800,
                        fontSize: 13,
                      ),
                    ),
                    const SizedBox(height: 4),
                    Row(
                      children: [
                        Text(
                          '${_fmt(product.displayPrice)} د.ع',
                          style: const TextStyle(
                            color: AppColors.goldAccent,
                            fontWeight: FontWeight.w900,
                            fontSize: 13,
                          ),
                        ),
                        if (hasSpecial) ...[
                          const SizedBox(width: 6),
                          Text(
                            '${_fmt(product.price)} د.ع',
                            style: const TextStyle(
                              color: Color(0x99B8BBC3),
                              fontSize: 11,
                              decoration: TextDecoration.lineThrough,
                            ),
                          ),
                        ],
                      ],
                    ),
                  ],
                ),
              ),
              const SizedBox(width: 8),
              FilledButton(
                onPressed: onCta,
                style: FilledButton.styleFrom(
                  backgroundColor: AppColors.goldAccent,
                  foregroundColor: AppColors.primaryDark,
                  disabledBackgroundColor: const Color(0x55D9A441),
                  padding:
                      const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
                  minimumSize: const Size(0, 36),
                  tapTargetSize: MaterialTapTargetSize.shrinkWrap,
                  shape: RoundedRectangleBorder(
                    borderRadius: BorderRadius.circular(12),
                  ),
                ),
                child: Text(
                  cta,
                  style: const TextStyle(
                    fontWeight: FontWeight.w900,
                    fontSize: 12,
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

class _FeedCaptionChrome extends StatelessWidget {
  const _FeedCaptionChrome();

  @override
  Widget build(BuildContext context) {
    return Column(
      mainAxisSize: MainAxisSize.min,
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Container(
          padding: const EdgeInsets.symmetric(
            horizontal: 11,
            vertical: 6,
          ),
          decoration: BoxDecoration(
            color: const Color(0x26D9A441),
            borderRadius: BorderRadius.circular(999),
            border: Border.all(
              color: const Color(0x55D9A441),
            ),
          ),
          child: const Text(
            'FINORA SELECT',
            style: TextStyle(
              color: AppColors.goldAccent,
              fontSize: 10,
              fontWeight: FontWeight.w900,
              letterSpacing: 1.1,
            ),
          ),
        ),
        const SizedBox(height: 11),
      ],
    );
  }
}

class _FeedTabsGroup extends StatelessWidget {
  const _FeedTabsGroup();

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(4),
      decoration: BoxDecoration(
        color: const Color(0x55000000),
        borderRadius: BorderRadius.circular(18),
        border: Border.all(color: const Color(0x26FFFFFF)),
      ),
      child: const Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          _FeedTab(label: 'لك', selected: true),
          _FeedTab(label: 'تتابع', selected: false),
        ],
      ),
    );
  }
}

/// Raw pointer tap catcher that is not delayed by PageView's gesture arena.
class _FeedCenterTapZone extends StatefulWidget {
  const _FeedCenterTapZone({required this.onTap});

  final VoidCallback onTap;

  @override
  State<_FeedCenterTapZone> createState() => _FeedCenterTapZoneState();
}

class _FeedCenterTapZoneState extends State<_FeedCenterTapZone> {
  Offset? _down;
  int? _downMs;

  @override
  Widget build(BuildContext context) {
    return Listener(
      behavior: HitTestBehavior.translucent,
      onPointerDown: (event) {
        _down = event.localPosition;
        _downMs = DateTime.now().millisecondsSinceEpoch;
      },
      onPointerCancel: (_) {
        _down = null;
        _downMs = null;
      },
      onPointerUp: (event) {
        final down = _down;
        final downMs = _downMs;
        _down = null;
        _downMs = null;
        if (down == null || downMs == null) return;
        final moved = (event.localPosition - down).distance;
        final elapsed = DateTime.now().millisecondsSinceEpoch - downMs;
        if (moved > 18 || elapsed > 450) return;
        widget.onTap();
      },
      child: const SizedBox.expand(),
    );
  }
}

void _noop() {}

class _BrandPill extends StatelessWidget {
  const _BrandPill();

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.fromLTRB(11, 7, 9, 7),
      decoration: BoxDecoration(
        color: const Color(0x66000000),
        borderRadius: BorderRadius.circular(18),
        border: Border.all(color: const Color(0x33FFFFFF)),
      ),
      child: const Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(Icons.auto_awesome_rounded,
              color: AppColors.goldAccent, size: 17),
          SizedBox(width: 6),
          Text(
            'Finora',
            style: TextStyle(
              color: AppColors.textLight,
              fontSize: 14,
              fontWeight: FontWeight.w900,
            ),
          ),
        ],
      ),
    );
  }
}

class _FeedTab extends StatelessWidget {
  const _FeedTab({required this.label, required this.selected});

  final String label;
  final bool selected;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 13, vertical: 7),
      decoration: BoxDecoration(
        color: selected ? const Color(0x33D9A441) : Colors.transparent,
        borderRadius: BorderRadius.circular(14),
      ),
      child: Text(
        label,
        style: TextStyle(
          color: selected ? AppColors.textLight : const Color(0xFFB8BBC3),
          fontSize: 12,
          fontWeight: selected ? FontWeight.w900 : FontWeight.w600,
        ),
      ),
    );
  }
}

class _GlassIconButton extends StatelessWidget {
  const _GlassIconButton({required this.icon, required this.onTap});

  final IconData icon;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return InkResponse(
      onTap: onTap,
      radius: 24,
      child: Container(
        width: 42,
        height: 42,
        decoration: BoxDecoration(
          color: const Color(0x66000000),
          shape: BoxShape.circle,
          border: Border.all(color: const Color(0x33FFFFFF)),
        ),
        child: Icon(icon, color: AppColors.textLight, size: 22),
      ),
    );
  }
}

class _ActionButton extends StatelessWidget {
  const _ActionButton({
    required this.icon,
    required this.label,
    required this.onTap,
    this.color = AppColors.textLight,
    this.emphasized = false,
  });

  final IconData icon;
  final String label;
  final VoidCallback onTap;
  final Color color;
  final bool emphasized;

  @override
  Widget build(BuildContext context) {
    return InkResponse(
      onTap: onTap,
      radius: 28,
      child: Column(
        children: [
          Container(
            width: emphasized ? 50 : 46,
            height: emphasized ? 50 : 46,
            decoration: BoxDecoration(
              color:
                  emphasized ? AppColors.goldAccent : const Color(0x66000000),
              shape: BoxShape.circle,
              border: Border.all(
                color: emphasized
                    ? const Color(0x99FFE2A0)
                    : const Color(0x33FFFFFF),
              ),
              boxShadow: emphasized
                  ? const [
                      BoxShadow(
                        color: Color(0x55D9A441),
                        blurRadius: 20,
                        spreadRadius: 2,
                      ),
                    ]
                  : null,
            ),
            child: Icon(
              icon,
              color: emphasized ? AppColors.primaryDark : color,
              size: emphasized ? 28 : 25,
            ),
          ),
          const SizedBox(height: 4),
          Text(
            label,
            style: TextStyle(
              color: emphasized ? AppColors.goldAccent : AppColors.textLight,
              fontSize: 11,
              fontWeight: emphasized ? FontWeight.w900 : FontWeight.w600,
            ),
          ),
        ],
      ),
    );
  }
}
