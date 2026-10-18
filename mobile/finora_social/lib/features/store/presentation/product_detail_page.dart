import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:share_plus/share_plus.dart';

import '../../../core/theme/app_colors.dart';
import '../../authentication/data/auth_controller.dart';
import '../../cart/data/cart_controller.dart';
import '../data/store_controller.dart';

class ProductDetailPage extends ConsumerStatefulWidget {
  const ProductDetailPage({super.key, required this.productId});

  final int productId;

  @override
  ConsumerState<ProductDetailPage> createState() => _ProductDetailPageState();
}

class _ProductDetailPageState extends ConsumerState<ProductDetailPage> {
  final _galleryController = PageController();
  StoreProduct? _product;
  String? _error;
  bool _loading = true;
  bool _adding = false;
  int _galleryIndex = 0;
  int _quantity = 1;

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void dispose() {
    _galleryController.dispose();
    super.dispose();
  }

  Future<void> _load() async {
    if (mounted) {
      setState(() {
        _loading = true;
        _error = null;
      });
    }
    try {
      final product = await ref
          .read(storeControllerProvider.notifier)
          .fetchDetail(widget.productId);
      if (!mounted) return;
      setState(() {
        _product = product;
        _loading = false;
        if (product == null) _error = 'المنتج غير موجود';
      });
    } catch (error) {
      if (!mounted) return;
      setState(() {
        _loading = false;
        _error = '$error';
      });
    }
  }

  Future<void> _toggleFavorite() async {
    final product = _product;
    if (product == null) return;
    if (!ref.read(authControllerProvider).isAuthenticated) {
      context.push('/auth/phone?returnTo=/store/product/${product.id}');
      return;
    }
    setState(() => _product = product.copyWith(favorited: !product.favorited));
    HapticFeedback.selectionClick();
    await ref.read(storeControllerProvider.notifier).toggleFavorite(product.id);
    try {
      final fresh = await ref
          .read(storeControllerProvider.notifier)
          .fetchDetail(product.id);
      if (mounted && fresh != null) setState(() => _product = fresh);
    } catch (_) {}
  }

