import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../core/theme/app_colors.dart';
import '../../authentication/data/auth_controller.dart';
import '../data/store_controller.dart';

class StorePage extends ConsumerStatefulWidget {
  const StorePage({super.key});

  @override
  ConsumerState<StorePage> createState() => _StorePageState();
}

class _StorePageState extends ConsumerState<StorePage> {
  final _searchCtrl = TextEditingController();
  final _gridController = ScrollController();
  Timer? _searchDebounce;

  @override
  void initState() {
    super.initState();
    _gridController.addListener(_onGridScroll);
    WidgetsBinding.instance.addPostFrameCallback((_) {
      ref.read(storeControllerProvider.notifier).bootstrap();
    });
  }

  @override
  void dispose() {
    _searchDebounce?.cancel();
    _gridController
      ..removeListener(_onGridScroll)
      ..dispose();
    _searchCtrl.dispose();
    super.dispose();
  }

  void _onGridScroll() {
    if (!_gridController.hasClients ||
        _gridController.position.extentAfter > 700) {
      return;
    }
    ref.read(storeControllerProvider.notifier).loadMore();
  }

  void _onSearchChanged(String value) {
    setState(() {});
    _searchDebounce?.cancel();
    final query = value.trim();
    if (query.isNotEmpty && query.length < 2) return;
    _searchDebounce = Timer(const Duration(milliseconds: 380), () {
      if (!mounted) return;
      ref.read(storeControllerProvider.notifier).search(query);
    });
  }

