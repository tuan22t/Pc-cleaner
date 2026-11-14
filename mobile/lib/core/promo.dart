/// The four businesses shown in "Khám phá", read from assets/promo/promo.json
/// (the same file the desktop app uses).
library;

import 'dart:convert';

class Place {
  Place({
    required this.id,
    required this.name,
    required this.tagline,
    required this.address,
    required this.phone,
    required this.image,
    required this.website,
    required this.maps,
    required this.facebook,
  });

  final String id;
  final String name;
  final Map<String, String> tagline;
  final String address;
  final String phone;
  final String image;
  final String website;
  final String maps;
  final String facebook;

  String taglineFor(String lang) => tagline[lang] ?? tagline['vi'] ?? '';

  /// Digits only, for the dialler.
  String get telUri => 'tel:${phone.replaceAll(RegExp(r'[^0-9+]'), '')}';

  /// Website link tagged so Google Analytics on the website can count
  /// visits coming from the app. No data about the user is added.
  String websiteFor(String placement) => withUtm(website, placement);

  static Place fromJson(Map<String, dynamic> j) {
    final links = (j['links'] as Map?)?.cast<String, dynamic>() ?? {};
    return Place(
      id: j['id'] as String,
      name: j['name'] as String,
      tagline: ((j['tagline'] as Map?) ?? {}).map((k, v) => MapEntry('$k', '$v')),
      address: j['address'] as String? ?? '',
      phone: j['phone'] as String? ?? '',
      image: j['image'] as String? ?? '',
      website: links['website'] as String? ?? '',
      maps: links['maps'] as String? ?? '',
      facebook: links['facebook'] as String? ?? '',
    );
  }
}

class PromoData {
  PromoData(this.sponsor, this.places);
  final Map<String, String> sponsor;
  final List<Place> places;

  String sponsorFor(String lang) => sponsor[lang] ?? sponsor['vi'] ?? '';

  static PromoData parse(String raw) {
    final j = jsonDecode(raw) as Map<String, dynamic>;
    return PromoData(
      ((j['sponsor'] as Map?) ?? {}).map((k, v) => MapEntry('$k', '$v')),
      [for (final p in (j['places'] as List? ?? [])) Place.fromJson(p as Map<String, dynamic>)],
    );
  }

  /// Rotates through the places, one per cleanup, so each gets its turn.
  Place pick(int counter) => places[counter % places.length];
}

String withUtm(String url, String placement) {
  if (url.isEmpty) return url;
  final u = Uri.parse(url);
  final q = Map<String, String>.from(u.queryParameters)
    ..['utm_source'] = 'pccleaner_android'
    ..['utm_medium'] = 'app'
    ..['utm_campaign'] = placement;
  return u.replace(queryParameters: q).toString();
}