  Future<void> _addToCart() async {
    final product = _product;
    if (product == null || !product.isAvailable || _adding) return;
    if (!ref.read(authControllerProvider).isAuthenticated) {
      context.push('/auth/phone?returnTo=/store/product/${product.id}');
      return;
    }
    setState(() => _adding = true);
    try {
      await ref
          .read(cartControllerProvider.notifier)
          .addProduct(product.id, quantity: _quantity);
      if (!mounted) return;
      HapticFeedback.mediumImpact();
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text('تمت إضافة $_quantity من ${product.name}'),
          action: SnackBarAction(
            label: 'عرض العربة',
            onPressed: () => context.push('/cart'),
          ),
        ),
      );
    } catch (error) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('$error')),
        );
      }
    } finally {
      if (mounted) setState(() => _adding = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    if (_loading) return const _ProductDetailSkeleton();
    if (_error != null || _product == null) {
      return Scaffold(
        appBar: AppBar(),
        body: _ProductError(message: _error ?? 'حدث خطأ', onRetry: _load),
      );
    }

    final product = _product!;
    final colors = Theme.of(context).colorScheme;
    final images = <String>{
      if (product.imageUrl.isNotEmpty) product.imageUrl,
      ...product.gallery.where((url) => url.isNotEmpty),
    }.toList();

    return Scaffold(
      body: CustomScrollView(
        slivers: [
          SliverAppBar(
            pinned: true,
            title: Text(
              product.name,
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
            ),
            actions: [
              IconButton(
                tooltip: 'مشاركة',
                onPressed: () => Share.share(
                  '${product.name}\n${_fmt(product.displayPrice)} د.ع',
                  subject: product.name,
                ),
                icon: const Icon(Icons.ios_share_rounded),
              ),
              IconButton(
                tooltip:
                    product.favorited ? 'إزالة من المفضلة' : 'حفظ في المفضلة',
                onPressed: _toggleFavorite,
                icon: AnimatedSwitcher(
                  duration: const Duration(milliseconds: 180),
                  transitionBuilder: (child, animation) =>
                      ScaleTransition(scale: animation, child: child),
                  child: Icon(
                    product.favorited
                        ? Icons.favorite_rounded
                        : Icons.favorite_border_rounded,
                    key: ValueKey(product.favorited),
                    color: product.favorited ? AppColors.error : null,
                  ),
                ),
              ),
              const SizedBox(width: 4),
            ],
          ),
          SliverToBoxAdapter(
            child: Stack(
              children: [
                AspectRatio(
                  aspectRatio: 1,
                  child: images.isEmpty
                      ? ColoredBox(
                          color: colors.surfaceVariant,
                          child: const Icon(Icons.image_outlined, size: 70),
                        )
                      : PageView.builder(
                          controller: _galleryController,
                          itemCount: images.length,
                          onPageChanged: (index) =>
                              setState(() => _galleryIndex = index),
                          itemBuilder: (context, index) {
                            final image = Image.network(
                              images[index],
                              fit: BoxFit.cover,
                              width: double.infinity,
                              errorBuilder: (_, __, ___) => ColoredBox(
                                color: colors.surfaceVariant,
                                child: const Icon(
                                  Icons.broken_image_outlined,
                                  size: 58,
                                ),
                              ),
                            );
                            if (index != 0) return image;
                            return Hero(
                              tag: 'product-${product.id}',
                              child: image,
                            );
                          },
                        ),
                ),
                if (product.discountPercent > 0)
                  PositionedDirectional(
                    top: 16,
                    start: 16,
                    child: _OfferBadge(
                      label: 'خصم ${product.discountPercent}%',
                    ),
                  ),
                if (images.length > 1)
                  Positioned(
                    right: 0,
                    left: 0,
                    bottom: 14,
                    child: Row(
                      mainAxisAlignment: MainAxisAlignment.center,
                      children: [
                        for (var index = 0; index < images.length; index++)
                          AnimatedContainer(
                            duration: const Duration(milliseconds: 180),
                            width: index == _galleryIndex ? 24 : 7,
                            height: 7,
                            margin: const EdgeInsets.symmetric(horizontal: 3),
                            decoration: BoxDecoration(
                              color: index == _galleryIndex
                                  ? AppColors.goldAccent
                                  : Colors.white70,
                              borderRadius: BorderRadius.circular(99),
                              boxShadow: const [
                                BoxShadow(
                                  color: Colors.black26,
                                  blurRadius: 4,
                                ),
                              ],
                            ),
                          ),
                      ],
                    ),
                  ),
              ],
            ),
          ),
          SliverPadding(
            padding: const EdgeInsets.fromLTRB(18, 20, 18, 32),
            sliver: SliverList.list(
              children: [
                if (product.category.isNotEmpty)
                  Text(
                    product.category,
                    style: const TextStyle(
                      color: AppColors.mutedGold,
                      fontWeight: FontWeight.w800,
                    ),
                  ),
                const SizedBox(height: 5),
                Text(
                  product.name,
                  style: Theme.of(context).textTheme.headlineSmall,
                ),
                const SizedBox(height: 12),
                Wrap(
                  spacing: 10,
                  runSpacing: 8,
                  crossAxisAlignment: WrapCrossAlignment.center,
                  children: [
                    Text(
                      '${_fmt(product.displayPrice)} د.ع',
                      style: const TextStyle(
                        fontSize: 25,
                        fontWeight: FontWeight.w900,
                        color: AppColors.mutedGold,
                      ),
                    ),
                    if (product.oldPrice > product.displayPrice)
                      Text(
                        '${_fmt(product.oldPrice)} د.ع',
                        style: TextStyle(
                          decoration: TextDecoration.lineThrough,
                          color: colors.onSurfaceVariant,
                          fontSize: 15,
                        ),
                      ),
                  ],
                ),
                const SizedBox(height: 14),
                _StockCard(product: product),
                if (product.description.isNotEmpty) ...[
                  const SizedBox(height: 26),
                  const _SectionTitle(
                    icon: Icons.notes_rounded,
                    title: 'عن المنتج',
                  ),
                  const SizedBox(height: 10),
                  Text(
                    product.description,
                    style: Theme.of(context).textTheme.bodyLarge?.copyWith(
                          color: colors.onSurfaceVariant,
                        ),
                  ),
                ],
                if (product.specs.isNotEmpty) ...[
                  const SizedBox(height: 26),
                  const _SectionTitle(
                    icon: Icons.tune_rounded,
                    title: 'المواصفات',
                  ),
                  const SizedBox(height: 12),
                  Container(
                    clipBehavior: Clip.antiAlias,
                    decoration: BoxDecoration(
                      color: colors.surface,
                      borderRadius: BorderRadius.circular(20),
                      border: Border.all(color: colors.outlineVariant),
                    ),
                    child: Column(
                      children: [
                        for (var index = 0;
                            index < product.specs.length;
                            index++) ...[
                          _SpecRow(spec: product.specs[index]),
                          if (index < product.specs.length - 1)
                            Divider(color: colors.outlineVariant),
                        ],
                      ],
                    ),
                  ),
                ],
                const SizedBox(height: 20),
                _TrustStrip(),
              ],
            ),
          ),
        ],
      ),
      bottomNavigationBar: _PurchaseBar(
        product: product,
        quantity: _quantity,
        isAdding: _adding,
        onDecrease: _quantity > 1 ? () => setState(() => _quantity--) : null,
        onIncrease: () => setState(() => _quantity++),
        onAdd: _addToCart,
      ),
    );
  }
}

