#!/bin/bash
# Notarize + staple a .dmg when notary secrets are present; else a no-op.
#   usage: notarize_dmg.sh <out.dmg>
# env (all optional — absent => skip, DMG ships un-notarized):
#   MACOS_NOTARY_APPLE_ID   your Apple ID email
#   MACOS_NOTARY_TEAM_ID    10-char Team ID
#   MACOS_NOTARY_PASSWORD   app-specific password
set -uo pipefail

DMG="${1:?usage: notarize_dmg.sh <out.dmg>}"
[ -f "$DMG" ] || { echo "no such dmg: $DMG" >&2; exit 1; }

if [ -z "${MACOS_NOTARY_APPLE_ID:-}" ] || [ -z "${MACOS_NOTARY_PASSWORD:-}" ] \
   || [ -z "${MACOS_NOTARY_TEAM_ID:-}" ]; then
  echo "== no notary creds -> skipping notarization (ships un-notarized) =="
  exit 0
fi

set -e
echo "== submitting $DMG to Apple notary (this can take a few minutes) =="
xcrun notarytool submit "$DMG" \
  --apple-id "$MACOS_NOTARY_APPLE_ID" \
  --team-id "$MACOS_NOTARY_TEAM_ID" \
  --password "$MACOS_NOTARY_PASSWORD" \
  --wait
xcrun stapler staple "$DMG"
xcrun stapler validate "$DMG"
echo "== notarized + stapled OK =="
