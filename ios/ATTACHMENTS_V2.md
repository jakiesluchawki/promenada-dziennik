# Attachment report v2 — unreleased candidate

This is a local implementation/review candidate. It is not deployed, and it is not
an iOS release. Do not publish school-derived blobs or run a fresh collection as
part of testing this change without separate, informed authorization.

## Why the format changes

The existing iOS reader accepts encrypted reports up to 25,000,000 bytes. The
read-only measurement of the existing production snapshot found 24,309,817 bytes,
zero removable exact attachment duplicates, and attachment records accounting for
18,117,022 of 18,232,271 plaintext bytes. Removing duplicate controls alone did
not recover any space in that snapshot. Raising the limit or silently removing
original attachments is not the repair.

The candidate keeps original attachment bytes in separate authenticated encrypted
blobs and keeps their references, decryption keys and private metadata inside the
encrypted report. Report encryption remains AES-256-GCM with the existing PBKDF2
settings. The decrypted new manifest has schema 2. Each attachment has its own
random AES-256-GCM key and nonce; its authenticated context binds audience,
principal, account, message, attachment index, original digest and original size.

## Bounds and byte preservation

- Report ciphertext limit: 25,000,000 bytes, unchanged.
- Original attachment limit: 8,000,000 bytes, unchanged from the collector.
- Pad before encryption to the next 65,536-byte bucket, at least one bucket,
  capped at 8,000,000 bytes. Padding is random; exact original length stays inside
  the encrypted manifest. Maximum blob size, including GCM tag: 8,000,016 bytes.
- Verify strict same-site path, response size, ciphertext digest, GCM tag and
  expected scope, then verify the original slice's size and SHA-256 digest.
- No file recompression, format conversion, metadata removal or PDF/image
  optimization. The decrypted original file is byte-for-byte identical.
- No cross-account or parent/student blob deduplication. Reuse is only within the
  same authenticated scope and after verifying the original bytes and blob.

## Metadata privacy difference

The old format exposed one public ciphertext size per report and its update
history. Separate encrypted blobs also expose their count, bucketed sizes,
creation/reuse history and timing. Their names are opaque hashes of randomized
ciphertext, not hashes of plaintext or original filenames. True names, exact
original lengths, keys, digests and the reference list remain encrypted.

Opaque filenames do not provide access control. The repository is public, so its
file tree and history can enumerate ciphertext blobs even if the website does not
list a directory. A recipient without the report password cannot read the
reference manifest or derive the random blob keys, but this metadata difference
must be explained and approved before publishing real school-derived blobs.

## Migration and compatibility

New parent readers prefer `report.v2.enc.json`; new student readers prefer their
own `students/<principal>.v2.enc.json`. A missing v2 endpoint (404) permits legacy
endpoint fallback. A malformed, unauthorized or corrupt present v2 report does
not permit network downgrade to v1.

A new writer prepares and verifies all blobs before replacing the manifest.
Collection, freshness checks and publication verification use v2 when present, so
freezing the legacy snapshot cannot cause repeated collection or lose archived
messages. Publication verification checks referenced blobs as well as the report.

When a full legacy inline report still fits, both formats can be updated. When it
exceeds the unchanged limit, retain the last valid v1 snapshot rather than
presenting incomplete data as current. Old installed clients therefore retain
access to their last compatible report and need an updated app for new v2 data.
Do not describe that old snapshot as a fresh collection.

## Offline and logout

The iOS report remains encrypted at rest and excludes its cache from backup.
Attachment ciphertext is cached with iOS file protection and excluded from backup.
An attachment is available offline only after its encrypted bytes have previously
been downloaded; receiving a manifest does not download every attachment.
Uncached offline attachments must show an actionable error, not an empty file.

Logout cancels/invalidates pending loads and clears both report and attachment
caches. Late download completions must not recreate a cache or a share sheet.
The existing native share flow temporarily writes the original file under full
file protection and removes temporary shares on replacement/logout.

## Retention and storage

The initial candidate keeps old ciphertext blobs so existing/cached report
versions do not break. Unchanged attachments can reuse their authenticated blobs;
new or changed files add storage. There is no automatic deletion and no aggregate
retained-storage ceiling in this initial design. Per-file and per-manifest bounds
are enforced; total repository/history storage can grow. Before release, agree a
retention/monitoring policy and hosting budget. Never garbage-collect old blobs
merely because a newer report no longer references them without an approved
policy covering older/offline readers and repository history.

## Release gates

1. Complete Python, browser and cross-language synthetic tests and independent
   security/compatibility review. Shared vectors include Unicode, slash,
   quote/backslash and student scope cases.
2. Build and run native iOS tests on a supported Mac/Xcode environment. Linux
   source review and browser tests are not native runtime verification.
3. Test parent/student isolation, migration, offline/cache, bounded transport,
   attachment sharing, cancellation/logout and malformed/tampered input on iPhone
   and iPad. Preserve local read/done/priority marks.
4. Obtain explicit approval for the metadata/privacy difference, publication of
   actual school-derived blobs, deployment and new Internal Only TestFlight build.
   Use existing credentials through authorized routes only.
5. Publish readers and format changes in a coordinated, reversible rollout;
   verify actual public report and blob availability. Do not start a production
   collection or claim the live incident fixed from synthetic tests alone.

The repository's documented native process uses `ios/scripts/sync-web.py`,
iPhone/iPad simulator tests, `ios/scripts/archive-candidate.sh`, signing and an
Internal Only TestFlight upload. The current cloud preparation environment has no
Swift compiler or Xcode. Native build, signing, distribution and device validation
remain unperformed here.

### Reproducible native checks

On an authorized Mac with Xcode, from the repository root:

```sh
sh ios/tests/run-attachment-contract-tests.sh
xcodebuild -project ios/Promenada.xcodeproj -scheme Mahbrus \
  -configuration Debug -sdk iphonesimulator \
  -destination 'generic/platform=iOS Simulator' \
  -derivedDataPath /tmp/mahbrus-v2-build CODE_SIGNING_ALLOWED=NO build
```

The first command compiles actual production crypto/bridge helpers and tests the
shared synthetic padded vectors. It intentionally excludes the iOS store actor,
file protection and UI; the unsigned simulator build type-checks the whole app
but does not exercise runtime behavior. The candidate CI contains the same two
secret-free checks. It must not be run remotely until publishing/testing the
larger candidate is authorized. Device/simulator UI and lifecycle testing remains
a separate gate even when these two checks pass.
