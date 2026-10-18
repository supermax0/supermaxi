import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:intl/intl.dart';

import '../../../core/di/providers.dart';
import '../../../core/features/feature_flags.dart';
import '../../../core/ui/finora_ui.dart';
import '../../../domain/entities/entities.dart';

class UnclassifiedCallsPage extends ConsumerStatefulWidget {
  const UnclassifiedCallsPage({super.key});

  @override
  ConsumerState<UnclassifiedCallsPage> createState() =>
      _UnclassifiedCallsPageState();
}

class _UnclassifiedCallsPageState extends ConsumerState<UnclassifiedCallsPage> {
  List<CallLogEntity> _rows = const [];
  bool _loading = true;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    setState(() => _loading = true);
    final rows =
        await ref.read(callLogRepositoryProvider).listUnclassified();
    if (mounted) {
      setState(() {
        _rows = rows;
        _loading = false;
      });
    }
  }

  Future<void> _classify(CallLogEntity log) async {
    String? selected;
    final ok = await showModalBottomSheet<bool>(
      context: context,
      builder: (ctx) {
        return StatefulBuilder(
          builder: (ctx, setLocal) {
            return Padding(
              padding: const EdgeInsets.all(20),
              child: Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  Text('تصنيف المكالمة',
                      style: Theme.of(ctx).textTheme.headlineSmall),
                  const SizedBox(height: 12),
                  Wrap(
                    spacing: 8,
                    children: [
                      for (final o in [
                        'interested',
                        'callback_required',
                        'no_answer',
                        'not_interested',
                        'complaint',
                        'other',
                      ])
                        ChoiceChip(
                          label: Text(o),
                          selected: selected == o,
                          onSelected: (_) => setLocal(() => selected = o),
                        ),
                    ],
                  ),
                  const SizedBox(height: 14),
                  FilledButton(
                    onPressed: () => Navigator.pop(ctx, true),
                    child: const Text('حفظ'),
                  ),
                ],
              ),
            );
          },
        );
      },
    );
    if (ok != true || selected == null) return;
    await ref.read(callLogRepositoryProvider).setOutcome(
          clientId: log.clientId,
          serverId: log.serverId,
          outcome: selected!,
          outcomeClientId:
              'outcome-unclassified-${log.clientId}-${DateTime.now().millisecondsSinceEpoch}',
        );
    await _load();
  }

  @override
  Widget build(BuildContext context) {
    final flags = ref.watch(featureFlagsProvider);
    final fmt = DateFormat('yyyy/MM/dd HH:mm');
    if (!flags.callOutcomes) {
      return const FinoraScaffold(
        body: Center(child: Text('نتائج المكالمة غير مفعّلة')),
      );
    }
    return FinoraScaffold(
      appBar: AppBar(title: const Text('مكالمات غير مصنّفة')),
      body: SafeArea(
        child: _loading
            ? const Center(child: CircularProgressIndicator())
            : _rows.isEmpty
                ? const Center(child: Text('لا توجد مكالمات بانتظار التصنيف'))
                : ListView.separated(
                    padding: const EdgeInsets.all(16),
                    itemCount: _rows.length,
                    separatorBuilder: (_, __) => const SizedBox(height: 8),
                    itemBuilder: (_, i) {
                      final log = _rows[i];
                      return FinoraSurface(
                        child: ListTile(
                          title: Text(log.customerName ?? log.phone),
                          subtitle: Text(
                            '${log.status} · ${fmt.format(log.startedAt.toLocal())}',
                          ),
                          trailing: const Icon(Icons.chevron_left),
                          onTap: () => _classify(log),
                        ),
                      );
                    },
                  ),
      ),
    );
  }
}
