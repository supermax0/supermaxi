import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api/api_client.dart';
import '../../../core/errors/api_exception.dart';
import '../../authentication/data/auth_controller.dart';

class StoreProduct {
  StoreProduct({
    required this.id,
    required this.name,
    required this.price,
    this.description = '',
    this.oldPrice = 0,
    this.discountPercent = 0,
    this.category = '',
    this.imageUrl = '',
    this.stockStatus = 'متوفر',
    this.isAvailable = true,
    this.favorited = false,
    this.specialPrice,
    this.customCta,
    this.gallery = const [],
    this.specs = const [],
  });

  factory StoreProduct.fromJson(Map<String, dynamic> json) {
    return StoreProduct(
      id: json['id'] as int,
      name: (json['custom_title'] as String?)?.isNotEmpty == true
          ? json['custom_title'] as String
          : ((json['name'] as String?) ?? ''),
      description: (json['description'] as String?) ?? '',
      price: (json['price'] as int?) ?? 0,
      oldPrice: (json['old_price'] as int?) ?? 0,
      discountPercent: (json['discount_percent'] as int?) ?? 0,
      category: (json['category'] as String?) ?? '',
      imageUrl: (json['image_url'] as String?) ?? '',
      stockStatus: (json['stock_status'] as String?) ?? 'متوفر',
      isAvailable: json['is_available'] != false,
      favorited: json['favorited'] == true,
      specialPrice: json['special_price'] as int?,
      customCta: json['custom_cta'] as String?,
      gallery: ((json['gallery'] as List<dynamic>?) ?? [])
          .map((e) => e.toString())
          .where((e) => e.isNotEmpty)
          .toList(),
      specs: ((json['specs'] as List<dynamic>?) ?? [])
          .whereType<Map<String, dynamic>>()
          .toList(),
    );
  }

  final int id;
  final String name;
  final String description;
  final int price;
  final int oldPrice;
  final int discountPercent;
  final String category;
  final String imageUrl;
  final String stockStatus;
  final bool isAvailable;
  final bool favorited;
  final int? specialPrice;
  final String? customCta;
  final List<String> gallery;
  final List<Map<String, dynamic>> specs;

  int get displayPrice => specialPrice ?? price;

  StoreProduct copyWith({bool? favorited}) {
    return StoreProduct(
      id: id,
      name: name,
      description: description,
      price: price,
      oldPrice: oldPrice,
      discountPercent: discountPercent,
      category: category,
      imageUrl: imageUrl,
      stockStatus: stockStatus,
      isAvailable: isAvailable,
      favorited: favorited ?? this.favorited,
      specialPrice: specialPrice,
      customCta: customCta,
      gallery: gallery,
      specs: specs,
    );
  }
}

class StoreState {
  const StoreState({
    this.products = const [],
    this.categories = const [],
    this.favorites = const [],
    this.videoHits = const [],
    this.query = '',
    this.selectedCategory,
    this.isLoading = false,
    this.isLoadingMore = false,
    this.nextOffset = 0,
    this.hasMore = true,
    this.error,
  });

  final List<StoreProduct> products;
  final List<String> categories;
  final List<StoreProduct> favorites;
  final List<Map<String, dynamic>> videoHits;
  final String query;
  final String? selectedCategory;
  final bool isLoading;
  final bool isLoadingMore;
  final int nextOffset;
  final bool hasMore;
  final String? error;

  StoreState copyWith({
    List<StoreProduct>? products,
    List<String>? categories,
    List<StoreProduct>? favorites,
    List<Map<String, dynamic>>? videoHits,
    String? query,
    String? selectedCategory,
    bool? isLoading,
    bool? isLoadingMore,
    int? nextOffset,
    bool? hasMore,
    String? error,
    bool clearCategory = false,
    bool clearError = false,
    bool clearVideos = false,
  }) {
    return StoreState(
      products: products ?? this.products,
      categories: categories ?? this.categories,
      favorites: favorites ?? this.favorites,
      videoHits: clearVideos ? const [] : (videoHits ?? this.videoHits),
      query: query ?? this.query,
      selectedCategory:
          clearCategory ? null : (selectedCategory ?? this.selectedCategory),
      isLoading: isLoading ?? this.isLoading,
      isLoadingMore: isLoadingMore ?? this.isLoadingMore,
      nextOffset: nextOffset ?? this.nextOffset,
      hasMore: hasMore ?? this.hasMore,
      error: clearError ? null : (error ?? this.error),
    );
  }
}

class StoreController extends StateNotifier<StoreState> {
  StoreController(this._api, this._ref) : super(const StoreState());

  final ApiClient _api;
  final Ref _ref;

  Future<void> bootstrap() async {
    state = state.copyWith(isLoading: true, clearError: true);
    try {
      final cats = await _api.get('/api/mobile/v1/categories');
      final categoryNames = ((cats['items'] as List<dynamic>?) ?? [])
          .whereType<Map<String, dynamic>>()
          .map((e) => (e['name'] as String?) ?? '')
          .where((e) => e.isNotEmpty)
          .toList();
      await _loadProducts(
        category: state.selectedCategory,
        q: state.query,
        reset: true,
      );
      var favorites = <StoreProduct>[];
      if (_ref.read(authControllerProvider).isAuthenticated) {
        final fav = await _api.get('/api/mobile/v1/favorites');
        favorites = ((fav['items'] as List<dynamic>?) ?? [])
            .whereType<Map<String, dynamic>>()
            .map(StoreProduct.fromJson)
            .toList();
      }
      state = state.copyWith(
        categories: categoryNames,
        favorites: favorites,
        isLoading: false,
      );
    } on ApiException catch (e) {
      state = state.copyWith(isLoading: false, error: e.message);
    }
  }

