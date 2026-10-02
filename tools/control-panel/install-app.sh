#!/usr/bin/env bash
# Builds ComplianceWatch.app (the control panel) on the Desktop, or in the directory given as $1.
set -euo pipefail

REPO="$(cd "$(dirname "$0")/../.." && pwd)"
DEST="${1:-$HOME/Desktop}"
APP="$DEST/ComplianceWatch.app"

rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"

cat > "$APP/Contents/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>ComplianceWatch</string>
  <key>CFBundleDisplayName</key><string>ComplianceWatch</string>
  <key>CFBundleIdentifier</key><string>local.compliancewatch.control-panel</string>
  <key>CFBundleExecutable</key><string>ComplianceWatch</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleVersion</key><string>1</string>
  <key>NSHighResolutionCapable</key><true/>
</dict>
</plist>
PLIST

cat > "$APP/Contents/MacOS/ComplianceWatch" <<LAUNCHER
#!/bin/bash
export PATH="/opt/homebrew/bin:/usr/local/bin:\$PATH"
cd "$REPO" || exit 1
[ -x .venv/bin/python ] || uv sync --all-packages >/dev/null 2>&1
exec .venv/bin/python tools/control-panel/control_panel.py
LAUNCHER
chmod +x "$APP/Contents/MacOS/ComplianceWatch"

echo "built $APP"
