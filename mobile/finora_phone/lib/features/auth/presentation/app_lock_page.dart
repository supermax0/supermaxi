import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:local_auth/local_auth.dart';

import '../../../core/di/providers.dart';
import '../../../core/theme/app_colors.dart';
import '../../../core/ui/finora_ui.dart';
import '../data/app_lock_controller.dart';

class AppLockPage extends ConsumerStatefulWidget {
  const AppLockPage({super.key});

  @override
  ConsumerState<AppLockPage> createState() => _AppLockPageState();
}

class _AppLockPageState extends ConsumerState<AppLockPage> {
  final _pinCtrl = TextEditingController();
  String? _error;
  bool _busy = false;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) => _tryBio());
  }

  @override
  void dispose() {
    _pinCtrl.dispose();
    super.dispose();
  }

  Future<void> _tryBio() async {
    final storage = ref.read(tokenStorageProvider);
    if (!await storage.isBiometricEnabled()) return;
    setState(() => _busy = true);
    try {
      final ok = await LocalAuthentication().authenticate(
        localizedReason: 'فتح Finora Phone',
        options: const AuthenticationOptions(
          stickyAuth: true,
          biometricOnly: false,
        ),
      );
      if (ok) {
        ref.read(appLockProvider.notifier).unlock();
      }
    } catch (_) {
      // Fall back to PIN.
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _submitPin() async {
    final pin = _pinCtrl.text.trim();
    final stored = await ref.read(tokenStorageProvider).readPin();
    if (stored == null || stored.isEmpty) {
      // Bio-only lock without PIN — allow bio retry.
      await _tryBio();
      return;
    }
    if (pin == stored) {
      HapticFeedback.lightImpact();
      ref.read(appLockProvider.notifier).unlock();
    } else {
      HapticFeedback.heavyImpact();
      setState(() => _error = 'PIN غير صحيح');
      _pinCtrl.clear();
    }
  }

  @override
  Widget build(BuildContext context) {
    return FinoraScaffold(
      body: SafeArea(
        child: Padding(
          padding: const EdgeInsets.all(28),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              const Spacer(),
              const FinoraBrandMark(compact: true),
              const SizedBox(height: 28),
              Text(
                'التطبيق مقفل',
                style: Theme.of(context).textTheme.headlineSmall,
                textAlign: TextAlign.center,
              ),
              const SizedBox(height: 8),
              Text(
                'أدخل PIN أو استخدم البصمة للمتابعة',
                style: Theme.of(context).textTheme.bodyMedium,
                textAlign: TextAlign.center,
              ),
              const SizedBox(height: 28),
              FinoraSurface(
                child: TextField(
                  controller: _pinCtrl,
                  obscureText: true,
                  keyboardType: TextInputType.number,
                  maxLength: 6,
                  textAlign: TextAlign.center,
                  decoration: InputDecoration(
                    hintText: '••••',
                    counterText: '',
                    errorText: _error,
                    border: InputBorder.none,
                  ),
                  onSubmitted: (_) => _submitPin(),
                ),
              ),
              const SizedBox(height: 16),
              FilledButton(
                onPressed: _busy ? null : _submitPin,
                child: const Text('فتح'),
              ),
              const SizedBox(height: 10),
              OutlinedButton.icon(
                onPressed: _busy ? null : _tryBio,
                icon: const Icon(Icons.fingerprint),
                label: const Text('بصمة / وجه'),
              ),
              const Spacer(),
              Text(
                'المكالمات لا تتأثر — هذا قفل لواجهة Finora فقط',
                style: Theme.of(context).textTheme.bodySmall?.copyWith(
                      color: AppColors.textMutedLight,
                    ),
                textAlign: TextAlign.center,
              ),
            ],
          ),
        ),
      ),
    );
  }
}
