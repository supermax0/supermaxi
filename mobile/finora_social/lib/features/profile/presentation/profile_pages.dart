import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../core/api/api_client.dart';
import '../../../core/errors/api_exception.dart';
import '../../../core/theme/app_colors.dart';
import '../data/profile_controller.dart';

class EditProfilePage extends ConsumerStatefulWidget {
  const EditProfilePage({super.key});

  @override
  ConsumerState<EditProfilePage> createState() => _EditProfilePageState();
}

class _EditProfilePageState extends ConsumerState<EditProfilePage> {
  final _name = TextEditingController();
  final _email = TextEditingController();
  final _city = TextEditingController();
  final _address = TextEditingController();
  bool _filled = false;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) async {
      await ref.read(profileControllerProvider.notifier).load();
      if (!mounted) return;
      final s = ref.read(profileControllerProvider);
      _name.text = s.name;
      _email.text = s.email;
      _city.text = s.city;
      _address.text = s.address;
      setState(() => _filled = true);
    });
  }

  @override
  void dispose() {
    _name.dispose();
    _email.dispose();
    _city.dispose();
    _address.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final state = ref.watch(profileControllerProvider);
    if (!_filled && state.name.isNotEmpty) {
      _name.text = state.name;
      _email.text = state.email;
      _city.text = state.city;
      _address.text = state.address;
      _filled = true;
    }
    return Scaffold(
      appBar: AppBar(title: const Text('تعديل الملف')),
      body: ListView(
        padding: const EdgeInsets.all(20),
        children: [
          if (state.error != null)
            Padding(
              padding: const EdgeInsets.only(bottom: 12),
              child: Text(state.error!,
                  style: const TextStyle(color: AppColors.error)),
            ),
          TextField(
              controller: _name,
              decoration: const InputDecoration(labelText: 'الاسم')),
          const SizedBox(height: 12),
          TextField(
              controller: _email,
              decoration: const InputDecoration(labelText: 'البريد')),
          const SizedBox(height: 12),
          TextField(
              controller: _city,
              decoration: const InputDecoration(labelText: 'المدينة')),
          const SizedBox(height: 12),
          TextField(
            controller: _address,
            decoration: const InputDecoration(labelText: 'العنوان'),
            maxLines: 2,
          ),
          const SizedBox(height: 20),
          FilledButton(
            onPressed: state.isLoading
                ? null
                : () async {
                    final ok = await ref
                        .read(profileControllerProvider.notifier)
                        .saveProfile(
                          name: _name.text.trim(),
                          email: _email.text.trim(),
                          city: _city.text.trim(),
                          address: _address.text.trim(),
                        );
                    if (ok && context.mounted) {
                      ScaffoldMessenger.of(context).showSnackBar(
                        const SnackBar(content: Text('تم حفظ الملف')),
                      );
                      context.pop();
                    }
                  },
            child: state.isLoading
                ? const SizedBox(
                    width: 18,
                    height: 18,
                    child: CircularProgressIndicator(strokeWidth: 2),
                  )
                : const Text('حفظ'),
          ),
        ],
      ),
    );
  }
}

class AddressesPage extends ConsumerStatefulWidget {
  const AddressesPage({super.key});

  @override
  ConsumerState<AddressesPage> createState() => _AddressesPageState();
}

class _AddressesPageState extends ConsumerState<AddressesPage> {
  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      ref.read(profileControllerProvider.notifier).load();
    });
  }

  Future<void> _showAddSheet() async {
    final label = TextEditingController(text: 'المنزل');
    final city = TextEditingController();
    final address = TextEditingController();
    final phone = TextEditingController();
    final ok = await showModalBottomSheet<bool>(
      context: context,
      isScrollControlled: true,
      builder: (ctx) {
        return Padding(
          padding: EdgeInsets.only(
            left: 20,
            right: 20,
            top: 20,
            bottom: MediaQuery.of(ctx).viewInsets.bottom + 20,
          ),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              TextField(
                  controller: label,
                  decoration: const InputDecoration(labelText: 'التسمية')),
              TextField(
                  controller: city,
                  decoration: const InputDecoration(labelText: 'المدينة')),
              TextField(
                controller: address,
                decoration:
                    const InputDecoration(labelText: 'العنوان التفصيلي'),
              ),
              TextField(
                  controller: phone,
                  decoration: const InputDecoration(labelText: 'الهاتف')),
              const SizedBox(height: 12),
              FilledButton(
                onPressed: () => Navigator.pop(ctx, true),
                child: const Text('إضافة'),
              ),
            ],
          ),
        );
      },
    );
    if (ok == true) {
      await ref.read(profileControllerProvider.notifier).addAddress({
        'label': label.text.trim(),
        'city': city.text.trim(),
        'address': address.text.trim(),
        'phone': phone.text.trim(),
        'is_default': true,
      });
    }
    label.dispose();
    city.dispose();
    address.dispose();
    phone.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final state = ref.watch(profileControllerProvider);
    return Scaffold(
      appBar: AppBar(title: const Text('عناويني')),
      floatingActionButton: FloatingActionButton(
        onPressed: _showAddSheet,
        child: const Icon(Icons.add),
      ),
      body: state.isLoading
          ? const Center(child: CircularProgressIndicator())
          : ListView.separated(
              padding: const EdgeInsets.all(16),
              itemCount: state.addresses.length,
              separatorBuilder: (_, __) => const Divider(),
              itemBuilder: (context, i) {
                final a = state.addresses[i];
                return ListTile(
                  title: Text('${a.label}${a.isDefault ? ' · افتراضي' : ''}'),
                  subtitle: Text('${a.city}\n${a.address}'),
                  isThreeLine: true,
                  trailing: IconButton(
                    icon: const Icon(Icons.delete_outline,
                        color: AppColors.error),
                    onPressed: () => ref
                        .read(profileControllerProvider.notifier)
                        .deleteAddress(a.id),
                  ),
                );
              },
            ),
    );
  }
}

