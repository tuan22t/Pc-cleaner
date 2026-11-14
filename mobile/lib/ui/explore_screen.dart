import 'package:material_ui/material_ui.dart';
import 'package:url_launcher/url_launcher.dart';

import '../core/promo.dart';
import '../i18n.dart';
import '../main.dart' show AppScope;

/// Opens a link in another app (dialler, maps, browser, Facebook). The app
/// itself has no Internet permission; Android hands the link over.
Future<void> openExternal(String url) async {
  if (url.isEmpty) return;
  try {
    await launchUrl(Uri.parse(url), mode: LaunchMode.externalApplication);
  } catch (_) {}
}

class ExploreScreen extends StatelessWidget {
  const ExploreScreen({super.key});

  @override
  Widget build(BuildContext context) {
    final s = AppScope.of(context);
    final p = s.promo;
    final t = Theme.of(context).textTheme;
    final cs = Theme.of(context).colorScheme;
    return Scaffold(
      appBar: AppBar(title: Text(tr('Khám phá'))),
      body: p == null
          ? const SizedBox.shrink()
          : ListView(
              padding: const EdgeInsets.fromLTRB(16, 4, 16, 24),
              children: [
                Text(tr('PC Cleaner miễn phí, không quảng cáo của bên thứ ba, nhờ sự tài trợ của {0}.', [p.sponsorFor(currentLang)]),
                    style: t.bodyMedium?.copyWith(color: cs.onSurfaceVariant)),
                const SizedBox(height: 12),
                for (final place in p.places) Padding(padding: const EdgeInsets.only(bottom: 14), child: PlaceCard(place: place)),
              ],
            ),
    );
  }
}

class PlaceCard extends StatelessWidget {
  const PlaceCard({super.key, required this.place});
  final Place place;

  static const _gradients = {
    'tananpalace-hotel': [Color(0xFF8C6A2F), Color(0xFFD9B566)],
    'tananpalace-wedding': [Color(0xFFB24A6B), Color(0xFFF2A7B8)],
    'zen-love-station': [Color(0xFF3A3F8F), Color(0xFF8E7CD6)],
    'zen-halong': [Color(0xFF1F6F8B), Color(0xFF7FC8D6)],
  };

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context).textTheme;
    final g = _gradients[place.id] ?? const [Color(0xFF2F6FED), Color(0xFF7FA7F5)];
    final fallback = DecoratedBox(
      decoration: BoxDecoration(gradient: LinearGradient(colors: g, begin: Alignment.topLeft, end: Alignment.bottomRight)),
      child: Center(child: Icon(place.id.contains('wedding') ? Icons.celebration_outlined : Icons.hotel_outlined, size: 54, color: Colors.white70)),
    );
    return Card(
      clipBehavior: Clip.antiAlias,
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        AspectRatio(
          aspectRatio: 1200 / 630,
          child: place.image.isEmpty
              ? fallback
              : Image.asset('assets/promo/${place.image}', fit: BoxFit.cover, errorBuilder: (_, _, _) => fallback),
        ),
        Padding(
          padding: const EdgeInsets.fromLTRB(16, 12, 16, 4),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text(place.name, style: t.titleMedium?.copyWith(fontWeight: FontWeight.w700)),
            const SizedBox(height: 4),
            Text(place.taglineFor(currentLang)),
            const SizedBox(height: 6),
            Row(children: [
              const Icon(Icons.place_outlined, size: 16),
              const SizedBox(width: 4),
              Expanded(child: Text(place.address, style: t.bodySmall)),
            ]),
          ]),
        ),
        Padding(padding: const EdgeInsets.fromLTRB(8, 4, 8, 10), child: PlaceActions(place: place, placement: 'kham_pha')),
      ]),
    );
  }
}

/// Call / Directions / Website / Fanpage buttons.
class PlaceActions extends StatelessWidget {
  const PlaceActions({super.key, required this.place, required this.placement, this.compact = false});
  final Place place;
  final String placement;
  final bool compact;

  @override
  Widget build(BuildContext context) {
    final items = [
      (Icons.call, tr('Gọi'), place.telUri),
      (Icons.directions, tr('Chỉ đường'), place.maps),
      (Icons.language, tr('Website'), place.websiteFor(placement)),
      (Icons.thumb_up_alt_outlined, tr('Fanpage'), place.facebook),
    ];
    return Wrap(
      spacing: 4,
      runSpacing: 0,
      children: [
        for (final (icon, label, url) in items)
          if (url.isNotEmpty)
            TextButton.icon(
              style: compact ? TextButton.styleFrom(visualDensity: VisualDensity.compact, padding: const EdgeInsets.symmetric(horizontal: 8)) : null,
              onPressed: () => openExternal(url),
              icon: Icon(icon, size: 18),
              label: Text(label),
            ),
      ],
    );
  }
}
