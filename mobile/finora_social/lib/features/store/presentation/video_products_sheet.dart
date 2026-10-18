import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../core/theme/app_colors.dart';
import '../../authentication/data/auth_controller.dart';
import '../../cart/data/cart_controller.dart';
import '../data/store_controller.dart';

Future<void> showVideoProductsSheet(BuildContext context, int videoId) {
  return showModalBottomSheet<void>(
    context: context,
    backgroundColor: AppColors.surfaceDark,
    shape: const RoundedRectangleBorder(
      borderRadius: BorderRadius.vertical(top: Radius.circular(20)),
    ),
    builder: (_) => VideoProductsSheet(videoId: videoId),
  );
}

class VideoProductsSheet extends ConsumerStatefulWidget {
  const VideoProductsSheet({super.key, required this.videoId});

  final int videoId;

  @override
  ConsumerState<VideoProductsSheet> createState() => _VideoProductsSheetState();
}

class _VideoProductsSheetState extends ConsumerState<VideoProductsSheet> {
  List<StoreProduct> _items = const [];
  bool _loading = true;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    final items = await ref
        .read(storeControllerProvider.notifier)
        .productsForVideo(widget.videoId);
    if (!mounted) return;
    setState(() {
      _items = items;
      _loading = false;
    });
  }

  @override
  Widget build(BuildContext context) {
    return SafeArea(
      child: SizedBox(
        height: 320,
        child: Column(
          children: [
            const SizedBox(height: 10),
            Container(
              width: 42,
              height: 4,
              decoration: BoxDecoration(
                color: Colors.white24,
                borderRadius: BorderRadius.circular(4),
              ),
            ),
            const Padding(
              padding: EdgeInsets.all(16),
              child: Text(
                'منتجات الفيديو',
                style: TextStyle(
                  color: AppColors.textLight,
                  fontWeight: FontWeight.w700,
                  fontSize: 16,
                ),
              ),
            ),
            Expanded(
              child: _loading
                  ? const Center(
                      child: CircularProgressIndicator(
                          color: AppColors.goldAccent),
                    )
                  : _items.isEmpty
                      ? const Center(
                          child: Text(
                            'لا توجد منتجات مرتبطة',
                            style: TextStyle(color: AppColors.textLight),
                          ),
                        )
                      : ListView.builder(
                          itemCount: _items.length,
                          itemBuilder: (context, index) {
                            final p = _items[index];
                            return ListTile(
                              leading: p.imageUrl.isNotEmpty
                                  ? Image.network(p.imageUrl,
                                      width: 48, height: 48, fit: BoxFit.cover)
                                  : const Icon(Icons.shopping_bag_outlined,
                                      color: AppColors.goldAccent),
                              title: Text(p.name,
                                  style: const TextStyle(
                                      color: AppColors.textLight)),
                              subtitle: Text(
                                '${p.displayPrice} د.ع · ${p.stockStatus}',
                                style: const TextStyle(color: Colors.white70),
                              ),
                              trailing: IconButton(
                                icon: const Icon(Icons.add_shopping_cart,
                                    color: AppColors.goldAccent),
                                onPressed: p.isAvailable
                                    ? () async {
                                        if (!ref
                                            .read(authControllerProvider)
                                            .isAuthenticated) {
                                          Navigator.pop(context);
                                          context.push(
                                            '/auth/phone?returnTo=/store/product/${p.id}',
                                          );
                                          return;
                                        }
                                        try {
                                          await ref
                                              .read(cartControllerProvider
                                                  .notifier)
                                              .addProduct(p.id,
                                                  videoId: widget.videoId);
                                          if (!context.mounted) return;
                                          ScaffoldMessenger.of(context)
                                              .showSnackBar(
                                            const SnackBar(
                                                content:
                                                    Text('تمت الإضافة للعربة')),
                                          );
                                        } catch (e) {
                                          if (!context.mounted) return;
                                          ScaffoldMessenger.of(context)
                                              .showSnackBar(
                                            SnackBar(content: Text('$e')),
                                          );
                                        }
                                      }
                                    : null,
                              ),
                              onTap: () {
                                Navigator.pop(context);
                                context.push('/store/product/${p.id}');
                              },
                            );
                          },
                        ),
            ),
          ],
        ),
      ),
    );
  }
}
