import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../core/theme/app_colors.dart';
import '../../authentication/data/auth_controller.dart';
import '../data/cart_controller.dart';

String fmtMoney(int value) {
  final s = value.toString();
  final buf = StringBuffer();
  for (var i = 0; i < s.length; i++) {
    buf.write(s[i]);
    final left = s.length - i - 1;
    if (left > 0 && left % 3 == 0) buf.write(',');
  }
  return buf.toString();
}

class CartPage extends ConsumerStatefulWidget {
  const CartPage({super.key});

  @override
  ConsumerState<CartPage> createState() => _CartPageState();
}

class _CartPageState extends ConsumerState<CartPage> {
  final _couponCtrl = TextEditingController();

  @override
  void initState() {
    super.initState();
    Future.microtask(() => ref.read(cartControllerProvider.notifier).refresh());
  }

  @override
  void dispose() {
    _couponCtrl.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final state = ref.watch(cartControllerProvider);
    return Scaffold(
      appBar: AppBar(title: const Text('العربة')),
      body: state.loading && state.cart.isEmpty
          ? const Center(child: CircularProgressIndicator())
          : state.cart.isEmpty
              ? const Center(child: Text('العربة فارغة'))
              : Column(
                  children: [
                    if (state.error != null)
                      MaterialBanner(
                        content: Text(state.error!),
                        actions: [
                          TextButton(
                            onPressed: () => ref
                                .read(cartControllerProvider.notifier)
                                .refresh(),
                            child: const Text('إعادة'),
                          ),
                        ],
                      ),
                    Expanded(
                      child: ListView.separated(
                        itemCount: state.cart.length,
                        separatorBuilder: (_, __) => const Divider(height: 1),
                        itemBuilder: (context, index) {
                          final item = state.cart[index];
                          return ListTile(
                            leading: item.imageUrl.isNotEmpty
                                ? Image.network(
                                    item.imageUrl,
                                    width: 52,
                                    height: 52,
                                    fit: BoxFit.cover,
                                  )
                                : const Icon(Icons.shopping_bag_outlined),
                            title: Text(item.name),
                            subtitle: Text(
                              '${fmtMoney(item.unitPrice)} د.ع · ${item.stockStatus}',
                            ),
                            trailing: Row(
                              mainAxisSize: MainAxisSize.min,
                              children: [
                                IconButton(
                                  onPressed: () async {
                                    try {
                                      await ref
                                          .read(cartControllerProvider.notifier)
                                          .updateQuantity(
                                            item.id,
                                            item.quantity - 1,
                                          );
                                    } catch (e) {
                                      if (context.mounted) {
                                        ScaffoldMessenger.of(context)
                                            .showSnackBar(
                                          SnackBar(content: Text('$e')),
                                        );
                                      }
                                    }
                                  },
                                  icon: const Icon(Icons.remove_circle_outline),
                                ),
                                Text('${item.quantity}'),
                                IconButton(
                                  onPressed: () async {
                                    try {
                                      await ref
                                          .read(cartControllerProvider.notifier)
                                          .updateQuantity(
                                            item.id,
                                            item.quantity + 1,
                                          );
                                    } catch (e) {
                                      if (context.mounted) {
                                        ScaffoldMessenger.of(context)
                                            .showSnackBar(
                                          SnackBar(content: Text('$e')),
                                        );
                                      }
                                    }
                                  },
                                  icon: const Icon(Icons.add_circle_outline),
                                ),
                              ],
                            ),
                          );
                        },
                      ),
                    ),
                    SafeArea(
                      child: Padding(
                        padding: const EdgeInsets.all(16),
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.stretch,
                          children: [
                            Row(
                              children: [
                                Expanded(
                                  child: TextField(
                                    controller: _couponCtrl,
                                    decoration: const InputDecoration(
                                      hintText: 'كود الخصم',
                                      isDense: true,
                                    ),
                                  ),
                                ),
                                const SizedBox(width: 8),
                                OutlinedButton(
                                  onPressed: () async {
                                    try {
                                      await ref
                                          .read(cartControllerProvider.notifier)
                                          .applyCoupon(_couponCtrl.text.trim());
                                    } catch (e) {
                                      if (context.mounted) {
                                        ScaffoldMessenger.of(context)
                                            .showSnackBar(
                                          SnackBar(content: Text('$e')),
                                        );
                                      }
                                    }
                                  },
                                  child: const Text('تطبيق'),
                                ),
                              ],
                            ),
                            if (state.couponCode != null &&
                                state.couponCode!.isNotEmpty)
                              TextButton(
                                onPressed: () => ref
                                    .read(cartControllerProvider.notifier)
                                    .removeCoupon(),
                                child:
                                    Text('إزالة الكوبون ${state.couponCode}'),
                              ),
                            if (state.discountAmount > 0)
                              Text(
                                'الخصم: ${fmtMoney(state.discountAmount)} د.ع',
                                textAlign: TextAlign.center,
                              ),
                            Text(
                              'الإجمالي: ${fmtMoney(state.grandTotal)} د.ع',
                              textAlign: TextAlign.center,
                              style: const TextStyle(
                                fontSize: 18,
                                fontWeight: FontWeight.w700,
                                color: AppColors.mutedGold,
                              ),
                            ),
                            const SizedBox(height: 12),
                            FilledButton(
                              onPressed: () => context.push('/cart/checkout'),
                              child: const Text('إتمام الطلب'),
                            ),
                          ],
                        ),
                      ),
                    ),
                  ],
                ),
    );
  }
}

