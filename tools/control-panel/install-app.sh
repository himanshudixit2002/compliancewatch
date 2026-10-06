#!/usr/bin/env bash
# Builds ComplianceWatch.app (the control panel) on the Desktop, or in the directory given as $1.
#
# The bundle carries its own copy of the panel (Contents/Resources/control-panel): the window it
# opens is the one installed, whatever branch the checkout is on later. The launcher runs that
# copy in the checkout with the checkout's Python and CW_CONTROL_PANEL_REPO set to it. The
# checkout is the one this script sits in, or CW_CONTROL_PANEL_REPO when the script runs from a
# copy of the panel outside a checkout. Run it again (make control-panel-app) to update the app.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "${CW_CONTROL_PANEL_REPO:-$HERE/../..}" && pwd)"
DEST="${1:-$HOME/Desktop}"
APP="$DEST/ComplianceWatch.app"
PANEL="$APP/Contents/Resources/control-panel"

for file in control_panel.py panel_core.py; do
  [ -f "$HERE/$file" ] || { echo "error: $HERE has no $file to copy into the app"; exit 1; }
done
if [ ! -f "$REPO/Makefile" ] || [ ! -e "$REPO/.git" ]; then
  echo "error: $REPO is not a ComplianceWatch checkout; set CW_CONTROL_PANEL_REPO=<checkout>"
  exit 1
fi

rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$PANEL"
cp "$HERE/control_panel.py" "$HERE/panel_core.py" "$PANEL/"

# What the window shows as its build: when, and the commit the files came from (with +changes
# when the panel's files differ from it), or the files' own hash outside a commit.
commit="$(git --no-optional-locks -C "$HERE" rev-parse --short HEAD 2>/dev/null || true)"
if [ -n "$commit" ] && [ -n "$(git --no-optional-locks -C "$HERE" status --porcelain -- control_panel.py panel_core.py 2>/dev/null)" ]; then
  commit="$commit+changes"
fi
if command -v shasum >/dev/null 2>&1; then digest() { shasum -a 256; }; else digest() { sha256sum; }; fi
files="$(cat "$HERE/control_panel.py" "$HERE/panel_core.py" | digest | cut -c1-12)"
{
  echo "built=$(date '+%Y-%m-%d %H:%M')"
  echo "commit=${commit:-none}"
  echo "files=$files"
  echo "source=$HERE"
} > "$PANEL/BUILD"

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

repo_quoted="$(printf '%q' "$REPO")"
cat > "$APP/Contents/MacOS/ComplianceWatch" <<LAUNCHER
#!/bin/bash
# Opens the control panel this bundle carries, on the checkout it was built for.
panel="\$(cd "\$(dirname "\$0")/../Resources/control-panel" && pwd)" || exit 1
export PATH="/opt/homebrew/bin:/usr/local/bin:\$PATH"
export CW_CONTROL_PANEL_REPO=$repo_quoted
cd "\$CW_CONTROL_PANEL_REPO" || exit 1
[ -x .venv/bin/python ] || uv sync --all-packages >/dev/null 2>&1
exec .venv/bin/python "\$panel/control_panel.py"
LAUNCHER
chmod +x "$APP/Contents/MacOS/ComplianceWatch"

echo "built $APP"
echo "  panel $(sed -n 's/^built=//p' "$PANEL/BUILD"), commit ${commit:-none}, files $files, for $REPO"
