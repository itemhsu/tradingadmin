#!/bin/bash
# Developer ID sign an .app when signing secrets are present; else ad-hoc sign.
#   usage: codesign_app.sh <App.app>
# env (all optional — absent => ad-hoc fallback):
#   MACOS_CERT_P12       base64 of a "Developer ID Application" .p12
#   MACOS_CERT_PASSWORD  password for that .p12
#   MACOS_SIGN_IDENTITY  identity string (optional; auto-detected otherwise)
set -uo pipefail

APP="${1:?usage: codesign_app.sh <App.app>}"
ENT="$(cd "$(dirname "$0")" && pwd)/entitlements.plist"
[ -d "$APP" ] || { echo "no such app bundle: $APP" >&2; exit 1; }

if [ -z "${MACOS_CERT_P12:-}" ]; then
  echo "== no signing cert -> ad-hoc sign (Gatekeeper will warn on first launch) =="
  codesign --force --deep --sign - "$APP" || true
  exit 0
fi

set -e
echo "== Developer ID sign =="
KEYCHAIN="build.keychain"
KPW="$(uuidgen)"
CERT="$(mktemp /tmp/cert.XXXXXX.p12)"
printf '%s' "$MACOS_CERT_P12" | base64 --decode > "$CERT"

security create-keychain -p "$KPW" "$KEYCHAIN"
security set-keychain-settings -lut 21600 "$KEYCHAIN"
security unlock-keychain -p "$KPW" "$KEYCHAIN"
security import "$CERT" -k "$KEYCHAIN" -P "${MACOS_CERT_PASSWORD:-}" \
  -T /usr/bin/codesign -T /usr/bin/security
security set-key-partition-list -S apple-tool:,apple:,codesign: -s -k "$KPW" "$KEYCHAIN" >/dev/null
# make the build keychain searchable alongside the existing ones
security list-keychains -d user -s "$KEYCHAIN" \
  $(security list-keychains -d user | sed 's/"//g')
rm -f "$CERT"

IDENT="${MACOS_SIGN_IDENTITY:-}"
if [ -z "$IDENT" ]; then
  IDENT="$(security find-identity -v -p codesigning "$KEYCHAIN" \
    | awk -F'"' '/Developer ID Application/{print $2; exit}')"
fi
[ -n "$IDENT" ] || { echo "no Developer ID Application identity in the imported cert" >&2; exit 1; }
echo "signing with: $IDENT"

codesign --deep --force --options runtime --timestamp \
  --entitlements "$ENT" --sign "$IDENT" "$APP"
codesign --verify --deep --strict --verbose=2 "$APP"
echo "== signed OK =="