class _ProductDetailSkeleton extends StatelessWidget {
  const _ProductDetailSkeleton();

  @override
  Widget build(BuildContext context) {
    final color = Theme.of(context).colorScheme.surfaceVariant;
    return Scaffold(
      appBar: AppBar(),
      body: ListView(
        children: [
          AspectRatio(aspectRatio: 1, child: ColoredBox(color: color)),
          Padding(
            padding: const EdgeInsets.all(20),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Container(width: 90, height: 14, color: color),
                const SizedBox(height: 12),
                Container(width: double.infinity, height: 26, color: color),
                const SizedBox(height: 14),
                Container(width: 150, height: 24, color: color),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class _ProductError extends StatelessWidget {
  const _ProductError({required this.message, required this.onRetry});

  final String message;
  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(28),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Icon(Icons.inventory_2_outlined, size: 62),
            const SizedBox(height: 16),
            Text(message, textAlign: TextAlign.center),
            const SizedBox(height: 16),
            FilledButton.tonalIcon(
              onPressed: onRetry,
              icon: const Icon(Icons.refresh_rounded),
              label: const Text('إعادة المحاولة'),
            ),
          ],
        ),
      ),
    );
  }
}

class _OfferBadge extends StatelessWidget {
  const _OfferBadge({required this.label});

  final String label;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 11, vertical: 7),
      decoration: BoxDecoration(
        color: AppColors.primaryDark,
        borderRadius: BorderRadius.circular(12),
        boxShadow: const [BoxShadow(color: Colors.black26, blurRadius: 10)],
      ),
      child: Text(
        label,
        style: const TextStyle(
          color: AppColors.goldAccent,
          fontWeight: FontWeight.w900,
        ),
      ),
    );
  }
}

class _StockCard extends StatelessWidget {
  const _StockCard({required this.product});

  final StoreProduct product;

  @override
  Widget build(BuildContext context) {
    final color = product.isAvailable ? AppColors.success : AppColors.error;
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
      decoration: BoxDecoration(
        color: color.withOpacity(0.1),
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: color.withOpacity(0.22)),
      ),
      child: Row(
        children: [
          Icon(
            product.isAvailable
                ? Icons.check_circle_rounded
                : Icons.cancel_rounded,
            color: color,
          ),
          const SizedBox(width: 10),
          Expanded(
            child: Text(
              product.stockStatus,
              style: TextStyle(color: color, fontWeight: FontWeight.w800),
            ),
          ),
          if (product.isAvailable)
            Text(
              'جاهز للطلب',
              style: TextStyle(color: color.withOpacity(0.9), fontSize: 12),
            ),
        ],
      ),
    );
  }
}

class _SectionTitle extends StatelessWidget {
  const _SectionTitle({required this.icon, required this.title});

  final IconData icon;
  final String title;

  @override
  Widget build(BuildContext context) {
    return Row(
      children: [
        Icon(icon, color: AppColors.mutedGold, size: 21),
        const SizedBox(width: 8),
        Text(
          title,
          style: Theme.of(context).textTheme.titleMedium?.copyWith(
                fontWeight: FontWeight.w900,
              ),
        ),
      ],
    );
  }
}

class _SpecRow extends StatelessWidget {
  const _SpecRow({required this.spec});

  final Map<String, dynamic> spec;

  @override
  Widget build(BuildContext context) {
    final label = '${spec['label'] ?? spec['name'] ?? ''}'.trim();
    final value = '${spec['value'] ?? ''}'.trim();
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
      child: Row(
        children: [
          Expanded(
            child: Text(
              label,
              style: TextStyle(
                color: Theme.of(context).colorScheme.onSurfaceVariant,
              ),
            ),
          ),
          const SizedBox(width: 16),
          Expanded(
            child: Text(
              value,
              textAlign: TextAlign.end,
              style: const TextStyle(fontWeight: FontWeight.w800),
            ),
          ),
        ],
      ),
    );
  }
}

class _TrustStrip extends StatelessWidget {
  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 14),
      decoration: BoxDecoration(
        color: colors.surface,
        borderRadius: BorderRadius.circular(18),
        border: Border.all(color: colors.outlineVariant),
      ),
      child: const Row(
        children: [
          Expanded(
              child: _TrustItem(icon: Icons.verified_user, label: 'شراء آمن')),
          Expanded(
              child:
                  _TrustItem(icon: Icons.local_shipping, label: 'توصيل سريع')),
          Expanded(
              child: _TrustItem(icon: Icons.support_agent, label: 'دعم مباشر')),
        ],
      ),
    );
  }
}