  @override
  Widget build(BuildContext context) {
    final state = ref.watch(storeControllerProvider);
    return Scaffold(
      appBar: AppBar(
        title: const Column(
          children: [
            Text('متجر Finora'),
            Text(
              'اختيارات تستحقها',
              style: TextStyle(fontSize: 11, fontWeight: FontWeight.w500),
            ),
          ],
        ),
        actions: [
          IconButton(
            onPressed: () => context.push('/cart'),
            icon: const Icon(Icons.shopping_cart_outlined),
          ),
          IconButton(
            onPressed: () => context.push('/store/favorites'),
            icon: const Icon(Icons.favorite_border),
          ),
        ],
      ),
      body: Column(
        children: [
          Container(
            margin: const EdgeInsets.fromLTRB(16, 8, 16, 10),
            padding: const EdgeInsets.symmetric(horizontal: 18, vertical: 16),
            decoration: BoxDecoration(
              gradient: const LinearGradient(
                begin: Alignment.topRight,
                end: Alignment.bottomLeft,
                colors: [AppColors.primaryDark, Color(0xFF3A2C16)],
              ),
              borderRadius: BorderRadius.circular(24),
              boxShadow: const [
                BoxShadow(
                  color: Color(0x26000000),
                  blurRadius: 24,
                  offset: Offset(0, 10),
                ),
              ],
            ),
            child: const Row(
              children: [
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        'تسوّق بسهولة',
                        style: TextStyle(
                          color: AppColors.textLight,
                          fontSize: 19,
                          fontWeight: FontWeight.w800,
                        ),
                      ),
                      SizedBox(height: 5),
                      Text(
                        'تصفح الآن، وسجّل فقط عندما تقرر الشراء',
                        style: TextStyle(color: Colors.white70, height: 1.4),
                      ),
                    ],
                  ),
                ),
                SizedBox(width: 12),
                CircleAvatar(
                  radius: 27,
                  backgroundColor: Color(0x22D9A441),
                  child: Icon(
                    Icons.local_mall_rounded,
                    color: AppColors.goldAccent,
                    size: 28,
                  ),
                ),
              ],
            ),
          ),
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 0, 16, 10),
            child: TextField(
              controller: _searchCtrl,
              decoration: InputDecoration(
                hintText: 'ما الذي تبحث عنه؟',
                prefixIcon: const Icon(Icons.search),
                suffixIcon: _searchCtrl.text.isEmpty
                    ? null
                    : IconButton(
                        icon: const Icon(Icons.close_rounded),
                        onPressed: () {
                          _searchCtrl.clear();
                          setState(() {});
                          ref.read(storeControllerProvider.notifier).search('');
                        },
                      ),
              ),
              onChanged: _onSearchChanged,
              textInputAction: TextInputAction.search,
              onSubmitted: (v) =>
                  ref.read(storeControllerProvider.notifier).search(v.trim()),
            ),
          ),
          SizedBox(
            height: 42,
            child: ListView(
              scrollDirection: Axis.horizontal,
              padding: const EdgeInsets.symmetric(horizontal: 12),
              children: [
                Padding(
                  padding: const EdgeInsets.only(left: 8),
                  child: FilterChip(
                    label: const Text('الكل'),
                    selected: state.selectedCategory == null,
                    onSelected: (_) => ref
                        .read(storeControllerProvider.notifier)
                        .selectCategory(null),
                  ),
                ),
                for (final cat in state.categories)
                  Padding(
                    padding: const EdgeInsets.only(left: 8),
                    child: FilterChip(
                      label: Text(cat),
                      selected: state.selectedCategory == cat,
                      onSelected: (_) => ref
                          .read(storeControllerProvider.notifier)
                          .selectCategory(cat),
                    ),
                  ),
              ],
            ),
          ),
          if (state.error != null)
            Padding(
              padding: const EdgeInsets.all(12),
              child: Text(state.error!,
                  style: const TextStyle(color: AppColors.error)),
            ),
          if (state.videoHits.isNotEmpty)
            SizedBox(
              height: 48,
              child: ListView(
                scrollDirection: Axis.horizontal,
                padding: const EdgeInsets.symmetric(horizontal: 12),
                children: [
                  for (final v in state.videoHits)
                    Padding(
                      padding: const EdgeInsets.only(left: 8),
                      child: ActionChip(
                        avatar: const Icon(Icons.play_circle_outline, size: 18),
                        label: Text(
                          ((v['title'] as String?)?.isNotEmpty == true
                                  ? v['title'] as String
                                  : 'فيديو')
                              .toString(),
                          overflow: TextOverflow.ellipsis,
                        ),
                        onPressed: () => context.go('/home'),
                      ),
                    ),
                ],
              ),
            ),
          Expanded(
            child: state.isLoading
                ? const Center(child: CircularProgressIndicator())
                : state.products.isEmpty
                    ? const Center(child: Text('لا توجد منتجات'))
                    : LayoutBuilder(
                        builder: (context, constraints) {
                          final columns = constraints.maxWidth >= 900
                              ? 4
                              : constraints.maxWidth >= 620
                                  ? 3
                                  : 2;
                          return GridView.builder(
                            controller: _gridController,
                            padding: const EdgeInsets.fromLTRB(14, 12, 14, 24),
                            cacheExtent: 900,
                            keyboardDismissBehavior:
                                ScrollViewKeyboardDismissBehavior.onDrag,
                            gridDelegate:
                                SliverGridDelegateWithFixedCrossAxisCount(
                              crossAxisCount: columns,
                              mainAxisSpacing: 14,
                              crossAxisSpacing: 14,
                              childAspectRatio: 0.67,
                            ),
                            itemCount: state.products.length,
                            itemBuilder: (context, index) {
                              final product = state.products[index];
                              return TweenAnimationBuilder<double>(
                                duration: Duration(
                                    milliseconds: 220 + (index % 6) * 45),
                                tween: Tween(begin: 0, end: 1),
                                builder: (context, value, child) => Opacity(
                                  opacity: value,
                                  child: Transform.translate(
                                    offset: Offset(0, 12 * (1 - value)),
                                    child: child,
                                  ),
                                ),
                                child: _ProductCard(
                                  product: product,
                                  onTap: () => context
                                      .push('/store/product/${product.id}'),
                                  onFavorite: () {
                                    if (!ref
                                        .read(authControllerProvider)
                                        .isAuthenticated) {
                                      context
                                          .push('/auth/phone?returnTo=/store');
                                      return;
                                    }
                                    ref
                                        .read(storeControllerProvider.notifier)
                                        .toggleFavorite(product.id);
                                  },
                                ),
                              );
                            },
                          );
                        },
                      ),
          ),
          if (state.isLoadingMore) const LinearProgressIndicator(minHeight: 2),
        ],
      ),
    );
  }
}