class CheckoutPage extends ConsumerStatefulWidget {
  const CheckoutPage({super.key});

  @override
  ConsumerState<CheckoutPage> createState() => _CheckoutPageState();
}

class _CheckoutPageState extends ConsumerState<CheckoutPage> {
  final _name = TextEditingController();
  final _phone = TextEditingController();
  final _city = TextEditingController();
  final _address = TextEditingController();
  final _notes = TextEditingController();
  bool _submitting = false;

  @override
  void initState() {
    super.initState();
    final user = ref.read(authControllerProvider).user;
    if (user != null) {
      _name.text = user.name;
      _phone.text = user.phone;
    }
  }

  @override
  void dispose() {
    _name.dispose();
    _phone.dispose();
    _city.dispose();
    _address.dispose();
    _notes.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    setState(() => _submitting = true);
    try {
      final order = await ref.read(cartControllerProvider.notifier).placeOrder(
            customerName: _name.text.trim(),
            phone: _phone.text.trim(),
            city: _city.text.trim(),
            address: _address.text.trim(),
            notes: _notes.text.trim(),
          );
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('تم إنشاء الطلب #${order.id}')),
      );
      context.go('/profile/orders/${order.id}');
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('$e')));
    } finally {
      if (mounted) setState(() => _submitting = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final cart = ref.watch(cartControllerProvider);
    return Scaffold(
      appBar: AppBar(title: const Text('إتمام الطلب')),
      body: ListView(
        padding: const EdgeInsets.all(20),
        children: [
          Text(
            'المبلغ: ${fmtMoney(cart.grandTotal)} د.ع',
            style: const TextStyle(
              fontWeight: FontWeight.w700,
              color: AppColors.mutedGold,
              fontSize: 18,
            ),
          ),
          const SizedBox(height: 16),
          TextField(
            controller: _name,
            decoration: const InputDecoration(labelText: 'الاسم الكامل'),
          ),
          TextField(
            controller: _phone,
            keyboardType: TextInputType.phone,
            decoration: const InputDecoration(labelText: 'رقم الهاتف'),
          ),
          TextField(
            controller: _city,
            decoration: const InputDecoration(labelText: 'المحافظة'),
          ),
          TextField(
            controller: _address,
            decoration: const InputDecoration(labelText: 'العنوان'),
            maxLines: 2,
          ),
          TextField(
            controller: _notes,
            decoration: const InputDecoration(labelText: 'ملاحظات (اختياري)'),
            maxLines: 2,
          ),
          const SizedBox(height: 24),
          FilledButton(
            onPressed: _submitting ? null : _submit,
            child: _submitting
                ? const SizedBox(
                    height: 20,
                    width: 20,
                    child: CircularProgressIndicator(strokeWidth: 2),
                  )
                : const Text('تأكيد الطلب (COD)'),
          ),
        ],
      ),
    );
  }
}

