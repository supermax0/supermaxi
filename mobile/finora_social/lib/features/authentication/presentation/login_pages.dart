import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../core/api/api_client.dart';
import '../../../core/theme/app_colors.dart';
import '../data/auth_controller.dart';

class PhoneLoginPage extends ConsumerStatefulWidget {
  const PhoneLoginPage({super.key, this.returnTo = '/home'});

  final String returnTo;

  @override
  ConsumerState<PhoneLoginPage> createState() => _PhoneLoginPageState();
}

class _PhoneLoginPageState extends ConsumerState<PhoneLoginPage> {
  final _phoneCtrl = TextEditingController();

  @override
  void dispose() {
    _phoneCtrl.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    final phone = _phoneCtrl.text.trim();
    final deviceId = await ref.read(deviceIdProvider.future);
    final ok = await ref.read(authControllerProvider.notifier).loginWithPhone(
          phone: phone,
          deviceId: deviceId,
        );
    if (!mounted) return;
    if (ok) context.go(widget.returnTo);
  }

  @override
  Widget build(BuildContext context) {
    final auth = ref.watch(authControllerProvider);
    return Scaffold(
      backgroundColor: AppColors.softWhite,
      body: SafeArea(
        child: Stack(
          children: [
            Positioned(
              top: -90,
              left: -70,
              child: Container(
                width: 240,
                height: 240,
                decoration: const BoxDecoration(
                  shape: BoxShape.circle,
                  gradient: RadialGradient(
                    colors: [Color(0x55D9A441), Color(0x00D9A441)],
                  ),
                ),
              ),
            ),
            ListView(
              padding: const EdgeInsets.fromLTRB(22, 12, 22, 24),
              children: [
                Align(
                  alignment: Alignment.centerRight,
                  child: IconButton.filledTonal(
                    tooltip: 'رجوع',
                    onPressed: () => context.go('/home'),
                    icon: const Icon(Icons.arrow_forward_rounded),
                  ),
                ),
                const SizedBox(height: 38),
                Container(
                  width: 72,
                  height: 72,
                  margin: const EdgeInsets.symmetric(horizontal: 118),
                  decoration: BoxDecoration(
                    color: AppColors.primaryDark,
                    borderRadius: BorderRadius.circular(24),
                    boxShadow: const [
                      BoxShadow(
                          color: Color(0x33000000),
                          blurRadius: 24,
                          offset: Offset(0, 10)),
                    ],
                  ),
                  child: const Icon(Icons.shopping_bag_rounded,
                      color: AppColors.goldAccent, size: 34),
                ),
                const SizedBox(height: 24),
                Text(
                  'أهلاً بك في Finora',
                  textAlign: TextAlign.center,
                  style: Theme.of(context).textTheme.headlineSmall?.copyWith(
                        color: AppColors.primaryDark,
                        fontWeight: FontWeight.w800,
                      ),
                ),
                const SizedBox(height: 8),
                Text(
                  'أدخل رقم هاتفك فقط لإكمال الشراء وحفظ طلباتك',
                  textAlign: TextAlign.center,
                  style: Theme.of(context)
                      .textTheme
                      .bodyLarge
                      ?.copyWith(color: const Color(0xFF6D6B66)),
                ),
                const SizedBox(height: 36),
                TextField(
                  controller: _phoneCtrl,
                  autofocus: true,
                  decoration: const InputDecoration(
                    labelText: 'رقم الهاتف',
                    hintText: '07XX XXX XXXX',
                    prefixIcon: Icon(Icons.phone_rounded),
                  ),
                  keyboardType: TextInputType.phone,
                  textDirection: TextDirection.ltr,
                  textInputAction: TextInputAction.done,
                  onSubmitted: (_) => _submit(),
                ),
                if (auth.error != null) ...[
                  const SizedBox(height: 12),
                  Container(
                    padding: const EdgeInsets.all(12),
                    decoration: BoxDecoration(
                      color: const Color(0xFFFFECEC),
                      borderRadius: BorderRadius.circular(14),
                    ),
                    child: Text(auth.error!,
                        style: const TextStyle(color: AppColors.error)),
                  ),
                ],
                const SizedBox(height: 20),
                FilledButton.icon(
                  onPressed: auth.isLoading ? null : _submit,
                  icon: auth.isLoading
                      ? const SizedBox(
                          height: 20,
                          width: 20,
                          child: CircularProgressIndicator(strokeWidth: 2),
                        )
                      : const Icon(Icons.arrow_back_rounded),
                  label: const Text('متابعة'),
                ),
                const SizedBox(height: 16),
                TextButton(
                  onPressed: () => context.go('/home'),
                  child: const Text('متابعة التصفح كضيف'),
                ),
                const SizedBox(height: 12),
                const Text(
                  'دخول مباشر على جهازك، بدون كلمة مرور أو رمز تحقق.',
                  textAlign: TextAlign.center,
                  style: TextStyle(fontSize: 12, color: Color(0xFF85827A)),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }
}

class OtpVerifyPage extends ConsumerStatefulWidget {
  const OtpVerifyPage({
    super.key,
    required this.phone,
    this.returnTo = '/home',
  });

  final String phone;
  final String returnTo;

  @override
  ConsumerState<OtpVerifyPage> createState() => _OtpVerifyPageState();
}

class _OtpVerifyPageState extends ConsumerState<OtpVerifyPage> {
  final _codeCtrl = TextEditingController();

  @override
  void dispose() {
    _codeCtrl.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    final deviceId = await ref.read(deviceIdProvider.future);
    final ok = await ref.read(authControllerProvider.notifier).verifyOtp(
          phone: widget.phone,
          code: _codeCtrl.text.trim(),
          deviceId: deviceId,
        );
    if (!mounted) return;
    if (ok) context.go(widget.returnTo);
  }

  @override
  Widget build(BuildContext context) {
    final auth = ref.watch(authControllerProvider);
    return Scaffold(
      appBar: AppBar(title: const Text('رمز التحقق')),
      body: SafeArea(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Text('أدخل الرمز المرسل إلى ${widget.phone}'),
              const SizedBox(height: 24),
              TextField(
                controller: _codeCtrl,
                decoration: const InputDecoration(labelText: 'رمز OTP'),
                keyboardType: TextInputType.number,
                maxLength: 6,
                onSubmitted: (_) => _submit(),
              ),
              if (auth.error != null) ...[
                const SizedBox(height: 8),
                Text(auth.error!,
                    style: const TextStyle(color: AppColors.error)),
              ],
              const Spacer(),
              FilledButton(
                onPressed: auth.isLoading ? null : _submit,
                child: auth.isLoading
                    ? const SizedBox(
                        height: 22,
                        width: 22,
                        child: CircularProgressIndicator(strokeWidth: 2),
                      )
                    : const Text('تأكيد الدخول'),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