class LikedVideosPage extends ConsumerStatefulWidget {
  const LikedVideosPage({super.key});

  @override
  ConsumerState<LikedVideosPage> createState() => _LikedVideosPageState();
}

class _LikedVideosPageState extends ConsumerState<LikedVideosPage> {
  List<Map<String, dynamic>> _items = const [];
  bool _loading = true;
  String? _error;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) => _load());
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final data = await ref
          .read(apiClientProvider)
          .get('/api/mobile/v1/profile/liked-videos');
      setState(() {
        _items = ((data['items'] as List<dynamic>?) ?? [])
            .whereType<Map<String, dynamic>>()
            .toList();
        _loading = false;
      });
    } on ApiException catch (e) {
      setState(() {
        _error = e.message;
        _loading = false;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('فيديوهات أعجبتني')),
      body: _loading
          ? const Center(child: CircularProgressIndicator())
          : _error != null
              ? Center(
                  child: Text(_error!,
                      style: const TextStyle(color: AppColors.error)))
              : _items.isEmpty
                  ? const Center(child: Text('لا توجد فيديوهات بعد'))
                  : ListView.separated(
                      padding: const EdgeInsets.all(16),
                      itemCount: _items.length,
                      separatorBuilder: (_, __) => const Divider(),
                      itemBuilder: (context, i) {
                        final v = _items[i];
                        return ListTile(
                          leading: const Icon(Icons.favorite,
                              color: AppColors.error),
                          title: Text(
                              (v['title'] as String?)?.isNotEmpty == true
                                  ? v['title'] as String
                                  : 'فيديو'),
                          subtitle: Text('${v['likes_count'] ?? 0} إعجاب'),
                          onTap: () => context.go('/home'),
                        );
                      },
                    ),
    );
  }
}

class SavedVideosPage extends ConsumerStatefulWidget {
  const SavedVideosPage({super.key});

  @override
  ConsumerState<SavedVideosPage> createState() => _SavedVideosPageState();
}

class _SavedVideosPageState extends ConsumerState<SavedVideosPage> {
  List<Map<String, dynamic>> _items = const [];
  bool _loading = true;
  String? _error;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) => _load());
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final data = await ref
          .read(apiClientProvider)
          .get('/api/mobile/v1/profile/saved-videos');
      setState(() {
        _items = ((data['items'] as List<dynamic>?) ?? [])
            .whereType<Map<String, dynamic>>()
            .toList();
        _loading = false;
      });
    } on ApiException catch (e) {
      setState(() {
        _error = e.message;
        _loading = false;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('فيديوهات محفوظة')),
      body: _loading
          ? const Center(child: CircularProgressIndicator())
          : _error != null
              ? Center(
                  child: Text(_error!,
                      style: const TextStyle(color: AppColors.error)))
              : _items.isEmpty
                  ? const Center(child: Text('لا توجد فيديوهات محفوظة'))
                  : ListView.separated(
                      padding: const EdgeInsets.all(16),
                      itemCount: _items.length,
                      separatorBuilder: (_, __) => const Divider(),
                      itemBuilder: (context, i) {
                        final v = _items[i];
                        return ListTile(
                          leading: const Icon(Icons.bookmark,
                              color: AppColors.mutedGold),
                          title: Text(
                              (v['title'] as String?)?.isNotEmpty == true
                                  ? v['title'] as String
                                  : 'فيديو'),
                          subtitle: Text('${v['saves_count'] ?? 0} حفظ'),
                          onTap: () => context.go('/home'),
                        );
                      },
                    ),
    );
  }
}
