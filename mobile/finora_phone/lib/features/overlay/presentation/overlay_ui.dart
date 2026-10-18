import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:uuid/uuid.dart';

import '../../../core/actions/customer_actions.dart';
import '../../../core/bootstrap/phone_bootstrap.dart';
import '../../../core/di/providers.dart';
import '../../../core/features/feature_flags.dart';
import '../../../core/theme/app_colors.dart';
import '../../../core/ui/finora_ui.dart';
import '../../../domain/entities/entities.dart';
import '../data/active_call_controller.dart';

class InCallToolsSheet extends ConsumerStatefulWidget {
  const InCallToolsSheet({super.key, this.fullPage = false, this.focus});

  final bool fullPage;

  /// Deep-link intent from the overlay: `note` focuses the note field,
  /// `task` creates the follow-up task straight away.
  final String? focus;

  @override
  ConsumerState<InCallToolsSheet> createState() => _InCallToolsSheetState();
}

class _InCallToolsSheetState extends ConsumerState<InCallToolsSheet> {
  final _noteCtrl = TextEditingController();
  final _noteFocus = FocusNode();
  final _productCtrl = TextEditingController();
  final _customerNameCtrl = TextEditingController();
  final _customerAddressCtrl = TextEditingController();
  List<Map<String, dynamic>> _products = const [];
  final _selected = <int, Map<String, dynamic>>{};
  String? _selectedProvince;
  bool _savingCustomer = false;
  bool _submittingOrder = false;

  void _addProduct(Map<String, dynamic> p) {
    final id = (p['id'] as num?)?.toInt();
    if (id == null) return;
    setState(() {
      final existing = _selected[id];
      if (existing == null) {
        _selected[id] = {...p, 'qty': 1};
      } else {
        final qty = ((existing['qty'] as num?)?.toInt() ?? 1) + 1;
        _selected[id] = {...existing, 'qty': qty};
      }
    });
  }

  void _bumpQty(int id, int delta) {
    setState(() {
      final existing = _selected[id];
      if (existing == null) return;
      final qty = ((existing['qty'] as num?)?.toInt() ?? 1) + delta;
      if (qty <= 0) {
        _selected.remove(id);
      } else {
        _selected[id] = {...existing, 'qty': qty};
      }
    });
  }

