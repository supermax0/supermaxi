import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:intl/intl.dart';
import 'package:uuid/uuid.dart';

import '../../../core/actions/customer_actions.dart';
import '../../../core/di/providers.dart';
import '../../../core/features/feature_flags.dart';
import '../../../core/theme/app_colors.dart';
import '../../../core/ui/finora_ui.dart';
import '../../../domain/entities/entities.dart';
import '../../recording/recording_player.dart';

class CustomerDetailPage extends ConsumerStatefulWidget {
  const CustomerDetailPage({super.key, required this.customer});

  final CustomerEntity customer;

  @override
  ConsumerState<CustomerDetailPage> createState() => _CustomerDetailPageState();
}

class _CustomerDetailPageState extends ConsumerState<CustomerDetailPage> {
  late CustomerEntity _customer;
  Map<String, dynamic>? _timeline;
  List<Map<String, Object?>> _localNotes = const [];
  List<CallLogEntity> _localCalls = const [];
  List<TimelineItem> _items = const [];
  String? _nextCursor;
  bool _hasMore = false;
  bool _loading = true;
  bool _loadingMore = false;
  bool _favorite = false;
  bool _offlineTimeline = false;

  CustomerEntity get c => _customer;

  @override
  void initState() {
    super.initState();
    _customer = widget.customer;
    _load();
  }

  Future<void> _load() async {
    setState(() => _loading = true);
    final db = ref.read(localDatabaseProvider);
    _favorite = await db.isFavorite(
      customerId: c.id,
      phone: c.phone,
    );
    final allCalls = await ref.read(callLogRepositoryProvider).listLocal();
    _localCalls = allCalls
        .where((l) =>
            l.phone.contains(c.phone) ||
            c.phone.contains(l.phone) ||
            (c.id != null && l.customerId == c.id))
        .take(12)
        .toList();
    if (c.id != null) {
      _localNotes = await db.listNotesByCustomer(c.id!);
      final flags = ref.read(featureFlagsProvider);
      if (flags.timeline) {
        _timeline =
            await ref.read(customerRepositoryProvider).timeline(c.id!);
        _parseTimeline(_timeline, append: false);
      } else {
        _timeline = null;
        _items = const [];
      }
    } else {
      _localNotes = const [];
      _timeline = null;
      _items = const [];
    }
    if (mounted) setState(() => _loading = false);
  }

  void _parseTimeline(Map<String, dynamic>? raw, {required bool append}) {
    if (raw == null) {
      if (!append) {
        _items = const [];
        _nextCursor = null;
        _hasMore = false;
      }
      return;
    }
    final list = (raw['items'] as List? ?? [])
        .whereType<Map>()
        .map((e) => TimelineItem.fromJson(Map<String, dynamic>.from(e)))
        .toList();
    final page = raw['pagination'];
    _nextCursor =
        page is Map ? page['next_cursor']?.toString() : null;
    _hasMore = page is Map && page['has_more'] == true;
    _offlineTimeline = raw['offline'] == true;
    if (append) {
      final seen = _items.map((e) => e.id).toSet();
      _items = [
        ..._items,
        ...list.where((e) => !seen.contains(e.id)),
      ];
    } else {
      // Merge local unsynced notes/calls into feed when offline/empty items
      _items = list;
      if (_items.isEmpty) {
        _items = [
          ..._localCalls.map(
            (l) => TimelineItem(
              id: 'local_call_${l.clientId}',
              type: 'call',
              occurredAt: l.startedAt.toLocal(),
              title: l.direction == 'outbound' ? 'مكالمة صادرة' : 'مكالمة واردة',
              summary: '${l.status}${l.outcome != null ? ' · ${l.outcome}' : ''}',
              status: l.status,
            ),
          ),
          ..._localNotes.map(
            (n) => TimelineItem(
              id: 'local_note_${n['client_id']}',
              type: 'note',
              occurredAt: DateTime.tryParse('${n['updated_at'] ?? ''}')
                      ?.toLocal() ??
                  DateTime.now(),
              title: 'ملاحظة محلية',
              summary: '${n['body']}',
              status: n['sync_status']?.toString(),
            ),
          ),
        ];
        _items.sort((a, b) => b.occurredAt.compareTo(a.occurredAt));
      }
    }
  }

