/// Photo analysis on a small thumbnail: perceptual hash, sharpness, brightness.
///
/// The hash is the same dHash the desktop app uses (pccleaner/similar.py):
/// shrink to 9x8 grey pixels and record whether each pixel is brighter than
/// its right neighbour. Copies, resized or re-saved versions and burst shots
/// end up only a few bits apart.
library;

import 'dart:math' as math;
import 'dart:typed_data';

import 'package:image/image.dart' as img;

import 'models.dart';

/// Longest side of the thumbnail the scanner asks the phone for.
const int thumbSide = 256;

/// Analyse an encoded thumbnail (JPEG/PNG). Returns null if it cannot be read.
ImageInfo? analyzeEncoded(Uint8List bytes) {
  final decoded = img.decodeImage(bytes);
  if (decoded == null || decoded.width < 9 || decoded.height < 8) return null;
  final w = decoded.width, h = decoded.height;
  final grey = Uint8List(w * h);
  var k = 0;
  for (var y = 0; y < h; y++) {
    for (var x = 0; x < w; x++) {
      final p = decoded.getPixel(x, y);
      // ITU-R 601 luma, as Pillow's "L" mode.
      grey[k++] = ((p.r * 299 + p.g * 587 + p.b * 114) ~/ 1000).clamp(0, 255);
    }
  }
  return analyzeGrey(grey, w, h);
}

/// Analyse raw grey pixels (row-major, one byte per pixel).
ImageInfo analyzeGrey(Uint8List grey, int w, int h) {
  return ImageInfo(
    dhash: dhashGrey(grey, w, h),
    sharpness: laplacianVariance(grey, w, h),
    brightness: meanBrightness(grey),
    tiny: tinyGrey(grey, w, h),
  );
}

const int tinySide = 16;

/// 16x16 box-filtered grey copy (256 bytes).
Uint8List tinyGrey(Uint8List grey, int w, int h) {
  final small = _resizeArea(grey, w, h, tinySide, tinySide);
  return Uint8List.fromList([for (final v in small) v.round().clamp(0, 255)]);
}

/// Pearson correlation of two tiny images, -1..1. Insensitive to overall
/// brightness and contrast changes (exposure differences between shots).
double correlation(Uint8List a, Uint8List b) {
  if (a.length != b.length || a.isEmpty) return 0;
  final n = a.length;
  var ma = 0.0, mb = 0.0;
  for (var i = 0; i < n; i++) {
    ma += a[i];
    mb += b[i];
  }
  ma /= n;
  mb /= n;
  var sab = 0.0, saa = 0.0, sbb = 0.0;
  for (var i = 0; i < n; i++) {
    final da = a[i] - ma, db = b[i] - mb;
    sab += da * db;
    saa += da * da;
    sbb += db * db;
  }
  if (saa < 1e-9 || sbb < 1e-9) {
    // A flat image (all one colour): only similar to another flat one of
    // about the same brightness.
    return (saa < 1e-9 && sbb < 1e-9 && (ma - mb).abs() < 8) ? 1 : 0;
  }
  return sab / math.sqrt(saa * sbb);
}

/// 64-bit difference hash from grey pixels.
int dhashGrey(Uint8List grey, int w, int h) {
  final small = _resizeArea(grey, w, h, 9, 8);
  var bits = 0;
  for (var row = 0; row < 8; row++) {
    for (var col = 0; col < 8; col++) {
      bits = (bits << 1) |
          (small[row * 9 + col] > small[row * 9 + col + 1] ? 1 : 0);
    }
  }
  return bits;
}

/// Box-filter downscale (each output pixel is the mean of its source area).
List<double> _resizeArea(Uint8List src, int w, int h, int ow, int oh) {
  final out = List<double>.filled(ow * oh, 0);
  for (var oy = 0; oy < oh; oy++) {
    final y0 = oy * h / oh, y1 = (oy + 1) * h / oh;
    for (var ox = 0; ox < ow; ox++) {
      final x0 = ox * w / ow, x1 = (ox + 1) * w / ow;
      var sum = 0.0, area = 0.0;
      for (var y = y0.floor(); y < y1.ceil() && y < h; y++) {
        final wy = math.min(y + 1.0, y1) - math.max(y.toDouble(), y0);
        if (wy <= 0) continue;
        for (var x = x0.floor(); x < x1.ceil() && x < w; x++) {
          final wx = math.min(x + 1.0, x1) - math.max(x.toDouble(), x0);
          if (wx <= 0) continue;
          sum += src[y * w + x] * wx * wy;
          area += wx * wy;
        }
      }
      out[oy * ow + ox] = area == 0 ? 0 : sum / area;
    }
  }
  return out;
}

/// Variance of the 4-neighbour Laplacian. Sharp edges give large values,
/// blur flattens them. Measured on the thumbnail, so values are comparable
/// between photos of any resolution.
double laplacianVariance(Uint8List g, int w, int h) {
  if (w < 3 || h < 3) return 0;
  var n = 0;
  var sum = 0.0, sumSq = 0.0;
  for (var y = 1; y < h - 1; y++) {
    for (var x = 1; x < w - 1; x++) {
      final i = y * w + x;
      final v = (g[i - 1] + g[i + 1] + g[i - w] + g[i + w] - 4 * g[i]).toDouble();
      sum += v;
      sumSq += v * v;
      n++;
    }
  }
  final mean = sum / n;
  return sumSq / n - mean * mean;
}

double meanBrightness(Uint8List g) {
  if (g.isEmpty) return 0;
  var s = 0;
  for (final v in g) {
    s += v;
  }
  return s / g.length;
}

int hamming(int a, int b) {
  var x = a ^ b;
  var c = 0;
  while (x != 0) {
    x &= x - 1;
    c++;
  }
  return c;
}
