/// Runtime config for the mobile API client.
abstract final class AppConfig {
  /// Override via `--dart-define=API_BASE_URL=https://host`
  static const String apiBaseUrl = String.fromEnvironment(
    'API_BASE_URL',
    defaultValue: 'https://www.finora.company',
  );

  /// Override via `--dart-define=TENANT_SLUG=super`
  static const String tenantSlug = String.fromEnvironment(
    'TENANT_SLUG',
    defaultValue: 'super',
  );

  static String? validationError({required bool releaseMode}) {
    final uri = Uri.tryParse(apiBaseUrl);
    if (uri == null || !uri.hasScheme || !uri.hasAuthority) {
      return 'API_BASE_URL must be provided as an absolute URL.';
    }
    if (releaseMode && uri.scheme.toLowerCase() != 'https') {
      return 'Release builds require an HTTPS API_BASE_URL.';
    }
    if (tenantSlug.trim().isEmpty) {
      return 'TENANT_SLUG must be provided.';
    }
    return null;
  }
}