class _ProductCard extends StatelessWidget {
  const _ProductCard({
    required this.product,
    required this.onTap,
    required this.onFavorite,
  });

  final StoreProduct product;
  final VoidCallback onTap;
  final VoidCallback onFavorite;

  @override
  Widget build(BuildContext context) {
    return InkWell(
      onTap: onTap,
      borderRadius: BorderRadius.circular(16),
      child: Ink(
        decoration: BoxDecoration(
          color: Theme.of(context).colorScheme.surface,
          borderRadius: BorderRadius.circular(22),
          border: Border.all(
            color: Theme.of(context).colorScheme.outlineVariant,
          ),
          boxShadow: const [
            BoxShadow(
                color: Color(0x10000000), blurRadius: 18, offset: Offset(0, 8)),
          ],
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Expanded(
              child: Stack(
                children: [
                  Positioned.fill(
                    child: ClipRRect(
                      borderRadius:
                          const BorderRadius.vertical(top: Radius.circular(22)),
                      child: product.imageUrl.isNotEmpty
                          ? Hero(
                              tag: 'product-${product.id}',
                              child: Image.network(product.imageUrl,
                                  fit: BoxFit.cover,
                                  errorBuilder: (_, __, ___) => Container(
                                        color: Theme.of(context)
                                            .colorScheme
                                            .surfaceVariant,
                                        child: const Icon(
                                          Icons.broken_image_outlined,
                                          size: 40,
                                        ),
                                      )),
                            )
                          : Container(
                              color: Colors.black12,
                              child: const Icon(Icons.image_outlined, size: 40),
                            ),
                    ),
                  ),
                  Positioned(
                    top: 8,
                    left: 8,
                    child: IconButton.filledTonal(
                      onPressed: onFavorite,
                      icon: Icon(
                        product.favorited
                            ? Icons.favorite
                            : Icons.favorite_border,
                        color: product.favorited ? AppColors.error : null,
                      ),
                    ),
                  ),
                  if (product.discountPercent > 0)
                    Positioned(
                      top: 10,
                      right: 10,
                      child: Container(
                        padding: const EdgeInsets.symmetric(
                            horizontal: 8, vertical: 5),
                        decoration: BoxDecoration(
                          color: AppColors.primaryDark,
                          borderRadius: BorderRadius.circular(10),
                        ),
                        child: Text(
                          '-${product.discountPercent}%',
                          style: const TextStyle(
                            color: AppColors.goldAccent,
                            fontSize: 11,
                            fontWeight: FontWeight.w800,
                          ),
                        ),
                      ),
                    ),
                ],
              ),
            ),
            Padding(
              padding: const EdgeInsets.all(10),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    product.name,
                    maxLines: 2,
                    overflow: TextOverflow.ellipsis,
                    style: const TextStyle(fontWeight: FontWeight.w600),
                  ),
                  const SizedBox(height: 4),
                  Text(
                    '${_money(product.displayPrice)} د.ع',
                    style: const TextStyle(
                      color: AppColors.mutedGold,
                      fontWeight: FontWeight.w700,
                    ),
                  ),
                  if (product.oldPrice > product.displayPrice)
                    Text(
                      '${_money(product.oldPrice)} د.ع',
                      style: TextStyle(
                        fontSize: 11,
                        color: Theme.of(context).colorScheme.onSurfaceVariant,
                        decoration: TextDecoration.lineThrough,
                      ),
                    ),
                  Text(
                    product.stockStatus,
                    style: TextStyle(
                      fontSize: 12,
                      color: product.isAvailable
                          ? AppColors.success
                          : AppColors.error,
                    ),
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

String _money(int value) {
  final s = value.toString();
  final buf = StringBuffer();
  for (var i = 0; i < s.length; i++) {
    buf.write(s[i]);
    final left = s.length - i - 1;
    if (left > 0 && left % 3 == 0) buf.write(',');
  }
  return buf.toString();
}
