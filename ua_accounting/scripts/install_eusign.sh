#!/usr/bin/env bash
# Installs the ІІТ EUSignCP library (Linux x64) for the e-reporting provider «ІІТ».
# Safe to run again: it does nothing when the pinned version is already there.
# No root is needed. Files go to $UA_EUSIGN_HOME (default /home/frappe/data/eusign):
#   lib/  the SDK libraries (euscp.so and its modules)     ca/  CACertificates.p7b, CAs.json (+ the .Test files)
# See docs/regulatory-update-process.md ("Бібліотека ІІТ EUSignCP").
set -euo pipefail

EUSIGN_HOME="${UA_EUSIGN_HOME:-/home/frappe/data/eusign}"
BASE_URL="https://iit.com.ua/download/productfiles"
ARCHIVE="euswi.64.tar"
# Pinned build (published by ІІТ 2026-10-23). Use UA_EUSIGN_SHA256=skip to take a newer build on purpose.
ARCHIVE_SHA256="${UA_EUSIGN_SHA256:-a7abdba3ac4fca556067df445053073c8cfb3a057d5b6ba6e9e48228e2731d21}"
VERSION="euswi.64.tar, ІІТ build of 2026-10-23, sha256 ${ARCHIVE_SHA256}"

if [ -f "$EUSIGN_HOME/lib/euscp.so" ] && [ -f "$EUSIGN_HOME/VERSION" ] && [ -z "${UA_EUSIGN_FORCE:-}" ]; then
  echo "EUSignCP is installed: $(cat "$EUSIGN_HOME/VERSION")"
  exit 0
fi

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

fetch() { curl -fsSL --retry 3 --max-time 600 -o "$work/$1" "$BASE_URL/$1"; }

echo "Downloading $ARCHIVE ..."
fetch "$ARCHIVE"
if [ "$ARCHIVE_SHA256" != "skip" ]; then
  echo "$ARCHIVE_SHA256  $work/$ARCHIVE" | sha256sum -c -
else
  VERSION="euswi.64.tar, ІІТ build downloaded $(date -u +%F), sha256 $(sha256sum "$work/$ARCHIVE" | cut -d' ' -f1)"
fi

mkdir -p "$work/x" "$EUSIGN_HOME/lib" "$EUSIGN_HOME/ca"
tar -xf "$work/$ARCHIVE" -C "$work/x" opt/iit/eu/sw
cp -a "$work/x/opt/iit/eu/sw/." "$EUSIGN_HOME/lib/"
rm -f "$EUSIGN_HOME/lib/install.sh" "$EUSIGN_HOME/lib/uninstall.sh"

# Lists of accredited CAs (КНЕДП): production and test.
for f in CAs.json CACertificates.p7b CAs.Test.json CACertificates.Test.p7b; do
  fetch "$f"
  cp "$work/$f" "$EUSIGN_HOME/ca/$f"
done

echo "$VERSION" > "$EUSIGN_HOME/VERSION"
echo "EUSignCP installed to $EUSIGN_HOME"
