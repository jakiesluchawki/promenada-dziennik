#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
if ! command -v xcrun >/dev/null 2>&1; then
  echo "NOT RUN: macOS with Xcode command-line tools is required for this Swift helper check" >&2
  exit 2
fi
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT HUP INT TERM
# Extract production helpers unchanged. The app's actor and iOS filesystem code
# are excluded from this macOS-only helper test, and remain an iOS release gate.
sed '/^actor ReportStore {/,$d' "$ROOT/ios/Promenada/ReportStore.swift" > "$TMP/ReportHelpers.swift"
cat >> "$TMP/ReportHelpers.swift" <<'SWIFT'
enum ReportStore {
    static let siteRoot = URL(string: "https://jakiesluchawki.github.io/promenada-dziennik/")!
}
SWIFT
xcrun swiftc -parse-as-library "$TMP/ReportHelpers.swift" "$ROOT/ios/tests/AttachmentV2ContractMain.swift" -o "$TMP/attachment-contract-tests"
"$TMP/attachment-contract-tests" "$ROOT/tests/fixtures/attachment_aad_vectors.json"
