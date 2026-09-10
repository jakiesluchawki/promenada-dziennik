#!/bin/zsh
# Prepare an unsigned release archive for inspection. This does not upload.
set -eu
IOS_DIR="$(cd "$(dirname "$0")/.." && pwd)"
: "${MAHBRUS_BUILD_DIR:?Set MAHBRUS_BUILD_DIR to a directory outside the repository}"
mkdir -p "$MAHBRUS_BUILD_DIR"
python3 "$IOS_DIR/scripts/sync-web.py"
xcodebuild -project "$IOS_DIR/Promenada.xcodeproj" -scheme Mahbrus -configuration Release \
 -destination 'generic/platform=iOS' -derivedDataPath "$MAHBRUS_BUILD_DIR/ReleaseData" \
 -archivePath "$MAHBRUS_BUILD_DIR/Mahbrus-1.0.0-1.xcarchive" \
 CODE_SIGNING_ALLOWED=NO archive
