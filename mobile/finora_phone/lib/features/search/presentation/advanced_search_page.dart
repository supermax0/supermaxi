import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../core/di/providers.dart';
import '../../../core/features/feature_flags.dart';
import '../../../core/theme/app_colors.dart';
import '../../../core/ui/finora_ui.dart';
import '../../../domain/entities/entities.dart';

class AdvancedSearchPage extends ConsumerStatefulWidget {
  const AdvancedSearchPage({super.key});

  @override
  ConsumerState<AdvancedSearchPage> createState() => _AdvancedSearchPageState();
}

class _AdvancedSearchPageState extends ConsumerState<AdvancedSearchPage> {
  final _ctrl = TextEditingController();
  Timer? _debounce;
  int _reqId = 0;
  bool _loading = false;
  Map<String, dynamic>? _result;
  List<String> _recent = const [];
  String _type = 'all';

  @override
  void initState() {
    super.initState();
    _loadRecent();
  }

  @override
  void dispose() {
    _debounce?.cancel();
    _ctrl.dispose();
    super.dispose();
  }

  Future<void> _loadRecent() async {
    final rows = await ref.read(localDatabaseProvider).listRecentSearches();
    if (mounted) setState(() => _recent = rows);
  }

  void _onChanged(String v) {
    _debounce?.cancel();
    _debounce = Timer(const Duration(milliseconds: 300), () => _search(v));
  }

  Future<void> _search(String raw) async {
    final flags = ref.read(featureFlagsProvider);
    if (!flags.advancedSearch) return;
    final q = raw.trim();
    final id = ++_reqId;
    setState(() => _loading = true);
    final types = _type == 'all' ? null : _type;
    final res = await ref
        .read(customerRepositoryProvider)
        .advancedSearch(q, types: types);
    if (!mounted || id != _reqId) return;
    setState(() {
      _result = res;
      _loading = false;
    });
    await _loadRecent();
  }

  Widget _highlight(String text, String q) {
    if (q.isEmpty || !text.toLowerCase().contains(q.toLowerCase())) {
      return Text(text);
    }
    final lower = text.toLowerCase();
    final iq = q.toLowerCase();
    final idx = lower.indexOf(iq);
    return Text.rich(
      TextSpan(
        children: [
          TextSpan(text: text.substring(0, idx)),
          TextSpan(
            text: text.substring(idx, idx + q.length),
            style: const TextStyle(
              color: AppColors.goldAccent,
              fontWeight: FontWeight.w800,
            ),
          ),
          TextSpan(text: text.substring(idx + q.length)),
        ],
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final flags = ref.watch(featureFlagsProvider);
    if (!flags.advancedSearch) {
      return const FinoraScaffold(
        body: Center(child: Text('البحث المتقدم غير مفعّل')),
      );
    }
    final q = _ctrl.text.trim();
    final groups = (_result?['groups'] as Map?) ?? {};
    return FinoraScaffold(
      appBar: AppBar(title: const Text('بحث متقدم')),
      body: SafeArea(
        child: Column(
          children: [
            Padding(
              padding: const EdgeInsets.fromLTRB(16, 8, 16, 0),
              child: TextField(
                controller: _ctrl,
                onChanged: _onChanged,
                decoration: InputDecoration(
                  hintText: 'رقم، اسم، عنوان، طلب، منتج…',
                  prefixIcon: const Icon(Icons.search_rounded),
                  suffixIcon: _ctrl.text.isEmpty
                      ? null
                      : IconButton(
                          icon: const Icon(Icons.clear),
                          onPressed: () {
                            _ctrl.clear();
                            setState(() => _result = null);
                          },
                        ),
                ),
              ),
            ),
            SingleChildScrollView(
              scrollDirection: Axis.horizontal,
              padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
              child: Row(
                children: [
                  for (final t in [
                    ('all', 'الكل'),
                    ('customers', 'زبائن'),
                    ('orders', 'طلبات'),
                    ('invoices', 'فواتير'),
                    ('calls', 'مكالمات'),
                    ('products', 'منتجات'),
                  ])
                    Padding(
                      padding: const EdgeInsets.only(left: 6),
                      child: ChoiceChip(
                        label: Text(t.$2),
                        selected: _type == t.$1,
                        onSelected: (_) {
                          setState(() => _type = t.$1);
                          _search(_ctrl.text);
                        },
                      ),
                    ),
                ],
              ),
            ),
            if (_loading) const LinearProgressIndicator(minHeight: 2),
            Expanded(
              child: _result == null
                  ? ListView(
                      padding: const EdgeInsets.all(16),
                      children: [
                        Row(
                          children: [
                            const Expanded(
                              child: FinoraSectionHeader('عمليات بحث أخيرة'),
                            ),
                            TextButton(
                              onPressed: () async {
                                await ref
                                    .read(localDatabaseProvider)
                                    .clearRecentSearches();
                                await _loadRecent();
                              },
                              child: const Text('مسح'),
                            ),
                          ],
                        ),
                        ..._recent.map(
                          (r) => ListTile(
                            leading: const Icon(Icons.history),
                            title: Text(r),
                            onTap: () {
                              _ctrl.text = r;
                              _search(r);
                            },
                          ),
                        ),
                      ],
                    )
                  : ListView(
                      padding: const EdgeInsets.all(16),
                      children: [
                        for (final section in [
                          ('customers', 'الزبائن'),
                          ('orders', 'الطلبات'),
                          ('invoices', 'الفواتير'),
                          ('calls', 'المكالمات'),
                          ('products', 'المنتجات'),
                        ])
                          ..._section(
                            section.$1,
                            section.$2,
                            groups[section.$1],
                            q,
                          ),
                      ],
                    ),
            ),
          ],
        ),
      ),
    );
  }

  List<Widget> _section(String key, String title, dynamic raw, String q) {
    final list = (raw is List ? raw : const [])
        .whereType<Map>()
        .map((e) => Map<String, dynamic>.from(e))
        .toList();
    if (list.isEmpty) return const [];
    return [
      FinoraSectionHeader(title),
      ...list.map((item) {
        return Padding(
          padding: const EdgeInsets.only(bottom: 8),
          child: FinoraSurface(
            padding: const EdgeInsets.all(12),
            child: InkWell(
              onTap: () async {
                if (key == 'customers' && item['id'] != null) {
                  final id = item['id'] is int
                      ? item['id'] as int
                      : int.tryParse('${item['id']}');
                  if (id == null) return;
                  final phone = '${item['subtitle'] ?? ''}';
                  final c = await ref
                      .read(customerRepositoryProvider)
                      .lookupByPhone(phone, allowNetwork: true);
                  if (!mounted) return;
                  context.push(
                    '/customer-detail',
                    extra: c ??
                        CustomerEntity(
                          id: id,
                          name: '${item['title'] ?? ''}',
                          phone: phone,
                        ),
                  );
                }
              },
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  _highlight('${item['title'] ?? ''}', q),
                  if ((item['subtitle'] ?? '').toString().isNotEmpty)
                    _highlight('${item['subtitle']}', q),
                  if ((item['summary'] ?? '').toString().isNotEmpty)
                    Text(
                      '${item['summary']}',
                      style: Theme.of(context).textTheme.bodySmall,
                    ),
                ],
              ),
            ),
          ),
        );
      }),
    ];
  }
}