  @override
  void initState() {
    super.initState();
    final draft = ref.read(activeCallProvider).noteDraft;
    _noteCtrl.text = draft;
    final bootstrap = ref.read(phoneBootstrapProvider);
    _selectedProvince = bootstrap.primaryProvince;
    final focus = widget.focus;
    if (focus == 'note') {
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (mounted) _noteFocus.requestFocus();
      });
    } else if (focus == 'task') {
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (mounted) _createTask();
      });
    }
  }

  @override
  void dispose() {
    _noteFocus.dispose();
    _noteCtrl.dispose();
    _productCtrl.dispose();
    _customerNameCtrl.dispose();
    _customerAddressCtrl.dispose();
    super.dispose();
  }

  Future<void> _searchProducts(String q) async {
    if (q.trim().isEmpty) {
      setState(() => _products = const []);
      return;
    }
    try {
      final res = await ref
          .read(apiClientProvider)
          .get('/api/phone/v1/products/search', query: {'q': q});
      final list = (res['products'] as List? ?? [])
          .whereType<Map>()
          .map((e) => Map<String, dynamic>.from(e))
          .toList();
      if (mounted) setState(() => _products = list);
    } catch (_) {}
  }

  Future<void> _saveNote() async {
    final call = ref.read(activeCallProvider);
    ref.read(activeCallProvider.notifier).setNoteDraft(_noteCtrl.text);
    if (_noteCtrl.text.trim().isEmpty) return;
    final clientId = (call.clientId != null && call.clientId!.isNotEmpty)
        ? 'note-${call.clientId}'
        : const Uuid().v4();
    await ref.read(noteRepositoryProvider).createLocal(
          NoteEntity(
            clientId: clientId,
            body: _noteCtrl.text.trim(),
            callClientId: call.clientId,
            customerId: call.customer?.id,
          ),
        );
    if (mounted) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('تم حفظ الملاحظة (مزامنة لاحقاً إن لزم)')),
      );
    }
  }

  Future<void> _createTask() async {
    final call = ref.read(activeCallProvider);
    if (call.number.isEmpty) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('لا يوجد رقم مكالمة')),
      );
      return;
    }
    final minutes = ref.read(phoneBootstrapProvider).missedCallFollowupMinutes;
    await ref.read(taskRepositoryProvider).createLocal(
          TaskEntity(
            clientId: const Uuid().v4(),
            title: 'متابعة مكالمة',
            phone: call.number,
            customerId: call.customer?.id,
            dueAt: DateTime.now().toUtc().add(Duration(minutes: minutes)),
            source: 'manual',
          ),
        );
    if (mounted) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('تم إنشاء مهمة متابعة')),
      );
    }
  }

  Future<void> _createOrder() async {
    final call = ref.read(activeCallProvider);
    final customerId = call.customer?.id;
    if (customerId == null) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('أنشئ أو اربط زبون أولاً')),
      );
      return;
    }
    if (_selected.isEmpty) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('اختر منتجات')),
      );
      return;
    }
    final items = _selected.values
        .map(
          (p) => {
            'product_id': p['id'],
            'qty': (p['qty'] as num?)?.toInt() ?? 1,
            'price': p['sale_price'],
          },
        )
        .toList();
    setState(() => _submittingOrder = true);
    try {
      final result = await ref.read(orderRepositoryProvider).createConfirmedOrder(
            customerId: customerId,
            items: items,
            note: _noteCtrl.text.trim(),
            clientId: const Uuid().v4(),
          );
      if (!mounted) return;
      final invoiceId = result['invoice_id'];
      setState(() {
        _selected.clear();
        _products = const [];
        _productCtrl.clear();
      });
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(
            invoiceId == null
                ? 'تم تأكيد الطلب وإرساله إلى صفحة الطلبات'
                : 'تم تأكيد الطلب رقم #$invoiceId وإرساله إلى صفحة الطلبات',
          ),
        ),
      );
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('فشل تأكيد الطلب: $e')),
        );
      }
    } finally {
      if (mounted) setState(() => _submittingOrder = false);
    }
  }

  Future<void> _createCustomerQuick() async {
    final call = ref.read(activeCallProvider);
    if (_customerNameCtrl.text.trim().isEmpty ||
        _customerAddressCtrl.text.trim().isEmpty ||
        _selectedProvince == null) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('أدخل اسم الزبون والمحافظة والعنوان')),
      );
      return;
    }
    setState(() => _savingCustomer = true);
    try {
      final c = await ref.read(customerRepositoryProvider).createCustomer(
            name: _customerNameCtrl.text.trim(),
            phone: call.number,
            city: _selectedProvince,
            address: _customerAddressCtrl.text.trim(),
            clientId: const Uuid().v4(),
          );
      ref.read(activeCallProvider.notifier).attachCustomer(c);
      await ref.read(overlayChannelProvider).updateCrm({
        'name': c.name,
        'phone': c.phone,
        'isNew': c.id == null,
      });
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('تم إنشاء الزبون #${c.id ?? ''}')),
        );
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('فشل إنشاء الزبون: $e')),
        );
      }
    } finally {
      if (mounted) setState(() => _savingCustomer = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final call = ref.watch(activeCallProvider);
    final customer = call.customer;
    final bootstrap = ref.watch(phoneBootstrapProvider);
    final dark = Theme.of(context).brightness == Brightness.dark;

    return DraggableScrollableSheet(
      expand: widget.fullPage,
      initialChildSize: widget.fullPage ? 1 : 0.72,
      minChildSize: widget.fullPage ? 1 : 0.42,
      maxChildSize: widget.fullPage ? 1 : 0.86,
      builder: (context, controller) {
        return Material(
          borderRadius: const BorderRadius.vertical(top: Radius.circular(24)),
          color: widget.fullPage
              ? Colors.transparent
              : (dark ? AppColors.elevatedDark : AppColors.surfaceLight),
          child: ListView(
            controller: controller,
            padding: const EdgeInsets.fromLTRB(20, 12, 20, 28),
            children: [
              Center(
                child: Container(
                  width: 40,
                  height: 4,
                  decoration: BoxDecoration(
                    color: AppColors.goldAccent.withOpacity(0.45),
                    borderRadius: BorderRadius.circular(4),
                  ),
                ),
              ),
              const SizedBox(height: 16),
              FinoraSurface(
                child: Row(
                  children: [
                    FinoraAvatar(
                      label: customer?.name ?? call.number,
                      size: 52,
                      highlighted: customer != null,
                    ),
                    const SizedBox(width: 14),
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(
                            customer?.name ??
                                (call.number.isEmpty ? 'مكالمة' : 'زبون جديد'),
                            style: Theme.of(context).textTheme.titleLarge,
                          ),
                          if (call.number.isNotEmpty)
                            Text(
                              call.number,
                              style: Theme.of(context).textTheme.bodyMedium,
                            ),
                          if (call.simSlot != null)
                            Text(
                              'SIM ${call.simSlot! + 1}',
                              style: Theme.of(context).textTheme.bodySmall,
                            ),
                        ],
                      ),
                    ),
                  ],
                ),
              ),
              if (customer == null) ...[
                const SizedBox(height: 12),
                FinoraSurface(
                  padding: const EdgeInsets.all(14),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: [
                      Text(
                        'بيانات الزبون الجديد',
                        style: Theme.of(context).textTheme.titleMedium,
                      ),
                      const SizedBox(height: 10),
                      TextField(
                        controller: _customerNameCtrl,
                        textInputAction: TextInputAction.next,
                        decoration: const InputDecoration(
                          labelText: 'اسم الزبون',
                          prefixIcon: Icon(Icons.person_outline_rounded),
                        ),
                      ),
                      const SizedBox(height: 10),
                      DropdownButtonFormField<String>(
                        value: bootstrap.provinces.contains(_selectedProvince)
                            ? _selectedProvince
                            : null,
                        isExpanded: true,
                        decoration: const InputDecoration(
                          labelText: 'المحافظة',
                          prefixIcon: Icon(Icons.location_city_rounded),
                        ),
                        items: bootstrap.provinces
                            .map(
                              (province) => DropdownMenuItem(
                                value: province,
                                child: Text(province),
                              ),
                            )
                            .toList(),
                        onChanged: (value) =>
                            setState(() => _selectedProvince = value),
                      ),
                      const SizedBox(height: 10),
                      TextField(
                        controller: _customerAddressCtrl,
                        textInputAction: TextInputAction.done,
                        minLines: 1,
                        maxLines: 2,
                        decoration: const InputDecoration(
                          labelText: 'العنوان التفصيلي',
                          prefixIcon: Icon(Icons.home_outlined),
                        ),
                      ),
                      const SizedBox(height: 10),
                      FilledButton.icon(
                        onPressed:
                            _savingCustomer ? null : _createCustomerQuick,
                        icon: _savingCustomer
                            ? const SizedBox.square(
                                dimension: 18,
                                child: CircularProgressIndicator(
                                  strokeWidth: 2,
                                ),
                              )
                            : const Icon(Icons.person_add_alt_1_rounded),
                        label: Text(
                          _savingCustomer ? 'جارٍ الحفظ…' : 'حفظ الزبون',
                        ),
                      ),
                    ],
                  ),
                ),
              ],
              if (customer != null) ...[
                const SizedBox(height: 12),
                FinoraSurface(
                  padding: const EdgeInsets.all(12),
                  child: Wrap(
                    spacing: 8,
                    runSpacing: 8,
                    children: [
                      if (customer.id != null)
                        _InfoChip('ID ${customer.id}'),
                      if (customer.balance != null)
                        _InfoChip('رصيد: ${customer.balance}'),
                      if (customer.totalPurchases != null)
                        _InfoChip('مشتريات: ${customer.totalPurchases}'),
                      _InfoChip('طلبات: ${customer.openOrdersCount}'),
                      if (customer.blacklisted)
                        const _InfoChip('قائمة سوداء', warn: true),
                    ],
                  ),
                ),
                if (customer.lastOrder != null || customer.lastNote != null) ...[
                  const SizedBox(height: 10),
                  FinoraSurface(
                    padding: const EdgeInsets.all(12),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        if (customer.lastOrder != null)
                          Text('آخر طلب: ${customer.lastOrder}'),
                        if (customer.lastNote != null)
                          Padding(
                            padding: const EdgeInsets.only(top: 4),
                            child: Text('آخر ملاحظة: ${customer.lastNote}'),
                          ),
                      ],
                    ),
                  ),
                ],
              ],
              const SizedBox(height: 16),
              const FinoraSectionHeader('أثناء المكالمة'),
              TextField(
                controller: _noteCtrl,
                focusNode: _noteFocus,
                maxLines: 3,
                decoration: const InputDecoration(
                  labelText: 'ملاحظات أثناء المكالمة',
                ),
                onChanged: (v) =>
                    ref.read(activeCallProvider.notifier).setNoteDraft(v),
              ),
              const SizedBox(height: 10),
              Row(
                children: [
                  Expanded(
                    child: FilledButton.tonal(
                      onPressed: _saveNote,
                      child: const Text('حفظ ملاحظة'),
                    ),
                  ),
                  const SizedBox(width: 8),
                  Expanded(
                    child: OutlinedButton(
                      onPressed: _createTask,
                      child: const Text('مهمة متابعة'),
                    ),
                  ),
                ],
              ),
              const SizedBox(height: 16),
              const FinoraSectionHeader('طلب جديد'),
              TextField(
                controller: _productCtrl,
                decoration: const InputDecoration(
                  labelText: 'بحث منتجات',
                  prefixIcon: Icon(Icons.search_rounded),
                ),
                onChanged: _searchProducts,
              ),
              ..._products.map(
                (p) {
                  final out = p['out_of_stock'] == true;
                  final low = p['low_stock'] == true;
                  final stockLabel = out
                      ? 'نفد المخزون'
                      : (low
                          ? 'مخزون منخفض ${p['quantity']}'
                          : 'مخزون ${p['quantity']}');
                  return Padding(
                    padding: const EdgeInsets.only(top: 8),
                    child: FinoraSurface(
                      padding: const EdgeInsets.symmetric(
                        horizontal: 12,
                        vertical: 8,
                      ),
                      onTap: out ? null : () => _addProduct(p),
                      child: Row(
                        children: [
                          Expanded(
                            child: Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                Text('${p['name']}'),
                                Text(
                                  [
                                    '${p['sale_price']}',
                                    stockLabel,
                                    if ((p['sku'] ?? '').toString().isNotEmpty)
                                      'SKU ${p['sku']}',
                                  ].join(' · '),
                                  style: Theme.of(context)
                                      .textTheme
                                      .bodySmall
                                      ?.copyWith(
                                        color: out
                                            ? AppColors.error
                                            : (low
                                                ? AppColors.warning
                                                : null),
                                      ),
                                ),
                              ],
                            ),
                          ),
                          IconButton(
                            icon: const Icon(Icons.add_circle_outline_rounded),
                            color: out
                                ? AppColors.textMutedLight
                                : AppColors.goldAccent,
                            onPressed: out ? null : () => _addProduct(p),
                          ),
                        ],
                      ),
                    ),
                  );
                },
              ),
              if (_selected.isNotEmpty) ...[
                const SizedBox(height: 10),
                const FinoraSectionHeader('المحدد'),
                ..._selected.entries.map((e) {
                  final p = e.value;
                  final qty = (p['qty'] as num?)?.toInt() ?? 1;
                  return Padding(
                    padding: const EdgeInsets.only(bottom: 8),
                    child: FinoraSurface(
                      padding: const EdgeInsets.symmetric(
                        horizontal: 10,
                        vertical: 6,
                      ),
                      child: Row(
                        children: [
                          Expanded(child: Text('${p['name']}')),
                          IconButton(
                            onPressed: () => _bumpQty(e.key, -1),
                            icon: const Icon(Icons.remove_circle_outline),
                          ),
                          Text('$qty'),
                          IconButton(
                            onPressed: () => _bumpQty(e.key, 1),
                            icon: const Icon(Icons.add_circle_outline),
                          ),
                          IconButton(
                            onPressed: () => setState(() => _selected.remove(e.key)),
                            icon: const Icon(Icons.delete_outline,
                                color: AppColors.error),
                          ),
                        ],
                      ),
                    ),
                  );
                }),
              ],
              FilledButton(
                onPressed: _submittingOrder ? null : _createOrder,
                child: Text(
                  _submittingOrder
                      ? 'جارٍ تأكيد الطلب…'
                      : 'تأكيد وإرسال الطلب',
                ),
              ),
              const SizedBox(height: 8),
              Text(
                'سيظهر الطلب مباشرة في صفحة الطلبات ويُخصم المخزون بعد نجاح التأكيد',
                style: Theme.of(context).textTheme.bodySmall,
                textAlign: TextAlign.center,
              ),
            ],
          ),
        );
      },
    );
  }
}

