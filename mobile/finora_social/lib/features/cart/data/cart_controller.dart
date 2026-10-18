import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api/api_client.dart';
import '../../../core/errors/api_exception.dart';
import '../../notifications/data/notifications_controller.dart';

class CartItem {
  CartItem({
    required this.id,
    required this.productId,
    required this.name,
    required this.quantity,
    required this.unitPrice,
    required this.lineTotal,
    this.imageUrl = '',
    this.stockStatus = '',
    this.isAvailable = true,
    this.availableQty = 0,
    this.videoId,
  });

  factory CartItem.fromJson(Map<String, dynamic> json) {
    return CartItem(
      id: json['id'] as int,
      productId: json['product_id'] as int,
      name: (json['name'] as String?) ?? '',
      quantity: (json['quantity'] as int?) ?? 0,
      unitPrice: (json['unit_price'] as int?) ?? 0,
      lineTotal: (json['line_total'] as int?) ?? 0,
      imageUrl: (json['image_url'] as String?) ?? '',
      stockStatus: (json['stock_status'] as String?) ?? '',
      isAvailable: json['is_available'] != false,
      availableQty: (json['available_qty'] as int?) ?? 0,
      videoId: json['video_id'] as int?,
    );
  }

  final int id;
  final int productId;
  final String name;
  final int quantity;
  final int unitPrice;
  final int lineTotal;
  final String imageUrl;
  final String stockStatus;
  final bool isAvailable;
  final int availableQty;
  final int? videoId;
}

class CartSnapshot {
  CartSnapshot({
    required this.items,
    required this.itemsCount,
    required this.subtotal,
    required this.grandTotal,
    this.discountAmount = 0,
    this.couponDiscount = 0,
    this.pointsDiscount = 0,
    this.couponCode,
    this.pointsToRedeem = 0,
    this.shippingFee = 0,
    this.valid = true,
    this.message = '',
  });

  factory CartSnapshot.fromJson(Map<String, dynamic> json) {
    final rawItems = (json['items'] as List<dynamic>? ?? [])
        .whereType<Map<String, dynamic>>()
        .map(CartItem.fromJson)
        .toList();
    return CartSnapshot(
      items: rawItems,
      itemsCount: (json['items_count'] as int?) ?? 0,
      subtotal: (json['subtotal'] as int?) ?? 0,
      discountAmount: (json['discount_amount'] as int?) ?? 0,
      couponDiscount: (json['coupon_discount'] as int?) ?? 0,
      pointsDiscount: (json['points_discount'] as int?) ?? 0,
      couponCode: json['coupon_code'] as String?,
      pointsToRedeem: (json['points_to_redeem'] as int?) ?? 0,
      shippingFee: (json['shipping_fee'] as int?) ?? 0,
      grandTotal: (json['grand_total'] as int?) ?? 0,
      valid: json['valid'] != false,
      message: (json['message'] as String?) ?? '',
    );
  }

  final List<CartItem> items;
  final int itemsCount;
  final int subtotal;
  final int discountAmount;
  final int couponDiscount;
  final int pointsDiscount;
  final String? couponCode;
  final int pointsToRedeem;
  final int shippingFee;
  final int grandTotal;
  final bool valid;
  final String message;

  static CartSnapshot empty() => CartSnapshot(
        items: const [],
        itemsCount: 0,
        subtotal: 0,
        grandTotal: 0,
      );
}

class MobileOrder {
  MobileOrder({
    required this.id,
    required this.status,
    required this.total,
    this.paymentStatus = '',
    this.createdAt,
    this.videoId,
    this.items = const [],
    this.steps = const [],
    this.customerName = '',
    this.note = '',
  });

  factory MobileOrder.fromJson(Map<String, dynamic> json) {
    return MobileOrder(
      id: json['id'] as int,
      status: (json['status'] as String?) ?? '',
      paymentStatus: (json['payment_status'] as String?) ?? '',
      total: (json['total'] as int?) ?? 0,
      createdAt: json['created_at'] as String?,
      videoId: json['video_id'] as int?,
      customerName: (json['customer_name'] as String?) ?? '',
      note: (json['note'] as String?) ?? '',
      items: ((json['items'] as List<dynamic>?) ?? [])
          .whereType<Map<String, dynamic>>()
          .toList(),
      steps: ((json['steps'] as List<dynamic>?) ?? [])
          .whereType<Map<String, dynamic>>()
          .toList(),
    );
  }

  final int id;
  final String status;
  final String paymentStatus;
  final int total;
  final String? createdAt;
  final int? videoId;
  final String customerName;
  final String note;
  final List<Map<String, dynamic>> items;
  final List<Map<String, dynamic>> steps;
}

class CartState {
  CartState({
    this.cart = const [],
    this.itemsCount = 0,
    this.subtotal = 0,
    this.grandTotal = 0,
    this.discountAmount = 0,
    this.couponCode,
    this.loading = false,
    this.error,
    this.orders = const [],
  });

  final List<CartItem> cart;
  final int itemsCount;
  final int subtotal;
  final int grandTotal;
  final int discountAmount;
  final String? couponCode;
  final bool loading;
  final String? error;
  final List<MobileOrder> orders;