  Future<void> _loadProducts({
    String? category,
    String q = '',
    bool reset = false,
  }) async {
    final offset = reset ? 0 : state.nextOffset;
    final path =
        StringBuffer('/api/mobile/v1/products?limit=24&offset=$offset');
    if (q.isNotEmpty) path.write('&q=${Uri.encodeQueryComponent(q)}');
    if (category != null && category.isNotEmpty) {
      path.write('&category=${Uri.encodeQueryComponent(category)}');
    }
    final data = await _api.get(path.toString());
    final products = ((data['items'] as List<dynamic>?) ?? [])
        .whereType<Map<String, dynamic>>()
        .map(StoreProduct.fromJson)
        .toList();
    final merged = reset
        ? products
        : <StoreProduct>[
            ...state.products,
            ...products.where(
              (product) =>
                  !state.products.any((existing) => existing.id == product.id),
            ),
          ];
    state = state.copyWith(
      products: merged,
      nextOffset: (data['next_offset'] as int?) ?? offset + products.length,
      hasMore: data['has_more'] == true,
    );
  }

  Future<void> search(String q) async {
    state = state.copyWith(query: q, isLoading: true, clearError: true);
    try {
      if (q.trim().length < 2) {
        await _loadProducts(
          category: state.selectedCategory,
          q: '',
          reset: true,
        );
        state = state.copyWith(
          isLoading: false,
          clearVideos: true,
        );
        return;
      }
      final data = await _api.get(
        '/api/mobile/v1/search/unified?q=${Uri.encodeQueryComponent(q)}&limit=40',
      );
      final products = ((data['products'] as List<dynamic>?) ?? [])
          .whereType<Map<String, dynamic>>()
          .map(StoreProduct.fromJson)
          .toList();
      final videos = ((data['videos'] as List<dynamic>?) ?? [])
          .whereType<Map<String, dynamic>>()
          .toList();
      state = state.copyWith(
        products: products,
        videoHits: videos,
        isLoading: false,
        hasMore: false,
      );
    } on ApiException catch (e) {
      state = state.copyWith(isLoading: false, error: e.message);
    }
  }

  Future<void> selectCategory(String? category) async {
    state = state.copyWith(
      selectedCategory: category,
      clearCategory: category == null,
      isLoading: true,
    );
    try {
      await _loadProducts(category: category, q: state.query, reset: true);
      state = state.copyWith(isLoading: false);
    } on ApiException catch (e) {
      state = state.copyWith(isLoading: false, error: e.message);
    }
  }

  Future<void> loadMore() async {
    if (state.isLoading || state.isLoadingMore || !state.hasMore) return;
    if (state.query.trim().length >= 2) return;
    state = state.copyWith(isLoadingMore: true, clearError: true);
    try {
      await _loadProducts(
        category: state.selectedCategory,
        q: state.query,
      );
      state = state.copyWith(isLoadingMore: false);
    } on ApiException catch (error) {
      state = state.copyWith(
        isLoadingMore: false,
        error: error.message,
      );
    }
  }

  Future<void> toggleFavorite(int productId) async {
    final current = state.products.where((p) => p.id == productId).toList();
    final wasFav = (current.isNotEmpty && current.first.favorited) ||
        state.favorites.any((f) => f.id == productId);
    try {
      if (wasFav) {
        await _api.delete('/api/mobile/v1/favorites/$productId');
      } else {
        await _api.post('/api/mobile/v1/favorites/$productId');
      }
      final products = state.products
          .map((p) => p.id == productId ? p.copyWith(favorited: !wasFav) : p)
          .toList();
      final favData = await _api.get('/api/mobile/v1/favorites');
      final favorites = ((favData['items'] as List<dynamic>?) ?? [])
          .whereType<Map<String, dynamic>>()
          .map(StoreProduct.fromJson)
          .toList();
      state = state.copyWith(products: products, favorites: favorites);
    } catch (_) {}
  }

  Future<StoreProduct?> fetchDetail(int productId) async {
    final data = await _api.get('/api/mobile/v1/products/$productId');
    final raw = data['product'] as Map<String, dynamic>?;
    if (raw == null) return null;
    return StoreProduct.fromJson(raw);
  }

  Future<List<StoreProduct>> productsForVideo(int videoId) async {
    final data = await _api.get('/api/mobile/v1/videos/$videoId/products');
    return ((data['items'] as List<dynamic>?) ?? [])
        .whereType<Map<String, dynamic>>()
        .map(StoreProduct.fromJson)
        .toList();
  }
}

final storeControllerProvider =
    StateNotifierProvider<StoreController, StoreState>((ref) {
  return StoreController(ref.watch(apiClientProvider), ref);
});