class _InfoChip extends StatelessWidget {
  const _InfoChip(this.label, {this.warn = false});

  final String label;
  final bool warn;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
      decoration: BoxDecoration(
        color: (warn ? AppColors.error : AppColors.goldAccent).withOpacity(0.12),
        borderRadius: BorderRadius.circular(999),
        border: Border.all(
          color: (warn ? AppColors.error : AppColors.goldAccent)
              .withOpacity(0.35),
        ),
      ),
      child: Text(
        label,
        style: TextStyle(
          fontSize: 12,
          fontWeight: FontWeight.w600,
          color: warn ? AppColors.error : AppColors.goldAccent,
        ),
      ),
    );
  }
}

class AfterCallPage extends ConsumerStatefulWidget {
  const AfterCallPage({super.key});

  @override
  ConsumerState<AfterCallPage> createState() => _AfterCallPageState();
}

class _AfterCallPageState extends ConsumerState<AfterCallPage> {
  late final TextEditingController _noteCtrl;
  String? _outcome;
  DateTime? _followUpAt;
  bool _showMore = false;
  bool _saving = false;

  static const _primary = [
    ('interested', 'مهتم'),
    ('callback_required', 'إعادة اتصال'),
    ('order_created', 'تم الطلب'),
    ('no_answer', 'لا يرد'),
    ('not_interested', 'غير مهتم'),
    ('complaint', 'شكوى'),
  ];
  static const _more = [
    ('busy', 'مشغول'),
    ('wrong_number', 'رقم خطأ'),
    ('support', 'دعم'),
    ('price_inquiry', 'استفسار سعر'),
    ('delivery_inquiry', 'استفسار توصيل'),
    ('cancelled', 'ملغاة'),
    ('other', 'أخرى'),
  ];

