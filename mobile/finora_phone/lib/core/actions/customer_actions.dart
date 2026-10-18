import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:url_launcher/url_launcher.dart';

import '../../data/mappers/phone_normalize.dart';
import '../di/providers.dart';

/// Shared customer quick actions (call / WhatsApp).
abstract final class CustomerActions {
  static Future<bool> dial(
    WidgetRef ref,
    String phone, {
    int? simSlot,
  }) async {
    final number = normalizePhone(phone);
    if (number.isEmpty) return false;
    return ref.read(permissionsChannelProvider).dialNumber(
          number,
          simSlot: simSlot,
        );
  }

  static Future<bool> openWhatsApp(String phone) async {
    final digits = normalizePhone(phone);
    if (digits.isEmpty) return false;
    var wa = digits;
    if (wa.startsWith('0') && wa.length >= 10) {
      wa = '964${wa.substring(1)}';
    }
    final uri = Uri.parse('https://wa.me/$wa');
    if (await canLaunchUrl(uri)) {
      return launchUrl(uri, mode: LaunchMode.externalApplication);
    }
    return false;
  }
}
