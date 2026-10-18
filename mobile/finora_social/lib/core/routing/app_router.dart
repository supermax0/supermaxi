import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../features/ai/presentation/ai_chat_page.dart';
import '../../features/authentication/data/auth_controller.dart';
import '../../features/authentication/presentation/login_pages.dart';
import '../../features/cart/presentation/cart_pages.dart';
import '../../features/notifications/presentation/notifications_page.dart';
import '../../features/profile/presentation/profile_pages.dart';
import '../../features/rewards/presentation/rewards_page.dart';
import '../../features/shell/presentation/main_shell.dart';
import '../../features/store/presentation/product_detail_page.dart';
import '../../features/store/presentation/store_page.dart';
import '../../features/video_feed/presentation/video_feed_page.dart';

final appRouterProvider = Provider<GoRouter>((ref) {
  return GoRouter(
    initialLocation: '/home',
    refreshListenable: _AuthListenable(ref),
    redirect: (context, state) {
      final auth = ref.read(authControllerProvider);
      final loggingIn = state.matchedLocation.startsWith('/auth');
      final protected = state.matchedLocation == '/cart' ||
          state.matchedLocation.startsWith('/cart/') ||
          state.matchedLocation == '/ai' ||
          state.matchedLocation == '/rewards' ||
          state.matchedLocation.startsWith('/profile/') ||
          state.matchedLocation == '/store/favorites';
      if (!auth.isAuthenticated && protected) {
        final target = Uri.encodeQueryComponent(state.uri.toString());
        return '/auth/phone?returnTo=$target';
      }
      if (auth.isAuthenticated && loggingIn) {
        return _safeReturnTo(state.uri.queryParameters['returnTo']);
      }
      return null;
    },
    routes: [
      GoRoute(
        path: '/auth/phone',
        builder: (context, state) => PhoneLoginPage(
          returnTo: _safeReturnTo(state.uri.queryParameters['returnTo']),
        ),
      ),
      GoRoute(
        path: '/cart',
        builder: (context, state) => const CartPage(),
        routes: [
          GoRoute(
            path: 'checkout',
            builder: (context, state) => const CheckoutPage(),
          ),
        ],
      ),
      StatefulShellRoute.indexedStack(
        builder: (context, state, navigationShell) {
          return MainShellPage(navigationShell: navigationShell);
        },
        branches: [
          StatefulShellBranch(
            routes: [
              GoRoute(
                path: '/home',
                builder: (context, state) => const VideoFeedPage(),
              ),
            ],
          ),
          StatefulShellBranch(
            routes: [
              GoRoute(
                path: '/store',
                builder: (context, state) => const StorePage(),
                routes: [
                  GoRoute(
                    path: 'favorites',
                    builder: (context, state) => const FavoritesPage(),
                  ),
                  GoRoute(
                    path: 'product/:id',
                    builder: (context, state) {
                      final id =
                          int.tryParse(state.pathParameters['id'] ?? '') ?? 0;
                      return ProductDetailPage(productId: id);
                    },
                  ),
                ],
              ),
            ],
          ),
          StatefulShellBranch(
            routes: [
              GoRoute(
                path: '/ai',
                builder: (context, state) => const AiChatPage(),
              ),
            ],
          ),
          StatefulShellBranch(
            routes: [
              GoRoute(
                path: '/rewards',
                builder: (context, state) => const RewardsPage(),
              ),
            ],
          ),
          StatefulShellBranch(
            routes: [
              GoRoute(
                path: '/profile',
                builder: (context, state) => const ProfileTabPage(),
                routes: [
                  GoRoute(
                    path: 'orders',
                    builder: (context, state) => const OrdersListPage(),
                    routes: [
                      GoRoute(
                        path: ':id',
                        builder: (context, state) {
                          final id =
                              int.tryParse(state.pathParameters['id'] ?? '') ??
                                  0;
                          return OrderDetailPage(orderId: id);
                        },
                      ),
                    ],
                  ),
                  GoRoute(
                    path: 'notifications',
                    builder: (context, state) => const NotificationsPage(),
                  ),
                  GoRoute(
                    path: 'edit',
                    builder: (context, state) => const EditProfilePage(),
                  ),
                  GoRoute(
                    path: 'addresses',
                    builder: (context, state) => const AddressesPage(),
                  ),
                  GoRoute(
                    path: 'liked-videos',
                    builder: (context, state) => const LikedVideosPage(),
                  ),
                  GoRoute(
                    path: 'saved-videos',
                    builder: (context, state) => const SavedVideosPage(),
                  ),
                ],
              ),
            ],
          ),
        ],
      ),
    ],
  );
});

String _safeReturnTo(String? value) {
  final target = (value ?? '').trim();
  if (target.startsWith('/') && !target.startsWith('/auth')) return target;
  return '/home';
}

class _AuthListenable extends ChangeNotifier {
  _AuthListenable(this._ref) {
    _ref.listen<AuthState>(
        authControllerProvider, (_, __) => notifyListeners());
  }

  final Ref _ref;
}