  @override
  void initState() {
    super.initState();
    _noteCtrl = TextEditingController(
      text: ref.read(activeCallProvider).noteDraft,
    );
  }

  @override
  void dispose() {
    _noteCtrl.dispose();
    super.dispose();
  }

  Future<void> _dismissWithoutOutcome() async {
    final call = ref.read(activeCallProvider);
    if (call.clientId != null && call.clientId!.isNotEmpty) {
      await ref
          .read(callLogRepositoryProvider)
          .markUnclassified(call.clientId!);
    }
    ref.read(activeCallProvider.notifier).dismissAfterCall();
    if (mounted) Navigator.of(context).maybePop();
  }

  Future<void> _save() async {
    final flags = ref.read(featureFlagsProvider);
    final call = ref.read(activeCallProvider);
    if (flags.callOutcomes && _outcome == null) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('اختر نتيجة المكالمة أو أغلق للتصنيف لاحقاً')),
      );
      return;
    }
    setState(() => _saving = true);
    try {
      final body = _noteCtrl.text.trim();
      if (body.isNotEmpty) {
        final clientId = (call.clientId != null && call.clientId!.isNotEmpty)
            ? 'note-${call.clientId}'
            : const Uuid().v4();
        await ref.read(noteRepositoryProvider).createLocal(
              NoteEntity(
                clientId: clientId,
                body: body,
                callClientId: call.clientId,
                customerId: call.customer?.id,
              ),
            );
      }
      if (flags.callOutcomes &&
          _outcome != null &&
          call.clientId != null &&
          call.clientId!.isNotEmpty) {
        var followAt = _followUpAt;
        if (_outcome == 'callback_required' && followAt == null) {
          final minutes =
              ref.read(phoneBootstrapProvider).missedCallFollowupMinutes;
          followAt = DateTime.now().toUtc().add(Duration(minutes: minutes));
        }
        // Resolve server id from local row if present
        final logs = await ref.read(callLogRepositoryProvider).listLocal();
        final match = logs.where((l) => l.clientId == call.clientId).toList();
        final serverId = match.isNotEmpty ? match.first.serverId : null;
        await ref.read(callLogRepositoryProvider).setOutcome(
              clientId: call.clientId!,
              serverId: serverId,
              outcome: _outcome!,
              outcomeNote: body.isEmpty ? null : body,
              followUpRequired: _outcome == 'callback_required' ||
                  _outcome == 'complaint',
              followUpAt: followAt,
              outcomeClientId: 'outcome-${call.clientId}',
              hasLinkedOrder: _outcome == 'order_created',
            );
        if (_outcome == 'callback_required' || _outcome == 'complaint') {
          await ref.read(taskRepositoryProvider).createLocal(
                TaskEntity(
                  clientId: 'task-outcome-${call.clientId}-$_outcome',
                  title: _outcome == 'complaint' ? 'متابعة شكوى' : 'إعادة اتصال',
                  phone: call.number,
                  customerId: call.customer?.id,
                  dueAt: followAt,
                  source: 'call_outcome',
                  taskType:
                      _outcome == 'complaint' ? 'complaint_followup' : 'callback',
                  reason: _outcome,
                  priority: _outcome == 'complaint' ? 'high' : 'normal',
                ),
              );
        }
      }
      ref.read(activeCallProvider.notifier).dismissAfterCall();
      if (mounted) Navigator.of(context).maybePop();
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final call = ref.watch(activeCallProvider);
    final flags = ref.watch(featureFlagsProvider);
    final duration = call.startedAt == null
        ? 0
        : DateTime.now().difference(call.startedAt!).inSeconds;
    final mm = (duration ~/ 60).toString().padLeft(2, '0');
    final ss = (duration % 60).toString().padLeft(2, '0');
    final chips = [
      ..._primary,
      if (_showMore) ..._more,
    ];

    return FinoraScaffold(
      appBar: AppBar(
        title: const Text('بعد المكالمة'),
        leading: IconButton(
          icon: const Icon(Icons.close),
          onPressed: _dismissWithoutOutcome,
        ),
      ),
      body: SafeArea(
        child: ListView(
          padding: const EdgeInsets.fromLTRB(20, 12, 20, 24),
          children: [
            FinoraSurface(
              child: Row(
                children: [
                  FinoraAvatar(
                    label: call.customer?.name ?? call.number,
                    size: 56,
                    highlighted: true,
                  ),
                  const SizedBox(width: 14),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          call.customer?.name ??
                              (call.number.isEmpty ? 'مكالمة' : call.number),
                          style: Theme.of(context).textTheme.headlineSmall,
                        ),
                        Text('المدة: $mm:$ss'),
                      ],
                    ),
                  ),
                ],
              ),
            ),
            if (flags.callOutcomes) ...[
              const SizedBox(height: 16),
              const FinoraSectionHeader('نتيجة المكالمة'),
              Wrap(
                spacing: 8,
                runSpacing: 8,
                children: [
                  for (final o in chips)
                    ChoiceChip(
                      label: Text(o.$2),
                      selected: _outcome == o.$1,
                      onSelected: (_) => setState(() => _outcome = o.$1),
                    ),
                  ActionChip(
                    label: Text(_showMore ? 'أقل' : 'المزيد'),
                    onPressed: () => setState(() => _showMore = !_showMore),
                  ),
                ],
              ),
              if (_outcome == 'callback_required') ...[
                const SizedBox(height: 10),
                OutlinedButton.icon(
                  onPressed: () async {
                    final now = DateTime.now();
                    final d = await showDatePicker(
                      context: context,
                      firstDate: now,
                      lastDate: now.add(const Duration(days: 30)),
                      initialDate: now,
                    );
                    if (d == null || !mounted) return;
                    final t = await showTimePicker(
                      context: context,
                      initialTime: TimeOfDay.fromDateTime(
                        now.add(const Duration(hours: 1)),
                      ),
                    );
                    if (t == null) return;
                    setState(() {
                      _followUpAt = DateTime(
                        d.year,
                        d.month,
                        d.day,
                        t.hour,
                        t.minute,
                      ).toUtc();
                    });
                  },
                  icon: const Icon(Icons.schedule_rounded),
                  label: Text(
                    _followUpAt == null
                        ? 'موعد المتابعة (افتراضي الشركة)'
                        : _followUpAt!.toLocal().toString(),
                  ),
                ),
              ],
            ],
            const SizedBox(height: 16),
            TextField(
              controller: _noteCtrl,
              maxLines: 3,
              decoration: const InputDecoration(
                labelText: 'ملاحظة مختصرة',
              ),
            ),
            const SizedBox(height: 12),
            FilledButton(
              onPressed: () {
                showModalBottomSheet(
                  context: context,
                  isScrollControlled: true,
                  builder: (_) => const InCallToolsSheet(),
                );
              },
              child: const Text('إنشاء طلب'),
            ),
            const SizedBox(height: 8),
            FilledButton.tonal(
              onPressed: _saving ? null : _save,
              child: Text(_saving ? 'جاري الحفظ…' : 'حفظ'),
            ),
          ],
        ),
      ),
    );
  }
}

