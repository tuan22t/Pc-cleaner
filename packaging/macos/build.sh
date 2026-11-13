#!/bin/bash
# Build "PC Cleaner.app" for both Intel and Apple-chip Macs (universal2) and pack it in a DMG.
#   packaging/macos/build.sh <version>
# Needs the universal2 Python from python.org (the CI job installs it). Pillow has
# no universal2 wheel, so its two wheels are fused with delocate.
# Signing and notarization run only when the Apple secrets are set:
#   MAC_SIGN_IDENTITY  "Developer ID Application: …" (certificate already in a keychain)
#   APPLE_ID, APPLE_TEAM_ID, APPLE_APP_PASSWORD  for notarytool
set -euo pipefail
VERSION="${1:?version}"
PY="${PYTHON:-/Library/Frameworks/Python.framework/Versions/3.12/bin/python3.12}"
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
BUILD="$ROOT/build/mac"
rm -rf "$BUILD" dist/PCCleaner.app "dist/PC Cleaner.app"
mkdir -p "$BUILD/wheels"

"$PY" -m venv "$BUILD/venv"
VPY="$BUILD/venv/bin/python"
"$VPY" -m pip install -q --upgrade pip
"$VPY" -m pip install -q "pyinstaller>=6.0" "pywebview>=5.0" delocate

PILLOW="$(grep -i '^Pillow' requirements.txt | head -1)"
for plat in macosx_11_0_arm64 macosx_10_13_x86_64; do
  "$VPY" -m pip download -q --only-binary=:all: --no-deps --platform "$plat" --python-version 3.12 \
    -d "$BUILD/wheels/$plat" "$PILLOW"
done
"$BUILD/venv/bin/delocate-merge" "$BUILD"/wheels/macosx_11_0_arm64/*.whl "$BUILD"/wheels/macosx_10_13_x86_64/*.whl -w "$BUILD/wheels/universal2"
"$VPY" -m pip install -q --force-reinstall --no-deps "$BUILD"/wheels/universal2/*.whl

"$VPY" -m PyInstaller --noconfirm --windowed --target-arch universal2 --name PCCleaner \
  --osx-bundle-identifier com.pccleaner.app \
  --add-data "pccleaner/web:pccleaner/web" run.py

APP="dist/PC Cleaner.app"
mv dist/PCCleaner.app "$APP"
PLIST="$APP/Contents/Info.plist"
plutil -replace CFBundleName -string "PC Cleaner" "$PLIST"
plutil -replace CFBundleDisplayName -string "PC Cleaner" "$PLIST"
plutil -replace CFBundleShortVersionString -string "$VERSION" "$PLIST"
plutil -replace CFBundleVersion -string "$VERSION" "$PLIST"
plutil -replace LSMinimumSystemVersion -string "11.0" "$PLIST"

# Every program file in the bundle must contain both architectures.
bad=0
while IFS= read -r -d '' f; do
  if file "$f" | grep -q "Mach-O"; then
    archs="$(lipo -archs "$f" 2>/dev/null || true)"
    if [[ "$archs" != *x86_64* || "$archs" != *arm64* ]]; then echo "not universal: $f ($archs)"; bad=1; fi
  fi
done < <(find "$APP" -type f -print0)
[ "$bad" = 0 ] || { echo "Some program files are not universal"; exit 1; }
echo "All program files contain x86_64 and arm64."

if [ -n "${MAC_SIGN_IDENTITY:-}" ]; then
  codesign --force --deep --options runtime --timestamp --sign "$MAC_SIGN_IDENTITY" "$APP"
else
  codesign --force --deep --sign - "$APP"   # ad-hoc: runs, but Gatekeeper warns on other Macs
fi
codesign --verify --deep --strict "$APP"

DMG="dist/PCCleaner-$VERSION.dmg"
STAGE="$BUILD/dmg"
rm -rf "$STAGE" "$DMG"; mkdir -p "$STAGE"
ditto "$APP" "$STAGE/PC Cleaner.app"
ln -s /Applications "$STAGE/Applications"
hdiutil create -volname "PC Cleaner" -srcfolder "$STAGE" -format UDZO -ov "$DMG"

if [ -n "${MAC_SIGN_IDENTITY:-}" ]; then
  codesign --force --timestamp --sign "$MAC_SIGN_IDENTITY" "$DMG"
  if [ -n "${APPLE_ID:-}" ]; then
    xcrun notarytool submit "$DMG" --apple-id "$APPLE_ID" --team-id "$APPLE_TEAM_ID" --password "$APPLE_APP_PASSWORD" --wait
    xcrun stapler staple "$DMG"
    spctl --assess --type open --context context:primary-signature -v "$DMG"
  fi
fi
echo "Built $DMG"
