import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../api/api_client.dart';
import '../di/providers.dart';
import '../features/feature_flags.dart';
import '../storage/token_storage.dart';

class PhoneBootstrapSettings {
  const PhoneBootstrapSettings({
    this.missedCallFollowupMinutes = 30,
    this.companyName,
    this.provinces = const [
      'بغداد',
      'البصرة',
      'نينوى',
      'أربيل',
      'النجف',
      'كربلاء',
      'ذي قار',
      'السليمانية',
      'دهوك',
      'كركوك',
      'ديالى',
      'الأنبار',
      'صلاح الدين',
      'واسط',
      'بابل',
      'القادسية',
      'ميسان',
      'المثنى',
    ],
    this.primaryProvince = 'بغداد',
  });

  final int missedCallFollowupMinutes;
  final String? companyName;
  final List<String> provinces;
  final String primaryProvince;
}

final phoneBootstrapProvider =
    StateNotifierProvider<PhoneBootstrapController, PhoneBootstrapSettings>(
  (ref) => PhoneBootstrapController(
    api: ref.watch(apiClientProvider),
    storage: ref.watch(tokenStorageProvider),
    flags: ref.read(featureFlagsProvider.notifier),
  ),
);

class PhoneBootstrapController extends StateNotifier<PhoneBootstrapSettings> {
  PhoneBootstrapController({
    required ApiClient api,
    required TokenStorage storage,
    required FeatureFlagsController flags,
  })  : _api = api,
        _storage = storage,
        _flags = flags,
        super(const PhoneBootstrapSettings()) {
    _restore();
  }

  final ApiClient _api;
  final TokenStorage _storage;
  final FeatureFlagsController _flags;

  Future<void> _restore() async {
    final m = await _storage.readFollowupMinutes();
    if (m != null && (m == 5 || m == 15 || m == 30 || m == 60)) {
      state = PhoneBootstrapSettings(missedCallFollowupMinutes: m);
    }
  }

  Future<void> setFollowupMinutes(int minutes) async {
    if (minutes != 5 && minutes != 15 && minutes != 30 && minutes != 60) {
      minutes = 30;
    }
    await _storage.saveFollowupMinutes(minutes);
    state = PhoneBootstrapSettings(
      missedCallFollowupMinutes: minutes,
      companyName: state.companyName,
      provinces: state.provinces,
      primaryProvince: state.primaryProvince,
    );
  }

  Future<void> refresh() async {
    try {
      final res = await _api.get('/api/phone/v1/bootstrap');
      final settings = res['settings'];
      var minutes = 30;
      if (settings is Map) {
        minutes = (settings['missed_call_followup_minutes'] as num?)?.toInt() ??
            30;
      }
      if (minutes != 5 && minutes != 15 && minutes != 30 && minutes != 60) {
        minutes = 30;
      }
      final branding = res['branding'];
      final company =
          branding is Map ? branding['company_name']?.toString() : null;
      final rawProvinces = settings is Map ? settings['provinces'] : null;
      final provinces = rawProvinces is List
          ? rawProvinces
              .map((e) => e.toString().trim())
              .where((e) => e.isNotEmpty)
              .toList()
          : state.provinces;
      final primary = settings is Map
          ? settings['primary_province']?.toString().trim()
          : null;
      await _storage.saveFollowupMinutes(minutes);
      final ff = res['feature_flags'];
      if (ff is Map) {
        await _flags.applyFromBootstrap(Map<String, dynamic>.from(ff));
      }
      state = PhoneBootstrapSettings(
        missedCallFollowupMinutes: minutes,
        companyName: company,
        provinces: provinces.isEmpty ? state.provinces : provinces,
        primaryProvince: (primary == null || primary.isEmpty)
            ? state.primaryProvince
            : primary,
      );
    } catch (_) {
      // Keep last known / default flags from secure storage.
    }
  }
}