class OrdersListPage extends ConsumerStatefulWidget {
  const OrdersListPage({super.key});

  @override
  ConsumerState<OrdersListPage> createState() => _OrdersListPageState();
}

class _OrdersListPageState extends ConsumerState<OrdersListPage> {
  @override
  void initState() {
    super.initState();
    Future.microtask(
        () => ref.read(cartControllerProvider.notifier).loadOrders());
  }

  @override
  Widget build(BuildContext context) {
    final orders = ref.watch(cartControllerProvider).orders;
    return Scaffold(
      appBar: AppBar(title: const Text('طلباتي')),
      body: orders.isEmpty
          ? const Center(child: Text('لا توجد طلبات بعد'))
          : ListView.separated(
              itemCount: orders.length,
              separatorBuilder: (_, __) => const Divider(height: 1),
              itemBuilder: (context, index) {
                final o = orders[index];
                return ListTile(
                  title: Text('طلب #${o.id}'),
                  subtitle: Text('${o.status} · ${fmtMoney(o.total)} د.ع'),
                  trailing: const Icon(Icons.chevron_left),
                  onTap: () => context.push('/profile/orders/${o.id}'),
                );
              },
            ),
    );
  }
}

class OrderDetailPage extends ConsumerStatefulWidget {
  const OrderDetailPage({super.key, required this.orderId});

  final int orderId;

  @override
  ConsumerState<OrderDetailPage> createState() => _OrderDetailPageState();
}

class _OrderDetailPageState extends ConsumerState<OrderDetailPage> {
  MobileOrder? _order;
  String? _error;
  bool _loading = true;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final order = await ref
          .read(cartControllerProvider.notifier)
          .fetchOrder(widget.orderId);
      if (!mounted) return;
      setState(() {
        _order = order;
        _loading = false;
        if (order == null) _error = 'الطلب غير موجود';
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _loading = false;
        _error = e.toString();
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    if (_loading) {
      return const Scaffold(body: Center(child: CircularProgressIndicator()));
    }
    if (_error != null || _order == null) {
      return Scaffold(
        appBar: AppBar(),
        body: Center(child: Text(_error ?? 'خطأ')),
      );
    }
    final order = _order!;
    return Scaffold(
      appBar: AppBar(title: Text('طلب #${order.id}')),
      body: ListView(
        padding: const EdgeInsets.all(20),
        children: [
          Text(
            order.status,
            style: const TextStyle(
              fontWeight: FontWeight.w700,
              fontSize: 18,
              color: AppColors.mutedGold,
            ),
          ),
          const SizedBox(height: 8),
          Text('المبلغ: ${fmtMoney(order.total)} د.ع'),
          if (order.customerName.isNotEmpty)
            Text('الزبون: ${order.customerName}'),
          const SizedBox(height: 20),
          Text('تتبع الطلب', style: Theme.of(context).textTheme.titleMedium),
          const SizedBox(height: 8),
          for (final step in order.steps)
            ListTile(
              contentPadding: EdgeInsets.zero,
              leading: Icon(
                step['done'] == true
                    ? Icons.check_circle
                    : (step['active'] == true
                        ? Icons.radio_button_checked
                        : Icons.radio_button_unchecked),
                color: step['done'] == true || step['active'] == true
                    ? AppColors.mutedGold
                    : Colors.grey,
              ),
              title: Text('${step['label'] ?? ''}'),
              subtitle: Text('${step['hint'] ?? ''}'),
            ),
          const SizedBox(height: 12),
          Text('المنتجات', style: Theme.of(context).textTheme.titleMedium),
          for (final item in order.items)
            ListTile(
              contentPadding: EdgeInsets.zero,
              title: Text('${item['name']}'),
              subtitle: Text('× ${item['quantity']}'),
              trailing:
                  Text('${fmtMoney((item['line_total'] as int?) ?? 0)} د.ع'),
            ),
          if (order.status == 'تم الطلب') ...[
            const SizedBox(height: 16),
            OutlinedButton(
              onPressed: () async {
                await ref
                    .read(cartControllerProvider.notifier)
                    .cancelOrder(order.id);
                await _load();
              },
              child: const Text('إلغاء الطلب'),
            ),
          ],
        ],
      ),
    );
  }
}
