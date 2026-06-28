#!/usr/bin/env bash
# Host-side install for otp-autofill. Browser side is manual (see README).
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
NM_DIR="$HOME/.mozilla/native-messaging-hosts"

echo "==> chmod native host"
chmod 755 "$HERE/native_host.py"

echo "==> install native-messaging manifest"
mkdir -p "$NM_DIR"
ln -sf "$HERE/otp_autofill.json" "$NM_DIR/otp_autofill.json"

echo "==> package extension -> $HERE/otp-autofill.xpi"
( cd "$HERE/extension" && zip -q -r -FS "$HERE/otp-autofill.xpi" . -x '*.DS_Store' )

echo "==> state dir"
mkdir -p "$HOME/.cache/otp-fill"
chmod 700 "$HOME/.cache/otp-fill"

cat <<'EOF'

Host side done. Browser side (Firefox Nightly), one time:

 1. about:config -> set  xpinstall.signatures.required = false
 2. about:addons -> gear -> "Install Add-on From File" -> pick otp-autofill.xpi
    (or about:debugging -> This Firefox -> Load Temporary Add-on -> manifest.json
     for a no-pref, non-persistent test)
 3. The extension id MUST stay  otp-autofill@yoshkoz.local  (matches the native
    manifest's allowed_extensions).

Test: trigger any email-login that sends a code, stay on the code page, watch it
fill + submit. Debug log: ~/.cache/otp-fill/host.log
EOF
