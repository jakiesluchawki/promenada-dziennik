#!/bin/zsh
set -eu
IOS_DIR="$(cd "$(dirname "$0")/.." && pwd)"
: "${MAHBRUS_BUILD_DIR:?Set MAHBRUS_BUILD_DIR to a directory outside the repository}"
: "${MAHBRUS_SIMULATOR_ID:?Set MAHBRUS_SIMULATOR_ID to a booted iPhone simulator UUID}"
mkdir -p "$MAHBRUS_BUILD_DIR"
python3 "$IOS_DIR/scripts/sync-web.py"
xcodebuild -project "$IOS_DIR/Promenada.xcodeproj" -scheme Mahbrus -configuration Debug \
 -destination "platform=iOS Simulator,id=$MAHBRUS_SIMULATOR_ID" \
 -derivedDataPath "$MAHBRUS_BUILD_DIR/DerivedData" \
 -resultBundlePath "$MAHBRUS_BUILD_DIR/TestResults-$(date +%Y%m%d-%H%M%S).xcresult" \
 -skip-testing:PromenadaUITests/PromenadaUITests/testTabletLayout \
 CODE_SIGN_IDENTITY=- ONLY_ACTIVE_ARCH=YES test