class _TrustItem extends StatelessWidget {
  const _TrustItem({required this.icon, required this.label});

  final IconData icon;
  final String label;

  @override
  Widget build(BuildContext context) {
    return Column(
      children: [
        Icon(icon, color: AppColors.mutedGold, size: 21),
        const SizedBox(height: 5),
        Text(
          label,
          textAlign: TextAlign.center,
          style: const TextStyle(fontSize: 11, fontWeight: FontWeight.w700),
        ),
      ],
    );
  }
}

class _PurchaseBar extends StatelessWidget {
  const _PurchaseBar({
    required this.product,
    required this.quantity,
    required this.isAdding,
    required this.onDecrease,
    required this.onIncrease,
    required this.onAdd,
  });

  final StoreProduct product;
  final int quantity;
  final bool isAdding;
  final VoidCallback? onDecrease;
  final VoidCallback onIncrease;
  final VoidCallback onAdd;

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
          boxShadow: const [
            BoxShadow(
              color: Color(0x18000000),
              blurRadius: 20,
              offset: Offset(0, -8),
            ),
          ],
        ),
        child: Row(
          children: [
            Container(
              height: 52,
              decoration: BoxDecoration(
                color: colors.surfaceVariant,
                borderRadius: BorderRadius.circular(17),
              ),
              child: Row(
                children: [
                  IconButton(
                    onPressed: onDecrease,
                    icon: const Icon(Icons.remove_rounded),
                  ),
                  Text(
                    '$quantity',
                    style: const TextStyle(
                      fontWeight: FontWeight.w900,
                      fontSize: 16,
                    ),
                  ),
                  IconButton(
                    onPressed: onIncrease,
                    icon: const Icon(Icons.add_rounded),
                  ),
                ],
              ),
            ),
            const SizedBox(width: 10),
            Expanded(
              child: FilledButton.icon(
                onPressed: product.isAvailable && !isAdding ? onAdd : null,
                icon: isAdding
                    ? const SizedBox(
                        width: 18,
                        height: 18,
                        child: CircularProgressIndicator(strokeWidth: 2),
                      )
                    : const Icon(Icons.add_shopping_cart_rounded),
                label: Text(
                  product.isAvailable
                      ? (product.customCta ?? 'أضف للعربة')
                      : 'غير متوفر حالياً',
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class FavoritesPage extends ConsumerWidget {
  const FavoritesPage({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final favs = ref.watch(storeControllerProvider).favorites;
    return Scaffold(
      appBar: AppBar(title: const Text('المفضلة')),
      body: favs.isEmpty
          ? const Center(child: Text('لا توجد منتجات محفوظة'))
          : ListView.separated(
              padding: const EdgeInsets.all(12),
              itemCount: favs.length,
              separatorBuilder: (_, __) => const SizedBox(height: 8),
              itemBuilder: (context, index) {
                final product = favs[index];
                return Card(
                  child: ListTile(
                    contentPadding: const EdgeInsets.all(8),
                    leading: ClipRRect(
                      borderRadius: BorderRadius.circular(12),
                      child: product.imageUrl.isNotEmpty
                          ? Image.network(
                              product.imageUrl,
                              width: 62,
                              height: 62,
                              fit: BoxFit.cover,
                              errorBuilder: (_, __, ___) => const SizedBox(
                                width: 62,
                                height: 62,
                                child: Icon(Icons.image_outlined),
                              ),
                            )
                          : const SizedBox(
                              width: 62,
                              height: 62,
                              child: Icon(Icons.image_outlined),
                            ),
                    ),
                    title: Text(
                      product.name,
                      maxLines: 2,
                      overflow: TextOverflow.ellipsis,
                      style: const TextStyle(fontWeight: FontWeight.w800),
                    ),
                    subtitle: Text(
                      '${_fmt(product.displayPrice)} د.ع',
                      style: const TextStyle(color: AppColors.mutedGold),
                    ),
                    trailing: const Icon(Icons.chevron_left_rounded),
                    onTap: () => context.push('/store/product/${product.id}'),
                  ),
                );
              },
            ),
    );
  }
}

String _fmt(int value) {
  final source = value.toString();
  final buffer = StringBuffer();
  for (var index = 0; index < source.length; index++) {
    buffer.write(source[index]);
    final left = source.length - index - 1;
    if (left > 0 && left % 3 == 0) buffer.write(',');
  }
  return buffer.toString();
}