/// In-app overlay host when Flutter is foreground.
class IncomingCallBanner extends ConsumerStatefulWidget {
  const IncomingCallBanner({super.key});

  @override
  ConsumerState<IncomingCallBanner> createState() => _IncomingCallBannerState();
}

class _IncomingCallBannerState extends ConsumerState<IncomingCallBanner> {
  bool? _hasOverlay;

  @override
  void initState() {
    super.initState();
    _check();
  }

  Future<void> _check() async {
    final s = await ref.read(permissionsChannelProvider).status();
    if (mounted) setState(() => _hasOverlay = s['overlay'] == true);
  }

  @override
  Widget build(BuildContext context) {
    final call = ref.watch(activeCallProvider);
    // Prefer native overlay; in-app banner only as degrade path.
    if (_hasOverlay == true) return const SizedBox.shrink();
    if (!call.isActive) return const SizedBox.shrink();
    return Material(
      elevation: 10,
      color: AppColors.elevatedDark,
      child: SafeArea(
        bottom: false,
        child: Container(
          decoration: const BoxDecoration(
            border: Border(
              bottom: BorderSide(color: AppColors.hairlineDark),
            ),
          ),
          child: ListTile(
            leading: const Icon(Icons.call_rounded, color: AppColors.goldAccent),
            title: Text(
              call.customer?.name ?? 'مكالمة واردة',
              style: const TextStyle(
                color: Colors.white,
                fontWeight: FontWeight.w800,
                fontFamily: 'Noto Sans Arabic',
              ),
            ),
            subtitle: Text(
              call.number,
              style: const TextStyle(color: Colors.white70),
            ),
            trailing: TextButton(
              onPressed: () {
                showModalBottomSheet(
                  context: context,
                  isScrollControlled: true,
                  builder: (_) => const InCallToolsSheet(),
                );
              },
              child: const Text(
                'أدوات',
                style: TextStyle(color: AppColors.goldAccent),
              ),
            ),
          ),
        ),
      ),
    );
  }
}
