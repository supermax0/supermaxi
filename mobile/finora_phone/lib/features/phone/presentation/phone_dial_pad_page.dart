import 'dart:async';
import 'dart:ui' show FontFeature;

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:uuid/uuid.dart';

import '../../../core/actions/customer_actions.dart';
import '../../../core/di/providers.dart';
import '../../../core/theme/app_colors.dart';
import '../../../core/ui/finora_ui.dart';
import '../../../domain/entities/entities.dart';

class PhoneDialPadPage extends ConsumerStatefulWidget {
  const PhoneDialPadPage({super.key});

  @override
  ConsumerState<PhoneDialPadPage> createState() => _PhoneDialPadPageState();
}

class _PhoneDialPadPageState extends ConsumerState<PhoneDialPadPage>
    with WidgetsBindingObserver {
  String _digits = '';
  CustomerEntity? _preview;
  Timer? _debounce;
  List<CustomerEntity> _recents = const [];
  List<Map<String, Object?>> _favorites = const [];
  int _simSlots = 1;
  int? _simSlot;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    _loadRecents();
    _loadDevice();
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    _debounce?.cancel();
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.resumed) {
      _loadRecents();
    }
  }

  Future<void> _loadDevice() async {
    final info = await ref.read(permissionsChannelProvider).deviceInfo();
    final slots = (info['sim_slots_count'] as num?)?.toInt() ?? 1;
    if (mounted) {
      setState(() {
        _simSlots = slots < 1 ? 1 : slots;
        if (_simSlots >= 2 && _simSlot == null) _simSlot = 0;
      });
    }
  }

  Future<void> _loadRecents() async {
    final logs = await ref.read(callLogRepositoryProvider).listLocal(limit: 8);
    final customers = <CustomerEntity>[];
    for (final log in logs) {
      final c = await ref
          .read(customerRepositoryProvider)
          .lookupByPhone(log.phone, allowNetwork: false);
      if (c != null) customers.add(c);
    }
    final favs = await ref.read(localDatabaseProvider).listFavorites(limit: 12);
    if (mounted) {
      setState(() {
        _recents = customers;
        _favorites = favs;
      });
    }
  }

  void _onDigit(String d) {
    HapticFeedback.selectionClick();
    setState(() => _digits += d);
    _debounce?.cancel();
    _debounce = Timer(const Duration(milliseconds: 150), _lookup);
  }

  void _backspace() {
    if (_digits.isEmpty) return;
    HapticFeedback.lightImpact();
    setState(() => _digits = _digits.substring(0, _digits.length - 1));
    _debounce?.cancel();
    _debounce = Timer(const Duration(milliseconds: 150), _lookup);
  }

  Future<void> _lookup() async {
    if (_digits.length < 3) {
      setState(() => _preview = null);
      return;
    }
    if (_digits.length >= 7) {
      final c = await ref.read(customerRepositoryProvider).lookupByPhone(_digits);
      if (mounted) setState(() => _preview = c);
    } else {
      final local =
          await ref.read(customerRepositoryProvider).searchLocal(_digits);
      if (mounted) setState(() => _preview = local.isEmpty ? null : local.first);
    }
  }

  Future<void> _createCustomer() async {
    final nameCtrl = TextEditingController();
    final cityCtrl = TextEditingController(text: 'بغداد');
    final addressCtrl = TextEditingController();
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
            top: 8,
            bottom: media.viewInsets.bottom + media.viewPadding.bottom + 20,
          ),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Text('زبون جديد', style: Theme.of(ctx).textTheme.headlineSmall),
              const SizedBox(height: 8),
              Text('الرقم: $_digits', style: Theme.of(ctx).textTheme.bodyMedium),
              const SizedBox(height: 14),
              TextField(
                controller: nameCtrl,
                decoration: const InputDecoration(labelText: 'الاسم'),
              ),
              const SizedBox(height: 10),
              TextField(
                controller: cityCtrl,
                decoration: const InputDecoration(labelText: 'المحافظة'),
              ),
              const SizedBox(height: 10),
              TextField(
                controller: addressCtrl,
                decoration: const InputDecoration(labelText: 'العنوان'),
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
    if (ok == true && nameCtrl.text.trim().isNotEmpty) {
      final created = await ref.read(customerRepositoryProvider).createCustomer(
            name: nameCtrl.text.trim(),
            phone: _digits,
            city: cityCtrl.text.trim(),
            address: addressCtrl.text.trim(),
            clientId: const Uuid().v4(),
          );
      if (mounted) setState(() => _preview = created);
    }
  }

  Future<void> _dial() async {
    if (_digits.isEmpty) return;
    final ok = await ref.read(permissionsChannelProvider).dialNumber(
          _digits,
          simSlot: _simSlots >= 2 ? _simSlot : null,
        );
    if (!ok && mounted) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(
            'افتح هاتف النظام واتصل بـ $_digits — Finora لا يرد/يرفض',
          ),
        ),
      );
    }
  }

  @override
  Widget build(BuildContext context) {
    final dark = Theme.of(context).brightness == Brightness.dark;
    final keys = [
      ['1', ''],
      ['2', 'ABC'],
      ['3', 'DEF'],
      ['4', 'GHI'],
      ['5', 'JKL'],
      ['6', 'MNO'],
      ['7', 'PQRS'],
      ['8', 'TUV'],
      ['9', 'WXYZ'],
      ['*', ''],
      ['0', '+'],
      ['#', ''],
    ];

    return FinoraScaffold(
      appBar: AppBar(
        title: const Text('الهاتف'),
        actions: [
          IconButton(
            tooltip: 'المفضلة',
            onPressed: () async {
              await context.push('/favorites');
              await _loadRecents();
            },
            icon: const Icon(Icons.star_outline_rounded),
          ),
          IconButton(
            tooltip: 'لوحة اليوم',
            onPressed: () => context.push('/dashboard'),
            icon: const Icon(Icons.dashboard_outlined),
          ),
          Padding(
            padding: const EdgeInsets.only(left: 8),
            child: Center(
              child: Text(
                'FINORA',
                style: Theme.of(context).textTheme.labelLarge?.copyWith(
                      color: AppColors.goldAccent,
                      letterSpacing: 1.5,
                    ),
              ),
            ),
          ),
        ],
      ),
      body: SafeArea(
        child: Column(
          children: [
            const SizedBox(height: 56),
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 16),
              child: _preview != null
                  ? FinoraSurface(
                      onTap: () => context.push(
                        '/customer-detail',
                        extra: _preview,
                      ),
                      padding: const EdgeInsets.symmetric(
                        horizontal: 12,
                        vertical: 10,
                      ),
                      child: Row(
                        children: [
                          FinoraAvatar(
                            label: _preview!.name,
                            highlighted: _preview!.vip,
                          ),
                          const SizedBox(width: 12),
                          Expanded(
                            child: Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                Text(
                                  _preview!.name,
                                  style: Theme.of(context).textTheme.titleMedium,
                                ),
                                Text(
                                  [
                                    _preview!.phone,
                                    if (_preview!.balance != null)
                                      'رصيد ${_preview!.balance}',
                                    if (_preview!.blacklisted) 'قائمة سوداء',
                                  ].join(' · '),
                                  style: Theme.of(context).textTheme.bodySmall,
                                ),
                              ],
                            ),
                          ),
                          IconButton(
                            tooltip: 'واتساب',
                            onPressed: () =>
                                CustomerActions.openWhatsApp(_preview!.phone),
                            icon: const Icon(Icons.chat_rounded,
                                color: AppColors.goldAccent),
                          ),
                          if (_preview!.vip)
                            const Icon(Icons.star_rounded,
                                color: AppColors.goldAccent),
                        ],
                      ),
                    )
                  : _digits.length >= 7
                      ? FinoraSurface(
                          child: Row(
                            children: [
                              const FinoraAvatar(label: '+'),
                              const SizedBox(width: 12),
                              Expanded(
                                child: Column(
                                  crossAxisAlignment: CrossAxisAlignment.start,
                                  children: [
                                    Text(
                                      'زبون جديد',
                                      style: Theme.of(context)
                                          .textTheme
                                          .titleMedium,
                                    ),
                                    Text(
                                      _digits,
                                      style:
                                          Theme.of(context).textTheme.bodySmall,
                                    ),
                                  ],
                                ),
                              ),
                              FilledButton.tonal(
                                onPressed: _createCustomer,
                                child: const Text('إنشاء'),
                              ),
                            ],
                          ),
                        )
                      : const SizedBox(height: 64),
            ),
            const SizedBox(height: 18),
            AnimatedDefaultTextStyle(
              duration: const Duration(milliseconds: 180),
              style: Theme.of(context).textTheme.headlineLarge!.copyWith(
                    letterSpacing: _digits.isEmpty ? 0 : 2.5,
                    fontFeatures: const [FontFeature.tabularFigures()],
                  ),
              child: Text(
                _digits.isEmpty ? 'أدخل الرقم' : _digits,
                textAlign: TextAlign.center,
              ),
            ),
            if (_favorites.isNotEmpty || _recents.isNotEmpty) ...[
              const SizedBox(height: 14),
              SizedBox(
                height: 40,
                child: ListView(
                  scrollDirection: Axis.horizontal,
                  padding: const EdgeInsets.symmetric(horizontal: 16),
                  children: [
                    ..._favorites.map(
                      (f) => Padding(
                        padding: const EdgeInsets.only(left: 8),
                        child: GestureDetector(
                          onLongPress: () async {
                            await ref.read(localDatabaseProvider).removeFavorite(
                                  customerId: f['customer_id'] is int
                                      ? f['customer_id'] as int
                                      : null,
                                  phone: '${f['phone']}',
                                );
                            await _loadRecents();
                          },
                          child: ActionChip(
                            avatar: const Icon(Icons.star_rounded,
                                size: 16, color: AppColors.goldAccent),
                            label: Text('${f['name']}'),
                            onPressed: () {
                              setState(() {
                                _digits = '${f['phone']}';
                                _preview = null;
                              });
                              _lookup();
                            },
                          ),
                        ),
                      ),
                    ),
                    ..._recents.map(
                      (c) => Padding(
                        padding: const EdgeInsets.only(left: 8),
                        child: ActionChip(
                          avatar: FinoraAvatar(label: c.name, size: 22),
                          label: Text(c.name),
                          onPressed: () {
                            setState(() {
                              _digits = c.phone;
                              _preview = c;
                            });
                          },
                        ),
                      ),
                    ),
                  ],
                ),
              ),
            ],
            if (_simSlots >= 2) ...[
              const SizedBox(height: 10),
              Row(
                mainAxisAlignment: MainAxisAlignment.center,
                children: [
                  for (var i = 0; i < _simSlots && i < 2; i++)
                    Padding(
                      padding: const EdgeInsets.symmetric(horizontal: 4),
                      child: ChoiceChip(
                        label: Text('SIM ${i + 1}'),
                        selected: _simSlot == i,
                        onSelected: (_) => setState(() => _simSlot = i),
                      ),
                    ),
                ],
              ),
            ],
            const Spacer(),
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 28),
              child: GridView.builder(
                shrinkWrap: true,
                physics: const NeverScrollableScrollPhysics(),
                itemCount: keys.length,
                gridDelegate: const SliverGridDelegateWithFixedCrossAxisCount(
                  crossAxisCount: 3,
                  mainAxisSpacing: 12,
                  crossAxisSpacing: 12,
                  childAspectRatio: 1.5,
                ),
                itemBuilder: (_, i) {
                  final key = keys[i];
                  return Material(
                    color: dark
                        ? AppColors.elevatedDark.withOpacity(0.85)
                        : Colors.white.withOpacity(0.88),
                    borderRadius: BorderRadius.circular(22),
                    child: InkWell(
                      borderRadius: BorderRadius.circular(22),
                      onTap: () => _onDigit(key[0]),
                      onLongPress:
                          key[0] == '0' ? () => _onDigit('+') : null,
                      child: Column(
                        mainAxisAlignment: MainAxisAlignment.center,
                        children: [
                          Text(
                            key[0],
                            style: const TextStyle(
                              fontSize: 28,
                              fontWeight: FontWeight.w700,
                              fontFamily: 'Noto Sans Arabic',
                            ),
                          ),
                          if (key[1].isNotEmpty)
                            Text(
                              key[1],
                              style: TextStyle(
                                fontSize: 9.5,
                                letterSpacing: 1.2,
                                color: dark
                                    ? AppColors.textMutedDark
                                    : AppColors.textMutedLight,
                              ),
                            ),
                        ],
                      ),
                    ),
                  );
                },
              ),
            ),
            const SizedBox(height: 20),
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 28),
              child: Row(
                children: [
                  const SizedBox(width: 56),
                  Expanded(
                    child: Center(
                      child: Material(
                        color: Colors.transparent,
                        child: InkWell(
                          onTap: _digits.isEmpty ? null : _dial,
                          customBorder: const CircleBorder(),
                          child: Ink(
                            width: 76,
                            height: 76,
                            decoration: BoxDecoration(
                              shape: BoxShape.circle,
                              gradient: _digits.isEmpty
                                  ? null
                                  : const LinearGradient(
                                      colors: [
                                        Color(0xFF3CBF7A),
                                        Color(0xFF2A8F58),
                                      ],
                                    ),
                              color: _digits.isEmpty
                                  ? (dark
                                      ? AppColors.hairlineDark
                                      : AppColors.mist)
                                  : null,
                              boxShadow: _digits.isEmpty
                                  ? null
                                  : [
                                      BoxShadow(
                                        color: AppColors.success
                                            .withOpacity(0.35),
                                        blurRadius: 18,
                                        offset: const Offset(0, 8),
                                      ),
                                    ],
                            ),
                            child: Icon(
                              Icons.call_rounded,
                              size: 34,
                              color: _digits.isEmpty
                                  ? (dark
                                      ? AppColors.textMutedDark
                                      : AppColors.textMutedLight)
                                  : Colors.white,
                            ),
                          ),
                        ),
                      ),
                    ),
                  ),
                  SizedBox(
                    width: 56,
                    child: GestureDetector(
                      onTap: _backspace,
                      onLongPress: () => setState(() {
                        _digits = '';
                        _preview = null;
                      }),
                      child: const Padding(
                        padding: EdgeInsets.all(12),
                        child: Icon(Icons.backspace_outlined, size: 26),
                      ),
                    ),
                  ),
                ],
              ),
            ),
            const SizedBox(height: 28),
          ],
        ),
      ),
    );
  }
}