  CartState copyWith({
    List<CartItem>? cart,
    int? itemsCount,
    int? subtotal,
    int? grandTotal,
    int? discountAmount,
    String? couponCode,
    bool? loading,
    String? error,
    List<MobileOrder>? orders,
    bool clearError = false,
    bool clearCoupon = false,
  }) {
    return CartState(
      cart: cart ?? this.cart,
      itemsCount: itemsCount ?? this.itemsCount,
      subtotal: subtotal ?? this.subtotal,
      grandTotal: grandTotal ?? this.grandTotal,
      discountAmount: discountAmount ?? this.discountAmount,
      couponCode: clearCoupon ? null : (couponCode ?? this.couponCode),
      loading: loading ?? this.loading,
      error: clearError ? null : (error ?? this.error),
      orders: orders ?? this.orders,
    );
  }
}

final cartControllerProvider =
    StateNotifierProvider<CartController, CartState>((ref) {
  return CartController(ref.watch(apiClientProvider), ref);
});

class CartController extends StateNotifier<CartState> {
  CartController(this._api, this._ref) : super(CartState());

  final ApiClient _api;
  final Ref _ref;

  AnalyticsTracker get _analytics => _ref.read(analyticsTrackerProvider);

  void _applyCart(Map<String, dynamic> raw) {
    final snap = CartSnapshot.fromJson(raw);
    state = state.copyWith(
      cart: snap.items,
      itemsCount: snap.itemsCount,
      subtotal: snap.subtotal,
      grandTotal: snap.grandTotal,
      discountAmount: snap.discountAmount,
      couponCode: snap.couponCode,
      loading: false,
      clearError: true,
      clearCoupon: snap.couponCode == null || snap.couponCode!.isEmpty,
    );
  }

  Future<void> refresh() async {
    state = state.copyWith(loading: true, clearError: true);
    try {
      final raw = await _api.get('/api/mobile/v1/cart');
      _applyCart(raw);
    } on ApiException catch (e) {
      state = state.copyWith(loading: false, error: e.message);
    }
  }

  Future<void> addProduct(int productId,
      {int quantity = 1, int? videoId}) async {
    try {
      final raw = await _api.post(
        '/api/mobile/v1/cart/items',
        data: {
          'product_id': productId,
          'quantity': quantity,
          if (videoId != null) 'video_id': videoId,
        },
      );
      _applyCart(raw);
      _analytics.track(
        'add_to_cart',
        properties: {
          'product_id': productId,
          if (videoId != null) 'video_id': videoId,
        },
      );
    } on ApiException catch (e) {
      state = state.copyWith(error: e.message);
      rethrow;
    }
  }

  Future<void> updateQuantity(int itemId, int quantity) async {
    final raw = await _api.patch(
      '/api/mobile/v1/cart/items/$itemId',
      data: {'quantity': quantity},
    );
    _applyCart(raw);
  }

  Future<void> removeItem(int itemId) async {
    final raw = await _api.delete('/api/mobile/v1/cart/items/$itemId');
    _applyCart(raw);
  }

  Future<void> applyCoupon(String code) async {
    final raw = await _api.post(
      '/api/mobile/v1/cart/apply-coupon',
      data: {'code': code},
    );
    _applyCart(raw);
  }

  Future<void> removeCoupon() async {
    final raw = await _api.delete('/api/mobile/v1/cart/coupon');
    _applyCart(raw);
  }

  Future<void> applyPoints(int points) async {
    final raw = await _api.post(
      '/api/mobile/v1/cart/apply-points',
      data: {'points': points},
    );
    _applyCart(raw);
  }

  Future<MobileOrder> placeOrder({
    required String customerName,
    required String phone,
    required String city,
    required String address,
    String notes = '',
    int shippingFee = 0,
    int? videoId,
  }) async {
    final raw = await _api.post(
      '/api/mobile/v1/orders',
      data: {
        'customer_name': customerName,
        'phone': phone,
        'city': city,
        'address': address,
        'notes': notes,
        'shipping_fee': shippingFee,
        if (videoId != null) 'video_id': videoId,
      },
    );
    final orderMap = (raw['order'] as Map<String, dynamic>?) ?? {};
    // Normalize to MobileOrder shape from create response
    final order = MobileOrder(
      id: (orderMap['invoice_id'] as int?) ?? 0,
      status: (orderMap['status'] as String?) ?? 'تم الطلب',
      total: (orderMap['grand_total'] as int?) ?? 0,
      videoId: orderMap['attribution_video_id'] as int?,
    );
    _analytics.track(
      'order_placed',
      properties: {
        'order_id': order.id,
        if (order.videoId != null) 'video_id': order.videoId,
      },
    );
    await refresh();
    await loadOrders();
    return order;
  }

  Future<void> loadOrders() async {
    try {
      final raw = await _api.get('/api/mobile/v1/orders');
      final items = ((raw['items'] as List<dynamic>?) ?? [])
          .whereType<Map<String, dynamic>>()
          .map(MobileOrder.fromJson)
          .toList();
      state = state.copyWith(orders: items);
    } on ApiException catch (e) {
      state = state.copyWith(error: e.message);
    }
  }

  Future<MobileOrder?> fetchOrder(int id) async {
    final raw = await _api.get('/api/mobile/v1/orders/$id');
    final order = raw['order'] as Map<String, dynamic>?;
    if (order == null) return null;
    return MobileOrder.fromJson(order);
  }

  Future<void> cancelOrder(int id) async {
    await _api.post('/api/mobile/v1/orders/$id/cancel');
    await loadOrders();
  }
}
