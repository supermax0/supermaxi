import 'dart:async';

import 'package:flutter/material.dart';
import 'package:video_player/video_player.dart';

import '../../../core/config/app_config.dart';
import '../../../core/theme/app_colors.dart';
import '../data/feed_controller.dart';

/// Owns one feed player and guarantees that playback is limited to the visible
/// page, active app lifecycle and enabled navigation branch.
class FeedVideoPlayer extends StatefulWidget {
  const FeedVideoPlayer({
    super.key,
    required this.video,
    required this.isActive,
    required this.shouldWarm,
    required this.onDoubleTapLike,
  });

  final FeedVideo video;
  final bool isActive;
  final bool shouldWarm;
  final VoidCallback onDoubleTapLike;

  @override
  State<FeedVideoPlayer> createState() => FeedVideoPlayerState();
}

class FeedVideoPlayerState extends State<FeedVideoPlayer>
    with WidgetsBindingObserver {
  static const _doubleTapWindow = Duration(milliseconds: 280);
  static const _tapSlop = 18.0;

  VideoPlayerController? _controller;
  bool _ready = false;
  bool _failed = false;
  bool _manuallyPaused = false;
  bool _tickerEnabled = true;
  bool _appIsActive = true;
  String? _boundUrl;

  int _tapCount = 0;
  Timer? _doubleTapTimer;
  bool _showPauseFlash = false;
  bool _showLikeHeart = false;
  Timer? _pauseFlashTimer;
  Timer? _likeHeartTimer;

  Offset? _pointerDown;
  int? _pointerDownMs;

  bool get _shouldPlay =>
      widget.isActive &&
      widget.shouldWarm &&
      _tickerEnabled &&
      _appIsActive &&
      !_manuallyPaused;

  bool get isManuallyPaused => _manuallyPaused;

  /// Called from the feed tap layer above overlays.
  void toggleFromUserTap() => _handleTap();

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    if (widget.shouldWarm) _ensureController();
  }

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    final enabled = TickerMode.of(context);
    if (_tickerEnabled != enabled) {
      _tickerEnabled = enabled;
      _syncPlayback();
    }
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    _appIsActive = state == AppLifecycleState.resumed;
    _syncPlayback();
  }

  @override
  void didUpdateWidget(covariant FeedVideoPlayer oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (!widget.shouldWarm) {
      _disposeController();
      return;
    }
    if (widget.video.playbackUrl != _boundUrl) {
      _manuallyPaused = false;
      _disposeController();
    }
    _ensureController();
    _syncPlayback();
  }

  Future<void> _ensureController() async {
    if (!widget.shouldWarm || widget.video.playbackUrl.isEmpty) return;
    if (_controller != null) {
      await _syncPlayback();
      return;
    }

    final url = widget.video.playbackUrl;
    _boundUrl = url;
    final controller = VideoPlayerController.networkUrl(
      Uri.parse(url),
      httpHeaders: const {'X-Tenant-Slug': AppConfig.tenantSlug},
      videoPlayerOptions: VideoPlayerOptions(mixWithOthers: false),
    );
    _controller = controller;
    try {
      await controller.initialize();
      await controller.setLooping(true);
      if (!mounted || _controller != controller) {
        await controller.dispose();
        return;
      }
      setState(() {
        _ready = true;
        _failed = false;
      });
      await _syncPlayback();
    } catch (_) {
      if (mounted && _controller == controller) {
        setState(() {
          _failed = true;
          _ready = false;
        });
      }
      await controller.dispose();
      if (_controller == controller) {
        _controller = null;
        _boundUrl = null;
      }
    }
  }

  Future<void> _syncPlayback() async {
    final controller = _controller;
    if (controller == null || !_ready || !controller.value.isInitialized) {
      return;
    }
    try {
      if (_shouldPlay) {
        await controller.setVolume(1);
        await controller.play();
      } else {
        // Pause first so the UI freezes immediately.
        await controller.pause();
        await controller.setVolume(0);
      }
    } catch (_) {
      // A controller can be disposed while an async platform command is in flight.
    }
  }

  Future<void> _togglePlayback({bool flashPauseOnResume = true}) async {
    if (_controller == null || !_ready || !widget.isActive) return;
    final willResume = _manuallyPaused;
    setState(() => _manuallyPaused = !_manuallyPaused);
    if (willResume && flashPauseOnResume) {
      _flashPauseIcon();
    }
    await _syncPlayback();
  }

  void _flashPauseIcon() {
    _pauseFlashTimer?.cancel();
    setState(() => _showPauseFlash = true);
    _pauseFlashTimer = Timer(const Duration(milliseconds: 420), () {
      if (!mounted) return;
      setState(() => _showPauseFlash = false);
    });
  }

  void _flashLikeHeart() {
    _likeHeartTimer?.cancel();
    setState(() => _showLikeHeart = true);
    _likeHeartTimer = Timer(const Duration(milliseconds: 650), () {
      if (!mounted) return;
      setState(() => _showLikeHeart = false);
    });
  }

  /// Instant single-tap pause/play. A second tap inside [_doubleTapWindow]
  /// undoes the first toggle and fires like — so double-tap never waits to pause.
  void _handleTap() {
    if (_controller == null || !_ready || !widget.isActive) return;

    _tapCount += 1;
    if (_tapCount == 1) {
      _togglePlayback();
      _doubleTapTimer?.cancel();
      _doubleTapTimer = Timer(_doubleTapWindow, () {
        _tapCount = 0;
      });
      return;
    }

    if (_tapCount >= 2) {
      _doubleTapTimer?.cancel();
      _tapCount = 0;
      // Undo the immediate toggle from the first tap of the pair.
      _togglePlayback(flashPauseOnResume: false);
      widget.onDoubleTapLike();
      _flashLikeHeart();
    }
  }

  void _onPointerDown(PointerDownEvent event) {
    _pointerDown = event.localPosition;
    _pointerDownMs = DateTime.now().millisecondsSinceEpoch;
  }

  void _onPointerUp(PointerUpEvent event) {
    final down = _pointerDown;
    final downMs = _pointerDownMs;
    _pointerDown = null;
    _pointerDownMs = null;
    if (down == null || downMs == null) return;
    final moved = (event.localPosition - down).distance;
    final elapsed = DateTime.now().millisecondsSinceEpoch - downMs;
    // Ignore scrolls / long presses; accept quick taps only.
    if (moved > _tapSlop || elapsed > 450) return;
    _handleTap();
  }

  void _onPointerCancel(PointerCancelEvent event) {
    _pointerDown = null;
    _pointerDownMs = null;
  }

  void _retry() {
    _disposeController();
    if (mounted) setState(() {});
    _ensureController();
  }

  void _disposeController() {
    final controller = _controller;
    _controller = null;
    _boundUrl = null;
    _ready = false;
    _failed = false;
    controller?.pause();
    controller?.setVolume(0);
    controller?.dispose();
  }

  @override
  void dispose() {
    _doubleTapTimer?.cancel();
    _pauseFlashTimer?.cancel();
    _likeHeartTimer?.cancel();
    WidgetsBinding.instance.removeObserver(this);
    _disposeController();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final controller = _controller;
    return Semantics(
      button: true,
      label: _manuallyPaused ? 'تشغيل الفيديو' : 'إيقاف الفيديو',
      child: Listener(
        behavior: HitTestBehavior.opaque,
        onPointerDown: _onPointerDown,
        onPointerUp: _onPointerUp,
        onPointerCancel: _onPointerCancel,
        child: ColoredBox(
          color: AppColors.primaryDark,
          child: Stack(
            fit: StackFit.expand,
            children: [
              if (widget.video.thumbnailUrl?.isNotEmpty == true)
                Image.network(
                  widget.video.thumbnailUrl!,
                  fit: BoxFit.cover,
                  headers: const {'X-Tenant-Slug': AppConfig.tenantSlug},
                  errorBuilder: (_, __, ___) => const SizedBox.shrink(),
                ),
              if (_ready && controller != null)
                FittedBox(
                  fit: BoxFit.cover,
                  child: SizedBox(
                    width: controller.value.size.width,
                    height: controller.value.size.height,
                    child: VideoPlayer(controller),
                  ),
                )
              else if (_failed)
                Center(
                  child: FilledButton.tonalIcon(
                    onPressed: _retry,
                    icon: const Icon(Icons.refresh_rounded),
                    label: const Text('إعادة تشغيل الفيديو'),
                  ),
                )
              else
                const Center(
                  child: CircularProgressIndicator(
                    color: AppColors.goldAccent,
                    strokeWidth: 2.5,
                  ),
                ),
              if (_ready && controller != null)
                ValueListenableBuilder<VideoPlayerValue>(
                  valueListenable: controller,
                  builder: (context, value, _) {
                    final paused = !value.isPlaying;
                    final durationMs = value.duration.inMilliseconds;
                    final progress = durationMs <= 0
                        ? 0.0
                        : (value.position.inMilliseconds / durationMs)
                            .clamp(0.0, 1.0);
                    final showPlay = paused && widget.isActive;
                    final showCenterIcon = showPlay || _showPauseFlash;
                    return Stack(
                      children: [
                        Center(
                          child: AnimatedScale(
                            scale: showCenterIcon ? 1 : 0.78,
                            duration: const Duration(milliseconds: 160),
                            curve: Curves.easeOutBack,
                            child: AnimatedOpacity(
                              opacity: showCenterIcon ? 1 : 0,
                              duration: const Duration(milliseconds: 140),
                              child: Container(
                                width: 72,
                                height: 72,
                                decoration: BoxDecoration(
                                  color: const Color(0x99000000),
                                  shape: BoxShape.circle,
                                  border: Border.all(color: Colors.white24),
                                ),
                                child: Icon(
                                  showPlay
                                      ? Icons.play_arrow_rounded
                                      : Icons.pause_rounded,
                                  color: Colors.white,
                                  size: 42,
                                ),
                              ),
                            ),
                          ),
                        ),
                        Align(
                          alignment: Alignment.bottomCenter,
                          child: LinearProgressIndicator(
                            value: progress,
                            minHeight: 2,
                            backgroundColor: Colors.white12,
                            valueColor: const AlwaysStoppedAnimation(
                              AppColors.goldAccent,
                            ),
                          ),
                        ),
                      ],
                    );
                  },
                ),
              IgnorePointer(
                child: Center(
                  child: AnimatedScale(
                    scale: _showLikeHeart ? 1 : 0.55,
                    duration: const Duration(milliseconds: 220),
                    curve: Curves.easeOutBack,
                    child: AnimatedOpacity(
                      opacity: _showLikeHeart ? 1 : 0,
                      duration: const Duration(milliseconds: 180),
                      child: const Icon(
                        Icons.favorite_rounded,
                        color: Color(0xE6FF3B5C),
                        size: 96,
                        shadows: [
                          Shadow(
                            color: Color(0x66000000),
                            blurRadius: 18,
                          ),
                        ],
                      ),
                    ),
                  ),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
