import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../core/actions/customer_actions.dart';
import '../../../core/di/providers.dart';
import '../../../core/theme/app_colors.dart';
import '../../../core/ui/finora_ui.dart';
import '../../../domain/entities/entities.dart';

class ContactsPage extends ConsumerStatefulWidget {
  const ContactsPage({super.key});

  @override
  ConsumerState<ContactsPage> createState() => _ContactsPageState();
}

class _ContactsPageState extends ConsumerState<ContactsPage> {
  List<Map<String, Object?>> _favorites = const [];
  bool _loading = true;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    setState(() => _loading = true);
    final rows = await ref.read(localDatabaseProvider).listFavorites(limit: 100);
    if (mounted) {
      setState(() {
        _favorites = rows;
        _loading = false;
      });
    }
  }

  Future<void> _openFavorite(Map<String, Object?> f) async {
    final phone = '${f['phone'] ?? ''}';
    final name = '${f['name'] ?? phone}';
    final id = f['customer_id'];
    CustomerEntity? customer;
    if (id is int) {
      customer = CustomerEntity(id: id, name: name, phone: phone);
    } else if (phone.isNotEmpty) {
      customer = await ref
          .read(customerRepositoryProvider)
          .lookupByPhone(phone, allowNetwork: true);
    }
    customer ??= CustomerEntity(id: null, name: name, phone: phone);
    if (!mounted) return;
    await context.push('/customer-detail', extra: customer);
    await _load();
  }

  Future<void> _remove(Map<String, Object?> f) async {
    await ref.read(localDatabaseProvider).removeFavorite(
          customerId: f['customer_id'] is int ? f['customer_id'] as int : null,
          phone: '${f['phone']}',
        );
    await _load();
  }

  @override
  Widget build(BuildContext context) {
    return FinoraScaffold(
      appBar: AppBar(title: const Text('المفضلة')),
      body: SafeArea(
        child: _loading
            ? const Center(child: CircularProgressIndicator())
            : _favorites.isEmpty
                ? const FinoraEmptyState(
                    icon: Icons.star_outline_rounded,
                    title: 'لا مفضلة بعد',
                    subtitle:
                        'أضف زبائن للمفضلة من صفحة الزبون — تظهر هنا وفي لوحة الاتصال',
                  )
                : ListView.separated(
                    padding: const EdgeInsets.fromLTRB(16, 56, 16, 28),
                    itemCount: _favorites.length,
                    separatorBuilder: (_, __) => const SizedBox(height: 10),
                    itemBuilder: (_, i) {
                      final f = _favorites[i];
                      final name = '${f['name'] ?? ''}';
                      final phone = '${f['phone'] ?? ''}';
                      return FinoraSurface(
                        onTap: () => _openFavorite(f),
                        padding: const EdgeInsets.symmetric(
                          horizontal: 14,
                          vertical: 12,
                        ),
                        child: Row(
                          children: [
                            FinoraAvatar(
                              label: name,
                              highlighted: true,
                            ),
                            const SizedBox(width: 12),
                            Expanded(
                              child: Column(
                                crossAxisAlignment: CrossAxisAlignment.start,
                                children: [
                                  Text(
                                    name,
                                    style:
                                        Theme.of(context).textTheme.titleMedium,
                                  ),
                                  Text(
                                    phone,
                                    style:
                                        Theme.of(context).textTheme.bodySmall,
                                  ),
                                ],
                              ),
                            ),
                            IconButton(
                              tooltip: 'اتصال',
                              onPressed: () =>
                                  CustomerActions.dial(ref, phone),
                              icon: const Icon(
                                Icons.call_rounded,
                                color: AppColors.success,
                              ),
                            ),
                            IconButton(
                              tooltip: 'إزالة',
                              onPressed: () => _remove(f),
                              icon: const Icon(
                                Icons.star_rounded,
                                color: AppColors.goldAccent,
                              ),
                            ),
                          ],
                        ),
                      );
                    },
                  ),
      ),
    );
  }
}
