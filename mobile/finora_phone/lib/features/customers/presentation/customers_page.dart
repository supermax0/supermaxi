import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:uuid/uuid.dart';

import '../../../core/actions/customer_actions.dart';
import '../../../core/di/providers.dart';
import '../../../core/theme/app_colors.dart';
import '../../../core/ui/finora_ui.dart';
import '../../../domain/entities/entities.dart';

class CustomersPage extends ConsumerStatefulWidget {
  const CustomersPage({super.key});

  @override
  ConsumerState<CustomersPage> createState() => _CustomersPageState();
}

class _CustomersPageState extends ConsumerState<CustomersPage> {
  final _query = TextEditingController();
  Timer? _debounce;
  List<CustomerEntity> _items = const [];
  bool _loading = true;
  String? _error;

  @override
  void initState() {
    super.initState();
    _search('');
  }

  @override
  void dispose() {
    _debounce?.cancel();
    _query.dispose();
    super.dispose();
  }

  Future<void> _search(String raw) async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final q = raw.trim();
      final repo = ref.read(customerRepositoryProvider);
      final list = q.isEmpty
          ? await repo.searchLocal('')
          : await repo.searchRemote(q);
      if (mounted) {
        setState(() {
          _items = list;
          _loading = false;
        });
      }
    } catch (e) {
      if (mounted) {
        setState(() {
          _error = '$e';
          _loading = false;
        });
      }
    }
  }

  void _onQueryChanged(String v) {
    setState(() {});
    _debounce?.cancel();
    _debounce = Timer(const Duration(milliseconds: 320), () => _search(v));
  }

  Future<void> _createCustomer() async {
    final nameCtrl = TextEditingController();
    final phoneCtrl = TextEditingController();
    final cityCtrl = TextEditingController(text: 'بغداد');
    final ok = await showModalBottomSheet<bool>(
      context: context,
      isScrollControlled: true,
      useRootNavigator: true,
      builder: (ctx) {
        final media = MediaQuery.of(ctx);
        return Padding(
          padding: EdgeInsets.only(
            left: 20,
            right: 20,
            top: 12,
            bottom: media.viewInsets.bottom + media.viewPadding.bottom + 20,
          ),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Text('زبون جديد', style: Theme.of(ctx).textTheme.headlineSmall),
              const SizedBox(height: 14),
              TextField(
                controller: nameCtrl,
                decoration: const InputDecoration(labelText: 'الاسم'),
              ),
              const SizedBox(height: 10),
              TextField(
                controller: phoneCtrl,
                keyboardType: TextInputType.phone,
                decoration: const InputDecoration(labelText: 'الهاتف'),
              ),
              const SizedBox(height: 10),
              TextField(
                controller: cityCtrl,
                decoration: const InputDecoration(labelText: 'المحافظة'),
              ),
              const SizedBox(height: 16),
              FilledButton(
                onPressed: () => Navigator.pop(ctx, true),
                child: const Text('حفظ'),
              ),
            ],
          ),
        );
      },
    );
    if (ok == true &&
        nameCtrl.text.trim().isNotEmpty &&
        phoneCtrl.text.trim().length >= 7) {
      try {
        final created =
            await ref.read(customerRepositoryProvider).createCustomer(
                  name: nameCtrl.text.trim(),
                  phone: phoneCtrl.text.trim(),
                  city: cityCtrl.text.trim(),
                  clientId: const Uuid().v4(),
                );
        if (!mounted) return;
        await _search(_query.text);
        if (!mounted) return;
        context.push('/customer-detail', extra: created);
      } catch (e) {
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(content: Text('تعذر الإنشاء: $e')),
          );
        }
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    return FinoraScaffold(
      appBar: AppBar(
        title: const Text('الزبائن'),
        actions: [
          IconButton(
            tooltip: 'بحث متقدم',
            onPressed: () => context.push('/search'),
            icon: const Icon(Icons.manage_search_rounded),
          ),
          IconButton(
            tooltip: 'المفضلة',
            onPressed: () => context.push('/favorites'),
            icon: const Icon(Icons.star_outline_rounded),
          ),
          IconButton(
            tooltip: 'تحديث',
            onPressed: () => _search(_query.text),
            icon: const Icon(Icons.refresh_rounded),
          ),
        ],
      ),
      floatingActionButton: Padding(
        padding: EdgeInsets.only(bottom: finoraShellBottomInset(context)),
        child: FloatingActionButton(
          onPressed: _createCustomer,
          child: const Icon(Icons.person_add_alt_1_rounded),
        ),
      ),
      body: SafeArea(
        child: Column(
          children: [
            const SizedBox(height: 56),
            Padding(
              padding: const EdgeInsets.fromLTRB(16, 0, 16, 12),
              child: TextField(
                controller: _query,
                decoration: const InputDecoration(
                  hintText: 'بحث بالاسم أو الرقم أو المحافظة',
                  prefixIcon: Icon(Icons.search_rounded),
                ),
                onChanged: _onQueryChanged,
              ),
            ),
            Expanded(
              child: _loading
                  ? const Center(child: CircularProgressIndicator())
                  : _error != null
                      ? Center(child: Text(_error!))
                      : _items.isEmpty
                          ? const FinoraEmptyState(
                              icon: Icons.people_outline_rounded,
                              title: 'لا نتائج',
                              subtitle:
                                  'ابحث عن زبون من النظام أو أنشئ زبوناً جديداً',
                            )
                          : ListView.separated(
                              padding:
                                  const EdgeInsets.fromLTRB(16, 0, 16, 100),
                              itemCount: _items.length,
                              separatorBuilder: (_, __) =>
                                  const SizedBox(height: 10),
                              itemBuilder: (_, i) {
                                final c = _items[i];
                                return FinoraSurface(
                                  onTap: () async {
                                    await context.push(
                                      '/customer-detail',
                                      extra: c,
                                    );
                                    if (mounted) _search(_query.text);
                                  },
                                  padding: const EdgeInsets.symmetric(
                                    horizontal: 14,
                                    vertical: 12,
                                  ),
                                  child: Row(
                                    children: [
                                      FinoraAvatar(
                                        label: c.name,
                                        highlighted: c.vip,
                                      ),
                                      const SizedBox(width: 12),
                                      Expanded(
                                        child: Column(
                                          crossAxisAlignment:
                                              CrossAxisAlignment.start,
                                          children: [
                                            Row(
                                              children: [
                                                Flexible(
                                                  child: Text(
                                                    c.name,
                                                    style: Theme.of(context)
                                                        .textTheme
                                                        .titleMedium,
                                                  ),
                                                ),
                                                if (c.vip) ...[
                                                  const SizedBox(width: 6),
                                                  const Icon(
                                                    Icons.star_rounded,
                                                    size: 16,
                                                    color:
                                                        AppColors.goldAccent,
                                                  ),
                                                ],
                                              ],
                                            ),
                                            Text(
                                              [
                                                c.phone,
                                                if (c.city.isNotEmpty) c.city,
                                                if (c.balance != null)
                                                  'رصيد ${c.balance}',
                                              ].join(' · '),
                                              style: Theme.of(context)
                                                  .textTheme
                                                  .bodySmall,
                                            ),
                                          ],
                                        ),
                                      ),
                                      IconButton(
                                        tooltip: 'اتصال',
                                        onPressed: () =>
                                            CustomerActions.dial(ref, c.phone),
                                        icon: const Icon(
                                          Icons.call_rounded,
                                          color: AppColors.success,
                                        ),
                                      ),
                                      if (c.blacklisted)
                                        const Icon(
                                          Icons.block,
                                          color: AppColors.error,
                                        ),
                                    ],
                                  ),
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
