import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../features/auth/data/app_lock_controller.dart';
import '../features/auth/data/auth_controller.dart';
import '../features/auth/data/permissions_gate.dart';
import '../features/auth/presentation/app_lock_page.dart';
import '../features/auth/presentation/login_page.dart';
import '../features/contacts/presentation/contacts_page.dart';
import '../features/customers/presentation/customer_detail_page.dart';
import '../features/dashboard/presentation/dashboard_page.dart';
import '../features/overlay/data/active_call_controller.dart';
import '../features/overlay/presentation/overlay_ui.dart';
import '../features/overlay/presentation/unclassified_calls_page.dart';
import '../features/orders/presentation/order_drafts_page.dart';
import '../features/permissions_wizard/presentation/permissions_wizard_page.dart';
import '../features/search/presentation/advanced_search_page.dart';
import '../domain/entities/entities.dart';
import '../core/ui/finora_ui.dart';
import 'shell.dart';

final _rootKey = GlobalKey<NavigatorState>();

class _AuthListenable extends ChangeNotifier {
  _AuthListenable(this._ref) {
    _ref.listen(authControllerProvider, (_, __) => notifyListeners());
    _ref.listen(appLockProvider, (_, __) => notifyListeners());
    _ref.listen(permissionsGateProvider, (_, __) => notifyListeners());
  }
  final Ref _ref;
}

final goRouterProvider = Provider<GoRouter>((ref) {
  final authListenable = _AuthListenable(ref);
  return GoRouter(
    navigatorKey: _rootKey,
    initialLocation: '/phone',
    refreshListenable: authListenable,
    redirect: (context, state) {
      final auth = ref.read(authControllerProvider);
      final lock = ref.read(appLockProvider);
      final perms = ref.read(permissionsGateProvider);
      final loc = state.matchedLocation;
      final loggingIn = loc == '/login';
      final onPerms = loc == '/permissions';
      final onLock = loc == '/lock';
      if (auth.status == AuthStatus.unknown) return null;
      if (auth.status == AuthStatus.unauthenticated) {
        return loggingIn ? null : '/login';
      }
      if (loggingIn) return '/permissions';
      // Enforce wizard until marked done (skip for live call surfaces).
      if (perms.ready &&
          !perms.done &&
          !onPerms &&
          loc != '/after-call' &&
          loc != '/tools') {
        return '/permissions';
      }
      if (onPerms) return null;
      // Soft lock — allow after-call / tools through for call workflow.
      if (lock.ready &&
          lock.locked &&
          loc != '/after-call' &&
          loc != '/tools' &&
          !onLock) {
        return '/lock';
      }
      if (onLock && (!lock.enabled || !lock.locked)) {
        return '/phone';
      }
      return null;
    },
    routes: [
      GoRoute(path: '/login', builder: (_, __) => const LoginPage()),
      GoRoute(
        path: '/permissions',
        builder: (_, __) => const PermissionsWizardPage(),
      ),
      GoRoute(path: '/lock', builder: (_, __) => const AppLockPage()),
      GoRoute(
        path: '/after-call',
        builder: (_, __) => const AfterCallPage(),
      ),
      GoRoute(
        path: '/tools',
        builder: (_, state) => FinoraScaffold(
          body: SafeArea(
            child: InCallToolsSheet(
              fullPage: true,
              focus: state.uri.queryParameters['focus'],
            ),
          ),
        ),
      ),
      GoRoute(
        path: '/search',
        builder: (_, __) => const AdvancedSearchPage(),
      ),
      GoRoute(
        path: '/unclassified-calls',
        builder: (_, __) => const UnclassifiedCallsPage(),
      ),
      GoRoute(
        path: '/order-drafts',
        builder: (_, __) => const OrderDraftsPage(),
      ),
      GoRoute(
        path: '/dashboard',
        builder: (_, __) => const DashboardPage(),
      ),
      GoRoute(
        path: '/favorites',
        builder: (_, __) => const ContactsPage(),
      ),
      GoRoute(
        path: '/customer-detail',
        builder: (context, state) {
          final c = state.extra;
          if (c is! CustomerEntity) {
            return const Scaffold(
              body: Center(child: Text('زبون غير موجود')),
            );
          }
          return CustomerDetailPage(customer: c);
        },
      ),
      StatefulShellRoute.indexedStack(
        builder: (context, state, navigationShell) {
          return AppShell(navigationShell: navigationShell);
        },
        branches: [
          StatefulShellBranch(routes: [
            GoRoute(path: '/phone', builder: (_, __) => ShellBranches.phone),
          ]),
          StatefulShellBranch(routes: [
            GoRoute(path: '/history', builder: (_, __) => ShellBranches.history),
          ]),
          StatefulShellBranch(routes: [
            GoRoute(
              path: '/customers',
              builder: (_, __) => ShellBranches.customers,
            ),
          ]),
          StatefulShellBranch(routes: [
            GoRoute(path: '/tasks', builder: (_, __) => ShellBranches.tasks),
          ]),
          StatefulShellBranch(routes: [
            GoRoute(
              path: '/settings',
              builder: (_, __) => ShellBranches.settings,
            ),
          ]),
        ],
      ),
    ],
  );
});

/// Ensures active call controller is created app-wide.
final callBootstrapProvider = Provider<void>((ref) {
  ref.watch(activeCallProvider);
});