  Future<void> _loadMore() async {
    if (_loadingMore || !_hasMore || c.id == null || _nextCursor == null) return;
    setState(() => _loadingMore = true);
    final more = await ref
        .read(customerRepositoryProvider)
        .timeline(c.id!, cursor: _nextCursor);
    _parseTimeline(more, append: true);
    if (mounted) setState(() => _loadingMore = false);
  }

  Future<void> _toggleFavorite() async {
    final db = ref.read(localDatabaseProvider);
    if (_favorite) {
      await db.removeFavorite(customerId: c.id, phone: c.phone);
    } else {
      await db.addFavorite(
        customerId: c.id,
        phone: c.phone,
        name: c.name,
      );
    }
    setState(() => _favorite = !_favorite);
  }

  Future<void> _addNote() async {
    final ctrl = TextEditingController();
    final ok = await showModalBottomSheet<bool>(
      context: context,
      isScrollControlled: true,
      builder: (ctx) => Padding(
        padding: EdgeInsets.only(
          left: 20,
          right: 20,
          top: 12,
          bottom: MediaQuery.of(ctx).viewInsets.bottom + 20,
        ),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Text('ملاحظة جديدة', style: Theme.of(ctx).textTheme.headlineSmall),
            const SizedBox(height: 12),
            TextField(
              controller: ctrl,
              maxLines: 4,
              decoration: const InputDecoration(hintText: 'نص الملاحظة'),
              autofocus: true,
            ),
            const SizedBox(height: 14),
            FilledButton(
              onPressed: () => Navigator.pop(ctx, true),
              child: const Text('حفظ'),
            ),
          ],
        ),
      ),
    );
    if (ok == true && ctrl.text.trim().isNotEmpty) {
      await ref.read(noteRepositoryProvider).createLocal(
            NoteEntity(
              clientId: const Uuid().v4(),
              body: ctrl.text.trim(),
              customerId: c.id,
            ),
          );
      await _load();
    }
  }

  Future<void> _editCustomer() async {
    if (c.id == null) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('انتظر مزامنة الزبون أولاً للتعديل')),
      );
      return;
    }
    final nameCtrl = TextEditingController(text: c.name);
    final cityCtrl = TextEditingController(text: c.city);
    final addressCtrl = TextEditingController(text: c.address);
    final notesCtrl = TextEditingController(text: c.notes);
    final ok = await showModalBottomSheet<bool>(
      context: context,
      isScrollControlled: true,
      builder: (ctx) => Padding(
        padding: EdgeInsets.only(
          left: 20,
          right: 20,
          top: 12,
          bottom: MediaQuery.of(ctx).viewInsets.bottom + 20,
        ),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Text('تعديل الزبون', style: Theme.of(ctx).textTheme.headlineSmall),
            const SizedBox(height: 12),
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
            const SizedBox(height: 10),
            TextField(
              controller: notesCtrl,
              maxLines: 2,
              decoration: const InputDecoration(labelText: 'ملاحظات ثابتة'),
            ),
            const SizedBox(height: 14),
            FilledButton(
              onPressed: () => Navigator.pop(ctx, true),
              child: const Text('حفظ'),
            ),
          ],
        ),
      ),
    );
    if (ok != true) return;
    try {
      final updated = await ref.read(customerRepositoryProvider).updateCustomer(
            customerId: c.id!,
            name: nameCtrl.text.trim(),
            city: cityCtrl.text.trim(),
            address: addressCtrl.text.trim(),
            notes: notesCtrl.text.trim(),
          );
      if (updated != null && mounted) {
        setState(() => _customer = updated);
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('تم تحديث الزبون')),
        );
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('فشل التحديث: $e')),
        );
      }
    }
  }

  IconData _iconFor(String type) {
    return switch (type) {
      'call' => Icons.call_rounded,
      'note' => Icons.sticky_note_2_outlined,
      'task' => Icons.task_alt_rounded,
      'invoice' || 'order' => Icons.receipt_long_rounded,
      'payment' => Icons.payments_outlined,
      'order_status' => Icons.sync_alt_rounded,
      'customer_created' => Icons.person_add_alt_1_rounded,
      _ => Icons.circle_outlined,
    };
  }

  @override
  Widget build(BuildContext context) {
    final fmt = DateFormat('yyyy/MM/dd HH:mm');
    final flags = ref.watch(featureFlagsProvider);
    return FinoraScaffold(
      appBar: AppBar(
        title: Text(c.name),
        actions: [
          IconButton(
            tooltip: 'تعديل',
            onPressed: _editCustomer,
            icon: const Icon(Icons.edit_outlined),
          ),
          IconButton(
            tooltip: _favorite ? 'إزالة من المفضلة' : 'إضافة للمفضلة',
            onPressed: _toggleFavorite,
            icon: Icon(
              _favorite ? Icons.star_rounded : Icons.star_outline_rounded,
              color: AppColors.goldAccent,
            ),
          ),
        ],
      ),
      floatingActionButton: FloatingActionButton.extended(
        onPressed: _addNote,
        icon: const Icon(Icons.note_add_outlined),
        label: const Text('ملاحظة'),
      ),
      body: SafeArea(
        child: _loading
            ? const Center(child: CircularProgressIndicator())
            : ListView(
                padding: const EdgeInsets.fromLTRB(16, 56, 16, 100),
                children: [
                  FinoraSurface(
                    child: Row(
                      children: [
                        FinoraAvatar(
                          label: c.name,
                          size: 64,
                          highlighted: c.vip || _favorite,
                        ),
                        const SizedBox(width: 14),
                        Expanded(
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Text(
                                c.name,
                                style:
                                    Theme.of(context).textTheme.headlineSmall,
                              ),
                              Text(c.phone),
                              if (c.city.isNotEmpty || c.address.isNotEmpty)
                                Text(
                                  [c.city, c.address]
                                      .where((e) => e.isNotEmpty)
                                      .join(' · '),
                                  style: Theme.of(context).textTheme.bodySmall,
                                ),
                            ],
                          ),
                        ),
                      ],
                    ),
                  ),
                  const SizedBox(height: 12),
                  Row(
                    children: [
                      Expanded(
                        child: FilledButton.icon(
                          onPressed: () => CustomerActions.dial(ref, c.phone),
                          icon: const Icon(Icons.call_rounded),
                          label: const Text('اتصال'),
                        ),
                      ),
                      const SizedBox(width: 8),
                      Expanded(
                        child: OutlinedButton.icon(
                          onPressed: () async {
                            final ok =
                                await CustomerActions.openWhatsApp(c.phone);
                            if (!ok && context.mounted) {
                              ScaffoldMessenger.of(context).showSnackBar(
                                const SnackBar(
                                  content: Text('تعذر فتح واتساب'),
                                ),
                              );
                            }
                          },
                          icon: const Icon(Icons.chat_rounded),
                          label: const Text('واتساب'),
                        ),
                      ),
                    ],
                  ),
                  const SizedBox(height: 16),
                  FinoraSurface(
                    padding: const EdgeInsets.all(14),
                    child: Wrap(
                      spacing: 10,
                      runSpacing: 10,
                      children: [
                        if (c.balance != null)
                          _StatChip('الرصيد', '${c.balance}'),
                        if (c.totalPurchases != null)
                          _StatChip('المشتريات', '${c.totalPurchases}'),
                        _StatChip('طلبات مفتوحة', '${c.openOrdersCount}'),
                        if (c.vip) const _StatChip('VIP', 'نعم'),
                        if (c.blacklisted)
                          const _StatChip('قائمة سوداء', 'نعم', warn: true),
                        if (c.deliveryStatus != null)
                          _StatChip('التوصيل', c.deliveryStatus!),
                      ],
                    ),
                  ),
                  if (c.lastNote != null && c.lastNote!.isNotEmpty) ...[
                    const SizedBox(height: 14),
                    const FinoraSectionHeader('آخر ملاحظة'),
                    FinoraSurface(child: Text(c.lastNote!)),
                  ],
                  if (flags.timeline) ...[
                    const SizedBox(height: 14),
                    Row(
                      children: [
                        const Expanded(
                          child: FinoraSectionHeader('الخط الزمني'),
                        ),
                        if (_offlineTimeline)
                          Text(
                            'offline',
                            style: Theme.of(context).textTheme.bodySmall,
                          ),
                      ],
                    ),
                    if (_items.isEmpty)
                      const FinoraSurface(
                        child: Text('لا أحداث بعد في الخط الزمني'),
                      )
                    else
                      ..._groupedTimeline(fmt),
                    if (_hasMore)
                      Padding(
                        padding: const EdgeInsets.only(top: 8),
                        child: OutlinedButton(
                          onPressed: _loadingMore ? null : _loadMore,
                          child: Text(
                            _loadingMore ? 'جاري التحميل…' : 'تحميل المزيد',
                          ),
                        ),
                      ),
                  ] else ...[
                    // Legacy sections when timeline flag off
                    const SizedBox(height: 14),
                    const FinoraSectionHeader('المكالمات'),
                    if (_localCalls.isEmpty)
                      const FinoraSurface(child: Text('لا مكالمات'))
                    else
                      ..._localCalls.map(
                        (log) => Padding(
                          padding: const EdgeInsets.only(bottom: 8),
                          child: FinoraSurface(
                            padding: const EdgeInsets.all(12),
                            child: Text(
                              [
                                log.direction == 'outbound' ? 'صادرة' : 'واردة',
                                log.status,
                                fmt.format(log.startedAt.toLocal()),
                              ].join(' · '),
                            ),
                          ),
                        ),
                      ),
                  ],
                ],
              ),
      ),
    );
  }

  List<Widget> _groupedTimeline(DateFormat fmt) {
    final byDay = <String, List<TimelineItem>>{};
    final dayFmt = DateFormat('yyyy/MM/dd');
    for (final item in _items) {
      final key = dayFmt.format(item.occurredAt);
      byDay.putIfAbsent(key, () => []).add(item);
    }
    final widgets = <Widget>[];
    for (final entry in byDay.entries) {
      widgets.add(
        Padding(
          padding: const EdgeInsets.only(top: 8, bottom: 6),
          child: Text(
            entry.key,
            style: const TextStyle(
              fontWeight: FontWeight.w700,
              color: AppColors.goldAccent,
            ),
          ),
        ),
      );
      for (final item in entry.value) {
        final hasRecording = item.type == 'call' &&
            item.referenceId != null &&
            item.metadata['has_recording'] == true;
        widgets.add(
          Padding(
            padding: const EdgeInsets.only(bottom: 8),
            child: FinoraSurface(
              padding: const EdgeInsets.all(12),
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Icon(_iconFor(item.type), color: AppColors.goldAccent),
                  const SizedBox(width: 10),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          item.title,
                          style: const TextStyle(fontWeight: FontWeight.w700),
                        ),
                        Text(item.summary),
                        Text(
                          [
                            fmt.format(item.occurredAt),
                            if (item.employeeName != null) item.employeeName!,
                            if (item.status != null) item.status!,
                          ].join(' · '),
                          style: Theme.of(context).textTheme.bodySmall,
                        ),
                      ],
                    ),
                  ),
                  if (hasRecording)
                    IconButton(
                      tooltip: 'تشغيل التسجيل',
                      icon: const Icon(Icons.play_circle_fill_rounded,
                          color: AppColors.goldAccent, size: 30),
                      onPressed: () => showRecordingPlayer(
                        context,
                        callId: item.referenceId!,
                      ),
                    ),
                ],
              ),
            ),
          ),
        );
      }
    }
    return widgets;
  }
}

class _StatChip extends StatelessWidget {
  const _StatChip(this.label, this.value, {this.warn = false});

  final String label;
  final String value;
  final bool warn;

  @override
  Widget build(BuildContext context) {
    final color = warn ? AppColors.error : AppColors.goldAccent;
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
      decoration: BoxDecoration(
        color: color.withOpacity(0.12),
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: color.withOpacity(0.3)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(label, style: TextStyle(fontSize: 11, color: color)),
          Text(
            value,
            style: const TextStyle(fontWeight: FontWeight.w700, fontSize: 14),
          ),
        ],
      ),
    );
  }
}
