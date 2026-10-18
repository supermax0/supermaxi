import 'dart:async';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:path_provider/path_provider.dart';

import '../../core/di/providers.dart';
import '../../core/theme/app_colors.dart';
import '../../core/ui/finora_ui.dart';
import '../../platform/call_event_channel.dart';

/// Bottom sheet that downloads a call recording (authenticated) and plays it
/// through the native MediaPlayer bridge — no third-party audio plugins.
Future<void> showRecordingPlayer(BuildContext context, {required int callId}) {
  return showModalBottomSheet(
    context: context,
    useRootNavigator: true,
    backgroundColor: Colors.transparent,
    builder: (ctx) => Padding(
      padding: EdgeInsets.only(bottom: MediaQuery.of(ctx).viewPadding.bottom),
      child: RecordingPlayerSheet(callId: callId),
    ),
  );
}

class RecordingPlayerSheet extends ConsumerStatefulWidget {
  const RecordingPlayerSheet({super.key, required this.callId});

  final int callId;

  @override
  ConsumerState<RecordingPlayerSheet> createState() =>
      _RecordingPlayerSheetState();
}

class _RecordingPlayerSheetState extends ConsumerState<RecordingPlayerSheet> {
  late final PermissionsChannel _channel =
      ref.read(permissionsChannelProvider);
  Timer? _ticker;
  bool _loading = true;
  String? _error;
  int _durationMs = 0;
  int _positionMs = 0;
  bool _playing = false;
  bool _completed = false;

  @override
  void initState() {
    super.initState();
    _prepare();
  }

  @override
  void dispose() {
    _ticker?.cancel();
    _channel.playerStop();
    super.dispose();
  }

  Future<void> _prepare() async {
    try {
      final dir = await getTemporaryDirectory();
      final file = File('${dir.path}/call_rec_${widget.callId}.m4a');
      if (!file.existsSync() || file.lengthSync() == 0) {
        final dio = ref.read(apiClientProvider).dio;
        await dio.download(
          '/api/phone/v1/calls/${widget.callId}/recording',
          file.path,
        );
      }
      final duration = await _channel.playerOpen(file.path);
      if (duration == null) {
        throw Exception('unplayable');
      }
      if (!mounted) return;
      setState(() {
        _durationMs = duration;
        _loading = false;
      });
      _ticker = Timer.periodic(const Duration(milliseconds: 400), (_) => _poll());
    } catch (_) {
      if (mounted) {
        setState(() {
          _loading = false;
          _error = 'تعذر تحميل التسجيل — تحقق من الاتصال';
        });
      }
    }
  }

  Future<void> _poll() async {
    final state = await _channel.playerState();
    if (!mounted || state.isEmpty) return;
    setState(() {
      _positionMs = (state['positionMs'] as num?)?.toInt() ?? _positionMs;
      final d = (state['durationMs'] as num?)?.toInt() ?? 0;
      if (d > 0) _durationMs = d;
      _playing = state['playing'] == true;
      _completed = state['completed'] == true;
    });
  }

  Future<void> _toggle() async {
    if (_completed) {
      await _channel.playerSeek(0);
      await _channel.playerPlay();
    } else if (_playing) {
      await _channel.playerPause();
    } else {
      await _channel.playerPlay();
    }
    await _poll();
  }

  String _fmt(int ms) {
    final total = (ms / 1000).floor();
    final m = (total ~/ 60).toString().padLeft(2, '0');
    final s = (total % 60).toString().padLeft(2, '0');
    return '$m:$s';
  }

  @override
  Widget build(BuildContext context) {
    return Container(
      margin: const EdgeInsets.all(12),
      child: FinoraSurface(
        padding: const EdgeInsets.fromLTRB(20, 18, 20, 22),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Row(
              children: [
                const Icon(Icons.graphic_eq_rounded,
                    color: AppColors.goldAccent),
                const SizedBox(width: 8),
                const Expanded(
                  child: Text(
                    'تسجيل المكالمة',
                    style: TextStyle(fontWeight: FontWeight.w700, fontSize: 16),
                  ),
                ),
                IconButton(
                  onPressed: () => Navigator.of(context).pop(),
                  icon: const Icon(Icons.close_rounded),
                ),
              ],
            ),
            const SizedBox(height: 8),
            if (_loading)
              const Padding(
                padding: EdgeInsets.symmetric(vertical: 24),
                child: CircularProgressIndicator(),
              )
            else if (_error != null)
              Padding(
                padding: const EdgeInsets.symmetric(vertical: 20),
                child: Text(
                  _error!,
                  style: const TextStyle(color: AppColors.error),
                  textAlign: TextAlign.center,
                ),
              )
            else ...[
              Slider(
                value: _durationMs <= 0
                    ? 0
                    : _positionMs.clamp(0, _durationMs).toDouble(),
                max: _durationMs <= 0 ? 1 : _durationMs.toDouble(),
                activeColor: AppColors.goldAccent,
                onChanged: (v) {
                  setState(() => _positionMs = v.round());
                },
                onChangeEnd: (v) => _channel.playerSeek(v.round()),
              ),
              Row(
                mainAxisAlignment: MainAxisAlignment.spaceBetween,
                children: [
                  Text(_fmt(_positionMs),
                      style: Theme.of(context).textTheme.bodySmall),
                  Text(_fmt(_durationMs),
                      style: Theme.of(context).textTheme.bodySmall),
                ],
              ),
              const SizedBox(height: 6),
              FilledButton.icon(
                onPressed: _toggle,
                icon: Icon(
                  _completed
                      ? Icons.replay_rounded
                      : _playing
                          ? Icons.pause_rounded
                          : Icons.play_arrow_rounded,
                ),
                label: Text(
                  _completed
                      ? 'إعادة'
                      : _playing
                          ? 'إيقاف مؤقت'
                          : 'تشغيل',
                ),
              ),
            ],
          ],
        ),
      ),
    );
  }
}
